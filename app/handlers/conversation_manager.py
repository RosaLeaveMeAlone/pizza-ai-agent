from loguru import logger
from typing import Dict, Optional
from app.models.conversation import ConversationContext, ConversationState, CustomerInfo
from app.services.langchain_service import langchain_service
from app.services.pizza_api_service import pizza_api
from app.services.polly_service import polly_service

class ConversationManager:
    """Manages conversation flow and state"""
    
    def __init__(self):
        self.active_conversations: Dict[str, ConversationContext] = {}
    
    async def process_customer_message(
        self, 
        call_sid: str, 
        customer_message: str
    ) -> Dict[str, str]:
        """
        Process customer message and return TwiML response
        
        Args:
            call_sid: Twilio call identifier
            customer_message: What customer said
            
        Returns:
            Dict with 'action', 'message', and 'twiml'
        """
        try:
            context = await self._get_or_create_context(call_sid)
            context.last_customer_message = customer_message
            
            if not context.catalog:
                context.catalog = await pizza_api.get_catalog()
                if not context.catalog:
                    return await self._error_response("No pude cargar el menú. Intenta más tarde.")
            
            ai_result = await langchain_service.process_customer_input(
                customer_message, 
                context.to_dict(),
                context.catalog,
                call_sid
            )
            
            context = ConversationContext.from_dict(ai_result["context"])
            context.call_sid = call_sid
            self.active_conversations[call_sid] = context
            
            return await self._execute_action(context, ai_result)
            
        except Exception as e:
            logger.error(f"Error processing customer message: {str(e)}")
            return await self._error_response("Disculpa, tuve un problema técnico.")
    
    async def _get_or_create_context(self, call_sid: str) -> ConversationContext:
        """Get existing conversation or create new one"""
        if call_sid in self.active_conversations:
            return self.active_conversations[call_sid]
        
        context = ConversationContext(call_sid=call_sid)
        
        cart_data = await pizza_api.create_cart()
        if cart_data:
            context.cart_token = cart_data["cart_token"]
            logger.info(f"Created cart {context.cart_token} for call {call_sid}")
        
        self.active_conversations[call_sid] = context
        return context
    
    async def _execute_action(self, context: ConversationContext, ai_result: Dict) -> Dict[str, str]:
        """Execute action determined by AI"""
        action = ai_result["action"]
        response_text = ai_result["response_text"]
        
        if action == "welcome":
            context.update_state(ConversationState.TAKING_ORDER)
            return await self._voice_response(response_text)
        
        elif action == "add_product":
            success = await self._add_product_to_cart(context, ai_result)
            if success:
                context.update_state(ConversationState.TAKING_ORDER)
                return await self._voice_response(response_text)
            else:
                return await self._voice_response("No pude agregar ese producto. ¿Puedes repetir tu pedido?")
        
        elif action == "confirm_cart":
            cart_summary = await self._get_cart_summary(context)
            full_message = f"{response_text} {cart_summary}"
            context.update_state(ConversationState.CONFIRMING_CART)
            return await self._voice_response(full_message)
        
        elif action == "collect_customer_info":
            context.update_state(ConversationState.COLLECTING_INFO)
            return await self._collect_customer_info(context, ai_result)
        
        elif action == "create_order":
            return await self._create_order(context)
        
        elif action == "clarification":
            context.increment_attempts()
            if context.attempts > 3:
                return await self._voice_response("Parece que tenemos dificultades. Te transfiero con un operador humano.")
            return await self._voice_response(response_text)
        
        else:  # error
            return await self._error_response(response_text)
    
    async def _add_product_to_cart(self, context: ConversationContext, ai_result: Dict) -> bool:
        """Add product to cart based on AI parsing"""
        try:
            product_name = ai_result.get("product")
            size_name = ai_result.get("size")
            quantity = ai_result.get("quantity", 1)
            
            if not product_name:
                return False
            
            # Find product in catalog
            product = await pizza_api.find_product_by_name(product_name, context.catalog)
            if not product:
                logger.warning(f"Product not found: {product_name}")
                return False
            
            product_id = product.get("id")  # We'll need to add ID to catalog
            pizza_size_id = None
            
            # Handle pizza size
            if size_name and "precios_por_tamaño" in product:
                pizza_sizes = await pizza_api.get_pizza_sizes(context.catalog)
                for size in pizza_sizes:
                    if size_name.lower() in size["name"].lower():
                        pizza_size_id = size.get("id")  # We'll need to add ID to catalog
                        break
            
            logger.info(f"Would add: {product_name} (size: {size_name}, qty: {quantity})")
            return True
            
        except Exception as e:
            logger.error(f"Error adding product to cart: {str(e)}")
            return False
    
    async def _get_cart_summary(self, context: ConversationContext) -> str:
        """Get human-readable cart summary"""
        try:
            if not context.cart_token:
                return "Tu carrito está vacío."
            
            cart_data = await pizza_api.get_cart(context.cart_token)
            if not cart_data or not cart_data.get("data", {}).get("items"):
                return "Tu carrito está vacío."
            
            items = cart_data["data"]["items"]
            total = cart_data["data"]["total"]
            
            summary = "En tu carrito tienes: "
            for item in items:
                product_name = item["product"]["name"]
                quantity = item["quantity"]
                price = item["subtotal"]
                summary += f"{quantity} {product_name} por ${price}, "
            
            summary = summary.rstrip(", ")
            summary += f". Total: ${total}."
            
            return summary
            
        except Exception as e:
            logger.error(f"Error getting cart summary: {str(e)}")
            return "No pude revisar tu carrito."
    
    async def _collect_customer_info(self, context: ConversationContext, ai_result: Dict) -> Dict[str, str]:
        """Collect customer information step by step"""
        response_text = ai_result["response_text"]
        
        # Parse customer info from the message
        customer_message = context.last_customer_message.strip()
        
        logger.info(f"Collecting info - Current state: name='{context.customer_info.name}', phone='{context.customer_info.phone}', address='{context.customer_info.address}'")
        logger.info(f"Customer message: '{customer_message}'")
        
        if not context.customer_info.name:
            # Extract name more intelligently
            if any(phrase in customer_message.lower() for phrase in ["me llamo", "soy", "mi nombre es"]):
                # Extract just the name part
                parts = customer_message.lower().split()
                name_index = 0
                if "llamo" in customer_message.lower():
                    name_index = parts.index("llamo") + 1
                elif "soy" in customer_message.lower():
                    name_index = parts.index("soy") + 1
                elif "es" in customer_message.lower():
                    name_index = parts.index("es") + 1
                
                if name_index < len(parts):
                    name = " ".join(customer_message.split()[name_index:]).strip()
                    context.customer_info.name = name
                    logger.info(f"Extracted name: '{name}'")
                    response_text = "Gracias. ¿Cuál es tu número de teléfono?"
                else:
                    response_text = "No pude entender tu nombre. ¿Puedes repetirlo?"
            else:
                # Assume the whole message is the name if no special phrases
                context.customer_info.name = customer_message
                logger.info(f"Assumed whole message as name: '{customer_message}'")
                response_text = "Gracias. ¿Cuál es tu número de teléfono?"
        
        elif not context.customer_info.phone:
            import re
            # Look for phone numbers (allow more flexibility)
            phone_match = re.search(r'\d{8,11}', customer_message.replace(" ", "").replace("-", ""))
            if phone_match:
                context.customer_info.phone = phone_match.group()
                logger.info(f"Extracted phone: '{context.customer_info.phone}'")
                response_text = "Perfecto. ¿Cuál es tu dirección de entrega?"
            else:
                response_text = "No pude entender tu teléfono. ¿Puedes repetir el número?"
        
        elif not context.customer_info.address:
            context.customer_info.address = customer_message
            logger.info(f"Extracted address: '{customer_message}'")
            response_text = "Excelente. Voy a confirmar tu pedido."
            context.update_state(ConversationState.CREATING_ORDER)
        
        return await self._voice_response(response_text)
    
    async def _create_order(self, context: ConversationContext) -> Dict[str, str]:
        """Create the final order"""
        try:
            if not context.is_customer_info_complete():
                return await self._voice_response("Necesito tu información completa para procesar el pedido.")
            
            order_result = await pizza_api.create_order(
                cart_token=context.cart_token,
                customer_name=context.customer_info.name,
                customer_phone=context.customer_info.phone,
                customer_address=context.customer_info.address,
                payment_method=context.customer_info.payment_method
            )
            
            if order_result:
                order_id = order_result["data"]["id"]
                view_url = order_result.get("view_url", "")
                
                response_text = f"""
                ¡Perfecto! Tu pedido número {order_id} ha sido confirmado.
                Puedes ver los detalles en: {view_url}
                Te llegará en aproximadamente 30 minutos.
                ¡Gracias por elegir Pizza Project!
                """
                
                context.update_state(ConversationState.ORDER_COMPLETE)
                return await self._voice_response(response_text, hangup=True)
            else:
                return await self._error_response("No pude procesar tu pedido. Intenta de nuevo.")
                
        except Exception as e:
            logger.error(f"Error creating order: {str(e)}")
            return await self._error_response("Hubo un problema al procesar tu pedido.")
    
    async def _voice_response(self, text: str, hangup: bool = False) -> Dict[str, str]:
        """Create voice response with TwiML"""
        
        audio_bytes = await polly_service.synthesize_speech(text)
        
        if hangup:
            twiml = f'<Response><Say language="es-ES">{text}</Say><Hangup/></Response>'
        else:
            twiml = f'''
            <Response>
                <Say language="es-ES">{text}</Say>
                <Gather input="speech" action="/voice/process-speech" method="POST" 
                        speechTimeout="5" language="es-ES">
                </Gather>
                <Say language="es-ES">No pude escucharte. ¿Puedes repetir?</Say>
                <Redirect>/voice/incoming</Redirect>
            </Response>
            '''
        
        return {
            "action": "voice_response",
            "message": text,
            "twiml": twiml
        }
    
    async def _error_response(self, message: str) -> Dict[str, str]:
        """Create error response"""
        twiml = f'''
        <Response>
            <Say language="es-ES">{message}</Say>
            <Hangup/>
        </Response>
        '''
        
        return {
            "action": "error",
            "message": message,
            "twiml": twiml
        }

conversation_manager = ConversationManager()
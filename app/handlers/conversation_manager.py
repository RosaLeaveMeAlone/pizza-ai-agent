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
            
            # Preserve the catalog when recreating context
            catalog = context.catalog
            context = ConversationContext.from_dict(ai_result["context"])
            context.call_sid = call_sid
            context.catalog = catalog
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
        
        logger.info(f"Executing action: {action} with ai_result: {ai_result}")
        
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
            # If customer info is incomplete, try to extract from the current message first
            if not context.is_customer_info_complete():
                logger.info(f"[CREATE_ORDER] Customer info incomplete, trying to extract from message: '{context.last_customer_message}'")
                
                # Temporarily switch to collecting info mode and extract data
                temp_ai_result = {"response_text": "Extrayendo información..."}
                temp_response = await self._collect_customer_info(context, temp_ai_result)
                
                # Check if we now have complete info
                if context.is_customer_info_complete():
                    logger.info(f"[CREATE_ORDER] Info extracted successfully, proceeding with order")
                    return await self._create_order(context)
                else:
                    logger.info(f"[CREATE_ORDER] Still missing info, asking for it")
                    context.update_state(ConversationState.COLLECTING_INFO)
                    return temp_response
            else:
                return await self._create_order(context)
        
        elif action == "clarification":
            # If we're collecting info, handle it as customer info collection
            if context.state == ConversationState.COLLECTING_INFO:
                return await self._collect_customer_info(context, ai_result)
            
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
            if size_name and "prices_by_size" in product:
                pizza_sizes = await pizza_api.get_pizza_sizes(context.catalog)
                for size in pizza_sizes:
                    if size_name.lower() in size["name"].lower():
                        pizza_size_id = size.get("id")
                        break
            
            # Actually add the product to cart
            success = await pizza_api.add_product_to_cart(
                cart_token=context.cart_token,
                product_id=product_id,
                quantity=quantity,
                pizza_size_id=pizza_size_id
            )
            
            if success:
                logger.info(f"Successfully added: {product_name} (id: {product_id}, size_id: {pizza_size_id}, qty: {quantity})")
                return True
            else:
                logger.error(f"Failed to add product {product_name} to cart")
                return False
            
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
        
        logger.info(f"[COLLECT_INFO] Current state: name='{context.customer_info.name}', phone='{context.customer_info.phone}', address='{context.customer_info.address}'")
        logger.info(f"[COLLECT_INFO] Customer message: '{customer_message}'")
        
        import re
        
        # Simple and direct extraction
        message_lower = customer_message.lower()
        
        # Extract name - look for common patterns
        if not context.customer_info.name:
            if "mi nombre es" in message_lower:
                name_part = customer_message.split("mi nombre es", 1)[1].split(",")[0].split(" y ")[0].strip()
                context.customer_info.name = name_part
                logger.info(f"[COLLECT_INFO] Extracted name: '{name_part}'")
            elif "me llamo" in message_lower:
                name_part = customer_message.split("me llamo", 1)[1].split(",")[0].split(" y ")[0].strip()
                context.customer_info.name = name_part
                logger.info(f"[COLLECT_INFO] Extracted name: '{name_part}'")
            elif "soy" in message_lower:
                name_part = customer_message.split("soy", 1)[1].split(",")[0].split(" y ")[0].strip()
                context.customer_info.name = name_part
                logger.info(f"[COLLECT_INFO] Extracted name: '{name_part}'")
        
        # Extract phone - look for numbers
        if not context.customer_info.phone:
            # Look for phone number patterns
            phone_match = re.search(r'(\d{3}\s*\d{2}\s*\d{2}|\d{7,11})', customer_message)
            if phone_match:
                phone = re.sub(r'[^\d]', '', phone_match.group(1))
                if len(phone) >= 7:
                    context.customer_info.phone = phone
                    logger.info(f"[COLLECT_INFO] Extracted phone: '{phone}'")
        
        # Extract address - look for address patterns
        if not context.customer_info.address:
            if "dirección" in message_lower:
                address_part = customer_message.split("dirección", 1)[1].replace("es", "", 1).replace(":", "", 1).strip()
                if address_part:
                    context.customer_info.address = address_part
                    logger.info(f"[COLLECT_INFO] Extracted address: '{address_part}'")
            elif "calle" in message_lower:
                # Find "calle" and take everything after it
                calle_index = message_lower.find("calle")
                address_part = customer_message[calle_index:].strip()
                context.customer_info.address = address_part
                logger.info(f"[COLLECT_INFO] Extracted address: '{address_part}'")
        
        # Log current state after extraction
        logger.info(f"[COLLECT_INFO] After extraction: name='{context.customer_info.name}', phone='{context.customer_info.phone}', address='{context.customer_info.address}'")
        
        # Check if we have all information
        if context.customer_info.name and context.customer_info.phone and context.customer_info.address:
            logger.info(f"[COLLECT_INFO] All info collected! Moving to order creation.")
            response_text = "Perfecto. Tengo toda tu información. Voy a procesar tu pedido."
            context.update_state(ConversationState.CREATING_ORDER)
        elif not context.customer_info.name:
            response_text = "Por favor, dime tu nombre."
        elif not context.customer_info.phone:
            response_text = "¿Cuál es tu número de teléfono?"
        elif not context.customer_info.address:
            response_text = "¿Cuál es tu dirección de entrega?"
        
        logger.info(f"[COLLECT_INFO] Response: '{response_text}'")
        return await self._voice_response(response_text)
    
    async def _create_order(self, context: ConversationContext) -> Dict[str, str]:
        """Create the final order"""
        try:
            logger.info(f"[CREATE_ORDER] Starting order creation")
            logger.info(f"[CREATE_ORDER] Customer info: name='{context.customer_info.name}', phone='{context.customer_info.phone}', address='{context.customer_info.address}'")
            logger.info(f"[CREATE_ORDER] Cart token: '{context.cart_token}'")
            
            if not context.is_customer_info_complete():
                logger.error(f"[CREATE_ORDER] Customer info incomplete!")
                return await self._voice_response("Necesito tu información completa para procesar el pedido.")
            
            logger.info(f"[CREATE_ORDER] Customer info complete, calling pizza_api.create_order")
            order_result = await pizza_api.create_order(
                cart_token=context.cart_token,
                customer_name=context.customer_info.name,
                customer_phone=context.customer_info.phone,
                customer_address=context.customer_info.address,
                payment_method=context.customer_info.payment_method
            )
            
            logger.info(f"[CREATE_ORDER] Order result: {order_result}")
            
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
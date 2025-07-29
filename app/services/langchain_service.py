from langchain_openai import ChatOpenAI
from langchain.prompts import ChatPromptTemplate, SystemMessagePromptTemplate, HumanMessagePromptTemplate, MessagesPlaceholder
from langchain.schema import BaseOutputParser
from langchain.memory import ConversationBufferMemory
from langchain.chains import ConversationChain
from loguru import logger
from app.config.settings import settings
from typing import Dict, List, Any
import re
import json


class PizzaOrderParser(BaseOutputParser):
    """Custom parser for pizza order responses"""
    
    def parse(self, text: str) -> Dict[str, Any]:
        """Parse AI response to extract action and parameters"""
        try:
            lines = text.strip().split('\n')
            
            action = "clarification"
            product = None
            size = None
            quantity = 1
            response_text = text
            
            for line in lines:
                line = line.strip()
                if line.startswith('[ACCIÓN:') or line.startswith('[ACTION:'):
                    action = line.split(':')[1].strip().rstrip(']')
                elif line.startswith('[PRODUCTO:') or line.startswith('[PRODUCT:'):
                    product = line.split(':')[1].strip().rstrip(']')
                elif line.startswith('[TAMAÑO:') or line.startswith('[SIZE:'):
                    size = line.split(':')[1].strip().rstrip(']')
                elif line.startswith('[CANTIDAD:') or line.startswith('[QUANTITY:'):
                    try:
                        quantity = int(line.split(':')[1].strip().rstrip(']'))
                    except ValueError:
                        quantity = 1
                elif line.startswith('[RESPUESTA:') or line.startswith('[RESPONSE:'):
                    response_text = line.split(':', 1)[1].strip().rstrip(']')
            
            return {
                "action": action,
                "response_text": response_text,
                "product": product,
                "size": size,
                "quantity": quantity
            }
            
        except Exception as e:
            logger.error(f"Error parsing AI response: {str(e)}")
            return {
                "action": "clarification",
                "response_text": "¿Puedes repetir tu pedido, por favor?",
                "product": None,
                "size": None,
                "quantity": 1
            }


class LangchainService:
    """Service for Langchain conversation management"""
    
    def __init__(self):
        self.llm = ChatOpenAI(
            model_name="gpt-3.5-turbo",
            temperature=0.7,
            max_tokens=400,
            openai_api_key=settings.openai_api_key
        )
        self.parser = PizzaOrderParser()
        self.memories: Dict[str, ConversationBufferMemory] = {}
        
    def _get_system_prompt_template(self, catalog: Dict) -> str:
        """Build system prompt template with catalog information"""
        
        products = catalog.get('data', {}).get('products', [])
        pizza_sizes = catalog.get('data', {}).get('pizza_sizes', [])
        
        products_text = "\\n".join([
            f"- {p['name']}: {p['description']} - Precio base: ${p['base_price']}"
            for p in products
        ])
        
        sizes_text = "\\n".join([
            f"- {s['name']}: {s['description']} - Multiplicador: {s['price_multiplier']}x"
            for s in pizza_sizes
        ])
        
        return f"""
Eres un asistente de IA para Pizza Project, especializado en tomar pedidos de pizza por teléfono.

PRODUCTOS DISPONIBLES:
{products_text}

TAMAÑOS DE PIZZA:
{sizes_text}

INSTRUCCIONES:
1. Saluda amablemente y pregunta qué quiere ordenar
2. Ayuda al cliente a elegir productos y tamaños
3. Confirma cada producto agregado al carrito
4. Al final, solicita datos del cliente: nombre, teléfono, dirección
5. Confirma el pedido completo antes de procesarlo
6. Sé amable, claro y eficiente

RESPONDE SIEMPRE EN ESPAÑOL y mantén las respuestas cortas para llamadas telefónicas.

Para cada respuesta, determina la ACCIÓN a realizar:
- "welcome": Saludo inicial
- "add_product": Agregar producto al carrito
- "confirm_cart": Mostrar contenido del carrito
- "collect_customer_info": Solicitar datos del cliente
- "create_order": Finalizar pedido
- "clarification": Pedir clarificación al cliente
- "error": Error o no entendido

FORMATO DE RESPUESTA:
[ACCIÓN: welcome/add_product/confirm_cart/collect_customer_info/create_order/clarification/error]
[PRODUCTO: nombre_del_producto] (solo si es add_product)
[TAMAÑO: nombre_del_tamaño] (solo si es pizza)
[CANTIDAD: número] (solo si es add_product)
[RESPUESTA: tu respuesta al cliente]
"""
        
    def _get_or_create_memory(self, call_sid: str) -> ConversationBufferMemory:
        """Get or create conversation memory for call"""
        if call_sid not in self.memories:
            self.memories[call_sid] = ConversationBufferMemory(
                return_messages=True,
                memory_key="chat_history"
            )
        return self.memories[call_sid]
    
    async def process_customer_input(
        self, 
        customer_message: str, 
        conversation_context: Dict,
        catalog: Dict,
        call_sid: str
    ) -> Dict:
        """
        Process customer input using Langchain
        
        Args:
            customer_message: What the customer said
            conversation_context: Current conversation state
            catalog: Pizza catalog for reference
            call_sid: Call identifier for memory management
            
        Returns:
            Dict with action, response_text, and context
        """
        try:
            memory = self._get_or_create_memory(call_sid)
            
            system_prompt = self._get_system_prompt_template(catalog)
            
            prompt = ChatPromptTemplate.from_messages([
                SystemMessagePromptTemplate.from_template(system_prompt),
                MessagesPlaceholder(variable_name="chat_history"),
                HumanMessagePromptTemplate.from_template("{input}")
            ])
            
            conversation = ConversationChain(
                llm=self.llm,
                prompt=prompt,
                memory=memory,
                verbose=True
            )
            
            response = await conversation.apredict(input=customer_message)
            logger.info(f"Langchain response: {response}")
            
            parsed_result = self.parser.parse(response)
            logger.info(f"Parsed result: {parsed_result}")
            
            updated_context = conversation_context.copy()
            if "conversation_history" not in updated_context:
                updated_context["conversation_history"] = []
            
            updated_context["conversation_history"].extend([
                {"role": "user", "content": customer_message},
                {"role": "assistant", "content": parsed_result["response_text"]}
            ])
            
            return {
                **parsed_result,
                "context": updated_context
            }
            
        except Exception as e:
            logger.error(f"Error processing with Langchain: {str(e)}")
            return {
                "action": "error",
                "response_text": "Disculpa, tuve un problema técnico. ¿Puedes repetir tu pedido?",
                "context": conversation_context,
                "product": None,
                "size": None,
                "quantity": 1
            }
    
    def clear_memory(self, call_sid: str):
        """Clear conversation memory for a call"""
        if call_sid in self.memories:
            del self.memories[call_sid]
            logger.info(f"Cleared Langchain memory for call {call_sid}")

langchain_service = LangchainService()
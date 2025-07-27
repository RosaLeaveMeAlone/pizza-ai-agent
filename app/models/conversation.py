from pydantic import BaseModel
from typing import Optional, Dict, List, Any
from enum import Enum

class ConversationState(str, Enum):
    WELCOME = "welcome"
    TAKING_ORDER = "taking_order"
    CONFIRMING_CART = "confirming_cart"
    COLLECTING_INFO = "collecting_info"
    CREATING_ORDER = "creating_order"
    ORDER_COMPLETE = "order_complete"
    ERROR = "error"

class CustomerInfo(BaseModel):
    name: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    payment_method: str = "efectivo"

class ConversationContext(BaseModel):
    call_sid: Optional[str] = None
    state: ConversationState = ConversationState.WELCOME
    cart_token: Optional[str] = None
    customer_info: CustomerInfo = CustomerInfo()
    conversation_history: List[Dict[str, str]] = []
    catalog: Optional[Dict] = None
    last_customer_message: Optional[str] = None
    attempts: int = 0  # Track clarification attempts
    
    def update_state(self, new_state: ConversationState):
        """Update conversation state"""
        self.state = new_state
    
    def add_message(self, role: str, content: str):
        """Add message to conversation history"""
        self.conversation_history.append({
            "role": role,
            "content": content
        })
    
    def is_customer_info_complete(self) -> bool:
        """Check if all required customer info is collected"""
        return bool(
            self.customer_info.name and 
            self.customer_info.phone and 
            self.customer_info.address
        )
    
    def reset_attempts(self):
        """Reset clarification attempts"""
        self.attempts = 0
    
    def increment_attempts(self):
        """Increment clarification attempts"""
        self.attempts += 1
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization"""
        return {
            "call_sid": self.call_sid,
            "state": self.state.value,
            "cart_token": self.cart_token,
            "customer_info": self.customer_info.model_dump(),
            "conversation_history": self.conversation_history,
            "last_customer_message": self.last_customer_message,
            "attempts": self.attempts
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ConversationContext":
        """Create from dictionary"""
        context = cls()
        context.call_sid = data.get("call_sid")
        context.state = ConversationState(data.get("state", "welcome"))
        context.cart_token = data.get("cart_token")
        context.customer_info = CustomerInfo(**data.get("customer_info", {}))
        context.conversation_history = data.get("conversation_history", [])
        context.last_customer_message = data.get("last_customer_message")
        context.attempts = data.get("attempts", 0)
        return context
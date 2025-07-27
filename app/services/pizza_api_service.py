import httpx
from loguru import logger
from app.config.settings import settings
from typing import Optional, Dict, List, Any

class PizzaAPIService:
    """Service to interact with Laravel Pizza API"""
    
    def __init__(self):
        self.base_url = settings.laravel_api_base_url.rstrip('/')
        self.api_base = f"{self.base_url}/api/v1"
        
    async def get_catalog(self) -> Optional[Dict]:
        """Get complete pizza catalog optimized for AI"""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(f"{self.api_base}/ai/catalog")
                
                if response.status_code == 200:
                    logger.info("Successfully fetched catalog from Laravel API")
                    return response.json()
                else:
                    logger.error(f"Failed to fetch catalog: {response.status_code}")
                    return None
                    
        except Exception as e:
            logger.error(f"Error fetching catalog: {str(e)}")
            return None
    
    async def create_cart(self) -> Optional[Dict]:
        """Create a new shopping cart"""
        try:
            logger.info(f"Creating cart - POST {self.api_base}/cart/create")
            async with httpx.AsyncClient() as client:
                response = await client.post(f"{self.api_base}/cart/create")
                
                logger.info(f"Create cart response - Status: {response.status_code}, Body: {response.text}")
                
                if response.status_code == 201:
                    result = response.json()
                    cart_token = result['data']['cart_token']
                    logger.info(f"Created cart with token: {cart_token}")
                    return result['data']
                else:
                    logger.error(f"Failed to create cart: {response.status_code}")
                    return None
                    
        except Exception as e:
            logger.error(f"Error creating cart: {str(e)}")
            return None
    
    async def add_product_to_cart(
        self, 
        cart_token: str, 
        product_id: int, 
        quantity: int = 1,
        pizza_size_id: Optional[int] = None
    ) -> bool:
        """Add product to cart"""
        try:
            payload = {
                "cart_token": cart_token,
                "product_id": product_id,
                "quantity": quantity
            }
            
            if pizza_size_id:
                payload["pizza_size_id"] = pizza_size_id
            
            logger.info(f"Adding product to cart - POST {self.api_base}/cart/add-product with payload: {payload}")
            
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.api_base}/cart/add-product",
                    json=payload
                )
                
                logger.info(f"Add product response - Status: {response.status_code}, Body: {response.text}")
                
                if response.status_code == 200:
                    logger.info(f"Added product {product_id} to cart {cart_token}")
                    return True
                else:
                    logger.error(f"Failed to add product to cart: {response.status_code}")
                    return False
                    
        except Exception as e:
            logger.error(f"Error adding product to cart: {str(e)}")
            return False
    
    async def get_cart(self, cart_token: str) -> Optional[Dict]:
        """Get cart contents"""
        try:
            logger.info(f"Getting cart - GET {self.api_base}/cart/{cart_token}")
            async with httpx.AsyncClient() as client:
                response = await client.get(f"{self.api_base}/cart/{cart_token}")
                
                logger.info(f"Get cart response - Status: {response.status_code}, Body: {response.text}")
                
                if response.status_code == 200:
                    logger.info(f"Retrieved cart {cart_token}")
                    return response.json()
                else:
                    logger.error(f"Failed to get cart: {response.status_code}")
                    return None
                    
        except Exception as e:
            logger.error(f"Error getting cart: {str(e)}")
            return None
    
    async def create_order(
        self, 
        cart_token: str,
        customer_name: str,
        customer_phone: str,
        customer_address: str,
        payment_method: str = "efectivo"
    ) -> Optional[Dict]:
        """Create order from cart"""
        try:
            payload = {
                "cart_token": cart_token,
                "customer_name": customer_name,
                "customer_phone": customer_phone,
                "customer_address": customer_address,
                "payment_method": payment_method
            }
            
            logger.info(f"Creating order - POST {self.api_base}/orders with payload: {payload}")
            
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.api_base}/orders",
                    json=payload
                )
                
                logger.info(f"Create order response - Status: {response.status_code}, Body: {response.text}")
                
                if response.status_code == 201:
                    result = response.json()
                    order_id = result['data']['id']
                    view_url = result.get('view_url', '')
                    logger.info(f"Created order {order_id} with URL: {view_url}")
                    logger.info(f"Full order creation response: {result}")
                    return result
                else:
                    logger.error(f"Failed to create order: {response.status_code} - Response: {response.text}")
                    return None
                    
        except Exception as e:
            logger.error(f"Error creating order: {str(e)}")
            return None
    
    async def find_product_by_name(self, product_name: str, catalog: Dict) -> Optional[Dict]:
        """Find product in catalog by name (fuzzy matching)"""
        try:
            if not catalog:
                logger.error("Catalog is None")
                return None
            
            products = catalog.get('data', {}).get('products', [])
            
            for product in products:
                if product_name.lower() in product['name'].lower():
                    return product
            
            pizza_terms = ['margarita', 'ny', 'vegetariana', 'pizza']
            beverage_terms = ['coca', 'cola', 'agua', 'bebida']
            
            search_term = product_name.lower()
            
            for product in products:
                product_name_lower = product['name'].lower()
                
                if any(term in search_term for term in pizza_terms):
                    if any(term in product_name_lower for term in pizza_terms):
                        return product
                
                if any(term in search_term for term in beverage_terms):
                    if any(term in product_name_lower for term in beverage_terms):
                        return product
            
            return None
            
        except Exception as e:
            logger.error(f"Error finding product: {str(e)}")
            return None
    
    async def get_pizza_sizes(self, catalog: Dict) -> List[Dict]:
        """Get available pizza sizes from catalog"""
        try:
            return catalog.get('data', {}).get('pizza_sizes', [])
        except Exception as e:
            logger.error(f"Error getting pizza sizes: {str(e)}")
            return []

pizza_api = PizzaAPIService()
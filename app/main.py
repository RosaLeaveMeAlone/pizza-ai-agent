from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse
from loguru import logger
import sys

from app.config.settings import settings
from app.handlers.voice_handler import voice_router

logger.remove()
logger.add(sys.stdout, level=settings.log_level)

app = FastAPI(
    title="Pizza AI Voice Agent",
    description="AI-powered voice agent for pizza orders using AWS and Twilio",
    version="1.0.0"
)

app.include_router(voice_router, prefix="/voice", tags=["voice"])

@app.get("/")
async def root():
    """Health check endpoint"""
    return {
        "message": "Pizza AI Voice Agent is running!",
        "status": "healthy",
        "environment": settings.app_env
    }

@app.get("/health")
async def health_check():
    """Detailed health check"""
    health_status = {
        "status": "healthy",
        "services": {
            "aws_configured": bool(settings.aws_access_key_id and settings.aws_secret_access_key),
            "twilio_configured": bool(settings.twilio_account_sid and settings.twilio_auth_token),
            "openai_configured": bool(settings.openai_api_key),
            "laravel_api_configured": bool(settings.laravel_api_base_url),
        }
    }
    
    return health_status

@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Log all incoming requests"""
    logger.info(f"Incoming request: {request.method} {request.url}")
    response = await call_next(request)
    logger.info(f"Response status: {response.status_code}")
    return response

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True if settings.app_env == "development" else False
    )
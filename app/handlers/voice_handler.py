from fastapi import APIRouter, Request, Form, HTTPException
from fastapi.responses import Response
from twilio.twiml.voice_response import VoiceResponse
from loguru import logger
from typing import Optional
from app.handlers.conversation_manager import conversation_manager
from app.services.langchain_service import langchain_service

voice_router = APIRouter()

@voice_router.post("/incoming")
async def handle_incoming_call(request: Request):
    """Handle incoming Twilio voice calls"""
    try:
        form_data = await request.form()
        call_sid = form_data.get("CallSid", "unknown")
        
        logger.info(f"Incoming voice call: {call_sid}")
        
        result = await conversation_manager.process_customer_message(
            call_sid, 
            "CALL_START"
        )
        
        return Response(content=result["twiml"], media_type="application/xml")
        
    except Exception as e:
        logger.error(f"Error handling incoming call: {str(e)}")
        
        response = VoiceResponse()
        response.say("Disculpa, tenemos problemas técnicos. Intenta más tarde.", 
                    language='es-ES')
        response.hangup()
        
        return Response(content=str(response), media_type="application/xml")

@voice_router.post("/process-speech")
async def process_speech(
    request: Request,
    SpeechResult: Optional[str] = Form(None),
    Confidence: Optional[float] = Form(None),
    CallSid: Optional[str] = Form(None)
):
    """Process speech input from Twilio"""
    try:
        logger.info(f"Processing speech from {CallSid}: '{SpeechResult}' (confidence: {Confidence})")
        
        if not SpeechResult or not CallSid:
            logger.warning("Missing speech result or call SID")
            
            response = VoiceResponse()
            response.say("No pude entender lo que dijiste. ¿Puedes repetir?", 
                        language='es-ES')
            response.redirect('/voice/incoming')
            return Response(content=str(response), media_type="application/xml")
        
        result = await conversation_manager.process_customer_message(
            CallSid, 
            SpeechResult
        )
        
        return Response(content=result["twiml"], media_type="application/xml")
        
    except Exception as e:
        logger.error(f"Error processing speech: {str(e)}")
        
        response = VoiceResponse()
        response.say("Hubo un error procesando tu solicitud. Por favor, intenta de nuevo.", 
                    language='es-ES')
        response.hangup()
        return Response(content=str(response), media_type="application/xml")

@voice_router.post("/status")
async def call_status(request: Request):
    """Handle call status updates from Twilio"""
    try:
        form_data = await request.form()
        call_status = form_data.get("CallStatus")
        call_sid = form_data.get("CallSid")
        
        logger.info(f"Call {call_sid} status: {call_status}")
        
        if call_status in ["completed", "busy", "no-answer", "failed", "canceled"]:
            if call_sid in conversation_manager.active_conversations:
                del conversation_manager.active_conversations[call_sid]
                langchain_service.clear_memory(call_sid)
                logger.info(f"Cleaned up conversation for {call_sid}")
        
        return {"status": "received"}
        
    except Exception as e:
        logger.error(f"Error handling call status: {str(e)}")
        return {"status": "error"}

@voice_router.get("/test")
async def test_voice_system():
    """Test endpoint to verify voice system integration"""
    try:
        test_result = await conversation_manager.process_customer_message(
            "test-call-123",
            "Hola, quiero una pizza"
        )
        
        return {
            "status": "success",
            "message": "Voice system integration working",
            "test_result": {
                "action": test_result["action"],
                "message": test_result["message"]
            }
        }
        
    except Exception as e:
        logger.error(f"Voice system test failed: {str(e)}")
        return {
            "status": "error",
            "message": str(e)
        }
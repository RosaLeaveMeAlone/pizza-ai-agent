from fastapi import APIRouter, Request, Form, HTTPException, WebSocket
from fastapi.responses import Response
from twilio.twiml.voice_response import VoiceResponse, Start
from loguru import logger
from typing import Optional
from app.handlers.conversation_manager import conversation_manager
from app.services.langchain_service import langchain_service
from app.services.transcribe_service import transcribe_service
from app.handlers.media_stream_handler import media_stream_handler

voice_router = APIRouter()

@voice_router.post("/incoming")
async def handle_incoming_call(request: Request):
    """Handle incoming Twilio voice calls using Media Streams"""
    try:
        form_data = await request.form()
        call_sid = form_data.get("CallSid", "unknown")
        
        logger.info(f"Incoming voice call with Media Streams: {call_sid}")
        
        # Create conversation context
        await conversation_manager._get_or_create_context(call_sid)
        
        # Generate TwiML with Media Streams
        response = VoiceResponse()
        
        # Start Media Stream
        start = Start()
        stream = start.stream(
            url=f'wss://{request.headers.get("host")}/voice/media-stream/{call_sid}'
        )
        response.append(start)
        
        # Keep call alive
        response.say("Conectando...", language='es-ES')
        
        # Log the generated TwiML
        twiml_content = str(response)
        logger.info(f"Generated TwiML for call {call_sid}: {twiml_content}")
        
        return Response(content=twiml_content, media_type="application/xml")
        
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

@voice_router.websocket("/media-stream/{call_sid}")
async def websocket_media_stream(websocket: WebSocket, call_sid: str):
    """WebSocket endpoint for Twilio Media Streams"""
    await media_stream_handler.handle_websocket(websocket, call_sid)

@voice_router.post("/process-recording")
async def process_recording(
    request: Request,
    RecordingUrl: Optional[str] = Form(None),
    CallSid: Optional[str] = Form(None)
):
    """Process audio recording using Whisper"""
    try:
        logger.info(f"Processing recording from {CallSid}: {RecordingUrl}")
        
        if not RecordingUrl or not CallSid:
            logger.warning("Missing recording URL or call SID")
            
            response = VoiceResponse()
            response.say("No pude recibir tu grabación. ¿Puedes repetir?", 
                        language='es-ES')
            response.redirect('/voice/incoming')
            return Response(content=str(response), media_type="application/xml")
        
        # Transcribe with Whisper
        transcribed_text = await transcribe_service.transcribe_audio_from_url(RecordingUrl)
        
        if not transcribed_text:
            logger.warning("Failed to transcribe audio")
            
            response = VoiceResponse()
            response.say("No pude entender lo que dijiste. ¿Puedes repetir?", 
                        language='es-ES')
            response.redirect('/voice/incoming')
            return Response(content=str(response), media_type="application/xml")
        
        # Process the transcribed text
        result = await conversation_manager.process_customer_message(
            CallSid, 
            transcribed_text
        )
        
        return Response(content=result["twiml"], media_type="application/xml")
        
    except Exception as e:
        logger.error(f"Error processing recording: {str(e)}")
        
        response = VoiceResponse()
        response.say("Hubo un error procesando tu grabación. Por favor, intenta de nuevo.", 
                    language='es-ES')
        response.hangup()
        return Response(content=str(response), media_type="application/xml")

@voice_router.post("/recording-status")
async def recording_status(request: Request):
    """Handle recording status updates"""
    try:
        form_data = await request.form()
        recording_status = form_data.get("RecordingStatus")
        call_sid = form_data.get("CallSid")
        
        logger.info(f"Recording {call_sid} status: {recording_status}")
        return {"status": "received"}
        
    except Exception as e:
        logger.error(f"Error handling recording status: {str(e)}")
        return {"status": "error"}

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
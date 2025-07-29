import json
import base64
import asyncio
from fastapi import WebSocket, WebSocketDisconnect
from loguru import logger
from typing import Dict, Optional
from app.handlers.conversation_manager import conversation_manager
from app.services.transcribe_service import transcribe_service
from app.services.polly_service import polly_service
import tempfile
import os
from collections import defaultdict
import io
import audioop
import wave


class MediaStreamHandler:
    """Handles Twilio Media Streams WebSocket connections for real-time audio"""
    
    def __init__(self):
        self.active_streams: Dict[str, Dict] = {}
        self.audio_buffers: Dict[str, io.BytesIO] = defaultdict(io.BytesIO)
        self.stream_sids: Dict[str, str] = {}  # call_sid -> stream_sid mapping
        
    async def handle_websocket(self, websocket: WebSocket, call_sid: str):
        """Handle WebSocket connection for media streaming"""
        await websocket.accept()
        logger.info(f"WebSocket connected for call: {call_sid}")
        
        # Initialize stream data  
        self.active_streams[call_sid] = {
            "websocket": websocket,
            "call_sid": call_sid,
            "connected": True
        }
        
        try:
            # Send initial greeting
            await self._send_initial_greeting(call_sid)
            
            # Process incoming messages
            while True:
                try:
                    data = await websocket.receive_text()
                    message = json.loads(data)
                    await self._process_media_message(call_sid, message)
                    
                except WebSocketDisconnect:
                    logger.info(f"WebSocket disconnected for call: {call_sid}")
                    break
                except json.JSONDecodeError:
                    logger.warning(f"Invalid JSON received from call {call_sid}")
                except Exception as e:
                    logger.error(f"Error processing message for call {call_sid}: {str(e)}")
                    
        except Exception as e:
            logger.error(f"WebSocket error for call {call_sid}: {str(e)}")
        finally:
            # Cleanup
            await self._cleanup_stream(call_sid)
            
    async def _process_media_message(self, call_sid: str, message: dict):
        """Process incoming media stream messages"""
        event = message.get("event")
        
        if event == "connected":
            logger.info(f"Media stream connected for call: {call_sid}")
            
        elif event == "start":
            stream_sid = message.get("streamSid")
            self.stream_sids[call_sid] = stream_sid
            logger.info(f"Media stream started: {stream_sid} for call: {call_sid}")
            
        elif event == "media":
            # Accumulate audio data
            payload = message.get("media", {})
            audio_data = payload.get("payload", "")
            
            if audio_data:
                # Decode base64 audio (mulaw format)
                try:
                    decoded_audio = base64.b64decode(audio_data)
                    self.audio_buffers[call_sid].write(decoded_audio)
                except Exception as e:
                    logger.error(f"Error decoding audio for call {call_sid}: {str(e)}")
                    
        elif event == "stop":
            logger.info(f"Media stream stopped for call: {call_sid}")
            # Process accumulated audio
            await self._process_accumulated_audio(call_sid)
            
    async def _process_accumulated_audio(self, call_sid: str):
        """Process accumulated audio buffer using Whisper"""
        try:
            audio_buffer = self.audio_buffers.get(call_sid)
            if not audio_buffer or audio_buffer.tell() == 0:
                logger.warning(f"No audio data to process for call: {call_sid}")
                return
                
            # Reset buffer position to beginning
            audio_buffer.seek(0)
            audio_data = audio_buffer.read()
            
            # Clear buffer for next chunk
            self.audio_buffers[call_sid] = io.BytesIO()
            
            # Convert mulaw to PCM WAV format
            # Twilio sends mulaw at 8kHz, 8-bit
            try:
                # Convert mulaw to 16-bit PCM
                pcm_data = audioop.ulaw2lin(audio_data, 2)
                
                # Create WAV file
                with tempfile.NamedTemporaryFile(delete=False, suffix='.wav') as temp_file:
                    temp_file_path = temp_file.name
                    
                with wave.open(temp_file_path, 'wb') as wav_file:
                    wav_file.setnchannels(1)  # Mono
                    wav_file.setsampwidth(2)  # 16-bit
                    wav_file.setframerate(8000)  # 8kHz sample rate
                    wav_file.writeframes(pcm_data)
                    
            except Exception as e:
                logger.error(f"Error converting audio format for call {call_sid}: {str(e)}")
                return
                
            try:
                # Transcribe with Whisper
                with open(temp_file_path, 'rb') as audio_file:
                    from openai import OpenAI
                    from app.config.settings import settings
                    
                    client = OpenAI(api_key=settings.openai_api_key)
                    transcript = client.audio.transcriptions.create(
                        model="whisper-1",
                        file=audio_file,
                        language="es"
                    )
                    
                transcribed_text = transcript.text.strip()
                logger.info(f"Whisper transcription for {call_sid}: '{transcribed_text}'")
                
                if transcribed_text:
                    # Process with conversation manager
                    result = await conversation_manager.process_customer_message(
                        call_sid, 
                        transcribed_text
                    )
                    
                    # Send audio response back via WebSocket
                    response_text = result.get("message", "")
                    await self._send_audio_response(call_sid, response_text)
                    
            finally:
                # Clean up temp file
                os.unlink(temp_file_path)
                
        except Exception as e:
            logger.error(f"Error processing accumulated audio for call {call_sid}: {str(e)}")
            
    async def _send_initial_greeting(self, call_sid: str):
        """Send initial greeting via WebSocket"""
        greeting = "¡Hola! Bienvenido a Pizza Project. ¿Qué desea ordenar hoy?"
        await self._send_audio_response(call_sid, greeting)
        
    async def _send_audio_response(self, call_sid: str, text: str):
        """Send audio response via WebSocket"""
        try:
            stream_data = self.active_streams.get(call_sid)
            if not stream_data or not stream_data.get("connected"):
                logger.warning(f"No active stream for call: {call_sid}")
                return
                
            websocket = stream_data["websocket"]
            stream_sid = self.stream_sids.get(call_sid)
            
            if not stream_sid:
                logger.warning(f"No stream SID for call: {call_sid}")
                return
                
            # Generate audio with Polly (returns PCM WAV)
            audio_bytes = await polly_service.synthesize_speech(text)
            
            # Convert PCM to mulaw for Twilio
            # Assuming Polly returns 16-bit PCM at 22kHz, we need to convert to 8kHz mulaw
            try:
                # Convert 16-bit PCM to mulaw (simplified - may need proper resampling)
                mulaw_data = audioop.lin2ulaw(audio_bytes, 2)
                audio_base64 = base64.b64encode(mulaw_data).decode('utf-8')
            except Exception as e:
                logger.error(f"Error converting response audio to mulaw: {str(e)}")
                return
            
            # Send audio via WebSocket
            media_message = {
                "event": "media",
                "streamSid": stream_sid,
                "media": {
                    "payload": audio_base64
                }
            }
            
            await websocket.send_text(json.dumps(media_message))
            logger.info(f"Sent audio response to call: {call_sid}")
            
        except Exception as e:
            logger.error(f"Error sending audio response to call {call_sid}: {str(e)}")
            
    async def _cleanup_stream(self, call_sid: str):
        """Clean up stream resources"""
        if call_sid in self.active_streams:
            del self.active_streams[call_sid]
        if call_sid in self.audio_buffers:
            del self.audio_buffers[call_sid]
        if call_sid in self.stream_sids:
            del self.stream_sids[call_sid]
        logger.info(f"Cleaned up stream resources for call: {call_sid}")


# Global handler instance
media_stream_handler = MediaStreamHandler()
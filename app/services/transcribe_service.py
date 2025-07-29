import httpx
import tempfile
import os
from openai import OpenAI
from loguru import logger
from app.config.settings import settings
from typing import Optional

class TranscribeService:
    """OpenAI Whisper speech-to-text service"""
    
    def __init__(self):
        self.client = OpenAI(api_key=settings.openai_api_key)
        
    async def transcribe_audio_from_url(
        self, 
        audio_url: str,
        language_code: str = "es"
    ) -> Optional[str]:
        """
        Transcribe audio from a URL using OpenAI Whisper
        
        Args:
            audio_url: URL to audio file
            language_code: Language for transcription (ISO 639-1 format)
            
        Returns:
            Transcribed text or None if error
        """
        try:
            logger.info(f"Starting Whisper transcription from URL: {audio_url}")
            
            # Download audio file
            async with httpx.AsyncClient() as client:
                response = await client.get(audio_url)
                response.raise_for_status()
                
                # Save to temporary file
                with tempfile.NamedTemporaryFile(delete=False, suffix='.wav') as temp_file:
                    temp_file.write(response.content)
                    temp_file_path = temp_file.name
            
            try:
                # Transcribe with Whisper
                with open(temp_file_path, 'rb') as audio_file:
                    transcript = self.client.audio.transcriptions.create(
                        model="whisper-1",
                        file=audio_file,
                        language=language_code
                    )
                
                text = transcript.text.strip()
                logger.info(f"Whisper transcription result: '{text}'")
                return text
                
            finally:
                # Clean up temporary file
                os.unlink(temp_file_path)
            
        except Exception as e:
            logger.error(f"Error with Whisper transcription: {str(e)}")
            return None

transcribe_service = TranscribeService()
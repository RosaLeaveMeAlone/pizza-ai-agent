import boto3
from io import BytesIO
import base64
from loguru import logger
from app.services.aws_config import aws_config
from typing import Optional

class PollyService:
    """Amazon Polly text-to-speech service"""
    
    def __init__(self):
        self.client = aws_config.get_polly_client()
        
    async def synthesize_speech(
        self, 
        text: str, 
        voice_id: str = "Conchita",
        output_format: str = "mp3",
        sample_rate: str = "8000"
    ) -> Optional[bytes]:
        """
        Convert text to speech using Amazon Polly
        
        Args:
            text: Text to convert to speech
            voice_id: Voice to use (Conchita for Spanish)
            output_format: Audio format (mp3, ogg_vorbis, pcm)
            sample_rate: Sample rate for phone calls (8000 for µ-law)
            
        Returns:
            Audio bytes or None if error
        """
        try:
            logger.info(f"Synthesizing speech: '{text[:50]}...' with voice {voice_id}")
            
            response = self.client.synthesize_speech(
                Text=text,
                OutputFormat=output_format,
                VoiceId=voice_id,
                SampleRate=sample_rate,
                LanguageCode="es-ES"
            )
            
            audio_stream = response['AudioStream']
            audio_bytes = audio_stream.read()
            
            logger.info(f"Successfully synthesized {len(audio_bytes)} bytes of audio")
            return audio_bytes
            
        except Exception as e:
            logger.error(f"Error synthesizing speech: {str(e)}")
            return None
    
    async def synthesize_speech_for_phone(self, text: str) -> Optional[str]:
        """
        Synthesize speech optimized for phone calls and return as base64
        
        Args:
            text: Text to convert to speech
            
        Returns:
            Base64 encoded audio or None if error
        """
        try:
            response = self.client.synthesize_speech(
                Text=text,
                OutputFormat="pcm",
                VoiceId="Conchita",
                SampleRate="8000",
                LanguageCode="es-ES"
            )
            
            audio_bytes = response['AudioStream'].read()
            
            audio_base64 = base64.b64encode(audio_bytes).decode('utf-8')
            
            logger.info(f"Phone audio synthesized: {len(audio_base64)} chars base64")
            return audio_base64
            
        except Exception as e:
            logger.error(f"Error synthesizing phone audio: {str(e)}")
            return None

polly_service = PollyService()
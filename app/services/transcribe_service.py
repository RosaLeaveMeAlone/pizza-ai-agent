import boto3
import asyncio
import uuid
import time
from loguru import logger
from app.services.aws_config import aws_config
from typing import Optional

class TranscribeService:
    """Amazon Transcribe speech-to-text service"""
    
    def __init__(self):
        self.client = aws_config.get_transcribe_client()
        self.s3_client = aws_config.get_s3_client()
        
    async def transcribe_audio_from_url(
        self, 
        audio_url: str,
        language_code: str = "es-ES"
    ) -> Optional[str]:
        """
        Transcribe audio from a URL (Twilio recording)
        
        Args:
            audio_url: URL to audio file
            language_code: Language for transcription
            
        Returns:
            Transcribed text or None if error
        """
        try:
            job_name = f"pizza-transcription-{uuid.uuid4()}"
            
            logger.info(f"Starting transcription job: {job_name}")
            
            # Start transcription job
            response = self.client.start_transcription_job(
                TranscriptionJobName=job_name,
                Media={'MediaFileUri': audio_url},
                MediaFormat='wav',
                LanguageCode=language_code,
                Settings={
                    'ShowSpeakerLabels': False,
                    'MaxSpeakerLabels': 1
                }
            )
            
            return await self._wait_for_transcription(job_name)
            
        except Exception as e:
            logger.error(f"Error starting transcription: {str(e)}")
            return None
    
    async def _wait_for_transcription(self, job_name: str, max_wait: int = 60) -> Optional[str]:
        """
        Wait for transcription job to complete
        
        Args:
            job_name: Name of the transcription job
            max_wait: Maximum seconds to wait
            
        Returns:
            Transcribed text or None if error/timeout
        """
        try:
            start_time = time.time()
            
            while time.time() - start_time < max_wait:
                response = self.client.get_transcription_job(
                    TranscriptionJobName=job_name
                )
                
                status = response['TranscriptionJob']['TranscriptionJobStatus']
                
                if status == 'COMPLETED':
                    transcript_uri = response['TranscriptionJob']['Transcript']['TranscriptFileUri']
                    return await self._extract_transcript_text(transcript_uri)
                    
                elif status == 'FAILED':
                    failure_reason = response['TranscriptionJob'].get('FailureReason', 'Unknown')
                    logger.error(f"Transcription failed: {failure_reason}")
                    return None
                
                await asyncio.sleep(2)
            
            logger.warning(f"Transcription job {job_name} timed out")
            return None
            
        except Exception as e:
            logger.error(f"Error waiting for transcription: {str(e)}")
            return None
    
    async def _extract_transcript_text(self, transcript_uri: str) -> Optional[str]:
        """
        Extract text from transcription result JSON
        
        Args:
            transcript_uri: URI to transcription result
            
        Returns:
            Extracted text or None if error
        """
        try:
            import httpx
            
            async with httpx.AsyncClient() as client:
                response = await client.get(transcript_uri)
                result = response.json()
                
                transcripts = result.get('results', {}).get('transcripts', [])
                if transcripts:
                    text = transcripts[0].get('transcript', '')
                    logger.info(f"Transcription result: '{text}'")
                    return text.strip()
                
                logger.warning("No transcript found in result")
                return None
                
        except Exception as e:
            logger.error(f"Error extracting transcript: {str(e)}")
            return None
    
    async def transcribe_real_time_stream(self, audio_stream):
        """
        TODO: Implement real-time transcription for live calls
        This would use Amazon Transcribe Streaming API
        """
        pass

transcribe_service = TranscribeService()
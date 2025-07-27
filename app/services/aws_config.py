import boto3
from app.config.settings import settings
from loguru import logger

class AWSConfig:
    """AWS services configuration and clients"""
    
    def __init__(self):
        self.session = boto3.Session(
            aws_access_key_id=settings.aws_access_key_id,
            aws_secret_access_key=settings.aws_secret_access_key,
            region_name=settings.aws_region
        )
        logger.info(f"AWS session initialized for region: {settings.aws_region}")
    
    def get_transcribe_client(self):
        """Get Amazon Transcribe client"""
        return self.session.client('transcribe')
    
    def get_polly_client(self):
        """Get Amazon Polly client"""
        return self.session.client('polly')
    
    def get_s3_client(self):
        """Get S3 client for storing audio files"""
        return self.session.client('s3')

aws_config = AWSConfig()
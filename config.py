"""
Configuration management for Kraken CLI
"""

import os
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv

class Config:
    def __init__(self):
        load_dotenv()
        self.api_key: Optional[str] = os.getenv('KRAKEN_API_KEY')
        self.api_secret: Optional[str] = os.getenv('KRAKEN_API_SECRET')
        self.sandbox: bool = os.getenv('KRAKEN_SANDBOX', 'false').lower() == 'true'
        self.config_file: Path = Path(__file__).parent.parent / 'config.json'
    
    def has_credentials(self) -> bool:
        """Check if API credentials are configured"""
        return bool(self.api_key and self.api_secret)
    
    def get_rate_limit(self) -> int:
        """Get API rate limit (requests per second) - Updated for 2025 API"""
        # Current Kraken API rate limits:
        # Public endpoints: 1 request/second
        # Private endpoints: 15-20 requests/minute (0.25-0.33 requests/second)
        return 1  # Conservative rate limit for all endpoints
    
    def get_timeout(self) -> int:
        """Get request timeout in seconds"""
        return 30
    
    def is_sandbox(self) -> bool:
        """Check if using sandbox environment"""
        return self.sandbox
    
    def get_api_url(self) -> str:
        """Get Kraken API URL based on environment"""
        if self.sandbox:
            return "https://api-sandbox.kraken.com"
        return "https://api.kraken.com"
    
    def validate_credentials(self) -> bool:
        """Validate API credentials format"""
        if not self.api_key or not self.api_secret:
            return False
        
        # Basic validation - adjust based on actual Kraken API key format
        if len(self.api_key) < 10 or len(self.api_secret) < 10:
            return False
        
        return True
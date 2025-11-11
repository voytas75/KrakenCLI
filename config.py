"""
Configuration management for Kraken CLI.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, Optional

from dotenv import load_dotenv

logger = logging.getLogger(__name__)


class Config:
    """Load configuration with Env → .env → config.json → defaults precedence."""

    _CONFIG_KEY_MAPPING: Dict[str, tuple[str, ...]] = {
        "KRAKEN_API_KEY": ("KRAKEN_API_KEY", "api_key"),
        "KRAKEN_API_SECRET": ("KRAKEN_API_SECRET", "api_secret"),
        "KRAKEN_SANDBOX": ("KRAKEN_SANDBOX", "sandbox"),
        "KRAKEN_RATE_LIMIT": ("KRAKEN_RATE_LIMIT", "rate_limit"),
        "KRAKEN_TIMEOUT": ("KRAKEN_TIMEOUT", "timeout"),
        "KRAKEN_LOG_LEVEL": ("KRAKEN_LOG_LEVEL", "log_level"),
    }

    _DEFAULTS: Dict[str, Any] = {
        "KRAKEN_API_KEY": None,
        "KRAKEN_API_SECRET": None,
        "KRAKEN_SANDBOX": False,
        "KRAKEN_RATE_LIMIT": 1,
        "KRAKEN_TIMEOUT": 30,
        "KRAKEN_LOG_LEVEL": "INFO",
    }

    def __init__(self) -> None:
        load_dotenv()
        self.config_file: Path = Path(__file__).parent / "config.json"
        self._config_data: Dict[str, Any] = self._load_config_file()

        api_key_value = self._get_setting("KRAKEN_API_KEY")
        api_secret_value = self._get_setting("KRAKEN_API_SECRET")
        sandbox_value = self._get_setting("KRAKEN_SANDBOX")
        rate_limit_value = self._get_setting("KRAKEN_RATE_LIMIT")
        timeout_value = self._get_setting("KRAKEN_TIMEOUT")
        log_level_value = self._get_setting("KRAKEN_LOG_LEVEL")

        self.api_key: Optional[str] = (
            str(api_key_value).strip() if api_key_value else None
        )
        self.api_secret: Optional[str] = (
            str(api_secret_value).strip() if api_secret_value else None
        )
        self.sandbox: bool = self._to_bool(sandbox_value)
        self.rate_limit: int = self._to_int(rate_limit_value, self._DEFAULTS["KRAKEN_RATE_LIMIT"])
        self.timeout: int = self._to_int(timeout_value, self._DEFAULTS["KRAKEN_TIMEOUT"])
        self.log_level: str = str(log_level_value or self._DEFAULTS["KRAKEN_LOG_LEVEL"]).upper()

    def _load_config_file(self) -> Dict[str, Any]:
        """Load configuration values from config.json if available."""
        if not self.config_file.exists():
            return {}
        try:
            with self.config_file.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
                if isinstance(data, dict):
                    return data
                logger.warning("config.json must contain a JSON object; ignoring content.")
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Failed to read config.json: %s", exc)
        return {}

    def _get_setting(self, env_key: str) -> Any:
        """Resolve a configuration value using the configured precedence."""
        env_value = os.getenv(env_key)
        if env_value not in (None, ""):
            return env_value

        keys_to_check = self._CONFIG_KEY_MAPPING.get(env_key, (env_key,))
        for key in keys_to_check:
            config_value = self._config_data.get(key)
            if config_value not in (None, ""):
                return config_value

        return self._DEFAULTS.get(env_key)

    @staticmethod
    def _to_bool(value: Any) -> bool:
        """Convert a configuration value to boolean."""
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return bool(value)

    @staticmethod
    def _to_int(value: Any, default: int) -> int:
        """Convert a configuration value to integer with fallback."""
        try:
            if value is None or value == "":
                return default
            return int(value)
        except (TypeError, ValueError):
            return default

    def has_credentials(self) -> bool:
        """Check if API credentials are configured."""
        return bool(self.api_key and self.api_secret)

    def get_rate_limit(self) -> int:
        """
        Get API rate limit (requests per second) - Updated for 2025 API.

        Current Kraken API guidance:
        - Public endpoints: 1 request/second
        - Private endpoints: 15-20 requests/minute (0.25-0.33 rps)
        """
        return self.rate_limit

    def get_timeout(self) -> int:
        """Get request timeout in seconds."""
        return self.timeout

    def is_sandbox(self) -> bool:
        """Check if using sandbox environment."""
        return self.sandbox

    def get_api_url(self) -> str:
        """Get Kraken API URL based on environment."""
        if self.sandbox:
            return "https://api-sandbox.kraken.com"
        return "https://api.kraken.com"

    def validate_credentials(self) -> bool:
        """Validate API credentials format."""
        if not self.api_key or not self.api_secret:
            return False

        # Basic validation - adjust based on actual Kraken API key format.
        if len(self.api_key) < 10 or len(self.api_secret) < 10:
            return False

        return True

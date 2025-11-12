"""
Configuration management for Kraken CLI.

Updates: v0.9.0 - 2025-11-11 - Added automated trading and alert configuration options.
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
        "KRAKEN_LOG_LEVEL": ("KRAKEN_LOG_LEVEL", "LOG_LEVEL", "log_level"),
        "KRAKEN_RETRY_ATTEMPTS": ("KRAKEN_RETRY_ATTEMPTS",),
        "KRAKEN_RETRY_INITIAL_DELAY": ("KRAKEN_RETRY_INITIAL_DELAY",),
        "KRAKEN_RETRY_BACKOFF": ("KRAKEN_RETRY_BACKOFF",),
        "AUTO_TRADING_ENABLED": ("AUTO_TRADING_ENABLED",),
        "AUTO_TRADING_CONFIG_PATH": ("AUTO_TRADING_CONFIG_PATH",),
        "ALERT_WEBHOOK_URL": ("ALERT_WEBHOOK_URL",),
        "ALERT_EMAIL_SENDER": ("ALERT_EMAIL_SENDER",),
        "ALERT_EMAIL_RECIPIENTS": ("ALERT_EMAIL_RECIPIENTS",),
        "ALERT_EMAIL_SMTP_SERVER": ("ALERT_EMAIL_SMTP_SERVER",),
        "ALERT_EMAIL_SMTP_PORT": ("ALERT_EMAIL_SMTP_PORT",),
        "ALERT_EMAIL_SMTP_USERNAME": ("ALERT_EMAIL_SMTP_USERNAME",),
        "ALERT_EMAIL_SMTP_PASSWORD": ("ALERT_EMAIL_SMTP_PASSWORD",),
    }

    _DEFAULTS: Dict[str, Any] = {
        "KRAKEN_API_KEY": None,
        "KRAKEN_API_SECRET": None,
        "KRAKEN_SANDBOX": False,
        "KRAKEN_RATE_LIMIT": 1,
        "KRAKEN_TIMEOUT": 30,
        "KRAKEN_LOG_LEVEL": "INFO",
        "KRAKEN_RETRY_ATTEMPTS": 3,
        "KRAKEN_RETRY_INITIAL_DELAY": 1.0,
        "KRAKEN_RETRY_BACKOFF": 1.5,
        "AUTO_TRADING_ENABLED": False,
        "AUTO_TRADING_CONFIG_PATH": "configs/auto_trading.yaml",
        "ALERT_WEBHOOK_URL": None,
        "ALERT_EMAIL_SENDER": None,
        "ALERT_EMAIL_RECIPIENTS": None,
        "ALERT_EMAIL_SMTP_SERVER": None,
        "ALERT_EMAIL_SMTP_PORT": 587,
        "ALERT_EMAIL_SMTP_USERNAME": None,
        "ALERT_EMAIL_SMTP_PASSWORD": None,
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
        retry_attempts_value = self._get_setting("KRAKEN_RETRY_ATTEMPTS")
        retry_initial_delay_value = self._get_setting("KRAKEN_RETRY_INITIAL_DELAY")
        retry_backoff_value = self._get_setting("KRAKEN_RETRY_BACKOFF")
        auto_trading_enabled_value = self._get_setting("AUTO_TRADING_ENABLED")
        auto_trading_config_value = self._get_setting("AUTO_TRADING_CONFIG_PATH")
        alert_webhook_value = self._get_setting("ALERT_WEBHOOK_URL")
        alert_email_sender_value = self._get_setting("ALERT_EMAIL_SENDER")
        alert_email_recipients_value = self._get_setting("ALERT_EMAIL_RECIPIENTS")
        alert_email_smtp_server_value = self._get_setting("ALERT_EMAIL_SMTP_SERVER")
        alert_email_smtp_port_value = self._get_setting("ALERT_EMAIL_SMTP_PORT")
        alert_email_smtp_username_value = self._get_setting("ALERT_EMAIL_SMTP_USERNAME")
        alert_email_smtp_password_value = self._get_setting("ALERT_EMAIL_SMTP_PASSWORD")

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
        self.retry_attempts: int = self._to_int(retry_attempts_value, self._DEFAULTS["KRAKEN_RETRY_ATTEMPTS"])
        self.retry_initial_delay: float = self._to_float(retry_initial_delay_value, self._DEFAULTS["KRAKEN_RETRY_INITIAL_DELAY"])
        self.retry_backoff: float = self._to_float(retry_backoff_value, self._DEFAULTS["KRAKEN_RETRY_BACKOFF"])
        self.auto_trading_enabled: bool = self._to_bool(auto_trading_enabled_value)
        self.auto_trading_config_path: Path = Path(str(auto_trading_config_value or self._DEFAULTS["AUTO_TRADING_CONFIG_PATH"]))
        self.alert_webhook_url: Optional[str] = str(alert_webhook_value).strip() if alert_webhook_value else None
        self.alert_email_sender: Optional[str] = str(alert_email_sender_value).strip() if alert_email_sender_value else None
        self.alert_email_recipients: list[str] = self._parse_recipients(alert_email_recipients_value)
        self.alert_email_smtp_server: Optional[str] = str(alert_email_smtp_server_value).strip() if alert_email_smtp_server_value else None
        self.alert_email_smtp_port: int = self._to_int(alert_email_smtp_port_value, self._DEFAULTS["ALERT_EMAIL_SMTP_PORT"])
        self.alert_email_smtp_username: Optional[str] = str(alert_email_smtp_username_value).strip() if alert_email_smtp_username_value else None
        self.alert_email_smtp_password: Optional[str] = str(alert_email_smtp_password_value).strip() if alert_email_smtp_password_value else None

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

    @staticmethod
    def _to_float(value: Any, default: float) -> float:
        """Convert a configuration value to float with fallback."""

        try:
            if value is None or value == "":
                return default
            return float(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _parse_recipients(value: Any) -> list[str]:
        """Parse comma-separated email recipient list."""
        if not value:
            return []
        if isinstance(value, (list, tuple)):
            return [str(item).strip() for item in value if str(item).strip()]
        return [item.strip() for item in str(value).split(",") if item.strip()]

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

    def get_retry_attempts(self) -> int:
        """Return configured retry attempts for Kraken requests."""

        return max(1, self.retry_attempts)

    def get_retry_initial_delay(self) -> float:
        """Return initial retry delay in seconds."""

        return max(0.1, self.retry_initial_delay)

    def get_retry_backoff(self) -> float:
        """Return exponential backoff factor for retries."""

        return max(1.0, self.retry_backoff)

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

    def get_auto_trading_config_path(self) -> Path:
        """Return path to the auto trading configuration file."""
        return self.auto_trading_config_path

    def alerts_enabled(self) -> bool:
        """Return True when any alert channel is configured."""
        return bool(self.alert_webhook_url or self.alert_email_recipients)

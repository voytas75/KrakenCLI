"""
Centralised alert manager handling CLI and log notifications.

Updates: v0.9.3 - 2025-11-12 - Added alert routing with enable/disable controls and event throttling.
"""

from __future__ import annotations

import json
import logging
import os
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Deque, Dict, List, Optional

from rich.console import Console

DEFAULT_ALERT_STATE_PATH = Path("logs") / "alert_state.json"
ALERT_STATE_ENV_KEY = "KRAKEN_ALERT_STATE_PATH"

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AlertPayload:
    """Structured payload captured for logging and CLI display."""

    event: str
    message: str
    severity: str
    details: Dict[str, Any]
    timestamp: float


class AlertManager:
    """Manage alert enablement and dispatch to console/log outputs."""

    ICON_MAP: Dict[str, str] = {
        "INFO": "ℹ️",
        "WARNING": "⚠️",
        "ERROR": "❌",
        "SUCCESS": "✅",
    }

    STYLE_MAP: Dict[str, str] = {
        "INFO": "cyan",
        "WARNING": "yellow",
        "ERROR": "red",
        "SUCCESS": "green",
    }

    def __init__(
        self,
        config: Any,
        console: Optional[Console] = None,
        state_path: Optional[Path] = None,
        throttle_seconds: float = 60.0,
    ):
        self._config = config
        self._console = console or Console()
        self._state_path = self._resolve_state_path(state_path)
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        self._state = self._load_state()
        self._throttle_seconds = max(0.0, throttle_seconds)
        self._last_sent: Dict[str, float] = {}
        self._history: Deque[AlertPayload] = deque(maxlen=20)

        default_enabled = False
        try:
            default_enabled = bool(self._config.alerts_enabled())
        except AttributeError:
            default_enabled = False

        self._enabled: bool = bool(self._state.get("enabled", default_enabled))

    @staticmethod
    def _resolve_state_path(state_path: Optional[Path]) -> Path:
        """Resolve alert state file path from explicit argument or environment."""
        if state_path is not None:
            return state_path
        env_path = os.getenv(ALERT_STATE_ENV_KEY)
        if env_path:
            return Path(env_path)
        return DEFAULT_ALERT_STATE_PATH

    def _load_state(self) -> Dict[str, Any]:
        if not self._state_path.exists():
            return {}
        try:
            with self._state_path.open("r", encoding="utf-8") as handle:
                payload = json.load(handle)
                if isinstance(payload, dict):
                    return payload
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Failed to read alert state (%s): %s", self._state_path, exc)
        return {}

    def _persist_state(self) -> None:
        try:
            with self._state_path.open("w", encoding="utf-8") as handle:
                json.dump({"enabled": self._enabled}, handle, indent=2)
        except OSError as exc:
            logger.error("Unable to persist alert state (%s): %s", self._state_path, exc)

    def enable(self, source: str = "cli") -> None:
        """Enable alert dispatch and persist the state."""
        self._enabled = True
        self._persist_state()
        logger.info("Alerts enabled via %s (channels=%s)", source, self._channel_summary())

    def disable(self, source: str = "cli") -> None:
        """Disable alert dispatch and persist the state."""
        self._enabled = False
        self._persist_state()
        logger.info("Alerts disabled via %s", source)

    def is_enabled(self) -> bool:
        """Return True when alerts are enabled."""
        return self._enabled

    def status(self) -> Dict[str, Any]:
        """Return a structured status summary for CLI display."""
        channels = self._channels()
        return {
            "enabled": self._enabled,
            "channels": channels,
            "state_path": str(self._state_path.resolve()),
            "cooldown_seconds": self._throttle_seconds,
            "recent_alerts": [
                {
                    "event": payload.event,
                    "severity": payload.severity,
                    "message": payload.message,
                    "timestamp": datetime.fromtimestamp(payload.timestamp, tz=timezone.utc).isoformat(),
                }
                for payload in list(self._history)[-5:]
            ],
        }

    def _channels(self) -> Dict[str, bool]:
        """Derive available channels based on configuration."""
        webhook = bool(getattr(self._config, "alert_webhook_url", None))
        recipients = getattr(self._config, "alert_email_recipients", None) or []
        email = bool(recipients)
        return {
            "console": True,
            "logs": True,
            "webhook_configured": webhook,
            "email_configured": email,
        }

    def _channel_summary(self) -> str:
        channels = self._channels()
        return ", ".join(f"{key}={value}" for key, value in channels.items())

    def send(
        self,
        event: str,
        message: str,
        severity: str = "INFO",
        details: Optional[Dict[str, Any]] = None,
        *,
        cooldown: Optional[float] = None,
        force: bool = False,
    ) -> None:
        """Dispatch an alert if enabled, logging outcome and printing to console."""
        payload = AlertPayload(
            event=event,
            message=message,
            severity=severity.upper(),
            details=details or {},
            timestamp=time.time(),
        )

        if not self._enabled and not force:
            logger.debug("Alert skipped (disabled): %s - %s", payload.event, payload.message)
            return

        if not self._should_emit(payload.event, cooldown):
            logger.debug("Alert suppressed by throttle: %s", payload.event)
            return

        self._last_sent[payload.event] = time.monotonic()
        self._history.append(payload)
        self._log_payload(payload)
        self._print_payload(payload)

    def _should_emit(self, event: str, cooldown: Optional[float]) -> bool:
        effective_cooldown = self._throttle_seconds if cooldown is None else max(0.0, cooldown)
        if effective_cooldown == 0:
            return True

        last_timestamp = self._last_sent.get(event)
        now = time.monotonic()
        if last_timestamp is None:
            return True
        return (now - last_timestamp) >= effective_cooldown

    def _log_payload(self, payload: AlertPayload) -> None:
        level_map = {
            "ERROR": logging.ERROR,
            "WARNING": logging.WARNING,
            "SUCCESS": logging.INFO,
            "INFO": logging.INFO,
        }
        level = level_map.get(payload.severity, logging.INFO)
        logger.log(
            level,
            "[%s] %s | details=%s",
            payload.severity,
            payload.message,
            payload.details or {},
        )

    def _print_payload(self, payload: AlertPayload) -> None:
        icon = self.ICON_MAP.get(payload.severity, self.ICON_MAP["INFO"])
        style = self.STYLE_MAP.get(payload.severity, self.STYLE_MAP["INFO"])
        details_text = ""
        if payload.details:
            serialized = ", ".join(f"{key}={value}" for key, value in payload.details.items())
            details_text = f" ({serialized})"

        self._console.print(
            f"[{style}]{icon} Alert ({payload.event}) {payload.message}{details_text}[/{style}]"
        )

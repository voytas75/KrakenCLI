"""Unit tests for the alert manager subsystem."""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from rich.console import Console

from alerts.alert_manager import AlertManager


class _StubConfig:
    """Minimal configuration stub exposing alert attributes."""

    def __init__(
        self,
        enabled: bool = False,
        webhook: str | None = None,
        recipients: list[str] | None = None,
    ):
        self._enabled = enabled
        self.alert_webhook_url = webhook
        self.alert_email_recipients = recipients or []

    def alerts_enabled(self) -> bool:
        return self._enabled


class AlertManagerTests(unittest.TestCase):
    """Validate alert manager enablement, persistence, and console output."""

    def setUp(self) -> None:
        self.tempdir = TemporaryDirectory()
        self.state_path = Path(self.tempdir.name) / "alert_state.json"

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_enable_disable_persists_state(self) -> None:
        config = _StubConfig(enabled=False)
        console = Console(record=True)
        manager = AlertManager(
            config,
            console=console,
            state_path=self.state_path,
            throttle_seconds=0,
        )

        self.assertFalse(manager.is_enabled())
        manager.enable(source="test")
        self.assertTrue(manager.is_enabled())
        manager.disable(source="test")
        self.assertFalse(manager.is_enabled())

        persisted = json.loads(self.state_path.read_text(encoding="utf-8"))
        self.assertFalse(persisted["enabled"])
        self.assertIsInstance(persisted.get("history"), list)

    def test_send_emits_console_output_when_enabled(self) -> None:
        config = _StubConfig(enabled=True, recipients=["alerts@example.com"])
        console = Console(record=True)
        manager = AlertManager(
            config,
            console=console,
            state_path=self.state_path,
            throttle_seconds=0,
        )

        manager.enable(source="test")
        manager.send(
            event="risk.test",
            message="Test alert message",
            severity="WARNING",
            details={"pair": "ETHUSD"},
        )

        rendered = console.export_text()
        self.assertIn("Test alert message", rendered)
        self.assertIn("risk.test", rendered)
        summary = manager.status()
        self.assertEqual(len(summary["recent_alerts"]), 1)

    def test_status_reports_channels(self) -> None:
        config = _StubConfig(enabled=True, webhook="https://example.com", recipients=["ops@example.com"])
        manager = AlertManager(
            config,
            console=Console(record=True),
            state_path=self.state_path,
            throttle_seconds=0,
        )
        summary = manager.status()

        self.assertIn("channels", summary)
        channels = summary["channels"]
        self.assertTrue(channels["console"])
        self.assertTrue(channels["logs"])
        self.assertTrue(channels["webhook_configured"])
        self.assertTrue(channels["email_configured"])
        self.assertEqual(summary["cooldown_seconds"], 0)
        self.assertIsInstance(summary.get("recent_alerts"), list)

    def test_throttle_suppresses_repeated_alerts(self) -> None:
        config = _StubConfig(enabled=True)
        console = Console(record=True)
        manager = AlertManager(
            config,
            console=console,
            state_path=self.state_path,
            throttle_seconds=60,
        )

        manager.enable(source="test")
        manager.send(event="risk.test", message="Throttle check", severity="WARNING")
        manager.send(event="risk.test", message="Throttle check", severity="WARNING")
        output = console.export_text()
        self.assertEqual(output.count("Throttle check"), 1)
        status = manager.status()
        self.assertEqual(len(status["recent_alerts"]), 1)


if __name__ == "__main__":  # pragma: no cover - test module entry point
    unittest.main()

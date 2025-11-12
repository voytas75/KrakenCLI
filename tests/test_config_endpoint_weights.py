"""Tests for Config endpoint weight parsing and cost lookups."""

from __future__ import annotations

import json

from config import Config


def _stub_config(weights: dict[str, float]):
    cfg = Config.__new__(Config)
    cfg.endpoint_weights = weights
    return cfg


def test_parse_endpoint_weights_from_string() -> None:
    payload = json.dumps({"private/AddOrder": 4, "public/*": 1.5})
    weights = Config._parse_endpoint_weights(payload)
    assert weights == {"private/AddOrder": 4.0, "public/*": 1.5}


def test_get_endpoint_cost_falls_back_to_defaults() -> None:
    cfg = _stub_config({"private/*": 2.0, "*": 1.2})
    assert cfg.get_endpoint_cost("private/AddOrder", True) == 2.0
    assert cfg.get_endpoint_cost("public/Ticker", False) == 1.2


def test_numeric_converters_handle_invalid_values() -> None:
    assert Config._to_bool("yes") is True
    assert Config._to_bool("no") is False
    assert Config._to_int("5", 1) == 5
    assert Config._to_int("", 2) == 2
    assert Config._to_float("1.5", 0.0) == 1.5
    assert Config._to_float("", 0.5) == 0.5


def test_alerts_enabled_detects_channels() -> None:
    cfg = Config.__new__(Config)
    cfg.alert_webhook_url = "https://example"
    cfg.alert_email_recipients = []
    assert cfg.alerts_enabled() is True

    cfg.alert_webhook_url = None
    cfg.alert_email_recipients = []
    assert cfg.alerts_enabled() is False

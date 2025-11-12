"""Coverage-oriented tests for utils.helpers functions."""

from __future__ import annotations

import datetime as dt

from utils import helpers


def test_format_currency_handles_strings() -> None:
    value = helpers.format_currency("1234.5", currency="USD", decimals=1)
    assert "USD" in value


def test_format_percentage_and_volume() -> None:
    assert helpers.format_percentage(0.123, decimals=1) == "0.1%"
    assert "BTC" in helpers.format_volume("0.123456", asset="BTC")
    assert helpers.format_volume("10", asset="ALGO") == "10.000000 ALGO"


def test_format_timestamp_handles_seconds() -> None:
    epoch = int(dt.datetime(2024, 1, 1, tzinfo=dt.timezone.utc).timestamp())
    formatted = helpers.format_timestamp(epoch)
    assert "2024" in formatted

    ms_epoch = int(epoch * 1000)
    formatted_ms = helpers.format_timestamp(ms_epoch)
    assert "2024" in formatted_ms


def test_validate_trading_pair_variants() -> None:
    assert helpers.validate_trading_pair("XBTUSD") is True
    assert helpers.validate_trading_pair("XXBTZUSD") is False
    assert helpers.validate_trading_pair("bad") is False


def test_calculate_profit_loss_and_risk_color() -> None:
    pnl = helpers.calculate_profit_loss({"cost": "100.0", "fee": "1.5"})
    assert pnl == 98.5
    assert helpers.get_risk_level_color(0.2) == "green"
    assert helpers.get_risk_level_color(0.9) == "red"
    assert helpers.calculate_profit_loss({}) == 0.0


def test_format_order_summary_and_sanitize_input() -> None:
    order = {"descr": {"pair": "XBTUSD", "type": "buy", "ordertype": "limit", "price": "120"}, "vol": "1"}
    summary = helpers.format_order_summary(order)
    assert "BUY" in summary
    assert helpers.sanitize_input("<danger>") == "danger"


def test_safe_float_convert_and_format_asset_amount() -> None:
    assert helpers.safe_float_convert("$1,234.50") == 1234.5
    assert helpers.format_asset_amount("1,000", "USD") == "1,000"
    assert helpers.format_asset_amount("bad", "USD") == "bad"


def test_format_currency_fallback(monkeypatch) -> None:
    def _raise_error(*_args, **_kwargs):
        raise helpers.locale.Error("unsupported locale")

    monkeypatch.setattr(helpers.locale, "setlocale", _raise_error)
    value = helpers.format_currency(1000.0, currency="USD", decimals=2)
    assert value.startswith("USD")

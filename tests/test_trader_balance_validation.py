"""Tests for Trader balance validation using Kraken-style asset codes."""

from __future__ import annotations

from typing import Any, Dict

import pytest

from trading.trader import Trader


class _DummyClient:
    """Minimal Kraken client stub returning predetermined balances."""

    def __init__(self, balances: Dict[str, Any]):
        self._balances = balances

    # Trading endpoints -------------------------------------------------
    def add_order(self, **_kwargs: Any) -> Dict[str, Any]:
        return {"result": {"txid": ["TEST123"]}}

    def cancel_order(self, _txid: str) -> Dict[str, Any]:
        return {"result": {"count": 1}}

    def cancel_all_orders(self) -> Dict[str, Any]:
        return {"result": {"count": 2}}

    def get_ticker(self, pair: str) -> Dict[str, Any]:
        return {"result": {pair: {"c": ["1000.0", ""]}}}

    def get_order_book(self, pair: str, _count: int) -> Dict[str, Any]:
        return {"result": {pair: {"asks": [], "bids": []}}}

    def get_account_balance(self) -> Dict[str, Dict[str, Any]]:
        return {"result": self._balances}

    def get_trade_balance(self, asset: str) -> Dict[str, Any]:
        return {"result": {asset: "1000.0"}}


class _ZeroResultClient(_DummyClient):
    def cancel_order(self, _txid: str) -> Dict[str, Any]:
        return {"result": {"count": 0}}

    def cancel_all_orders(self) -> Dict[str, Any]:
        return {"result": {"count": 0}}

    def get_ticker(self, pair: str) -> Dict[str, Any]:
        return {"result": {}}


@pytest.mark.parametrize(
    "pair,order_type,volume,price,balances,expected",
    [
        (
            "XXBTZUSD",
            "buy",
            0.01,
            50000.0,
            {"ZUSD": "750.0"},
            True,
        ),
        (
            "XXBTZUSD",
            "buy",
            0.01,
            50000.0,
            {"USD": "400.0"},
            False,
        ),
        (
            "XXBTZUSD",
            "sell",
            0.5,
            None,
            {"XXBT": "0.75"},
            True,
        ),
        (
            "XETHZUSDT",
            "sell",
            2.0,
            None,
            {"XETH": "1.5", "ETH": "0.25"},
            False,
        ),
        (
            "ETHUSD",
            "buy",
            1.0,
            1800.0,
            {"USD": "1000.0"},
            False,
        ),
        (
            "ETHUSD",
            "buy",
            1.0,
            1800.0,
            {"USD": "1900.0"},
            True,
        ),
    ],
)
def test_validate_sufficient_balance_handles_prefixed_assets(
    pair: str,
    order_type: str,
    volume: float,
    price: float | None,
    balances: Dict[str, Any],
    expected: bool,
) -> None:
    trader = Trader(api_client=_DummyClient(balances))

    assert trader.validate_sufficient_balance(
        pair=pair,
        type=order_type,
        volume=volume,
        price=price,
    ) is expected


def test_validate_sufficient_balance_returns_false_when_insufficient() -> None:
    trader = Trader(api_client=_DummyClient({"ZUSD": "50"}))

    assert trader.validate_sufficient_balance(
        pair="XBTUSD",
        type="buy",
        volume=1.0,
        price=100.0,
    ) is False

    assert trader.validate_sufficient_balance(
        pair="XBTUSD",
        type="sell",
        volume=1.0,
        price=None,
    ) is False


def test_place_order_executes_and_returns_result() -> None:
    api_client = _DummyClient({"ZUSD": "1000"})
    trader = Trader(api_client=api_client)

    result = trader.place_order(
        pair="XBTUSD",
        type="buy",
        ordertype="market",
        volume=0.1,
        validate=False,
    )

    assert result["result"]["txid"][0] == "TEST123"

    validate_result = trader.place_order(
        pair="XBTUSD",
        type="buy",
        ordertype="market",
        volume=0.05,
        validate=True,
    )
    assert validate_result["result"]["txid"][0] == "TEST123"


def test_cancel_order_returns_true_when_count_positive() -> None:
    api_client = _DummyClient({})
    trader = Trader(api_client=api_client)

    assert trader.cancel_order("TXID123") is True


def test_cancel_all_orders_returns_true() -> None:
    api_client = _DummyClient({})
    trader = Trader(api_client=api_client)

    assert trader.cancel_all_orders() is True


def test_cancel_operations_handle_zero_counts() -> None:
    trader = Trader(api_client=_ZeroResultClient({}))

    assert trader.cancel_order("TXID123") is False
    assert trader.cancel_all_orders() is True


def test_get_market_data_returns_payload() -> None:
    api_client = _DummyClient({})
    trader = Trader(api_client=api_client)

    data = trader.get_market_data("XBTUSD")
    assert data and data["c"][0] == "1000.0"


def test_get_market_data_handles_missing_payload() -> None:
    trader = Trader(api_client=_ZeroResultClient({}))
    assert trader.get_market_data("XBTUSD") is None


def test_get_order_book_returns_payload() -> None:
    api_client = _DummyClient({})
    trader = Trader(api_client=api_client)

    payload = trader.get_order_book("XBTUSD")
    assert payload == {"asks": [], "bids": []}


def test_calculate_order_value_defaults_to_market_price() -> None:
    api_client = _DummyClient({})
    trader = Trader(api_client=api_client)

    value = trader.calculate_order_value("XBTUSD", volume=0.5)
    assert value == pytest.approx(500.0)

    explicit = trader.calculate_order_value("XBTUSD", volume=0.25, price=2000.0)
    assert explicit == pytest.approx(500.0)


def test_estimate_fees_returns_expected_trade_value() -> None:
    api_client = _DummyClient({})
    trader = Trader(api_client=api_client)

    details = trader.estimate_fees("XBTUSD", volume=0.25, ordertype="market")
    assert details["trade_value"] == pytest.approx(250.0)


def test_validate_order_params_rejects_invalid_types() -> None:
    api_client = _DummyClient({})
    trader = Trader(api_client=api_client)

    with pytest.raises(ValueError):
        trader.place_order(
            pair="XBTUSD",
            type="hold",  # invalid
            ordertype="market",
            volume=1.0,
        )


def test_validate_order_params_requires_positive_volume() -> None:
    api_client = _DummyClient({})
    trader = Trader(api_client=api_client)

    with pytest.raises(ValueError):
        trader.place_order(
            pair="XBTUSD",
            type="buy",
            ordertype="market",
            volume=0,
        )


def test_limit_and_stop_orders_require_prices() -> None:
    api_client = _DummyClient({})
    trader = Trader(api_client=api_client)

    with pytest.raises(ValueError):
        trader.place_order(
            pair="XBTUSD",
            type="buy",
            ordertype="limit",
            volume=1.0,
        )

    with pytest.raises(ValueError):
        trader.place_order(
            pair="XBTUSD",
            type="buy",
            ordertype="stop-loss",
            volume=1.0,
            price=21000.0,
        )


def test_trader_internal_helpers() -> None:
    api_client = _DummyClient({})
    trader = Trader(api_client=api_client)

    base, quote = trader._split_pair("XXBTZUSD")
    assert base == "XXBT" and quote == "ZUSD"

    keys = trader._candidate_balance_keys("XXBT")
    assert "XXBT" in keys and "XBT" in keys

    trader.refresh_state()  # should invoke cache clear methods safely

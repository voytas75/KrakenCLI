"""Tests for Trader balance validation using Kraken-style asset codes."""

from __future__ import annotations

from typing import Any, Dict

import pytest

from trading.trader import Trader


class _DummyClient:
    """Minimal Kraken client stub returning predetermined balances."""

    def __init__(self, balances: Dict[str, Any]):
        self._balances = balances

    def get_account_balance(self) -> Dict[str, Dict[str, Any]]:
        return {"result": self._balances}


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

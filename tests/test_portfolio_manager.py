"""Tests for PortfolioManager value calculations and caching."""

from __future__ import annotations

from typing import Any, Dict

from portfolio.portfolio_manager import PortfolioManager


class _StubApiClient:
    def __init__(self) -> None:
        self.ticker_calls: list[str] = []
        self.trade_volume_requests: list[Any] = []

    def get_asset_info(self) -> Dict[str, Any]:
        return {"result": {"XXBT": {"altname": "XBT"}}}

    def get_ticker(self, pair: str) -> Dict[str, Any]:
        self.ticker_calls.append(pair)
        return {"result": {pair: {"c": ["20000.0", ""], "b": ["0", "0"], "a": ["0", "0"]}}}

    def get_account_balance(self) -> Dict[str, Any]:
        return {"result": {"XXBT": "0.5", "ZUSD": "100"}}

    def get_trade_balance(self, asset: str = "ZUSD") -> Dict[str, Any]:
        return {"result": {asset: "1200.0"}}

    def get_open_orders(self, force_refresh: bool = False) -> Dict[str, Any]:
        return {"result": {"open": {}}}

    def get_open_positions(self) -> Dict[str, Any]:
        return {"result": {"XXBTZUSD": {"type": "long", "vol": "0.1", "net": "5"}}}

    def get_trade_history(self, trades: bool = True, start: Any = None, end: Any = None) -> Dict[str, Any]:
        return {"result": {"trades": {"1": {"cost": "50", "fee": "0.1", "vol": "0.25"}}}}

    def get_closed_orders(self, trades: bool = True) -> Dict[str, Any]:
        return {"result": {"closed": {"1": {"vol": "0.1"}}}}

    def get_trade_volume(self, pair=None, include_fee_info: bool = True) -> Dict[str, Any]:
        self.trade_volume_requests.append(pair)
        return {
            "result": {
                "currency": "ZUSD",
                "volume": "1500.5",
                "fees": {
                    "XXBTZUSD": {"fee": "0.002", "minfee": "0.001", "nextfee": "0.0025", "nextvolume": "200000"}
                },
                "fees_maker": {
                    "XXBTZUSD": {"fee": "0.0015", "minfee": "0.001", "nextfee": "0.0010", "nextvolume": "50000"}
                },
            }
        }


def test_portfolio_summary_calculates_usd_values() -> None:
    manager = PortfolioManager(api_client=_StubApiClient())
    summary = manager.get_portfolio_summary(refresh=True)

    assert summary["total_usd_value"] is not None
    assert summary["open_positions_count"] == 1
    assert summary["open_orders_count"] == 1  # underlying open dict counts as 1 entry
    assert summary["total_assets"] == 2
    assert summary["fee_status"]["currency"] == "ZUSD"
    assert summary["fee_status"]["maker_fee"] == 0.0015
    assert manager.api_client.trade_volume_requests
    assert isinstance(manager.api_client.trade_volume_requests[0], list)


def test_refresh_portfolio_resets_price_cache() -> None:
    api_client = _StubApiClient()
    manager = PortfolioManager(api_client=api_client)

    value = manager.get_usd_value("XXBT", 0.5)
    assert value is not None
    assert api_client.ticker_calls

    api_client.ticker_calls.clear()
    manager.refresh_portfolio()
    manager.get_usd_value("XXBT", 0.25)
    assert api_client.ticker_calls  # ticker called again after refresh


def test_portfolio_helpers_expose_balances_and_history() -> None:
    manager = PortfolioManager(api_client=_StubApiClient())

    balances = manager.get_balances()
    assert balances["XXBT"] == "0.5"

    trade_balance = manager.get_trade_balance("ZUSD")
    assert trade_balance["ZUSD"] == "1200.0"

    open_orders = manager.get_open_orders()
    assert "open" in open_orders

    open_positions = manager.get_open_positions()
    assert open_positions

    trade_history = manager.get_trade_history()
    assert trade_history and trade_history[0]["cost"] == "50"
    assert manager.get_trade_history(limit=0) == []

    closed_orders = manager.get_closed_orders()
    assert closed_orders and closed_orders[0]["vol"] == "0.1"
    assert manager.get_closed_orders(limit=0) == []

    total_value = manager.get_total_usd_value()
    assert total_value is not None

    performance = manager.get_performance_metrics()
    assert performance["total_trades"] == 1

    assert manager.get_usd_value("UNKNOWN", 1.0) is not None

    fee_status = manager.get_fee_status()
    assert fee_status["maker_fee"] == 0.0015
    assert fee_status["thirty_day_volume"] == 1500.5


def test_portfolio_helper_pair_building() -> None:
    manager = PortfolioManager(api_client=_StubApiClient())

    normalized = manager._normalize_asset_symbol("XXDG")
    assert normalized == "XDG"

    pairs = manager._build_price_pairs("XXDG")
    assert pairs[0].endswith("USD")

    deduped = manager._dedupe_preserve_order(["XDG", "XDG", "USD"])
    assert deduped == ["XDG", "USD"]

    price = manager._get_price_for_pairs(["XXBTZUSD", "XBTUSD"])
    assert price is not None


class _NoPriceApiClient(_StubApiClient):
    def get_ticker(self, pair: str) -> Dict[str, Any]:
        return {"result": {pair: {"c": ["", ""], "b": ["0", "0"], "a": ["0", "0"]}}}


def test_portfolio_summary_tracks_missing_assets() -> None:
    manager = PortfolioManager(api_client=_NoPriceApiClient())
    summary = manager.get_portfolio_summary(refresh=True)
    assert summary["missing_assets"]
    assert summary["total_usd_value"] is not None


class _ErrorApiClient(_StubApiClient):
    def get_open_orders(self, force_refresh: bool = False) -> Dict[str, Any]:
        raise RuntimeError("boom")

    def get_open_positions(self) -> Dict[str, Any]:
        raise RuntimeError("boom")


def test_portfolio_manages_api_errors() -> None:
    manager = PortfolioManager(api_client=_ErrorApiClient())
    assert manager.get_open_orders() == {}
    assert manager.get_open_positions() == {}

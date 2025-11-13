"""Additional coverage for trading CLI commands."""

from __future__ import annotations

from typing import Any, Dict, Optional

from click.testing import CliRunner

import kraken_cli


class _StubApiClient:
    def __init__(self, balances: Dict[str, str] | None = None) -> None:
        self._balances = balances or {"ZUSD": "25.0", "XXBT": "0.05"}

    def get_account_balance(self) -> Dict[str, Dict[str, str]]:
        return {"result": self._balances}


class _InsufficientTrader:
    last_instance: "_InsufficientTrader" | None = None

    def __init__(self, api_client: Any) -> None:
        self.api_client = api_client
        _InsufficientTrader.last_instance = self

    def place_order(self, **_kwargs: Any) -> Dict[str, Any]:  # pragma: no cover - method raises below
        raise Exception("Insufficient funds")


class _SuccessTrader:
    last_instance: "_SuccessTrader" | None = None

    def __init__(self, api_client: Any) -> None:
        self.api_client = api_client
        self.calls: list[Dict[str, Any]] = []
        _SuccessTrader.last_instance = self

    def place_order(self, **kwargs: Any) -> Dict[str, Any]:
        self.calls.append(kwargs)
        return {"result": {"txid": ["TST123"]}}


def _install_trader(monkeypatch, trader_cls):
    monkeypatch.setattr("kraken_cli.Trader", trader_cls)
    monkeypatch.setattr("cli.trading.Trader", trader_cls)


def _install_api_client(monkeypatch, factory):
    monkeypatch.setattr("kraken_cli.KrakenAPIClient", factory)
    monkeypatch.setattr("cli.trading.KrakenAPIClient", factory)


def test_order_conflicting_flags_short_circuits(monkeypatch) -> None:
    runner = CliRunner()

    _install_api_client(monkeypatch, lambda *args, **kwargs: _StubApiClient())
    _install_trader(monkeypatch, _SuccessTrader)

    result = runner.invoke(
        kraken_cli.cli,
        [
            "order",
            "--pair",
            "XBTUSD",
            "--side",
            "buy",
            "--volume",
            "1",
            "--execute",
            "--validate",
        ],
        catch_exceptions=False,
    )

    assert result.exit_code == 0
    assert "Conflicting flags" in result.output


def test_order_insufficient_funds_displays_balances(monkeypatch) -> None:
    runner = CliRunner()

    _install_api_client(monkeypatch, lambda *args, **kwargs: _StubApiClient())
    _install_trader(monkeypatch, _InsufficientTrader)

    result = runner.invoke(
        kraken_cli.cli,
        [
            "order",
            "--pair",
            "XBTUSD",
            "--side",
            "buy",
            "--volume",
            "1",
            "--execute",
            "--yes",
        ],
        catch_exceptions=False,
    )

    assert result.exit_code == 0
    assert "insufficient funds" in result.output.lower()
    assert "ZUSD" in result.output


def test_order_dry_run_success(monkeypatch) -> None:
    runner = CliRunner()
    trader = _SuccessTrader(_StubApiClient())

    _install_api_client(monkeypatch, lambda *args, **kwargs: trader.api_client)

    def _create_trader(api_client):
        return trader

    _install_trader(monkeypatch, _create_trader)  # type: ignore[arg-type]

    result = runner.invoke(
        kraken_cli.cli,
        [
            "order",
            "--pair",
            "ETHUSD",
            "--side",
            "sell",
            "--volume",
            "0.5",
        ],
        catch_exceptions=False,
    )

    assert result.exit_code == 0
    assert "Order validated successfully" in result.output
    assert _SuccessTrader.last_instance and _SuccessTrader.last_instance.calls
    assert _SuccessTrader.last_instance.calls[0]["validate"] is True


class _NoneTrader:
    def __init__(self, api_client: Any) -> None:
        self.api_client = api_client

    def place_order(self, **kwargs: Any) -> Dict[str, Any]:
        return {}


class _ErrorTrader:
    def __init__(self, api_client: Any) -> None:
        self.api_client = api_client

    def place_order(self, **kwargs: Any) -> Dict[str, Any]:
        raise Exception("Service unavailable")


def test_order_missing_price_validation(monkeypatch) -> None:
    runner = CliRunner()
    _install_api_client(monkeypatch, lambda *args, **kwargs: _StubApiClient())
    _install_trader(monkeypatch, _SuccessTrader)

    result = runner.invoke(
        kraken_cli.cli,
        [
            "order",
            "--pair",
            "ETHUSD",
            "--side",
            "buy",
            "--volume",
            "1",
            "--order-type",
            "limit",
        ],
        catch_exceptions=False,
    )

    assert "Limit price required" in result.output


def test_order_invalid_price_format(monkeypatch) -> None:
    runner = CliRunner()
    _install_api_client(monkeypatch, lambda *args, **kwargs: _StubApiClient())
    _install_trader(monkeypatch, _SuccessTrader)

    result = runner.invoke(
        kraken_cli.cli,
        [
            "order",
            "--pair",
            "ETHUSD",
            "--side",
            "buy",
            "--volume",
            "1",
            "--price",
            "abc",
        ],
        catch_exceptions=False,
    )

    assert "Invalid price value" in result.output


def test_order_stop_loss_requires_secondary_price(monkeypatch) -> None:
    runner = CliRunner()
    _install_api_client(monkeypatch, lambda *args, **kwargs: _StubApiClient())
    _install_trader(monkeypatch, _SuccessTrader)

    result = runner.invoke(
        kraken_cli.cli,
        [
            "order",
            "--pair",
            "ETHUSD",
            "--side",
            "sell",
            "--volume",
            "1",
            "--order-type",
            "stop-loss",
            "--price",
            "1200",
        ],
        catch_exceptions=False,
    )

    assert "Secondary price required" in result.output


def test_order_place_order_returns_empty(monkeypatch) -> None:
    runner = CliRunner()
    _install_api_client(monkeypatch, lambda *args, **kwargs: _StubApiClient())
    _install_trader(monkeypatch, _NoneTrader)

    result = runner.invoke(
        kraken_cli.cli,
        [
            "order",
            "--pair",
            "ETHUSD",
            "--side",
            "buy",
            "--volume",
            "1",
            "--execute",
            "--yes",
        ],
        catch_exceptions=False,
    )

    assert "Failed to place order" in result.output


def test_order_general_error(monkeypatch) -> None:
    runner = CliRunner()
    _install_api_client(monkeypatch, lambda *args, **kwargs: _StubApiClient())
    _install_trader(monkeypatch, _ErrorTrader)

    result = runner.invoke(
        kraken_cli.cli,
        [
            "order",
            "--pair",
            "ETHUSD",
            "--side",
            "buy",
            "--volume",
            "1",
            "--execute",
            "--yes",
        ],
        catch_exceptions=False,
    )

    assert "Error placing order" in result.output


class _PortfolioStub:
    def __init__(self):
        self.trade_history = [
            {"time": "2025-11-13", "pair": "ETHUSD", "type": "buy", "price": "2000", "vol": "0.5", "cost": "1000"}
        ]

    def get_trade_history(self):
        return self.trade_history

    def get_open_orders(self, refresh: bool = False):  # pragma: no cover - not used here
        return {}


def test_orders_command_trade_history(monkeypatch) -> None:
    runner = CliRunner()

    portfolio = _PortfolioStub()

    monkeypatch.setattr("kraken_cli.PortfolioManager", lambda *args, **kwargs: portfolio)
    monkeypatch.setattr("cli.trading.PortfolioManager", lambda *args, **kwargs: portfolio)
    _install_api_client(monkeypatch, lambda *args, **kwargs: _StubApiClient())
    _install_trader(monkeypatch, _SuccessTrader)

    result = runner.invoke(
        kraken_cli.cli,
        ["orders", "--trades"],
        catch_exceptions=False,
    )

    assert result.exit_code == 0
    assert "Trade History" in result.output
    assert "ETHUSD" in result.output


class _OrdersPortfolio:
    def get_trade_history(self):  # pragma: no cover - not required here
        return []

    def get_open_orders(self, refresh: bool = False):
        return {
            "open": {
                "OID123": {
                    "opentm": 1700000000,
                    "descr": {
                        "pair": "ETHUSD",
                        "type": "buy",
                        "ordertype": "limit",
                        "price": "2000",
                    },
                    "vol": "1.0",
                }
            }
        }


def test_orders_command_verbose_debug(monkeypatch) -> None:
    runner = CliRunner()
    portfolio = _OrdersPortfolio()

    monkeypatch.setattr("kraken_cli.PortfolioManager", lambda *args, **kwargs: portfolio)
    monkeypatch.setattr("cli.trading.PortfolioManager", lambda *args, **kwargs: portfolio)
    _install_api_client(monkeypatch, lambda *args, **kwargs: _StubApiClient())
    _install_trader(monkeypatch, _SuccessTrader)

    result = runner.invoke(
        kraken_cli.cli,
        ["orders", "--verbose"],
        catch_exceptions=False,
    )

    assert "Debug" in result.output
    assert "Open Orders" in result.output


class _CancelTrader:
    def __init__(self, api_client: Any) -> None:
        self.api_client = api_client
        self.calls: list[tuple[str, Optional[str]]] = []

    def cancel_order(self, txid: str) -> bool:
        self.calls.append(("order", txid))
        return True

    def cancel_all_orders(self) -> bool:
        self.calls.append(("all", None))
        return False


def test_cancel_requires_option(monkeypatch) -> None:
    runner = CliRunner()
    _install_api_client(monkeypatch, lambda *args, **kwargs: _StubApiClient())
    _install_trader(monkeypatch, _CancelTrader)

    result = runner.invoke(kraken_cli.cli, ["cancel"], catch_exceptions=False)

    assert "Please specify --cancel-all or --txid" in result.output


def test_cancel_specific_order_success(monkeypatch) -> None:
    runner = CliRunner()
    trader = _CancelTrader(_StubApiClient())

    _install_api_client(monkeypatch, lambda *args, **kwargs: trader.api_client)
    _install_trader(monkeypatch, lambda api_client: trader)

    result = runner.invoke(
        kraken_cli.cli,
        ["cancel", "--txid", "OID123"],
        catch_exceptions=False,
    )

    assert "Order cancelled successfully" in result.output
    assert trader.calls == [("order", "OID123")]


def test_cancel_all_orders_failure(monkeypatch) -> None:
    runner = CliRunner()
    trader = _CancelTrader(_StubApiClient())

    _install_api_client(monkeypatch, lambda *args, **kwargs: trader.api_client)
    _install_trader(monkeypatch, lambda api_client: trader)

    result = runner.invoke(
        kraken_cli.cli,
        ["cancel", "--cancel-all"],
        catch_exceptions=False,
    )

    assert "Failed to cancel orders" in result.output
    assert trader.calls == [("all", None)]

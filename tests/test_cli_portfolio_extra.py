"""Additional coverage for portfolio CLI command."""

from __future__ import annotations

import json

from click.testing import CliRunner

import kraken_cli


class _StubPortfolio:
    def __init__(self, summary, positions):
        self.summary = summary
        self.positions = positions

    def get_portfolio_summary(self, refresh: bool = False):
        return self.summary

    def get_open_positions(self):
        return self.positions


def _install_portfolio(monkeypatch, portfolio_instance):
    monkeypatch.setattr("kraken_cli.PortfolioManager", lambda *args, **kwargs: portfolio_instance)
    monkeypatch.setattr("cli.portfolio.PortfolioManager", lambda *args, **kwargs: portfolio_instance)


def _install_api_client(monkeypatch):
    monkeypatch.setattr("kraken_cli.KrakenAPIClient", lambda *args, **kwargs: object())
    monkeypatch.setattr("cli.portfolio.KrakenAPIClient", lambda *args, **kwargs: object())


def test_portfolio_command_handles_missing_assets(monkeypatch) -> None:
    runner = CliRunner()

    summary = {
        "significant_assets": [
            {"asset": "XXBT", "amount": "0.10", "usd_value": 6000.0},
            {"asset": "XETH", "amount": "0.00", "usd_value": 0.0},
            {"asset": "FANTOM", "amount": "5", "usd_value": None},
        ],
        "total_usd_value": 6500.0,
        "missing_assets": ["FANTOM"],
        "fee_status": {},
    }
    positions = {
        "XBTUSD": {"type": "long", "vol": "0.1", "net": "250"},
    }

    portfolio_stub = _StubPortfolio(summary, positions)

    _install_api_client(monkeypatch)
    _install_portfolio(monkeypatch, portfolio_stub)

    result = runner.invoke(kraken_cli.cli, ["portfolio"], catch_exceptions=False)

    assert result.exit_code == 0
    assert "Total Portfolio Value" in result.output
    assert "No USD pricing available" in result.output
    assert "Open Positions" in result.output


def test_portfolio_command_save_snapshot(monkeypatch, tmp_path) -> None:
    runner = CliRunner()

    summary = {
        "significant_assets": [
            {"asset": "XXBT", "amount": "0.10", "usd_value": 6200.0},
        ],
        "total_usd_value": 6200.0,
        "missing_assets": [],
        "open_positions_count": 0,
        "open_orders_count": 0,
        "total_assets": 1,
        "fee_status": {},
    }

    portfolio_stub = _StubPortfolio(summary, positions={})

    _install_api_client(monkeypatch)
    _install_portfolio(monkeypatch, portfolio_stub)

    monkeypatch.setattr("cli.portfolio.SNAPSHOT_DIR", tmp_path)

    result = runner.invoke(kraken_cli.cli, ["portfolio", "--save"], catch_exceptions=False)

    assert result.exit_code == 0

    files = list(tmp_path.glob("*.json"))
    assert len(files) == 1
    saved_payload = json.loads(files[0].read_text(encoding="utf-8"))
    assert saved_payload["total_usd_value"] == summary["total_usd_value"]


def test_portfolio_command_compare_snapshot(monkeypatch, tmp_path) -> None:
    runner = CliRunner()

    current_summary = {
        "significant_assets": [
            {"asset": "XXBT", "amount": "0.11", "usd_value": 6200.0},
        ],
        "total_usd_value": 6200.0,
        "missing_assets": [],
        "open_positions_count": 0,
        "open_orders_count": 0,
        "total_assets": 1,
        "fee_status": {},
    }

    snapshot_summary = {
        "significant_assets": [
            {"asset": "XXBT", "amount": "0.10", "usd_value": 6000.0},
        ],
        "total_usd_value": 6000.0,
        "missing_assets": [],
        "open_positions_count": 0,
        "open_orders_count": 0,
        "total_assets": 1,
        "fee_status": {},
    }

    snapshot_path = tmp_path / "snapshot.json"
    snapshot_path.write_text(json.dumps(snapshot_summary), encoding="utf-8")

    portfolio_stub = _StubPortfolio(current_summary, positions={})

    _install_api_client(monkeypatch)
    _install_portfolio(monkeypatch, portfolio_stub)

    result = runner.invoke(
        kraken_cli.cli,
        ["portfolio", "--compare", str(snapshot_path)],
        catch_exceptions=False,
    )

    assert result.exit_code == 0
    assert "Portfolio Comparison" in result.output
    assert "+USD 200.00" in result.output
    assert "+0.01" in result.output


def test_portfolio_command_displays_fee_status(monkeypatch) -> None:
    runner = CliRunner()

    summary = {
        "significant_assets": [
            {"asset": "XXBT", "amount": "0.10", "usd_value": 6200.0},
        ],
        "total_usd_value": 6200.0,
        "missing_assets": [],
        "open_positions_count": 0,
        "open_orders_count": 0,
        "total_assets": 1,
        "fee_status": {
            "currency": "ZUSD",
            "thirty_day_volume": 1500.5,
            "maker_fee": 0.0015,
            "taker_fee": 0.0020,
            "next_fee": 0.0010,
            "next_volume": 50000,
        },
    }

    portfolio_stub = _StubPortfolio(summary, positions={})

    _install_api_client(monkeypatch)
    _install_portfolio(monkeypatch, portfolio_stub)

    result = runner.invoke(kraken_cli.cli, ["portfolio"], catch_exceptions=False)

    assert result.exit_code == 0
    assert "Fee Status" in result.output
    assert "0.1500%" in result.output
    assert "USD 1,500.50" in result.output

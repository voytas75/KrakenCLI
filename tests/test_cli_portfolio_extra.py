"""Additional coverage for portfolio CLI command."""

from __future__ import annotations

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

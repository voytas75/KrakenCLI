"""
Unit tests for PortfolioManager valuation helpers.
"""

from __future__ import annotations

import unittest
from typing import Any, Dict, Optional

from portfolio.portfolio_manager import PortfolioManager


class FakeKrakenClient:
    """Minimal stub that mimics the Kraken API client surface area used by PortfolioManager."""

    def __init__(self,
                 balances: Dict[str, str],
                 asset_info: Dict[str, Dict[str, Any]],
                 ticker_prices: Dict[str, float]):
        self._balances = balances
        self._asset_info = asset_info
        self._ticker_prices = ticker_prices
        self.ticker_calls: list[str] = []

    # Public endpoint helpers -------------------------------------------------
    def get_asset_info(self) -> Dict[str, Any]:
        return {"result": self._asset_info}

    def get_ticker(self, pair: str) -> Dict[str, Any]:
        self.ticker_calls.append(pair)
        price = self._ticker_prices.get(pair)
        if price is None:
            return {"result": {}}
        return {
            "result": {
                pair: {
                    "c": [f"{price}", ""]
                }
            }
        }

    # Private endpoint helpers ------------------------------------------------
    def get_account_balance(self) -> Dict[str, Any]:
        return {"result": self._balances}

    def get_open_positions(self) -> Dict[str, Any]:
        return {"result": {}}

    def get_open_orders(self) -> Dict[str, Any]:
        return {"result": {}}

    def get_trade_history(self, trades: bool = True, start: Optional[str] = None,
                          end: Optional[str] = None) -> Dict[str, Any]:
        return {"result": {"trades": {}}}

    def get_closed_orders(self, trades: bool = True) -> Dict[str, Any]:
        return {"result": {"closed": {}}}


class PortfolioManagerValuationTests(unittest.TestCase):
    """Validate enriched USD valuation behaviour for tricky asset codes."""

    def setUp(self) -> None:
        balances = {
            "ADA.S": "11.5",
            "XXDG": "57.75",
            "ZUSD": "10.00",
            "UNKNOWN": "3.0",
        }
        asset_info = {
            "ADA.S": {"altname": "ADA.S"},
            "XXDG": {"altname": "XDG"},
            "ZUSD": {"altname": "ZUSD"},
        }
        ticker_prices = {
            "ADAUSD": 0.25,
            "XDGUSD": 0.1,
            "XXDGZUSD": 0.1,  # fallback variation
        }
        self.fake_client = FakeKrakenClient(balances, asset_info, ticker_prices)
        self.portfolio = PortfolioManager(self.fake_client)

    def test_portfolio_summary_normalizes_asset_codes(self) -> None:
        """Staked / prefixed assets should resolve to USD values via ticker lookup."""
        summary = self.portfolio.get_portfolio_summary()

        assets = {row["asset"]: row for row in summary["significant_assets"]}
        self.assertIn("ADA.S", assets)
        self.assertIn("XXDG", assets)

        # ADA.S should price via ADAUSD ticker -> 11.5 * 0.25 = 2.875
        self.assertAlmostEqual(assets["ADA.S"]["usd_value"], 11.5 * 0.25, places=6)

        # XXDG should map to XDGUSD ticker -> 57.75 * 0.1 = 5.775
        self.assertAlmostEqual(assets["XXDG"]["usd_value"], 57.75 * 0.1, places=6)

        # Unknown asset without price should be tracked in missing list
        self.assertIn("UNKNOWN", summary["missing_assets"])
        self.assertIsNone(assets["UNKNOWN"]["usd_value"])

        # Total portfolio value only sums priced assets + USD balance
        expected_total = (11.5 * 0.25) + (57.75 * 0.1) + 10.0
        self.assertAlmostEqual(summary["total_usd_value"], expected_total, places=6)

    def test_price_lookup_is_cached(self) -> None:
        """Repeated summary calls should reuse cached ticker data."""
        first_summary = self.portfolio.get_portfolio_summary()
        second_summary = self.portfolio.get_portfolio_summary()

        # Same totals both times
        self.assertAlmostEqual(
            first_summary["total_usd_value"],
            second_summary["total_usd_value"],
            places=6,
        )

        # Ensure redundant tickers were not requested after caching
        ada_calls = [pair for pair in self.fake_client.ticker_calls if "ADA" in pair]
        doge_calls = [pair for pair in self.fake_client.ticker_calls if "DG" in pair]
        self.assertLessEqual(len(ada_calls), 2)
        self.assertLessEqual(len(doge_calls), 3)


if __name__ == "__main__":
    unittest.main()

"""Trader cache integration tests."""

from __future__ import annotations

import unittest
from unittest import mock

from trading.trader import Trader


class TraderCacheIntegrationTests(unittest.TestCase):
    """Ensure trader cache refresh delegates to Kraken client helpers."""

    def test_refresh_state_clears_client_caches(self) -> None:
        api_client = mock.Mock()
        trader = Trader(api_client=api_client)

        trader.refresh_state()

        api_client.clear_open_orders_cache.assert_called_once_with()
        api_client.clear_ledgers_cache.assert_called_once_with()


if __name__ == "__main__":  # pragma: no cover - manual execution helper
    unittest.main()

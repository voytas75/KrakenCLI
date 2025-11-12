"""
CLI integration tests that exercise commands with mocked Kraken API responses.
"""

from __future__ import annotations

import json
import os
from contextlib import ExitStack
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Dict
from unittest import TestCase
from unittest.mock import patch

from click.testing import CliRunner

# Ensure Config sees credentials when module is imported.
os.environ.setdefault("KRAKEN_API_KEY", "TESTKEY123")
os.environ.setdefault("KRAKEN_API_SECRET", "TESTSECRET123")
os.environ.setdefault("KRAKEN_SANDBOX", "true")

import kraken_cli  # noqa: E402
from api.kraken_client import KrakenAPIClient  # noqa: E402


FIXTURE_DIR = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> Dict[str, Any]:
    """Return fixture content as a dictionary."""
    path = FIXTURE_DIR / name
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _ticker_response_for_pair(pair: str) -> Dict[str, Any]:
    """Return a ticker payload matching the requested pair."""
    # Use the live ETHUSD payload for market command coverage.
    if "ETH" in pair and "ETHW" not in pair:
        return load_fixture("ticker_ethusd.json")

    price_map = {
        "ADA": 0.25,
        "DOT": 5.50,
        "ETHW": 10.75,
        "LINK": 14.10,
        "SC": 0.01,
        "XDG": 0.10,
        "XXDG": 0.10,
        "XBT": 68000.0,
    }

    target_key = next(
        (key for key in price_map if key in pair),
        None,
    )

    if target_key is None:
        return {"error": [], "result": {}}

    price = price_map[target_key]
    return {
        "error": [],
        "result": {
            pair: {
                "c": [f"{price:.8f}", ""],
                "h": ["0", "0"],
                "l": ["0", "0"],
                "p": ["0", "0"],
                "v": ["0", "0"],
                "b": ["0", "0"],
                "a": ["0", "0"],
            }
        },
    }


class KrakenCliMockedTests(TestCase):
    """Exercise CLI commands using captured Kraken fixtures."""

    def setUp(self) -> None:
        self.runner = CliRunner()
        self.balance_fixture = load_fixture("account_balance.json")
        self.asset_info_fixture = load_fixture("asset_info.json")
        self.open_orders_fixture = load_fixture("open_orders.json")
        self.open_positions_fixture = load_fixture("open_positions.json")
        self.closed_orders_fixture = load_fixture("closed_orders.json")
        self.trade_history_fixture = load_fixture("trade_history.json")

    def _mock_api(self) -> ExitStack:
        """Patch Kraken API methods with fixture-backed responses."""
        stack = ExitStack()
        stack.enter_context(
            patch.object(
                KrakenAPIClient,
                "get_account_balance",
                return_value=self.balance_fixture,
            )
        )
        stack.enter_context(
            patch.object(
                KrakenAPIClient,
                "get_asset_info",
                return_value=self.asset_info_fixture,
            )
        )
        stack.enter_context(
            patch.object(
                KrakenAPIClient,
                "get_open_positions",
                return_value=self.open_positions_fixture,
            )
        )
        stack.enter_context(
            patch.object(
                KrakenAPIClient,
                "get_open_orders",
                return_value=self.open_orders_fixture,
            )
        )
        stack.enter_context(
            patch.object(
                KrakenAPIClient,
                "get_closed_orders",
                return_value=self.closed_orders_fixture,
            )
        )
        stack.enter_context(
            patch.object(
                KrakenAPIClient,
                "get_trade_history",
                return_value=self.trade_history_fixture,
            )
        )
        stack.enter_context(
            patch.object(
                KrakenAPIClient,
                "get_ticker",
                side_effect=_ticker_response_for_pair,
            )
        )
        return stack

    def test_portfolio_command_renders_assets(self) -> None:
        """Portfolio command should present balances using mocked data."""
        with self._mock_api():
            result = self.runner.invoke(
                kraken_cli.cli,
                ["portfolio"],
                catch_exceptions=False,
            )

        self.assertEqual(result.exit_code, 0, msg=result.output)
        self.assertIn("💼 Portfolio Overview", result.output)
        self.assertIn("Asset Balances", result.output)
        self.assertIn("XXDG", result.output)
        self.assertIn("ZUSD", result.output)
        self.assertIn("Total Portfolio Value", result.output)

    def test_ticker_command_uses_alternate_pair_keys(self) -> None:
        """Ticker command should display Rich panel with mocked payload."""
        with patch.object(
            KrakenAPIClient,
            "get_ticker",
            return_value=load_fixture("ticker_ethusd.json"),
        ):
            result = self.runner.invoke(
                kraken_cli.cli,
                ["ticker", "-p", "ETHUSD"],
                catch_exceptions=False,
            )

        self.assertEqual(result.exit_code, 0, msg=result.output)
        self.assertIn("Market Data", result.output)
        self.assertIn("Last Price", result.output)
        self.assertIn("24h High", result.output)

    def test_orders_command_surfaces_open_orders(self) -> None:
        """Orders command should summarise open orders via fixtures."""
        with self._mock_api():
            result = self.runner.invoke(
                kraken_cli.cli,
                ["orders", "--verbose"],
                catch_exceptions=False,
            )

        self.assertEqual(result.exit_code, 0, msg=result.output)
        self.assertIn("Open Orders", result.output)
        self.assertIn("ETHUSD", result.output)
        self.assertIn("0.01300000", result.output)

    def test_withdraw_command_requires_confirmation(self) -> None:
        """Withdraw command should confirm before submitting requests."""

        with patch.object(
            KrakenAPIClient,
            "request_withdrawal",
            return_value={"result": {"refid": "WD123"}},
        ) as withdraw_mock:
            result = self.runner.invoke(
                kraken_cli.cli,
                [
                    "withdraw",
                    "--asset",
                    "ZUSD",
                    "--key",
                    "Primary",
                    "--amount",
                    "1.50",
                ],
                input="y\n",
                catch_exceptions=False,
            )

        self.assertEqual(result.exit_code, 0, msg=result.output)
        self.assertIn("Withdrawal submitted successfully", result.output)
        self.assertGreaterEqual(withdraw_mock.call_count, 1)

        withdraw_mock.assert_called_with(
            asset="ZUSD",
            key="Primary",
            amount="1.50",
            address=None,
            otp=None,
        )

    def test_withdraw_retries_on_failure(self) -> None:
        """Withdraw command should retry transient failures before succeeding."""

        side_effects = [Exception("temporary failure"), {"result": {"refid": "WD123"}}]

        with patch("kraken_cli.time.sleep", return_value=None), \
                patch.object(
                    KrakenAPIClient,
                    "request_withdrawal",
                    side_effect=side_effects,
                ) as withdraw_mock:
            result = self.runner.invoke(
                kraken_cli.cli,
                [
                    "withdraw",
                    "--asset",
                    "ZUSD",
                    "--key",
                    "Primary",
                    "--amount",
                    "1.50",
                ],
                input="y\n",
                catch_exceptions=False,
            )

        self.assertEqual(result.exit_code, 0, msg=result.output)
        self.assertIn("Withdrawal submitted successfully", result.output)
        self.assertEqual(withdraw_mock.call_count, 2)

    def test_withdraw_status_lists_entries(self) -> None:
        """Withdraw command should list status entries when --status is used."""

        status_payload = {
            "result": [
                {
                    "refid": "WD123",
                    "status": "Success",
                    "amount": "1.50",
                    "fee": "0.10",
                    "method": "Bank",
                    "info": "Completed",
                }
            ]
        }

        with patch.object(
            KrakenAPIClient,
            "get_withdraw_status",
            return_value=status_payload,
        ) as status_mock:
            result = self.runner.invoke(
                kraken_cli.cli,
                [
                    "withdraw",
                    "--asset",
                    "ZUSD",
                    "--status",
                ],
                catch_exceptions=False,
            )

        self.assertEqual(result.exit_code, 0, msg=result.output)
        self.assertIn("Withdrawal Status", result.output)
        self.assertIn("WD123", result.output)
        status_mock.assert_called_once_with(asset="ZUSD", method=None, start=None)

    def test_export_report_creates_job(self) -> None:
        """Export command should submit new jobs after confirmation."""

        with patch.object(
            KrakenAPIClient,
            "request_export",
            return_value={"result": {"id": "EXP123", "status": "processing"}},
        ) as export_mock:
            result = self.runner.invoke(
                kraken_cli.cli,
                [
                    "export-report",
                    "--report",
                    "ledgers",
                    "--description",
                    "Monthly ledger",
                    "--field",
                    "txid",
                    "--field",
                    "fee",
                    "--confirm",
                ],
                catch_exceptions=False,
            )

        self.assertEqual(result.exit_code, 0, msg=result.output)
        self.assertIn("Export job submitted", result.output)
        export_mock.assert_called_once_with(
            report="ledgers",
            description="Monthly ledger",
            export_format="CSV",
            fields=["txid", "fee"],
            start=None,
            end=None,
        )

    def test_export_report_status_lists_jobs(self) -> None:
        """Export command should display job status when requested."""

        status_payload = {
            "result": [
                {
                    "id": "EXP123",
                    "report": "ledgers",
                    "status": "processing",
                    "descr": "Monthly ledger",
                    "created": "1700000000",
                }
            ]
        }

        with patch.object(
            KrakenAPIClient,
            "get_export_status",
            return_value=status_payload,
        ) as status_mock:
            result = self.runner.invoke(
                kraken_cli.cli,
                [
                    "export-report",
                    "--status",
                ],
                catch_exceptions=False,
            )

        self.assertEqual(result.exit_code, 0, msg=result.output)
        self.assertIn("Export Job Status", result.output)
        self.assertIn("EXP123", result.output)
        status_mock.assert_called_once_with(report=None)

    def test_export_report_retrieve_saves_file(self) -> None:
        """Export retrieval should write archive to configured output directory."""

        with TemporaryDirectory() as tmpdir, \
                patch.object(kraken_cli, "EXPORT_OUTPUT_DIR", Path(tmpdir)), \
                patch.object(
                    KrakenAPIClient,
                    "retrieve_export",
                    return_value=(b"binary-data", {"Content-Disposition": "attachment; filename=export.zip"}),
                ) as retrieve_mock:
            result = self.runner.invoke(
                kraken_cli.cli,
                [
                    "export-report",
                    "--retrieve-id",
                    "EXP123",
                ],
                catch_exceptions=False,
            )

            self.assertEqual(result.exit_code, 0, msg=result.output)
            self.assertIn("Export saved to", result.output)
            retrieve_mock.assert_called_once_with(report_id="EXP123")

            written_path = Path(tmpdir) / "export.zip"
            self.assertTrue(written_path.exists(), msg="Export file was not written")
            self.assertEqual(written_path.read_bytes(), b"binary-data")

    def test_export_report_retries_on_failure(self) -> None:
        """Export retrieval should retry transient failures before succeeding."""

        side_effects = [Exception("temporary failure"), (b"binary-data", {})]

        with TemporaryDirectory() as tmpdir, \
                patch.object(kraken_cli, "EXPORT_OUTPUT_DIR", Path(tmpdir)), \
                patch("kraken_cli.time.sleep", return_value=None), \
                patch.object(
                    KrakenAPIClient,
                    "retrieve_export",
                    side_effect=side_effects,
                ) as retrieve_mock:
            result = self.runner.invoke(
                kraken_cli.cli,
                [
                    "export-report",
                    "--retrieve-id",
                    "EXP123",
                ],
                catch_exceptions=False,
            )

        self.assertEqual(result.exit_code, 0, msg=result.output)
        self.assertIn("Export saved to", result.output)
        self.assertEqual(retrieve_mock.call_count, 2)

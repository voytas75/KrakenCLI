"""Additional Kraken API client endpoint and caching tests."""

from __future__ import annotations

import base64
import unittest
from typing import Dict
from unittest import mock

from api.kraken_client import KrakenAPIClient


def _build_client() -> KrakenAPIClient:
    api_key = "TESTKEY123456"
    api_secret = base64.b64encode(b"dummy-secret").decode()
    return KrakenAPIClient(api_key=api_key, api_secret=api_secret, sandbox=True)


class KrakenClientEndpointTests(unittest.TestCase):
    """Validate caching rules and new endpoint payload behaviour."""

    def test_get_open_orders_uses_cache_and_force_refresh(self) -> None:
        client = _build_client()
        response: Dict[str, object] = {"error": [], "result": {"open": {}}}

        with mock.patch.object(client, "_make_request", return_value=response) as mocked_request:
            first = client.get_open_orders()
            second = client.get_open_orders()
            third = client.get_open_orders(force_refresh=True)

        mocked_request.assert_called_with("private/OpenOrders", auth_required=True)
        self.assertEqual(2, mocked_request.call_count)
        self.assertIs(first, response)
        self.assertEqual(response, second)
        self.assertIsNot(second, response)
        self.assertEqual(response, third)

    def test_get_open_orders_no_cache_on_error(self) -> None:
        client = _build_client()

        with mock.patch.object(client, "_make_request", side_effect=RuntimeError("kaboom")):
            with self.assertRaises(RuntimeError):
                client.get_open_orders()

        recovery_payload: Dict[str, object] = {"error": [], "result": {"open": {"id": {}}}}
        with mock.patch.object(client, "_make_request", return_value=recovery_payload) as mocked_request:
            client.get_open_orders()

        mocked_request.assert_called_once_with("private/OpenOrders", auth_required=True)

    def test_get_ledgers_cache_and_force_refresh(self) -> None:
        client = _build_client()
        payload: Dict[str, object] = {"error": [], "result": {"ledger": {}}}

        with mock.patch.object(client, "_make_request", return_value=payload) as mocked_request:
            first = client.get_ledgers(assets=["ZUSD", "XBT"])
            second = client.get_ledgers(assets=["ZUSD", "XBT"])
            third = client.get_ledgers(assets=["ZUSD", "XBT"], force_refresh=True)
            fourth = client.get_ledgers(assets=["ZUSD"], force_refresh=False)

        self.assertIs(first, payload)
        self.assertEqual(payload, second)
        self.assertEqual(payload, third)
        self.assertEqual(payload, fourth)
        self.assertEqual(3, mocked_request.call_count)

    def test_request_withdrawal_clears_ledger_cache_and_payload(self) -> None:
        client = _build_client()
        payload: Dict[str, object] = {"error": [], "result": {"refid": "ABCD"}}

        with mock.patch.object(client, "_make_request", return_value=payload) as mocked_request, \
                mock.patch.object(client, "_clear_ledgers_cache") as mocked_clear:
            result = client.request_withdrawal(
                asset="ZUSD",
                key="Primary",
                amount=1.5,
                address="wallet-123",
                otp="123456",
            )

        mocked_request.assert_called_once_with(
            "private/Withdraw",
            data={
                "asset": "ZUSD",
                "key": "Primary",
                "amount": "1.5",
                "address": "wallet-123",
                "otp": "123456",
            },
            auth_required=True,
        )
        mocked_clear.assert_called_once()
        self.assertIs(result, payload)

    def test_request_export_payload_and_status_calls(self) -> None:
        client = _build_client()

        with mock.patch.object(client, "_make_request", return_value={}) as mocked_request:
            client.request_export(
                report="ledgers",
                description="Monthly ledger",
                export_format="csv",
                fields=["id", "time", "id"],
                start="1700000000",
                end="1700500000",
            )

        mocked_request.assert_called_once_with(
            "private/AddExport",
            data={
                "report": "ledgers",
                "description": "Monthly ledger",
                "format": "CSV",
                "fields": "id,time",
                "starttm": "1700000000",
                "endtm": "1700500000",
            },
            auth_required=True,
        )

        with mock.patch.object(client, "_make_request", return_value={}) as mocked_status:
            client.get_export_status()

        mocked_status.assert_called_once_with("private/ExportStatus", data=None, auth_required=True)

        with mock.patch.object(client, "_make_request", return_value=(b"data", {})) as mocked_retrieve:
            client.retrieve_export("REPORT-ID")

        mocked_retrieve.assert_called_once_with(
            "private/RetrieveExport",
            data={"id": "REPORT-ID"},
            auth_required=True,
            raw=True,
        )

        with mock.patch.object(client, "_make_request", return_value={}) as mocked_delete:
            client.delete_export("REPORT-ID")

        mocked_delete.assert_called_once_with(
            "private/DeleteExport", data={"id": "REPORT-ID"}, auth_required=True
        )

    def test_public_cache_clear_helpers_delegate_to_private_methods(self) -> None:
        client = _build_client()

        with mock.patch.object(client, "_invalidate_orders_cache") as orders_mock:
            client.clear_open_orders_cache()
        orders_mock.assert_called_once_with()

        with mock.patch.object(client, "_clear_ledgers_cache") as ledgers_mock:
            client.clear_ledgers_cache()
        ledgers_mock.assert_called_once_with()


if __name__ == "__main__":  # pragma: no cover - manual invocation helper
    unittest.main()

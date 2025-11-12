"""Core behaviour tests for KrakenAPIClient helpers."""

from __future__ import annotations

import base64
import json
from typing import Any, Dict
from unittest import mock

import pytest
import requests

from api.kraken_client import KrakenAPIClient, _RateLimiter


class _DummyResponse:
    def __init__(self, payload: Dict[str, Any]):
        self._payload = payload

    def raise_for_status(self) -> None:  # pragma: no cover - satisfies interface
        return None

    def json(self) -> Dict[str, Any]:
        return self._payload


def _build_client() -> KrakenAPIClient:
    api_key = "TESTKEY123456789"
    api_secret = base64.b64encode(b"secret-key").decode()
    return KrakenAPIClient(api_key=api_key, api_secret=api_secret, sandbox=True)


def test_make_request_private_uses_session_and_returns_payload() -> None:
    client = _build_client()
    dummy_response = _DummyResponse({"error": [], "result": {"foo": "bar"}})
    client.session.post = mock.Mock(return_value=dummy_response)

    with mock.patch.object(client, "_generate_signature", return_value="sig"), mock.patch.object(
        client.config, "get_endpoint_cost", return_value=1.0
    ):
        payload = client._make_request("private/AddOrder", data={"pair": "XBTUSD"}, auth_required=True)

    assert payload["result"]["foo"] == "bar"
    client.session.post.assert_called_once()


def test_generate_signature_produces_base64_hash() -> None:
    client = _build_client()
    signature = client._generate_signature("/0/private/Balance", "123456", "nonce=123456")
    assert isinstance(signature, str)
    assert signature


def test_make_request_public_get_passes_params() -> None:
    client = _build_client()
    dummy_response = _DummyResponse({"error": [], "result": {"time": 123}})
    client.session.get = mock.Mock(return_value=dummy_response)

    with mock.patch.object(client.config, "get_endpoint_cost", return_value=1.0):
        payload = client._make_request("public/Time", data={"foo": "bar"}, auth_required=False, method="GET")

    assert payload["result"]["time"] == 123
    client.session.get.assert_called_once()


def test_make_request_handles_error_payload() -> None:
    client = _build_client()
    error_response = _DummyResponse({"error": ["EGeneral:Invalid"], "result": {}})
    client.session.post = mock.Mock(return_value=error_response)

    with pytest.raises(Exception) as excinfo, mock.patch.object(client.config, "get_endpoint_cost", return_value=1.0):
        client._make_request("private/Balance", auth_required=True)

    assert "Kraken API Error" in str(excinfo.value)


def test_make_request_raw_returns_bytes() -> None:
    client = _build_client()

    class _RawResponse:
        def __init__(self) -> None:
            self.content = b"body"
            self.headers = {"Content-Type": "text/plain"}

        def raise_for_status(self) -> None:  # pragma: no cover - interface stub
            return None

        def json(self):  # pragma: no cover - will not be called
            raise AssertionError("json() should not be called when raw=True")

    client.session.post = mock.Mock(return_value=_RawResponse())

    with mock.patch.object(client.config, "get_endpoint_cost", return_value=1.0):
        content, headers = client._make_request("private/Balance", auth_required=True, raw=True)

    assert content == b"body"
    assert headers["Content-Type"] == "text/plain"


def test_make_request_handles_request_exception() -> None:
    client = _build_client()
    client.session.post = mock.Mock(side_effect=requests.exceptions.RequestException("boom"))

    with pytest.raises(Exception) as excinfo, mock.patch.object(client.config, "get_endpoint_cost", return_value=1.0):
        client._make_request("private/Balance", auth_required=True)

    assert "Request failed" in str(excinfo.value)


def test_make_request_reports_json_errors() -> None:
    client = _build_client()

    class _BadJsonResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self):
            raise json.JSONDecodeError("err", "", 0)

    client.session.get = mock.Mock(return_value=_BadJsonResponse())

    with pytest.raises(Exception) as excinfo, mock.patch.object(client.config, "get_endpoint_cost", return_value=1.0):
        client._make_request("public/Time", method="GET")

    assert "Invalid JSON" in str(excinfo.value)


def test_public_and_private_helpers_delegate_to_make_request() -> None:
    client = _build_client()
    with mock.patch.object(client, "_make_request", return_value={"result": {}}) as mocked:
        client.get_server_time()
        client.get_account_balance()
        client.get_trade_balance()
        client.get_ticker("XBTUSD")
        client.get_ohlc_data("XBTUSD", interval=15)
        client.get_order_book("XBTUSD")
        client.get_recent_trades("XBTUSD")
        client.add_order("XBTUSD", "buy", "market", 1.0)
        client.cancel_order("TXID123")
        client.cancel_all_orders()
        client.get_open_orders(force_refresh=True)
        client.get_closed_orders(trades=True)
        client.get_trade_history(trades=False)
        client.get_ledgers(assets=["XBT"], ledger_type="trade")
        client.get_open_positions()
        client.get_trade_info_for_pair("XBTUSD")
        client.get_asset_info()
        client.get_tradable_asset_pairs()
        client.request_export("trade", "desc")
        client.get_export_status("trade")
        client.retrieve_export("ABC123")
        client.delete_export("ABC123")
    assert mocked.call_count >= 21


def test_rate_limiter_acquire_respects_cost() -> None:
    limiter = _RateLimiter(rate_per_second=5.0, capacity=5.0)
    # Consume the full bucket in one go.
    limiter.acquire(cost=2.5)
    assert limiter._tokens <= 2.5


def test_orders_cache_roundtrip() -> None:
    client = _build_client()
    payload = {"error": [], "result": {"open": []}}
    client._set_orders_cache(payload)
    cached = client._get_cached_orders()
    assert cached == payload
    client.clear_open_orders_cache()
    assert client._get_cached_orders() is None


def test_ledgers_cache_roundtrip() -> None:
    client = _build_client()
    key = client._ledger_cache_key("XBT", "trade", None, None, 0)
    entry = {"result": {"ledger": []}}
    client._set_ledgers_cache(key, entry)
    assert client._get_cached_ledgers(key) == entry
    client.clear_ledgers_cache()
    assert client._get_cached_ledgers(key) is None


def test_normalise_assets_input_handles_sequences() -> None:
    assert KrakenAPIClient._normalise_assets_input(["XBT", "XBT", "ETH"]) == "XBT,ETH"
    assert KrakenAPIClient._normalise_assets_input(None) is None
    assert KrakenAPIClient._normalise_assets_input("XBT") == "XBT"


def test_endpoint_cost_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _build_client()
    monkeypatch.setattr(client.config, "endpoint_weights", {"private/*": 2.0})
    assert client.config.get_endpoint_cost("private/AddOrder", True) == 2.0

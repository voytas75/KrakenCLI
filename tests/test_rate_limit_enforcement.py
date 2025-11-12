"""Tests for KrakenAPIClient rate limit integration."""

from __future__ import annotations

import base64
from unittest import mock

from api.kraken_client import KrakenAPIClient


class _DummyResponse:
    """Minimal response stub for Kraken API client tests."""

    def raise_for_status(self) -> None:  # pragma: no cover - interface stub
        return None

    @staticmethod
    def json() -> dict[str, object]:
        return {"error": [], "result": {}}


def _build_client() -> KrakenAPIClient:
    api_key = "TESTKEY123456"
    api_secret = base64.b64encode(b"dummy-secret").decode()
    return KrakenAPIClient(api_key=api_key, api_secret=api_secret, sandbox=True)


def test_private_request_invokes_rate_limit_delay() -> None:
    client = _build_client()
    client.session.post = mock.Mock(return_value=_DummyResponse())

    with mock.patch.object(client, "rate_limit_delay") as mocked_delay:
        client._make_request("private/Balance", data={}, auth_required=True)

    mocked_delay.assert_called_once()

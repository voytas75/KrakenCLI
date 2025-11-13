"""Additional coverage for export CLI command."""

from __future__ import annotations

from typing import Any

from click.testing import CliRunner

import kraken_cli


def _install_api_client(monkeypatch, client: Any) -> None:
    monkeypatch.setattr("kraken_cli.KrakenAPIClient", lambda *args, **kwargs: client)
    monkeypatch.setattr("cli.export.KrakenAPIClient", lambda *args, **kwargs: client)


class _ExportClient:
    def __init__(self) -> None:
        self.deleted_id: str | None = None

    def get_export_status(self, report: str | None = None):
        return {"result": []}

    def retrieve_export(self, report_id: str):
        return b"", {}

    def delete_export(self, report_id: str):
        self.deleted_id = report_id
        return {"result": "ok"}

    def request_export(self, **_kwargs):  # pragma: no cover - not used in these tests
        return {"result": {}}


def test_export_report_prevents_multiple_actions(monkeypatch) -> None:
    runner = CliRunner()
    _install_api_client(monkeypatch, _ExportClient())

    result = runner.invoke(
        kraken_cli.cli,
        ["export-report", "--status", "--retrieve-id", "ABC"],
        catch_exceptions=False,
    )

    assert "Please choose only one action" in result.output


def test_export_status_handles_no_jobs(monkeypatch) -> None:
    runner = CliRunner()
    _install_api_client(monkeypatch, _ExportClient())

    result = runner.invoke(
        kraken_cli.cli,
        ["export-report", "--status"],
        catch_exceptions=False,
    )

    assert "No export jobs found" in result.output


def test_export_retrieve_handles_empty_content(monkeypatch) -> None:
    runner = CliRunner()
    _install_api_client(monkeypatch, _ExportClient())

    result = runner.invoke(
        kraken_cli.cli,
        ["export-report", "--retrieve-id", "JOB123"],
        catch_exceptions=False,
    )

    assert "Export data was empty" in result.output


def test_export_delete_invokes_client(monkeypatch) -> None:
    runner = CliRunner()
    client = _ExportClient()
    _install_api_client(monkeypatch, client)

    result = runner.invoke(
        kraken_cli.cli,
        ["export-report", "--delete-id", "JOB999"],
        catch_exceptions=False,
    )

    assert result.exit_code == 0
    assert client.deleted_id == "JOB999"

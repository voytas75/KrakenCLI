"""
Export management CLI commands for KrakenCLI.

Provides the ``export-report`` command that submits, inspects, and retrieves
Kraken export jobs.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Sequence, Tuple

import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from api.kraken_client import KrakenAPIClient

logger = logging.getLogger(__name__)


def register(
    cli_group: click.Group,
    *,
    console: Console,
    config,
    call_with_retries: Callable[[Callable[[], Any], str, Optional[str]], Any],
    export_output_dir: Path,
) -> None:
    """Register export-report command on the root Click group."""

    def _extract_filename_from_headers(headers: Dict[str, Any], fallback: str) -> str:
        """Extract filename from HTTP headers or fall back to provided value."""

        if not headers:
            return fallback

        disposition = headers.get("Content-Disposition") or headers.get("content-disposition")
        if not disposition:
            return fallback

        for part in disposition.split(";"):
            part = part.strip()
            if part.lower().startswith("filename="):
                filename = part.split("=", 1)[1].strip().strip('"')
                if filename:
                    return filename

        return fallback

    def _log_export_headers(headers: Dict[str, Any]) -> None:
        """Log a sanitized subset of export response headers for diagnostics."""

        if not headers:
            return

        safe_keys = {"content-type", "content-length", "content-disposition"}
        safe_headers = {
            key: value
            for key, value in headers.items()
            if key.lower() in safe_keys
        }
        if safe_headers:
            logger.info("Export response headers: %s", safe_headers)

    def _ensure_api_client(ctx: click.Context) -> Optional[KrakenAPIClient]:
        api_client = ctx.obj.get("api_client")
        if api_client is not None:
            return api_client

        if not config.has_credentials():
            console.print("[red]⚠️  API credentials not configured![/red]")
            console.print("[yellow]Please configure your Kraken API credentials in .env file[/yellow]")
            console.print("[yellow]See README.md for setup instructions[/yellow]")
            return None

        try:
            api_client = KrakenAPIClient(
                api_key=config.api_key,
                api_secret=config.api_secret,
                sandbox=config.sandbox,
            )
        except Exception as exc:  # pragma: no cover - defensive user message
            console.print(f"[red]❌ Failed to initialize API client: {exc}[/red]")
            return None

        ctx.obj["api_client"] = api_client
        return api_client

    @cli_group.command(name="export-report")
    @click.option("--report", "-r", help="Kraken report type (ledgers, trades, margin, etc.)")
    @click.option("--description", "-d", help="Description for the export job")
    @click.option(
        "--format",
        "export_format",
        type=click.Choice(["CSV", "TSV", "JSON"], case_sensitive=False),
        default="CSV",
        show_default=True,
        help="Export format",
    )
    @click.option("--field", "fields", multiple=True, help="Optional field to include (repeatable)")
    @click.option("--start", help="Unix timestamp for export start window")
    @click.option("--end", help="Unix timestamp for export end window")
    @click.option("--status", is_flag=True, help="List export job status (optionally filter by --report)")
    @click.option("--retrieve-id", help="Retrieve details for a specific export job ID")
    @click.option("--delete-id", help="Delete a completed export job by ID")
    @click.option("--confirm", is_flag=True, help="Skip confirmation when creating a new export job")
    @click.pass_context
    def export_report(  # type: ignore[unused-ignore]
        ctx: click.Context,
        report: Optional[str],
        description: Optional[str],
        export_format: str,
        fields: Sequence[str],
        start: Optional[str],
        end: Optional[str],
        status: bool,
        retrieve_id: Optional[str],
        delete_id: Optional[str],
        confirm: bool,
    ) -> None:
        """Manage Kraken export jobs for ledgers, trades, and other reports."""

        api_client = _ensure_api_client(ctx)
        if api_client is None:
            return

        actions_selected = sum(
            action is True for action in (status,)
        ) + sum(
            action is not None for action in (retrieve_id, delete_id)
        )

        if actions_selected > 1:
            console.print("[red]❌ Please choose only one action: create, --status, --retrieve-id, or --delete-id.[/red]")
            return

        if status:
            console.print("[bold blue]🔍 Fetching export job status...[/bold blue]")
            try:
                response = call_with_retries(
                    lambda: api_client.get_export_status(report=report),
                    "Export status fetch",
                    display_label="⏳ Fetching export status",
                )
            except Exception as exc:  # pragma: no cover - defensive user message
                console.print(f"[red]❌ Failed to fetch export status: {exc}[/red]")
                return

            jobs_raw = response.get("result") if isinstance(response, dict) else None
            if isinstance(jobs_raw, list):
                jobs = [job for job in jobs_raw if isinstance(job, dict)]
            elif isinstance(jobs_raw, dict):
                jobs = [payload for payload in jobs_raw.values() if isinstance(payload, dict)]
            else:
                jobs = []

            if not jobs:
                console.print("[yellow]ℹ️  No export jobs found.[/yellow]")
                return

            table = Table(title="Export Job Status", show_lines=False)
            table.add_column("ID", style="cyan")
            table.add_column("Report", style="green")
            table.add_column("Status", style="yellow")
            table.add_column("Description", style="white")
            table.add_column("Created", style="magenta")

            for job in jobs:
                table.add_row(
                    str(job.get("id", "N/A")),
                    str(job.get("report", "N/A")),
                    str(job.get("status", "N/A")),
                    str(job.get("descr", job.get("description", ""))),
                    str(job.get("created", job.get("createdtm", ""))),
                )

            console.print(table)
            return

        if retrieve_id:
            console.print(f"[bold blue]🔍 Retrieving export job {retrieve_id}...[/bold blue]")
            try:
                content, headers = call_with_retries(
                    lambda: api_client.retrieve_export(report_id=retrieve_id),
                    "Export retrieval",
                    display_label="⏳ Downloading export",
                )
            except Exception as exc:  # pragma: no cover - defensive user message
                console.print(f"[red]❌ Failed to retrieve export: {exc}[/red]")
                return

            if not content:
                console.print("[yellow]ℹ️  Export data was empty for the specified job.[/yellow]")
                return

            export_output_dir.mkdir(parents=True, exist_ok=True)
            filename = _extract_filename_from_headers(headers, fallback=f"{retrieve_id}.zip")
            output_path = export_output_dir / filename

            _log_export_headers(headers)

            try:
                with output_path.open("wb") as handle:
                    handle.write(content)
            except OSError as exc:  # pragma: no cover - filesystem guard
                console.print(f"[red]❌ Failed to write export file: {exc}[/red]")
                return

            expected_length = (headers.get("Content-Length") if headers else None) or (
                headers.get("content-length") if headers else None
            )
            if expected_length:
                try:
                    expected_bytes = int(expected_length)
                    if expected_bytes != len(content):
                        logger.warning(
                            "Export size mismatch (expected=%s, actual=%s)",
                            expected_bytes,
                            len(content),
                        )
                        console.print(
                            "[yellow]⚠️  Download size differs from Content-Length; verify archive integrity.[/yellow]"
                        )
                except ValueError:
                    logger.debug("Unable to parse Content-Length header: %s", expected_length)

            console.print(f"[green]✅ Export saved to [bold]{output_path}[/bold].[/green]")
            console.print("[yellow]💡 Extract the archive to review the exported data.[/yellow]")
            return

        if delete_id:
            console.print(f"[bold yellow]⚠️  Deleting export job {delete_id}...[/bold yellow]")
            try:
                response = call_with_retries(
                    lambda: api_client.delete_export(report_id=delete_id),
                    "Export delete",
                    display_label="⏳ Deleting export job",
                )
            except Exception as exc:  # pragma: no cover - defensive user message
                console.print(f"[red]❌ Failed to delete export: {exc}[/red]")
                return

            result_payload = response.get("result") if isinstance(response, dict) else None
            if isinstance(result_payload, dict) and result_payload.get("result") == "success":
                console.print("[green]✅ Export job deleted successfully.[/green]")
            else:
                console.print("[green]✅ Delete request submitted.[/green]")
            return

        if not report:
            console.print("[red]❌ Report type (--report) is required when creating an export job.[/red]")
            return

        job_description = description or f"CLI export for {report}"

        summary_table = Table.grid(padding=(0, 1))
        summary_table.add_column(justify="right", style="cyan")
        summary_table.add_column(style="white")
        summary_table.add_row("Report", report)
        summary_table.add_row("Format", export_format.upper())
        summary_table.add_row("Description", job_description)
        summary_table.add_row("Fields", ", ".join(fields) if fields else "(all)")
        summary_table.add_row("Start", start or "(none)")
        summary_table.add_row("End", end or "(none)")

        console.print(
            Panel(
                summary_table,
                title="Export Job Confirmation",
                border_style="yellow",
            )
        )

        if not confirm:
            proceed = click.confirm("Submit export job?", default=False)
            if not proceed:
                console.print("[yellow]ℹ️  Export job cancelled by user.[/yellow]")
                return

        try:
            response = call_with_retries(
                lambda: api_client.request_export(
                    report=report,
                    description=job_description,
                    export_format=export_format.upper(),
                    fields=list(fields) if fields else None,
                    start=start,
                    end=end,
                ),
                "Export submission",
                display_label="⏳ Submitting export job",
            )
        except Exception as exc:  # pragma: no cover - defensive user message
            console.print(f"[red]❌ Failed to submit export job: {exc}[/red]")
            return

        payload = response.get("result") if isinstance(response, dict) else None
        job_id = None
        if isinstance(payload, dict):
            job_id = payload.get("id")

        if job_id:
            console.print(f"[green]✅ Export job submitted (id: {job_id}).[/green]")
        else:
            console.print("[green]✅ Export job submitted successfully.[/green]")

        if isinstance(payload, dict) and payload:
            details = Table(title="Export Job Details", show_lines=False)
            details.add_column("Field", style="cyan")
            details.add_column("Value", style="white")
            for field, value in payload.items():
                details.add_row(str(field), str(value))
            console.print(details)

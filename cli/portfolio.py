"""
Portfolio command registration for KrakenCLI.

This module encapsulates the ``portfolio`` command that displays balances and
open positions using Rich tables.

Updates: v0.9.8 - 2025-11-15 - Added snapshot save and comparison options.
Updates: v0.9.9 - 2025-11-15 - Print raw fee status payload when debug logging is active.
Updates: v0.9.10 - 2025-11-16 - Align asset display with status command notes and raw values.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Optional

import click
from rich.console import Console
from rich.pretty import Pretty
from rich.table import Table

from api.kraken_client import KrakenAPIClient
from portfolio.portfolio_manager import PortfolioManager
from utils.helpers import format_asset_amount, format_currency

logger = logging.getLogger(__name__)

SNAPSHOT_DIR = Path("logs") / "portfolio" / "snapshots"


def register(
    cli_group: click.Group,
    *,
    console: Console,
    config,
    call_with_retries: Callable[[Callable[[], Any], str, Optional[str]], Any],
) -> None:
    """Register the portfolio command on the provided Click group."""

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

    def _ensure_portfolio(ctx: click.Context) -> Optional[PortfolioManager]:
        portfolio: Optional[PortfolioManager] = ctx.obj.get("portfolio")
        if portfolio is not None:
            return portfolio

        api_client = _ensure_api_client(ctx)
        if api_client is None:
            return None

        try:
            portfolio = PortfolioManager(api_client=api_client)
        except Exception as exc:  # pragma: no cover - defensive user message
            console.print(f"[red]❌ Failed to initialize portfolio manager: {exc}[/red]")
            return None

        ctx.obj["portfolio"] = portfolio
        return portfolio

    def _write_snapshot(summary: dict[str, Any]) -> Optional[Path]:
        """Persist summary payload to the snapshot directory."""
        try:
            SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            file_path = SNAPSHOT_DIR / f"portfolio_{timestamp}.json"
            file_path.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
            return file_path
        except Exception as exc:  # pragma: no cover - defensive file system guard
            logger.error("Failed to write portfolio snapshot: %s", exc)
            return None

    def _load_snapshot(path: Path) -> Optional[Dict[str, Any]]:
        """Return snapshot payload from disk when possible."""
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            logger.error("Failed to read snapshot %s: %s", path, exc)
            return None
        if not isinstance(payload, dict):
            logger.error("Snapshot %s did not contain a JSON object", path)
            return None
        return payload

    def _safe_float(value: Any) -> Optional[float]:
        try:
            if value is None:
                return None
            return float(value)
        except (TypeError, ValueError):
            return None

    def _format_currency_value(value: Optional[float], *, currency: str = "USD") -> str:
        if value is None:
            return "N/A"
        return format_currency(value, currency=currency, decimals=2)

    def _format_currency_delta(delta: Optional[float]) -> str:
        if delta is None:
            return "N/A"
        if abs(delta) < 1e-9:
            return "USD 0.00"
        sign = "+" if delta > 0 else "-"
        return f"{sign}{format_currency(abs(delta), decimals=2)}"

    def _format_amount_delta(delta: float, asset: str) -> str:
        if abs(delta) < 1e-12:
            return "0"
        sign = "+" if delta > 0 else "-"
        return f"{sign}{format_asset_amount(abs(delta), asset)}"

    def _format_fee_percent(value: Optional[float]) -> str:
        if value is None:
            return "N/A"
        return f"{value:.4f}%"

    def _assets_index(summary: Dict[str, Any]) -> Dict[str, Dict[str, Optional[float]]]:
        index: Dict[str, Dict[str, Optional[float]]] = {}
        for entry in summary.get("significant_assets", []) or []:
            asset = str(entry.get("asset", "")).upper()
            if not asset:
                continue
            amount = _safe_float(entry.get("amount")) or 0.0
            usd_value = _safe_float(entry.get("usd_value"))
            index[asset] = {
                "amount": amount,
                "usd": usd_value,
            }
        return index

    def _display_comparison(
        current_summary: Dict[str, Any],
        snapshot_summary: Dict[str, Any],
    ) -> None:
        current_assets = _assets_index(current_summary)
        snapshot_assets = _assets_index(snapshot_summary)
        asset_keys = sorted(set(current_assets) | set(snapshot_assets))

        if not asset_keys:
            console.print("[yellow]ℹ️  No asset data available for comparison.[/yellow]")
            return

        table = Table(title="Portfolio Comparison")
        table.add_column("Asset", style="cyan")
        table.add_column("Snapshot Amount", justify="right", style="yellow")
        table.add_column("Current Amount", justify="right", style="green")
        table.add_column("Δ Amount", justify="right", style="magenta")
        table.add_column("Snapshot USD", justify="right", style="yellow")
        table.add_column("Current USD", justify="right", style="green")
        table.add_column("Δ USD", justify="right", style="magenta")

        for asset in asset_keys:
            snapshot_entry = snapshot_assets.get(asset, {"amount": 0.0, "usd": None})
            current_entry = current_assets.get(asset, {"amount": 0.0, "usd": None})

            snapshot_amount = snapshot_entry.get("amount") or 0.0
            current_amount = current_entry.get("amount") or 0.0
            amount_delta = current_amount - snapshot_amount

            snapshot_usd = snapshot_entry.get("usd")
            current_usd = current_entry.get("usd")
            usd_delta: Optional[float]
            if snapshot_usd is not None and current_usd is not None:
                usd_delta = current_usd - snapshot_usd
            else:
                usd_delta = None

            table.add_row(
                asset,
                format_asset_amount(snapshot_amount, asset),
                format_asset_amount(current_amount, asset),
                _format_amount_delta(amount_delta, asset),
                _format_currency_value(snapshot_usd),
                _format_currency_value(current_usd),
                _format_currency_delta(usd_delta),
            )

        snapshot_total = _safe_float(snapshot_summary.get("total_usd_value"))
        current_total = _safe_float(current_summary.get("total_usd_value"))
        total_delta = (
            current_total - snapshot_total
            if snapshot_total is not None and current_total is not None
            else None
        )

        console.print(table)
        snapshot_text = _format_currency_value(snapshot_total)
        current_text = _format_currency_value(current_total)
        delta_text = _format_currency_delta(total_delta)
        console.print(
            f"[bold magenta]Snapshot Total: {snapshot_text} | Current Total: {current_text} | Δ {delta_text}[/bold magenta]"
        )

    @cli_group.command()
    @click.option("--pair", "-p", help="Filter by trading pair")
    @click.option(
        "--save",
        is_flag=True,
        help="Save portfolio summary to logs/portfolio/snapshots/",
    )
    @click.option(
        "--compare",
        type=click.Path(exists=True, file_okay=True, dir_okay=False, path_type=Path),
        help="Compare current portfolio summary with the provided snapshot JSON file.",
    )
    @click.pass_context
    def portfolio(  # type: ignore[unused-ignore]
        ctx: click.Context,
        pair: Optional[str],
        save: bool,
        compare: Optional[Path],
    ) -> None:
        """Show portfolio overview."""

        portfolio_manager = _ensure_portfolio(ctx)
        if portfolio_manager is None:
            return

        try:
            console.print("[bold blue]💼 Portfolio Overview[/bold blue]")

            summary = call_with_retries(
                lambda: portfolio_manager.get_portfolio_summary(refresh=True),
                "Portfolio summary fetch",
                display_label="🔄 Refreshing portfolio",
            )
            asset_rows = summary.get("significant_assets", []) if summary else []

            if asset_rows:
                table = Table(title="Asset Balances")
                table.add_column("Asset", style="cyan")
                table.add_column("Pair", style="yellow")
                table.add_column("Balance", justify="right", style="green")
                table.add_column("USD Value", justify="right", style="blue")
                table.add_column("Note", style="yellow")

                suffix_notes = {
                    ".B": "Yield-bearing balance",
                    ".F": "Kraken Rewards balance",
                    ".T": "Tokenized asset",
                    ".S": "Staked balance",
                    ".M": "Opt-in rewards balance",
                }

                for row in asset_rows:
                    asset_code = str(row.get("asset", "N/A"))
                    amount_value = row.get("amount", 0.0)
                    raw_amount = row.get("raw_amount")
                    usd_value = row.get("usd_value")

                    try:
                        amount_float = float(amount_value)
                    except (ValueError, TypeError):
                        amount_float = 0.0

                    if amount_float <= 0:
                        continue

                    note = ""
                    display_asset = asset_code
                    for suffix, message in suffix_notes.items():
                        if asset_code.endswith(suffix):
                            note = message
                            display_asset = asset_code[: -len(suffix)] or asset_code
                            break

                    amount_text: str
                    if isinstance(raw_amount, str) and raw_amount.strip():
                        amount_text = raw_amount.strip()
                    else:
                        amount_text = str(amount_value)

                    usd_text = format_currency(usd_value, decimals=2) if usd_value is not None else "N/A"
                    pair_display = portfolio_manager.get_pair_display(asset_code, "USD")

                    table.add_row(display_asset, pair_display, amount_text, usd_text, note)

                console.print(table)

                total_value = summary.get("total_usd_value") if summary else None
                if total_value is not None:
                    console.print(
                        f"\n[bold green]Total Portfolio Value: {format_currency(total_value, decimals=2)}[/bold green]"
                    )

                missing_assets = summary.get("missing_assets") if summary else []
                if missing_assets:
                    formatted_missing = ", ".join(sorted(set(missing_assets)))
                    console.print(f"[yellow]⚠️  No USD pricing available for: {formatted_missing}[/yellow]")

            fee_status = summary.get("fee_status") if summary else None
            if fee_status:
                console.print("\n[bold blue]Fee Status[/bold blue]")
                fee_table = Table()
                fee_table.add_column("Metric", style="cyan")
                fee_table.add_column("Value", justify="right", style="green")

                currency_raw = str(fee_status.get("currency") or "USD")
                currency_display = currency_raw[1:] if currency_raw.startswith("Z") and len(currency_raw) > 1 else currency_raw

                volume_value = _safe_float(fee_status.get("thirty_day_volume"))
                maker_value = _safe_float(fee_status.get("maker_fee"))
                taker_value = _safe_float(fee_status.get("taker_fee"))
                next_fee_value = _safe_float(fee_status.get("next_fee"))
                next_volume_value = _safe_float(fee_status.get("next_volume"))
                tier_volume_value = _safe_float(fee_status.get("tier_volume"))

                pair_display = fee_status.get("pair") or "Multiple"

                volume_text = _format_currency_value(volume_value, currency=currency_display)
                maker_text = _format_fee_percent(maker_value)
                taker_text = _format_fee_percent(taker_value)
                next_fee_text = _format_fee_percent(next_fee_value)
                next_volume_text = _format_currency_value(next_volume_value, currency=currency_display)
                tier_volume_text = _format_currency_value(tier_volume_value, currency=currency_display)

                fee_table.add_row("Pair", str(pair_display))
                fee_table.add_row("30-day Volume", volume_text)
                fee_table.add_row("Maker Fee", maker_text)
                fee_table.add_row("Taker Fee", taker_text)
                fee_table.add_row("Next Fee Tier", next_fee_text)
                fee_table.add_row("Current Tier Volume", tier_volume_text)
                fee_table.add_row("Volume For Next Tier", next_volume_text)

                console.print(fee_table)
                if logging.getLogger().getEffectiveLevel() <= logging.DEBUG:
                    raw_payload = summary.get("fee_status_raw") if summary else None
                    if raw_payload is not None:
                        console.print("\n[dim]Raw Fee Status Response[/dim]")
                        console.print(Pretty(raw_payload))
            elif fee_status == {}:
                console.print(
                    "[yellow]ℹ️  Fee status unavailable (Kraken did not return fee data for this account or pair set).[/yellow]"
                )

            if save and summary:
                snapshot_path = _write_snapshot(summary)
                if snapshot_path is not None:
                    console.print(f"[green]✅ Snapshot saved to {snapshot_path}[/green]")
                else:
                    console.print("[red]❌ Failed to save portfolio snapshot.[/red]")

            if compare and summary:
                snapshot_payload = _load_snapshot(compare)
                if snapshot_payload is None:
                    console.print(f"[red]❌ Failed to load snapshot from {compare}[/red]")
                else:
                    console.print()
                    _display_comparison(summary, snapshot_payload)

            positions = portfolio_manager.get_open_positions()
            if positions:
                console.print("\n[bold blue]Open Positions[/bold blue]")
                pos_table = Table()
                pos_table.add_column("Pair", style="cyan")
                pos_table.add_column("Side", style="yellow")
                pos_table.add_column("Volume", style="green")
                pos_table.add_column("P&L", style="magenta")

                for pair_name, position in positions.items():
                    pos_table.add_row(
                        pair_name,
                        position.get("type", "N/A"),
                        position.get("vol", "N/A"),
                        position.get("net", "N/A"),
                    )

                console.print(pos_table)

        except Exception as exc:  # pragma: no cover - defensive user message
            console.print(f"[red]❌ Error fetching portfolio: {str(exc)}[/red]")

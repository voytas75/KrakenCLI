"""
Portfolio command registration for KrakenCLI.

This module encapsulates the ``portfolio`` command that displays balances and
open positions using Rich tables.
"""

from __future__ import annotations

from typing import Any, Callable, Optional

import click
from rich.console import Console
from rich.table import Table

from api.kraken_client import KrakenAPIClient
from portfolio.portfolio_manager import PortfolioManager
from utils.helpers import format_asset_amount, format_currency


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

    @cli_group.command()
    @click.option("--pair", "-p", help="Filter by trading pair")
    @click.pass_context
    def portfolio(  # type: ignore[unused-ignore]
        ctx: click.Context,
        pair: Optional[str],
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
                table.add_column("Amount", justify="right", style="green")
                table.add_column("USD Value", justify="right", style="blue")

                for row in asset_rows:
                    asset_code = row.get("asset", "N/A")
                    amount_value = row.get("amount", 0.0)
                    usd_value = row.get("usd_value")

                    try:
                        amount_float = float(amount_value)
                    except (ValueError, TypeError):
                        amount_float = 0.0

                    if amount_float <= 0:
                        continue

                    amount_text = format_asset_amount(amount_float, asset_code)
                    usd_text = format_currency(usd_value, decimals=2) if usd_value is not None else "N/A"

                    table.add_row(asset_code, amount_text, usd_text)

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

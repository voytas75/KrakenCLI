"""Trading-related CLI commands for KrakenCLI.

The register function attaches order management and withdrawal commands to the
root Click group without keeping all of the logic inside ``kraken_cli.py``.

Updates: v0.9.10 - 2025-11-15 - Added OHLC fetch command with table/JSON rendering.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Callable, Dict, List, Optional

import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from api.kraken_client import KrakenAPIClient
from portfolio.portfolio_manager import PortfolioManager
from trading.trader import Trader
from utils.helpers import format_currency
from utils.market_data import resolve_ohlc_payload


def register(
    cli_group: click.Group,
    *,
    console: Console,
    config,
    call_with_retries: Callable[[Callable[[], Any], str, Optional[str]], Any],
) -> None:
    """Register trading commands on the provided Click group."""

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

    def _ensure_trader(ctx: click.Context) -> Optional[Trader]:
        trader: Optional[Trader] = ctx.obj.get("trader")
        if trader:
            return trader

        api_client = _ensure_api_client(ctx)
        if api_client is None:
            return None

        try:
            trader = Trader(api_client=api_client)
        except Exception as exc:  # pragma: no cover - defensive user message
            console.print(f"[red]❌ Failed to initialize trader: {exc}[/red]")
            return None

        ctx.obj["trader"] = trader
        return trader

    def _ensure_portfolio(ctx: click.Context) -> Optional[PortfolioManager]:
        portfolio: Optional[PortfolioManager] = ctx.obj.get("portfolio")
        if portfolio:
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
    @click.option("--pair", "-p", required=True, help="Trading pair (e.g., XBTUSD)")
    @click.option("--side", "-s", type=click.Choice(["buy", "sell"]), required=True, help="Order side")
    @click.option(
        "--order-type",
        "-t",
        type=click.Choice(["market", "limit", "stop-loss", "take-profit"]),
        default="market",
        help="Order type",
    )
    @click.option("--volume", "-v", required=True, type=float, help="Order volume")
    @click.option("--price", help="Limit price (required for limit orders)")
    @click.option("--price2", help="Secondary price (for stop-loss-profit orders)")
    @click.option(
        "--execute",
        is_flag=True,
        help="Execute order after confirmation (default: dry-run validation)",
    )
    @click.option(
        "--validate",
        is_flag=True,
        help="Force validation-only mode (alias for default behaviour)",
    )
    @click.option(
        "--yes",
        "-y",
        is_flag=True,
        help="Skip confirmation prompt when executing (expert only)",
    )
    @click.pass_context
    def order(  # type: ignore[unused-ignore]
        ctx: click.Context,
        pair: str,
        side: str,
        order_type: str,
        volume: float,
        price: Optional[str],
        price2: Optional[str],
        execute: bool,
        validate: bool,
        yes: bool,
    ) -> None:
        """Place a new order."""

        trader = _ensure_trader(ctx)
        if trader is None:
            return

        try:
            parsed_price = float(price) if price is not None else None
        except ValueError:
            console.print("[red]❌ Invalid price value. Please provide a numeric price.[/red]")
            return

        try:
            parsed_price2 = float(price2) if price2 is not None else None
        except ValueError:
            console.print("[red]❌ Invalid secondary price value. Please provide a numeric value.[/red]")
            return

        console.print(f"[bold blue]📝 Placing {side} order for {pair}...[/bold blue]")

        if order_type in ["limit", "take-profit"] and parsed_price is None:
            console.print("[red]❌ Limit price required for limit/take-profit orders[/red]")
            return

        if order_type in ["stop-loss", "take-profit"] and parsed_price2 is None:
            console.print("[red]❌ Secondary price required for stop-loss/take-profit orders[/red]")
            return

        order_params: Dict[str, Any] = {
            "pair": pair,
            "type": side,
            "ordertype": order_type,
            "volume": volume,
        }

        if parsed_price is not None:
            order_params["price"] = parsed_price
        if parsed_price2 is not None:
            order_params["price2"] = parsed_price2

        if execute and validate:
            console.print("[red]❌ Conflicting flags: use either --execute or --validate, not both[/red]")
            return

        dry_run = not execute or validate

        summary_table = Table(title="Order Summary")
        summary_table.add_column("Field", style="cyan")
        summary_table.add_column("Value", style="green")
        summary_table.add_row("Mode", "Dry-run (validate only)" if dry_run else "Live execution")
        summary_table.add_row("Pair", pair)
        summary_table.add_row("Side", side.upper())
        summary_table.add_row("Type", order_type.upper())
        summary_table.add_row("Volume", str(volume))
        if parsed_price is not None:
            summary_table.add_row("Price", str(parsed_price))
        if parsed_price2 is not None:
            summary_table.add_row("Secondary Price", str(parsed_price2))
        console.print(summary_table)

        if not dry_run and not yes:
            console.print("[yellow]⚠️ You are about to execute a live order.[/yellow]")
            if not click.confirm("Do you want to proceed?", default=False):
                console.print("[yellow]🚫 Order cancelled by user.[/yellow]")
                return

        try:
            result = trader.place_order(validate=dry_run, **order_params)
        except Exception as exc:  # pragma: no cover - defensive user message
            result = None
            error_message = str(exc)
            if "insufficient funds" in error_message.lower():
                console.print("[red]❌ Order rejected: insufficient funds.[/red]")
                try:
                    balances = trader.api_client.get_account_balance()
                    balance_data = balances.get("result", {}) if balances else {}
                except Exception as balance_error:  # pragma: no cover - defensive user message
                    console.print(f"[yellow]⚠️ Unable to retrieve balances: {balance_error}[/yellow]")
                    balance_data = {}

                if balance_data:
                    balance_table = Table(title="Current Account Balances")
                    balance_table.add_column("Asset", style="cyan")
                    balance_table.add_column("Balance", style="green")

                    shown = 0
                    for asset_code, amount in balance_data.items():
                        try:
                            amount_float = float(amount)
                        except (TypeError, ValueError):
                            amount_float = 0.0
                        if amount_float > 0:
                            balance_table.add_row(asset_code, format_currency(amount))
                            shown += 1
                    if shown > 0:
                        console.print(balance_table)
                    else:
                        console.print("[yellow]⚠️ No positive balances available to display.[/yellow]")
                console.print("[yellow]💡 Reduce the order size or deposit funds to proceed.[/yellow]")
                return

            console.print(f"[red]❌ Error placing order: {error_message}[/red]")
            return

        if result:
            txid = result.get("result", {}).get("txid", ["Unknown"])
            reference_id = txid[0] if txid else "Unknown"
            if dry_run:
                console.print("[green]✅ Order validated successfully (no trade executed).[/green]")
            else:
                console.print("[green]✅ Order executed successfully![/green]")
            console.print(f"Reference: [cyan]{reference_id}[/cyan]")
        else:
            console.print("[red]❌ Failed to place order[/red]")

    @cli_group.command()
    @click.option("--status", "-s", help="Filter by order status (open, closed, any)")
    @click.option("--trades", is_flag=True, help="Show trade history instead of orders")
    @click.option("--verbose", "-v", is_flag=True, help="Show detailed debug information")
    @click.pass_context
    def orders(  # type: ignore[unused-ignore]
        ctx: click.Context,
        status: Optional[str],
        trades: bool,
        verbose: bool,
    ) -> None:
        """Show current orders or trade history."""

        portfolio = _ensure_portfolio(ctx)
        if portfolio is None:
            return

        try:
            if trades:
                console.print("[bold blue]📊 Fetching trade history...[/bold blue]")
                trades_data = call_with_retries(
                    lambda: portfolio.get_trade_history(),
                    "Trade history fetch",
                    display_label="🔄 Fetching trade history",
                )

                if trades_data:
                    table = Table(title="Trade History")
                    table.add_column("Time", style="cyan")
                    table.add_column("Pair", style="green")
                    table.add_column("Side", style="yellow")
                    table.add_column("Price", style="blue")
                    table.add_column("Volume", style="magenta")
                    table.add_column("Cost", style="red")

                    for trade in trades_data:
                        table.add_row(
                            str(trade.get("time", "N/A")),
                            str(trade.get("pair", "N/A")),
                            str(trade.get("type", "N/A")),
                            str(trade.get("price", "N/A")),
                            str(trade.get("vol", "N/A")),
                            str(trade.get("cost", "N/A")),
                        )

                    console.print(table)
                else:
                    console.print("[yellow]No trade history found[/yellow]")
                return

            console.print("[bold blue]📋 Fetching open orders...[/bold blue]")
            orders_data = call_with_retries(
                lambda: portfolio.get_open_orders(refresh=True),
                "Open orders fetch",
                display_label="🔄 Fetching open orders",
            )

            if not orders_data:
                console.print("[yellow]No open orders found[/yellow]")
                return

            if verbose:
                console.print(f"[dim]🔍 Debug: orders_data type: {type(orders_data)}[/dim]")
                console.print(f"[dim]🔍 Debug: orders_data keys: {list(orders_data.keys())}[/dim]")
                first_key = next(iter(orders_data), None)
                if first_key is not None:
                    first_value = orders_data[first_key]
                    console.print(f"[dim]🔍 Debug: First key: {first_key}[/dim]")
                    console.print(f"[dim]🔍 Debug: First value type: {type(first_value)}[/dim]")
                    if isinstance(first_value, dict):
                        console.print(f"[dim]🔍 Debug: First value keys: {list(first_value.keys())}[/dim]")

            actual_orders = orders_data
            if isinstance(orders_data, dict) and "open" in orders_data and isinstance(orders_data["open"], dict):
                actual_orders = orders_data["open"]
                if verbose:
                    console.print(f"[dim]🔍 Debug: Using 'open' sub-dictionary with {len(actual_orders)} orders[/dim]")

            table = Table(title="Open Orders")
            table.add_column("Time", style="cyan")
            table.add_column("Pair", style="green")
            table.add_column("Side", style="yellow")
            table.add_column("Type", style="blue")
            table.add_column("Volume", style="magenta")
            table.add_column("Price", style="red")

            first_processed = False
            for order_id, order in actual_orders.items():
                descr = order.get("descr", {}) if isinstance(order, dict) else {}

                is_first = not first_processed
                if verbose and is_first:
                    console.print(f"[dim]🔍 Debug: Processing order {order_id}[/dim]")
                    console.print(f"[dim]🔍 Debug: order keys: {list(order.keys()) if isinstance(order, dict) else order}[/dim]")
                    console.print(f"[dim]🔍 Debug: descr keys: {list(descr.keys()) if isinstance(descr, dict) else descr}[/dim]")
                    console.print(f"[dim]🔍 Debug: opentm: {order.get('opentm') if isinstance(order, dict) else 'N/A'}[/dim]")
                    console.print(f"[dim]🔍 Debug: vol: {order.get('vol') if isinstance(order, dict) else 'N/A'}[/dim]")

                time_val = order.get("opentm", "N/A") if isinstance(order, dict) else "N/A"
                if isinstance(time_val, (int, float)):
                    time_val = datetime.fromtimestamp(time_val).strftime("%Y-%m-%d %H:%M:%S")

                pair_val = descr.get("pair", "N/A") if isinstance(descr, dict) else "N/A"
                side_val = descr.get("type", "N/A") if isinstance(descr, dict) else "N/A"
                type_val = descr.get("ordertype", "N/A") if isinstance(descr, dict) else "N/A"
                vol_val = order.get("vol", "N/A") if isinstance(order, dict) else "N/A"
                price_val = descr.get("price", "N/A") if isinstance(descr, dict) else "N/A"

                if verbose and is_first:
                    console.print(
                        f"[dim]🔍 Debug: final values: time={time_val}, pair={pair_val}, "
                        f"side={side_val}, type={type_val}, vol={vol_val}, price={price_val}[/dim]"
                    )

                first_processed = True

                table.add_row(
                    str(time_val),
                    str(pair_val),
                    str(side_val),
                    str(type_val),
                    str(vol_val),
                    str(price_val),
                )

            console.print(table)
        except Exception as exc:  # pragma: no cover - defensive user message
            console.print(f"[red]❌ Error fetching orders: {str(exc)}[/red]")

    @cli_group.command()
    @click.option("--cancel-all", is_flag=True, help="Cancel all open orders")
    @click.option("--txid", help="Order ID to cancel")
    @click.pass_context
    def cancel(  # type: ignore[unused-ignore]
        ctx: click.Context,
        cancel_all: bool,
        txid: Optional[str],
    ) -> None:
        """Cancel orders."""

        trader = _ensure_trader(ctx)
        if trader is None:
            return

        try:
            if cancel_all:
                console.print("[bold yellow]⚠️  Cancelling all open orders...[/bold yellow]")
                result = trader.cancel_all_orders()

                if result:
                    console.print("[green]✅ All orders cancelled successfully![/green]")
                else:
                    console.print("[red]❌ Failed to cancel orders[/red]")

            elif txid:
                console.print(f"[bold yellow]⚠️  Cancelling order {txid}...[/bold yellow]")
                result = trader.cancel_order(txid)

                if result:
                    console.print("[green]✅ Order cancelled successfully![/green]")
                else:
                    console.print("[red]❌ Failed to cancel order[/red]")
            else:
                console.print("[red]❌ Please specify --cancel-all or --txid[/red]")

        except Exception as exc:  # pragma: no cover - defensive user message
            console.print(f"[red]❌ Error cancelling order: {str(exc)}[/red]")

    @cli_group.command()
    @click.option("--asset", "-a", required=True, help="Kraken asset code for the withdrawal (e.g., ZUSD)")
    @click.option("--key", "-k", help="Withdrawal key configured in Kraken security settings")
    @click.option("--amount", "-n", help="Amount to withdraw")
    @click.option("--address", help="Override withdrawal address when supported")
    @click.option("--otp", help="Two-factor token when required by account security settings")
    @click.option("--method", help="Filter withdrawal method for status lookups")
    @click.option("--start", help="Unix timestamp to filter withdrawal status results")
    @click.option("--status", is_flag=True, help="Display recent withdrawal status instead of submitting a new request")
    @click.option("--confirm", is_flag=True, help="Skip interactive confirmation prompts")
    @click.pass_context
    def withdraw(  # type: ignore[unused-ignore]
        ctx: click.Context,
        asset: str,
        key: Optional[str],
        amount: Optional[str],
        address: Optional[str],
        otp: Optional[str],
        method: Optional[str],
        start: Optional[str],
        status: bool,
        confirm: bool,
    ) -> None:
        """Submit Kraken withdrawals or inspect recent withdrawal status."""

        api_client = _ensure_api_client(ctx)
        if api_client is None:
            return

        asset_code = asset.upper()

        if status:
            console.print("[bold blue]🔍 Fetching withdrawal status...[/bold blue]")
            try:
                response = call_with_retries(
                    lambda: api_client.get_withdraw_status(asset=asset_code, method=method, start=start),
                    "Withdrawal status fetch",
                    display_label="⏳ Fetching withdrawal status",
                )
            except Exception as exc:  # pragma: no cover - defensive user message
                console.print(f"[red]❌ Failed to fetch withdrawal status: {exc}[/red]")
                return

            entries: List[Dict[str, Any]]
            raw_result = response.get("result") if isinstance(response, dict) else None
            if isinstance(raw_result, list):
                entries = [entry for entry in raw_result if isinstance(entry, dict)]
            elif isinstance(raw_result, dict):
                entries = [payload for payload in raw_result.values() if isinstance(payload, dict)]
            else:
                entries = []

            if not entries:
                console.print("[yellow]ℹ️  No withdrawal records found for the selected filters.[/yellow]")
                return

            table = Table(title="Withdrawal Status", show_lines=False)
            table.add_column("RefID", style="cyan")
            table.add_column("Status", style="green")
            table.add_column("Amount", justify="right")
            table.add_column("Fee", justify="right")
            table.add_column("Method", style="magenta")
            table.add_column("Info", style="yellow")

            for entry in entries:
                table.add_row(
                    str(entry.get("refid", "N/A")),
                    str(entry.get("status", "N/A")),
                    str(entry.get("amount", "N/A")),
                    str(entry.get("fee", "0")),
                    str(entry.get("method", "N/A")),
                    str(entry.get("info", "")),
                )

            console.print(table)
            return

        if not key:
            console.print("[red]❌ Withdrawal key (--key) is required when submitting a withdrawal.[/red]")
            return

        if amount is None:
            console.print("[red]❌ Withdrawal amount (--amount) is required.[/red]")
            return

        try:
            amount_decimal = Decimal(str(amount))
        except (InvalidOperation, TypeError):
            console.print("[red]❌ Withdrawal amount must be a valid numeric value.[/red]")
            return

        if amount_decimal <= 0:
            console.print("[red]❌ Withdrawal amount must be greater than zero.[/red]")
            return

        summary_table = Table.grid(padding=(0, 1))
        summary_table.add_column(justify="right", style="cyan")
        summary_table.add_column(style="white")
        summary_table.add_row("Asset", asset_code)
        summary_table.add_row("Amount", str(amount_decimal))
        summary_table.add_row("Key", key)
        summary_table.add_row("Address", address or "(default)")
        summary_table.add_row("Sandbox", "Yes" if config.sandbox else "No")

        console.print(
            Panel(
                summary_table,
                title="Withdrawal Confirmation",
                border_style="yellow",
            )
        )

        if not confirm:
            proceed = click.confirm("Submit withdrawal request?", default=False)
            if not proceed:
                console.print("[yellow]ℹ️  Withdrawal cancelled by user.[/yellow]")
                return

        try:
            response = call_with_retries(
                lambda: api_client.request_withdrawal(
                    asset=asset_code,
                    key=key,
                    amount=str(amount_decimal),
                    address=address,
                    otp=otp,
                ),
                "Withdrawal submission",
                display_label="⏳ Submitting withdrawal",
            )
        except Exception as exc:  # pragma: no cover - defensive user message
            console.print(f"[red]❌ Withdrawal request failed: {exc}[/red]")
            return

        result_payload = response.get("result") if isinstance(response, dict) else None
        refid = None
        if isinstance(result_payload, dict):
            refid = result_payload.get("refid") or result_payload.get("txid")

        if refid:
            console.print(f"[green]✅ Withdrawal submitted successfully (refid: {refid})[/green]")
        else:
            console.print("[green]✅ Withdrawal submitted successfully.[/green]")

        if isinstance(result_payload, dict) and result_payload:
            details = Table(title="Withdrawal Result", show_lines=False)
            details.add_column("Field", style="cyan")
            details.add_column("Value", style="white")
            for field, value in result_payload.items():
                details.add_row(str(field), str(value))
            console.print(details)

    @cli_group.command()
    @click.option("--pair", "-p", required=True, help="Trading pair (e.g., ETHUSD)")
    @click.option(
        "--interval",
        "-i",
        default=15,
        show_default=True,
        type=click.IntRange(1, 1440),
        help="Candle interval in minutes.",
    )
    @click.option(
        "--limit",
        "-l",
        default=48,
        show_default=True,
        type=click.IntRange(1, 720),
        help="Number of candles to display (most recent first).",
    )
    @click.option(
        "--since",
        type=int,
        help="Unix timestamp to fetch candles since (Kraken `since` parameter).",
    )
    @click.option(
        "--output",
        "-o",
        type=click.Choice(["table", "json"], case_sensitive=False),
        default="table",
        show_default=True,
        help="Render output as a Rich table or JSON payload.",
    )
    @click.pass_context
    def ohlc(  # type: ignore[unused-ignore]
        ctx: click.Context,
        pair: str,
        interval: int,
        limit: int,
        since: Optional[int],
        output: str,
    ) -> None:
        """Fetch OHLC candles for a trading pair.

        Args:
            ctx (click.Context): Click context carrying cached clients.
            pair (str): Kraken trading pair (e.g., ``ETHUSD``).
            interval (int): Candle interval in minutes.
            limit (int): Number of rows to render.
            since (Optional[int]): Optional Unix timestamp passed to Kraken.
            output (str): Rendering mode (`table` or `json`).
        """

        api_client = _ensure_api_client(ctx)
        if api_client is None:
            return

        normalized_pair = pair.upper()
        console.print(
            f"[bold blue]📈 Fetching OHLC data for {normalized_pair} ({interval}m)...[/bold blue]"
        )

        def _fetch() -> Dict[str, Any]:
            kwargs: Dict[str, Any] = {"since": since} if since is not None else {}
            return api_client.get_ohlc_data(normalized_pair, interval=interval, **kwargs)

        try:
            response = call_with_retries(
                _fetch,
                "OHLC data fetch",
                display_label="⏳ Loading OHLC candles",
            )
        except Exception as exc:  # pragma: no cover - defensive user message
            console.print(f"[red]❌ Failed to fetch OHLC data: {exc}[/red]")
            return

        result = response.get("result", {}) if isinstance(response, dict) else {}
        candles, resolved_key = resolve_ohlc_payload(normalized_pair, result)
        if not candles:
            sample_keys = [key for key in result.keys() if key != "last"][:5]
            key_hint = ", ".join(sample_keys) if sample_keys else "none"
            console.print(
                f"[yellow]⚠️  No OHLC data returned for {normalized_pair}. Available keys: {key_hint}[/yellow]"
            )
            return

        rows = list(candles)
        if not rows:
            console.print("[yellow]ℹ️  OHLC payload was empty.[/yellow]")
            return

        limited_rows = rows[-limit:]

        def _convert_row(raw: List[Any]) -> Dict[str, Any]:
            timestamp = int(raw[0])
            ts = datetime.fromtimestamp(timestamp, tz=timezone.utc)
            formatted_time = ts.strftime("%Y-%m-%d %H:%M:%S")
            open_, high, low, close = (float(raw[idx]) for idx in range(1, 5))
            vwap = float(raw[5])
            volume = float(raw[6])
            count = int(raw[7])
            return {
                "time": formatted_time,
                "open": open_,
                "high": high,
                "low": low,
                "close": close,
                "vwap": vwap,
                "volume": volume,
                "count": count,
            }

        converted = [_convert_row(entry) for entry in limited_rows]
        resolved_label = resolved_key or normalized_pair
        last_marker = result.get("last")

        if output.lower() == "json":
            payload = {
                "pair": resolved_label,
                "interval": interval,
                "count": len(converted),
                "last": last_marker,
                "candles": converted,
            }
            console.print(json.dumps(payload, indent=2, default=str))
            return

        def _fmt(value: float) -> str:
            if abs(value) >= 1:
                return f"{value:,.2f}"
            return f"{value:.8f}".rstrip("0").rstrip(".") or "0"

        table = Table(
            title=f"OHLC {resolved_label} — {interval}m",
            show_lines=False,
            expand=False,
        )
        table.add_column("Time (UTC)", style="cyan")
        table.add_column("Open", justify="right", style="green")
        table.add_column("High", justify="right", style="green")
        table.add_column("Low", justify="right", style="red")
        table.add_column("Close", justify="right", style="magenta")
        table.add_column("Vol", justify="right", style="yellow")

        for row in converted:
            table.add_row(
                row["time"],
                _fmt(row["open"]),
                _fmt(row["high"]),
                _fmt(row["low"]),
                _fmt(row["close"]),
                f"{row['volume']:,.4f}",
            )

        console.print(table)
        if last_marker:
            console.print(f"[dim]Next 'since' token: {last_marker}[/dim]")

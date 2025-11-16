"""Data operations CLI for KrakenCLI.

Provides commands to synchronize OHLC data from Kraken into a local SQLite
database for reliable historical access and faster pattern scans.

Updates:
    v0.10.0 - 2025-11-16 - Added 'data ohlc-sync' command with SQLite storage.
"""

from __future__ import annotations

import logging
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

import click
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table

from api.kraken_client import KrakenAPIClient
from config import Config
from utils.market_data import resolve_ohlc_payload

logger = logging.getLogger(__name__)

DB_PATH_DEFAULT = Path("data") / "ohlc.db"

_TIMEFRAME_LABEL_TO_MINUTES: Dict[str, int] = {
    "1m": 1,
    "5m": 5,
    "15m": 15,
    "1h": 60,
    "4h": 240,
    "1d": 1440,
}


def _parse_timeframe_label(label: str) -> int:
    """Convert a timeframe label to minutes.

    Args:
        label: Candle interval label ('1m', '5m', '15m', '1h', '4h', '1d').

    Returns:
        Interval length in minutes.

    Raises:
        click.BadParameter: If the label is unsupported.
    """
    normalized = label.strip().lower()
    minutes = _TIMEFRAME_LABEL_TO_MINUTES.get(normalized)
    if minutes is None:
        raise click.BadParameter(
            f"Unsupported timeframe '{label}'. "
            "Use one of: 1m, 5m, 15m, 1h, 4h, 1d"
        )
    return minutes


def _parse_time_input(value: Optional[str]) -> Optional[int]:
    """Parse time input as epoch seconds or ISO date/datetime.

    Args:
        value: String value to parse. Accepts:
            - Epoch seconds integer (e.g., '1731763200')
            - ISO date 'YYYY-MM-DD'
            - ISO datetime 'YYYY-MM-DDTHH:MM:SS'

    Returns:
        Epoch seconds (int) or None when value was None.

    Raises:
        click.BadParameter: If parsing fails.
    """
    if value is None:
        return None

    candidate = value.strip()
    if not candidate:
        return None

    # Epoch seconds
    try:
        return int(candidate)
    except ValueError:
        pass

    # ISO date
    try:
        dt = datetime.strptime(candidate, "%Y-%m-%d")
        return int(dt.replace(tzinfo=timezone.utc).timestamp())
    except ValueError:
        pass

    # ISO datetime
    try:
        dt = datetime.strptime(candidate, "%Y-%m-%dT%H:%M:%S")
        return int(dt.replace(tzinfo=timezone.utc).timestamp())
    except ValueError:
        pass

    raise click.BadParameter(
        f"Invalid time '{value}'. Provide epoch seconds or "
        "ISO 'YYYY-MM-DD' or 'YYYY-MM-DDTHH:MM:SS'."
    )


def _ensure_db_schema(conn: sqlite3.Connection) -> None:
    """Create the OHLC schema and indexes if missing."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS ohlc_bars (
            pair TEXT NOT NULL,
            timeframe_minutes INTEGER NOT NULL,
            time INTEGER NOT NULL,
            open REAL NOT NULL,
            high REAL NOT NULL,
            low REAL NOT NULL,
            close REAL NOT NULL,
            vwap REAL,
            volume REAL,
            count INTEGER,
            PRIMARY KEY (pair, timeframe_minutes, time)
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_ohlc_pair_tf_time
        ON ohlc_bars(pair, timeframe_minutes, time)
        """
    )
    conn.commit()


def _ensure_api_client(
    ctx: click.Context, console: Console, config: Config
) -> Optional[KrakenAPIClient]:
    """Get or create an authenticated Kraken API client."""
    api_client: Optional[KrakenAPIClient] = ctx.obj.get("api_client")
    if api_client is not None:
        return api_client

    if not config.has_credentials():
        console.print("[red]⚠️  API credentials not configured![/red]")
        console.print(
            "[yellow]Please configure your Kraken API credentials in .env file[/yellow]"
        )
        console.print("[yellow]See README.md for setup instructions[/yellow]")
        return None

    try:
        api_client = KrakenAPIClient(
            api_key=config.api_key, api_secret=config.api_secret, sandbox=config.sandbox
        )
    except Exception as exc:
        console.print(f"[red]❌ Failed to initialize API client: {exc}[/red]")
        return None

    ctx.obj["api_client"] = api_client
    return api_client


def _insert_bars(
    conn: sqlite3.Connection,
    pair: str,
    timeframe_minutes: int,
    bars: Iterable[Iterable[Any]],
) -> int:
    """Insert OHLC bars with upsert on conflict.

    Args:
        conn: SQLite connection.
        pair: Trading pair identifier (e.g., 'ETHUSD').
        timeframe_minutes: Interval length in minutes.
        bars: Iterable of bar arrays in Kraken format:
            [time, open, high, low, close, vwap, volume, count]

    Returns:
        Number of rows inserted (conflicts are ignored).
    """
    rows = [
        (
            pair,
            timeframe_minutes,
            int(bar[0]),
            float(bar[1]),
            float(bar[2]),
            float(bar[3]),
            float(bar[4]),
            float(bar[5]) if len(bar) > 5 and bar[5] is not None else None,
            float(bar[6]) if len(bar) > 6 and bar[6] is not None else None,
            int(bar[7]) if len(bar) > 7 and bar[7] is not None else None,
        )
        for bar in bars
    ]
    if not rows:
        return 0

    cursor = conn.cursor()
    cursor.executemany(
        """
        INSERT INTO ohlc_bars (
            pair, timeframe_minutes, time,
            open, high, low, close, vwap, volume, count
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(pair, timeframe_minutes, time) DO NOTHING
        """,
        rows,
    )
    conn.commit()
    return cursor.rowcount


def register(
    cli_group: click.Group,
    *,
    console: Console,
    config: Config,
    call_with_retries: Callable[[Callable[[], Any], str, Optional[str]], Any],
) -> None:
    """Register the 'data' CLI group and 'ohlc-sync' command.

    Exposes:
        data ohlc-sync - Backfill OHLC candles into SQLite.

    The command supports:
        - --pair/-p: trading pair (e.g., ETHUSD)
        - --timeframe/-t: interval label (1m, 5m, 15m, 1h, 4h, 1d)
        - --days/-d: number of days to backfill (default 365)
        - --since/--until: start/end times (epoch seconds or ISO)
    """

    @cli_group.group(name="data")
    @click.pass_context
    def data(ctx: click.Context) -> None:  # type: ignore[unused-ignore]
        """Data operations (import/sync/cache)."""
        # no-op group initializer

    @data.command(name="ohlc-sync")
    @click.option(
        "--pair",
        "-p",
        required=True,
        help="Trading pair (e.g., ETHUSD)",
    )
    @click.option(
        "--timeframe",
        "-t",
        required=True,
        help="Candle interval label (1m, 5m, 15m, 1h, 4h, 1d)",
    )
    @click.option(
        "--days",
        "-d",
        type=click.IntRange(1, 5000),
        default=365,
        show_default=True,
        help="Number of days to backfill when --since/--until not provided.",
    )
    @click.option(
        "--since",
        type=str,
        default=None,
        help="Start time (epoch seconds or ISO 'YYYY-MM-DD' or 'YYYY-MM-DDT%H:%M:%S').",
    )
    @click.option(
        "--until",
        type=str,
        default=None,
        help="End time (epoch seconds or ISO 'YYYY-MM-DD' or 'YYYY-MM-DDT%H:%M:%S').",
    )
    @click.pass_context
    def ohlc_sync(  # type: ignore[unused-ignore]
        ctx: click.Context,
        pair: str,
        timeframe: str,
        days: int,
        since: Optional[str],
        until: Optional[str],
    ) -> None:
        """Synchronize OHLC candles from Kraken into SQLite.

        Examples:
            # Backfill 365 days of ETHUSD 15-minute candles
            kraken_cli.py data ohlc-sync -p ETHUSD -t 15m

            # Backfill last 90 days of 1-hour candles
            kraken_cli.py data ohlc-sync -p ETHUSD -t 1h -d 90

            # Backfill from a specific start date until now
            kraken_cli.py data ohlc-sync -p ETHUSD -t 1h --since 2025-01-01

            # Backfill between explicit timestamps
            kraken_cli.py data ohlc-sync -p ETHUSD -t 1h --since 2025-01-01 --until 2025-03-01
        """
        api_client = _ensure_api_client(ctx, console, config)
        if api_client is None:
            return

        interval_minutes = _parse_timeframe_label(timeframe)

        now_sec = int(time.time())
        start_ts = _parse_time_input(since)
        end_ts = _parse_time_input(until)

        if start_ts is None and end_ts is None:
            # Default window: last 'days'
            end_ts = now_sec
            start_ts = max(0, end_ts - days * 86400)
        elif start_ts is None and end_ts is not None:
            # Only 'until' provided: go back 'days' from until
            start_ts = max(0, end_ts - days * 86400)
        elif start_ts is not None and end_ts is None:
            # Only 'since' provided: up to now
            end_ts = now_sec

        assert start_ts is not None and end_ts is not None

        # Prepare database
        try:
            DB_PATH_DEFAULT.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            console.print(f"[red]❌ Failed to prepare data directory: {exc}[/red]")
            return

        try:
            conn = sqlite3.connect(DB_PATH_DEFAULT.as_posix())
        except sqlite3.Error as exc:
            console.print(f"[red]❌ Failed to open database: {exc}[/red]")
            return

        try:
            _ensure_db_schema(conn)
        except sqlite3.Error as exc:
            console.print(f"[red]❌ Failed to initialize schema: {exc}[/red]")
            conn.close()
            return

        console.print(
            Panel.fit(
                f"Pair: [cyan]{pair}[/cyan]\n"
                f"Timeframe: [cyan]{timeframe}[/cyan] "
                f"([green]{interval_minutes} min[/green])\n"
                f"Window: [cyan]{start_ts}[/cyan] → [cyan]{end_ts}[/cyan]\n"
                f"DB: [magenta]{DB_PATH_DEFAULT}[/magenta]",
                title="OHLC Sync",
                border_style="blue",
            )
        )

        inserted_total = 0
        request_count = 0
        current_since = start_ts

        # Avoid nested Rich Live/Progress contexts to prevent runtime errors.
        # Rely on the entrypoint's call_with_retries progress rendering instead.
        while True:
            def _fetch() -> Dict[str, Any]:
                return api_client.get_ohlc_data(
                    pair=pair, interval=interval_minutes, since=current_since
                )

            try:
                payload = call_with_retries(
                    _fetch,
                    "OHLC fetch",
                    display_label=(
                        f"OHLC {pair} {interval_minutes}m since {current_since}"
                    ),
                )
            except Exception as exc:
                console.print(f"[red]❌ API error: {exc}[/red]")
                break

            request_count += 1
            result = payload.get("result", {}) if payload else {}
            bars_iter, resolved_key = resolve_ohlc_payload(pair, result)
            last_ts_raw = result.get("last")
            try:
                last_ts = int(last_ts_raw) if last_ts_raw is not None else 0
            except (TypeError, ValueError):
                last_ts = 0

            bars_list: List[Any] = list(bars_iter or [])
            if not bars_list:
                # No bars for this request; stop if we cannot advance
                if last_ts <= current_since or last_ts == 0:
                    console.print("[yellow]ℹ️ No more data available[/yellow]")
                    break

            try:
                inserted = _insert_bars(conn, pair, interval_minutes, bars_list)
            except sqlite3.Error as exc:
                console.print(f"[red]❌ DB insert failed: {exc}[/red]")
                break

            inserted_total += inserted

            # Determine next window advancement
            if last_ts <= current_since or last_ts == 0:
                # Safety: prevent infinite loop
                console.print(
                    "[yellow]⚠️ Unable to advance 'since' marker; stopping[/yellow]"
                )
                break

            current_since = last_ts

            # Stop when we reached or passed the end window
            if current_since >= end_ts:
                break

        conn.close()

        table = Table(title="OHLC Sync Summary")
        table.add_column("Metric", style="cyan")
        table.add_column("Value", style="green")
        table.add_row("Pair", pair)
        table.add_row("Timeframe", f"{timeframe} ({interval_minutes}m)")
        table.add_row("Requests", str(request_count))
        table.add_row("Inserted Bars", str(inserted_total))
        table.add_row("DB Path", str(DB_PATH_DEFAULT))
        console.print(table)

        if inserted_total > 0:
            console.print("[green]✅ Sync completed[/green]")
        else:
            console.print("[yellow]ℹ️ No rows inserted[/yellow]")
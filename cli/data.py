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
import json
import csv
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
from utils.market_data import resolve_ohlc_payload, candidate_pair_keys

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


def _iter_bars_from_trades_csv(
    file_path: Path,
    interval_minutes: int,
    *,
    since_ts: Optional[int] = None,
    until_ts: Optional[int] = None,
) -> Iterable[List[Any]]:
    """Yield OHLC bars aggregated from a trades CSV.

    The input CSV must contain rows:
        timestamp_unix,price,volume

    Args:
        file_path: Path to the trades CSV file.
        interval_minutes: Candle interval in minutes.
        since_ts: Optional inclusive start timestamp (epoch seconds).
        until_ts: Optional inclusive end timestamp (epoch seconds).

    Yields:
        Lists in Kraken OHLC format:
        [time, open, high, low, close, vwap, volume, count]
    """
    step = max(1, interval_minutes * 60)

    current_start: Optional[int] = None
    open_price: Optional[float] = None
    high_price: Optional[float] = None
    low_price: Optional[float] = None
    close_price: Optional[float] = None
    volume_sum = 0.0
    vwap_numerator = 0.0
    trade_count = 0

    def flush_current() -> Optional[List[Any]]:
        nonlocal current_start, open_price, high_price, low_price, close_price
        nonlocal volume_sum, vwap_numerator, trade_count

        if current_start is None or trade_count == 0 or open_price is None:
            return None

        vwap: Optional[float]
        if volume_sum > 0.0:
            vwap = vwap_numerator / volume_sum
            volume_out: Optional[float] = volume_sum
        else:
            vwap = None
            volume_out = None

        bar: List[Any] = [
            int(current_start),
            float(open_price),
            float(high_price if high_price is not None else open_price),
            float(low_price if low_price is not None else open_price),
            float(close_price if close_price is not None else open_price),
            vwap,
            volume_out,
            int(trade_count),
        ]

        current_start = None
        open_price = None
        high_price = None
        low_price = None
        close_price = None
        volume_sum = 0.0
        vwap_numerator = 0.0
        trade_count = 0

        return bar

    with file_path.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.reader(fh)
        for row in reader:
            if not row:
                continue

            first = row[0].strip()
            if not first:
                continue
            if not (first[0].isdigit() or first.startswith("-")):
                # Skip header or comment-like lines
                continue

            try:
                ts = int(first)
                price = float(row[1])
                volume = float(row[2])
            except (ValueError, IndexError):
                logger.debug("Skipping malformed trade CSV row: %s", row)
                continue

            if since_ts is not None and ts < since_ts:
                continue
            if until_ts is not None and ts > until_ts:
                break

            bucket_start = (ts // step) * step

            if current_start is None:
                current_start = bucket_start
                open_price = price
                high_price = price
                low_price = price
                close_price = price
                volume_sum = volume
                vwap_numerator = price * volume
                trade_count = 1
                continue

            if bucket_start != current_start:
                prev_bar = flush_current()
                if prev_bar is not None:
                    yield prev_bar

                current_start = bucket_start
                open_price = price
                high_price = price
                low_price = price
                close_price = price
                volume_sum = volume
                vwap_numerator = price * volume
                trade_count = 1
                continue

            # Same bucket: update OHLCV
            if high_price is None or price > high_price:
                high_price = price
            if low_price is None or price < low_price:
                low_price = price
            close_price = price
            volume_sum += volume
            vwap_numerator += price * volume
            trade_count += 1

    final_bar = flush_current()
    if final_bar is not None:
        yield final_bar


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


def _count_existing_bars(
    conn: sqlite3.Connection,
    pair: str,
    timeframe_minutes: int,
    times: Iterable[int],
) -> int:
    """Count existing OHLC rows for given (pair, timeframe, time) keys.

    Args:
        conn: SQLite connection.
        pair: Trading pair identifier (e.g., 'ETHUSD').
        timeframe_minutes: Interval length in minutes.
        times: Iterable of epoch times to check.

    Returns:
        Number of rows already present in the database for the provided keys.
    """
    ts_list = list(times)
    if not ts_list:
        return 0

    # Chunk IN() parameter list to avoid excessive parameter counts
    chunk_size = 500
    total = 0
    cursor = conn.cursor()

    for i in range(0, len(ts_list), chunk_size):
        chunk = ts_list[i : i + chunk_size]
        placeholders = ",".join("?" for _ in chunk)
        query = (
            f"SELECT COUNT(1) FROM ohlc_bars "
            f"WHERE pair=? AND timeframe_minutes=? AND time IN ({placeholders})"
        )
        params: List[Any] = [pair, timeframe_minutes, *chunk]
        try:
            cursor.execute(query, params)
            row = cursor.fetchone()
            total += int(row[0]) if row and row[0] is not None else 0
        except sqlite3.Error as exc:
            logger.debug("Existing bars count failed: %s", exc)
            break

    return total


def _get_max_existing_time(
    conn: sqlite3.Connection,
    pair: str,
    timeframe_minutes: int,
) -> Optional[int]:
    """Return the maximum time present for a pair/timeframe.

    Args:
        conn: SQLite connection.
        pair: Trading pair identifier (e.g., 'ETHUSD').
        timeframe_minutes: Interval length in minutes.

    Returns:
        The greatest epoch time stored for the pair/timeframe, or None if
        no rows exist.
    """
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT MAX(time) FROM ohlc_bars WHERE pair=? AND timeframe_minutes=?",
            (pair, timeframe_minutes),
        )
        row = cursor.fetchone()
        return int(row[0]) if row and row[0] is not None else None
    except sqlite3.Error as exc:
        logger.debug("Failed to get MAX(time): %s", exc)
        return None


def _has_bars_since(
    conn: sqlite3.Connection,
    pair: str,
    timeframe_minutes: int,
    start_ts: int,
) -> bool:
    """Return True if DB has any bars at or after start_ts for pair/timeframe.

    Args:
        conn: SQLite connection.
        pair: Trading pair identifier.
        timeframe_minutes: Interval length in minutes.
        start_ts: Start epoch seconds (inclusive).

    Returns:
        True when at least one row exists with time >= start_ts.
    """
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT EXISTS(SELECT 1 FROM ohlc_bars "
            "WHERE pair=? AND timeframe_minutes=? AND time >= ? LIMIT 1)",
            (pair, timeframe_minutes, start_ts),
        )
        row = cursor.fetchone()
        return bool(row[0]) if row else False
    except sqlite3.Error as exc:
        logger.debug("has_bars_since check failed: %s", exc)
        return False


# Gap detection helpers for OHLC SQLite storage

def _align_window(start_ts: int, end_ts: int, step: int) -> tuple[int, int]:
    """Align a window to the candle grid in epoch seconds.
    
    Args:
        start_ts: Window start timestamp (epoch seconds).
        end_ts: Window end timestamp (epoch seconds).
        step: Candle step in seconds (timeframe_minutes * 60).
    
    Returns:
        Tuple of aligned start and end timestamps (Astart, Aend) such that:
        - Astart is the smallest multiple of step >= start_ts
        - Aend is the largest multiple of step <= end_ts
        - If window is empty after alignment, returns (0, -1).
    """
    if end_ts < start_ts:
        return 0, -1
    aligned_start = ((start_ts + step - 1) // step) * step
    aligned_end = (end_ts // step) * step
    return aligned_start, aligned_end


def _iter_existing_candle_times(
    conn: sqlite3.Connection,
    pair: str,
    timeframe_minutes: int,
    start_ts: int,
    end_ts: int,
) -> Iterable[int]:
    """Yield ordered candle times present in DB within [start_ts, end_ts].
    
    Args:
        conn: SQLite connection.
        pair: Trading pair (e.g., 'ETHUSD').
        timeframe_minutes: Interval length in minutes.
        start_ts: Window start (inclusive, epoch seconds).
        end_ts: Window end (inclusive, epoch seconds).
    
    Yields:
        Candle start timestamps as integers in ascending order.
    """
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT time
        FROM ohlc_bars
        WHERE pair=? AND timeframe_minutes=? AND time BETWEEN ? AND ?
        ORDER BY time
        """,
        (pair, timeframe_minutes, start_ts, end_ts),
    )
    for row in cursor:
        try:
            yield int(row[0])
        except (TypeError, ValueError):
            # Skip malformed rows; schema should prevent these.
            continue


def find_ohlc_gaps(
    conn: sqlite3.Connection,
    pair: str,
    timeframe_minutes: int,
    start_ts: int,
    end_ts: int,
) -> tuple[list[dict[str, int]], dict[str, float]]:
    """Compute missing candle ranges for (pair, timeframe, window).
    
    This scans the local SQLite OHLC store and returns contiguous missing
    ranges as gap records, along with coverage metrics for the window.
    
    Args:
        conn: SQLite connection.
        pair: Trading pair identifier (e.g., 'ETHUSD').
        timeframe_minutes: Interval length in minutes.
        start_ts: Window start (epoch seconds, inclusive).
        end_ts: Window end (epoch seconds, inclusive).
    
    Returns:
        Tuple of:
        - gaps: list of dicts with keys:
            - start_ts: inclusive missing timestamp
            - end_ts_exclusive: exclusive bound (next expected or window end + step)
            - missing_count: number of missing candles in the gap
        - summary: dict with coverage metrics:
            - expected: number of expected candles in the aligned window
            - present: number of present candles found
            - missing: total missing candle count across gaps
            - coverage_ratio: present / expected (0.0..1.0)
    
    Notes:
        - Window is aligned to the candle grid before scanning.
        - All times are UTC epoch seconds of candle starts.
    """
    step = timeframe_minutes * 60
    aligned_start, aligned_end = _align_window(start_ts, end_ts, step)
    if aligned_start > aligned_end:
        return [], {
            "expected": 0.0,
            "present": 0.0,
            "missing": 0.0,
            "coverage_ratio": 1.0,
        }

    expected_count = ((aligned_end - aligned_start) // step) + 1

    gaps: list[dict[str, int]] = []
    present_count = 0
    expected = aligned_start

    for present in _iter_existing_candle_times(
        conn, pair, timeframe_minutes, aligned_start, aligned_end
    ):
        # Ignore any unexpected or duplicate entries behind the cursor
        if present < expected:
            continue

        # Missing region up to 'present'
        if expected < present:
            gaps.append(
                {
                    "start_ts": expected,
                    "end_ts_exclusive": present,
                    "missing_count": (present - expected) // step,
                }
            )

        # Accept the present candle and advance cursor
        present_count += 1
        expected = present + step

    # Trailing gap to end of window (if any)
    if expected <= aligned_end:
        gaps.append(
            {
                "start_ts": expected,
                "end_ts_exclusive": aligned_end + step,
                "missing_count": ((aligned_end + step) - expected) // step,
            }
        )

    missing_total = sum(g["missing_count"] for g in gaps)
    coverage_ratio = (
        present_count / expected_count if expected_count else 1.0
    )

    summary = {
        "expected": float(expected_count),
        "present": float(present_count),
        "missing": float(missing_total),
        "coverage_ratio": coverage_ratio,
    }
    return gaps, summary
def _fill_gaps_in_window(
    conn: sqlite3.Connection,
    api_client: KrakenAPIClient,
    request_pair: str,
    interval_minutes: int,
    start_ts: int,
    end_ts: int,
    console: Console,
) -> tuple[int, int]:
    """Backfill only missing OHLC candles for the given window.
    
    This function:
    - Detects gaps using find_ohlc_gaps
    - Iterates gaps in order and fetches OHLC with Kraken's `since` token
    - Inserts rows into SQLite, relying on PK conflict to skip duplicates
    - Honors ≤1 public request/sec per HTTP call
    
    Args:
        conn: Open SQLite connection to the OHLC database.
        api_client: Kraken API client for public OHLC requests.
        request_pair: Normalized pair (e.g., 'ETHUSD').
        interval_minutes: Candle interval in minutes.
        start_ts: Inclusive window start (epoch seconds).
        end_ts: Inclusive window end (epoch seconds).
        console: Rich console for status messages.
    
    Returns:
        Tuple of (inserted_total, request_count).
    """
    inserted_total = 0
    request_count = 0

    gaps, summary = find_ohlc_gaps(
        conn=conn,
        pair=request_pair,
        timeframe_minutes=interval_minutes,
        start_ts=start_ts,
        end_ts=end_ts,
    )

    if not gaps:
        console.print("[green]✅ No gaps to fill in the selected window[/green]")
        return 0, 0

    step = max(1, interval_minutes * 60)
    last_public_call_ts = 0.0

    # Enforce Kraken OHLC retrieval horizon (max 720 most recent candles).
    now_sec = int(time.time())
    max_entries = 720
    retrievable_start = max(0, now_sec - (max_entries * step))

    if end_ts < retrievable_start:
        console.print(
            "[yellow]⚠️ Requested window is entirely older than Kraken OHLC "
            "retrieval horizon for this timeframe.[/yellow]"
        )
        console.print(
            f"[dim]Timeframe={interval_minutes}m → retrievable horizon start="
            f"{retrievable_start}[/dim]"
        )
        console.print(
            "[blue]ℹ️ Tips:[/blue] Use a larger timeframe (e.g., 1d has ~720 days), "
            "or source historical data externally."
        )
        return 0, 0

    if start_ts < retrievable_start:
        console.print(
            "[yellow]⚠️ Clamping start of window to Kraken OHLC horizon "
            "(older candles cannot be fetched).[/yellow]"
        )
        console.print(
            f"[dim]Original start={start_ts} → Effective start={retrievable_start}[/dim]"
        )
        start_ts = retrievable_start

    for idx, gap in enumerate(gaps, start=1):
        gap_start = int(gap.get("start_ts", start_ts))
        gap_end_exclusive = int(gap.get("end_ts_exclusive", end_ts + step))
        gap_missing = int(gap.get("missing_count", 0))
        current_since = gap_start

        # Local timestamp formatter for readable progress output
        def _fmt_ts(ts: int) -> str:
            try:
                dt = datetime.fromtimestamp(ts, tz=timezone.utc)
                return dt.strftime("%Y-%m-%d %H:%M:%S")
            except Exception:
                return str(ts)

        console.print(
            f"[dim]Gap {idx}/{len(gaps)}: {_fmt_ts(gap_start)} → "
            f"{_fmt_ts(gap_end_exclusive)} (missing {gap_missing})[/dim]"
        )
        gap_inserted = 0

        # Fetch until Kraken's last marker reaches the end of this gap
        while True:
            # Per-call throttle: ≤ 1 req/sec
            now_monotonic = time.monotonic()
            wait = max(0.0, 1.0 - (now_monotonic - last_public_call_ts))
            if wait > 0.0:
                if logger.isEnabledFor(logging.DEBUG):
                    console.print(f"[dim]Throttling {wait:.2f}s (rate limit)[/dim]")
                time.sleep(wait)

            candidates = candidate_pair_keys(request_pair)
            payload: Dict[str, Any] | None = None
            rows: List[Any] = []

            # Try candidate pair keys to resolve OHLC payload
            for attempt_pair in candidates:
                try:
                    if logger.isEnabledFor(logging.DEBUG):
                        console.print(
                            f"[dim]Fetching {attempt_pair} since={current_since} "
                            f"interval={interval_minutes}m[/dim]"
                        )
                    payload = api_client.get_ohlc_data(
                        pair=attempt_pair,
                        interval=interval_minutes,
                        since=current_since,
                    )
                    request_count += 1
                    last_public_call_ts = time.monotonic()
                except Exception as exc:
                    request_count += 1
                    last_public_call_ts = time.monotonic()
                    msg = str(exc)
                    if ("Too many requests" in msg) or ("429" in msg):
                        console.print(
                            f"[yellow]⚠️ Rate limited on {attempt_pair}; "
                            "backing off 2.0s[/yellow]"
                        )
                        time.sleep(2.0)
                        continue
                    payload = None

                if not payload:
                    continue

                result = payload.get("result", {}) if isinstance(payload, dict) else {}
                bars_iter, _resolved_key = resolve_ohlc_payload(attempt_pair, result)
                rows = list(bars_iter or [])
                break

            if not payload:
                # Unable to fetch for this gap with any candidate; move to next gap
                console.print(
                    f"[yellow]⚠️ Skipping gap starting at {_fmt_ts(gap_start)} "
                    "(no payload returned)[/yellow]"
                )
                break

            # Filter rows within the gap window to avoid overshoot inserts
            filtered_rows = [
                b for b in rows
                if int(b[0]) >= current_since and int(b[0]) < gap_end_exclusive
            ]

            if filtered_rows:
                try:
                    inserted = _insert_bars(
                        conn, request_pair, interval_minutes, filtered_rows
                    )
                except sqlite3.Error as exc:
                    console.print(f"[red]❌ DB insert failed during gap fill: {exc}[/red]")
                    break

                inserted_total += inserted
                gap_inserted += inserted
                if logger.isEnabledFor(logging.DEBUG):
                    console.print(
                        f"[dim]Inserted {inserted} rows for "
                        f"{request_pair} (since={current_since})[/dim]"
                    )

            # Advance using Kraken's 'last' token
            last_raw = (
                payload.get("result", {}) if isinstance(payload, dict) else {}
            ).get("last")
            try:
                last_ts = int(last_raw) if last_raw is not None else 0
            except (TypeError, ValueError):
                last_ts = 0

            if last_ts == 0:
                # No more data available according to Kraken; stop this gap
                console.print("[yellow]ℹ️ No more data available for this gap[/yellow]")
                break

            if last_ts >= (gap_end_exclusive - step):
                # We have covered this gap sufficiently
                console.print(
                    f"[dim]Gap {idx}/{len(gaps)} covered up to {_fmt_ts(last_ts)}[/dim]"
                )
                break

            current_since = last_ts

        console.print(
            f"[green]✅ Completed gap {idx}/{len(gaps)}; "
            f"inserted {gap_inserted} bars[/green]"
        )

    return inserted_total, request_count

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
    @click.option(
        "--inspect-gaps",
        is_flag=True,
        help="Inspect DB for missing candles in the requested window (no sync).",
    )
    @click.option(
        "--gaps-output",
        type=click.Choice(["table", "json"], case_sensitive=False),
        default="table",
        show_default=True,
        help="Output format for gap inspection.",
    )
    @click.option(
        "--fill-gaps",
        is_flag=True,
        help="Backfill only missing candles within the requested window.",
    )
    @click.pass_context
    def ohlc_sync(  # type: ignore[unused-ignore]
        ctx: click.Context,
        pair: str,
        timeframe: str,
        days: int,
        since: Optional[str],
        until: Optional[str],
        inspect_gaps: bool,
        gaps_output: str,
        fill_gaps: bool,
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
        request_pair = pair.upper()

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

        # Kraken OHLC limitation: returns up to 720 most recent entries only.
        # Older data cannot be retrieved regardless of 'since'. Enforce this
        # constraint by clamping the start of the requested window to the
        # retrievable horizon and warn the user when a full historical backfill
        # is not possible for the selected timeframe.
        step_seconds = interval_minutes * 60
        max_entries = 720
        retrievable_start = max(0, now_sec - (max_entries * step_seconds))

        if end_ts < retrievable_start:
            console.print(
                "[yellow]⚠️ Requested window is entirely older than Kraken OHLC "
                "retrieval horizon for this timeframe.[/yellow]"
            )
            console.print(
                f"[dim]Timeframe={interval_minutes}m → retrievable horizon start="
                f"{retrievable_start}[/dim]"
            )
            console.print(
                "[blue]ℹ️ Tips:[/blue] Use a larger timeframe (e.g., 1d has ~720 days), "
                "or source historical data externally."
            )
            return

        if start_ts < retrievable_start:
            console.print(
                "[yellow]⚠️ Clamping start of window to Kraken OHLC horizon "
                "(older candles cannot be fetched).[/yellow]"
            )
            console.print(
                f"[dim]Original start={start_ts} → Effective start={retrievable_start}[/dim]"
            )
            start_ts = retrievable_start

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
                f"Pair: [cyan]{request_pair}[/cyan]\n"
                f"Timeframe: [cyan]{timeframe}[/cyan] "
                f"([green]{interval_minutes} min[/green])\n"
                f"Window: [cyan]{start_ts}[/cyan] → [cyan]{end_ts}[/cyan]\n"
                f"DB: [magenta]{DB_PATH_DEFAULT}[/magenta]",
                title="OHLC Sync",
                border_style="blue",
            )
        )

        # Optional gap inspection: compute and display gaps, then exit early
        if inspect_gaps:
            try:
                gaps, summary = find_ohlc_gaps(
                    conn=conn,
                    pair=request_pair,
                    timeframe_minutes=interval_minutes,
                    start_ts=start_ts,
                    end_ts=end_ts,
                )
            except Exception as exc:
                conn.close()
                console.print(f"[red]❌ Gap inspection failed: {exc}[/red]")
                return

            step_seconds = interval_minutes * 60
            if gaps_output.lower() == "json":
                payload: Dict[str, Any] = {
                    "pair": request_pair,
                    "timeframe": timeframe,
                    "window": {"start": start_ts, "end": end_ts},
                    "step_seconds": step_seconds,
                    "coverage": {
                        "expected": int(summary.get("expected", 0.0)),
                        "present": int(summary.get("present", 0.0)),
                        "missing": int(summary.get("missing", 0.0)),
                        "ratio": float(summary.get("coverage_ratio", 0.0)),
                    },
                    "gaps": gaps,
                }
                console.print(json.dumps(payload, indent=2))
                conn.close()
                return

            coverage_table = Table(title="OHLC Coverage Summary")
            coverage_table.add_column("Metric", style="cyan")
            coverage_table.add_column("Value", style="green")
            coverage_table.add_row("Expected", str(int(summary.get("expected", 0.0))))
            coverage_table.add_row("Present", str(int(summary.get("present", 0.0))))
            coverage_table.add_row("Missing", str(int(summary.get("missing", 0.0))))
            coverage_table.add_row(
                "Coverage Ratio",
                f"{float(summary.get('coverage_ratio', 0.0)):.4f}",
            )
            console.print(coverage_table)

            gaps_table = Table(title="Detected Gaps", show_lines=False)
            gaps_table.add_column("Start (UTC)", style="cyan")
            gaps_table.add_column("End (UTC, excl.)", style="magenta")
            gaps_table.add_column("Missing Candles", justify="right", style="yellow")

            def _fmt_ts(ts: int) -> str:
                try:
                    dt = datetime.fromtimestamp(ts, tz=timezone.utc)
                    return dt.strftime("%Y-%m-%d %H:%M:%S")
                except Exception:
                    return str(ts)

            if not gaps:
                console.print("[green]✅ No gaps detected in the selected window[/green]")
            else:
                for gap in gaps:
                    start_val = int(gap.get("start_ts", 0))
                    end_excl = int(gap.get("end_ts_exclusive", 0))
                    count = int(gap.get("missing_count", 0))
                    gaps_table.add_row(_fmt_ts(start_val), _fmt_ts(end_excl), str(count))
                console.print(gaps_table)

            conn.close()
            return

        # Optional gaps-only backfill path
        if fill_gaps:
            try:
                inserted_total, request_count = _fill_gaps_in_window(
                    conn=conn,
                    api_client=api_client,
                    request_pair=request_pair,
                    interval_minutes=interval_minutes,
                    start_ts=start_ts,
                    end_ts=end_ts,
                    console=console,
                )
            except Exception as exc:
                console.print(f"[red]❌ Gap fill failed: {exc}[/red]")
                conn.close()
                return

            conn.close()

            table = Table(title="OHLC Gap Fill Summary")
            table.add_column("Metric", style="cyan")
            table.add_column("Value", style="green")
            table.add_row("Pair", pair)
            table.add_row("Timeframe", f"{timeframe} ({interval_minutes}m)")
            table.add_row("Requests", str(request_count))
            table.add_row("Inserted Bars", str(inserted_total))
            table.add_row("DB Path", str(DB_PATH_DEFAULT))
            console.print(table)

            if inserted_total > 0:
                console.print("[green]✅ Gap fill completed[/green]")
            else:
                console.print("[yellow]ℹ️ No rows inserted[/yellow]")
            return

        inserted_total = 0
        request_count = 0
        last_public_call_ts = 0.0  # enforce ≤1 public req/sec for OHLC sync
        current_since = start_ts
        stall_count = 0

        # Avoid nested Rich Live/Progress contexts to prevent runtime errors.
        # Rely on the entrypoint's call_with_retries progress rendering instead.
        while True:
            prev_since = current_since

            # Removed previous pre-check that skipped API calls based on global
            # MAX(time). It caused missed backfills when DB had only later data
            # beyond the requested window. Always fetch from current_since and
            # rely on PK upsert for deduplication.

            # Try multiple Kraken pair key variants for robustness
            candidates = candidate_pair_keys(request_pair)
            selected_bars: List[Any] = []
            selected_pair: Optional[str] = None
            last_ts = 0

            for attempt_pair in candidates:
                # Stronger, local retry/backoff to respect Kraken public limits
                retries = 5
                delay = 2.0
                payload: Dict[str, Any] | None = None

                while True:
                    # Enforce Kraken public REST API limit: ≤1 request per second
                    now_monotonic = time.monotonic()
                    wait = max(0.0, 1.0 - (now_monotonic - last_public_call_ts))
                    if wait > 0.0:
                        time.sleep(wait)
                    try:
                        payload = api_client.get_ohlc_data(
                            pair=attempt_pair,
                            interval=interval_minutes,
                            since=current_since,
                        )
                        request_count += 1
                        last_public_call_ts = time.monotonic()
                        break
                    except Exception as exc:
                        request_count += 1
                        last_public_call_ts = time.monotonic()
                        msg = str(exc)
                        if (("Too many requests" in msg) or ("429" in msg)) and retries > 0:
                            console.print(
                                f"[yellow]⚠️ Rate limited on {attempt_pair}, "
                                f"retrying in {delay:.1f}s ({retries} left)…[/yellow]"
                            )
                            time.sleep(delay)
                            delay = min(delay * 2.0, 30.0)
                            retries -= 1
                            continue
                        # Non-retryable or retries exhausted: try next candidate
                        payload = None
                        break

                if not payload:
                    continue

                result = payload.get("result", {}) if payload else {}
                bars_iter, _ = resolve_ohlc_payload(attempt_pair, result)
                last_ts_raw = result.get("last")
                try:
                    last_ts = int(last_ts_raw) if last_ts_raw is not None else 0
                except (TypeError, ValueError):
                    last_ts = 0

                selected_bars = list(bars_iter or [])
                if selected_bars:
                    selected_pair = attempt_pair
                    break

            # Per-request throttle enforced above (1 req/sec); no extra cycle delay.

            # Restrict fetched rows to the requested window to avoid false
            # "already in DB" detections caused by out-of-window candles.
            step = max(1, interval_minutes * 60)
            selected_bars = [
                b for b in selected_bars
                if int(b[0]) >= current_since and int(b[0]) <= end_ts
            ]
            if not selected_bars:
                # Debug: explain absence of bars for current window/candidates
                if logger.isEnabledFor(logging.DEBUG):
                    console.print(
                        f"[dim]No bars fetched for {request_pair}; "
                        f"since={current_since}, last={last_ts} "
                        f"(candidates tried: {', '.join(candidates)})[/dim]"
                    )
                    logger.debug(
                        "No bars fetched for %s; since=%d last=%d; candidates=%s",
                        request_pair,
                        current_since,
                        last_ts,
                        ",".join(candidates),
                    )

                if last_ts == 0:
                    console.print("[yellow]ℹ️ No more data available[/yellow]")
                    break
                # Step forward to avoid stalling when no bars are returned
                step = max(1, interval_minutes * 60)
                current_since = current_since + step
                continue

            # Deduplicate against DB before insert: skip only if all fetched bars
            # already exist. Do NOT filter by global MAX(time) because DB may
            # contain later candles while earlier ones are missing.
            try:
                existing_count = _count_existing_bars(
                    conn,
                    request_pair,
                    interval_minutes,
                    [int(b[0]) for b in selected_bars],
                )
            except Exception as exc:
                existing_count = 0
                logger.debug("Existing count check failed: %s", exc)

            if existing_count >= len(selected_bars):
                if logger.isEnabledFor(logging.DEBUG):
                    console.print(
                        f"[dim]All fetched bars already in DB; "
                        f"skipping insert (count={existing_count})[/dim]"
                    )
                    logger.debug(
                        "All fetched bars already in DB for %s at since=%d (count=%d)",
                        request_pair,
                        current_since,
                        existing_count,
                    )
                # Advance by one interval to avoid repeated duplicates
                current_since = prev_since + max(1, interval_minutes * 60)
                if current_since >= end_ts:
                    break
                continue

            try:
                # Store under normalized pair key for consistency
                inserted = _insert_bars(
                    conn, request_pair, interval_minutes, selected_bars
                )
            except sqlite3.Error as exc:
                console.print(f"[red]❌ DB insert failed: {exc}[/red]")
                break

            inserted_total += inserted

            # Determine next window advancement
            if last_ts == 0:
                console.print("[yellow]ℹ️ No 'last' marker returned; stopping[/yellow]")
                break

            if last_ts <= current_since:
                # Advance by one candle interval to avoid stalls on duplicate/older data
                current_since = prev_since + max(1, interval_minutes * 60)
            else:
                current_since = last_ts

            # Debug progress: per-batch insert details
            if logger.isEnabledFor(logging.DEBUG):
                console.print(
                    f"[dim]Inserted {inserted} bars for "
                    f"{selected_pair or request_pair}; window "
                    f"{prev_since} → {current_since} (last={last_ts})[/dim]"
                )
                logger.debug(
                    "Inserted %d bars for %s; window %d → %d; last=%d",
                    inserted,
                    (selected_pair or request_pair),
                    prev_since,
                    current_since,
                    last_ts,
                )

                # If no bars were inserted but we did fetch bars,
                # explain likely cause (duplicates already present in DB)
                if inserted == 0 and selected_bars:
                    try:
                        existing_count = _count_existing_bars(
                            conn,
                            request_pair,
                            interval_minutes,
                            [int(b[0]) for b in selected_bars],
                        )
                    except Exception as exc:
                        existing_count = 0
                        logger.debug("Existing count check failed: %s", exc)

                    new_keys = max(0, len(selected_bars) - existing_count)
                    console.print(
                        f"[dim]Fetched {len(selected_bars)} bars; "
                        f"inserted=0 (duplicates in DB={existing_count}, new={new_keys}).[/dim]"
                    )
                    logger.debug(
                        "Fetched %d bars; inserted=0; duplicates=%d, new=%d for %s "
                        "between %d and %d",
                        len(selected_bars),
                        existing_count,
                        new_keys,
                        (selected_pair or request_pair),
                        prev_since,
                        current_since,
                    )

            # Detect repeated duplicate/old data stalls to avoid rate limits
            if inserted == 0 and last_ts <= prev_since:
                stall_count += 1
            else:
                stall_count = 0
            if stall_count >= 3:
                console.print(
                    "[yellow]ℹ️ Detected repeated duplicate/old data; "
                    "stopping to avoid rate limits[/yellow]"
                )
                logger.debug(
                    "Stopping after %d consecutive stalls (last_ts=%d, prev_since=%d)",
                    stall_count,
                    last_ts,
                    prev_since,
                )
                break

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
    @data.command(name="ohlc-from-trades")
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
        "--file",
        "-f",
        "file_path",
        type=click.Path(
            exists=True, dir_okay=False, readable=True, path_type=Path
        ),
        required=True,
        help="Path to trades CSV file (timestamp,price,volume).",
    )
    @click.option(
        "--since",
        type=str,
        default=None,
        help=(
            "Optional start time (epoch seconds or ISO "
            "'YYYY-MM-DD' or 'YYYY-MM-DDT%H:%M:%S')."
        ),
    )
    @click.option(
        "--until",
        type=str,
        default=None,
        help=(
            "Optional end time (epoch seconds or ISO "
            "'YYYY-MM-DD' or 'YYYY-MM-DDT%H:%M:%S')."
        ),
    )
    @click.option(
        "--dry-run",
        is_flag=True,
        help="Parse and aggregate CSV but do not write to the database.",
    )
    @click.pass_context
    def ohlc_from_trades(  # type: ignore[unused-ignore]
        ctx: click.Context,
        pair: str,
        timeframe: str,
        file_path: Path,
        since: Optional[str],
        until: Optional[str],
        dry_run: bool,
    ) -> None:
        """Import OHLC candles into SQLite from a trades CSV.

        The CSV must contain trade-level rows:
            timestamp_unix,price,volume

        Examples:
            # Import 1-minute candles for ETHUSD from trades.csv
            python kraken_cli.py data ohlc-from-trades -p ETHUSD -t 1m -f trades.csv

            # Import 5-minute candles for a specific window
            python kraken_cli.py data ohlc-from-trades -p ETHUSD -t 5m -f trades.csv \\
                --since 2015-08-07 --until 2015-08-10
        """
        interval_minutes = _parse_timeframe_label(timeframe)
        request_pair = pair.upper()

        start_ts = _parse_time_input(since)
        end_ts = _parse_time_input(until)

        if start_ts is not None and end_ts is not None and end_ts < start_ts:
            raise click.BadParameter(
                f"Invalid window: until ({end_ts}) is earlier than since ({start_ts})."
            )

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

        window_desc = f"{start_ts or '-∞'} → {end_ts or '+∞'}"
        console.print(
            Panel.fit(
                f"Pair: [cyan]{request_pair}[/cyan]\n"
                f"Timeframe: [cyan]{timeframe}[/cyan] "
                f"([green]{interval_minutes} min[/green])\n"
                f"Window: [cyan]{window_desc}[/cyan]\n"
                f"Source CSV: [magenta]{file_path}[/magenta]\n"
                f"DB: [magenta]{DB_PATH_DEFAULT}[/magenta]\n"
                f"Dry-run: [yellow]{'yes' if dry_run else 'no'}[/yellow]",
                title="OHLC Import from Trades",
                border_style="blue",
            )
        )

        inserted_total = 0
        generated_total = 0

        try:
            batch: List[List[Any]] = []
            batch_size = 500

            for bar in _iter_bars_from_trades_csv(
                file_path=file_path,
                interval_minutes=interval_minutes,
                since_ts=start_ts,
                until_ts=end_ts,
            ):
                generated_total += 1
                batch.append(bar)

                if not dry_run and len(batch) >= batch_size:
                    try:
                        inserted_total += _insert_bars(
                            conn, request_pair, interval_minutes, batch
                        )
                    except sqlite3.Error as exc:
                        console.print(f"[red]❌ DB insert failed: {exc}[/red]")
                        conn.close()
                        return
                    finally:
                        batch.clear()

            # Flush any remaining bars
            if batch and not dry_run:
                try:
                    inserted_total += _insert_bars(
                        conn, request_pair, interval_minutes, batch
                    )
                except sqlite3.Error as exc:
                    console.print(f"[red]❌ DB insert failed: {exc}[/red]")
                    conn.close()
                    return
        except OSError as exc:
            console.print(f"[red]❌ File read failed: {exc}[/red]")
            conn.close()
            return
        finally:
            conn.close()

        table = Table(title="OHLC Import from Trades Summary")
        table.add_column("Metric", style="cyan")
        table.add_column("Value", style="green")
        table.add_row("Pair", request_pair)
        table.add_row("Timeframe", f"{timeframe} ({interval_minutes}m)")
        table.add_row("Generated Candles", str(generated_total))
        if dry_run:
            table.add_row("Inserted Bars", "0 (dry-run)")
        else:
            table.add_row("Inserted Bars", str(inserted_total))
        table.add_row("DB Path", str(DB_PATH_DEFAULT))
        console.print(table)

        if generated_total == 0:
            console.print(
                "[yellow]ℹ️ No candles generated from the provided trades CSV[/yellow]"
            )
        elif dry_run:
            console.print(
                "[green]✅ Dry-run completed (no changes written to database)[/green]"
            )
        elif inserted_total > 0:
            console.print("[green]✅ OHLC import completed[/green]")
        else:
            console.print(
                "[yellow]ℹ️ Candles were generated but all already existed in DB[/yellow]"
            )
    @data.command(name="ohlc-from-trades")
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
        "--file",
        "-f",
        "file_path",
        type=click.Path(exists=True, dir_okay=False, readable=True, path_type=Path),
        required=True,
        help="Path to trades CSV file (timestamp,price,volume).",
    )
    @click.option(
        "--since",
        type=str,
        default=None,
        help="Optional start time (epoch seconds or ISO 'YYYY-MM-DD' or 'YYYY-MM-DDT%H:%M:%S').",
    )
    @click.option(
        "--until",
        type=str,
        default=None,
        help="Optional end time (epoch seconds or ISO 'YYYY-MM-DD' or 'YYYY-MM-DDT%H:%M:%S').",
    )
    @click.option(
        "--dry-run",
        is_flag=True,
        help="Parse and aggregate CSV but do not write to the database.",
    )
    @click.pass_context
    def ohlc_from_trades(  # type: ignore[unused-ignore]
        ctx: click.Context,
        pair: str,
        timeframe: str,
        file_path: Path,
        since: Optional[str],
        until: Optional[str],
        dry_run: bool,
    ) -> None:
        """Import OHLC candles into SQLite from a trades CSV.

        The CSV must contain trade-level rows:
            timestamp_unix,price,volume

        Examples:
            # Import 1-minute candles for ETHUSD from trades.csv
            python kraken_cli.py data ohlc-from-trades -p ETHUSD -t 1m -f trades.csv

            # Import 5-minute candles for a specific window
            python kraken_cli.py data ohlc-from-trades -p ETHUSD -t 5m -f trades.csv \\
                --since 2015-08-07 --until 2015-08-10
        """
        interval_minutes = _parse_timeframe_label(timeframe)
        request_pair = pair.upper()

        start_ts = _parse_time_input(since)
        end_ts = _parse_time_input(until)

        if start_ts is not None and end_ts is not None and end_ts < start_ts:
            raise click.BadParameter(
                f"Invalid window: until ({end_ts}) is earlier than since ({start_ts})."
            )

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

        window_desc = f"{start_ts or '-∞'} → {end_ts or '+∞'}"
        console.print(
            Panel.fit(
                f"Pair: [cyan]{request_pair}[/cyan]\n"
                f"Timeframe: [cyan]{timeframe}[/cyan] "
                f"([green]{interval_minutes} min[/green])\n"
                f"Window: [cyan]{window_desc}[/cyan]\n"
                f"Source CSV: [magenta]{file_path}[/magenta]\n"
                f"DB: [magenta]{DB_PATH_DEFAULT}[/magenta]\n"
                f"Dry-run: [yellow]{'yes' if dry_run else 'no'}[/yellow]",
                title="OHLC Import from Trades",
                border_style="blue",
            )
        )

        inserted_total = 0
        generated_total = 0

        try:
            batch: List[List[Any]] = []
            batch_size = 500

            for bar in _iter_bars_from_trades_csv(
                file_path=file_path,
                interval_minutes=interval_minutes,
                since_ts=start_ts,
                until_ts=end_ts,
            ):
                generated_total += 1
                batch.append(bar)
                if not dry_run and len(batch) >= batch_size:
                    try:
                        inserted_total += _insert_bars(
                            conn, request_pair, interval_minutes, batch
                        )
                    except sqlite3.Error as exc:
                        console.print(f"[red]❌ DB insert failed: {exc}[/red]")
                        conn.close()
                        return
                    finally:
                        batch.clear()

            if batch and not dry_run:
                try:
                    inserted_total += _insert_bars(
                        conn, request_pair, interval_minutes, batch
                    )
                except sqlite3.Error as exc:
                    console.print(f"[red]❌ DB insert failed: {exc}[/red]")
                    conn.close()
                    return
        except OSError as exc:
            console.print(f"[red]❌ File read failed: {exc}[/red]")
            conn.close()
            return
        finally:
            conn.close()

        table = Table(title="OHLC Import from Trades Summary")
        table.add_column("Metric", style="cyan")
        table.add_column("Value", style="green")
        table.add_row("Pair", request_pair)
        table.add_row("Timeframe", f"{timeframe} ({interval_minutes}m)")
        table.add_row("Generated Candles", str(generated_total))
        if dry_run:
            table.add_row("Inserted Bars", "0 (dry-run)")
        else:
            table.add_row("Inserted Bars", str(inserted_total))
        table.add_row("DB Path", str(DB_PATH_DEFAULT))
        console.print(table)

        if generated_total == 0:
            console.print(
                "[yellow]ℹ️ No candles generated from the provided trades CSV[/yellow]"
            )
        elif dry_run:
            console.print(
                "[green]✅ Dry-run completed (no changes written to database)[/green]"
            )
        elif inserted_total > 0:
            console.print("[green]✅ OHLC import completed[/green]")
        else:
            console.print(
                "[yellow]ℹ️ Candles were generated but all already existed in DB[/yellow]"
            )
    @data.command(name="ohlc-from-trades")
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
        "--file",
        "-f",
        "file_path",
        type=click.Path(
            exists=True, dir_okay=False, readable=True, path_type=Path
        ),
        required=True,
        help="Path to trades CSV file (timestamp,price,volume).",
    )
    @click.option(
        "--since",
        type=str,
        default=None,
        help=(
            "Optional start time (epoch seconds or ISO "
            "'YYYY-MM-DD' or 'YYYY-MM-DDT%H:%M:%S')."
        ),
    )
    @click.option(
        "--until",
        type=str,
        default=None,
        help=(
            "Optional end time (epoch seconds or ISO "
            "'YYYY-MM-DD' or 'YYYY-MM-DDT%H:%M:%S')."
        ),
    )
    @click.option(
        "--dry-run",
        is_flag=True,
        help="Parse and aggregate CSV but do not write to the database.",
    )
    @click.pass_context
    def ohlc_from_trades(  # type: ignore[unused-ignore]
        ctx: click.Context,
        pair: str,
        timeframe: str,
        file_path: Path,
        since: Optional[str],
        until: Optional[str],
        dry_run: bool,
    ) -> None:
        """Import OHLC candles into SQLite from a trades CSV.

        The CSV must contain trade-level rows:
            timestamp_unix,price,volume

        Examples:
            # Import 1-minute candles for ETHUSD from trades.csv
            python kraken_cli.py data ohlc-from-trades -p ETHUSD -t 1m -f trades.csv

            # Import 5-minute candles for a specific window
            python kraken_cli.py data ohlc-from-trades -p ETHUSD -t 5m -f trades.csv \\
                --since 2015-08-07 --until 2015-08-10
        """
        interval_minutes = _parse_timeframe_label(timeframe)
        request_pair = pair.upper()

        start_ts = _parse_time_input(since)
        end_ts = _parse_time_input(until)

        if start_ts is not None and end_ts is not None and end_ts < start_ts:
            raise click.BadParameter(
                f"Invalid window: until ({end_ts}) is earlier than since ({start_ts})."
            )

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

        window_desc = f"{start_ts or '-∞'} → {end_ts or '+∞'}"
        console.print(
            Panel.fit(
                f"Pair: [cyan]{request_pair}[/cyan]\n"
                f"Timeframe: [cyan]{timeframe}[/cyan] "
                f"([green]{interval_minutes} min[/green])\n"
                f"Window: [cyan]{window_desc}[/cyan]\n"
                f"Source CSV: [magenta]{file_path}[/magenta]\n"
                f"DB: [magenta]{DB_PATH_DEFAULT}[/magenta]\n"
                f"Dry-run: [yellow]{'yes' if dry_run else 'no'}[/yellow]",
                title="OHLC Import from Trades",
                border_style="blue"
            )
        )

        inserted_total = 0
        generated_total = 0

        try:
            batch: List[List[Any]] = []
            batch_size = 500

            for bar in _iter_bars_from_trades_csv(
                file_path=file_path,
                interval_minutes=interval_minutes,
                since_ts=start_ts,
                until_ts=end_ts,
            ):
                generated_total += 1
                batch.append(bar)

                if not dry_run and len(batch) >= batch_size:
                    try:
                        inserted_total += _insert_bars(
                            conn, request_pair, interval_minutes, batch
                        )
                    except sqlite3.Error as exc:
                        console.print(f"[red]❌ DB insert failed: {exc}[/red]")
                        conn.close()
                        return
                    finally:
                        batch.clear()

            # Flush any remaining bars
            if batch and not dry_run:
                try:
                    inserted_total += _insert_bars(
                        conn, request_pair, interval_minutes, batch
                    )
                except sqlite3.Error as exc:
                    console.print(f"[red]❌ DB insert failed: {exc}[/red]")
                    conn.close()
                    return
        except OSError as exc:
            console.print(f"[red]❌ File read failed: {exc}[/red]")
            conn.close()
            return
        finally:
            conn.close()

        table = Table(title="OHLC Import from Trades Summary")
        table.add_column("Metric", style="cyan")
        table.add_column("Value", style="green")
        table.add_row("Pair", request_pair)
        table.add_row("Timeframe", f"{timeframe} ({interval_minutes}m)")
        table.add_row("Generated Candles", str(generated_total))
        if dry_run:
            table.add_row("Inserted Bars", "0 (dry-run)")
        else:
            table.add_row("Inserted Bars", str(inserted_total))
        table.add_row("DB Path", str(DB_PATH_DEFAULT))
        console.print(table)

        if generated_total == 0:
            console.print(
                "[yellow]ℹ️ No candles generated from the provided trades CSV[/yellow]"
            )
        elif dry_run:
            console.print(
                "[green]✅ Dry-run completed (no changes written to database)[/green]"
            )
        elif inserted_total > 0:
            console.print("[green]✅ OHLC import completed[/green]")
        else:
            console.print(
                "[yellow]ℹ️ Candles were generated but all already existed in DB[/yellow]"
            )
    @data.command(name="ohlc-from-trades")
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
        "--file",
        "-f",
        "file_path",
        type=click.Path(
            exists=True, dir_okay=False, readable=True, path_type=Path
        ),
        required=True,
        help="Path to trades CSV file (timestamp,price,volume).",
    )
    @click.option(
        "--since",
        type=str,
        default=None,
        help=(
            "Optional start time (epoch seconds or ISO "
            "'YYYY-MM-DD' or 'YYYY-MM-DDT%H:%M:%S')."
        ),
    )
    @click.option(
        "--until",
        type=str,
        default=None,
        help=(
            "Optional end time (epoch seconds or ISO "
            "'YYYY-MM-DD' or 'YYYY-MM-DDT%H:%M:%S')."
        ),
    )
    @click.option(
        "--dry-run",
        is_flag=True,
        help="Parse and aggregate CSV but do not write to the database.",
    )
    @click.pass_context
    def ohlc_from_trades(  # type: ignore[unused-ignore]
        ctx: click.Context,
        pair: str,
        timeframe: str,
        file_path: Path,
        since: Optional[str],
        until: Optional[str],
        dry_run: bool,
    ) -> None:
        """Import OHLC candles into SQLite from a trades CSV.

        The CSV must contain trade-level rows:
            timestamp_unix,price,volume

        Examples:
            # Import 1-minute candles for ETHUSD from trades.csv
            python kraken_cli.py data ohlc-from-trades -p ETHUSD -t 1m -f trades.csv

            # Import 5-minute candles for a specific window
            python kraken_cli.py data ohlc-from-trades -p ETHUSD -t 5m -f trades.csv \\
                --since 2015-08-07 --until 2015-08-10
        """
        interval_minutes = _parse_timeframe_label(timeframe)
        request_pair = pair.upper()

        start_ts = _parse_time_input(since)
        end_ts = _parse_time_input(until)

        if start_ts is not None and end_ts is not None and end_ts < start_ts:
            raise click.BadParameter(
                f"Invalid window: until ({end_ts}) is earlier than since ({start_ts})."
            )

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

        window_desc = f"{start_ts or '-∞'} → {end_ts or '+∞'}"
        console.print(
            Panel.fit(
                f"Pair: [cyan]{request_pair}[/cyan]\n"
                f"Timeframe: [cyan]{timeframe}[/cyan] "
                f"([green]{interval_minutes} min[/green])\n"
                f"Window: [cyan]{window_desc}[/cyan]\n"
                f"Source CSV: [magenta]{file_path}[/magenta]\n"
                f"DB: [magenta]{DB_PATH_DEFAULT}[/magenta]\n"
                f"Dry-run: [yellow]{'yes' if dry_run else 'no'}[/yellow]",
                title="OHLC Import from Trades",
                border_style="blue",
            )
        )

        inserted_total = 0
        generated_total = 0

        try:
            batch: List[List[Any]] = []
            batch_size = 500

            for bar in _iter_bars_from_trades_csv(
                file_path=file_path,
                interval_minutes=interval_minutes,
                since_ts=start_ts,
                until_ts=end_ts,
            ):
                generated_total += 1
                batch.append(bar)

                if not dry_run and len(batch) >= batch_size:
                    try:
                        inserted_total += _insert_bars(
                            conn, request_pair, interval_minutes, batch
                        )
                    except sqlite3.Error as exc:
                        console.print(f"[red]❌ DB insert failed: {exc}[/red]")
                        conn.close()
                        return
                    finally:
                        batch.clear()

            # Flush any remaining bars
            if batch and not dry_run:
                try:
                    inserted_total += _insert_bars(
                        conn, request_pair, interval_minutes, batch
                    )
                except sqlite3.Error as exc:
                    console.print(f"[red]❌ DB insert failed: {exc}[/red]")
                    conn.close()
                    return
        except OSError as exc:
            console.print(f"[red]❌ File read failed: {exc}[/red]")
            conn.close()
            return
        finally:
            conn.close()

        table = Table(title="OHLC Import from Trades Summary")
        table.add_column("Metric", style="cyan")
        table.add_column("Value", style="green")
        table.add_row("Pair", request_pair)
        table.add_row("Timeframe", f"{timeframe} ({interval_minutes}m)")
        table.add_row("Generated Candles", str(generated_total))
        if dry_run:
            table.add_row("Inserted Bars", "0 (dry-run)")
        else:
            table.add_row("Inserted Bars", str(inserted_total))
        table.add_row("DB Path", str(DB_PATH_DEFAULT))
        console.print(table)

        if generated_total == 0:
            console.print(
                "[yellow]ℹ️ No candles generated from the provided trades CSV[/yellow]"
            )
        elif dry_run:
            console.print(
                "[green]✅ Dry-run completed (no changes written to database)[/green]"
            )
        elif inserted_total > 0:
            console.print("[green]✅ OHLC import completed[/green]")
        else:
            console.print(
                "[yellow]ℹ️ Candles were generated but all already existed in DB[/yellow]"
            )
    @data.command(name="ohlc-report")
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
        "--since",
        type=str,
        default=None,
        help=(
            "Start time (epoch seconds or ISO "
            "'YYYY-MM-DD' or 'YYYY-MM-DDT%H:%M:%S')."
        ),
    )
    @click.option(
        "--until",
        type=str,
        default=None,
        help=(
            "End time (epoch seconds or ISO "
            "'YYYY-MM-DD' or 'YYYY-MM-DDT%H:%M:%S')."
        ),
    )
    @click.option(
        "--output",
        type=click.Choice(["table", "json"], case_sensitive=False),
        default="table",
        show_default=True,
        help="Output format for coverage report.",
    )
    @click.pass_context
    def ohlc_report(  # type: ignore[unused-ignore]
        ctx: click.Context,
        pair: str,
        timeframe: str,
        since: Optional[str],
        until: Optional[str],
        output: str,
    ) -> None:
        """Report local OHLC coverage and gaps for a time window.
        
        This command reads the local SQLite `ohlc_bars` store and computes
        how complete your OHLC history is for the requested pair/timeframe,
        along with contiguous missing ranges (“gaps”). It does not contact
        Kraken APIs.
        
        Examples:
            # Coverage report (last 365 days by default)
            python kraken_cli.py data ohlc-report -p ETHUSD -t 1h
            
            # Explicit window with human-readable tables
            python kraken_cli.py data ohlc-report -p ETHUSD -t 15m \\
                --since 2025-01-01 --until 2025-03-01
            
            # JSON output for scripting
            python kraken_cli.py data ohlc-report -p ETHUSD -t 1h \\
                --since 2025-01-01 --until 2025-03-01 --output json
        """
        interval_minutes = _parse_timeframe_label(timeframe)
        request_pair = pair.upper()
        
        now_sec = int(time.time())
        start_ts = _parse_time_input(since)
        end_ts = _parse_time_input(until)
        
        # Default window: last 365 days when no bounds provided
        DEFAULT_REPORT_DAYS = 365
        if start_ts is None and end_ts is None:
            end_ts = now_sec
            start_ts = max(0, end_ts - DEFAULT_REPORT_DAYS * 86400)
        elif start_ts is None and end_ts is not None:
            start_ts = max(0, end_ts - DEFAULT_REPORT_DAYS * 86400)
        elif start_ts is not None and end_ts is None:
            end_ts = now_sec
        
        assert start_ts is not None and end_ts is not None
        
        if end_ts < start_ts:
            raise click.BadParameter(
                f"Invalid window: until ({end_ts}) is earlier than since ({start_ts})."
            )
        
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
        
        # Header panel
        step_seconds = interval_minutes * 60
        window_desc = f"{start_ts} → {end_ts}"
        console.print(
            Panel.fit(
                f"Pair: [cyan]{request_pair}[/cyan]\n"
                f"Timeframe: [cyan]{timeframe}[/cyan] "
                f"([green]{interval_minutes} min[/green])\n"
                f"Window: [cyan]{window_desc}[/cyan]\n"
                f"DB: [magenta]{DB_PATH_DEFAULT}[/magenta]",
                title="OHLC Coverage Report",
                border_style="blue",
            )
        )
        
        # Compute gaps and coverage from local store only
        try:
            gaps, summary = find_ohlc_gaps(
                conn=conn,
                pair=request_pair,
                timeframe_minutes=interval_minutes,
                start_ts=start_ts,
                end_ts=end_ts,
            )
        except Exception as exc:
            conn.close()
            console.print(f"[red]❌ Coverage computation failed: {exc}[/red]")
            return
        
        if output.lower() == "json":
            payload: Dict[str, Any] = {
                "pair": request_pair,
                "timeframe": timeframe,
                "window": {"start": start_ts, "end": end_ts},
                "step_seconds": step_seconds,
                "coverage": {
                    "expected": int(summary.get("expected", 0.0)),
                    "present": int(summary.get("present", 0.0)),
                    "missing": int(summary.get("missing", 0.0)),
                    "ratio": float(summary.get("coverage_ratio", 0.0)),
                },
                "gaps": gaps,
            }
            console.print(json.dumps(payload, indent=2))
            conn.close()
            return
        
        # Human-readable tables
        coverage_table = Table(title="OHLC Coverage Summary")
        coverage_table.add_column("Metric", style="cyan")
        coverage_table.add_column("Value", style="green")
        coverage_table.add_row("Expected", str(int(summary.get("expected", 0.0))))
        coverage_table.add_row("Present", str(int(summary.get("present", 0.0))))
        coverage_table.add_row("Missing", str(int(summary.get("missing", 0.0))))
        coverage_table.add_row(
            "Coverage Ratio",
            f"{float(summary.get('coverage_ratio', 0.0)):.4f}",
        )
        console.print(coverage_table)
        
        gaps_table = Table(title="Detected Gaps", show_lines=False)
        gaps_table.add_column("Start (UTC)", style="cyan")
        gaps_table.add_column("End (UTC, excl.)", style="magenta")
        gaps_table.add_column("Missing Candles", justify="right", style="yellow")
        
        def _fmt_ts(ts: int) -> str:
            try:
                dt = datetime.fromtimestamp(ts, tz=timezone.utc)
                return dt.strftime("%Y-%m-%d %H:%M:%S")
            except Exception:
                return str(ts)
        
        if not gaps:
            console.print("[green]✅ No gaps detected in the selected window[/green]")
        else:
            for gap in gaps:
                start_val = int(gap.get("start_ts", 0))
                end_excl = int(gap.get("end_ts_exclusive", 0))
                count = int(gap.get("missing_count", 0))
                gaps_table.add_row(_fmt_ts(start_val), _fmt_ts(end_excl), str(count))
            console.print(gaps_table)
        
        conn.close()
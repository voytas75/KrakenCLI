"""Historical pattern analysis utilities for KrakenCLI.

This module defines data models and orchestration helpers used to
scan OHLC data for recurring patterns such as moving-average
crossovers, RSI extremes, Bollinger band touches, and MACD signal
crosses.

Updates:
    v0.9.15 - 2025-11-16 - Added candlestick hammer and shooting star
        detectors.
    v0.9.14 - 2025-11-16 - Added MACD signal cross detector.
    v0.9.13 - 2025-11-16 - Added snapshot YAML export helper.
    v0.9.12 - 2025-11-16 - Added snapshot payload helper and heatmap
        aggregation utilities.
    v0.9.11 - 2025-11-16 - Initial scaffolding for pattern scanner
        models and PatternScanner shell.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
import sqlite3

import pandas as pd
import yaml

from api.kraken_client import KrakenAPIClient
from indicators.technical_indicators import TechnicalIndicators
from utils.market_data import resolve_ohlc_payload


logger = logging.getLogger(__name__)


@dataclass(slots=True)
class PatternMatch:
    """Single historical occurrence of a trading pattern."""

    pair: str
    timeframe: int
    pattern_name: str
    direction: str
    triggered_at: float
    close_price: float
    move_pct: float
    window: int


@dataclass(slots=True)
class PatternStats:
    """Aggregate statistics computed from pattern matches."""

    pair: str
    timeframe: int
    pattern_name: str
    total_matches: int = 0
    average_move_pct: float = 0.0
    median_move_pct: float = 0.0
    max_move_pct: float = 0.0
    min_move_pct: float = 0.0


@dataclass(slots=True)
class PatternSnapshot:
    """Serializable snapshot suitable for backtest/strategy seeding."""

    pair: str
    timeframe: int
    pattern_name: str
    direction: str
    triggered_at: float
    expected_move_pct: float


@dataclass(slots=True)
class PatternCacheKey:
    """Key identifying a cached pattern scan result."""

    pair: str
    timeframe: int
    pattern_name: str
    lookback_days: int
    data_source: str
    db_label: Optional[str] = None


@dataclass(slots=True)
class PatternCacheEntry:
    """Cached pattern scan payload persisted on disk."""

    key: PatternCacheKey
    created_at: float
    ttl_seconds: float
    stats: PatternStats
    matches: List[PatternMatch] = field(default_factory=list)


@dataclass(slots=True)
class PatternHeatmap:
    """Aggregated pattern metrics grouped by time buckets."""

    pair: str
    timeframe: int
    pattern_name: str
    group_by: str
    buckets: Dict[str, PatternStats] = field(default_factory=dict)


class PatternScanner:
    """Coordinator for historical pattern analysis.

    PatternScanner orchestrates OHLC retrieval, indicator calculation,
    detector execution, and on-disk caching for recurring pattern
    detection such as moving-average crossovers, RSI extremes, and
    Bollinger band touches.
    """

    DEFAULT_CACHE_TTL_SECONDS: float = 3600.0
    DEFAULT_MOVE_WINDOW: int = 24

    def __init__(
        self,
        client: KrakenAPIClient,
        *,
        cache_dir: Optional[Path] = None,
        indicators: Optional[TechnicalIndicators] = None,
    ) -> None:
        """Create a new PatternScanner instance.

        Args:
            client: Kraken API client used for OHLC retrieval.
            cache_dir: Optional directory used for on-disk cache files.
            indicators: Optional indicator helper instance. When not
                provided, a new TechnicalIndicators helper is used.
        """

        self._client = client
        self._cache_dir = cache_dir or Path("logs") / "patterns"
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._indicators = indicators or TechnicalIndicators()
        self._detectors = {
            "ma_crossover": self._detect_ma_crossover,
            "rsi_extreme": self._detect_rsi_extreme,
            "bollinger_touch": self._detect_bollinger_touch,
            "macd_signal_cross": self._detect_macd_signal_cross,
            "candle_hammer": self._detect_candle_hammer,
            "candle_shooting_star": self._detect_candle_shooting_star,
            "single_candle_move": self._detect_single_candle_move,
        }

    def scan_pattern(
        self,
        pair: str,
        timeframe: int,
        lookback_days: int,
        pattern_name: str,
        *,
        force_refresh: bool = False,
        data_source: str = "api",
        db_path: Path | None = None,
        detector_params: Dict[str, Any] | None = None,
    ) -> tuple[PatternStats, List[PatternMatch], List[PatternSnapshot]]:
        """Scan OHLC data for the requested pattern.

        This method coordinates OHLC retrieval, detector execution, and
        caching. Results are persisted as JSON blobs keyed by
        ``PatternCacheKey`` and reused until the cache entry expires
        or ``force_refresh`` is set.

        Args:
            pair: Trading pair such as ``ETHUSD``.
            timeframe: Candle interval in minutes.
            lookback_days: Number of days to look back when fetching
                OHLC candles.
            pattern_name: Registered pattern identifier.
            force_refresh: When True, bypass any cached results.

        Returns:
            Tuple of PatternStats, list of PatternMatch, and list of
            PatternSnapshot objects.

        Raises:
            ValueError: If the pattern name is unknown or OHLC data
                cannot be resolved.
        """

        key = PatternCacheKey(
            pair=pair.upper(),
            timeframe=int(timeframe),
            pattern_name=pattern_name,
            lookback_days=int(lookback_days),
            data_source=str(data_source).lower(),
            db_label=(
                (db_path.name if db_path is not None else "default")
                if str(data_source).lower() == "local"
                else None
            ),
        )

        if not force_refresh:
            cached = self._load_cache_entry(key)
            if cached is not None:
                logger.debug(
                    "Using cached pattern scan for %s/%s (%s, lookback=%s)",
                    cached.key.pair,
                    cached.key.timeframe,
                    cached.key.pattern_name,
                    cached.key.lookback_days,
                )
                snapshots = self._build_snapshots(
                    cached.key.pair,
                    cached.key.timeframe,
                    cached.key.pattern_name,
                    cached.matches,
                )
                return cached.stats, cached.matches, snapshots

        detector = self._detectors.get(pattern_name)
        if detector is None:
            raise ValueError(f"Unknown pattern name: {pattern_name!r}")

        if str(data_source).lower() == "local":
            ohlc_frame = self._fetch_ohlc_frame_local(
                pair=pair,
                timeframe=timeframe,
                lookback_days=lookback_days,
                db_path=db_path,
            )
        else:
            ohlc_frame = self._fetch_ohlc_frame(
                pair=pair,
                timeframe=timeframe,
                lookback_days=lookback_days,
            )
        if ohlc_frame.empty:
            raise ValueError("No OHLC data available for pattern scan.")

        try:
            matches = detector(
                ohlc_frame,
                pair.upper(),
                int(timeframe),
                self.DEFAULT_MOVE_WINDOW,
                **(detector_params or {}),
            )
        except TypeError:
            # Detector does not accept extra parameters, call baseline signature
            matches = detector(
                ohlc_frame,
                pair.upper(),
                int(timeframe),
                self.DEFAULT_MOVE_WINDOW,
            )
        stats = self._compute_stats(
            pair.upper(),
            int(timeframe),
            pattern_name,
            matches,
        )

        entry = PatternCacheEntry(
            key=key,
            created_at=time.time(),
            ttl_seconds=self.DEFAULT_CACHE_TTL_SECONDS,
            stats=stats,
            matches=matches,
        )
        self._save_cache_entry(entry)

        snapshots = self._build_snapshots(
            pair.upper(),
            int(timeframe),
            pattern_name,
            matches,
        )
        return stats, matches, snapshots

    def _cache_file_path(self, key: PatternCacheKey) -> Path:
        """Return path to the cache file for the provided key."""
        safe_pair = key.pair.replace("/", "_")
        source_tag = f"_src{key.data_source}" if getattr(key, "data_source", None) else ""
        db_tag = f"_{key.db_label}" if getattr(key, "db_label", None) else ""
        filename = (
            f"{safe_pair}_tf{key.timeframe}_"
            f"{key.pattern_name}_lb{key.lookback_days}"
            f"{source_tag}{db_tag}.json"
        )
        return self._cache_dir / filename

    def _load_cache_entry(
        self,
        key: PatternCacheKey,
    ) -> Optional[PatternCacheEntry]:
        """Load a cache entry from disk when present and valid."""
        path = self._cache_file_path(key)
        if not path.is_file():
            return None

        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.error("Failed to read pattern cache %s: %s", path, exc)
            return None

        try:
            created_at = float(payload.get("created_at", 0.0))
            ttl_seconds = float(
                payload.get("ttl_seconds", self.DEFAULT_CACHE_TTL_SECONDS),
            )
        except (TypeError, ValueError):
            return None

        if created_at <= 0.0:
            return None
        if (time.time() - created_at) > ttl_seconds:
            return None

        stats_data = payload.get("stats") or {}
        try:
            stats = PatternStats(**stats_data)
        except TypeError as exc:
            logger.error("Invalid stats payload in %s: %s", path, exc)
            return None

        matches: List[PatternMatch] = []
        for item in payload.get("matches", []) or []:
            try:
                matches.append(PatternMatch(**item))
            except TypeError:
                continue

        return PatternCacheEntry(
            key=key,
            created_at=created_at,
            ttl_seconds=ttl_seconds,
            stats=stats,
            matches=matches,
        )

    def _save_cache_entry(self, entry: PatternCacheEntry) -> None:
        """Persist a cache entry to disk in a JSON file."""
        path = self._cache_file_path(entry.key)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            payload: Dict[str, Any] = {
                "key": asdict(entry.key),
                "created_at": entry.created_at,
                "ttl_seconds": entry.ttl_seconds,
                "stats": asdict(entry.stats),
                "matches": [asdict(match) for match in entry.matches],
            }
            tmp_path = path.with_suffix(".tmp")
            tmp_path.write_text(
                json.dumps(payload, indent=2, sort_keys=True),
                encoding="utf-8",
            )
            tmp_path.replace(path)
        except OSError as exc:  # pragma: no cover - defensive file guard
            logger.error("Failed to write pattern cache %s: %s", path, exc)

    def _fetch_ohlc_frame(
        self,
        *,
        pair: str,
        timeframe: int,
        lookback_days: int,
    ) -> pd.DataFrame:
        """Fetch and normalise OHLC data for the requested window."""
        now = int(time.time())
        since = now - int(lookback_days) * 86400
    
        response = self._client.get_ohlc_data(
            pair=pair,
            interval=int(timeframe),
            since=since,
        )
        result_payload = response.get("result") or {}
        ohlc_iterable, _resolved_key = resolve_ohlc_payload(pair, result_payload)
        if ohlc_iterable is None:
            logger.warning(
                "Failed to resolve OHLC payload for pair %s in result keys: %s",
                pair,
                list(result_payload.keys()),
            )
            return pd.DataFrame()
    
        rows: List[Dict[str, Any]] = []
        for raw in ohlc_iterable:
            if not raw or len(raw) < 8:
                continue
            try:
                rows.append(
                    {
                        "time": float(raw[0]),
                        "open": float(raw[1]),
                        "high": float(raw[2]),
                        "low": float(raw[3]),
                        "close": float(raw[4]),
                        "vwap": float(raw[5]),
                        "volume": float(raw[6]),
                        "count": int(raw[7]),
                    },
                )
            except (TypeError, ValueError):
                continue
    
        if not rows:
            return pd.DataFrame()
    
        frame = pd.DataFrame(rows)
        frame.sort_values("time", inplace=True)
        frame.reset_index(drop=True, inplace=True)
        return frame
    
    def _fetch_ohlc_frame_local(
        self,
        *,
        pair: str,
        timeframe: int,
        lookback_days: int,
        db_path: Path | None = None,
    ) -> pd.DataFrame:
        """Fetch OHLC data from local SQLite store (data/ohlc.db by default).
    
        Args:
            pair: Trading pair (e.g., 'ETHUSD').
            timeframe: Candle interval in minutes.
            lookback_days: Number of days to look back from now.
            db_path: Optional explicit database path.
    
        Returns:
            DataFrame with columns: time, open, high, low, close, vwap, volume, count.
            Empty DataFrame if unavailable.
        """
        try:
            database = db_path or (Path("data") / "ohlc.db")
            if not database.exists():
                logger.warning("Local OHLC database not found at %s", database)
                return pd.DataFrame()
    
            since = int(time.time()) - int(lookback_days) * 86400
            rows: list[dict[str, Any]] = []
    
            conn = sqlite3.connect(database.as_posix())
            try:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT time, open, high, low, close, vwap, volume, count
                    FROM ohlc_bars
                    WHERE pair=? AND timeframe_minutes=? AND time >= ?
                    ORDER BY time
                    """,
                    (pair.upper(), int(timeframe), int(since)),
                )
                for rec in cursor:
                    try:
                        rows.append(
                            {
                                "time": float(rec[0]),
                                "open": float(rec[1]),
                                "high": float(rec[2]),
                                "low": float(rec[3]),
                                "close": float(rec[4]),
                                "vwap": float(rec[5]) if rec[5] is not None else float("nan"),
                                "volume": float(rec[6]) if rec[6] is not None else float("nan"),
                                "count": int(rec[7]) if rec[7] is not None else 0,
                            }
                        )
                    except (TypeError, ValueError):
                        continue
            finally:
                try:
                    conn.close()
                except Exception:
                    pass
    
            if not rows:
                return pd.DataFrame()
    
            frame = pd.DataFrame(rows)
            frame.sort_values("time", inplace=True)
            frame.reset_index(drop=True, inplace=True)
            return frame
        except Exception as exc:  # defensive local IO/SQL guard
            logger.error("Failed to read local OHLC data: %s", exc)
            return pd.DataFrame()

    def _compute_stats(
        self,
        pair: str,
        timeframe: int,
        pattern_name: str,
        matches: List[PatternMatch],
    ) -> PatternStats:
        """Compute aggregate statistics for a set of matches."""
        if not matches:
            return PatternStats(
                pair=pair,
                timeframe=timeframe,
                pattern_name=pattern_name,
                total_matches=0,
            )

        moves = [match.move_pct for match in matches]
        moves_sorted = sorted(moves)
        total_matches = len(moves)
        average_move = float(sum(moves) / total_matches)
        if total_matches % 2 == 1:
            median_move = moves_sorted[total_matches // 2]
        else:
            mid_index = total_matches // 2
            median_move = (
                moves_sorted[mid_index - 1] + moves_sorted[mid_index]
            ) / 2.0

        return PatternStats(
            pair=pair,
            timeframe=timeframe,
            pattern_name=pattern_name,
            total_matches=total_matches,
            average_move_pct=average_move,
            median_move_pct=median_move,
            max_move_pct=max(moves),
            min_move_pct=min(moves),
        )

    def _build_snapshots(
        self,
        pair: str,
        timeframe: int,
        pattern_name: str,
        matches: List[PatternMatch],
    ) -> List[PatternSnapshot]:
        """Create PatternSnapshot instances from match records."""
        snapshots: List[PatternSnapshot] = []
        for match in matches:
            snapshots.append(
                PatternSnapshot(
                    pair=pair,
                    timeframe=timeframe,
                    pattern_name=pattern_name,
                    direction=match.direction,
                    triggered_at=match.triggered_at,
                    expected_move_pct=match.move_pct,
                ),
            )
        return snapshots

    @staticmethod
    def snapshots_to_payload(
        snapshots: List[PatternSnapshot],
    ) -> Dict[str, Any]:
        """Convert snapshots to a serialisable payload.

        The resulting dictionary is suitable for YAML export and can be
        written directly to a file. The schema is intentionally simple
        and focuses on pattern metadata rather than full strategy
        configuration. This keeps exports loosely coupled while still
        providing enough information for backtest seeding.

        Args:
            snapshots: List of PatternSnapshot instances.

        Returns:
            Mapping with a single ``pattern_snapshots`` key containing
            a list of snapshot dictionaries.
        """
        return {
            "pattern_snapshots": [
                asdict(snapshot) for snapshot in snapshots
            ],
        }

    def export_snapshots_to_yaml(
        self,
        snapshots: List[PatternSnapshot],
        *,
        output_dir: Path | None = None,
    ) -> Path:
        """Export pattern snapshots to a YAML file on disk.

        This helper converts the provided ``PatternSnapshot`` instances
        into a lightweight dictionary payload and writes it as a YAML
        document. The resulting file is intended for use as a seed for
        backtests or strategy configuration and intentionally focuses on
        pattern metadata rather than full trading rules.

        When ``output_dir`` is not provided, the file is written to the
        ``configs/backtests`` directory, which is created on demand. The
        filename incorporates the first snapshot's pair, a pattern
        label, the timeframe, and a Unix timestamp. If a file with the
        generated name already exists, a numeric suffix is appended to
        keep the export operation non-destructive.

        Args:
            snapshots: Snapshots to serialise and export.
            output_dir: Optional directory where the YAML file should be
                written. When omitted, ``configs/backtests`` is used.

        Returns:
            Path to the final YAML file on disk.

        Raises:
            ValueError: If ``snapshots`` is empty.
            OSError: If the underlying filesystem operations fail.
        """
        if not snapshots:
            raise ValueError("No snapshots provided for YAML export.")

        payload = self.snapshots_to_payload(snapshots)
        target_dir = output_dir or Path("configs") / "backtests"
        target_dir.mkdir(parents=True, exist_ok=True)

        first = snapshots[0]
        pair_label = (first.pair or "UNKNOWN").upper()

        pattern_names = {snapshot.pattern_name for snapshot in snapshots}
        if len(pattern_names) == 1:
            pattern_label = next(iter(pattern_names)) or "unknown"
        else:
            pattern_label = "mixed"

        timeframe_minutes = int(first.timeframe)
        if timeframe_minutes % 1440 == 0 and timeframe_minutes > 0:
            days = timeframe_minutes // 1440
            timeframe_label = f"{days}d"
        elif timeframe_minutes % 60 == 0 and timeframe_minutes >= 60:
            hours = timeframe_minutes // 60
            timeframe_label = f"{hours}h"
        else:
            timeframe_label = f"{timeframe_minutes}m"

        timestamp = int(time.time())

        def _sanitize(component: str) -> str:
            return "".join(
                ch
                if ch.isalnum() or ch in ("-", "_", ".")
                else "_"
                for ch in component
            )

        safe_pair = _sanitize(pair_label)
        safe_pattern = _sanitize(pattern_label)
        safe_timeframe = _sanitize(timeframe_label)

        base_name = (
            f"pattern_snapshots_{safe_pair}_{safe_pattern}_"
            f"{safe_timeframe}_{timestamp}"
        )

        candidate = target_dir / f"{base_name}.yaml"
        suffix_counter = 1
        while candidate.exists():
            candidate = target_dir / f"{base_name}_{suffix_counter}.yaml"
            suffix_counter += 1

        tmp_path = candidate.with_suffix(candidate.suffix + ".tmp")

        try:
            with tmp_path.open("w", encoding="utf-8") as handle:
                yaml.safe_dump(
                    payload,
                    handle,
                    default_flow_style=False,
                    allow_unicode=True,
                )
                handle.flush()
            tmp_path.replace(candidate)
        except OSError as exc:
            logger.error(
                "Failed to write pattern snapshots YAML %s: %s",
                candidate,
                exc,
            )
            raise

        return candidate

    def build_heatmap(
        self,
        matches: List[PatternMatch],
        pair: str,
        timeframe: int,
        pattern_name: str,
        group_by: str = "weekday",
    ) -> PatternHeatmap:
        """Aggregate matches into a PatternHeatmap structure.

        The grouping is performed on the match trigger timestamp using
        UTC semantics. Supported groupings:

        - ``weekday``: Buckets by weekday name (Mon, Tue, ...).
        - ``hour``: Buckets by hour of day in ``HH:00`` format.
        - ``weekday_hour``: Combined weekday and hour
          (for example ``Mon 13:00``).

        Args:
            matches: PatternMatch instances to aggregate.
            pair: Trading pair associated with the matches.
            timeframe: Candle interval in minutes.
            pattern_name: Registered pattern identifier.
            group_by: One of ``weekday``, ``hour``, or ``weekday_hour``.

        Returns:
            PatternHeatmap populated with PatternStats for each bucket.

        Raises:
            ValueError: If the group_by value is unsupported.
        """
        if not matches:
            return PatternHeatmap(
                pair=pair,
                timeframe=timeframe,
                pattern_name=pattern_name,
                group_by=group_by,
                buckets={},
            )

        buckets: Dict[str, List[PatternMatch]] = {}

        for match in matches:
            dt = datetime.fromtimestamp(match.triggered_at, tz=timezone.utc)

            if group_by == "weekday":
                bucket_key = dt.strftime("%a")
            elif group_by == "hour":
                bucket_key = f"{dt.hour:02d}:00"
            elif group_by == "weekday_hour":
                bucket_key = f"{dt.strftime('%a')} {dt.hour:02d}:00"
            else:
                raise ValueError(f"Unsupported group_by value: {group_by!r}")

            buckets.setdefault(bucket_key, []).append(match)

        stats_buckets: Dict[str, PatternStats] = {}
        for bucket_key, bucket_matches in buckets.items():
            stats_buckets[bucket_key] = self._compute_stats(
                pair=pair,
                timeframe=timeframe,
                pattern_name=pattern_name,
                matches=bucket_matches,
            )

        return PatternHeatmap(
            pair=pair,
            timeframe=timeframe,
            pattern_name=pattern_name,
            group_by=group_by,
            buckets=stats_buckets,
        )

    def _detect_ma_crossover(
        self,
        frame: pd.DataFrame,
        pair: str,
        timeframe: int,
        window: int,
    ) -> List[PatternMatch]:
        """Detect moving-average crossover events.

        The detector uses EMA(12) and EMA(26) on the close price to
        identify bullish (fast crossing above slow) and bearish (fast
        crossing below slow) crossovers.
        """
        close = frame["close"]
        ema_fast = self._indicators.ema(close, period=12)
        ema_slow = self._indicators.ema(close, period=26)

        matches: List[PatternMatch] = []
        for idx in range(1, len(frame)):
            fast_prev = ema_fast.iloc[idx - 1]
            slow_prev = ema_slow.iloc[idx - 1]
            fast_now = ema_fast.iloc[idx]
            slow_now = ema_slow.iloc[idx]

            if any(pd.isna(value) for value in (fast_prev, slow_prev, fast_now, slow_now)):
                continue

            direction: Optional[str] = None
            if fast_prev <= slow_prev and fast_now > slow_now:
                direction = "bullish"
            elif fast_prev >= slow_prev and fast_now < slow_now:
                direction = "bearish"

            if direction is None:
                continue

            future_index = idx + window
            if future_index >= len(frame):
                continue

            entry_price = float(close.iloc[idx])
            future_price = float(close.iloc[future_index])
            if entry_price <= 0.0:
                continue

            move_pct = (future_price / entry_price - 1.0) * 100.0
            matches.append(
                PatternMatch(
                    pair=pair,
                    timeframe=timeframe,
                    pattern_name="ma_crossover",
                    direction=direction,
                    triggered_at=float(frame["time"].iloc[idx]),
                    close_price=entry_price,
                    move_pct=move_pct,
                    window=window,
                ),
            )

        return matches

    def _detect_rsi_extreme(
        self,
        frame: pd.DataFrame,
        pair: str,
        timeframe: int,
        window: int,
    ) -> List[PatternMatch]:
        """Detect RSI extreme events (overbought/oversold)."""
        close = frame["close"]
        rsi_series = self._indicators.rsi(close, period=14)

        matches: List[PatternMatch] = []
        for idx in range(len(frame)):
            rsi_value = rsi_series.iloc[idx]
            if pd.isna(rsi_value):
                continue

            direction: Optional[str]
            if rsi_value >= 70.0:
                direction = "bearish"
            elif rsi_value <= 30.0:
                direction = "bullish"
            else:
                continue

            future_index = idx + window
            if future_index >= len(frame):
                continue

            entry_price = float(close.iloc[idx])
            future_price = float(close.iloc[future_index])
            if entry_price <= 0.0:
                continue

            move_pct = (future_price / entry_price - 1.0) * 100.0
            matches.append(
                PatternMatch(
                    pair=pair,
                    timeframe=timeframe,
                    pattern_name="rsi_extreme",
                    direction=direction,
                    triggered_at=float(frame["time"].iloc[idx]),
                    close_price=entry_price,
                    move_pct=move_pct,
                    window=window,
                ),
            )

        return matches

    def _detect_bollinger_touch(
        self,
        frame: pd.DataFrame,
        pair: str,
        timeframe: int,
        window: int,
    ) -> List[PatternMatch]:
        """Detect touches of Bollinger Band upper and lower bands."""
        close = frame["close"]
        bands = self._indicators.bollinger(close, period=20, stddev=2.0)

        upper = bands["upper"]
        lower = bands["lower"]

        matches: List[PatternMatch] = []
        for idx in range(len(frame)):
            price = close.iloc[idx]
            upper_val = upper.iloc[idx]
            lower_val = lower.iloc[idx]

            if any(pd.isna(value) for value in (price, upper_val, lower_val)):
                continue

            direction: Optional[str] = None
            if price >= upper_val:
                direction = "bearish"
            elif price <= lower_val:
                direction = "bullish"

            if direction is None:
                continue

            future_index = idx + window
            if future_index >= len(frame):
                continue

            entry_price = float(price)
            future_price = float(close.iloc[future_index])
            if entry_price <= 0.0:
                continue

            move_pct = (future_price / entry_price - 1.0) * 100.0
            matches.append(
                PatternMatch(
                    pair=pair,
                    timeframe=timeframe,
                    pattern_name="bollinger_touch",
                    direction=direction,
                    triggered_at=float(frame["time"].iloc[idx]),
                    close_price=entry_price,
                    move_pct=move_pct,
                    window=window,
                ),
            )

        return matches
    def _detect_macd_signal_cross(
        self,
        frame: pd.DataFrame,
        pair: str,
        timeframe: int,
        window: int,
    ) -> List[PatternMatch]:
        """Detect MACD line crossing the signal line (bullish/bearish).
        
        Bullish signal: MACD crosses above Signal.
        Bearish signal: MACD crosses below Signal.
        
        For each detected cross, compute the percentage move over the
        specified future window based on close prices.
        """
        close = frame["close"]
        macd_df = self._indicators.macd(close, fast=12, slow=26, signal=9)
        macd_line = macd_df["macd"]
        signal_line = macd_df["signal"]
    
        matches: List[PatternMatch] = []
        for idx in range(1, len(frame)):
            prev_macd = macd_line.iloc[idx - 1]
            prev_signal = signal_line.iloc[idx - 1]
            cur_macd = macd_line.iloc[idx]
            cur_signal = signal_line.iloc[idx]
    
            if any(
                pd.isna(v)
                for v in (prev_macd, prev_signal, cur_macd, cur_signal)
            ):
                continue
    
            direction: Optional[str] = None
            if prev_macd <= prev_signal and cur_macd > cur_signal:
                direction = "bullish"
            elif prev_macd >= prev_signal and cur_macd < cur_signal:
                direction = "bearish"
    
            if direction is None:
                continue
    
            future_index = idx + window
            if future_index >= len(frame):
                continue
    
            entry_price = float(close.iloc[idx])
            future_price = float(close.iloc[future_index])
            if entry_price <= 0.0:
                continue
    
            move_pct = (future_price / entry_price - 1.0) * 100.0
            matches.append(
                PatternMatch(
                    pair=pair,
                    timeframe=timeframe,
                    pattern_name="macd_signal_cross",
                    direction=direction,
                    triggered_at=float(frame["time"].iloc[idx]),
                    close_price=entry_price,
                    move_pct=move_pct,
                    window=window,
                ),
            )
    
        return matches

    def _detect_candle_hammer(
        self,
        frame: pd.DataFrame,
        pair: str,
        timeframe: int,
        window: int,
    ) -> List[PatternMatch]:
        """Detect Hammer candlestick pattern occurrences.
        
        The hammer is characterized by a small real body near the top of the
        range, a long lower shadow (≥2x the body), and a minimal upper shadow.
        It is interpreted as a potential bullish reversal. This detector
        focuses on shape heuristics without requiring an explicit trend filter.
        
        Args:
            frame: OHLC dataframe with columns: time, open, high, low, close.
            pair: Trading pair label (e.g., 'ETHUSD').
            timeframe: Candle interval in minutes.
            window: Future window used to compute subsequent move in percent.
        
        Returns:
            List of PatternMatch entries for detected hammer shapes.
        """
        matches: List[PatternMatch] = []
        open_s = frame["open"]
        close_s = frame["close"]
        high_s = frame["high"]
        low_s = frame["low"]
        
        for idx in range(len(frame)):
            o = open_s.iloc[idx]
            c = close_s.iloc[idx]
            h = high_s.iloc[idx]
            l = low_s.iloc[idx]
            
            if any(pd.isna(v) for v in (o, c, h, l)):
                continue
            
            body = abs(c - o)
            rng = h - l
            if rng <= 0.0 or body <= 0.0:
                continue
            
            lower_shadow = min(o, c) - l
            upper_shadow = h - max(o, c)
            
            is_hammer = (
                lower_shadow >= 2.0 * body
                and upper_shadow <= 0.3 * body
                and (body / rng) <= 0.4
                and (max(o, c) - l) / rng >= 0.6
            )
            if not is_hammer:
                continue
            
            future_index = idx + window
            if future_index >= len(frame):
                continue
            
            entry_price = float(close_s.iloc[idx])
            future_price = float(close_s.iloc[future_index])
            if entry_price <= 0.0:
                continue
            
            move_pct = (future_price / entry_price - 1.0) * 100.0
            matches.append(
                PatternMatch(
                    pair=pair,
                    timeframe=timeframe,
                    pattern_name="candle_hammer",
                    direction="bullish",
                    triggered_at=float(frame["time"].iloc[idx]),
                    close_price=entry_price,
                    move_pct=move_pct,
                    window=window,
                ),
            )
        
        return matches

    def _detect_candle_shooting_star(
        self,
        frame: pd.DataFrame,
        pair: str,
        timeframe: int,
        window: int,
    ) -> List[PatternMatch]:
        """Detect Shooting Star candlestick pattern occurrences.
        
        The shooting star is characterized by a small real body near the
        bottom of the range, a long upper shadow (≥2x the body), and minimal
        lower shadow. It is interpreted as a potential bearish reversal.
        
        Args:
            frame: OHLC dataframe with columns: time, open, high, low, close.
            pair: Trading pair label (e.g., 'ETHUSD').
            timeframe: Candle interval in minutes.
            window: Future window used to compute subsequent move in percent.
        
        Returns:
            List of PatternMatch entries for detected shooting star shapes.
        """
        matches: List[PatternMatch] = []
        open_s = frame["open"]
        close_s = frame["close"]
        high_s = frame["high"]
        low_s = frame["low"]
        
        for idx in range(len(frame)):
            o = open_s.iloc[idx]
            c = close_s.iloc[idx]
            h = high_s.iloc[idx]
            l = low_s.iloc[idx]
            
            if any(pd.isna(v) for v in (o, c, h, l)):
                continue
            
            body = abs(c - o)
            rng = h - l
            if rng <= 0.0 or body <= 0.0:
                continue
            
            upper_shadow = h - max(o, c)
            lower_shadow = min(o, c) - l
            
            is_shooting_star = (
                upper_shadow >= 2.0 * body
                and lower_shadow <= 0.3 * body
                and (body / rng) <= 0.4
                and (min(o, c) - l) / rng <= 0.4
            )
            if not is_shooting_star:
                continue
            
            future_index = idx + window
            if future_index >= len(frame):
                continue
            
            entry_price = float(close_s.iloc[idx])
            future_price = float(close_s.iloc[future_index])
            if entry_price <= 0.0:
                continue
            
            move_pct = (future_price / entry_price - 1.0) * 100.0
            matches.append(
                PatternMatch(
                    pair=pair,
                    timeframe=timeframe,
                    pattern_name="candle_shooting_star",
                    direction="bearish",
                    triggered_at=float(frame["time"].iloc[idx]),
                    close_price=entry_price,
                    move_pct=move_pct,
                    window=window,
                ),
            )
        
        return matches

    def _detect_single_candle_move(
        self,
        frame: pd.DataFrame,
        pair: str,
        timeframe: int,
        window: int,
        *,
        threshold_pct: float = 5.0,
        direction: Optional[str] = None,
    ) -> List[PatternMatch]:
        """Detect single-candle percent moves matching a user threshold.

        A match occurs when the percent change from open to close within a
        single candle meets or exceeds the provided threshold. If a direction
        is specified:
            - 'bullish': (close - open) / open >= threshold_pct
            - 'bearish': (close - open) / open <= -threshold_pct
        When no direction is specified, both sides are considered.

        The move_pct stored in PatternMatch is the subsequent move over the
        provided future window (consistent with other detectors).

        Args:
            frame: OHLC dataframe with columns: time, open, high, low, close.
            pair: Trading pair label (e.g., 'ETHUSD').
            timeframe: Candle interval in minutes.
            window: Future window used to compute subsequent move in percent.
            threshold_pct: Required single-candle percent change (0.1..50.0).
            direction: Optional side filter ('bullish' or 'bearish').

        Returns:
            List of PatternMatch entries for detected single-candle moves.
        """
        open_s = frame["open"]
        close_s = frame["close"]

        # Normalise threshold bounds defensively
        try:
            th = float(threshold_pct)
        except (TypeError, ValueError):
            th = 5.0
        th = max(0.1, min(th, 50.0))

        matches: List[PatternMatch] = []
        for idx in range(len(frame)):
            o = open_s.iloc[idx]
            c = close_s.iloc[idx]
            if any(pd.isna(v) for v in (o, c)):
                continue
            if o <= 0.0:
                continue

            candle_move_pct = (c / o - 1.0) * 100.0

            # Apply direction filtering
            if direction == "bullish":
                if candle_move_pct < th:
                    continue
                dir_label = "bullish"
            elif direction == "bearish":
                if candle_move_pct > -th:
                    continue
                dir_label = "bearish"
            else:
                if abs(candle_move_pct) < th:
                    continue
                dir_label = "bullish" if candle_move_pct >= 0.0 else "bearish"

            future_index = idx + window
            if future_index >= len(frame):
                continue

            entry_price = float(close_s.iloc[idx])
            future_price = float(close_s.iloc[future_index])
            if entry_price <= 0.0:
                continue

            move_pct = (future_price / entry_price - 1.0) * 100.0
            matches.append(
                PatternMatch(
                    pair=pair,
                    timeframe=timeframe,
                    pattern_name="single_candle_move",
                    direction=dir_label,
                    triggered_at=float(frame["time"].iloc[idx]),
                    close_price=entry_price,
                    move_pct=move_pct,
                    window=window,
                ),
            )

        return matches
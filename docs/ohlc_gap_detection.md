# OHLC Gap Detection Model

Updates:
- v0.10.1 - 2025-11-17 - Initial gap detection concept and design

This document models how to detect gaps (missing candles) in the local
SQLite OHLC store for a given (pair, timeframe, time window). The goal is
to reliably find missing data ranges and later enable targeted backfilling
that respects Kraken’s public REST rate limit (≤1 request/second).

References:
- Schema creation in [cli/data.py](cli/data.py:113)
- OHLC sync command in [cli/data.py](cli/data.py:350)
- OHLC table: ohlc_bars(pair, timeframe_minutes, time, open, high, low, close, vwap, volume, count)
- Index: idx_ohlc_pair_tf_time ON (pair, timeframe_minutes, time)

## Definitions

- Candle step (seconds): step = timeframe_minutes * 60.
- Valid candle time: t is valid for timeframe if (t % step) == 0 and t is
  the UTC epoch of the candle start.
- Window [Wstart, Wend]: inclusive range of interest for detecting gaps.
  The range will be normalized to multiples of step:
  - Astart = smallest multiple of step ≥ Wstart
  - Aend = largest multiple of step ≤ Wend
- Existing set E: ordered set of times present in DB for
  (pair, timeframe_minutes) with Astart ≤ time ≤ Aend.
- Expected set X: ordered set of all valid times in [Astart, Aend], spaced
  exactly by `step`.

Gap:
- A contiguous run of expected times that are not present in E.
- Represented as [Gstart, GendExclusive) where:
  - Gstart is the first missing candle timestamp
  - GendExclusive is the first present or out-of-window timestamp following
    the gap, not included in the missing range
  - missing_count = (GendExclusive - Gstart) / step

Special cases:
- Leading gap: Missing from Astart up to the first present time.
- Trailing gap: Missing from the last present time’s successor to Aend.
- Internal gaps: Missing spans between present candles.

## Inputs / Outputs

Inputs:
- conn: sqlite3.Connection (read-only for scanning).
- pair: str (e.g., "ETHUSD").
- timeframe_minutes: int (e.g., 1, 5, 15, 60, 240, 1440).
- start_ts: int (epoch seconds, window start).
- end_ts: int (epoch seconds, window end, must be ≥ start_ts).

Outputs:
- Gaps: a list of Gap structures:
  - start_ts: int (inclusive)
  - end_ts_exclusive: int (exclusive)
  - missing_count: int
- Coverage summary:
  - expected: int
  - present: int
  - missing: int
  - coverage_ratio: float in [0, 1]

## Normalization

Normalize [start_ts, end_ts] to the candle grid:

- step = timeframe_minutes * 60
- Astart = ceil_div(start_ts, step) * step
- Aend = floor_div(end_ts, step) * step
- If Astart > Aend, the normalized window is empty.

Example:
- timeframe 15m → step=900
- start_ts=1731763233 → Astart=1731763500 (next multiple of 900)
- end_ts=1731769999 → Aend=1731769500 (previous multiple of 900)

## DB Query Strategy

Fetch present/known times in the window:

SQL:
SELECT time
FROM ohlc_bars
WHERE pair = ?
  AND timeframe_minutes = ?
  AND time BETWEEN ? AND ?
ORDER BY time

This uses the composite index (pair, timeframe_minutes, time).

Note:
- Deduplicate times if any duplicates exist (should not, due to PK).
- Ensure ascending order.

## Gap Scan Algorithm

Given:
- step
- aligned Astart, Aend
- E = sorted list of present times in [Astart, Aend]

Procedure:
1) Initialize cursor expected = Astart
2) Iterate through E as present_time:
   - While expected < present_time:
     - If no current gap, start one at gap_start = expected
     - Advance expected by step
   - If a gap was in progress and expected == present_time:
     - Close gap at gap_end_exclusive = present_time
     - Emit gap
   - Advance expected to present_time + step (move to next expected)
3) After iterating E, if expected ≤ Aend:
   - If not in gap, start gap at expected
   - Set gap_end_exclusive = Aend + step
   - Emit gap

Emit each gap with:
missing_count = (gap_end_exclusive - gap_start) // step

Edge handling:
- If E is empty:
  - Single gap [Astart, Aend + step)
- If no gaps (expected matches all present):
  - No gap records emitted

Time complexity:
- O(|E| + expected_count) with a single linear pass.
- expected_count = 1 + (Aend - Astart) / step

## Pseudocode

```python
from dataclasses import dataclass
from typing import Iterator

@dataclass(frozen=True, slots=True)
class Gap:
    start_ts: int
    end_ts_exclusive: int
    missing_count: int

def iter_existing_candle_times(
    conn: sqlite3.Connection,
    pair: str,
    timeframe_minutes: int,
    start_ts: int,
    end_ts: int,
) -> Iterator[int]:
    """Yield ordered candle times present in DB within [start_ts, end_ts]."""
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
        except Exception:
            continue

def align_window(
    start_ts: int,
    end_ts: int,
    step: int,
) -> tuple[int, int]:
    """Return Astart, Aend aligned to candle grid."""
    if end_ts < start_ts:
        return 0, -1  # empty
    astart = ((start_ts + step - 1) // step) * step
    aend = (end_ts // step) * step
    return astart, aend

def find_ohlc_gaps(
    conn: sqlite3.Connection,
    pair: str,
    timeframe_minutes: int,
    start_ts: int,
    end_ts: int,
) -> tuple[list[Gap], dict[str, float]]:
    """Compute missing candle ranges for (pair, timeframe, window)."""
    step = timeframe_minutes * 60
    astart, aend = align_window(start_ts, end_ts, step)
    if astart > aend:
        return [], {"expected": 0, "present": 0, "missing": 0, "coverage_ratio": 1.0}

    expected_count = ((aend - astart) // step) + 1

    gaps: list[Gap] = []
    existing = iter_existing_candle_times(conn, pair, timeframe_minutes, astart, aend)

    in_gap = False
    gap_start = 0
    expected = astart
    present_count = 0

    for present in existing:
        # Skip any unexpected out-of-grid values
        if present < expected:
            # could be duplicate or stale, ignore and continue
            continue

        # Fill missing region up to present
        if expected < present:
            if not in_gap:
                in_gap = True
                gap_start = expected
            # Close the gap right before present
            gaps.append(
                Gap(
                    start_ts=gap_start,
                    end_ts_exclusive=present,
                    missing_count=(present - gap_start) // step,
                )
            )
            in_gap = False

        # present matches expected (or we snapped onto present)
        present_count += 1
        expected = present + step

    # Trailing gap to end of window
    if expected <= aend:
        if not in_gap:
            gap_start = expected
        gaps.append(
            Gap(
                start_ts=gap_start,
                end_ts_exclusive=aend + step,
                missing_count=((aend + step) - gap_start) // step,
            )
        )

    missing = sum(g.missing_count for g in gaps)
    coverage = present_count / expected_count if expected_count else 1.0
    summary = {
        "expected": float(expected_count),
        "present": float(present_count),
        "missing": float(missing),
        "coverage_ratio": coverage,
    }
    return gaps, summary
```

## Edge Cases and Invariants

- Accept any window; normalize to the grid.
- Ignore non-grid times returned by DB (should not occur due to sync).
- Do not assume continuous ingest; internal gaps are possible.
- PK prevents duplicates; if present, they do not break correctness.
- Timezone: all times are epoch seconds (UTC). No DST involvement.
- If timeframe changes for the same pair, scanning must use the same
  timeframe_minutes to avoid false gap detection.

## SQL and Indexing

- Existing index `idx_ohlc_pair_tf_time (pair, timeframe_minutes, time)`
  enables efficient range scans by pair and timeframe.
- Query returns only the time column to reduce memory/IO.
- For very large windows, consider chunked scanning by time ranges if
  memory is a concern (not required initially).

## Coverage Metrics

- expected = number of expected candles in aligned window
- present = count of rows returned by SQL
- missing = sum of missing_count across gaps
- coverage_ratio = present / expected

These metrics allow reporting progress and designing threshold-based
alerts (e.g., coverage < 95%).

## CLI Integration (Proposed)

Add options to `data ohlc-sync`:
- `--inspect-gaps`: Perform a gap scan for the requested window without
  fetching data; render summary and gap list.
- `--output json|table`: Mirror existing convention; when json, return:
  ```
  {
    "pair": "...",
    "timeframe": "...",
    "window": {"start": Astart, "end": Aend},
    "coverage": {"expected": N, "present": M, "missing": K, "ratio": R},
    "gaps": [
      {"start": ts, "end_exclusive": ts2, "missing_count": c},
      ...
    ]
  }
  ```
- Optional later: `--fill-gaps` to backfill only missing ranges, honoring
  per-call ≤1 req/sec and Kraken 'since' semantics.

## Fill-Only Strategy (Future)

- Iterate gaps in ascending order.
- For each gap, call `get_ohlc_data(pair, interval, since=gap.start)`.
- Insert returned rows, advance using Kraken’s `last` token until
  `last >= gap.end_exclusive - step`.
- Stop early if API indicates no more data.
- Enforce 1 req/sec (already done in [cli/data.py](cli/data.py:509)).

## Testing Plan

Unit tests with in-memory SQLite:
1) Empty DB:
   - Expect single gap covering full aligned window.
2) Full coverage:
   - No gaps, coverage_ratio = 1.0.
3) Leading gap only:
   - No rows until mid-window, expect one gap at start.
4) Trailing gap only:
   - Missing end of window, expect one trailing gap.
5) Internal gaps:
   - Remove a few specific candles; detect multiple gaps with correct counts.
6) Edge alignment:
   - Non-aligned start/end timestamps normalize correctly; counts match.

These tests will validate correctness and boundary handling before CLI
integration and fill-only execution are implemented.
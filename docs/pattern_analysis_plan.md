"""
Plan for implementing historical pattern analysis features in KrakenCLI.

Updates: v0.9.11 - 2025-11-16 - Initial plan draft for pattern scanning and snapshot exports.
"""

# Pattern Analysis Feature Plan

## 1. Objectives

- Add tools to scan Kraken OHLC data for recurring patterns (MA crossovers, RSI extremes, Bollinger touches).
- Expose results via dedicated CLI commands with Rich rendering.
- Persist findings for repeat analysis and optional strategy snapshots.

## 2. Components & Responsibilities

1. `analysis/pattern_scanner.py`
   - Dataclasses: `PatternMatch`, `PatternStats`, `PatternSnapshot`.
   - `PatternScanner` orchestrates OHLC retrieval, indicator calculation, and detector registry.
   - Optional `PatternCache` helper storing JSON blobs in `logs/patterns/`.
2. `cli/patterns.py`
   - `pattern-scan` command: accepts `--pair`, `--timeframe`, `--lookback`, `--pattern`, `--force-refresh`, `--export-snapshots`, `--output`.
   - `pattern-heatmap` command: aggregates cached matches into weekday/hour heatmaps with thresholds (`--min-move`, `--window`, `--group-by`).
3. Strategy integration
   - `PatternSnapshot` structure compatible with `StrategyConfig`.
   - Optional YAML export to `configs/backtests/` for seeding automated strategies.

## 3. Implementation Steps

1. **Analysis Module**
   - Create `analysis` package with `__init__.py`.
   - Implement `PatternScanner` using `KrakenAPIClient.get_ohlc`, `utils.market_data`, and `indicators.TechnicalIndicators`.
   - Provide detector functions (MA crossover, RSI threshold, Bollinger band touch) registered in a dict keyed by pattern name.
   - Add caching layer storing computed matches alongside metadata (pair, timeframe, lookback, timestamp).
2. **CLI Commands**
   - Add `cli/patterns.py` that registers commands with shared dependency helpers (API client, retries, console).
   - Update `cli/__init__.py` and `kraken_cli.py` to include the new module.
   - Ensure output supports Rich tables and JSON export; include status icons from AGENTS.md.
3. **Snapshot Export**
   - Define `PatternSnapshot` dataclass storing pattern metadata plus expected move stats.
   - `pattern-scan --export-snapshots` writes YAML files into `configs/backtests/` with schema aligning to `StrategyConfig`.
4. **Documentation**
   - Update README Feature Highlights + Command Reference with new commands/examples.
   - Add CHANGELOG entry documenting the feature release.

## 4. Testing Strategy

- New unit tests (`tests/test_pattern_scanner.py`) covering indicator detectors, caching, and snapshot serialization.
- Extend `tests/test_cli_mocked.py` with Click runner coverage for `pattern-scan` and `pattern-heatmap`, using patched API responses or VCR cassettes.
- Optional integration test ensuring exported snapshots load into `StrategyManager` for a dry-run cycle.

## 5. Verification Checklist

- `pytest` (including new modules).
- `pyright` on new files (strict mode).
- CLI smoke tests:
  - `python kraken_cli.py pattern-scan -p ETHUSD --timeframe 1h --pattern ma_crossover`
  - `python kraken_cli.py pattern-heatmap -p ETHUSD --pattern rsi_extreme`
- Confirm cache files in `logs/patterns/` and snapshot exports in `configs/backtests/`.

## 6. Immediate Next Steps

1. Scaffold `analysis/pattern_scanner.py` plus caching helpers and ensure detectors are wired to `TechnicalIndicators`.
2. Implement `cli/patterns.py`, register it in `kraken_cli.py`, and refresh README/CHANGELOG documentation.
3. Create pytest suites (unit + CLI) for the new modules, then execute `pytest` and `pyright` to validate the additions.

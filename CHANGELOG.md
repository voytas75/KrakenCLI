# Changelog
All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Trader balance validation tests covering Kraken-prefixed asset codes.
- Configuration support for weighted Kraken endpoint costs in the rate limiter.
- Kraken API client session tests, trader execution tests, and config endpoint weight coverage additions.

### Changed
- `run_tests.sh` now enforces ≥80% coverage via the coverage CLI.
- Added `.coveragerc` to exclude optional automation and CLI utility modules from coverage calculations.

### Planned
- Expand automated trading test coverage (engine cycles, strategy signals, risk persistence).
- Implement dynamic rate limiter aligned with configurable thresholds.
- Add diagnostics command to verify optional dependencies and configuration health.

## [0.9.6] - 2025-11-13

### Added
- Introduced refreshed project blueprint documenting alerts, automation, and risk modules.

### Changed
- Updated `README.md` project structure section to align with AGENTS guidance.

## [0.9.5] - 2025-11-13

### Changed
- Standardised Kraken API base URL handling in configuration to follow 2025 guidance.

## [0.9.4] - 2025-11-12

### Added
- Withdrawal and export management commands to the CLI.
- Kraken API client helpers for export lifecycle operations with response caching.

### Fixed
- Improved internal caching strategy for open orders and ledger queries.

## [0.9.3] - 2025-11-12

### Added
- Risk alert management commands with logging integrations and alert persistence.
- Alert manager wiring in trading engine to surface automation failures.

## [0.9.2] - 2025-11-12

### Added
- Risk manager integration supplying protective orders and realised PnL tracking inside the trading engine.

## [0.9.1] - 2025-11-11

### Added
- Strategy manager registration for MACD and moving-average crossover strategies.

## [0.9.0] - 2025-11-11

### Added
- Automated trading engine with persistent status reporting and configurable strategies.
- Expanded configuration options for automation and alert subsystems.

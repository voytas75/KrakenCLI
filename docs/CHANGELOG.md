# Changelog
All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Planned
- Extend automated trading test coverage to include risk-state persistence and signal rejection paths.
- Introduce an automated diagnostics command for optional dependency and configuration checks.
- Implement adaptive rate limiting tuned to Kraken's endpoint categories.

### Changed
- `run_tests.sh` now executes the comprehensive suite plus pytest coverage for rate limits, automation, and CLI behaviour.

## [0.9.7] - 2025-11-13

### Added
- Token-bucket rate limiting for public and private Kraken endpoints with configurable thresholds.
- Trading engine unit tests covering dry-run and live execution paths.
- Diagnostics flag for the `info` command to surface configuration and dependency status.

### Changed
- Documented new rate-limit environment variables in README and project blueprint.

## [0.9.6] - 2025-11-13

### Added
- Refreshed project blueprint describing alerts, automation, and risk architecture.

### Changed
- `README.md` project structure now mirrors the authoritative layout from AGENTS guidance.

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

# Kraken CLI Project Blueprint

## Project Overview

**Project Name:** Kraken CLI  
**Version:** 1.0.0  
**Description:** Command-line interface for interacting with the Kraken cryptocurrency exchange API  
**Author:** MiniMax Agent  
**Last Updated:** 2025-11-13  

Updates: v0.9.6 - 2025-11-13 - Refreshed blueprint to capture alerts, automation, and risk architecture.

## Project Structure

```
KrakenCLI/
├── README.md
├── kraken_cli.py
├── config.py
├── requirements.txt
├── setup.py
├── alerts/
│   └── alert_manager.py
├── api/
│   └── kraken_client.py
├── cli/
│   ├── automation.py
│   ├── export.py
│   ├── portfolio.py
│   └── trading.py
├── configs/
│   ├── auto_trading.yaml
│   └── backtests/
├── engine/
│   └── trading_engine.py
├── indicators/
│   └── technical_indicators.py
├── portfolio/
│   └── portfolio_manager.py
├── risk/
│   └── risk_manager.py
├── strategies/
│   ├── base_strategy.py
│   ├── ma_crossover_strategy.py
│   ├── macd_strategy.py
│   ├── rsi_strategy.py
│   └── strategy_manager.py
├── trading/
│   └── trader.py
├── utils/
│   ├── helpers.py
│   └── logger.py
└── tests/
    ├── comprehensive_test.py
    ├── test_alert_manager.py
    ├── test_cli_mocked.py
    └── ...
```

## Core Architecture

### 1. Main Components

#### **CLI Interface (`kraken_cli.py`)**
- Click-based entry point (`python kraken_cli.py`) bundling configuration, logging, API client, portfolio manager, trader, and alert manager.
- Rich is used extensively for formatted panels, tables, and status indicators (`✅`, `❌`, `⚠️`, `ℹ️`, `🔍`).
- Exposes trading, portfolio, risk alert, export, and automation command groups while applying exponential backoff for API calls.

#### **Configuration (`config.py`)**
- Precedence: Environment → `.env` → `config.json` → defaults.
- Normalises API URL, boolean flags, retry/backoff values, rate limits, and alert settings.
- Provides helpers for retry configuration, rate limits, and auto-trading config path resolution.

#### **API Client (`api/kraken_client.py`)**
- Handles Kraken REST communication with HMAC-SHA512 signing (2025 spec), configurable base URL, and HTTPS enforcement.
- Implements caching for open orders and ledger lookups, export/withdraw endpoints, and conservative rate limiting.
- All responses are inspected for Kraken `error` payloads and surfaced with detailed logging while keeping secrets out of logs.

#### **Trading (`trading/trader.py`)**
- Validates orders, enforces confirmations, supports dry-run execution, and records operations.
- Integrates with risk manager decisions before executing live trades.
- Provides helpers for cancellations, order status checks, and balance confirmation.

#### **Portfolio (`portfolio/portfolio_manager.py`)**
- Aggregates balances, positions, USD conversions, and caches data to minimise API calls.
- Supports automation and CLI commands by exposing structured portfolio snapshots.

#### **Alerting (`alerts/alert_manager.py`)**
- Routes alert events to Rich console notifications and optional webhook/email channels.
- Persists alert preferences under `logs/auto_trading/risk_state.json` and sanitises sensitive fields by default.

#### **Risk Management (`risk/risk_manager.py`)**
- Tracks risk parameters (position sizing, drawdown limits, stop management) and persists state.
- Issues `RiskDecision` objects consumed by trading engine and trader to gate live execution.
- Integrates with alert manager for escalations and uses configuration-driven thresholds.

#### **Strategies & Automation**
- Strategy definitions live under `strategies/` with shared base classes and indicators (`indicators/technical_indicators.py`).
- `configs/auto_trading.yaml` configures enabled strategies, parameters, and risk settings.
- `engine/trading_engine.py` orchestrates strategy evaluation, risk checks, trader execution, and persists `status.json`.
- `cli/automation.py` exposes `auto-*` commands (`auto-start`, `auto-stop`, `auto-status`, `auto-config`) and validates optional dependencies (pandas, pandas-ta, TA-Lib).

### 2. Command Landscape

| Command | Description | Status | Notes |
|---------|-------------|--------|-------|
| `status` | Connectivity, balances, and logger level | ✅ | Shows credential status and active log level |
| `ticker` | Market data for a trading pair | ✅ | Normalises asset symbols and formats spread metrics |
| `order` | Validate/execute orders | ✅ | Dry-run by default; requires confirmation for live trades |
| `orders` | Open orders or trade history | ✅ | Uses cached payloads with auto-invalidation |
| `cancel` | Cancel individual or all orders | ✅ | Enforces explicit confirmation on destructive ops |
| `withdraw` | Submit or review withdrawals | ✅ | Requires `--confirm` to execute |
| `export-report` | Manage Kraken export jobs | ✅ | Supports create/status/retrieve/delete |
| `portfolio` | Portfolio balances and valuations | ✅ | Combines balances, USD conversions, and warnings |
| `risk-alerts` | Toggle and inspect alert settings | ✅ | Persists state and respects security checklist |
| `config-setup` | Interactive `.env` generator | ✅ | Wizard for onboarding credentials/settings |
| `auto-*` | Automation lifecycle management | ✅ | Requires strategies, risk manager, and authenticated trader |

## Technical Specifications

### Configuration & Environment
```env
KRAKEN_API_KEY=your_api_key_here
KRAKEN_API_SECRET=your_api_secret_here
KRAKEN_SANDBOX=false
KRAKEN_RATE_LIMIT=1
KRAKEN_TIMEOUT=30
KRAKEN_LOG_LEVEL=INFO
AUTO_TRADING_ENABLED=false
AUTO_TRADING_CONFIG_PATH=./configs/auto_trading.yaml
```

- Sensitive data is loaded from environment variables first; secrets are never written to logs or files.  
- Retry/backoff defaults: attempts=3, initial delay=1.0, backoff factor=1.5 (configurable via environment or `config.json`).  
- Rate limiting currently sleeps 1.2 seconds between authenticated calls to keep under 15 private requests/minute.

### Error Handling & Observability
- CLI backoff helper wraps network calls with exponential retries and Rich spinner progress.
- Logging format: `[YYYY-MM-DD HH:MM:SS] [LEVEL] [Component] Message`.
- Alerts emit Rich messages and JSON payloads without leaking secrets; cooldown prevents alert storms (default 60s).
- Automation status persisted to `logs/auto_trading/status.json` includes dry-run flag, last cycle timestamp, active strategies, and processed signal counts.

### Data Display
- Rich tables and panels across commands ensure consistent monospace alignment and emoji status indicators.
- Portfolio command highlights staked/future assets, cached USD valuation, and total portfolio value.
- Automation summary presents selected strategies, parameters, risk levels, and pair overrides before starting the engine.

### Security Considerations
- HTTPS enforced on all requests; HMAC signing uses base64-decoded secret per Kraken spec.
- CLI validates credentials before allowing trading/automation; dry-run mode is default for auto trading.
- Request/response logs redact secrets; no API keys or sensitive data stored in repository.
- Rate limiting and retry logic differentiates transient network errors from authentication/validation failures to avoid unsafe retries.

## Current Status

### ✅ Mature Capabilities
- Manual trading commands (status, ticker, order, orders, cancel, withdraw).
- Portfolio aggregation with caching and automated conversion helpers.
- Export management, risk alert lifecycle controls, and logging infrastructure.
- Automation engine coordinating strategies, risk manager, portfolio snapshotting, and trader integration.
- Documentation alignment between README, AGENTS, and this blueprint.

### 🚧 Active Enhancements
- Expand automated trading unit/integration tests (engine cycles, risk persistence, strategy signals).
- Implement dynamic rate limiter using token-bucket logic tied to configurable thresholds.
- Broaden diagnostics (`auto-status`, `info --diagnostics`) to surface dependency and configuration checks.

### 🔍 Known Risks
- Optional dependencies (pandas, pandas-ta, TA-Lib) remain user-managed; missing modules disable automation paths.
- Current rate limit guard applies a blanket delay and does not yet differentiate public/private buckets.
- Automation still relies on manual verification of strategy YAML; validation tooling is limited.

## Development Guidelines Snapshot

- **Language:** Python 3.12  
- **Style:** PEP 8 compliance, mandatory type hints, concise docstrings for all public functions.  
- **Testing:** Run `python tests/comprehensive_test.py` plus smoke commands (`--help`, `status`, `orders`, `ticker -p ETHUSD`) before commits.  
- **Security Checklist:** Ensure no secrets in code/logs, validate user inputs, enforce HTTPS, respect rate limits, and confirm request signing.  
- **Diagnostics:** Prefer Rich-formatted output for user-facing messages; sanitise exceptions; never expose stack traces in normal CLI mode.

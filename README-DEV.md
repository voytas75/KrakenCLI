# Kraken CLI – Developer Guide

Updates: v0.9.12 - 2025-11-24 - Created a dedicated developer handbook and moved engineering details from README.

This document captures developer workflows, coding standards, configuration details, and operational expectations for Kraken CLI. It complements the user-focused `README.md` and should be updated alongside code changes.

## 1. Development Environment

### 1.1 Requirements
- Python 3.12+
- `pip`, `virtualenv`, and `make` (optional but recommended)
- Access to Kraken API credentials (sandbox and production) stored via environment variables
- Optional TA libraries: `pandas-ta` or `TA-Lib` for accelerated indicators

### 1.2 Recommended Setup
```bash
git clone https://github.com/your-org/KrakenCLI.git
cd KrakenCLI
python3 -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install --upgrade pip
pip install -r requirements.txt
cp .env.template .env  # or run: python kraken_cli.py config-setup
```

Run smoke checks after installation:

```bash
python kraken_cli.py --help
python kraken_cli.py status
python tests/comprehensive_test.py
```

## 2. Coding Standards & Tooling
- **Formatting**: Use Black (line length 88) and order imports with isort.
- **Docstrings**: Google style docstrings for every public module/class/function, including argument and return types.
- **Typing**: Full annotations; run `pyright --strict` on core modules. Treat warnings as failures.
- **Async I/O**: Use `async`/`await` with `httpx` or async adapters for network/database calls. Reserve synchronous code for CPU-bound helpers.
- **Error Handling**: Wrap Kraken API calls in `try/except`, emit user-friendly messages, and log detailed traces (without secrets). Retry transient network faults up to 3 times with exponential backoff.
- **Logging**: Use the structured format `[YYYY-MM-DD HH:MM:SS] [LEVEL] [Component] Message`. Never log API keys or secrets.
- **CLI UX**: All commands must support `--help`, optional `--verbose`, Rich formatting, status icons (✅, ❌, ⚠️, ℹ️, 🔍), and graceful Ctrl+C handling.
- **Security**: Prioritise sandbox/dry-run defaults, double-check account balances before trading, and require explicit confirmations for live orders.

## 3. Architecture Overview

| Component | Responsibility |
| --- | --- |
| `api/kraken_client.py` | Authenticated REST communication, rate limiting, retries, structured responses. |
| `cli/` | Click command groups (trading, portfolio, export, automation). |
| `portfolio/portfolio_manager.py` | Portfolio aggregation, currency conversions, caching. |
| `trading/trader.py` | Order validation/execution, persistence hooks. |
| `alerts/alert_manager.py` | Alert routing (webhook/email) with throttling. |
| `engine/trading_engine.py` | Automated strategy orchestration. |
| `strategies/` & `risk/` | Strategy implementations and risk controls. |
| `utils/logger.py`, `utils/helpers.py` | Shared utilities, Rich console helpers, logging setup. |

Project tree (abridged):

```
KrakenCLI/
├── api/
├── cli/
├── portfolio/
├── trading/
├── strategies/
├── engine/
├── alerts/
├── utils/
├── tests/
└── docs/
```

Keep modules focused; extract secondary concerns when files approach ~350 executable lines and block merges when >500 lines until refactored (excluding tests and generated code).

## 4. Configuration & Secrets

### 4.1 Source Precedence
1. Environment variables
2. `.env` file (loaded via `python-dotenv`)
3. `config.json`
4. Hard-coded defaults in `config.Config`

### 4.2 Environment Variables

| Variable | Purpose | Default |
| --- | --- | --- |
| `KRAKEN_API_KEY` | Kraken API key for private endpoints | `None` |
| `KRAKEN_API_SECRET` | Base64 Kraken API secret | `None` |
| `KRAKEN_SANDBOX` | Toggle sandbox/test environment (`true`/`false`) | `false` |
| `KRAKEN_API_BASE_URL` | Override REST base URL | `https://api.kraken.com` |
| `KRAKEN_RATE_LIMIT` | Public requests per second | `1` |
| `KRAKEN_PUBLIC_RATE_LIMIT` | Alternate public throttle | `1.0` |
| `KRAKEN_PRIVATE_RATE_LIMIT_PER_MIN` | Private requests per minute | `15.0` |
| `KRAKEN_ENDPOINT_WEIGHTS` | JSON mapping of endpoint weights | `{}` |
| `KRAKEN_TIMEOUT` | HTTP timeout (seconds) | `30` |
| `KRAKEN_LOG_LEVEL` | Root logger level | `INFO` |
| `AUTO_TRADING_ENABLED` | Enable background engine | `false` |
| `AUTO_TRADING_CONFIG_PATH` | Strategy/risk YAML path | `./configs/auto_trading.yaml` |
| `ALERT_WEBHOOK_URL` | Optional webhook destination | `None` |
| `ALERT_EMAIL_*` | SMTP settings for alert emails | See template |

Example `.env` snippet:

```env
KRAKEN_API_KEY=your_api_key_here
KRAKEN_API_SECRET=your_api_secret_here
KRAKEN_SANDBOX=false
KRAKEN_RATE_LIMIT=1
KRAKEN_PRIVATE_RATE_LIMIT_PER_MIN=15
KRAKEN_TIMEOUT=30
KRAKEN_LOG_LEVEL=INFO
AUTO_TRADING_ENABLED=false
AUTO_TRADING_CONFIG_PATH=./configs/auto_trading.yaml
ALERT_WEBHOOK_URL=
ALERT_EMAIL_SMTP_SERVER=
ALERT_EMAIL_SMTP_PORT=587
```

Validate configuration during startup and never log raw credentials. Use HTTPS and signed requests for authenticated calls.

## 5. CLI Workflows & Command Reference

| Command | Description | Example |
| --- | --- | --- |
| `status` | Connectivity, balances, log level | `python kraken_cli.py status` |
| `ticker` | Market data for a pair | `python kraken_cli.py ticker -p XBTUSD` |
| `ohlc` | Candle data (interval/limit options) | `python kraken_cli.py ohlc -p ETHUSD -i 15 -l 20` |
| `order` | Validate/execute orders (dry-run default) | `python kraken_cli.py order --pair ETHUSD --side buy --order-type limit --volume 0.5 --price 2500` |
| `orders` | Open orders or trades | `python kraken_cli.py orders --trades` |
| `cancel` | Cancel single or all orders | `python kraken_cli.py cancel --txid OABC123` |
| `withdraw` | Manage withdrawals | `python kraken_cli.py withdraw --asset ZUSD --key Primary --amount 25 --confirm` |
| `export-report` | Kraken export jobs | `python kraken_cli.py export-report --report ledgers --description "Monthly" --confirm` |
| `portfolio` | Balances, USD valuations, comparisons | `python kraken_cli.py portfolio --compare logs/.../snapshot.json` |
| `config-setup` | Interactive `.env` generator | `python kraken_cli.py config-setup` |
| `risk-alerts` | Enable/disable alert notifications | `python kraken_cli.py risk-alerts --status` |
| `auto-*` | Manage automated trading engine | `python kraken_cli.py auto-start --dry-run --interval 180` |

When introducing new commands, ensure discoverability through `kraken_cli.py --help`, add regression coverage, and document behavior in both README files as appropriate.

## 6. Testing & Quality Assurance

- Use `pytest` (unit), `pytest-asyncio` (async flows), and `vcrpy` for HTTP fixtures.
- Maintain ≥80% coverage for core logic; `./run_tests.sh` aggregates coverage, pytest, and CLI smoke checks.
- Always run `python tests/comprehensive_test.py` plus the CLI smoke commands before committing:

```bash
python tests/comprehensive_test.py
pytest
coverage run -m pytest && coverage report --fail-under=80
python kraken_cli.py --help
python kraken_cli.py status
python kraken_cli.py orders
python kraken_cli.py ticker -p ETHUSD
```

- Add regression fixtures for new endpoints/features, and prefer dependency injection/mocks for Kraken API calls.
- Document any environment-related failures and ask users to rerun commands locally when DNS/network errors occur.

## 7. Logging, Monitoring, and Rate Limits

- Global limit: ≤1 request/second overall; ≤15 requests/minute for private endpoints. Track weights with `KRAKEN_ENDPOINT_WEIGHTS`.
- All API responses must follow the structured format `{"success": bool, "data": dict | list, "error": str | None, "cached": bool, "timestamp": float}`.
- Logs live in `logs/kraken_cli.log` (rotating 10 MB x5). Portfolio snapshots are stored under `logs/portfolio/snapshots/`.
- Alerts are throttled to 60 seconds between identical events; respect enable/disable state persisted in `logs/alert_state.json`.

## 8. Release & Documentation Workflow

- Follow Semantic Versioning (MAJOR.MINOR.PATCH) and tag releases as `vX.Y.Z`.
- Update `docs/CHANGELOG.md`, `README.md`, and `README-DEV.md` for user-facing changes.
- Each updated source file should include an `Updates: vX.Y.Z - YYYY-MM-DD - <description>` entry near the top.
- Internal documentation (`AGENTS.md`, `docs/*`) is reviewed quarterly; sync major architecture or process changes promptly.

## 9. Troubleshooting & Support

- **Missing API credentials**: Confirm `.env` values, reload shell, rerun `python kraken_cli.py status`.
- **Rate limit errors**: Increase cached data usage, double-check `KRAKEN_ENDPOINT_WEIGHTS`, and extend polling intervals.
- **Indicator discrepancies**: Ensure TA dependencies match strategy expectations; fall back to built-in math when libraries are absent.
- **Empty logs**: Verify `KRAKEN_LOG_LEVEL` and confirm the logger initialized (status command prints the active level).

## 10. Resources
- Kraken REST API: https://docs.kraken.com/api/
- Project blueprint: `docs/project_blueprint.md`
- Change history: `docs/CHANGELOG.md`
- Pattern analysis plan: `docs/pattern_analysis_plan.md`
- OHLC gap detection notes: `docs/ohlc_gap_detection.md`

For questions or planning new features, apply the GROW technique (Goal, Reality, Options, Way Forward) before implementation.

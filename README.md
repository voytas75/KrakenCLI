# Kraken Pro Trading CLI

Professional-grade command-line tooling for the Kraken cryptocurrency exchange. The CLI covers connectivity checks, market data, portfolio insights, and order execution with rich terminal feedback and comprehensive logging.

## Safety Notice

- 🚨 Trading digital assets involves substantial risk and can result in complete loss of capital.
- 🚨 Past performance is not indicative of future results.
- 🚨 Always validate strategies in sandbox mode before trading live funds.
- 🚨 Keep API credentials confidential and rotate them regularly.

## Table of Contents

- [Overview](#overview)
- [Feature Highlights](#feature-highlights)
- [Quick Start](#quick-start)
- [Configuration & Environment](#configuration--environment)
- [Command Reference](#command-reference)
- [Logging & Monitoring](#logging--monitoring)
- [Testing & Quality Assurance](#testing--quality-assurance)
- [Troubleshooting](#troubleshooting)
- [Project Structure](#project-structure)
- [Development Guidelines](#development-guidelines)
- [Resources & Support](#resources--support)
- [License & Disclaimer](#license--disclaimer)

## Overview

Kraken Pro Trading CLI is a Python 3.12+ application that interacts with the 2025 Kraken REST API (`https://api.kraken.com/0/`). It authenticates via HMAC-SHA512 signatures, respects exchange rate limits, and outputs results using the Rich library for readable terminal formatting. Configuration values are loaded securely from environment variables, `.env`, `config.json`, and built-in defaults (in that order).

## Feature Highlights

### Trading & Market Data

- Status command validates API connectivity, credentials, and surfaces the active log level.
- Ticker command normalises common asset symbols (BTC, ETH, USD, etc.) to Kraken pair codes and displays prices, spreads, and 24h performance.
- Order command supports market, limit, stop-loss, and take-profit orders with confirmation workflows and dry-run validation by default.
- Orders command renders open orders or trade history with human-readable timestamps.
- Cancel command handles single-order or global cancellations with explicit user confirmation.

### Portfolio & Risk Management

- Portfolio command aggregates balances, USD valuations, and open position snapshots.
- Built-in sanity checks flag missing USD reference prices for staked or future assets without breaking execution.
- Rate limiting helpers and consistent API response handling guard against throttling penalties.

### Operational Tooling

- `config-setup` wizard bootstraps `.env` files interactively.
- Logging helper writes rotating files to `logs/` and mirrors output to stdout at the configured level.
- Rich console panels and status icons provide clear user feedback across commands.

## Quick Start

### Prerequisites

- Python 3.12 or higher (enforced by `setup.py`)
- `pip` package manager
- Kraken API key and secret with required permissions

### Install & Configure

1. Clone or download the repository and move into the project directory:
   ```bash
   git clone https://github.com/your-org/KrakenCLI.git
   cd KrakenCLI
   ```
2. (Optional) Create and activate a virtual environment:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate  # Windows: .venv\Scripts\activate
   ```
3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
4. Create a `.env` file either by copying the template or running the interactive wizard:
   ```bash
   cp .env.template .env            # or
   python kraken_cli.py config-setup
   ```
5. Populate `KRAKEN_API_KEY`, `KRAKEN_API_SECRET`, and other settings in `.env`. Never commit real credentials to version control.

### Verify Installation

Run the following smoke checks after configuration:

```bash
python kraken_cli.py --help            # CLI command list
python kraken_cli.py status            # Connectivity check + current log level
python kraken_cli.py ticker -p ETHUSD  # Market data sample
python kraken_cli.py orders            # Orders overview (handles missing creds gracefully)
python tests/comprehensive_test.py     # End-to-end CLI regression suite
```

The status command prints the active logger level so you can confirm the `KRAKEN_LOG_LEVEL` setting without inspecting files.

### Optional Setup Script

`python setup.py` performs version checks, installs requirements, seeds `.env`, and runs `kraken_cli.py --help`. Use it if you prefer an automated bootstrap.

## Configuration & Environment

### Configuration Sources

Precedence from highest to lowest:

1. Runtime environment variables (`export VAR=value`)
2. `.env` file values (loaded via `python-dotenv`)
3. `config.json` (for non-sensitive defaults such as rate limit or timeout)
4. Application defaults embedded in `config.Config`

### Environment Variables

| Variable            | Purpose                                            | Default |
|---------------------|----------------------------------------------------|---------|
| `KRAKEN_API_KEY`    | Kraken API key (private endpoints)                 | `None`  |
| `KRAKEN_API_SECRET` | Kraken API secret (base64 string)                  | `None`  |
| `KRAKEN_SANDBOX`    | Toggle sandbox/test environment (`true`/`false`)   | `false` |
| `KRAKEN_RATE_LIMIT` | Requests per second throttle                       | `1`     |
| `KRAKEN_TIMEOUT`    | HTTP request timeout in seconds                    | `30`    |
| `KRAKEN_LOG_LEVEL`  | Root logger level (`INFO`, `DEBUG`, etc.)          | `INFO`  |

Example `.env` snippet:

```env
KRAKEN_API_KEY=your_api_key_here
KRAKEN_API_SECRET=your_api_secret_here
KRAKEN_SANDBOX=false
KRAKEN_RATE_LIMIT=1
KRAKEN_TIMEOUT=30
KRAKEN_LOG_LEVEL=INFO
```

### API Permissions

Create a Kraken API key with at least:

- Query Funds
- Query Open Orders & Trades
- Create & Modify Orders
- Cancel Orders

### Sandbox Mode

Set `KRAKEN_SANDBOX=true` for test trading. Use a dedicated sandbox API key and revert to `false` for live trading. The base URL remains `https://api.kraken.com`; sandbox behaviour is controlled by key entitlements.

## Command Reference

| Command | Description | Example |
|---------|-------------|---------|
| `status` | Check API connectivity, balances, and log level | `python kraken_cli.py status` |
| `ticker` | Display market data for a trading pair (`--pair` or base/quote args) | `python kraken_cli.py ticker -p XBTUSD` |
| `order` | Validate or execute an order (dry-run by default) | `python kraken_cli.py order --pair ETHUSD --side buy --order-type limit --volume 0.5 --price 2500` |
| `orders` | View open orders or trade history (`--trades`) | `python kraken_cli.py orders --trades` |
| `cancel` | Cancel a specific order (`--txid`) or all (`--cancel-all`) | `python kraken_cli.py cancel --txid OABC123` |
| `portfolio` | Summarise balances, USD valuations, and open positions | `python kraken_cli.py portfolio` |
| `config-setup` | Interactive `.env` generator | `python kraken_cli.py config-setup` |
| `info` | Application overview, risk warnings, and current log level | `python kraken_cli.py info` |

### Order Options at a Glance

- `--pair / -p`: Kraken trading pair (e.g., `XBTUSD`, `ETHUSD`)
- `--side / -s`: `buy` or `sell`
- `--order-type / -t`: `market`, `limit`, `stop-loss`, `take-profit`
- `--volume / -v`: Order volume (float)
- `--price`: Required for `limit` orders
- `--price2`: Secondary trigger price (stop-loss/take-profit)
- `--execute`: Execute live order after confirmation (otherwise validation only)
- `--validate`: Explicit dry-run (alias for default behaviour)
- `--yes / -y`: Skip execution confirmation (experienced users only)

## Logging & Monitoring

- Logs are written to `logs/kraken_cli.log` with rotation (10 MB x 5 files).
- Root logger honours `KRAKEN_LOG_LEVEL`; invalid values fall back to `INFO`.
- Outgoing API calls and errors are logged without leaking sensitive data.
- The current log level is displayed in CLI output (`status` command and application info panel) to confirm runtime configuration quickly.

## Testing & Quality Assurance

The project ships with CLI-focused regression tests (`tests/comprehensive_test.py`) and helper scripts.

Recommended test sequence after changes:

```bash
python tests/comprehensive_test.py
python kraken_cli.py --help
python kraken_cli.py status
python kraken_cli.py orders
python kraken_cli.py ticker -p ETHUSD
```

Ensure commands that hit authenticated endpoints handle missing credentials gracefully when running in non-production environments.

## Troubleshooting

- **“API credentials not configured”**: Confirm `.env` exists, is readable, and contains populated key/secret values. Restart your shell session after exporting variables manually.
- **Connection failures or timeouts**: Verify network access, confirm API rate limits are not exceeded, and check `KRAKEN_TIMEOUT`.
- **Invalid trading pair**: Use recognised Kraken symbols (`XBTUSD`, `ETHUSD`, etc.). The CLI automatically maps common codes like `BTC` to `XBT`.
- **Unexpected percentage changes**: VWAP-based calculations rely on Kraken’s 24h stats; large deviations usually indicate thin liquidity or newly listed assets.
- **Portfolio warnings about staked assets**: Staked or future tokens (e.g., `ADA.S`) may not have direct USD pricing. The CLI flags them without interrupting execution.
- **Logs look empty**: Confirm `KRAKEN_LOG_LEVEL` isn’t set higher than intended. Run `python kraken_cli.py status` to display the active level.

For deeper debugging, add `--verbose` (where available), rerun commands, and inspect `logs/kraken_cli.log`.

## Project Structure

```
KrakenCLI/
├── kraken_cli.py            # Main Click command group
├── config.py                # Configuration loader and precedence handler
├── api/
│   └── kraken_client.py     # REST API integration and signing
├── portfolio/
│   └── portfolio_manager.py # Portfolio aggregation logic
├── trading/
│   └── trader.py            # Order validation and submission
├── utils/
│   ├── helpers.py           # Formatting utilities
│   └── logger.py            # Logging bootstrap
├── tests/                   # CLI regression scripts
├── requirements.txt         # Python dependencies
├── setup.py                 # Optional bootstrap helper
├── AGENTS.md                # Codex project guidance
└── logs/                    # Rotating log outputs (generated at runtime)
```

## Development Guidelines

- Follow PEP 8 and include type hints and docstrings for public functions.
- Handle Kraken API errors gracefully; never expose secrets in logs or console output.
- Respect rate limits (1 req/sec public, ~15 req/min private) and back off on HTTP errors.
- Use Rich components consistently for user-facing output.
- Before submitting changes, run the comprehensive test script and smoke-test core commands listed in [Testing & Quality Assurance](#testing--quality-assurance).

## Resources & Support

- Kraken REST API reference: https://docs.kraken.com/rest/
- Kraken support centre: https://support.kraken.com
- Internal project guidelines: `AGENTS.md`

## License & Disclaimer

This project is provided for educational and research purposes. It is not affiliated with Kraken, and the authors accept no liability for financial losses. By using the CLI you acknowledge the risks associated with cryptocurrency trading and agree to trade only with funds you can afford to lose.

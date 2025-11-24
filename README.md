# Kraken CLI

Updates: v0.9.12 - 2025-11-24 - Moved developer documentation into README-DEV and refreshed the user overview.

Professional-grade command-line tooling for the Kraken cryptocurrency exchange. Kraken CLI focuses on secure configuration, Rich-formatted output, and predictable execution for market data, portfolio insights, and trading workflows.

> If you can, please support me by
> [![Kraken](https://img.shields.io/badge/Kraken.com-earn_20_USDG-2824B6)](https://proinvite.kraken.com/9f1e/hqsollz2)
> Unlock 20 USDG after signing up and trade with the code `bz9fds3s`. Thanks!

## Installation

```bash
git clone https://github.com/your-org/KrakenCLI.git
cd KrakenCLI
python3 -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.template .env  # then populate your credentials
```

## Quick Start

```bash
# Set environment variables (or edit .env)
export KRAKEN_API_KEY=your_api_key
export KRAKEN_API_SECRET=your_api_secret
export KRAKEN_SANDBOX=false

# Explore the CLI
python kraken_cli.py --help
python kraken_cli.py status
python kraken_cli.py ticker -p ETHUSD
python kraken_cli.py orders

# Run the end-to-end regression script
python tests/comprehensive_test.py
```

## Safety Notice

- 🚨 Trading digital assets involves substantial risk and can result in complete loss of capital.
- 🚨 Past performance is not indicative of future results.
- 🚨 Always validate strategies in sandbox or dry-run modes before trading with live funds.
- 🚨 Keep API credentials confidential and rotate them regularly.

## Features

- Rich-formatted commands for connectivity checks, market data, portfolio views, and order execution.
- Built-in safety controls such as dry-run orders, explicit confirmations, and balance validation.
- Portfolio manager aggregates spot, staking, and futures balances with cached USD pricing.
- Optional automated trading engine with configurable RSI, MACD, and MA crossover strategies.
- Logging subsystem writes structured output to both console and rotating files for easy auditing.

## Developer

For contributor workflows, coding standards, configuration details, and troubleshooting steps, see `README-DEV.md`. Release notes are tracked in `docs/CHANGELOG.md`.

## License

MIT License

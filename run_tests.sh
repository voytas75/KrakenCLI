#!/bin/bash
# Kraken CLI Test Runner

echo "🧪 Running Kraken CLI Test Suite"
echo "================================="

# Respectively run Python comprehensive regression and pytest suites.
set -euo pipefail

python tests/comprehensive_test.py

python -m coverage erase
python -m coverage run \
  --rcfile=.coveragerc \
  --source=alerts,api,cli,engine,portfolio,risk,strategies,trading,utils,kraken_cli,config \
  -m pytest \
  tests/test_rate_limit_enforcement.py \
  tests/test_kraken_client_core.py \
  tests/test_trader_balance_validation.py \
  tests/test_config_endpoint_weights.py \
  tests/test_utils_helpers.py \
  tests/test_portfolio_manager.py \
  tests/test_trading_engine.py \
  tests/test_cli_mocked.py

python -m coverage report --fail-under=80

echo ""
echo "🎉 Test execution completed!"

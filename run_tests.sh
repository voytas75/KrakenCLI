#!/bin/bash
# Kraken CLI Test Runner

echo "🧪 Running Kraken CLI Test Suite"
echo "================================="

# Respectively run Python comprehensive regression and pytest suites.
set -e

python tests/comprehensive_test.py

python -m pytest \
  tests/test_rate_limit_enforcement.py \
  tests/test_trading_engine.py \
  tests/test_cli_mocked.py

echo ""
echo "🎉 Test execution completed!"

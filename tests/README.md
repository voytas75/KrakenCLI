# Kraken CLI Test Suite

This directory contains test files for the Kraken CLI application.

## Test Files

### comprehensive_test.py
Main test script that validates all CLI commands work correctly.
- Tests safe commands (help, info) that work without credentials
- Tests credential commands (portfolio, orders, status) that show graceful errors
- Validates context object handling
- Checks for KeyError exceptions

**Usage:**
```bash
python tests/comprehensive_test.py
```

### test_kraken_pairs.py
Test script to investigate Kraken API pair naming conventions.
- Discovers how Kraken API formats pair names internally
- Tests pair resolution logic
- Found the issue: XBTUSD → XXBTZUSD translation

**Usage:**
```bash
python tests/test_kraken_pairs.py
```

### test_ticker_pair_fix.py
Test script to validate the ticker command pair resolution fix.
- Confirms realistic percentage calculations (1.12% vs 3622%)
- Tests the smart pair resolution logic
- Validates API response handling

**Usage:**
```bash
python tests/test_ticker_pair_fix.py
```

### test_ticker_debug.py
Debug script for ticker command issues.
- Helps identify ticker display problems
- Tests individual components

**Usage:**
```bash
python tests/test_ticker_debug.py
```

### test_ticker_fix.py
Earlier test script for ticker fixes.
- Historical test for ticker command debugging
- Contains development progress

**Usage:**
```bash
python tests/test_ticker_fix.py
```

### final_demo.py
Final demonstration script showing working ticker functionality.
- Demonstrates the fixed ticker command
- Shows realistic price and percentage data
- Good for quick validation

**Usage:**
```bash
python tests/final_demo.py
```

### final_test_summary.py
Test summary and validation script.
- Provides overall test results
- Documents all fixes applied

**Usage:**
```bash
python tests/final_test_summary.py
```

## Running All Tests

To run the comprehensive test from the project root:
```bash
python tests/comprehensive_test.py
```

## Test Results

All tests validate that:
- ✅ Context object management works correctly
- ✅ Commands handle missing credentials gracefully
- ✅ Help commands work without credentials
- ✅ No more KeyError exceptions
- ✅ Rich library rendering works properly
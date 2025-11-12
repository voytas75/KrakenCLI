# KrakenCLI – Development Standards and Rules

This document defines development standards, testing procedures, and operational rules for KrakenCLI, a financial command-line interface for interacting with the Kraken Cryptocurrency Exchange API.

Reliability, accuracy, and security are mandatory. All contributors must follow these rules to ensure consistent and safe system behavior.

---

## 1. Project Overview

KrakenCLI is a Python 3.12 command-line tool for trading and portfolio management through Kraken’s API.

Core design principles:

* Security and privacy over convenience.
* Consistent user experience via Rich-formatted output.
* Predictable, testable behavior for all commands.
* Explicit error handling and detailed logging.

Primary reference:
[Kraken API Documentation](https://docs.kraken.com/api/)

---

## 2. Architecture and Components

| Component                          | Description                                                                                 |
| ---------------------------------- | ------------------------------------------------------------------------------------------- |
| api/kraken_client.py           | Manages communication with the Kraken API. Handles authentication, rate limits, and errors. |
| cli/                            | Modular Click command groups for trading, portfolio, export, and automation flows.          |
| portfolio/portfolio_manager.py | Processes and caches portfolio data. Performs calculations and conversions.                 |
| trading/trader.py              | Executes trading actions. Validates orders and records operations.                          |
| kraken_cli.py                  | Entry point bootstrapping context and delegating to CLI modules.                            |
| config.py                      | Loads configuration and environment variables.                                              |
| tests/                         | Contains test suite for unit, integration, and end-to-end validation.                       |

### Project folder and file structure

```text
KrakenCLI/
├── kraken_cli.py
├── config.py
├── cli/
│   ├── __init__.py
│   ├── automation.py
│   ├── export.py
│   ├── portfolio.py
│   └── trading.py
├── api/
│   ├── kraken_client.py
│   └── *
├── portfolio/
│   ├── portfolio_manager.py
│   └── *
├── trading/
│   ├── trader.py
│   └── *
└── tests/
    ├── comprehensive_test.py
    └── *
```

---

## 3. Coding Standards

* Follow PEP 8 strictly.
* Use type hints on all function parameters and return values.
* Document all public functions with concise docstrings.
* Prefer explicit names and avoid abbreviations.
* Emoji usage limited to user-facing CLI output.
* Maintain semantic clarity—no hidden logic or side effects.

---

## 4. Testing Requirements

### 4.1 Scope

| Test Type             | Purpose                                                     |
| --------------------- | ----------------------------------------------------------- |
| Unit Tests        | Validate internal logic of each module.                     |
| Integration Tests | Ensure correct API interaction and data flow.               |
| End-to-End Tests  | Simulate user commands and verify system behavior manually. |

### 4.2 Execution

* Run `./tests/comprehensive_test.py` before each commit.
* Ensure all CLI commands function as expected:

  ```bash
  python kraken_cli.py --help
  python kraken_cli.py orders
  python kraken_cli.py ticker -p ETHUSD
  ```
* Maintain ≥ 80 % code coverage for all core modules.
* For environment-related errors (e.g., network or DNS issues), request user re-execution with explicit CLI command examples.

---

## 5. Configuration Management

* Sensitive data must always use environment variables.
* Precedence: Environment → .env → config.json → Defaults.
* Never log secrets or tokens.
* Validate configuration on startup.
* Example required variables:

  ```text
  KRAKEN_API_KEY=your_api_key
  KRAKEN_API_SECRET=your_secret
  KRAKEN_SANDBOX=false
  ```

---

## 6. Error Handling

* Wrap all API calls in `try/except`.
* Never allow unhandled exceptions to terminate execution.
* Display user-friendly messages; log full details separately.
* Retry transient network errors up to 3 times with exponential backoff.
* Never retry on authentication or validation failures.

---

## 7. Documentation Rules

* Every file and public method must include docstrings describing purpose, inputs, outputs, and known limitations.
* Each update must append a version log entry:

  ```
  Updates: v{version} - {YYYY-MM-DD} - {description}
  ```
* Maintain:

  * `README.md` for overall description.
  * `CHANGELOG.md` per [Keep a Changelog](https://keepachangelog.com).
* Internal docs (this file and others under `/docs`) are reviewed quarterly.

---

## 8. API and Communication Rules

* Apply 1 request / second limit globally; ≤ 15 requests / minute for private endpoints.
* Log all API activity without sensitive data.
* Use consistent structured response format:

  ```python
  {
      "success": bool,
      "data": dict | list,
      "error": str | None,
      "cached": bool,
      "timestamp": float
  }
  ```

### Logging Format

```
[YYYY-MM-DD HH:MM:SS] [LEVEL] [Component] Message
```

---

## 9. Trading and Financial Safety

* Validate all order parameters before execution.
* Require explicit confirmation for each trade.
* Always check account balance.
* Support a dry-run mode for non-production testing.
* Use HTTPS and signed requests for all authenticated operations.

---

## 10. CLI Interface Standards

* All commands must implement `--help`.
* Provide `--verbose` for detailed output.
* Handle `Ctrl+C` gracefully.
* Display progress bars for long operations.
* Use Rich for formatting and table alignment.
* Status icons: ✅ Success, ❌ Failure, ⚠️ Warning, ℹ️ Info, 🔍 Inspect.

---

## 11. Performance Considerations

* Cache frequent API data.
* Avoid redundant calls; use batch endpoints when available.
* Close all network sessions properly.
* Use generators for large datasets.
* Monitor memory use for portfolio computations.

---

## 12. Security Checklist

* [ ] No API keys or secrets in code.
* [ ] No sensitive data in logs.
* [ ] All user inputs validated.
* [ ] HTTPS enforced for all calls.
* [ ] Request signing implemented.
* [ ] Rate limiting respected.
* [ ] Error messages sanitized.

---

## 13. Versioning Policy

Use Semantic Versioning:

| Type      | Change Description                    | Example |
| --------- | ------------------------------------- | ------- |
| MAJOR | Incompatible API or CLI changes       | 2.0.0   |
| MINOR | Backward-compatible feature additions | 1.1.0   |
| PATCH | Backward-compatible bug fixes         | 1.0.1   |

Tag releases as `vX.Y.Z`.
Document version changes in `CHANGELOG.md`.

---

## 14. GROW Technique for Feature Planning

The GROW model structures reasoning for new features or refactors.

1. Goal – Define desired outcome, inputs, outputs, and success criteria.
2. Reality – Describe environment, dependencies, and constraints.
3. Options – List alternative approaches with trade-offs.
4. Way Forward – Select best approach and outline implementation steps.

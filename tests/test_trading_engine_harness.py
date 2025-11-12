"""Tests for trading engine harness, risk manager, and auto CLI commands."""

from __future__ import annotations

import base64
import json
import unittest
import uuid
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Dict, Iterable, List, Optional, Sequence
from unittest import mock

import pandas as pd
from click.testing import CliRunner

import kraken_cli
from engine.trading_engine import TradingEngine
from risk.risk_manager import RiskDecision, RiskManager
from strategies.base_strategy import BaseStrategy, StrategyConfig, StrategyContext, StrategySignal


FIXTURE_DIR = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> Dict[str, Any]:
    """Return fixture content as a dictionary."""
    path = FIXTURE_DIR / name
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def ohlc_dataframe_from_fixture(payload: Dict[str, Any], key: str) -> pd.DataFrame:
    """Convert Kraken-style OHLC payload into a pandas DataFrame."""
    rows = payload.get("result", {}).get(key, [])
    df = pd.DataFrame(
        rows,
        columns=["time", "open", "high", "low", "close", "vwap", "volume", "count"],
    )
    if df.empty:
        raise ValueError(f"No OHLC data available for key {key}.")
    df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
    for column in ["open", "high", "low", "close", "vwap", "volume"]:
        df[column] = df[column].astype(float)
    return df


class DummyApiClient:
    """Stub Kraken API client returning fixture-backed OHLC data."""

    def __init__(self, payload: Dict[str, Any]):
        self._payload = payload
        self.calls: List[tuple[str, int]] = []

    def get_ohlc_data(self, pair: str, interval: int = 60) -> Dict[str, Any]:
        self.calls.append((pair, interval))
        return self._payload


class StubTrader:
    """Trader stub that records placed orders without touching the network."""

    def __init__(self, api_client: DummyApiClient):
        self.api_client = api_client
        self.orders: List[Dict[str, Any]] = []

    def place_order(
        self,
        pair: str,
        type: str,
        ordertype: str,
        volume: float,
        price: Optional[float] = None,
        price2: Optional[float] = None,
        leverage: Optional[str] = None,
        userref: Optional[int] = None,
        validate: bool = True,
    ) -> Dict[str, Any]:
        self.orders.append(
            {
                "pair": pair,
                "type": type,
                "ordertype": ordertype,
                "volume": volume,
                "price": price,
                "price2": price2,
                "validate": validate,
            }
        )
        return {"result": {"txid": ["STUB-TX"]}}


class StubPortfolioManager:
    """Portfolio manager stub supplying deterministic balances and positions."""

    def __init__(self, balances: Dict[str, str], positions: Dict[str, Any]):
        self._balances = balances
        self._positions = positions

    def get_balances(self) -> Dict[str, str]:
        return self._balances

    def get_open_positions(self) -> Dict[str, Any]:
        return self._positions


class StubStrategy(BaseStrategy):
    """Strategy stub that returns a predefined list of signals."""

    def __init__(self, config: StrategyConfig, signals: Sequence[StrategySignal]):
        super().__init__(config)
        self._signals = list(signals)
        self.calls: List[StrategyContext] = []

    def generate_signals(self, context: StrategyContext) -> List[StrategySignal]:
        self.calls.append(context)
        return list(self._signals)


class StubStrategyManager:
    """Strategy manager stub that exposes a fixed strategy set."""

    def __init__(self, strategies: Dict[str, StubStrategy]):
        self._strategies = strategies
        self.refreshed = False

    def refresh(self) -> None:
        self.refreshed = True

    def available(self) -> Iterable[str]:
        return self._strategies.keys()

    def get_config(self, key: str) -> StrategyConfig:
        return self._strategies[key].config

    def get_strategy(self, key: str) -> StubStrategy:
        return self._strategies[key]

    def get_active_strategies(self) -> List[StubStrategy]:  # pragma: no cover - simple passthrough
        return list(self._strategies.values())


class StubRiskManager:
    """Risk manager stub returning a predetermined decision."""

    def __init__(self, decision: RiskDecision):
        self._decision = decision
        self.evaluate_calls: List[tuple[StrategySignal, StrategyContext]] = []
        self.record_calls: List[tuple[str, RiskDecision, StrategyContext]] = []

    def evaluate_signal(self, signal: StrategySignal, context: StrategyContext) -> RiskDecision:
        self.evaluate_calls.append((signal, context))
        return self._decision

    def record_execution(self, pair: str, decision: RiskDecision, context: StrategyContext) -> float:
        self.record_calls.append((pair, decision, context))
        return 0.0


class RecordingAlertManager:
    """Collects alert payloads for verification during tests."""

    def __init__(self) -> None:
        self.records: List[tuple[str, str, str, Dict[str, Any]]] = []

    def send(
        self,
        event: str,
        message: str,
        severity: str = "INFO",
        details: Optional[Dict[str, Any]] = None,
        *,
        cooldown: Optional[float] = None,
        force: bool = False,
    ) -> None:
        self.records.append((event, message, severity, details or {}))


class DummyEngine:
    """Engine stub capturing run_forever invocations for CLI tests."""

    def __init__(self):
        self.run_args: Optional[Dict[str, Any]] = None
        self.stop_requested: bool = False

    def run_forever(self, **kwargs: Any) -> None:
        self.run_args = kwargs

    def request_stop(self) -> None:  # pragma: no cover - exercised via auto-start exception path
        self.stop_requested = True

    def status(self):  # pragma: no cover - simple stub accessor
        class _Status:
            processed_signals = 0

        return _Status()


class TradingEngineHarnessTests(unittest.TestCase):
    """Validate TradingEngine.run_once behaviour using fixture-driven data."""

    def setUp(self) -> None:
        self.tempdir = TemporaryDirectory()
        self.ohlc_payload = load_fixture("ohlc_ethusd.json")
        self.strategy_config = StrategyConfig(
            name="Stub Strategy",
            parameters={"pairs": ["ETHUSD"]},
            risk={},
            timeframe="1h",
            enabled=True,
        )
        self.default_signal = StrategySignal(action="buy", confidence=0.9, reason="Fixture signal")

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _build_engine(
        self,
        decision: RiskDecision,
        *,
        signals: Optional[Sequence[StrategySignal]] = None,
        alert_manager: Optional[Any] = None,
    ) -> tuple[TradingEngine, StubTrader, StubRiskManager, DummyApiClient]:
        api_client = DummyApiClient(self.ohlc_payload)
        trader = StubTrader(api_client)
        portfolio = StubPortfolioManager({"USD": "1000"}, {})
        strategy = StubStrategy(self.strategy_config, signals or [self.default_signal])
        manager = StubStrategyManager({"stub": strategy})
        risk_manager = StubRiskManager(decision)
        control_dir = Path(self.tempdir.name) / f"auto_{uuid.uuid4().hex}"
        engine = TradingEngine(
            trader=trader,
            portfolio_manager=portfolio,
            strategy_manager=manager,
            risk_manager=risk_manager,
            control_dir=control_dir,
            poll_interval=60,
            rate_limit=100.0,
            alert_manager=alert_manager,
        )
        return engine, trader, risk_manager, api_client

    def test_run_once_dry_run_processes_fixture_signals(self) -> None:
        decision = RiskDecision(
            True,
            "Approved",
            volume=0.25,
            position_fraction=0.1,
            direction="long",
            entry_price=3038.15,
            stop_loss_price=None,
            take_profit_price=None,
            closing_position=False,
        )
        engine, trader, risk_manager, api_client = self._build_engine(decision)

        with mock.patch("time.sleep", return_value=None):
            processed = engine.run_once(dry_run=True)

        self.assertEqual(processed, 1)
        self.assertEqual(api_client.calls, [("ETHUSD", 60)])
        self.assertEqual(len(risk_manager.evaluate_calls), 1)
        self.assertEqual(len(risk_manager.record_calls), 1)
        self.assertEqual(trader.orders, [])
        self.assertEqual(engine._status.active_pairs, ["ETHUSD"])

    def test_run_once_live_executes_orders(self) -> None:
        decision = RiskDecision(
            True,
            "Approved",
            volume=0.5,
            position_fraction=0.1,
            direction="long",
            entry_price=3038.15,
            stop_loss_price=None,
            take_profit_price=None,
            closing_position=False,
        )
        engine, trader, risk_manager, api_client = self._build_engine(decision)

        with mock.patch("time.sleep", return_value=None):
            processed = engine.run_once(dry_run=False)

        self.assertEqual(processed, 1)
        self.assertEqual(api_client.calls, [("ETHUSD", 60)])
        self.assertEqual(len(trader.orders), 1)
        order = trader.orders[0]
        self.assertEqual(order["pair"], "ETHUSD")
        self.assertEqual(order["type"], "buy")
        self.assertEqual(order["ordertype"], "market")
        self.assertFalse(order["validate"])
        self.assertAlmostEqual(order["volume"], decision.volume)
        self.assertEqual(len(risk_manager.record_calls), 1)

    def test_run_once_emits_alert_when_decision_rejected(self) -> None:
        decision = RiskDecision(
            False,
            "Daily trade limit reached.",
            volume=None,
            position_fraction=0.0,
            direction="flat",
            entry_price=None,
            stop_loss_price=None,
            take_profit_price=None,
            closing_position=False,
        )
        alert_recorder = RecordingAlertManager()
        engine, trader, risk_manager, api_client = self._build_engine(
            decision,
            alert_manager=alert_recorder,
        )

        with mock.patch("time.sleep", return_value=None):
            processed = engine.run_once(dry_run=True)

        self.assertEqual(processed, 1)
        self.assertEqual(len(alert_recorder.records), 1)
        event, message, severity, details = alert_recorder.records[0]
        self.assertEqual(event, "risk.decision_rejected")
        self.assertEqual(severity, "WARNING")
        self.assertIn("Daily trade limit", message)
        self.assertEqual(details.get("pair"), "ETHUSD")
        self.assertEqual(len(alert_recorder.records), 1)

    def test_run_forever_emits_stop_alert(self) -> None:
        decision = RiskDecision(
            True,
            "Approved",
            volume=0.1,
            position_fraction=0.1,
            direction="long",
            entry_price=3038.15,
            stop_loss_price=None,
            take_profit_price=None,
            closing_position=False,
        )
        alert_recorder = RecordingAlertManager()
        engine, _, _, _ = self._build_engine(
            decision,
            alert_manager=alert_recorder,
        )

        with mock.patch("time.sleep", return_value=None):
            engine.run_forever(dry_run=True, max_cycles=1)

        events = [event for event, *_ in alert_recorder.records]
        self.assertIn("engine.stopped", events)


class RiskManagerEvaluationTests(unittest.TestCase):
    """Validate RiskManager.evaluate_signal decisions using fixture OHLC data."""

    def setUp(self) -> None:
        self.tempdir = TemporaryDirectory()
        payload = load_fixture("ohlc_ethusd.json")
        self.dataframe = ohlc_dataframe_from_fixture(payload, "XETHZUSD")
        risk_config = {
            "position_size": 0.1,
            "stop_loss": 0.02,
            "take_profit": 0.04,
            "max_daily_trades": 5,
        }
        self.config = StrategyConfig(
            name="Risk Test",
            parameters={},
            risk=risk_config,
            timeframe="1h",
            enabled=True,
        )
        self.context = StrategyContext(
            pair="ETHUSD",
            timeframe="1h",
            ohlcv=self.dataframe,
            account_balances={"USD": "1000"},
            open_positions={},
            config=self.config,
        )
        self.signal = StrategySignal(action="buy", confidence=0.85, reason="Test entry")
        self.risk_manager = RiskManager(Path(self.tempdir.name) / "risk_state.json")

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_evaluate_signal_returns_volume_and_protective_prices(self) -> None:
        decision = self.risk_manager.evaluate_signal(self.signal, self.context)
        self.assertTrue(decision.approved)

        latest_close = float(self.context.ohlcv["close"].iloc[-1])
        expected_volume = (1000.0 * 0.1) / latest_close
        self.assertAlmostEqual(decision.volume or 0.0, expected_volume, places=6)
        self.assertAlmostEqual(decision.stop_loss_price or 0.0, latest_close * (1 - 0.02), places=6)
        self.assertAlmostEqual(decision.take_profit_price or 0.0, latest_close * (1 + 0.04), places=6)
        self.assertEqual(decision.direction, "long")

    def test_evaluate_signal_blocks_when_daily_trade_limit_reached(self) -> None:
        self.risk_manager._state.daily_trades = self.risk_manager.DEFAULT_LIMITS["max_daily_trades"]
        decision = self.risk_manager.evaluate_signal(self.signal, self.context)
        self.assertFalse(decision.approved)
        self.assertIn("Daily trade limit", decision.reason)

    def test_daily_loss_alert_triggered_and_persisted(self) -> None:
        alert_recorder = RecordingAlertManager()
        manager = RiskManager(
            Path(self.tempdir.name) / "risk_alert_state.json",
            alert_manager=alert_recorder,
        )
        manager._state.daily_loss = 25.0
        manager._state.daily_loss_alerted = False

        decision = manager.evaluate_signal(self.signal, self.context)
        self.assertFalse(decision.approved)
        self.assertEqual(len(alert_recorder.records), 1)
        event, _, severity, details = alert_recorder.records[0]
        self.assertEqual(event, "risk.daily_loss_limit")
        self.assertEqual(severity, "ERROR")
        self.assertGreater(details.get("daily_loss", 0), details.get("limit", 0))

        manager.evaluate_signal(self.signal, self.context)
        self.assertEqual(len(alert_recorder.records), 1)


class AutoCliTests(unittest.TestCase):
    """Integration-style tests for auto-start and auto-status CLI commands."""

    def setUp(self) -> None:
        self.runner = CliRunner()
        self.tempdir = TemporaryDirectory()
        self.auto_dir = Path(self.tempdir.name)
        self.status_path = self.auto_dir / "status.json"
        secret = base64.b64encode(b"secret-key").decode()
        self.env = {
            "KRAKEN_API_KEY": "TESTKEY123",
            "KRAKEN_API_SECRET": secret,
            "KRAKEN_SANDBOX": "true",
        }

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_auto_start_invokes_engine_run_forever(self) -> None:
        fake_engine = DummyEngine()
        with mock.patch.object(kraken_cli, "AUTO_CONTROL_DIR", self.auto_dir), \
            mock.patch.object(kraken_cli, "RISK_STATE_FILE", self.auto_dir / "risk_state.json"), \
            mock.patch.object(kraken_cli, "AUTO_STATUS_FILE", self.status_path), \
            mock.patch("kraken_cli._create_trading_engine", return_value=fake_engine) as mock_create, \
            mock.patch("kraken_cli._display_auto_start_summary") as mock_summary:
            result = self.runner.invoke(
                kraken_cli.cli,
                ["auto-start", "--interval", "60", "--dry-run"],
                env=self.env,
            )

        self.assertEqual(result.exit_code, 0, msg=result.output)
        self.assertIn("Starting auto trading engine", result.output)
        mock_create.assert_called_once()
        mock_summary.assert_called_once()
        self.assertIsNotNone(fake_engine.run_args)
        self.assertTrue(fake_engine.run_args["dry_run"])
        self.assertEqual(fake_engine.run_args["poll_interval"], 60)
        self.assertIsNone(fake_engine.run_args["strategy_keys"])

    def test_auto_status_displays_structured_status_table(self) -> None:
        payload = {
            "running": True,
            "dry_run": True,
            "last_cycle_at": datetime.now(timezone.utc).isoformat(),
            "processed_signals": 3,
            "active_strategies": ["rsi"],
            "active_pairs": ["ETHUSD"],
            "last_error": None,
        }
        self.auto_dir.mkdir(parents=True, exist_ok=True)
        self.status_path.write_text(json.dumps(payload), encoding="utf-8")

        with mock.patch.object(kraken_cli, "AUTO_STATUS_FILE", self.status_path), \
            mock.patch.object(kraken_cli, "AUTO_CONTROL_DIR", self.auto_dir):
            result = self.runner.invoke(kraken_cli.cli, ["auto-status"], env=self.env)

        self.assertEqual(result.exit_code, 0, msg=result.output)
        self.assertIn("Auto Trading Status", result.output)
        self.assertIn("Processed Signals", result.output)
        self.assertIn("Active Strategies", result.output)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()

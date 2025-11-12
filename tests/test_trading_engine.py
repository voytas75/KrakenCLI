"""Unit tests for the trading engine automation cycle."""

from __future__ import annotations

import time
from types import SimpleNamespace
from typing import Any, Dict, Iterable, List, Optional, Sequence

import pytest

pd = pytest.importorskip("pandas")

from engine.trading_engine import TradingEngine
from risk.risk_manager import RiskDecision
from strategies.base_strategy import BaseStrategy, StrategyConfig, StrategySignal


class _StubStrategy(BaseStrategy):
    """Strategy returning predetermined signals for testing."""

    def __init__(self, config: StrategyConfig, signals: Sequence[StrategySignal]):
        super().__init__(config)
        self._signals = list(signals)
        self.last_context = None

    def generate_signals(self, context: Any) -> List[StrategySignal]:
        self.last_context = context
        return list(self._signals)


class _StubStrategyManager:
    """Minimal strategy manager satisfying engine requirements."""

    def __init__(self, strategies: Sequence[_StubStrategy]):
        self._strategies = list(strategies)
        self._lookup = {strategy.name: strategy for strategy in strategies}

    def refresh(self) -> None:  # pragma: no cover - no-op
        return None

    def available(self) -> Iterable[str]:
        return self._lookup.keys()

    def get_strategy(self, key: str) -> _StubStrategy:
        return self._lookup[key]

    def get_active_strategies(self) -> List[_StubStrategy]:
        for strategy in self._strategies:
            strategy.validate()
        return list(self._strategies)


class _StubPortfolioManager:
    """Portfolio manager stub returning static balances/positions."""

    def get_balances(self) -> Dict[str, Any]:
        return {"ZUSD": {"balance": "1000.0"}}

    def get_open_positions(self) -> Dict[str, Any]:
        return {}


class _StubRiskManager:
    """Risk manager stub returning predetermined decisions."""

    def __init__(self, decisions: Sequence[RiskDecision], record_pnl: Sequence[float] | None = None):
        self._decisions = list(decisions)
        self._record_returns = list(record_pnl or [0.0] * len(decisions))
        self.evaluate_calls: List[StrategySignal] = []
        self.record_calls: List[tuple[str, RiskDecision]] = []

    def evaluate_signal(self, signal: StrategySignal, context: Any) -> RiskDecision:
        self.evaluate_calls.append(signal)
        return self._decisions[min(len(self.evaluate_calls) - 1, len(self._decisions) - 1)]

    def record_execution(self, pair: str, decision: RiskDecision, context: Any) -> float:
        self.record_calls.append((pair, decision))
        index = min(len(self.record_calls) - 1, len(self._record_returns) - 1)
        return self._record_returns[index]


class _StubTrader:
    """Trader stub capturing order placement requests."""

    def __init__(self, ohlc_payload: Dict[str, Any]):
        self.api_client = SimpleNamespace(get_ohlc_data=lambda pair, interval: ohlc_payload)
        self.orders: List[Dict[str, Any]] = []

    def place_order(self, *, pair: str, type: str, ordertype: str, volume: float, price: Optional[float] = None, validate: bool) -> Dict[str, Any]:  # type: ignore[override]
        order = {
            "pair": pair,
            "type": type,
            "ordertype": ordertype,
            "volume": volume,
            "price": price,
            "validate": validate,
        }
        self.orders.append(order)
        return {"result": "ok"}


def _build_engine(
    tmp_path: Any,
    *,
    strategy: _StubStrategy,
    risk_manager: _StubRiskManager,
    trader: _StubTrader,
) -> TradingEngine:
    engine = TradingEngine(
        trader=trader,
        portfolio_manager=_StubPortfolioManager(),
        strategy_manager=_StubStrategyManager([strategy]),
        risk_manager=risk_manager,
        control_dir=tmp_path,
        poll_interval=300,
        rate_limit=1000.0,
        alert_manager=None,
    )
    engine.rate_delay = 0.0
    engine._send_alert = lambda *args, **kwargs: None  # type: ignore[attr-defined]
    return engine


def _ohlc_payload_for_pair(pair: str) -> Dict[str, Any]:
    now = int(time.time())
    rows = [
        [now - 120, "1000", "1010", "995", "1005", "1002", "150", "10"],
        [now - 60, "1005", "1020", "998", "1015", "1010", "200", "12"],
        [now, "1015", "1030", "1005", "1025", "1020", "180", "9"],
    ]
    return {"result": {pair: rows}}


@pytest.fixture(autouse=True)
def _patch_time_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    """Prevent trading engine tests from sleeping during execution."""

    monkeypatch.setattr("time.sleep", lambda *_args, **_kwargs: None)


def test_run_once_dry_run_records_execution_without_orders(tmp_path: Any) -> None:
    pair = "ETHUSD"
    signal = StrategySignal(action="buy", confidence=0.9, reason="test")
    strategy = _StubStrategy(
        StrategyConfig(name="stub", parameters={"pairs": [pair]}, timeframe="1h"),
        signals=[signal],
    )
    risk_decision = RiskDecision(approved=True, reason="ok", volume=0.5)
    risk_manager = _StubRiskManager([risk_decision], record_pnl=[0.0])
    trader = _StubTrader(_ohlc_payload_for_pair(pair))

    engine = _build_engine(tmp_path, strategy=strategy, risk_manager=risk_manager, trader=trader)

    processed = engine.run_once(dry_run=True)

    assert processed == 1
    assert trader.orders == []
    assert len(risk_manager.evaluate_calls) == 1
    assert len(risk_manager.record_calls) == 1
    assert engine._status.active_pairs == [pair]
    assert engine._status.active_strategies == [strategy.name]


def test_run_once_live_trade_places_orders_and_protective(tmp_path: Any) -> None:
    pair = "ETHUSD"
    signal = StrategySignal(action="buy", confidence=0.95, reason="entry")
    strategy = _StubStrategy(
        StrategyConfig(name="live-stub", parameters={"pairs": [pair]}, timeframe="1h"),
        signals=[signal],
    )
    risk_decision = RiskDecision(
        approved=True,
        reason="ok",
        volume=1.0,
        stop_loss_price=990.0,
        take_profit_price=1050.0,
    )
    risk_manager = _StubRiskManager([risk_decision], record_pnl=[12.5])
    trader = _StubTrader(_ohlc_payload_for_pair(pair))

    engine = _build_engine(tmp_path, strategy=strategy, risk_manager=risk_manager, trader=trader)

    processed = engine.run_once(dry_run=False)

    assert processed == 1
    assert len(trader.orders) == 3  # market + stop loss + take profit
    market_order, stop_order, take_profit_order = trader.orders
    assert market_order["ordertype"] == "market" and market_order["validate"] is False
    assert stop_order["ordertype"] == "stop-loss" and stop_order["price"] == pytest.approx(990.0)
    assert take_profit_order["ordertype"] == "take-profit" and take_profit_order["price"] == pytest.approx(1050.0)
    assert len(risk_manager.record_calls) == 1

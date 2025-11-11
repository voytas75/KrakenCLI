"""
Automated trading engine coordinating strategies, risk, and trade execution.

Updates: v0.9.0 - 2025-11-11 - Added polling engine with persistent status reporting.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

import pandas as pd

from portfolio.portfolio_manager import PortfolioManager
from risk import RiskDecision, RiskManager
from strategies.base_strategy import StrategyContext, StrategySignal
from strategies.strategy_manager import StrategyManager
from trading.trader import Trader

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class TradingEngineStatus:
    """Structured status payload for CLI display."""

    running: bool
    dry_run: bool
    last_cycle_at: Optional[datetime] = None
    last_error: Optional[str] = None
    active_pairs: List[str] = field(default_factory=list)
    active_strategies: List[str] = field(default_factory=list)
    processed_signals: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "running": self.running,
            "dry_run": self.dry_run,
            "last_cycle_at": self.last_cycle_at.isoformat() if self.last_cycle_at else None,
            "last_error": self.last_error,
            "active_pairs": self.active_pairs,
            "active_strategies": self.active_strategies,
            "processed_signals": self.processed_signals,
        }

    @staticmethod
    def from_dict(payload: Dict[str, Any]) -> "TradingEngineStatus":
        status = TradingEngineStatus(
            running=payload.get("running", False),
            dry_run=payload.get("dry_run", True),
            last_error=payload.get("last_error"),
            active_pairs=list(payload.get("active_pairs", [])),
            active_strategies=list(payload.get("active_strategies", [])),
            processed_signals=int(payload.get("processed_signals", 0)),
        )
        if payload.get("last_cycle_at"):
            status.last_cycle_at = datetime.fromisoformat(payload["last_cycle_at"])
        return status


class TradingEngine:
    """Polling trading engine coordinating strategy evaluation."""

    TIMEFRAME_TO_INTERVAL = {
        "1m": 1,
        "5m": 5,
        "15m": 15,
        "30m": 30,
        "1h": 60,
        "4h": 240,
        "1d": 1440,
    }

    def __init__(
        self,
        trader: Trader,
        portfolio_manager: PortfolioManager,
        strategy_manager: StrategyManager,
        risk_manager: RiskManager,
        control_dir: Path,
        poll_interval: int = 300,
        rate_limit: float = 1.0,
    ):
        self.trader = trader
        self.portfolio_manager = portfolio_manager
        self.strategy_manager = strategy_manager
        self.risk_manager = risk_manager
        self.poll_interval = poll_interval
        self.rate_delay = 1.0 / max(rate_limit, 0.1)

        self.control_dir = control_dir
        self.control_dir.mkdir(parents=True, exist_ok=True)
        self.status_file = self.control_dir / "status.json"
        self.stop_flag_file = self.control_dir / "stop.flag"

        self._stop_event = threading.Event()
        self._status = TradingEngineStatus(running=False, dry_run=True)

    def run_forever(
        self,
        strategy_keys: Optional[Sequence[str]] = None,
        dry_run: bool = True,
        poll_interval: Optional[int] = None,
        max_cycles: Optional[int] = None,
        pairs_override: Optional[Sequence[str]] = None,
        timeframe_override: Optional[str] = None,
    ) -> None:
        """Execute trading cycles until stop requested or max_cycles reached."""
        self.strategy_manager.refresh()
        self._status.running = True
        self._status.dry_run = dry_run
        self._status.last_error = None
        self._persist_status()

        interval = poll_interval or self.poll_interval
        cycle_count = 0

        try:
            while not self._should_stop():
                cycle_count += 1
                start_time = time.perf_counter()
                try:
                    processed = self.run_once(
                        strategy_keys=strategy_keys,
                        dry_run=dry_run,
                        pairs_override=pairs_override,
                        timeframe_override=timeframe_override,
                    )
                    self._status.processed_signals = processed
                    self._status.last_cycle_at = datetime.now(tz=timezone.utc)
                    self._status.last_error = None
                except Exception as exc:  # pragma: no cover - protective guard
                    logger.exception("Trading engine cycle failed: %s", exc)
                    self._status.last_error = str(exc)
                finally:
                    self._persist_status()

                if max_cycles is not None and cycle_count >= max_cycles:
                    break

                elapsed = time.perf_counter() - start_time
                sleep_time = max(0.0, interval - elapsed)
                if sleep_time > 0:
                    self._stop_event.wait(timeout=sleep_time)
        finally:
            self._status.running = False
            self._persist_status()
            self._clear_stop_flag()

    def run_once(
        self,
        strategy_keys: Optional[Sequence[str]] = None,
        dry_run: bool = True,
        pairs_override: Optional[Sequence[str]] = None,
        timeframe_override: Optional[str] = None,
    ) -> int:
        """Execute a single trading evaluation cycle."""
        strategies = self._select_strategies(strategy_keys)
        self._status.active_strategies = [strategy.name for strategy in strategies]

        balances = self.portfolio_manager.get_balances()
        positions = self.portfolio_manager.get_open_positions()

        processed_signals = 0
        active_pairs: List[str] = []

        for strategy in strategies:
            pairs = list(pairs_override) if pairs_override else self._extract_pairs(strategy.config.parameters)
            timeframe = timeframe_override or strategy.config.timeframe
            interval = self.TIMEFRAME_TO_INTERVAL.get(timeframe, 60)

            for pair in pairs:
                active_pairs.append(pair)
                ohlcv = self._fetch_ohlcv(pair, interval)
                if ohlcv is None:
                    continue

                context = StrategyContext(
                    pair=pair,
                    timeframe=timeframe,
                    ohlcv=ohlcv,
                    account_balances=balances,
                    open_positions=positions,
                    config=strategy.config,
                )

                signals = strategy.generate_signals(context)
                for signal in signals:
                    processed_signals += 1
                    decision = self.risk_manager.evaluate_signal(signal, context)
                    if not decision.approved:
                        logger.info("⚠️  Signal skipped: %s (%s)", signal.reason, decision.reason)
                        continue

                    if dry_run:
                        logger.info(
                            "🔍 Dry-run signal approved for %s: %s %.4f (confidence %.2f)",
                            pair,
                            signal.action,
                            decision.volume or 0.0,
                            signal.confidence,
                        )
                        self.risk_manager.record_execution(pair)
                        continue

                    self._execute_order(pair, signal, decision)
                    time.sleep(self.rate_delay)

                time.sleep(self.rate_delay)

        self._status.active_pairs = active_pairs
        return processed_signals

    def request_stop(self) -> None:
        """Signal the engine loop to halt."""
        self._stop_event.set()
        self._persist_stop_flag()

    def _execute_order(self, pair: str, signal: StrategySignal, decision: RiskDecision) -> None:
        volume = decision.volume
        if volume is None or volume <= 0:
            logger.warning("Calculated order volume invalid; skipping order for %s.", pair)
            return

        try:
            result = self.trader.place_order(
                pair=pair,
                type=signal.action,
                ordertype="market",
                volume=volume,
                validate=False,
            )
            logger.info("✅ Order placed for %s: %s", pair, result)
            self.risk_manager.record_execution(pair)
        except Exception as exc:
            logger.error("Failed to place order for %s: %s", pair, exc)

    def _select_strategies(self, strategy_keys: Optional[Sequence[str]]) -> List[Any]:
        if strategy_keys:
            selected = []
            for key in strategy_keys:
                selected.append(self.strategy_manager.get_strategy(key))
            return selected
        return self.strategy_manager.get_active_strategies()

    def _extract_pairs(self, parameters: Dict[str, Any]) -> List[str]:
        pairs = parameters.get("pairs") or parameters.get("symbols") or []
        if isinstance(pairs, str):
            pairs = [item.strip() for item in pairs.split(",") if item.strip()]
        if not pairs:
            pairs = ["ETHUSD"]
        return pairs

    def _fetch_ohlcv(self, pair: str, interval: int) -> Optional[pd.DataFrame]:
        try:
            response = self.trader.api_client.get_ohlc_data(pair, interval=interval)
        except Exception as exc:
            logger.error("Failed to fetch OHLCV for %s: %s", pair, exc)
            return None

        result = response.get("result", {})
        data = result.get(pair)
        if not data:
            logger.warning("No OHLCV data returned for %s.", pair)
            return None

        df = pd.DataFrame(
            data,
            columns=["time", "open", "high", "low", "close", "vwap", "volume", "count"],
        )
        df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
        for column in ["open", "high", "low", "close", "vwap", "volume"]:
            df[column] = df[column].astype(float)
        return df

    def _should_stop(self) -> bool:
        if self._stop_event.is_set():
            return True
        if self.stop_flag_file.exists():
            return True
        return False

    def _persist_status(self) -> None:
        try:
            with self.status_file.open("w", encoding="utf-8") as handle:
                json.dump(self._status.to_dict(), handle, indent=2)
        except OSError as exc:
            logger.error("Unable to persist engine status: %s", exc)

    def _persist_stop_flag(self) -> None:
        try:
            self.stop_flag_file.write_text("stop", encoding="utf-8")
        except OSError as exc:
            logger.error("Failed to create stop flag: %s", exc)

    def _clear_stop_flag(self) -> None:
        try:
            if self.stop_flag_file.exists():
                self.stop_flag_file.unlink()
        except OSError as exc:
            logger.error("Failed to remove stop flag: %s", exc)

    def status(self) -> TradingEngineStatus:
        """Return the most recent status payload, reading from disk if necessary."""
        if self.status_file.exists():
            try:
                payload = json.loads(self.status_file.read_text(encoding="utf-8"))
                self._status = TradingEngineStatus.from_dict(payload)
            except (json.JSONDecodeError, OSError) as exc:
                logger.error("Failed to read engine status: %s", exc)
        return self._status

"""
Risk management controls for automated trading.

Updates: v0.9.0 - 2025-11-11 - Implemented baseline daily limits and position sizing rules.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from strategies.base_strategy import StrategyContext, StrategySignal

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class RiskDecision:
    """Decision outcome returned by RiskManager."""

    approved: bool
    reason: str
    volume: Optional[float] = None
    position_fraction: float = 0.0


@dataclass(slots=True)
class _TradeHistory:
    """Internal structure for tracking trade cadence."""

    last_trade_at: Optional[datetime] = None
    trades_today: int = 0


@dataclass(slots=True)
class _RiskState:
    """Persisted risk state for daily limits."""

    as_of: datetime = field(default_factory=lambda: datetime.now(tz=timezone.utc))
    daily_loss: float = 0.0
    daily_trades: int = 0
    history_by_pair: Dict[str, _TradeHistory] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Serialise state for disk persistence."""
        serialised_history: Dict[str, Dict[str, Any]] = {}
        for pair, history in self.history_by_pair.items():
            serialised_history[pair] = {
                "last_trade_at": history.last_trade_at.isoformat() if history.last_trade_at else None,
                "trades_today": history.trades_today,
            }
        return {
            "as_of": self.as_of.isoformat(),
            "daily_loss": self.daily_loss,
            "daily_trades": self.daily_trades,
            "history_by_pair": serialised_history,
        }

    @staticmethod
    def from_dict(payload: Dict[str, Any]) -> "_RiskState":
        """Deserialise risk state from disk."""
        state = _RiskState()
        if payload.get("as_of"):
            state.as_of = datetime.fromisoformat(payload["as_of"])
        state.daily_loss = float(payload.get("daily_loss", 0.0))
        state.daily_trades = int(payload.get("daily_trades", 0))

        history: Dict[str, Any] = payload.get("history_by_pair", {})
        for pair, entry in history.items():
            last_trade_at = None
            if entry.get("last_trade_at"):
                last_trade_at = datetime.fromisoformat(entry["last_trade_at"])
            state.history_by_pair[pair] = _TradeHistory(
                last_trade_at=last_trade_at,
                trades_today=int(entry.get("trades_today", 0)),
            )
        return state


class RiskManager:
    """Evaluate trade signals against configured limits."""

    DEFAULT_LIMITS: Dict[str, Any] = {
        "position_size": 0.02,
        "max_daily_loss": 0.02,
        "max_positions": 3,
        "max_daily_trades": 5,
        "min_trade_gap_minutes": 60,
    }

    def __init__(self, state_path: Path):
        self.state_path = state_path
        self._state = self._load_state()
        self.state_path.parent.mkdir(parents=True, exist_ok=True)

    def _load_state(self) -> _RiskState:
        if not self.state_path.exists():
            return _RiskState()
        try:
            with self.state_path.open("r", encoding="utf-8") as handle:
                payload = json.load(handle)
            return _RiskState.from_dict(payload)
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Failed to load risk state, starting fresh: %s", exc)
            return _RiskState()

    def _persist_state(self) -> None:
        try:
            with self.state_path.open("w", encoding="utf-8") as handle:
                json.dump(self._state.to_dict(), handle, indent=2)
        except OSError as exc:
            logger.error("Unable to write risk state: %s", exc)

    def reset_if_new_day(self) -> None:
        """Reset counters when UTC day rolls over."""
        now = datetime.now(tz=timezone.utc)
        if self._state.as_of.date() != now.date():
            logger.info("Resetting risk counters for new day.")
            self._state = _RiskState(as_of=now)
            self._persist_state()

    def evaluate_signal(self, signal: StrategySignal, context: StrategyContext) -> RiskDecision:
        """
        Evaluate whether a proposed trade signal satisfies risk constraints.
        Returns a RiskDecision containing approval flag and recommended volume.
        """
        self.reset_if_new_day()
        limits = self._merge_limits(context.config.risk)

        if self._state.daily_trades >= limits["max_daily_trades"]:
            return RiskDecision(False, "Daily trade limit reached.")

        pair_history = self._state.history_by_pair.setdefault(context.pair, _TradeHistory())
        if pair_history.last_trade_at:
            elapsed = datetime.now(tz=timezone.utc) - pair_history.last_trade_at
            min_gap = timedelta(minutes=limits["min_trade_gap_minutes"])
            if elapsed < min_gap:
                return RiskDecision(False, f"Minimum trade gap {min_gap} not met for {context.pair}.")

        volume = self._calculate_volume(signal, context, limits)
        if volume is None or volume <= 0:
            return RiskDecision(False, "Calculated trade volume is non-positive.")

        # Placeholder for drawdown monitoring; ensures daily loss does not exceed threshold.
        account_equity = self._estimate_account_equity(context)
        if account_equity <= 0:
            logger.debug("Account equity estimation unavailable; proceeding with caution.")
        elif self._state.daily_loss / account_equity >= limits["max_daily_loss"]:
            return RiskDecision(False, "Maximum daily loss threshold reached.")

        return RiskDecision(True, "Signal approved.", volume=volume, position_fraction=limits["position_size"])

    def record_execution(self, pair: str, pnl: float = 0.0) -> None:
        """Record a trade execution to update daily counters."""
        now = datetime.now(tz=timezone.utc)
        self._state.daily_trades += 1
        self._state.daily_loss = max(0.0, self._state.daily_loss + min(0.0, pnl))

        history = self._state.history_by_pair.setdefault(pair, _TradeHistory())
        history.last_trade_at = now
        history.trades_today += 1

        self._state.as_of = now
        self._persist_state()

    def status(self) -> Dict[str, Any]:
        """Return current risk metrics for monitoring."""
        return {
            "daily_trades": self._state.daily_trades,
            "daily_loss": self._state.daily_loss,
            "history": {
                pair: {
                    "last_trade_at": history.last_trade_at.isoformat() if history.last_trade_at else None,
                    "trades_today": history.trades_today,
                }
                for pair, history in self._state.history_by_pair.items()
            },
        }

    @staticmethod
    def _merge_limits(risk_config: Dict[str, Any]) -> Dict[str, Any]:
        limits = RiskManager.DEFAULT_LIMITS.copy()
        for key, value in (risk_config or {}).items():
            if key in limits:
                limits[key] = value
        return limits

    @staticmethod
    def _calculate_volume(signal: StrategySignal, context: StrategyContext, limits: Dict[str, Any]) -> Optional[float]:
        """Derive trade volume based on balances and configured risk fraction."""
        balances = context.account_balances or {}
        close_price = float(context.ohlcv["close"].iloc[-1])
        position_fraction = float(limits["position_size"])

        pair = context.pair
        base_asset = pair[:-3]
        quote_asset = pair[-3:]

        try:
            if signal.action == "buy":
                quote_balance = float(balances.get(quote_asset, 0.0))
                position_value = quote_balance * position_fraction
                if position_value <= 0:
                    return None
                return position_value / close_price
            if signal.action == "sell":
                base_balance = float(balances.get(base_asset, 0.0))
                return base_balance * position_fraction
        except (TypeError, ValueError) as exc:
            logger.debug("Failed to calculate volume for %s: %s", pair, exc)
            return None
        return None

    @staticmethod
    def _estimate_account_equity(context: StrategyContext) -> float:
        """Estimate total account equity using USD balances when available."""
        balances = context.account_balances or {}
        try:
            usd_balance = float(balances.get("ZUSD", balances.get("USD", 0.0)))
            return max(0.0, usd_balance)
        except (TypeError, ValueError):
            return 0.0

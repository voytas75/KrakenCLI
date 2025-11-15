"""
Risk management controls for automated trading.

Updates:
    v0.9.0 - 2025-11-11 - Implemented baseline daily limits and position sizing rules.
    v0.9.2 - 2025-11-12 - Added stop loss/take profit handling, realised PnL tracking, and drawdown enforcement.
    v0.9.3 - 2025-11-12 - Integrated alert notifications and daily loss guardrails.
    v0.9.4 - 2025-11-15 - Hardened price extraction for test harness compatibility.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, Optional, Tuple

from strategies.base_strategy import StrategyContext, StrategySignal

if TYPE_CHECKING:
    from alerts.alert_manager import AlertManager

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class RiskDecision:
    """Decision outcome returned by RiskManager."""

    approved: bool
    reason: str
    volume: Optional[float] = None
    position_fraction: float = 0.0
    direction: str = "flat"
    entry_price: Optional[float] = None
    stop_loss_price: Optional[float] = None
    take_profit_price: Optional[float] = None
    closing_position: bool = False


@dataclass(slots=True)
class _TradeHistory:
    """Internal structure for tracking trade cadence."""

    last_trade_at: Optional[datetime] = None
    trades_today: int = 0


@dataclass(slots=True)
class _PositionState:
    """Internal representation of an open position for PnL tracking."""

    direction: str
    entry_price: float
    volume: float

    def to_dict(self) -> Dict[str, Any]:
        """Serialise the open position for persistence."""
        return {
            "direction": self.direction,
            "entry_price": self.entry_price,
            "volume": self.volume,
        }

    @staticmethod
    def from_dict(payload: Dict[str, Any]) -> "_PositionState":
        """Restore an open position from persisted payload."""
        return _PositionState(
            direction=str(payload.get("direction", "flat")),
            entry_price=float(payload.get("entry_price", 0.0)),
            volume=float(payload.get("volume", 0.0)),
        )


@dataclass(slots=True)
class _RiskState:
    """Persisted risk state for daily limits."""

    as_of: datetime = field(default_factory=lambda: datetime.now(tz=timezone.utc))
    daily_loss: float = 0.0
    daily_realised_pnl: float = 0.0
    daily_trades: int = 0
    history_by_pair: Dict[str, _TradeHistory] = field(default_factory=dict)
    positions: Dict[str, _PositionState] = field(default_factory=dict)
    daily_loss_alerted: bool = False

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
            "daily_realised_pnl": self.daily_realised_pnl,
            "daily_trades": self.daily_trades,
            "history_by_pair": serialised_history,
            "positions": {pair: position.to_dict() for pair, position in self.positions.items()},
            "daily_loss_alerted": self.daily_loss_alerted,
        }

    @staticmethod
    def from_dict(payload: Dict[str, Any]) -> "_RiskState":
        """Deserialise risk state from disk."""
        state = _RiskState()
        if payload.get("as_of"):
            state.as_of = datetime.fromisoformat(payload["as_of"])
        state.daily_loss = float(payload.get("daily_loss", 0.0))
        state.daily_realised_pnl = float(payload.get("daily_realised_pnl", 0.0))
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

        positions_payload: Dict[str, Any] = payload.get("positions", {})
        for pair, entry in positions_payload.items():
            try:
                state.positions[pair] = _PositionState.from_dict(entry)
            except (TypeError, ValueError):
                logger.debug("Failed to restore position for %s; skipping.", pair)

        state.daily_loss_alerted = bool(payload.get("daily_loss_alerted", False))
        return state


class RiskManager:
    """Evaluate trade signals against configured limits."""

    DEFAULT_LIMITS: Dict[str, Any] = {
        "position_size": 0.02,
        "max_daily_loss": 0.02,
        "max_positions": 3,
        "max_daily_trades": 5,
        "min_trade_gap_minutes": 60,
        "stop_loss": 0.03,
        "take_profit": 0.06,
    }

    def __init__(self, state_path: Path, alert_manager: Optional["AlertManager"] = None):
        self.state_path = state_path
        self._state = self._load_state()
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self._alert_manager = alert_manager

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
            preserved_positions = {
                pair: _PositionState(position.direction, position.entry_price, position.volume)
                for pair, position in self._state.positions.items()
            }
            self._state = _RiskState(as_of=now, positions=preserved_positions)
            self._state.daily_loss_alerted = False
            self._persist_state()

    def evaluate_signal(self, signal: StrategySignal, context: StrategyContext) -> RiskDecision:
        """
        Evaluate whether a proposed trade signal satisfies risk constraints.
        Returns a RiskDecision containing approval flag and recommended volume.
        """
        self.reset_if_new_day()
        limits = self._merge_limits(context.config.risk)

        existing_position = self._state.positions.get(context.pair)
        is_buy = signal.action == "buy"
        is_sell = signal.action == "sell"

        if not (is_buy or is_sell):
            return RiskDecision(False, f"Unsupported signal action '{signal.action}'.")

        closing_position = bool(existing_position and existing_position.direction == "long" and is_sell)

        if existing_position and existing_position.direction == "long" and is_buy:
            return RiskDecision(False, "Existing long position already open; awaiting exit signal.")

        if is_sell and not closing_position and existing_position is None:
            return RiskDecision(False, "Short selling not permitted by risk policy.")

        if self._state.daily_trades >= limits["max_daily_trades"]:
            return RiskDecision(False, "Daily trade limit reached.")

        pair_history = self._state.history_by_pair.setdefault(context.pair, _TradeHistory())
        if pair_history.last_trade_at:
            elapsed = datetime.now(tz=timezone.utc) - pair_history.last_trade_at
            min_gap = timedelta(minutes=limits["min_trade_gap_minutes"])
            if elapsed < min_gap:
                return RiskDecision(False, f"Minimum trade gap {min_gap} not met for {context.pair}.")

        if not closing_position:
            open_positions = len(self._state.positions)
            if existing_position is None and open_positions >= int(limits["max_positions"]):
                return RiskDecision(False, "Maximum concurrent positions reached.")

        volume = self._calculate_volume(signal, context, limits, existing_position, closing_position)
        if volume is None or volume <= 0:
            return RiskDecision(False, "Calculated trade volume is non-positive.")

        account_equity = self._estimate_account_equity(context)
        if account_equity <= 0:
            logger.debug("Account equity estimation unavailable; proceeding with caution.")
        else:
            max_loss_allowed = float(limits["max_daily_loss"]) * account_equity
            if self._state.daily_loss >= max_loss_allowed:
                self._trigger_daily_loss_alert(max_loss_allowed)
                return RiskDecision(False, "Maximum daily drawdown reached; halting trades.")

        entry_price = self._latest_close_price(context)
        if entry_price is None:
            return RiskDecision(False, "Unable to determine latest close price.")
        stop_loss_price, take_profit_price = self._derive_protective_prices(
            entry_price=entry_price,
            limits=limits,
            is_buy=is_buy,
            closing_position=closing_position,
        )

        direction = "long" if (is_buy and not closing_position) else (existing_position.direction if existing_position else "flat")

        return RiskDecision(
            True,
            "Signal approved.",
            volume=volume,
            position_fraction=float(limits["position_size"]),
            direction=direction,
            entry_price=entry_price,
            stop_loss_price=stop_loss_price,
            take_profit_price=take_profit_price,
            closing_position=closing_position,
        )

    def record_execution(
        self,
        pair: str,
        decision: RiskDecision,
        context: StrategyContext,
    ) -> float:
        """Record a trade execution to update daily counters and realised PnL."""
        self.reset_if_new_day()

        now = datetime.now(tz=timezone.utc)
        exit_price = decision.entry_price if decision.entry_price is not None else self._latest_close_price(context)
        if exit_price is None:
            logger.debug("Exit price unavailable for %s; defaulting to zero.", pair)
            exit_price = 0.0
        else:
            exit_price = float(exit_price)
        realised_pnl = 0.0

        if decision.closing_position:
            position = self._state.positions.get(pair)
            if position is None:
                logger.debug("No tracked position to close for %s; skipping PnL computation.", pair)
            else:
                volume = min(position.volume, float(decision.volume or position.volume))
                if position.direction == "long":
                    realised_pnl = (exit_price - position.entry_price) * volume
                else:
                    realised_pnl = (position.entry_price - exit_price) * volume

                if volume >= position.volume:
                    self._state.positions.pop(pair, None)
                else:
                    position.volume -= volume
                    self._state.positions[pair] = position
        else:
            entry_price = decision.entry_price if decision.entry_price is not None else self._latest_close_price(context)
            if entry_price is None:
                logger.debug("Entry price unavailable for %s when recording position; defaulting to zero.", pair)
                entry_price = 0.0
            else:
                entry_price = float(entry_price)
            volume = float(decision.volume or 0.0)
            if volume > 0:
                self._state.positions[pair] = _PositionState(
                    direction=decision.direction or "long",
                    entry_price=entry_price,
                    volume=volume,
                )

        self._state.daily_trades += 1
        if realised_pnl < 0:
            self._state.daily_loss += abs(realised_pnl)
        self._state.daily_realised_pnl += realised_pnl

        history = self._state.history_by_pair.setdefault(pair, _TradeHistory())
        history.last_trade_at = now
        history.trades_today += 1

        self._state.as_of = now
        self._persist_state()

        limits = self._merge_limits(context.config.risk)
        account_equity = self._estimate_account_equity(context)
        if account_equity > 0:
            max_loss_allowed = float(limits["max_daily_loss"]) * account_equity
            if self._state.daily_loss >= max_loss_allowed:
                self._trigger_daily_loss_alert(max_loss_allowed)

        return realised_pnl

    def status(self) -> Dict[str, Any]:
        """Return current risk metrics for monitoring."""
        return {
            "daily_trades": self._state.daily_trades,
            "daily_loss": self._state.daily_loss,
            "daily_realised_pnl": self._state.daily_realised_pnl,
            "open_positions": {
                pair: position.to_dict()
                for pair, position in self._state.positions.items()
            },
            "history": {
                pair: {
                    "last_trade_at": history.last_trade_at.isoformat() if history.last_trade_at else None,
                    "trades_today": history.trades_today,
                }
                for pair, history in self._state.history_by_pair.items()
            },
        }

    def open_positions(self) -> Dict[str, Dict[str, Any]]:
        """Expose a copy of the tracked open positions."""
        return {
            pair: position.to_dict()
            for pair, position in self._state.positions.items()
        }

    def _trigger_daily_loss_alert(self, limit_amount: float) -> None:
        """Emit a throttled alert when the daily loss limit is breached."""
        if self._state.daily_loss_alerted:
            return

        self._state.daily_loss_alerted = True
        self._persist_state()
        self._send_alert(
            event="risk.daily_loss_limit",
            message="Maximum daily drawdown reached; trading halted.",
            severity="ERROR",
            details={
                "daily_loss": round(self._state.daily_loss, 2),
                "limit": round(limit_amount, 2),
            },
            cooldown=300,
        )

    def _send_alert(
        self,
        event: str,
        message: str,
        *,
        severity: str = "INFO",
        details: Optional[Dict[str, Any]] = None,
        cooldown: Optional[float] = None,
    ) -> None:
        if self._alert_manager is None:
            return
        self._alert_manager.send(
            event=event,
            message=message,
            severity=severity,
            details=details,
            cooldown=cooldown,
        )

    @staticmethod
    def _merge_limits(risk_config: Dict[str, Any]) -> Dict[str, Any]:
        limits = RiskManager.DEFAULT_LIMITS.copy()
        for key, value in (risk_config or {}).items():
            if key in limits and value is not None:
                limits[key] = value
        return limits

    @staticmethod
    def _latest_close_price(context: StrategyContext) -> Optional[float]:
        """Return the most recent close price from the strategy context."""

        try:
            series = context.ohlcv["close"]
        except (KeyError, TypeError, AttributeError) as exc:
            logger.debug("Close series unavailable for %s: %s", getattr(context, "pair", "unknown"), exc)
            return None

        try:
            if hasattr(series, "iloc"):
                value = series.iloc[-1]
            else:
                value = series[-1]  # type: ignore[index]
            return float(value)
        except (TypeError, ValueError, IndexError) as exc:
            logger.debug("Failed to extract latest close for %s: %s", getattr(context, "pair", "unknown"), exc)
            return None

    @staticmethod
    def _calculate_volume(
        signal: StrategySignal,
        context: StrategyContext,
        limits: Dict[str, Any],
        existing_position: Optional[_PositionState],
        closing_position: bool,
    ) -> Optional[float]:
        """Derive trade volume based on balances and configured risk fraction."""
        balances = context.account_balances or {}

        close_price = RiskManager._latest_close_price(context)
        if close_price is None or close_price <= 0:
            logger.debug("Unable to determine close price for %s; skipping position sizing.", context.pair)
            return None

        position_fraction = float(limits["position_size"])

        pair = context.pair
        base_asset = pair[:-3]
        quote_asset = pair[-3:]

        if closing_position and existing_position is not None:
            return existing_position.volume

        try:
            if signal.action == "buy":
                quote_balance = float(balances.get(quote_asset, balances.get(f"Z{quote_asset}", 0.0)))
                position_value = quote_balance * position_fraction
                if position_value <= 0:
                    return None
                return position_value / close_price
            if signal.action == "sell":
                if existing_position is not None:
                    return existing_position.volume
                base_balance = float(balances.get(base_asset, balances.get(f"X{base_asset}", 0.0)))
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

    @staticmethod
    def _derive_protective_prices(
        entry_price: float,
        limits: Dict[str, Any],
        is_buy: bool,
        closing_position: bool,
    ) -> Tuple[Optional[float], Optional[float]]:
        """Compute stop loss and take profit price levels for a trade."""
        if closing_position:
            return None, None

        stop_loss_pct = limits.get("stop_loss")
        take_profit_pct = limits.get("take_profit")

        stop_loss_price: Optional[float] = None
        take_profit_price: Optional[float] = None

        try:
            if stop_loss_pct:
                stop_loss_pct = float(stop_loss_pct)
                if stop_loss_pct > 0:
                    stop_loss_price = entry_price * (1 - stop_loss_pct) if is_buy else entry_price * (1 + stop_loss_pct)
            if take_profit_pct:
                take_profit_pct = float(take_profit_pct)
                if take_profit_pct > 0:
                    take_profit_price = entry_price * (1 + take_profit_pct) if is_buy else entry_price * (1 - take_profit_pct)
        except (TypeError, ValueError):
            logger.debug("Invalid protective percentages configured; skipping stop/take profit calculations.")
            return None, None

        return stop_loss_price, take_profit_price

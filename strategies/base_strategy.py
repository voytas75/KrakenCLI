"""
Base abstractions for automated trading strategies.

Updates: v0.9.0 - 2025-11-11 - Introduced foundational strategy interfaces and dataclasses.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

import pandas as pd


@dataclass(slots=True)
class StrategySignal:
    """Structured representation of a strategy trading signal."""

    action: str
    confidence: float
    reason: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(tz=timezone.utc))

    def is_actionable(self, threshold: float = 0.0) -> bool:
        """Return True when the signal confidence clears a minimum threshold."""
        return self.confidence >= threshold


@dataclass(slots=True)
class StrategyConfig:
    """Configuration envelope for a trading strategy loaded from YAML."""

    name: str
    parameters: Dict[str, Any] = field(default_factory=dict)
    risk: Dict[str, Any] = field(default_factory=dict)
    timeframe: str = "1h"
    enabled: bool = True

    def get(self, key: str, default: Any = None) -> Any:
        """Helper for parameter lookups with precedence."""
        if key in self.parameters:
            return self.parameters[key]
        return self.risk.get(key, default)


@dataclass(slots=True)
class StrategyContext:
    """Runtime context supplied to strategies during signal generation."""

    pair: str
    timeframe: str
    ohlcv: pd.DataFrame
    account_balances: Dict[str, Any]
    open_positions: Dict[str, Any]
    config: StrategyConfig
    now: datetime = field(default_factory=lambda: datetime.now(tz=timezone.utc))


class BaseStrategy:
    """Abstract base strategy supplying hooks for concrete implementations."""

    signal_threshold: float = 0.0

    def __init__(self, config: StrategyConfig):
        self.config = config
        self._prepared: bool = False

    @property
    def name(self) -> str:
        """Return the strategy identifier."""
        return self.config.name

    def prepare(self) -> None:
        """Lazy hook for expensive initialisation (indicator caching, etc.)."""
        self._prepared = True

    def validate(self) -> None:
        """Validate configuration prior to trading."""
        if not self.config.enabled:
            raise ValueError(f"Strategy {self.name} is disabled.")

    def generate_signals(self, context: StrategyContext) -> List[StrategySignal]:
        """
        Produce trading signals for the supplied market context.

        Concrete strategies must override this method and return a list of
        actionable StrategySignal instances sorted by priority.
        """
        raise NotImplementedError("Strategy must implement generate_signals().")

    def required_indicators(self) -> Iterable[str]:
        """Return indicator names required for prepare-time preloading."""
        return []

    def supports_pair(self, pair: str) -> bool:
        """Override to restrict strategy support to specific trading pairs."""
        return True

    def on_order_fill(self, metadata: Dict[str, Any]) -> None:
        """Callback executed after an order fill (override as needed)."""
        return None

    def on_order_error(self, metadata: Dict[str, Any]) -> None:
        """Callback executed when order execution fails."""
        return None

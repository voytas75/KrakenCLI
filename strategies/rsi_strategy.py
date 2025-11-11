"""
Relative Strength Index (RSI) mean reversion strategy implementation.

Updates: v0.9.0 - 2025-11-11 - Added first automated trading strategy leveraging RSI signals.
"""

from __future__ import annotations

import logging
from typing import List

import pandas as pd

from indicators import TechnicalIndicators
from strategies.base_strategy import BaseStrategy, StrategyConfig, StrategyContext, StrategySignal

logger = logging.getLogger(__name__)


class RSIStrategy(BaseStrategy):
    """Mean-reversion RSI strategy: buy oversold, sell overbought."""

    def __init__(self, config: StrategyConfig):
        super().__init__(config)
        self.period: int = int(config.get("rsi_period", 14))
        self.oversold: float = float(config.get("oversold", 30))
        self.overbought: float = float(config.get("overbought", 70))
        self.cooldown_bars: int = int(config.get("cooldown_bars", 3))
        self.signal_threshold = float(config.get("signal_threshold", 0.55))

    def required_indicators(self):
        """RSI series required for execution."""
        return ["rsi"]

    def validate(self) -> None:
        """Ensure configuration bounds are sensible."""
        super().validate()
        if self.period <= 0:
            raise ValueError("RSI period must be positive.")
        if not (0 <= self.oversold < self.overbought <= 100):
            raise ValueError("RSI oversold/overbought levels must be within 0-100 and oversold < overbought.")

    def _calculate_rsi(self, close: pd.Series) -> pd.Series:
        """Calculate RSI while handling missing data."""
        if len(close) < self.period + 1:
            raise ValueError("Insufficient OHLCV data for RSI calculation.")
        rsi_values = TechnicalIndicators.rsi(close, period=self.period)
        return rsi_values.dropna()

    def generate_signals(self, context: StrategyContext) -> List[StrategySignal]:
        """Generate RSI-based buy/sell signals."""
        if "close" not in context.ohlcv.columns:
            raise KeyError("OHLCV dataframe must include a 'close' column.")

        try:
            rsi_series = self._calculate_rsi(context.ohlcv["close"])
        except ValueError as exc:
            logger.debug("RSI strategy skipped due to data issue: %s", exc)
            return []

        if rsi_series.empty:
            logger.debug("RSI series empty for %s; skipping signal.", context.pair)
            return []

        latest_rsi = rsi_series.iloc[-1]
        previous_rsi = rsi_series.iloc[-self.cooldown_bars :] if len(rsi_series) >= self.cooldown_bars else rsi_series

        signals: List[StrategySignal] = []

        def _confidence(value: float, target: float) -> float:
            distance = abs(target - value)
            return max(0.0, min(1.0, 1 - distance / 100))

        if latest_rsi <= self.oversold:
            confidence = _confidence(latest_rsi, self.oversold)
            if confidence >= self.signal_threshold and (previous_rsi <= self.oversold).all():
                signals.append(
                    StrategySignal(
                        action="buy",
                        confidence=confidence,
                        reason=f"RSI {latest_rsi:.2f} below oversold {self.oversold}",
                        metadata={
                            "indicator": "rsi",
                            "value": latest_rsi,
                            "threshold": self.oversold,
                            "timeframe": context.timeframe,
                        },
                    )
                )
        elif latest_rsi >= self.overbought:
            confidence = _confidence(latest_rsi, self.overbought)
            if confidence >= self.signal_threshold and (previous_rsi >= self.overbought).all():
                signals.append(
                    StrategySignal(
                        action="sell",
                        confidence=confidence,
                        reason=f"RSI {latest_rsi:.2f} above overbought {self.overbought}",
                        metadata={
                            "indicator": "rsi",
                            "value": latest_rsi,
                            "threshold": self.overbought,
                            "timeframe": context.timeframe,
                        },
                    )
                )

        return signals


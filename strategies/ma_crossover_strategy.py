"""
Moving average crossover trend-following strategy implementation.

Updates: v0.9.1 - 2025-11-11 - Added MA crossover strategy with configurable MA type.
"""

from __future__ import annotations

import logging
from typing import Callable, List

import pandas as pd

from indicators import TechnicalIndicators
from strategies.base_strategy import BaseStrategy, StrategyConfig, StrategyContext, StrategySignal

logger = logging.getLogger(__name__)


class MovingAverageCrossoverStrategy(BaseStrategy):
    """Trend strategy based on fast/slow moving average crossovers."""

    def __init__(self, config: StrategyConfig):
        super().__init__(config)
        self.fast_period: int = int(config.get("fast_period", 20))
        self.slow_period: int = int(config.get("slow_period", 50))
        self.ma_type: str = str(config.get("ma_type", "ema")).lower()
        self.signal_threshold = float(config.get("signal_threshold", 0.5))
        self.cooldown_bars: int = int(config.get("cooldown_bars", 2))

    def required_indicators(self):
        """Moving averages required for execution."""
        return ["moving_average"]

    def validate(self) -> None:
        """Ensure configuration bounds are sensible."""
        super().validate()
        if self.fast_period <= 0 or self.slow_period <= 0:
            raise ValueError("Moving average periods must be positive.")
        if self.fast_period >= self.slow_period:
            raise ValueError("Fast period must be less than slow period.")
        if self.ma_type not in {"sma", "ema"}:
            raise ValueError("ma_type must be 'sma' or 'ema'.")

    def _get_ma_function(self) -> Callable[[pd.Series, int], pd.Series]:
        """Return the moving average function based on configuration."""
        if self.ma_type == "sma":
            return TechnicalIndicators.sma
        return TechnicalIndicators.ema

    def _calculate_moving_averages(self, close: pd.Series) -> pd.DataFrame:
        """Compute fast and slow moving averages."""
        min_length = max(self.fast_period, self.slow_period) * 2
        if len(close) < min_length:
            raise ValueError("Insufficient OHLCV data for moving average calculation.")

        ma_fn = self._get_ma_function()
        fast_ma = ma_fn(close, self.fast_period).rename("fast_ma")
        slow_ma = ma_fn(close, self.slow_period).rename("slow_ma")
        df = pd.concat([fast_ma, slow_ma], axis=1).dropna()
        return df

    def generate_signals(self, context: StrategyContext) -> List[StrategySignal]:
        """Generate moving average crossover signals."""
        if "close" not in context.ohlcv.columns:
            raise KeyError("OHLCV dataframe must include a 'close' column.")

        try:
            ma_df = self._calculate_moving_averages(context.ohlcv["close"])
        except ValueError as exc:
            logger.debug("MA crossover strategy skipped due to data issue: %s", exc)
            return []

        if ma_df.empty:
            return []

        fast = ma_df["fast_ma"]
        slow = ma_df["slow_ma"]

        latest_fast = fast.iloc[-1]
        latest_slow = slow.iloc[-1]

        prev_fast = fast.iloc[-self.cooldown_bars :] if len(fast) >= self.cooldown_bars else fast
        prev_slow = slow.iloc[-self.cooldown_bars :] if len(slow) >= self.cooldown_bars else slow

        signals: List[StrategySignal] = []

        def _confidence(ratio: float) -> float:
            return max(0.0, min(1.0, abs(ratio) - 1.0 + self.signal_threshold))

        delta_ratio = latest_fast / latest_slow if latest_slow else 0.0

        # Bullish crossover when fast MA crosses above slow MA.
        if latest_fast > latest_slow and (prev_fast <= prev_slow).all():
            confidence = max(self.signal_threshold, _confidence(delta_ratio))
            if confidence >= self.signal_threshold:
                signals.append(
                    StrategySignal(
                        action="buy",
                        confidence=confidence,
                        reason=f"{self.ma_type.upper()} crossover bullish ({delta_ratio:.4f})",
                        metadata={
                            "indicator": f"{self.ma_type}_crossover",
                            "fast_ma": latest_fast,
                            "slow_ma": latest_slow,
                        },
                    )
                )

        # Bearish crossover when fast MA crosses below slow MA.
        if latest_fast < latest_slow and (prev_fast >= prev_slow).all():
            confidence = max(self.signal_threshold, _confidence(delta_ratio))
            if confidence >= self.signal_threshold:
                signals.append(
                    StrategySignal(
                        action="sell",
                        confidence=confidence,
                        reason=f"{self.ma_type.upper()} crossover bearish ({delta_ratio:.4f})",
                        metadata={
                            "indicator": f"{self.ma_type}_crossover",
                            "fast_ma": latest_fast,
                            "slow_ma": latest_slow,
                        },
                    )
                )

        return signals

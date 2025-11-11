"""
Moving Average Convergence Divergence (MACD) momentum strategy implementation.

Updates: v0.9.1 - 2025-11-11 - Added MACD crossover strategy for automated trading engine.
"""

from __future__ import annotations

import logging
from typing import List

import pandas as pd

from indicators import TechnicalIndicators
from strategies.base_strategy import BaseStrategy, StrategyConfig, StrategyContext, StrategySignal

logger = logging.getLogger(__name__)


class MACDStrategy(BaseStrategy):
    """MACD crossover strategy: trade when MACD line crosses the signal line."""

    def __init__(self, config: StrategyConfig):
        super().__init__(config)
        self.fast_period: int = int(config.get("fast_period", 12))
        self.slow_period: int = int(config.get("slow_period", 26))
        self.signal_period: int = int(config.get("signal_period", 9))
        self.signal_threshold = float(config.get("signal_threshold", 0.55))
        self.cooldown_bars: int = int(config.get("cooldown_bars", 2))

    def required_indicators(self):
        """MACD values required for execution."""
        return ["macd"]

    def validate(self) -> None:
        """Ensure configuration bounds are sensible."""
        super().validate()
        if self.fast_period <= 0 or self.slow_period <= 0 or self.signal_period <= 0:
            raise ValueError("MACD periods must be positive.")
        if self.fast_period >= self.slow_period:
            raise ValueError("MACD fast period must be less than slow period.")

    def _calculate_macd(self, close: pd.Series) -> pd.DataFrame:
        """Calculate MACD series, ensuring sufficient data length."""
        min_length = max(self.fast_period, self.slow_period, self.signal_period) * 3
        if len(close) < min_length:
            raise ValueError("Insufficient OHLCV data for MACD calculation.")
        macd_df = TechnicalIndicators.macd(
            close,
            fast=self.fast_period,
            slow=self.slow_period,
            signal=self.signal_period,
        ).dropna()
        return macd_df

    def generate_signals(self, context: StrategyContext) -> List[StrategySignal]:
        """Generate MACD-based buy/sell signals."""
        if "close" not in context.ohlcv.columns:
            raise KeyError("OHLCV dataframe must include a 'close' column.")

        try:
            macd_df = self._calculate_macd(context.ohlcv["close"])
        except ValueError as exc:
            logger.debug("MACD strategy skipped due to data issue: %s", exc)
            return []

        if macd_df.empty:
            return []

        macd_line = macd_df["macd"]
        signal_line = macd_df["signal"]
        histogram = macd_df["hist"]

        latest_macd = macd_line.iloc[-1]
        latest_signal = signal_line.iloc[-1]
        latest_hist = histogram.iloc[-1]

        prev_macd = macd_line.iloc[-self.cooldown_bars :] if len(macd_line) >= self.cooldown_bars else macd_line
        prev_signal = signal_line.iloc[-self.cooldown_bars :] if len(signal_line) >= self.cooldown_bars else signal_line

        signals: List[StrategySignal] = []

        def _confidence(delta: float) -> float:
            return max(0.0, min(1.0, abs(delta)))

        # Bullish signal: MACD crosses above signal line and histogram positive.
        if latest_macd > latest_signal and (prev_macd <= prev_signal).all() and latest_hist >= 0:
            delta = latest_macd - latest_signal
            confidence = max(self.signal_threshold, _confidence(delta))
            if confidence >= self.signal_threshold:
                signals.append(
                    StrategySignal(
                        action="buy",
                        confidence=confidence,
                        reason=f"MACD crossover bullish (Δ={delta:.4f})",
                        metadata={
                            "indicator": "macd",
                            "macd": latest_macd,
                            "signal": latest_signal,
                            "hist": latest_hist,
                        },
                    )
                )

        # Bearish signal: MACD crosses below signal line and histogram negative.
        if latest_macd < latest_signal and (prev_macd >= prev_signal).all() and latest_hist <= 0:
            delta = latest_macd - latest_signal
            confidence = max(self.signal_threshold, _confidence(delta))
            if confidence >= self.signal_threshold:
                signals.append(
                    StrategySignal(
                        action="sell",
                        confidence=confidence,
                        reason=f"MACD crossover bearish (Δ={delta:.4f})",
                        metadata={
                            "indicator": "macd",
                            "macd": latest_macd,
                            "signal": latest_signal,
                            "hist": latest_hist,
                        },
                    )
                )

        return signals

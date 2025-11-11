"""
Technical indicator helpers with TA-Lib and pandas-ta fallbacks.

Updates: v0.9.0 - 2025-11-11 - Added core indicator calculations for automated strategies.
"""

from __future__ import annotations

import logging
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)

try:
    import talib  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    talib = None
    logger.debug("TA-Lib not available; falling back to pandas-ta when possible.")

try:
    import pandas_ta as pta  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    pta = None
    logger.debug("pandas-ta not available; limited indicator support.")


class TechnicalIndicators:
    """Collection of stateless indicator calculations."""

    @staticmethod
    def _validate_series(series: pd.Series, name: str) -> None:
        if not isinstance(series, pd.Series):
            raise TypeError(f"{name} input must be a pandas Series.")
        if series.empty:
            raise ValueError(f"{name} series must contain data.")

    @staticmethod
    def rsi(close: pd.Series, period: int = 14) -> pd.Series:
        """Return Relative Strength Index values."""
        TechnicalIndicators._validate_series(close, "RSI close")
        if talib is not None:
            return pd.Series(talib.RSI(close.values, timeperiod=period), index=close.index)
        if pta is not None:
            return pta.rsi(close, length=period)
        raise ImportError("Neither TA-Lib nor pandas-ta is available for RSI calculation.")

    @staticmethod
    def macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
        """Return MACD line, signal line, and histogram."""
        TechnicalIndicators._validate_series(close, "MACD close")
        if talib is not None:
            macd_line, signal_line, hist = talib.MACD(
                close.values,
                fastperiod=fast,
                slowperiod=slow,
                signalperiod=signal,
            )
            return pd.DataFrame(
                {
                    "macd": macd_line,
                    "signal": signal_line,
                    "hist": hist,
                },
                index=close.index,
            )
        if pta is not None:
            macd_df = pta.macd(close, fast=fast, slow=slow, signal=signal)
            return macd_df.rename(columns={"MACD_12_26_9": "macd", "MACDs_12_26_9": "signal", "MACDh_12_26_9": "hist"})
        raise ImportError("Neither TA-Lib nor pandas-ta is available for MACD calculation.")

    @staticmethod
    def sma(close: pd.Series, period: int = 20) -> pd.Series:
        """Return simple moving average values."""
        TechnicalIndicators._validate_series(close, "SMA close")
        if talib is not None:
            return pd.Series(talib.SMA(close.values, timeperiod=period), index=close.index, name=f"sma_{period}")
        return close.rolling(window=period, min_periods=period).mean().rename(f"sma_{period}")

    @staticmethod
    def ema(close: pd.Series, period: int = 20) -> pd.Series:
        """Return exponential moving average values."""
        TechnicalIndicators._validate_series(close, "EMA close")
        if talib is not None:
            return pd.Series(talib.EMA(close.values, timeperiod=period), index=close.index, name=f"ema_{period}")
        return close.ewm(span=period, adjust=False).mean().rename(f"ema_{period}")

    @staticmethod
    def bollinger(close: pd.Series, period: int = 20, stddev: float = 2.0) -> pd.DataFrame:
        """Return Bollinger Bands (upper, middle, lower)."""
        TechnicalIndicators._validate_series(close, "Bollinger close")
        if talib is not None:
            upper, middle, lower = talib.BBANDS(close.values, timeperiod=period, nbdevup=stddev, nbdevdn=stddev)
            return pd.DataFrame({"upper": upper, "middle": middle, "lower": lower}, index=close.index)
        if pta is not None:
            bands = pta.bbands(close, length=period, std=stddev)
            return bands.rename(columns={
                f"BBU_{period}_{stddev}": "upper",
                f"BBM_{period}_{stddev}": "middle",
                f"BBL_{period}_{stddev}": "lower",
            })
        rolling_mean = close.rolling(window=period, min_periods=period).mean()
        rolling_std = close.rolling(window=period, min_periods=period).std()
        upper = rolling_mean + stddev * rolling_std
        lower = rolling_mean - stddev * rolling_std
        return pd.DataFrame({"upper": upper, "middle": rolling_mean, "lower": lower}, index=close.index)

    @staticmethod
    def atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
        """Return Average True Range values."""
        for name, series in (("ATR high", high), ("ATR low", low), ("ATR close", close)):
            TechnicalIndicators._validate_series(series, name)
        if talib is not None:
            return pd.Series(
                talib.ATR(high.values, low.values, close.values, timeperiod=period),
                index=close.index,
                name=f"atr_{period}",
            )
        true_range = pd.concat(
            [
                high - low,
                (high - close.shift(1)).abs(),
                (low - close.shift(1)).abs(),
            ],
            axis=1,
        )
        tr = true_range.max(axis=1)
        return tr.rolling(window=period, min_periods=period).mean().rename(f"atr_{period}")


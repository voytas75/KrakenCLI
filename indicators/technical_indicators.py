"""
Technical indicator helpers with TA-Lib and pure-Python fallbacks.

Updates:
    v0.9.0 - 2025-11-11 - Added core indicator calculations for automated strategies.
    v0.9.1 - 2025-11-11 - Added pure-Python RSI and MACD fallbacks to avoid hard dependency on pandas-ta.
"""

from __future__ import annotations

import logging

import pandas as pd

logger = logging.getLogger(__name__)

try:
    import talib  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    talib = None
    logger.debug("TA-Lib not available; falling back to pure-Python indicators.")

try:
    import pandas_ta as pta  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    pta = None
    logger.debug("pandas-ta not available; using built-in indicator implementations.")


class TechnicalIndicators:
    """Collection of stateless indicator calculations."""

    @staticmethod
    def _validate_series(series: pd.Series, name: str) -> None:
        if not isinstance(series, pd.Series):
            raise TypeError(f"{name} input must be a pandas Series.")
        if series.empty:
            raise ValueError(f"{name} series must contain data.")

    @staticmethod
    def _wilder_ewm(series: pd.Series, period: int) -> pd.Series:
        """Wilder's exponential moving average (alpha = 1/period)."""
        return series.ewm(alpha=1 / period, adjust=False).mean()

    @staticmethod
    def _rsi_manual(close: pd.Series, period: int) -> pd.Series:
        """Pure-Python RSI based on Wilder's smoothing."""
        delta = close.diff()
        gain = delta.clip(lower=0.0)
        loss = -delta.clip(upper=0.0)

        avg_gain = TechnicalIndicators._wilder_ewm(gain, period)
        avg_loss = TechnicalIndicators._wilder_ewm(loss, period)

        rs = avg_gain / avg_loss.replace(to_replace=0.0, value=pd.NA)
        rsi = 100 - (100 / (1 + rs))

        rsi = rsi.where(avg_loss > 0, 100.0)
        rsi = rsi.where(avg_gain > 0, 0.0)
        rsi = rsi.where((avg_gain > 0) | (avg_loss > 0), 50.0)

        return rsi.fillna(50.0).rename("rsi")

    @staticmethod
    def rsi(close: pd.Series, period: int = 14) -> pd.Series:
        """Return Relative Strength Index values."""
        TechnicalIndicators._validate_series(close, "RSI close")
        if talib is not None:
            return pd.Series(talib.RSI(close.values, timeperiod=period), index=close.index, name="rsi")
        if pta is not None:
            return pta.rsi(close, length=period).rename("rsi")
        return TechnicalIndicators._rsi_manual(close, period)

    @staticmethod
    def _macd_manual(close: pd.Series, fast: int, slow: int, signal: int) -> pd.DataFrame:
        """Pure-Python MACD implementation using EMA calculations."""
        ema_fast = TechnicalIndicators.ema(close, fast)
        ema_slow = TechnicalIndicators.ema(close, slow)
        macd_line = (ema_fast - ema_slow).rename("macd")
        signal_line = macd_line.ewm(span=signal, adjust=False).mean().rename("signal")
        hist = (macd_line - signal_line).rename("hist")
        return pd.concat([macd_line, signal_line, hist], axis=1)

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
        return TechnicalIndicators._macd_manual(close, fast, slow, signal)

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

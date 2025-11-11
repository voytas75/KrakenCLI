"""
Strategy package initialization.

Updates:
    v0.9.0 - 2025-11-11 - Added automated trading strategy package scaffolding.
    v0.9.1 - 2025-11-11 - Exposed MACD and moving average crossover strategies.
"""

from strategies.base_strategy import BaseStrategy, StrategyConfig, StrategySignal, StrategyContext
from strategies.macd_strategy import MACDStrategy
from strategies.ma_crossover_strategy import MovingAverageCrossoverStrategy
from strategies.rsi_strategy import RSIStrategy
from strategies.strategy_manager import StrategyManager

__all__ = [
    "BaseStrategy",
    "StrategyConfig",
    "StrategySignal",
    "StrategyContext",
    "MACDStrategy",
    "MovingAverageCrossoverStrategy",
    "RSIStrategy",
    "StrategyManager",
]

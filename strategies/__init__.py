"""
Strategy package initialization.

Updates: v0.9.0 - 2025-11-11 - Added automated trading strategy package scaffolding.
"""

from strategies.base_strategy import BaseStrategy, StrategyConfig, StrategySignal, StrategyContext
from strategies.rsi_strategy import RSIStrategy
from strategies.strategy_manager import StrategyManager

__all__ = [
    "BaseStrategy",
    "StrategyConfig",
    "StrategySignal",
    "StrategyContext",
    "RSIStrategy",
    "StrategyManager",
]

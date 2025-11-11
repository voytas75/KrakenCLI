"""
Strategy manager responsible for loading YAML configs and instantiating strategies.

Updates:
    v0.9.0 - 2025-11-11 - Added configurable strategy management and factory utilities.
    v0.9.1 - 2025-11-11 - Registered MACD and moving average crossover strategies.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Type

import yaml

from strategies.base_strategy import BaseStrategy, StrategyConfig
from strategies.macd_strategy import MACDStrategy
from strategies.ma_crossover_strategy import MovingAverageCrossoverStrategy
from strategies.rsi_strategy import RSIStrategy

logger = logging.getLogger(__name__)

STRATEGY_REGISTRY: Dict[str, Type[BaseStrategy]] = {
    "rsi": RSIStrategy,
    "macd": MACDStrategy,
    "ma_crossover": MovingAverageCrossoverStrategy,
}


class StrategyManager:
    """Load and manage strategy configurations at runtime."""

    def __init__(self, config_path: Path):
        self.config_path = config_path
        self._configs: Dict[str, StrategyConfig] = {}
        self._instances: Dict[str, BaseStrategy] = {}

    def refresh(self) -> None:
        """Reload configurations from disk."""
        if not self.config_path.exists():
            raise FileNotFoundError(f"Strategy config file not found: {self.config_path}")

        with self.config_path.open("r", encoding="utf-8") as handle:
            payload = yaml.safe_load(handle) or {}

        strategies = payload.get("strategies", {})
        if not isinstance(strategies, dict):
            raise ValueError("Strategy configuration must provide a mapping under 'strategies'.")

        self._configs.clear()
        self._instances.clear()

        for key, config_data in strategies.items():
            if not isinstance(config_data, dict):
                logger.warning("Skipping invalid strategy entry for %s; expected mapping.", key)
                continue

            name = config_data.get("name") or key
            parameters = config_data.get("parameters", {})
            risk = config_data.get("risk", {})
            timeframe = config_data.get("timeframe") or config_data.get("parameters", {}).get("timeframe", "1h")
            enabled = bool(config_data.get("enabled", True))

            strategy_config = StrategyConfig(
                name=name,
                parameters=parameters,
                risk=risk,
                timeframe=timeframe,
                enabled=enabled,
            )
            self._configs[key] = strategy_config

    def available(self) -> Iterable[str]:
        """Return the keys for all configured strategies."""
        return self._configs.keys()

    def get_config(self, key: str) -> Optional[StrategyConfig]:
        """Return the strategy configuration for the supplied key."""
        return self._configs.get(key)

    def get_strategy(self, key: str) -> BaseStrategy:
        """Return a strategy instance (cached) for the supplied key."""
        if key not in STRATEGY_REGISTRY:
            raise KeyError(f"Strategy '{key}' is not registered.")
        if key not in self._configs:
            raise KeyError(f"Strategy '{key}' not loaded from configuration.")

        if key not in self._instances:
            strategy_cls = STRATEGY_REGISTRY[key]
            instance = strategy_cls(self._configs[key])
            instance.prepare()
            self._instances[key] = instance
        return self._instances[key]

    def get_active_strategies(self) -> List[BaseStrategy]:
        """Return all enabled strategies."""
        strategies: List[BaseStrategy] = []
        for key, config in self._configs.items():
            if not config.enabled:
                continue
            try:
                strategy = self.get_strategy(key)
                strategy.validate()
                strategies.append(strategy)
            except Exception as exc:
                logger.error("Failed to initialise strategy %s: %s", key, exc)
        return strategies

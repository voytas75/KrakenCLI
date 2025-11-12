"""
CLI command registration helpers for KrakenCLI.

Each submodule exposes a ``register`` function that attaches a group of
related commands to the root Click group defined in ``kraken_cli.py``.
"""

from . import automation, export, portfolio, trading

__all__ = ["automation", "export", "portfolio", "trading"]

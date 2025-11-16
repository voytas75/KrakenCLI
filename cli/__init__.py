"""
CLI command registration helpers for KrakenCLI.

Each submodule exposes a ``register`` function that attaches a group of
related commands to the root Click group defined in ``kraken_cli.py``.
"""

# Do not eagerly import submodules here to avoid importing optional dependencies
# (e.g., pandas in analysis stack) when not needed.
__all__ = ["automation", "export", "portfolio", "trading", "patterns", "data"]

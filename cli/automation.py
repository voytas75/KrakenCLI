"""
Automated trading commands for KrakenCLI.

Encapsulates the auto-trading lifecycle commands and related helpers so the
entry module stays manageable.

Updates: v0.9.5 - 2025-11-15 - Resolve engine hooks via entry module for testability.
"""

from __future__ import annotations

import json
import logging
from importlib import import_module
from pathlib import Path
from typing import Any, Callable, Optional, Sequence

import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from alerts import AlertManager
from config import Config

logger = logging.getLogger(__name__)

# Paths used by automation commands (exported for reuse in entry module/tests).
AUTO_CONTROL_DIR = Path("logs/auto_trading")
RISK_STATE_FILE = AUTO_CONTROL_DIR / "risk_state.json"
AUTO_STATUS_FILE = AUTO_CONTROL_DIR / "status.json"

TradingEngine: Any = None
TradingEngineStatus: Any = None
StrategyManager: Any = None
RiskManager: Any = None
_AUTO_MODULES_LOADED = False
_AUTO_IMPORT_ERROR: Optional[Exception] = None


def _ensure_auto_modules() -> None:
    """Lazy-load automated trading modules and cache failures."""
    global TradingEngine, TradingEngineStatus, StrategyManager, RiskManager
    global _AUTO_MODULES_LOADED, _AUTO_IMPORT_ERROR

    if _AUTO_MODULES_LOADED:
        if _AUTO_IMPORT_ERROR is not None:
            raise _AUTO_IMPORT_ERROR
        return

    try:
        from engine import TradingEngine as _TradingEngine, TradingEngineStatus as _TradingEngineStatus
        from strategies import StrategyManager as _StrategyManager
        from risk import RiskManager as _RiskManager
    except Exception as exc:  # pragma: no cover - import guard
        _AUTO_IMPORT_ERROR = exc
        _AUTO_MODULES_LOADED = True
        raise

    TradingEngine = _TradingEngine
    TradingEngineStatus = _TradingEngineStatus
    StrategyManager = _StrategyManager
    RiskManager = _RiskManager
    _AUTO_IMPORT_ERROR = None
    _AUTO_MODULES_LOADED = True


def _format_auto_dependency_error(exc: Exception) -> str:
    """Return a user-friendly error message for missing auto trading deps."""
    message = str(exc)
    hint = "Install optional dependencies: pip install pandas ta-lib pandas-ta"
    if isinstance(exc, ModuleNotFoundError):
        return f"{message}. {hint}"
    return f"{message}. {hint}"


def _resolve_entry_function(name: str, fallback: Callable[..., Any]) -> Callable[..., Any]:
    """Return entry module attribute when present; otherwise use fallback."""

    try:
        entry_module = import_module("kraken_cli")
        candidate = getattr(entry_module, name, None)
        if callable(candidate):
            return candidate
    except Exception as exc:  # pragma: no cover - defensive import guard
        logger.debug("Failed to resolve %s from entry module: %s", name, exc)
    return fallback


def _create_strategy_manager(config_obj: Config):
    """Instantiate a strategy manager for the configured YAML path."""
    _ensure_auto_modules()
    return StrategyManager(config_obj.get_auto_trading_config_path())


def _create_trading_engine(
    ctx: click.Context,
    *,
    console: Console,
    config: Config,
    poll_interval: int,
    control_dir: Path,
    risk_state_path: Path,
) -> Optional[Any]:
    """Create a TradingEngine instance when prerequisites are available."""

    trader = ctx.obj.get("trader")
    portfolio = ctx.obj.get("portfolio")
    config_obj: Config = ctx.obj.get("config", config)
    alert_manager: Optional[AlertManager] = ctx.obj.get("alerts")

    if trader is None or portfolio is None:
        console.print("[red]❌ Automated trading requires authenticated trader access.[/red]")
        return None

    try:
        strategy_manager = _create_strategy_manager(config_obj)
        risk_manager = RiskManager(risk_state_path, alert_manager=alert_manager)
    except Exception as exc:
        console.print(f"[red]❌ Unable to initialise automated trading modules: {_format_auto_dependency_error(exc)}[/red]")
        return None

    engine = TradingEngine(
        trader=trader,
        portfolio_manager=portfolio,
        strategy_manager=strategy_manager,
        risk_manager=risk_manager,
        control_dir=control_dir,
        poll_interval=poll_interval,
        rate_limit=config_obj.get_rate_limit(),
        alert_manager=alert_manager,
    )
    return engine


def _display_auto_start_summary(
    console: Console,
    engine: Any,
    strategy_keys: Optional[Sequence[str]],
    pair_list: Optional[Sequence[str]],
    timeframe: Optional[str],
    interval: int,
    dry_run: bool,
) -> None:
    """Render a Rich summary describing the upcoming automated trading run."""

    def _summarise_config_section(
        payload: Optional[dict],
        preferred_keys: Sequence[str],
        *,
        max_items: int = 4,
    ) -> str:
        """Return a compact 'key=value' summary for parameters or risk settings."""
        if not payload:
            return "-"

        summary: list[str] = []
        seen: set[str] = set()

        def _append(key: str, value: Any) -> None:
            if value is None or key in seen:
                return
            seen.add(key)
            summary.append(f"{key}={value}")

        for key in preferred_keys:
            if key in payload:
                _append(key, payload[key])
                if len(summary) >= max_items:
                    break

        if len(summary) < max_items:
            for key, value in payload.items():
                if len(summary) >= max_items:
                    break
                _append(key, value)

        return ", ".join(summary) if summary else "-"

    strategy_manager = getattr(engine, "strategy_manager", None)
    if strategy_manager is None:
        console.print("[yellow]⚠️  Strategy manager unavailable; skipping summary.[/yellow]")
        return

    strategy_manager.refresh()
    available_keys = list(strategy_manager.available())
    if not available_keys:
        console.print("[yellow]⚠️  No strategies configured. Update auto_trading.yaml to enable automation.[/yellow]")
        return

    if strategy_keys:
        missing = [key for key in strategy_keys if key not in available_keys]
        if missing:
            console.print(f"[yellow]⚠️  Unknown strategy keys ignored: {', '.join(missing)}[/yellow]")

    table = Table(title="Auto Trading Plan", expand=False)
    table.add_column("Strategy", style="cyan")
    table.add_column("State", style="green")
    table.add_column("Timeframe", style="magenta")
    table.add_column("Configured Pairs", style="yellow")
    table.add_column("Parameters", style="white")
    table.add_column("Risk Levels", style="red")

    selected_keys = set(strategy_keys or available_keys)
    for key in available_keys:
        config_entry = strategy_manager.get_config(key)
        enabled = config_entry.enabled
        will_run = enabled and (not strategy_keys or key in selected_keys)
        status_text = "✅ Running" if will_run else ("⏸️ Disabled" if not enabled else "🚫 Skipped")

        configured_pairs = config_entry.parameters.get("pairs") or config_entry.parameters.get("symbols") or ["ETHUSD"]
        if isinstance(configured_pairs, str):
            pairs_display = configured_pairs
        elif isinstance(configured_pairs, (list, tuple, set)):
            pairs_display = ", ".join(str(item) for item in configured_pairs)
        else:
            pairs_display = str(configured_pairs)

        display_timeframe = timeframe or config_entry.timeframe
        parameter_snapshot = _summarise_config_section(
            config_entry.parameters,
            ("rsi_period", "oversold", "overbought", "signal_threshold", "cooldown_bars", "fast", "slow", "window"),
            max_items=4,
        )
        risk_snapshot = _summarise_config_section(
            config_entry.risk,
            ("position_size", "stop_loss", "take_profit", "max_daily_loss", "max_daily_trades", "min_trade_gap_minutes"),
            max_items=3,
        )

        table.add_row(
            config_entry.name or key,
            status_text,
            display_timeframe,
            pairs_display,
            parameter_snapshot,
            risk_snapshot,
        )

    effective_pairs = ", ".join(pair_list) if pair_list else "Strategy defaults"
    summary_panel = Panel(
        table,
        title="Automated Trading Summary",
        subtitle=(
            f"Mode: {'Dry-run' if dry_run else 'Live'}  •  Interval: {interval}s  •  Pairs: {effective_pairs}"
        ),
        border_style="blue",
    )
    console.print(summary_panel)


def register(
    cli_group: click.Group,
    *,
    console: Console,
    config: Config,
    control_dir_getter: Optional[Callable[[], Path]] = None,
    risk_state_getter: Optional[Callable[[], Path]] = None,
    status_file_getter: Optional[Callable[[], Path]] = None,
) -> None:
    """Register automated trading commands on the Click group."""

    def _control_dir() -> Path:
        if control_dir_getter:
            return control_dir_getter()
        return AUTO_CONTROL_DIR

    def _risk_state_file() -> Path:
        if risk_state_getter:
            return risk_state_getter()
        return RISK_STATE_FILE

    def _status_file() -> Path:
        if status_file_getter:
            return status_file_getter()
        return AUTO_STATUS_FILE

    @cli_group.command("auto-config")
    @click.option("--show/--no-show", default=False, help="Display the current auto trading YAML content.")
    @click.pass_context
    def auto_config(ctx: click.Context, show: bool) -> None:  # type: ignore[unused-ignore]
        """Display the auto trading configuration file path and optional contents."""
        config_obj: Config = ctx.obj.get("config", config)
        path = config_obj.get_auto_trading_config_path()
        console.print(f"ℹ️  Auto trading configuration file: [cyan]{path.resolve()}[/cyan]")

        if show:
            if not path.exists():
                console.print("[red]❌ Configuration file not found.[/red]")
                return
            content = path.read_text(encoding="utf-8")
            console.print(Panel(content, title="auto_trading.yaml"))

    @cli_group.command("auto-start")
    @click.option("--strategy", "-s", multiple=True, help="Strategy key(s) to run (default: all enabled).")
    @click.option("--pairs", "-p", help="Comma separated trading pairs override (e.g., ETHUSD,BTCUSD).")
    @click.option("--timeframe", "-t", help="Override timeframe for all strategies (e.g., 1h, 4h).")
    @click.option("--interval", "-i", type=int, default=300, help="Polling interval in seconds between cycles.")
    @click.option("--dry-run/--live", default=True, help="Execute in dry-run validation mode or live trading.")
    @click.option("--cycles", type=int, default=None, help="Limit the number of cycles (testing).")
    @click.pass_context
    def auto_start(  # type: ignore[unused-ignore]
        ctx: click.Context,
        strategy: Sequence[str],
        pairs: Optional[str],
        timeframe: Optional[str],
        interval: int,
        dry_run: bool,
        cycles: Optional[int],
    ) -> None:
        """Start the automated trading engine."""

        engine_factory = _resolve_entry_function("_create_trading_engine", _create_trading_engine)
        engine = engine_factory(
            ctx,
            console=console,
            config=config,
            poll_interval=interval,
            control_dir=_control_dir(),
            risk_state_path=_risk_state_file(),
        )
        if engine is None:
            return

        strategy_keys = list(strategy) if strategy else None
        pair_list = [item.strip() for item in pairs.split(",") if item.strip()] if pairs else None

        console.print(
            f"🚀 Starting auto trading engine | Dry-run: [cyan]{dry_run}[/cyan] | Interval: [cyan]{interval}s[/cyan]"
        )

        try:
            summary_renderer = _resolve_entry_function(
                "_display_auto_start_summary", _display_auto_start_summary
            )
            summary_renderer(
                console=console,
                engine=engine,
                strategy_keys=strategy_keys,
                pair_list=pair_list,
                timeframe=timeframe,
                interval=interval,
                dry_run=dry_run,
            )
            console.print(
                "ℹ️  To terminate: press [bold]Ctrl+C[/bold] in this session or run "
                "[cyan]python kraken_cli.py auto-stop[/cyan] from another terminal. "
                "The engine stops after the current cycle finishes (API calls and cool-down)."
            )
            engine.run_forever(
                strategy_keys=strategy_keys,
                dry_run=dry_run,
                poll_interval=interval,
                max_cycles=cycles,
                pairs_override=pair_list,
                timeframe_override=timeframe,
            )
        except KeyboardInterrupt:
            console.print("\n⚠️  Interrupted by user, requesting shutdown...")
            engine.request_stop()
        except FileNotFoundError as exc:
            console.print(f"[red]❌ Configuration error: {exc}[/red]")
            return
        except ValueError as exc:
            console.print(f"[red]❌ Strategy configuration invalid: {exc}[/red]")
            return
        except Exception as exc:  # pragma: no cover - defensive catch
            console.print(f"[red]❌ Engine encountered an error: {exc}[/red]")
            return
        finally:
            status = engine.status()
            console.print(f"✅ Engine stopped. Processed signals (last cycle): [green]{status.processed_signals}[/green]")

    @cli_group.command("auto-stop")
    def auto_stop() -> None:  # type: ignore[unused-ignore]
        """Signal a running auto trading engine to stop."""
        control_dir = _control_dir()
        control_dir.mkdir(parents=True, exist_ok=True)
        stop_file = control_dir / "stop.flag"
        stop_file.write_text("stop", encoding="utf-8")
        console.print("🛑 Stop request written. Engine will halt after the next cycle.")

    @cli_group.command("auto-status")
    def auto_status() -> None:  # type: ignore[unused-ignore]
        """Display the most recent auto trading engine status."""
        status_file = _status_file()
        if not status_file.exists():
            console.print("[yellow]ℹ️  No status file available. Start the engine first.[/yellow]")
            return

        try:
            payload = json.loads(status_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            console.print(f"[red]❌ Failed to read status: {exc}[/red]")
            return

        status_obj = None
        try:
            _ensure_auto_modules()
            status_obj = TradingEngineStatus.from_dict(payload)
        except Exception as exc:
            console.print(f"[yellow]⚠️  Automated trading modules unavailable: {_format_auto_dependency_error(exc)}[/yellow]")
            status_obj = None

        table = Table(title="Auto Trading Status")
        table.add_column("Metric", style="cyan")
        table.add_column("Value", style="green")

        if status_obj is not None:
            table.add_row("Running", "✅" if status_obj.running else "❌")
            table.add_row("Dry Run", "✅" if status_obj.dry_run else "❌")
            table.add_row(
                "Last Cycle",
                status_obj.last_cycle_at.isoformat() if status_obj.last_cycle_at else "N/A",
            )
            table.add_row("Processed Signals", str(status_obj.processed_signals))
            table.add_row("Active Strategies", ", ".join(status_obj.active_strategies) or "N/A")
            table.add_row("Active Pairs", ", ".join(status_obj.active_pairs) or "N/A")
            table.add_row("Last Error", status_obj.last_error or "None")
        else:
            table.add_row("Running", "✅" if payload.get("running") else "❌")
            table.add_row("Dry Run", "✅" if payload.get("dry_run", True) else "❌")
            table.add_row("Last Cycle", payload.get("last_cycle_at", "N/A"))
            table.add_row("Processed Signals", str(payload.get("processed_signals", 0)))
            table.add_row("Active Strategies", ", ".join(payload.get("active_strategies", [])) or "N/A")
            table.add_row("Active Pairs", ", ".join(payload.get("active_pairs", [])) or "N/A")
            table.add_row("Last Error", payload.get("last_error") or "None")

        alert_snapshot = AlertManager(config=config, console=console).status()
        table.add_row("Alerts Enabled", "✅" if alert_snapshot["enabled"] else "❌")
        table.add_row("Alert Cooldown", f"{int(alert_snapshot['cooldown_seconds'])}s")
        recent = alert_snapshot.get("recent_alerts", [])
        if recent:
            table.add_row("Recent Alerts", "")
            for entry in recent:
                table.add_row(
                    f"  {entry['timestamp']}",
                    f"{entry['severity']}: {entry['event']} - {entry['message']}",
                )

        console.print(table)

    @cli_group.command("risk-alerts")
    @click.option("--enable", is_flag=True, help="Enable alert notifications and persist the preference.")
    @click.option("--disable", is_flag=True, help="Disable alert notifications until re-enabled.")
    @click.option("--status", is_flag=True, help="Display current alert configuration status.")
    @click.pass_context
    def risk_alerts(  # type: ignore[unused-ignore]
        ctx: click.Context,
        enable: bool,
        disable: bool,
        status: bool,
    ) -> None:
        """Manage alert enablement and inspect configured channels."""
        alert_manager: Optional[AlertManager] = ctx.obj.get("alerts")
        if alert_manager is None:
            console.print("[red]❌ Alert manager unavailable; initialise configuration first.[/red]")
            return

        actions_selected = sum(1 for flag in (enable, disable, status) if flag)
        if actions_selected > 1:
            console.print("[red]❌ Choose only one flag: --enable, --disable, or --status.[/red]")
            return

        if enable:
            alert_manager.enable(source="cli")
            console.print("[green]✅ Alerts enabled.[/green]")
            status = True
        elif disable:
            alert_manager.disable(source="cli")
            console.print("[yellow]⚠️  Alerts disabled.[/yellow]")
            status = True
        else:
            status = True

        if status:
            summary = alert_manager.status()
            table = Table(title="Alert Status", expand=False)
            table.add_column("Setting", style="cyan")
            table.add_column("Value", style="green")

            table.add_row("Enabled", "✅" if summary["enabled"] else "❌")
            channels = summary.get("channels", {})
            for name, active in channels.items():
                table.add_row(f"Channel: {name}", "✅" if active else "❌")
            table.add_row("State File", summary.get("state_path", "N/A"))
            console.print(table)
            logger.info("Alert status inspected (enabled=%s, channels=%s)", summary["enabled"], channels)

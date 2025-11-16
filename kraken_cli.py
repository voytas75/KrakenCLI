#!/usr/bin/env python3
"""
Kraken Pro Trading CLI Application
Professional cryptocurrency trading interface for Kraken exchange

Updates: v0.9.0 - 2025-11-11 - Added automated trading engine commands and integrations.
Updates: v0.9.3 - 2025-11-12 - Added risk alert management commands and logging integration.
Updates: v0.9.4 - 2025-11-12 - Added withdrawal and export management commands.
Updates: v0.9.5 - 2025-11-15 - Added Kraken system status check to status command.
Updates: v0.9.6 - 2025-11-15 - Surface raw balance API payload in debug mode.
Updates: v0.9.7 - 2025-11-15 - Display exact balance strings without rounding.
Updates: v0.9.8 - 2025-11-15 - Annotate special asset suffixes in balance table.
Updates: v0.9.9 - 2025-11-15 - Highlight zero-balance assets count in status output.
"""

import click
import importlib
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple, List

from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.pretty import Pretty
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table
import logging

# Add current directory to path for imports
sys.path.append(str(Path(__file__).parent))

from alerts import AlertManager
from config import Config
from api.kraken_client import KrakenAPIClient
from trading.trader import Trader
from portfolio.portfolio_manager import PortfolioManager
from utils.logger import setup_logging

from cli import automation as automation_commands
from cli import export as export_commands
from cli import portfolio as portfolio_commands
from cli import trading as trading_commands
from cli import patterns as patterns_commands
# Load environment variables
load_dotenv()

console = Console()
config = Config()
logger = logging.getLogger(__name__)

# Setup logging
setup_logging(log_level=config.log_level)

_MAX_RETRY_ATTEMPTS = config.get_retry_attempts()
_RETRY_INITIAL_DELAY = config.get_retry_initial_delay()
_RETRY_BACKOFF_FACTOR = config.get_retry_backoff()

EXPORT_OUTPUT_DIR = Path("logs/exports")
AUTO_CONTROL_DIR = Path("logs/auto_trading")
RISK_STATE_FILE = AUTO_CONTROL_DIR / "risk_state.json"
AUTO_STATUS_FILE = AUTO_CONTROL_DIR / "status.json"

_OPTIONAL_DEPENDENCIES: Tuple[Tuple[str, str, str], ...] = (
    ("pandas", "Required for automated trading engine and indicator calculations.", "pip install pandas"),
    ("pandas_ta", "Extends indicator coverage (optional).", "pip install pandas-ta"),
    ("talib", "Native TA-Lib acceleration (optional).", "pip install TA-Lib"),
    ("ta-lib", "Native TA-Lib acceleration (alias).", "pip install TA-Lib"),
)


def _get_active_log_level() -> str:
    """Return the currently configured logging level name."""
    level = logging.getLogger().getEffectiveLevel()
    return logging.getLevelName(level)


def _dependency_status(module_name: str) -> Tuple[bool, Optional[str]]:
    """Return availability status and optional error message for a module."""
    try:
        importlib.import_module(module_name)
        return True, None
    except Exception as exc:  # pragma: no cover - import errors vary by platform
        return False, str(exc)


def _render_diagnostics(console: Console, config_obj: Config) -> None:
    """Display environment and dependency diagnostics."""
    summary = Table(title="Diagnostics Summary", show_lines=False, expand=False)
    summary.add_column("Check", style="cyan", no_wrap=True)
    summary.add_column("Status", style="green")
    summary.add_column("Details", style="white")

    credentials_ok = config_obj.has_credentials()
    credentials_valid = config_obj.validate_credentials()

    summary.add_row(
        "API Credentials",
        "✅" if credentials_ok else "⚠️",
        "Configured" if credentials_ok else "Missing (.env or environment variables)",
    )
    summary.add_row(
        "Credential Format",
        "✅" if credentials_valid else ("⚠️" if credentials_ok else "ℹ️"),
        "Looks valid" if credentials_valid else "Key/secret length appears invalid",
    )
    summary.add_row(
        "Sandbox Mode",
        "✅" if config_obj.is_sandbox() else "ℹ️",
        "Sandbox enabled" if config_obj.is_sandbox() else "Live mode (ensure dry-run when testing)",
    )
    summary.add_row(
        "Public Rate Limit",
        "ℹ️",
        f"{config_obj.get_public_rate_limit():.2f} req/sec",
    )
    summary.add_row(
        "Private Rate Limit",
        "ℹ️",
        f"{config_obj.get_private_rate_limit_per_min():.2f} req/min",
    )
    env_path = Path(".env")
    summary.add_row(
        ".env File",
        "✅" if env_path.exists() else "⚠️",
        str(env_path.resolve()),
    )

    console.print(summary)

    deps_table = Table(title="Optional Dependencies", show_lines=False, expand=False)
    deps_table.add_column("Module", style="magenta")
    deps_table.add_column("Status", style="green")
    deps_table.add_column("Notes", style="white")
    deps_table.add_column("Install Hint", style="yellow")

    for module_name, description, hint in _OPTIONAL_DEPENDENCIES:
        available, error = _dependency_status(module_name)
        status = "✅ Available" if available else "⚠️ Missing"
        note = description if available else (error or description or description)
        install_hint = "-" if available else hint
        deps_table.add_row(module_name, status, note, install_hint)

    console.print(deps_table)

    missing_env_keys: List[str] = []
    required_vars = ["KRAKEN_API_KEY", "KRAKEN_API_SECRET"]
    optional_vars = [
        "KRAKEN_API_BASE_URL",
        "KRAKEN_PUBLIC_RATE_LIMIT",
        "KRAKEN_PRIVATE_RATE_LIMIT_PER_MIN",
    ]
    for key in required_vars:
        if not os.getenv(key):
            missing_env_keys.append(key)

    env_detail_lines: List[str] = []
    if missing_env_keys:
        env_detail_lines.append(
            f"• Missing critical environment variables: {', '.join(missing_env_keys)}"
        )
    else:
        env_detail_lines.append("• Required environment variables detected.")

    for key in optional_vars:
        if not os.getenv(key):
            env_detail_lines.append(f"• Optional tuning variable unset: {key}")

    export_dir_exists = EXPORT_OUTPUT_DIR.exists()
    export_dir_writable = False
    if export_dir_exists:
        try:
            test_file = EXPORT_OUTPUT_DIR / ".write_test"
            with test_file.open("w") as handle:
                handle.write("ok")
            test_file.unlink()
            export_dir_writable = True
        except OSError:
            export_dir_writable = False

    env_detail_lines.append(
        f"• Export directory: {EXPORT_OUTPUT_DIR} "
        f"({'writable' if export_dir_writable else 'create pending' if not export_dir_exists else 'not writable'})"
    )

    if not config_obj.is_sandbox():
        env_detail_lines.append(
            "• Sandbox disabled: enable dry-run or set KRAKEN_SANDBOX=true when testing."
        )

    console.print(
        Panel.fit(
            "\n".join(env_detail_lines),
            title="Environment Checks",
            border_style="blue",
        )
    )

    guidance = Panel.fit(
        "\n".join(
            [
                "[bold yellow]Next Steps[/bold yellow]",
                "• Install missing optional dependencies for full automation support.",
                "• Populate `.env` with API credentials if not already set.",
                "• Adjust `KRAKEN_PUBLIC_RATE_LIMIT` / `KRAKEN_PRIVATE_RATE_LIMIT_PER_MIN` as needed.",
            ]
        ),
        title="Guidance",
        border_style="yellow",
    )
    console.print(guidance)


def _convert_to_kraken_asset(currency_code: str) -> str:
    """Convert common currency codes to Kraken format"""
    # Common currency mappings
    conversions = {
        'BTC': 'XBT',  # Bitcoin uses XBT in Kraken
        'XBT': 'XBT',  # Already in Kraken format
        'ETH': 'XETH',  # Ethereum uses XETH in Kraken  
        'EUR': 'ZEUR',  # Euro
        'USD': 'ZUSD',  # US Dollar
        'GBP': 'ZGBP',  # British Pound
        'JPY': 'ZJPY',  # Japanese Yen
        'CAD': 'ZCAD',  # Canadian Dollar
        'CHF': 'ZCHF',  # Swiss Franc
        'ADA': 'ADA',   # Cardano (already in standard format)
        'DOT': 'DOT',   # Polkadot (already in standard format)
        'LINK': 'LINK', # Chainlink (already in standard format)
        'SC': 'SC',     # Siacoin (already in standard format)
    }

    return conversions.get(currency_code.upper(), currency_code.upper())


def _call_with_retries(action, description: str, display_label: Optional[str] = None) -> Any:
    """Invoke the provided callable with exponential backoff and Rich progress."""

    delay = _RETRY_INITIAL_DELAY
    last_error: Optional[Exception] = None
    display_label = display_label or description

    progress = Progress(
        SpinnerColumn(),
        TextColumn("{task.description}"),
        transient=True,
        console=console,
    )

    with progress:
        task_id = progress.add_task(f"{display_label}…", start=False)
        for attempt in range(1, _MAX_RETRY_ATTEMPTS + 1):
            progress.update(task_id, description=f"{display_label} (attempt {attempt}/{_MAX_RETRY_ATTEMPTS})")
            progress.start_task(task_id)
            try:
                result = action()
                progress.update(task_id, description=f"{display_label} (completed)")
                return result
            except KeyboardInterrupt:  # pragma: no cover - user interruption
                progress.stop_task(task_id)
                raise
            except Exception as exc:
                last_error = exc
                progress.update(task_id, description=f"{display_label} failed: {exc}")
                logger.warning(
                    "%s attempt %d/%d failed: %s",
                    description,
                    attempt,
                    _MAX_RETRY_ATTEMPTS,
                    exc,
                )
                if attempt >= _MAX_RETRY_ATTEMPTS:
                    break
                time.sleep(delay)
                delay *= _RETRY_BACKOFF_FACTOR

    if last_error:
        raise last_error

    return None


@click.group()
@click.pass_context  
def cli(ctx):
    """Kraken Pro Trading CLI - Professional cryptocurrency trading interface"""
    ctx.ensure_object(dict)
    ctx.obj['config'] = config
    ctx.obj['alerts'] = AlertManager(config=config, console=console)
    
    # Initialize API client if credentials are available
    if config.has_credentials():
        try:
            api_client = KrakenAPIClient(
                api_key=config.api_key,
                api_secret=config.api_secret,
                sandbox=config.sandbox
            )
            ctx.obj['api_client'] = api_client
        except Exception as e:
            # If API client creation fails, store None - commands will handle missing client
            ctx.obj['api_client'] = None
    else:
        # No credentials available
        ctx.obj['api_client'] = None
    
    # Initialize portfolio manager if API client is available
    try:
        if ctx.obj['api_client'] is not None:
            portfolio = PortfolioManager(api_client=ctx.obj['api_client'])
            ctx.obj['portfolio'] = portfolio
        else:
            ctx.obj['portfolio'] = None
    except Exception as e:
        # If portfolio creation fails, store None
        ctx.obj['portfolio'] = None
    
    # Initialize trader if API client is available
    try:
        if ctx.obj['api_client'] is not None:
            trader = Trader(api_client=ctx.obj['api_client'])
            ctx.obj['trader'] = trader
        else:
            ctx.obj['trader'] = None
    except Exception as e:
        # If trader creation fails, store None
        ctx.obj['trader'] = None

# Keep automation module paths aligned with entry module constants.
automation_commands.AUTO_CONTROL_DIR = AUTO_CONTROL_DIR
automation_commands.RISK_STATE_FILE = RISK_STATE_FILE
automation_commands.AUTO_STATUS_FILE = AUTO_STATUS_FILE

# Re-export automation helpers for integration tests and Click patching.
_create_trading_engine = automation_commands._create_trading_engine
_display_auto_start_summary = automation_commands._display_auto_start_summary

trading_commands.register(
    cli,
    console=console,
    config=config,
    call_with_retries=_call_with_retries,
)

portfolio_commands.register(
    cli,
    console=console,
    config=config,
    call_with_retries=_call_with_retries,
)

patterns_commands.register(
    cli,
    console=console,
    config=config,
    call_with_retries=_call_with_retries,
)

export_commands.register(
    cli,
    console=console,
    config=config,
    call_with_retries=_call_with_retries,
    export_output_dir=EXPORT_OUTPUT_DIR,
)

automation_commands.register(
    cli,
    console=console,
    config=config,
    control_dir_getter=lambda: AUTO_CONTROL_DIR,
    risk_state_getter=lambda: RISK_STATE_FILE,
    status_file_getter=lambda: AUTO_STATUS_FILE,
)

@cli.command()
@click.pass_context
def status(ctx):
    """Show account status and connectivity"""
    # Get API client from context, or create if not available
    api_client = ctx.obj.get('api_client')

    console.print(f"ℹ️  Current log level: [cyan]{_get_active_log_level()}[/cyan]")
    
    if api_client is None:
        # Check if API credentials are configured and create client
        if not config.has_credentials():
            console.print("[red]⚠️  API credentials not configured![/red]")
            console.print("[yellow]Please configure your Kraken API credentials in .env file[/yellow]")
            console.print("[yellow]See README.md for setup instructions[/yellow]")
            return
        
        try:
            api_client = KrakenAPIClient(
                api_key=config.api_key,
                api_secret=config.api_secret,
                sandbox=config.sandbox
            )
        except Exception as e:
            console.print(f"[red]❌ Failed to initialize API client: {e}[/red]")
            return
    
    try:
        console.print("[bold blue]🌐 Checking Kraken system status...[/bold blue]")

        try:
            system_status_payload = api_client.get_system_status()
        except Exception as status_error:
            console.print(f"[yellow]⚠️  Unable to retrieve system status: {status_error}[/yellow]")
        else:
            status_result = system_status_payload.get("result", {})
            status_value_raw = str(status_result.get("status", "unknown"))
            normalized_status = status_value_raw.replace("_", " ").strip()
            status_label = normalized_status.title() if normalized_status else "Unknown"
            status_icon_map = {
                "online": "✅",
                "operational": "✅",
                "cancel only": "⚠️",
                "post only": "⚠️",
                "maintenance": "⚠️",
                "degraded": "⚠️",
            }
            status_icon = status_icon_map.get(normalized_status.lower(), "ℹ️")

            status_table = Table(title="System Status", show_lines=False, expand=False)
            status_table.add_column("Metric", style="cyan", no_wrap=True)
            status_table.add_column("Value", style="green")
            status_table.add_row("Status", f"{status_icon} {status_label}")

            status_timestamp = status_result.get("timestamp")
            if status_timestamp:
                status_table.add_row("Updated", str(status_timestamp))

            status_message = status_result.get("message")
            if status_message:
                status_table.add_row("Message", str(status_message))

            console.print(status_table)

        console.print("[bold blue]🔌 Checking Kraken API connection...[/bold blue]")

        # Test connection
        time_info = api_client.get_server_time()
        balance = api_client.get_account_balance()
        
        console.print("[green]✅ Connection successful![/green]")
        # Get server time from result field (2025 API format: {"error": [], "result": {}})
        server_time = time_info.get('result', {})
        if 'unixtime' in server_time:
            console.print(f"🕐 Server time: {server_time['unixtime']}")
        elif 'time' in server_time:
            console.print(f"🕐 Server time: {server_time['time']}")
        else:
            console.print("🕐 Server time: Available")
        # Check balance from result field (2025 API format)
        if logging.getLogger().getEffectiveLevel() <= logging.DEBUG:
            console.print(
                Panel.fit(
                    Pretty(balance, expand_all=True),
                    title="Balance API Raw Response",
                    border_style="dim",
                )
            )

        balance_data = balance.get('result', {})

        def _is_zero_balance(candidate: Any) -> bool:
            """Return True when the provided balance value is empty or zero."""

            try:
                normalized = str(candidate).strip()
                if not normalized:
                    return True
                return float(normalized) == 0.0
            except (ValueError, TypeError):
                return False

        total_assets = len(balance_data) if balance_data else 0
        zero_assets = sum(1 for amount in balance_data.values() if _is_zero_balance(amount)) if balance_data else 0

        console.print(f"💰 Account balances retrieved: {total_assets} ({zero_assets})")
        
        if balance_data:
            table = Table(title="Account Balances")
            table.add_column("Asset", style="cyan")
            table.add_column("Balance", style="green")
            table.add_column("Note", style="yellow")

            suffix_notes = {
                ".B": "Yield-bearing balance",
                ".F": "Kraken Rewards balance",
                ".T": "Tokenized asset",
                ".S": "Staked balance",
                ".M": "Opt-in rewards balance",
            }

            for asset, balance_str in balance_data.items():
                # Kraken returns balances as strings, not dictionaries; display raw value for clarity
                if float(balance_str) > 0:
                    note = ""
                    display_asset = asset
                    for suffix, message in suffix_notes.items():
                        if asset.endswith(suffix):
                            note = message
                            display_asset = asset[:-len(suffix)] or asset
                            break
                    table.add_row(
                        display_asset,
                        str(balance_str),
                        note
                    )
            
            console.print(table)
            
    except Exception as e:
        console.print(f"[red]❌ Connection failed: {str(e)}[/red]")
        console.print("[yellow]Please check your API credentials and internet connection[/yellow]")

@cli.command()
@click.argument('base', required=False)
@click.argument('quote', required=False)
@click.option('--pair', '-p', help='Trading pair (e.g., XBTUSD, ETHUSD, ADAUSD)')
@click.pass_context
def ticker(ctx, base, quote, pair):
    """Show ticker information for a trading pair
    
    Usage:
        kraken_cli.py ticker BTC EUR    # Bitcoin in Euro
        kraken_cli.py ticker XBT USD    # Bitcoin in USD  
        kraken_cli.py ticker --pair XBTUSD  # Direct Kraken pair format
        kraken_cli.py ticker --pair ETHUSD  # ETH/USD pair
    """
    # Get API client from context, or create if not available
    api_client = ctx.obj.get('api_client')
    
    if api_client is None:
        # Check if API credentials are configured and create client
        if not config.has_credentials():
            console.print("[red]⚠️  API credentials not configured![/red]")
            console.print("[yellow]Please configure your Kraken API credentials in .env file[/yellow]")
            console.print("[yellow]See README.md for setup instructions[/yellow]")
            return
        
        try:
            api_client = KrakenAPIClient(
                api_key=config.api_key,
                api_secret=config.api_secret,
                sandbox=config.sandbox
            )
        except Exception as e:
            console.print(f"[red]❌ Failed to initialize API client: {e}[/red]")
            return
    
    # Determine the trading pair
    if pair:
        trading_pair = pair.upper()
    elif base and quote:
        # Convert common currency codes to Kraken format
        base_code = _convert_to_kraken_asset(base.upper())
        quote_code = _convert_to_kraken_asset(quote.upper())
        trading_pair = f"{base_code}{quote_code}"
    else:
        # Default to Bitcoin/USD
        trading_pair = "XBTUSD"
    
    try:
        console.print(f"[bold blue]📊 Fetching ticker data for {trading_pair}...[/bold blue]")
        
        ticker_data = api_client.get_ticker(trading_pair)
        
        # Get ticker data from result field (2025 API format)
        result_data = ticker_data.get('result', {})
        
        # Find the actual pair data - Kraken may return data with different keys
        pair_data = None
        actual_pair_key = None
        
        # First, try exact match
        if trading_pair in result_data:
            pair_data = result_data[trading_pair]
            actual_pair_key = trading_pair
        else:
            # Look for alternate formats
            # Common conversions: XBTUSD -> XXBTZUSD, ETHUSD -> XETHZUSD
            alt_formats = []
            
            # Handle different pair formats
            if trading_pair == 'XBTUSD':
                alt_formats = ['XXBTZUSD', 'XXBTZUSD']
            elif trading_pair == 'ETHUSD':
                alt_formats = ['XETHZUSD', 'XETHZUSD']
            elif 'XBT' in trading_pair and 'USD' in trading_pair:
                alt_formats = [trading_pair.replace('XBT', 'XXBT').replace('USD', 'ZUSD'), 
                              trading_pair.replace('XBT', 'XXBTZ').replace('USD', 'ZUSD')]
            elif 'XETH' in trading_pair and 'USD' in trading_pair:
                alt_formats = [trading_pair.replace('XETH', 'XETH').replace('USD', 'ZUSD'),
                              trading_pair.replace('XETH', 'XETHZ').replace('USD', 'ZUSD')]
            
            # Try alternate formats
            for alt_format in alt_formats:
                if alt_format in result_data:
                    pair_data = result_data[alt_format]
                    actual_pair_key = alt_format
                    break
            
            # If still not found, list available pairs for debugging
            if pair_data is None:
                available_pairs = list(result_data.keys())
                console.print(f"[red]❌ No ticker data found for {trading_pair}[/red]")
                console.print(f"[yellow]Available pairs: {len(available_pairs)} pairs found[/yellow]")
                if len(available_pairs) <= 10:  # Only show if reasonable number
                    console.print(f"[dim]Sample pairs: {', '.join(available_pairs[:5])}[/dim]")
                console.print("[yellow]💡 Try a different pair or check available pairs[/yellow]")
                return
        
        if pair_data and actual_pair_key:
            # Extract data from API response
            current_price = float(pair_data.get('c', ['0', ''])[0] or 0)
            vwap_24h = float(pair_data.get('p', ['0', ''])[1] or 0)  # VWAP is index 1
            high_24h = pair_data.get('h', ['0', ''])[0]
            low_24h = pair_data.get('l', ['0', ''])[0]
            volume_24h = pair_data.get('v', ['0', ''])[0]
            bid_price = pair_data.get('b', ['0', ''])[0]
            ask_price = pair_data.get('a', ['0', ''])[0]
            
            # Calculate 24h percentage change using VWAP
            if current_price > 0 and vwap_24h > 0:
                percentage_change = ((current_price - vwap_24h) / vwap_24h) * 100
                if percentage_change >= 0:
                    change_color = "green"
                    change_sign = "+"
                else:
                    change_color = "red"
                    change_sign = ""
                change_text = f"{change_sign}{percentage_change:.2f}%"
            else:
                change_color = "yellow"
                change_text = "N/A"
            
            panel = Panel(
                f"[bold cyan]{trading_pair}[/bold cyan]\n"
                f"Last Price: [green]{current_price:,.8f}[/green]\n"
                f"24h Change: [{change_color}]{change_text}[/{change_color}]\n"
                f"24h High: [green]{high_24h}[/green]\n"
                f"24h Low: [red]{low_24h}[/red]\n"
                f"Volume 24h: [blue]{volume_24h}[/blue]\n"
                f"Bid: [green]{bid_price}[/green]\n"
                f"Ask: [red]{ask_price}[/red]",
                title="Market Data",
                border_style="blue"
            )
            console.print(panel)
            
    except Exception as e:
        console.print(f"[red]❌ Error fetching ticker: {str(e)}[/red]")


@cli.command()
def config_setup():
    """Setup configuration interactively"""
    console.print("[bold blue]🛠️  Kraken API Configuration Setup[/bold blue]")
    
    api_key = click.prompt('Enter your Kraken API key', type=str, hide_input=True)
    api_secret = click.prompt('Enter your Kraken API secret', type=str, hide_input=True)
    sandbox = click.confirm('Use Kraken sandbox (test) environment?', default=False)
    
    # Save to .env file
    env_path = Path(__file__).parent / '.env'
    with open(env_path, 'w') as f:
        f.write(f"KRAKEN_API_KEY={api_key}\n")
        f.write(f"KRAKEN_API_SECRET={api_secret}\n")
        f.write(f"KRAKEN_SANDBOX={sandbox}\n")
    
    console.print("[green]✅ Configuration saved to .env file[/green]")
    console.print("[yellow]⚠️  Keep your API credentials secure and never share them![/yellow]")

@cli.command()
@click.option(
    "--diagnostics",
    is_flag=True,
    help="Display environment and optional dependency checks.",
)
@click.pass_context
def info(ctx: click.Context, diagnostics: bool):
    """Show application information and warnings"""
    if diagnostics:
        _render_diagnostics(console, config)
        return

    log_level_line = f"[bold white]Current Log Level:[/bold white] [cyan]{_get_active_log_level()}[/cyan]"
    panel = Panel.fit(
        "[bold cyan]Kraken Pro Trading CLI[/bold cyan]\n\n"
        f"{log_level_line}\n\n"
        "[bold yellow]⚠️  IMPORTANT RISK WARNINGS:[/bold yellow]\n"
        "• Cryptocurrency trading involves substantial risk\n"
        "• Past performance does not guarantee future results\n"
        "• Only trade with money you can afford to lose\n"
        "• This tool is for educational purposes\n\n"
        "[bold green]Features:[/bold green]\n"
        "• Real-time market data\n"
        "• Order placement and management\n"
        "• Portfolio tracking\n"
        "• Trade history\n"
        "• Risk management tools\n\n"
        "[bold blue]Supported Trading Pairs:[/bold blue]\n"
        "• XBTUSD (Bitcoin/USD)\n"
        "• ETHUSD (Ethereum/USD)\n"
        "• ADAUSD (Cardano/USD)\n"
        "• And many more...\n\n"
        "[yellow]For support, visit: https://support.kraken.com[/yellow]",
        title="Application Information"
    )
    console.print(panel)

if __name__ == '__main__':
    cli()

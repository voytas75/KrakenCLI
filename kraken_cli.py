#!/usr/bin/env python3
"""
Kraken Pro Trading CLI Application
Professional cryptocurrency trading interface for Kraken exchange
"""

import click
import os
import sys
import time
from pathlib import Path
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import print as rprint
from dotenv import load_dotenv
import logging

# Add current directory to path for imports
sys.path.append(str(Path(__file__).parent))

from config import Config
from api.kraken_client import KrakenAPIClient
from trading.trader import Trader
from portfolio.portfolio_manager import PortfolioManager
from utils.logger import setup_logging
from utils.helpers import format_currency, format_percentage

# Load environment variables
load_dotenv()

console = Console()
config = Config()

# Setup logging
setup_logging()

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

@click.group()
@click.pass_context
def cli(ctx):
    """Kraken Pro Trading CLI - Professional cryptocurrency trading interface"""
    ctx.ensure_object(dict)
    
    # Check if API credentials are configured
    if not config.has_credentials():
        console.print("[red]⚠️  API credentials not configured![/red]")
        console.print("[yellow]Please configure your Kraken API credentials in .env file[/yellow]")
        console.print("[yellow]See README.md for setup instructions[/yellow]")
        ctx.exit(1)
    
    # Initialize API client
    ctx.obj['api_client'] = KrakenAPIClient(
        api_key=config.api_key,
        api_secret=config.api_secret,
        sandbox=config.sandbox
    )
    ctx.obj['trader'] = Trader(ctx.obj['api_client'])
    ctx.obj['portfolio'] = PortfolioManager(ctx.obj['api_client'])

@cli.command()
@click.pass_context
def status(ctx):
    """Show account status and connectivity"""
    api_client = ctx.obj['api_client']
    
    try:
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
        balance_data = balance.get('result', {})
        console.print(f"💰 Account balances retrieved: {len(balance_data) if balance_data else 0}")
        
        if balance_data:
            table = Table(title="Account Balances")
            table.add_column("Asset", style="cyan")
            table.add_column("Balance", style="green")
            
            for asset, balance_str in balance_data.items():
                # Kraken returns balances as strings, not dictionaries
                if float(balance_str) > 0:
                    table.add_row(
                        asset,
                        format_currency(balance_str)
                    )
            
            console.print(table)
            
    except Exception as e:
        console.print(f"[red]❌ Connection failed: {str(e)}[/red]")
        console.print("[yellow]Please check your API credentials and internet connection[/yellow]")

@cli.command()
@click.argument('base', required=False)
@click.argument('quote', required=False)
@click.option('--pair', '-p', help='Trading pair in Kraken format (e.g., XBTUSD, ETHUSD)')
@click.pass_context
def ticker(ctx, base, quote, pair):
    """Show ticker information for a trading pair
    
    Usage:
        kraken_cli.py ticker BTC EUR    # Bitcoin in Euro
        kraken_cli.py ticker XBT USD    # Bitcoin in USD  
        kraken_cli.py ticker --pair XBTUSD  # Direct Kraken pair format
    """
    api_client = ctx.obj['api_client']
    
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
        pair_data = result_data.get(trading_pair, {})
        
        if pair_data:
            panel = Panel(
                f"[bold cyan]{trading_pair}[/bold cyan]\n"
                f"Last Price: [green]{pair_data.get('c', ['0', ''])[0]}[/green]\n"
                f"24h Change: [yellow]{pair_data.get('p', ['0', ''])[0]}%[/yellow]\n"
                f"24h High: [green]{pair_data.get('h', ['0', ''])[0]}[/green]\n"
                f"24h Low: [red]{pair_data.get('l', ['0', ''])[0]}[/red]\n"
                f"Volume 24h: [blue]{pair_data.get('v', ['0', ''])[0]}[/blue]\n"
                f"Bid: [green]{pair_data.get('b', ['0', ''])[0]}[/green]\n"
                f"Ask: [red]{pair_data.get('a', ['0', ''])[0]}[/red]",
                title="Market Data",
                border_style="blue"
            )
            console.print(panel)
        else:
            console.print(f"[red]❌ No ticker data found for {trading_pair}[/red]")
            console.print("[yellow]💡 Try a different pair or check available trading pairs[/yellow]")
            
    except Exception as e:
        console.print(f"[red]❌ Error fetching ticker: {str(e)}[/red]")

@cli.command()
@click.option('--pair', '-p', required=True, help='Trading pair (e.g., XBTUSD)')
@click.option('--side', '-s', type=click.Choice(['buy', 'sell']), required=True, help='Order side')
@click.option('--order-type', '-t', type=click.Choice(['market', 'limit', 'stop-loss', 'take-profit']), 
              default='market', help='Order type')
@click.option('--volume', '-v', required=True, type=float, help='Order volume')
@click.option('--price', help='Limit price (required for limit orders)')
@click.option('--price2', help='Secondary price (for stop-loss-profit orders)')
@click.option('--validate', is_flag=True, help='Validate order only, do not place')
@click.pass_context
def order(ctx, pair, side, order_type, volume, price, price2, validate):
    """Place a new order"""
    trader = ctx.obj['trader']
    
    try:
        console.print(f"[bold blue]📝 Placing {side} order for {pair}...[/bold blue]")
        
        # Validate order parameters
        if order_type in ['limit', 'take-profit'] and not price:
            console.print("[red]❌ Limit price required for limit/take-profit orders[/red]")
            return
        
        if order_type in ['stop-loss', 'take-profit'] and not price2:
            console.print("[red]❌ Secondary price required for stop-loss/take-profit orders[/red]")
            return
        
        # Prepare order parameters
        order_params = {
            'pair': pair,
            'type': side,
            'ordertype': order_type,
            'volume': volume
        }
        
        if price:
            order_params['price'] = price
        if price2:
            order_params['price2'] = price2
        
        # Place the order
        result = trader.place_order(**order_params)
        
        if result:
            console.print("[green]✅ Order placed successfully![/green]")
            console.print(f"Order ID: [cyan]{result.get('txid', ['Unknown'])[0]}[/cyan]")
            
            # Show order details
            table = Table(title="Order Details")
            table.add_column("Field", style="cyan")
            table.add_column("Value", style="green")
            
            table.add_row("Pair", pair)
            table.add_row("Side", side.upper())
            table.add_row("Type", order_type.upper())
            table.add_row("Volume", str(volume))
            if price:
                table.add_row("Price", str(price))
            
            console.print(table)
        else:
            console.print("[red]❌ Failed to place order[/red]")
            
    except Exception as e:
        console.print(f"[red]❌ Error placing order: {str(e)}[/red]")

@cli.command()
@click.option('--status', '-s', help='Filter by order status (open, closed, any)')
@click.option('--trades', is_flag=True, help='Show trade history instead of orders')
@click.pass_context
def orders(ctx, status, trades):
    """Show current orders or trade history"""
    portfolio = ctx.obj['portfolio']
    
    try:
        if trades:
            console.print("[bold blue]📊 Fetching trade history...[/bold blue]")
            trades_data = portfolio.get_trade_history()
            
            if trades_data:
                table = Table(title="Trade History")
                table.add_column("Time", style="cyan")
                table.add_column("Pair", style="green")
                table.add_column("Side", style="yellow")
                table.add_column("Price", style="blue")
                table.add_column("Volume", style="magenta")
                table.add_column("Cost", style="red")
                
                for trade in trades_data:
                    table.add_row(
                        trade.get('time', 'N/A'),
                        trade.get('pair', 'N/A'),
                        trade.get('type', 'N/A'),
                        trade.get('price', 'N/A'),
                        trade.get('vol', 'N/A'),
                        trade.get('cost', 'N/A')
                    )
                
                console.print(table)
            else:
                console.print("[yellow]No trade history found[/yellow]")
        else:
            console.print("[bold blue]📋 Fetching open orders...[/bold blue]")
            orders_data = portfolio.get_open_orders()
            
            if orders_data:
                table = Table(title="Open Orders")
                table.add_column("Time", style="cyan")
                table.add_column("Pair", style="green")
                table.add_column("Side", style="yellow")
                table.add_column("Type", style="blue")
                table.add_column("Volume", style="magenta")
                table.add_column("Price", style="red")
                
                for order_id, order in orders_data.items():
                    table.add_row(
                        order.get('opentm', 'N/A'),
                        order.get('descr', {}).get('pair', 'N/A'),
                        order.get('descr', {}).get('type', 'N/A'),
                        order.get('descr', {}).get('ordertype', 'N/A'),
                        order.get('vol', 'N/A'),
                        order.get('descr', {}).get('price', 'N/A')
                    )
                
                console.print(table)
            else:
                console.print("[yellow]No open orders found[/yellow]")
                
    except Exception as e:
        console.print(f"[red]❌ Error fetching orders: {str(e)}[/red]")

@cli.command()
@click.option('--cancel-all', is_flag=True, help='Cancel all open orders')
@click.option('--txid', help='Order ID to cancel')
@click.pass_context
def cancel(ctx, cancel_all, txid):
    """Cancel orders"""
    trader = ctx.obj['trader']
    
    try:
        if cancel_all:
            console.print("[bold yellow]⚠️  Cancelling all open orders...[/bold yellow]")
            result = trader.cancel_all_orders()
            
            if result:
                console.print("[green]✅ All orders cancelled successfully![/green]")
            else:
                console.print("[red]❌ Failed to cancel orders[/red]")
                
        elif txid:
            console.print(f"[bold yellow]⚠️  Cancelling order {txid}...[/bold yellow]")
            result = trader.cancel_order(txid)
            
            if result:
                console.print("[green]✅ Order cancelled successfully![/green]")
            else:
                console.print("[red]❌ Failed to cancel order[/red]")
        else:
            console.print("[red]❌ Please specify --cancel-all or --txid[/red]")
            
    except Exception as e:
        console.print(f"[red]❌ Error cancelling order: {str(e)}[/red]")

@cli.command()
@click.option('--pair', '-p', help='Filter by trading pair')
@click.pass_context
def portfolio(ctx, pair):
    """Show portfolio overview"""
    portfolio = ctx.obj['portfolio']
    
    try:
        console.print("[bold blue]💼 Portfolio Overview[/bold blue]")
        
        # Get balances
        balances = portfolio.get_balances()
        
        if balances:
            table = Table(title="Asset Balances")
            table.add_column("Asset", style="cyan")
            table.add_column("Balance", style="green")
            table.add_column("Hold", style="yellow")
            table.add_column("USD Value", style="blue")
            
            for asset, amount in balances.items():
                if float(amount) > 0.01:  # Only show significant balances
                    usd_value = portfolio.get_usd_value(asset, float(amount))
                    table.add_row(
                        asset,
                        format_currency(amount),
                        "0.00",  # Hold amount not shown in balance endpoint
                        format_currency(str(usd_value)) if usd_value else "N/A"
                    )
            
            console.print(table)
            
            # Show total value if possible
            total_value = portfolio.get_total_usd_value()
            if total_value:
                console.print(f"\n[bold green]Total Portfolio Value: ${format_currency(str(total_value))}[/bold green]")
        
        # Get open positions
        positions = portfolio.get_open_positions()
        if positions:
            console.print("\n[bold blue]Open Positions[/bold blue]")
            pos_table = Table()
            pos_table.add_column("Pair", style="cyan")
            pos_table.add_column("Side", style="yellow")
            pos_table.add_column("Volume", style="green")
            pos_table.add_column("P&L", style="magenta")
            
            for pair_name, position in positions.items():
                pos_table.add_row(
                    pair_name,
                    position.get('type', 'N/A'),
                    position.get('vol', 'N/A'),
                    position.get('net', 'N/A')
                )
            
            console.print(pos_table)
            
    except Exception as e:
        console.print(f"[red]❌ Error fetching portfolio: {str(e)}[/red]")

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
def info():
    """Show application information and warnings"""
    panel = Panel.fit(
        "[bold cyan]Kraken Pro Trading CLI[/bold cyan]\n\n"
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
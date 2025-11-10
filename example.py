#!/usr/bin/env python3
"""
Example script demonstrating Kraken CLI usage
This script shows how to use the Kraken trading application programmatically
"""

import os
import sys
from pathlib import Path

# Add the current directory to the path
sys.path.append(str(Path(__file__).parent))

from config import Config
from api.kraken_client import KrakenAPIClient
from trading.trader import Trader
from portfolio.portfolio_manager import PortfolioManager
from utils.helpers import format_currency, format_percentage


def main():
    """Demonstrate Kraken CLI functionality"""
    print("🚀 Kraken Pro Trading CLI - Example Usage")
    print("=" * 50)
    
    # Load configuration
    config = Config()
    
    # Check if credentials are configured
    if not config.has_credentials():
        print("❌ API credentials not configured!")
        print("Please set up your .env file with Kraken API credentials.")
        print("See README.md for setup instructions.")
        return
    
    print(f"🔧 Using {'Sandbox' if config.is_sandbox() else 'Live'} environment")
    
    try:
        # Initialize API client
        print("🔌 Connecting to Kraken API...")
        api_client = KrakenAPIClient(
            api_key=config.api_key,
            api_secret=config.api_secret,
            sandbox=config.sandbox
        )
        
        # Initialize components
        trader = Trader(api_client)
        portfolio = PortfolioManager(api_client)
        
        # Test connection
        print("📡 Testing API connection...")
        time_info = api_client.get_server_time()
        print(f"✅ Connected successfully! Server time: {time_info['result']['unixtime']}")
        
        # Get account balances
        print("\n💰 Getting account balances...")
        balances = portfolio.get_balances()
        if balances:
            print("Account balances:")
            for asset, amount in balances.items():
                if float(amount) > 0:
                    print(f"  {asset}: {format_currency(amount)}")
        else:
            print("No balances found or insufficient permissions")
        
        # Get ticker data
        print("\n📊 Getting ticker data for XBTUSD...")
        ticker = api_client.get_ticker("XBTUSD")
        if ticker and 'result' in ticker:
            xbt_data = ticker['result'].get('XXBTZUSD', {})
            if xbt_data:
                print(f"Bitcoin (XBT/USD):")
                print(f"  Last Price: {format_currency(xbt_data['c'][0])}")
                print(f"  24h Change: {format_percentage(xbt_data['p'][0])}")
                print(f"  24h High: {format_currency(xbt_data['h'][0])}")
                print(f"  24h Low: {format_currency(xbt_data['l'][0])}")
                print(f"  Volume: {xbt_data['v'][0]}")
        
        # Get portfolio summary
        print("\n📈 Portfolio Summary...")
        summary = portfolio.get_portfolio_summary()
        if summary['total_usd_value']:
            print(f"Total Portfolio Value: {format_currency(str(summary['total_usd_value']))}")
            print(f"Total Assets: {summary['total_assets']}")
            print(f"Open Orders: {summary['open_orders_count']}")
            print(f"Open Positions: {summary['open_positions_count']}")
        
        # Performance metrics
        print("\n📊 Performance Metrics...")
        metrics = portfolio.get_performance_metrics()
        print(f"Total Trades: {metrics['total_trades']}")
        print(f"Profitable Trades: {metrics['profitable_trades']}")
        print(f"Win Rate: {format_percentage(metrics['win_rate'])}")
        print(f"Total Volume: {metrics['total_volume']}")
        
        # Example order validation
        print("\n🔍 Example Order Validation...")
        pair = "XBTUSD"
        volume = 0.001
        has_balance = trader.validate_sufficient_balance(pair, "buy", volume)
        print(f"Can place buy order for {volume} {pair}? {'✅ Yes' if has_balance else '❌ No'}")
        
        if has_balance:
            # Estimate fees
            fees = trader.estimate_fees(pair, volume, "market")
            print(f"Estimated trade value: {format_currency(str(fees['trade_value']))}")
            print(f"Estimated fee: {format_currency(str(fees['estimated_fee']))}")
        
        print("\n🎯 Example Commands to Try:")
        print("  python kraken_cli.py status                    # Check account status")
        print("  python kraken_cli.py ticker --pair XBTUSD     # View Bitcoin price")
        print("  python kraken_cli.py orders                    # View open orders")
        print("  python kraken_cli.py portfolio                 # View portfolio")
        print("  python kraken_cli.py order --pair XBTUSD --side buy --order-type market --volume 0.001  # Place order")
        
        print("\n⚠️  REMEMBER: Only place orders you can afford to lose!")
        
    except Exception as e:
        print(f"❌ Error: {str(e)}")
        print("Please check your API credentials and internet connection.")
        print("See README.md for troubleshooting tips.")


if __name__ == "__main__":
    main()
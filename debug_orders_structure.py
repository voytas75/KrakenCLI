#!/usr/bin/env python3
"""
Debug script to see the actual structure of open orders API response
"""
import os
import sys
from pathlib import Path

# Add the project root to Python path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

import config
from api.kraken_client import KrakenAPIClient
from portfolio.portfolio_manager import PortfolioManager

def main():
    print("🔍 Debug: Open Orders API Response Structure")
    print("=" * 50)
    
    # Check credentials
    config_instance = config.Config()
    if not config_instance.has_credentials():
        print("❌ API credentials not configured!")
        print("Please set KRAKEN_API_KEY and KRAKEN_API_SECRET in .env file")
        return
    
    try:
        # Create API client and portfolio manager
        api_client = KrakenAPIClient(
            api_key=config_instance.api_key,
            api_secret=config_instance.api_secret,
            sandbox=config_instance.sandbox
        )
        portfolio = PortfolioManager(api_client=api_client)
        
        print("✅ Connected to Kraken API")
        print("\n📋 Fetching open orders...")
        
        # Get open orders data
        orders_data = portfolio.get_open_orders()
        
        print(f"\n📊 Response type: {type(orders_data)}")
        print(f"📊 Response keys: {list(orders_data.keys()) if isinstance(orders_data, dict) else 'Not a dict'}")
        
        if orders_data:
            print(f"\n📊 Number of orders: {len(orders_data)}")
            
            # Show first order details
            first_key = list(orders_data.keys())[0]
            first_order = orders_data[first_key]
            
            print(f"\n🔍 First order ID: {first_key}")
            print(f"🔍 First order type: {type(first_order)}")
            print(f"🔍 First order keys: {list(first_order.keys()) if isinstance(first_order, dict) else 'Not a dict'}")
            
            # Show full structure of first order
            print(f"\n📋 First order structure:")
            for key, value in first_order.items():
                print(f"  {key}: {value} (type: {type(value)})")
                
        else:
            print("\n⚠️  No open orders found")
    
    except Exception as e:
        print(f"❌ Error: {str(e)}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
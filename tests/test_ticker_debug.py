#!/usr/bin/env python3
"""
Debug script to check the actual ticker API response format
"""
import os
import sys
import json
from dotenv import load_dotenv

# Add the current directory to Python path
sys.path.insert(0, '/workspace')

from api.kraken_client import KrakenAPIClient

def debug_ticker():
    """Debug ticker API response"""
    load_dotenv()
    
    # Initialize API client
    api_key = os.getenv('KRAKEN_API_KEY')
    api_secret = os.getenv('KRAKEN_API_SECRET')
    
    if not api_key or not api_secret:
        print("❌ API credentials not found in .env file")
        return
    
    client = KrakenAPIClient(api_key, api_secret)
    
    # Test ticker for XETHZUSD
    pair = "XETHZUSD"
    print(f"🔍 Debugging ticker response for {pair}")
    print("=" * 50)
    
    try:
        ticker_data = client.get_ticker(pair)
        print("Full API Response:")
        print(json.dumps(ticker_data, indent=2))
        print("\n" + "=" * 50)
        
        # Analyze the result data
        result_data = ticker_data.get('result', {})
        pair_data = result_data.get(pair, {})
        
        print(f"\nParsed pair data for {pair}:")
        for key, value in pair_data.items():
            print(f"  {key}: {value} (type: {type(value)})")
            
        # Check the 'p' field specifically
        p_field = pair_data.get('p', [])
        print(f"\nPrice change field 'p': {p_field}")
        if len(p_field) >= 2:
            vwap = p_field[0]  # Volume weighted average price
            avg_24h = p_field[1]  # 24h rolling average
            print(f"  VWAP (p[0]): {vwap}")
            print(f"  24h Average (p[1]): {avg_24h}")
            
        # Check current price
        c_field = pair_data.get('c', [])
        if len(c_field) >= 1:
            current_price = c_field[0]
            print(f"\nCurrent price (c[0]): {current_price}")
            
        # Calculate proper percentage change
        if len(p_field) >= 2 and len(c_field) >= 1:
            vwap = float(p_field[0])
            current_price = float(c_field[0])
            
            if vwap > 0:
                percentage_change = ((current_price - vwap) / vwap) * 100
                print(f"\nCalculated 24h change: {percentage_change:.2f}%")
                print(f"   Current: {current_price}")
                print(f"   VWAP: {vwap}")
                print(f"   Change: {current_price - vwap}")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    debug_ticker()
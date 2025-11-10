#!/usr/bin/env python3
"""
Test the ticker fix with the Kraken API
"""

import requests
import json

def test_ticker_with_fix():
    """Test the ticker with the new pair resolution logic"""
    try:
        print("🔍 Testing ticker with new pair resolution logic...")
        
        # Test with XBTUSD
        pair = "XBTUSD"
        url = f"https://api.kraken.com/0/public/Ticker?pair={pair}"
        response = requests.get(url, timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            result_data = data.get('result', {})
            
            print(f"✅ API Response keys: {list(result_data.keys())}")
            
            # Apply the new logic
            trading_pair = pair
            pair_data = None
            actual_pair_key = None
            
            # First, try exact match
            if trading_pair in result_data:
                pair_data = result_data[trading_pair]
                actual_pair_key = trading_pair
            else:
                # Look for alternate formats
                alt_formats = []
                if 'XBT' in trading_pair and 'USD' in trading_pair:
                    alt_formats = [trading_pair.replace('XBT', 'XXBT').replace('USD', 'ZUSD'), 
                                  trading_pair.replace('XBT', 'XXBTZ').replace('USD', 'ZUSD')]
                
                print(f"🔄 Trying alternate formats: {alt_formats}")
                
                # Try alternate formats
                for alt_format in alt_formats:
                    if alt_format in result_data:
                        pair_data = result_data[alt_format]
                        actual_pair_key = alt_format
                        print(f"✅ Found data with key: {alt_format}")
                        break
            
            if pair_data and actual_pair_key:
                # Extract data
                current_price = float(pair_data.get('c', ['0', ''])[0] or 0)
                vwap_24h = float(pair_data.get('p', ['0', ''])[1] or 0)  # VWAP is index 1
                
                print(f"💰 Current Price: {current_price}")
                print(f"📊 VWAP 24h: {vwap_24h}")
                
                # Calculate percentage change
                if current_price > 0 and vwap_24h > 0:
                    percentage_change = ((current_price - vwap_24h) / vwap_24h) * 100
                    print(f"📈 24h Change: {percentage_change:.2f}%")
                else:
                    print("❌ Could not calculate percentage change")
                    
            else:
                print("❌ No pair data found")
                
        else:
            print(f"❌ HTTP Error: {response.status_code}")
            
    except Exception as e:
        print(f"❌ Error: {str(e)}")

if __name__ == "__main__":
    test_ticker_with_fix()
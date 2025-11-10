#!/usr/bin/env python3
"""
Test script to check available trading pairs on Kraken
"""

import requests
import json
import sys

def test_asset_pairs():
    """Test the AssetPairs endpoint to see available pairs"""
    try:
        print("🔍 Testing Kraken AssetPairs endpoint...")
        
        # Try the AssetPairs endpoint
        url = "https://api.kraken.com/0/public/AssetPairs"
        response = requests.get(url, timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            
            if data.get('error'):
                print(f"❌ API Error: {data['error']}")
                return
            
            pairs = data.get('result', {})
            print(f"✅ Retrieved {len(pairs)} trading pairs")
            
            # Look for Bitcoin and Ethereum related pairs
            bitcoin_pairs = []
            ethereum_pairs = []
            
            for pair_name, pair_info in pairs.items():
                altname = pair_info.get('altname', pair_name)
                wsname = pair_info.get('wsname', '')
                
                # Look for Bitcoin pairs
                if 'BTC' in pair_name or 'XBT' in pair_name or 'btc' in altname.lower():
                    bitcoin_pairs.append({
                        'pair': pair_name,
                        'altname': altname,
                        'wsname': wsname
                    })
                
                # Look for Ethereum pairs
                if 'ETH' in pair_name or 'eth' in altname.lower():
                    ethereum_pairs.append({
                        'pair': pair_name,
                        'altname': altname,
                        'wsname': wsname
                    })
            
            print("\n🪙 Bitcoin pairs found:")
            for pair in bitcoin_pairs[:5]:  # Show first 5
                print(f"  - {pair['pair']} (altname: {pair['altname']}, wsname: {pair['wsname']})")
            
            print("\n🌐 Ethereum pairs found:")
            for pair in ethereum_pairs[:5]:  # Show first 5
                print(f"  - {pair['pair']} (altname: {pair['altname']}, wsname: {pair['wsname']})")
                
        else:
            print(f"❌ HTTP Error: {response.status_code}")
            
    except Exception as e:
        print(f"❌ Error: {str(e)}")

def test_ticker_endpoint():
    """Test the Ticker endpoint with different pair formats"""
    try:
        print("\n🔍 Testing Ticker endpoint with different formats...")
        
        # Test different Bitcoin/USD formats
        test_pairs = ['XBTUSD', 'XXBTZUSD', 'XBT/USD', 'BTCUSD']
        
        for pair in test_pairs:
            try:
                url = f"https://api.kraken.com/0/public/Ticker?pair={pair}"
                response = requests.get(url, timeout=5)
                
                if response.status_code == 200:
                    data = response.json()
                    
                    if not data.get('error') and data.get('result'):
                        result = data.get('result', {})
                        if result:
                            print(f"✅ {pair}: Success - {list(result.keys())}")
                        else:
                            print(f"⚠️  {pair}: No data returned")
                    else:
                        print(f"❌ {pair}: {data.get('error', 'Unknown error')}")
                else:
                    print(f"❌ {pair}: HTTP {response.status_code}")
                    
            except Exception as e:
                print(f"❌ {pair}: Error - {str(e)}")
                
    except Exception as e:
        print(f"❌ Ticker test error: {str(e)}")

if __name__ == "__main__":
    print("🌊 Testing Kraken API Trading Pairs")
    print("=" * 50)
    
    test_asset_pairs()
    test_ticker_endpoint()
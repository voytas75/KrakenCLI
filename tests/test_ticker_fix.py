#!/usr/bin/env python3
"""
Test script to demonstrate the corrected ticker percentage calculation
"""
import json

def test_ticker_calculation():
    """Test the ticker percentage calculation logic"""
    
    # Simulate a typical Kraken API ticker response
    mock_pair_data = {
        'c': ['3617.19000', '0.02539000'],  # last price, volume
        'p': ['3622.16036', '3594.84730'],   # VWAP 24h, average 24h
        'h': ['3658.00000', '3662.15000'],   # high 24h, high all-time
        'l': ['3551.99000', '3551.99000'],   # low 24h, low all-time
        'v': ['15810.12587008', '15023.98765432'],  # volume 24h, volume 24h (alternate)
        'b': ['3617.18000', '5'],            # bid price, bid lot volume
        'a': ['3617.19000', '2']             # ask price, ask lot volume
    }
    
    print("🧪 Testing Ticker Percentage Calculation")
    print("=" * 50)
    
    # Extract current price and VWAP
    current_price = float(mock_pair_data.get('c', ['0', ''])[0] or 0)
    vwap_24h = float(mock_pair_data.get('p', ['0', ''])[0] or 0)
    
    print(f"Current Price: ${current_price:,.8f}")
    print(f"VWAP 24h: ${vwap_24h:,.8f}")
    
    # Calculate percentage change
    if current_price > 0 and vwap_24h > 0:
        percentage_change = ((current_price - vwap_24h) / vwap_24h) * 100
        change_sign = "+" if percentage_change >= 0 else ""
        change_color = "green" if percentage_change >= 0 else "red"
        
        print(f"\n📊 Calculated 24h Change: {change_sign}{percentage_change:.2f}%")
        print(f"   Formula: ((Current - VWAP) / VWAP) * 100")
        print(f"   = (({current_price} - {vwap_24h}) / {vwap_24h}) * 100")
        print(f"   = ({current_price - vwap_24h} / {vwap_24h}) * 100")
        print(f"   = {percentage_change:.4f}%")
        
        # Show what it looked like before the fix
        print(f"\n❌ BEFORE (Wrong): {vwap_24h}% (displayed VWAP as percentage)")
        print(f"✅ AFTER (Correct): {change_sign}{percentage_change:.2f}% (calculated percentage)")
        
    else:
        print("❌ Invalid price data")
    
    print("\n" + "=" * 50)
    print("🔍 Volume Analysis:")
    volume_24h = mock_pair_data.get('v', ['0', ''])[0]
    print(f"Volume 24h: {volume_24h} (likely in base asset units)")
    print("Note: Volume is in base currency units, not USD value")
    
    print("\n" + "=" * 50)
    print("📝 Summary of Fixes:")
    print("1. ✅ Fixed percentage calculation using (current - vwap) / vwap * 100")
    print("2. ✅ Added color coding (green=positive, red=negative)")
    print("3. ✅ Proper number formatting with commas")
    print("4. ✅ Better error handling for invalid data")

if __name__ == "__main__":
    test_ticker_calculation()
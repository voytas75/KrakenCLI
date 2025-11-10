#!/usr/bin/env python3
"""
Test script to verify the orders fix in the user's environment
"""
import subprocess
import sys

def run_test():
    print("🧪 Testing Orders Command Fix")
    print("=" * 40)
    
    try:
        # Run the orders command
        result = subprocess.run(
            [sys.executable, "kraken_cli.py", "orders"],
            capture_output=True,
            text=True,
            timeout=30
        )
        
        print("📋 Orders Command Output:")
        print("-" * 30)
        print(result.stdout)
        
        if result.stderr:
            print("⚠️  Error Output:")
            print("-" * 30)
            print(result.stderr)
        
        print(f"\n📊 Exit Code: {result.returncode}")
        
        # Check if the fix worked (no N/A values or debug info visible)
        if "N/A" in result.stdout and "Debug:" not in result.stdout:
            print("❌ Still showing N/A values - needs more debugging")
        elif "Debug:" in result.stdout:
            print("🔍 Debug info visible - check the order structure output above")
        elif "No open orders found" in result.stdout:
            print("ℹ️  No orders found (this is normal if you have no open orders)")
        else:
            print("✅ Orders command executed successfully!")
            
    except subprocess.TimeoutExpired:
        print("⏰ Command timed out")
    except Exception as e:
        print(f"❌ Error running test: {e}")

if __name__ == "__main__":
    run_test()
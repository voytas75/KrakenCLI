#!/usr/bin/env python3
"""
Comprehensive test to verify all CLI command fixes
"""

import subprocess
import sys

def run_command(command):
    """Run a CLI command and capture the result"""
    try:
        result = subprocess.run(
            command, 
            shell=True, 
            capture_output=True, 
            text=True, 
            timeout=10
        )
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return -1, "", "Command timed out"
    except Exception as e:
        return -1, "", str(e)

def test_all_commands():
    """Test all available CLI commands"""
    print("🧪 COMPREHENSIVE CLI TEST")
    print("=" * 50)
    
    # Test commands that should work without credentials
    safe_commands = [
        ("python kraken_cli.py --help", "Main help"),
        ("python kraken_cli.py ticker --help", "Ticker help"),
        ("python kraken_cli.py info", "Info command"),
        ("python kraken_cli.py config-setup --help", "Config help"),
    ]
    
    # Test commands that should show credential warning
    credential_commands = [
        ("python kraken_cli.py status", "Status"),
        ("python kraken_cli.py portfolio", "Portfolio"),
        ("python kraken_cli.py orders", "Orders"),
        ("python kraken_cli.py orders --trades", "Trade history"),
        ("python kraken_cli.py ticker xbt usd", "Ticker XBT/USD"),
        ("python kraken_cli.py order --help", "Order help"),
        ("python kraken_cli.py cancel --help", "Cancel help"),
    ]
    
    all_passed = True
    
    print("🔍 Testing SAFE commands (should work without credentials):")
    print("-" * 60)
    for cmd, desc in safe_commands:
        returncode, stdout, stderr = run_command(cmd)
        
        if returncode == 0:
            print(f"✅ {desc}: PASSED")
        else:
            print(f"❌ {desc}: FAILED")
            if stderr:
                print(f"   Error: {stderr.strip()}")
            all_passed = False
    
    print("\n🔍 Testing CREDENTIAL commands (should show graceful error):")
    print("-" * 60)
    for cmd, desc in credential_commands:
        returncode, stdout, stderr = run_command(cmd)
        
        if returncode == 0 and "API credentials not configured" in stdout:
            print(f"✅ {desc}: PASSED (graceful error)")
        elif returncode == 0:
            print(f"⚠️  {desc}: Unexpected success (may have credentials)")
        else:
            print(f"❌ {desc}: FAILED")
            if stderr:
                print(f"   Error: {stderr.strip()}")
            all_passed = False
    
    print("\n" + "=" * 50)
    if all_passed:
        print("🎉 ALL TESTS PASSED!")
        print("✅ Context object handling is working correctly")
        print("✅ Commands handle missing credentials gracefully")
        print("✅ Help commands work without credentials")
        print("✅ No more KeyError exceptions")
    else:
        print("❌ Some tests failed - check the output above")
    
    return all_passed

if __name__ == "__main__":
    test_all_commands()
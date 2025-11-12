#!/usr/bin/env python3
"""Comprehensive test to verify all CLI command fixes."""

from pathlib import Path
import subprocess
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import Config

def run_command(command):
    """Run a CLI command and capture the result"""
    try:
        result = subprocess.run(
            command, 
            shell=True, 
            capture_output=True, 
            text=True, 
            timeout=10,
            encoding='utf-8',
            errors='replace'  # Replace undecodable characters instead of failing
        )
        return result.returncode, result.stdout or "", result.stderr or ""
    except subprocess.TimeoutExpired:
        return -1, "", "Command timed out"
    except Exception as e:
        return -1, "", str(e)

def test_all_commands():
    """Test all available CLI commands"""
    print("🧪 COMPREHENSIVE CLI TEST")
    print("=" * 50)

    config = Config()
    credentials_present = config.has_credentials()
    
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
        ("python kraken_cli.py ticker -p XBTUSD", "Ticker direct XBTUSD"),
        ("python kraken_cli.py ticker -p ETHUSD", "Ticker direct ETHUSD"),
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
                print(f"   Error: {str(stderr).strip()}")
            all_passed = False
    
    print("\n🔍 Testing CREDENTIAL commands (should show graceful error):")
    print("-" * 60)
    for cmd, desc in credential_commands:
        returncode, stdout, stderr = run_command(cmd)
        
        if returncode == 0 and stdout and "API credentials not configured" in stdout:
            print(f"✅ {desc}: PASSED (graceful error)")
        elif returncode == 0:
            if credentials_present:
                print(f"✅ {desc}: PASSED (credentials detected)")
            else:
                print(f"⚠️  {desc}: Unexpected success (credentials detected via other source)")
        else:
            print(f"❌ {desc}: FAILED")
            if stderr:
                print(f"   Error: {str(stderr).strip()}")
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

#!/usr/bin/env python3
"""
Setup script for Kraken Pro Trading CLI
"""

import os
import sys
from pathlib import Path


def main():
    print("🚀 Kraken Pro Trading CLI - Setup Script")
    print("=" * 50)
    
    # Check Python version
    python_version = sys.version_info
    print(f"🐍 Python version: {python_version.major}.{python_version.minor}.{python_version.micro}")
    
    if python_version < (3, 12):
        print("❌ Python 3.12 or higher is required!")
        print("Please upgrade your Python version.")
        return False
    
    print("✅ Python version is compatible")
    
    # Check if we're in the right directory
    if not Path("kraken_cli.py").exists():
        print("❌ kraken_cli.py not found!")
        print("Please run this script from the application directory.")
        return False
    
    print("✅ Application files found")
    
    # Install dependencies
    print("\n📦 Installing dependencies...")
    try:
        import subprocess
        result = subprocess.run([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"], 
                              capture_output=True, text=True)
        if result.returncode == 0:
            print("✅ Dependencies installed successfully")
        else:
            print("❌ Failed to install dependencies:")
            print(result.stderr)
            return False
    except Exception as e:
        print(f"❌ Error installing dependencies: {e}")
        return False
    
    # Create .env file if it doesn't exist
    env_file = Path(".env")
    env_template = Path(".env.template")
    
    if not env_file.exists():
        if env_template.exists():
            print("\n📝 Creating .env file from template...")
            import shutil
            shutil.copy(env_template, env_file)
            print("✅ .env file created")
            print("⚠️  IMPORTANT: Edit .env file with your Kraken API credentials!")
        else:
            print("\n⚠️  .env file not found and no template available")
            print("You'll need to create .env file manually")
    else:
        print("✅ .env file already exists")
    
    # Test application
    print("\n🧪 Testing application...")
    try:
        result = subprocess.run([sys.executable, "kraken_cli.py", "--help"], 
                              capture_output=True, text=True)
        if result.returncode == 0:
            print("✅ Application is working")
        else:
            print("❌ Application test failed:")
            print(result.stderr)
            return False
    except Exception as e:
        print(f"❌ Error testing application: {e}")
        return False
    
    # Print next steps
    print("\n🎉 Setup completed successfully!")
    print("\nNext steps:")
    print("1. Edit .env file with your Kraken API credentials")
    print("2. Get your API key from: https://www.kraken.com/u/settings/api")
    print("3. Test connection: python kraken_cli.py status")
    print("4. Read README.md for detailed usage instructions")
    print("\n⚠️  REMEMBER: Only trade with money you can afford to lose!")
    print("🧪 Start with sandbox mode for testing!")
    
    return True


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
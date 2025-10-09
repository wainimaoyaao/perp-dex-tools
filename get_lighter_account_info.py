#!/usr/bin/env python3
"""
Lighter Account Information Retrieval Tool

This script helps you find the correct LIGHTER_ACCOUNT_INDEX for your account.
Run this script to get your account information and find the correct index to use.

Usage:
    python get_lighter_account_info.py

Make sure you have set the following environment variables:
    - API_KEY_PRIVATE_KEY: Your Lighter API private key (not used in this version)
    - LIGHTER_ACCOUNT_INDEX: Initial account index (can be 0 if unknown)
    - LIGHTER_API_KEY_INDEX: API key index (usually 0)
"""

import os
import asyncio
import logging
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Import Lighter SDK
try:
    import lighter
except ImportError:
    print("❌ Error: Lighter SDK not installed. Please install it with:")
    print("pip install git+https://github.com/elliottech/lighter-python.git")
    exit(1)

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Suppress Lighter SDK debug logs
logging.getLogger('lighter').setLevel(logging.WARNING)


class LighterAccountInfo:
    """Tool to retrieve Lighter account information."""
    
    def __init__(self):
        """Initialize the account info tool."""
        self.api_key_private_key = os.getenv('API_KEY_PRIVATE_KEY')
        self.account_index = int(os.getenv('LIGHTER_ACCOUNT_INDEX', '0'))
        self.api_key_index = int(os.getenv('LIGHTER_API_KEY_INDEX', '0'))
        self.base_url = "https://mainnet.zklighter.elliot.ai"
        
        # Note: The new API doesn't require private key for read operations
        self.api_client = None
        self.account_api = None
    
    async def initialize_client(self):
        """Initialize the Lighter client."""
        try:
            print("🔧 Initializing Lighter client...")
            
            # Create API client (no authentication needed for read operations)
            self.api_client = lighter.ApiClient()
            self.account_api = lighter.AccountApi(self.api_client)
            
            print(f"✅ Client initialized successfully")
            print(f"📍 Current Account Index: {self.account_index}")
            print(f"📍 Current API Key Index: {self.api_key_index}")
            
        except Exception as e:
            print(f"❌ Error initializing client: {e}")
            raise
    
    async def print_api_result(self, api_call, description, **kwargs):
        """Helper function to print API call results."""
        try:
            print(f"\n🔍 {description}")
            print("-" * 50)
            
            if kwargs:
                print(f"Parameters: {kwargs}")
            
            result = await api_call(**kwargs)
            print(f"Result: {result}")
            
            return result
            
        except Exception as e:
            print(f"❌ Error in {description}: {e}")
            return None
    
    async def get_account_apis(self):
        """Get account information using various API calls."""
        try:
            print("\n" + "="*60)
            print("🏦 LIGHTER ACCOUNT INFORMATION")
            print("="*60)
            
            # Get account by index
            await self.print_api_result(
                self.account_api.account,
                "Account by Index",
                by="index",
                value=str(self.account_index)
            )
            
            # Get API keys for current account
            await self.print_api_result(
                self.account_api.apikeys,
                "API Keys for Current Account",
                account_index=self.account_index,
                api_key_index=self.api_key_index
            )
            
            # Get public pools
            await self.print_api_result(
                self.account_api.public_pools,
                "Public Pools",
                filter="all",
                limit=5,
                index=0
            )
            
        except Exception as e:
            print(f"❌ Error getting account APIs: {e}")
            raise
    
    async def test_different_indices(self):
        """Test different account indices to find the correct one."""
        print(f"\n🔍 Testing different account indices...")
        
        working_indices = []
        
        for test_index in range(5):  # Test indices 0-4
            try:
                print(f"\n🧪 Testing account index: {test_index}")
                
                result = await self.account_api.account(by="index", value=str(test_index))
                
                if result:
                    print(f"✅ Index {test_index} works: {result}")
                    working_indices.append(test_index)
                else:
                    print(f"❌ Index {test_index} returned no result")
                    
            except Exception as e:
                print(f"❌ Index {test_index} failed: {e}")
        
        if working_indices:
            print(f"\n✅ Working account indices: {working_indices}")
            print(f"💡 Recommended LIGHTER_ACCOUNT_INDEX: {working_indices[0]}")
        else:
            print(f"\n❌ No working account indices found")
    
    async def close(self):
        """Close the client connection."""
        if self.api_client:
            await self.api_client.close()


async def main():
    """Main function to run the account info tool."""
    print("🚀 Lighter Account Information Tool")
    print("="*50)
    
    # Note: This version uses public API endpoints and doesn't require authentication
    
    account_info = None
    
    try:
        # Initialize account info tool
        account_info = LighterAccountInfo()
        await account_info.initialize_client()
        
        # Get account information
        await account_info.get_account_apis()
        
        # Test different indices
        await account_info.test_different_indices()
        
        print(f"\n" + "="*60)
        print("✅ Account information retrieval completed!")
        print("="*60)
        print("\n💡 Next steps:")
        print("1. Check the 'Working account indices' above")
        print("2. Update your .env file with the correct LIGHTER_ACCOUNT_INDEX")
        print("3. Restart your trading bot")
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        print("\n🔧 Troubleshooting:")
        print("1. Check your API_KEY_PRIVATE_KEY is correct")
        print("2. Ensure you have network connectivity")
        print("3. Verify your Lighter account is properly set up")
        
    finally:
        if account_info:
            await account_info.close()


if __name__ == "__main__":
    asyncio.run(main())
#!/usr/bin/env python3
"""
Debug version of the trading bot with enhanced error reporting
"""

import argparse
import asyncio
import logging
import sys
import traceback
from pathlib import Path
import dotenv
from decimal import Decimal
from trading_bot import TradingBot, TradingConfig
from exchanges import ExchangeFactory


def setup_debug_logging():
    """Setup debug logging configuration."""
    # Configure root logger with DEBUG level
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler('debug_bot.log')
        ]
    )
    
    # Enable debug for all relevant modules
    logging.getLogger('lighter').setLevel(logging.DEBUG)
    logging.getLogger('websockets').setLevel(logging.DEBUG)
    logging.getLogger('urllib3').setLevel(logging.DEBUG)
    logging.getLogger('requests').setLevel(logging.DEBUG)


def check_environment():
    """Check environment variables and configuration."""
    print("=== Environment Check ===")
    
    # Check .env file
    env_file = Path(".env")
    if not env_file.exists():
        print("❌ .env file not found!")
        return False
    else:
        print("✅ .env file found")
    
    # Load environment variables
    dotenv.load_dotenv()
    
    # Check required variables for Lighter
    required_vars = [
        'API_KEY_PRIVATE_KEY',
        'LIGHTER_ACCOUNT_INDEX', 
        'LIGHTER_API_KEY_INDEX'
    ]
    
    missing_vars = []
    for var in required_vars:
        import os
        value = os.getenv(var)
        if not value:
            missing_vars.append(var)
            print(f"❌ {var}: Not set")
        else:
            # Don't print the actual private key, just confirm it exists
            if 'PRIVATE_KEY' in var:
                print(f"✅ {var}: Set (length: {len(value)})")
            else:
                print(f"✅ {var}: {value}")
    
    if missing_vars:
        print(f"\n❌ Missing required environment variables: {missing_vars}")
        return False
    
    print("✅ All required environment variables are set")
    return True


def parse_arguments():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description='Debug Trading Bot')
    
    parser.add_argument('--exchange', type=str, default='lighter',
                        choices=ExchangeFactory.get_supported_exchanges(),
                        help='Exchange to use')
    parser.add_argument('--ticker', type=str, default='HYPE',
                        help='Ticker symbol')
    parser.add_argument('--quantity', type=Decimal, default=Decimal(1.0),
                        help='Order quantity')
    parser.add_argument('--take-profit', type=Decimal, default=Decimal(0.002),
                        help='Take profit percentage')
    parser.add_argument('--direction', type=str, default='buy', choices=['buy', 'sell'],
                        help='Trading direction')
    parser.add_argument('--max-orders', type=int, default=20,
                        help='Maximum number of active orders')
    parser.add_argument('--wait-time', type=int, default=450,
                        help='Wait time between orders in seconds')
    parser.add_argument('--grid-step', type=str, default='0.5',
                        help='Grid step percentage')
    parser.add_argument('--stop-price', type=Decimal, default=-1,
                        help='Stop price')
    parser.add_argument('--pause-price', type=Decimal, default=-1,
                        help='Pause price')
    parser.add_argument('--enable-drawdown-monitor', action='store_true',
                        help='Enable drawdown monitoring')
    
    return parser.parse_args()


async def test_exchange_connection(config):
    """Test exchange connection and basic functionality."""
    print("\n=== Exchange Connection Test ===")
    
    try:
        # Create exchange client
        print(f"Creating {config.exchange} exchange client...")
        exchange_client = ExchangeFactory.create_exchange(config.exchange, config)
        print("✅ Exchange client created successfully")
        
        # Test connection
        print("Testing connection...")
        await exchange_client.connect()
        print("✅ Connected to exchange successfully")
        
        # Test basic functionality
        print("Testing contract attributes...")
        contract_id, tick_size = await exchange_client.get_contract_attributes()
        print(f"✅ Contract ID: {contract_id}, Tick Size: {tick_size}")
        
        # Test market data
        print("Testing market data...")
        try:
            bid, ask = await exchange_client.fetch_bbo_prices(contract_id)
            print(f"✅ BBO Prices - Bid: {bid}, Ask: {ask}")
            if bid > 0 and ask > 0:
                print(f"✅ Market data is working correctly!")
            else:
                print(f"⚠️ Market data returned zero values - WebSocket may not be connected")
        except Exception as e:
            print(f"❌ BBO Prices failed: {e}")

        print("Testing WebSocket connection status...")
        try:
            if hasattr(exchange_client, 'ws_manager') and exchange_client.ws_manager:
                if hasattr(exchange_client.ws_manager, 'running') and exchange_client.ws_manager.running:
                    print(f"✅ WebSocket is running")
                    # Test order book data
                    best_levels = exchange_client.ws_manager.get_best_levels()
                    print(f"✅ Order book best levels: {best_levels}")
                else:
                    print(f"❌ WebSocket is not running")
            else:
                print(f"❌ WebSocket manager not initialized")
        except Exception as e:
            print(f"❌ WebSocket status check failed: {e}")
        
        # Test account info
        print("Testing account information...")
        try:
            net_worth = await exchange_client.get_account_networth()
            print(f"✅ Account Net Worth: {net_worth}")
        except Exception as e:
            print(f"❌ Account Net Worth failed: {e}")
        
        # Disconnect
        await exchange_client.disconnect()
        print("✅ Disconnected successfully")
        
        return True
        
    except Exception as e:
        print(f"❌ Exchange connection test failed: {e}")
        print(f"Traceback: {traceback.format_exc()}")
        return False


async def main():
    """Main debug function."""
    print("🔍 Trading Bot Debug Mode")
    print("=" * 50)
    
    # Setup debug logging
    setup_debug_logging()
    
    # Check environment
    if not check_environment():
        print("\n❌ Environment check failed. Please fix the issues above.")
        sys.exit(1)
    
    # Parse arguments
    args = parse_arguments()
    
    # Create configuration
    config = TradingConfig(
        ticker=args.ticker.upper(),
        contract_id='',
        tick_size=Decimal(0),
        quantity=args.quantity,
        take_profit=args.take_profit,
        direction=args.direction.lower(),
        max_orders=args.max_orders,
        wait_time=args.wait_time,
        exchange=args.exchange.lower(),
        grid_step=Decimal(args.grid_step),
        stop_price=args.stop_price,
        pause_price=args.pause_price,
        aster_boost=False,
        enable_drawdown_monitor=args.enable_drawdown_monitor
    )
    
    print(f"\n=== Configuration ===")
    print(f"Exchange: {config.exchange}")
    print(f"Ticker: {config.ticker}")
    print(f"Quantity: {config.quantity}")
    print(f"Direction: {config.direction}")
    print(f"Max Orders: {config.max_orders}")
    print(f"Wait Time: {config.wait_time}s")
    print(f"Grid Step: {config.grid_step}%")
    print(f"Drawdown Monitor: {config.enable_drawdown_monitor}")
    
    # Test exchange connection
    connection_ok = await test_exchange_connection(config)
    if not connection_ok:
        print("\n❌ Exchange connection test failed. Cannot proceed.")
        sys.exit(1)
    
    print("\n=== Starting Trading Bot ===")
    
    # Create and run the bot
    try:
        bot = TradingBot(config)
        await bot.run()
    except KeyboardInterrupt:
        print("\n🛑 Bot stopped by user (Ctrl+C)")
    except Exception as e:
        print(f"\n❌ Bot execution failed: {e}")
        print(f"Traceback: {traceback.format_exc()}")
        sys.exit(1)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n🛑 Debug session interrupted by user")
    except Exception as e:
        print(f"\n💥 Critical error in debug session: {e}")
        print(f"Traceback: {traceback.format_exc()}")
        sys.exit(1)
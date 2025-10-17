"""
Lighter exchange client implementation.
"""

import os
import asyncio
import time
import logging
from decimal import Decimal
from typing import Dict, Any, List, Optional, Tuple

from .base import BaseExchangeClient, OrderResult, OrderInfo, query_retry
from helpers.logger import TradingLogger

# Import official Lighter SDK for API client
import lighter
from lighter import SignerClient, ApiClient, Configuration

# Import custom WebSocket implementation
from .lighter_custom_websocket import LighterCustomWebSocketManager

# Suppress Lighter SDK debug logs
logging.getLogger('lighter').setLevel(logging.WARNING)
# Also suppress root logger DEBUG messages that might be coming from Lighter SDK
root_logger = logging.getLogger()
if root_logger.level == logging.DEBUG:
    root_logger.setLevel(logging.WARNING)


class LighterClient(BaseExchangeClient):
    """Lighter exchange client implementation."""

    def __init__(self, config: Dict[str, Any]):
        """Initialize Lighter client."""
        super().__init__(config)

        # Lighter credentials from environment
        self.api_key_private_key = os.getenv('API_KEY_PRIVATE_KEY')
        self.account_index = int(os.getenv('LIGHTER_ACCOUNT_INDEX', '0'))
        self.api_key_index = int(os.getenv('LIGHTER_API_KEY_INDEX', '0'))
        self.base_url = "https://mainnet.zklighter.elliot.ai"

        if not self.api_key_private_key:
            raise ValueError("API_KEY_PRIVATE_KEY must be set in environment variables")

        # Initialize logger
        self.logger = TradingLogger(exchange="lighter", ticker=self.config.ticker, log_to_console=False)
        self._order_update_handler = None

        # Initialize Lighter client (will be done in connect)
        self.lighter_client = None

        # Initialize API client (will be done in connect)
        self.api_client = None

        # Market configuration
        self.base_amount_multiplier = None
        self.price_multiplier = None
        self.orders_cache = {}
        self.current_order_client_id = None
        self.current_order = None
        
        # Account networth cache to avoid rate limiting
        self._networth_cache = None
        self._networth_cache_time = 0
        self._networth_cache_duration = 30  # Cache for 30 seconds to avoid rate limiting
        self._last_api_call_time = 0
        self._min_api_interval = 2  # Minimum 2 seconds between API calls
        # Collateral-only cache
        self._collateral_cache = None
        self._collateral_cache_time = 0
        # Cache last filled prices per market and side for avg_price fallback
        self._last_fill_price_by_market = {}

    def _extract_avg_price(self, position: Any) -> Optional[Decimal]:
        """Extract average entry price from position with multiple fallbacks."""
        candidate_fields = [
            'avg_price', 'avgPrice', 'average_price', 'averagePrice',
            'avg_entry_price', 'avgEntryPrice', 'entry_avg_price',
            'entry_price', 'entryPrice', 'open_price', 'openPrice',
            'price'
        ]
        for field in candidate_fields:
            if hasattr(position, field):
                try:
                    value = getattr(position, field)
                    if value is not None:
                        price = Decimal(str(value))
                        if price > 0:
                            return price
                except Exception:
                    continue
        return None

    def _extract_market_id(self, position: Any) -> Optional[int]:
        """Extract market identifier from a position using multiple field names."""
        candidate_fields = [
            'market_id', 'marketIndex', 'market_index', 'marketId', 'index', 'market'
        ]
        for field in candidate_fields:
            if hasattr(position, field):
                try:
                    value = getattr(position, field)
                    if value is not None:
                        try:
                            return int(value)
                        except Exception:
                            # Fallback via string cast
                            return int(str(value))
                except Exception:
                    continue
        return None

    def _extract_position_size(self, position: Any) -> Decimal:
        """Extract position size from a position using multiple field names."""
        candidate_fields = [
            'position', 'size', 'base_size', 'base_amount', 'quantity'
        ]
        for field in candidate_fields:
            try:
                value = getattr(position, field, None)
                if value is not None:
                    return Decimal(str(value))
            except Exception:
                continue
        return Decimal('0')

    def _extract_unrealized_pnl(self, position: Any) -> Optional[Decimal]:
        """Extract unrealized PnL from position if provided by API."""
        candidate_fields = [
            'unrealized_pnl', 'unrealizedPnl', 'unrealizedPNL',
            'pnl_unrealized', 'unrealized', 'uPnL', 'UPNL'
        ]
        for field in candidate_fields:
            if hasattr(position, field):
                try:
                    value = getattr(position, field)
                    if value is not None:
                        return Decimal(str(value))
                except Exception:
                    continue
        return None

    async def _derive_avg_price_fallback(self, pos_size: Decimal) -> Optional[Decimal]:
        """Derive average price using cached fills or inactive orders as fallback."""
        try:
            side = 'buy' if pos_size > 0 else 'sell'
            market_id = self.config.contract_id
            cached = None
            try:
                cached = self._last_fill_price_by_market.get(market_id, {}).get(side)
            except Exception:
                cached = None
            if cached:
                try:
                    price = Decimal(str(cached))
                    if price > 0:
                        self.logger.log(f"Avg price fallback from cache: side={side}, price={price}", "DEBUG")
                        return price
                except Exception:
                    pass

            # Fetch last filled order price from inactive orders
            try:
                if self.lighter_client is None:
                    await self._initialize_lighter_client()

                auth_token, error = self.lighter_client.create_auth_token_with_expiry()
                if error is not None:
                    self.logger.log(f"Auth token error for inactive orders: {error}", "WARNING")
                else:
                    order_api = lighter.OrderApi(self.api_client)
                    orders_response = await order_api.account_inactive_orders(
                        account_index=self.account_index,
                        market_id=market_id,
                        auth=auth_token
                    )
                    orders = getattr(orders_response, 'orders', []) if orders_response else []
                    for order in reversed(orders):
                        try:
                            order_side = 'sell' if getattr(order, 'is_ask', False) else 'buy'
                            status = str(getattr(order, 'status', '')).upper()
                            price_val = getattr(order, 'price', None)
                            if order_side == side and status == 'FILLED' and price_val is not None:
                                price = Decimal(str(price_val))
                                if price > 0:
                                    self.logger.log(f"Avg price fallback from inactive orders: side={side}, price={price}", "DEBUG")
                                    return price
                        except Exception:
                            continue
            except Exception as e:
                self.logger.log(f"Inactive orders fallback error: {e}", "WARNING")
        except Exception:
            pass
        return None

    def _validate_config(self) -> None:
        """Validate Lighter configuration."""
        required_env_vars = ['API_KEY_PRIVATE_KEY', 'LIGHTER_ACCOUNT_INDEX', 'LIGHTER_API_KEY_INDEX']
        missing_vars = [var for var in required_env_vars if not os.getenv(var)]
        if missing_vars:
            raise ValueError(f"Missing required environment variables: {missing_vars}")

    async def _get_market_config(self, ticker: str) -> Tuple[int, int, int]:
        """Get market configuration for a ticker using official SDK."""
        try:
            # Use shared API client
            order_api = lighter.OrderApi(self.api_client)

            # Get order books to find market info
            order_books = await order_api.order_books()

            for market in order_books.order_books:
                if market.symbol == ticker:
                    market_id = market.market_id
                    base_multiplier = pow(10, market.supported_size_decimals)
                    price_multiplier = pow(10, market.supported_price_decimals)

                    # Store market info for later use
                    self.config.market_info = market

                    self.logger.log(
                        f"Market config for {ticker}: ID={market_id}, "
                        f"Base multiplier={base_multiplier}, Price multiplier={price_multiplier}",
                        "INFO"
                    )
                    return market_id, base_multiplier, price_multiplier

            raise Exception(f"Ticker {ticker} not found in available markets")

        except Exception as e:
            self.logger.log(f"Error getting market config: {e}", "ERROR")
            raise

    async def _initialize_lighter_client(self):
        """Initialize the Lighter client using official SDK."""
        if self.lighter_client is None:
            try:
                self.lighter_client = SignerClient(
                    url=self.base_url,
                    private_key=self.api_key_private_key,
                    account_index=self.account_index,
                    api_key_index=self.api_key_index,
                )

                # Check client
                err = self.lighter_client.check_client()
                if err is not None:
                    raise Exception(f"CheckClient error: {err}")

                self.logger.log("Lighter client initialized successfully", "INFO")
            except Exception as e:
                self.logger.log(f"Failed to initialize Lighter client: {e}", "ERROR")
                raise
        return self.lighter_client

    async def connect(self) -> None:
        """Connect to Lighter."""
        try:
            # Initialize shared API client
            self.api_client = ApiClient(configuration=Configuration(host=self.base_url))

            # Initialize Lighter client
            await self._initialize_lighter_client()

            # Only initialize WebSocket manager if contract_id is available
            if hasattr(self.config, 'contract_id') and self.config.contract_id:
                # Add market config to config for WebSocket manager
                self.config.market_index = self.config.contract_id
                self.config.account_index = self.account_index
                self.config.lighter_client = self.lighter_client

                # Initialize WebSocket manager (using custom implementation)
                self.ws_manager = LighterCustomWebSocketManager(
                    config=self.config,
                    order_update_callback=self._handle_websocket_order_update
                )

                # Set logger for WebSocket manager
                self.ws_manager.set_logger(self.logger)

                # Start WebSocket connection in background task
                asyncio.create_task(self.ws_manager.connect())
                # Wait a moment for connection to establish
                await asyncio.sleep(2)
                self.logger.log(f"WebSocket manager initialized with contract_id: {self.config.contract_id}", "INFO")
            else:
                self.logger.log("WebSocket manager not initialized - contract_id not available yet", "INFO")

        except Exception as e:
            self.logger.log(f"Error connecting to Lighter: {e}", "ERROR")
            raise

    async def initialize_websocket_manager(self) -> None:
        """Initialize WebSocket manager after contract_id is set."""
        try:
            if not hasattr(self, 'ws_manager') or self.ws_manager is None:
                if hasattr(self.config, 'contract_id') and self.config.contract_id:
                    # Add market config to config for WebSocket manager
                    self.config.market_index = self.config.contract_id
                    self.config.account_index = self.account_index
                    self.config.lighter_client = self.lighter_client

                    # Initialize WebSocket manager (using custom implementation)
                    self.ws_manager = LighterCustomWebSocketManager(
                        config=self.config,
                        order_update_callback=self._handle_websocket_order_update
                    )

                    # Set logger for WebSocket manager
                    self.ws_manager.set_logger(self.logger)

                    # Start WebSocket connection in background task
                    asyncio.create_task(self.ws_manager.connect())
                    # Wait a moment for connection to establish
                    await asyncio.sleep(2)
                    self.logger.log(f"WebSocket manager initialized with contract_id: {self.config.contract_id}", "INFO")
                else:
                    self.logger.log("Cannot initialize WebSocket manager - contract_id not available", "WARNING")
        except Exception as e:
            self.logger.log(f"Error initializing WebSocket manager: {e}", "ERROR")

    async def disconnect(self) -> None:
        """Disconnect from Lighter."""
        try:
            if hasattr(self, 'ws_manager') and self.ws_manager:
                await self.ws_manager.disconnect()

            # Close shared API client
            if self.api_client:
                await self.api_client.close()
                self.api_client = None
        except Exception as e:
            self.logger.log(f"Error during Lighter disconnect: {e}", "ERROR")

    def get_exchange_name(self) -> str:
        """Get the exchange name."""
        return "lighter"

    def setup_order_update_handler(self, handler) -> None:
        """Setup order update handler for WebSocket."""
        self._order_update_handler = handler

    def _handle_websocket_order_update(self, order_data_list: List[Dict[str, Any]]):
        """Handle order updates from WebSocket."""
        for order_data in order_data_list:
            if order_data['market_index'] != self.config.contract_id:
                continue

            side = 'sell' if order_data['is_ask'] else 'buy'
            if side == self.config.close_order_side:
                order_type = "CLOSE"
            else:
                order_type = "OPEN"

            order_id = order_data['order_index']
            status = order_data['status'].upper()
            filled_size = Decimal(order_data['filled_base_amount'])
            size = Decimal(order_data['initial_base_amount'])
            price = Decimal(order_data['price'])
            remaining_size = Decimal(order_data['remaining_base_amount'])

            if order_id in self.orders_cache.keys():
                if (self.orders_cache[order_id]['status'] == 'OPEN' and
                        status == 'OPEN' and
                        filled_size == self.orders_cache[order_id]['filled_size']):
                    continue
                elif status in ['FILLED', 'CANCELED']:
                    del self.orders_cache[order_id]
                else:
                    self.orders_cache[order_id]['status'] = status
                    self.orders_cache[order_id]['filled_size'] = filled_size
            elif status == 'OPEN':
                self.orders_cache[order_id] = {'status': status, 'filled_size': filled_size}

            if status == 'OPEN' and filled_size > 0:
                status = 'PARTIALLY_FILLED'

            if status == 'OPEN':
                self.logger.log(f"[{order_type}] [{order_id}] {status} "
                                f"{size} @ {price}", "INFO")
            else:
                self.logger.log(f"[{order_type}] [{order_id}] {status} "
                                f"{filled_size} @ {price}", "INFO")

            if order_data['client_order_index'] == self.current_order_client_id or order_type == 'OPEN':
                current_order = OrderInfo(
                    order_id=order_id,
                    side=side,
                    size=size,
                    price=price,
                    status=status,
                    filled_size=filled_size,
                    remaining_size=remaining_size,
                    cancel_reason=''
                )
                self.current_order = current_order

            if status in ['FILLED', 'CANCELED']:
                self.logger.log_transaction(order_id, side, filled_size, price, status)

            # Cache last filled price per market and side for avg_price fallback
            try:
                if status == 'FILLED' and filled_size > 0:
                    market_id = order_data['market_index']
                    if market_id not in self._last_fill_price_by_market:
                        self._last_fill_price_by_market[market_id] = {}
                    self._last_fill_price_by_market[market_id][side] = price
                    self.logger.log(f"Cached last fill price: market={market_id}, side={side}, price={price}", "DEBUG")
            except Exception:
                pass

            # Call the order update handler for trading_bot.py
            if self._order_update_handler:
                self._order_update_handler({
                    'order_id': order_id,
                    'side': side,
                    'order_type': order_type,
                    'status': status,
                    'size': size,
                    'price': price,
                    'contract_id': self.config.contract_id,
                    'filled_size': filled_size
                })

    @query_retry(default_return=(0, 0))
    async def fetch_bbo_prices(self, contract_id: str) -> Tuple[Decimal, Decimal]:
        """Get best bid/ask prices, prefer WebSocket with REST fallback."""
        # Use WebSocket data if available and valid
        if (hasattr(self, 'ws_manager') and self.ws_manager.best_bid and self.ws_manager.best_ask):
            try:
                best_bid = Decimal(str(self.ws_manager.best_bid))
                best_ask = Decimal(str(self.ws_manager.best_ask))
                if best_bid > 0 and best_ask > 0 and best_bid < best_ask:
                    self.logger.log(f"WS BBO: bid={best_bid}, ask={best_ask}", "DEBUG")
                    return best_bid, best_ask
                else:
                    self.logger.log("WebSocket bid/ask invalid, trying REST fallback", "WARNING")
            except Exception:
                self.logger.log("Failed to parse WebSocket bid/ask, trying REST fallback", "WARNING")

        # REST fallback
        try:
            best_bid, best_ask = await self._fetch_bbo_prices_rest_fallback(contract_id)
            if best_bid > 0 and best_ask > 0 and best_bid < best_ask:
                self.logger.log(f"REST BBO: bid={best_bid}, ask={best_ask}", "DEBUG")
                return best_bid, best_ask
            else:
                self.logger.log("REST fallback bid/ask invalid", "ERROR")
                raise ValueError("Invalid bid/ask prices from REST fallback")
        except Exception as e:
            self.logger.log(f"Failed to fetch valid bid/ask: {e}", "ERROR")
            raise

    async def _fetch_bbo_prices_rest_fallback(self, contract_id: str) -> Tuple[Decimal, Decimal]:
        """Fetch best bid/ask via REST as a fallback."""
        # Ensure API client is initialized
        if self.api_client is None:
            await self._initialize_lighter_client()

        order_api = lighter.OrderApi(self.api_client)

        # Prefer detailed order book endpoint
        try:
            details = await order_api.order_book_details(market_id=contract_id)
            if details and hasattr(details, 'order_book_details') and len(details.order_book_details) > 0:
                d = details.order_book_details[0]
                best_bid = Decimal('0')
                best_ask = Decimal('0')

                # Try bids/asks lists
                bids = getattr(d, 'bids', None)
                asks = getattr(d, 'asks', None)
                if isinstance(bids, list) and len(bids) > 0 and isinstance(asks, list) and len(asks) > 0:
                    try:
                        bid_entry = bids[0]
                        ask_entry = asks[0]
                        # Support dict or object entries
                        bid_price = Decimal(str(bid_entry.get('price', bid_entry.get('p', 0)))) if isinstance(bid_entry, dict) else Decimal(str(getattr(bid_entry, 'price', getattr(bid_entry, 'p', 0))))
                        ask_price = Decimal(str(ask_entry.get('price', ask_entry.get('p', 0)))) if isinstance(ask_entry, dict) else Decimal(str(getattr(ask_entry, 'price', getattr(ask_entry, 'p', 0))))
                        best_bid = bid_price
                        best_ask = ask_price
                    except Exception:
                        pass

                # Try direct fields
                for attr_name in ['best_bid_price', 'best_bid', 'bid_price', 'bid']:
                    if best_bid <= 0 and hasattr(d, attr_name):
                        try:
                            best_bid = Decimal(str(getattr(d, attr_name)))
                        except Exception:
                            pass
                for attr_name in ['best_ask_price', 'best_ask', 'ask_price', 'ask']:
                    if best_ask <= 0 and hasattr(d, attr_name):
                        try:
                            best_ask = Decimal(str(getattr(d, attr_name)))
                        except Exception:
                            pass

                if best_bid > 0 and best_ask > 0:
                    return best_bid, best_ask
        except Exception:
            # Fall through to simplified order_books endpoint
            pass

        order_books = await order_api.order_books()
        for market in getattr(order_books, 'order_books', []) or []:
            if getattr(market, 'market_id', None) == contract_id or getattr(market, 'symbol', None) == self.config.ticker:
                # Try multiple field names
                candidates_bid = ['best_bid_price', 'best_bid', 'bid_price', 'bid']
                candidates_ask = ['best_ask_price', 'best_ask', 'ask_price', 'ask']
                best_bid = Decimal('0')
                best_ask = Decimal('0')
                for attr in candidates_bid:
                    if hasattr(market, attr):
                        try:
                            best_bid = Decimal(str(getattr(market, attr)))
                            break
                        except Exception:
                            continue
                for attr in candidates_ask:
                    if hasattr(market, attr):
                        try:
                            best_ask = Decimal(str(getattr(market, attr)))
                            break
                        except Exception:
                            continue
                return best_bid, best_ask

        # If all fails, return zeros to indicate invalid
        return Decimal('0'), Decimal('0')

    async def _submit_order_with_retry(self, order_params: Dict[str, Any]) -> OrderResult:
        """Submit an order with Lighter using official SDK."""
        # Ensure client is initialized
        if self.lighter_client is None:
            raise ValueError("Lighter client not initialized. Call connect() first.")

        # Create order using official SDK
        try:
            result = await self.lighter_client.create_order(**order_params)
            
            # Handle None response from SDK - this fixes the original NoneType error
            if result is None:
                return OrderResult(
                    success=False,
                    order_id=str(order_params.get('client_order_index', 'unknown')),
                    error_message="SDK returned None response - possible network or API issue"
                )
            
            # Unpack the result tuple safely
            if not isinstance(result, tuple) or len(result) < 3:
                return OrderResult(
                    success=False,
                    order_id=str(order_params.get('client_order_index', 'unknown')),
                    error_message=f"Unexpected SDK response format: {type(result)}"
                )
                
            create_order, tx_hash, error = result
                
        except Exception as e:
            return OrderResult(
                success=False,
                order_id=str(order_params.get('client_order_index', 'unknown')),
                error_message=f"Order creation exception: {e}"
            )
            
        # Check for explicit error from SDK
        if error is not None:
            # Handle case where error might not have 'code' attribute - this fixes the .code error
            error_msg = f"Order creation error: {error.code}" if hasattr(error, 'code') else f"Order creation error: {error}"
            return OrderResult(
                success=False, 
                order_id=str(order_params['client_order_index']),
                error_message=error_msg
            )

        # Success case
        return OrderResult(success=True, order_id=str(order_params['client_order_index']))

    async def place_limit_order(self, contract_id: str, quantity: Decimal, price: Decimal,
                                side: str) -> OrderResult:
        """Place a post only order with Lighter using official SDK."""
        # Ensure client is initialized
        if self.lighter_client is None:
            await self._initialize_lighter_client()

        # Determine order side and price
        if side.lower() == 'buy':
            is_ask = False
        elif side.lower() == 'sell':
            is_ask = True
        else:
            raise Exception(f"Invalid side: {side}")

        # Generate unique client order index
        client_order_index = int(time.time() * 1000) % 1000000  # Simple unique ID
        self.current_order_client_id = client_order_index

        # Create order parameters
        order_params = {
            'market_index': self.config.contract_id,
            'client_order_index': client_order_index,
            'base_amount': int(quantity * self.base_amount_multiplier),
            'price': int(price * self.price_multiplier),
            'is_ask': is_ask,
            'order_type': self.lighter_client.ORDER_TYPE_LIMIT,
            'time_in_force': self.lighter_client.ORDER_TIME_IN_FORCE_GOOD_TILL_TIME,
            'reduce_only': False,
            'trigger_price': 0,
        }

        order_result = await self._submit_order_with_retry(order_params)
        return order_result

    async def place_market_order(self, contract_id: str, quantity: Decimal, direction: str, prefer_ws: bool = False, reduce_only: bool = False) -> OrderResult:
        """
        Place a market order with Lighter using official SDK.

        Uses the official create_market_order method with avg_execution_price parameter.
        Confirms via WebSocket updates when available, falling back to position delta verification.

        Args:
            contract_id: The contract identifier (market_index in Lighter)
            quantity: Order quantity
            direction: 'buy' or 'sell'
            prefer_ws: Prefer WebSocket-first confirmation if supported
            reduce_only: Whether this is a reduce-only order

        Returns:
            OrderResult: Result of the order placement
        """
        self.logger.info(f"[MARKET] Starting market order placement - contract: {contract_id}, quantity: {quantity}, direction: {direction}, reduce_only: {reduce_only}")
        
        # Ensure client is initialized
        if self.lighter_client is None:
            await self._initialize_lighter_client()

        # Validate direction and map to ask/bid
        if direction.lower() == 'buy':
            is_ask = False
        elif direction.lower() == 'sell':
            is_ask = True
        else:
            return OrderResult(success=False, error_message=f"Invalid direction: {direction}")

        # Capture pre-order position for fallback verification
        try:
            pre_position = await self.get_account_positions()
        except Exception as e:
            pre_position = None

        # Generate client order index and set current tracking fields
        client_order_index = int(time.time() * 1000) % 1000000
        self.current_order_client_id = client_order_index
        self.current_order = None

        # Use the official SDK create_market_order_limited_slippage method for better slippage control
        # Set reasonable slippage tolerance (0.2% = 0.002)
        max_slippage = 0.003  # 0.2% slippage tolerance
        
        try:
            self.logger.info(f"[MARKET] Placing {direction} market order for {quantity} with {max_slippage*100}% slippage tolerance")
            
            result = await self.lighter_client.create_market_order_limited_slippage(
                market_index=self.config.contract_id,
                client_order_index=client_order_index,
                base_amount=int(quantity * self.base_amount_multiplier),
                max_slippage=max_slippage,
                is_ask=is_ask,
                reduce_only=reduce_only
            )
            
            self.logger.info(f"[MARKET] Market order submitted successfully: {result}")
            order_result = OrderResult(success=True, order_id=str(client_order_index))
            
        except Exception as e:
            self.logger.error(f"[MARKET] Failed to place market order: {e}")
            return OrderResult(success=False, error_message=f"Market order failed: {e}")
        
        if not order_result.success:
            return OrderResult(success=False, error_message=f"[MARKET] {order_result.error_message}")

        # Attempt quick confirmation via WebSocket updates
        start_time = time.time()
        ws_confirmed = False
        
        if prefer_ws:
            for i in range(50):  # ~5s at 100ms intervals
                await asyncio.sleep(0.1)
                if self.current_order is not None:
                    status = self.current_order.status
                    if status in ['FILLED', 'CANCELED']:
                        ws_confirmed = True
                        break

        # If WS not preferred or not confirmed, do a short general wait for any update
        if not ws_confirmed:
            for i in range(50):
                await asyncio.sleep(0.1)
                if self.current_order is not None:
                    break

        if self.current_order is not None:
            # Use data from WS-tracked current order
            return OrderResult(
                success=True,
                order_id=self.current_order.order_id,
                side=direction,
                size=quantity,
                price=self.current_order.price,
                status=self.current_order.status,
                filled_size=self.current_order.filled_size,
            )

        # Fallback: verify by position delta if available
        if pre_position is not None:
            try:
                post_position = pre_position
                for i in range(10):  # up to ~5s
                    await asyncio.sleep(0.5)
                    post_position = await self.get_account_positions()
                    if post_position != pre_position:
                        break

                delta = (pre_position - post_position).copy_abs()
                
                if delta > Decimal('0'):
                    status = 'FILLED' if delta >= quantity else 'PARTIALLY_FILLED'
                    return OrderResult(
                        success=True,
                        order_id=str(client_order_index),
                        side=direction,
                        size=quantity,
                        price=None,
                        status=status,
                        filled_size=delta,
                    )
            except Exception as e:
                self.logger.error(f"[MARKET] Position verification failed: {e}")
        else:
            self.logger.warning("[MARKET] No pre_position available for fallback verification")

        # If we reach here, order placed but confirmation pending
        return OrderResult(success=True, order_id=str(client_order_index), error_message="Market order placed; awaiting confirmation")

    async def place_open_order(self, contract_id: str, quantity: Decimal, direction: str) -> OrderResult:
        """Place an open order with Lighter using official SDK."""

        self.current_order = None
        self.current_order_client_id = None
        order_price = await self.get_order_price(direction)

        order_price = self.round_to_tick(order_price)
        order_result = await self.place_limit_order(contract_id, quantity, order_price, direction)
        if not order_result.success:
            raise Exception(f"[OPEN] Error placing order: {order_result.error_message}")

        start_time = time.time()
        order_status = 'OPEN'

        # While waiting for order to be filled
        while time.time() - start_time < 10 and order_status != 'FILLED':
            await asyncio.sleep(0.1)
            if self.current_order is not None:
                order_status = self.current_order.status

        return OrderResult(
            success=True,
            order_id=self.current_order.order_id,
            side=direction,
            size=quantity,
            price=order_price,
            status=self.current_order.status
        )


    async def _get_active_close_orders(self, contract_id: str) -> int:
        """Get active close orders for a contract using official SDK."""
        active_orders = await self.get_active_orders(contract_id)
        active_close_orders = 0
        for order in active_orders:
            if order.side == self.config.close_order_side:
                active_close_orders += 1
        return active_close_orders

    async def place_close_order(self, contract_id: str, quantity: Decimal, price: Decimal, side: str) -> OrderResult:
        """Place a close order with Lighter using official SDK."""
        self.current_order = None
        self.current_order_client_id = None
        order_result = await self.place_limit_order(contract_id, quantity, price, side)

        # wait for 5 seconds to ensure order is placed
        await asyncio.sleep(5)
        if order_result.success:
            return OrderResult(
                success=True,
                order_id=order_result.order_id,
                side=side,
                size=quantity,
                price=price,
                status='OPEN'
            )
        else:
            raise Exception(f"[CLOSE] Error placing order: {order_result.error_message}")
    
    async def get_order_price(self, side: str = '') -> Decimal:
        """Get the price of an order with Lighter using official SDK."""
        # Get current market prices
        best_bid, best_ask = await self.fetch_bbo_prices(self.config.contract_id)
        if best_bid <= 0 or best_ask <= 0 or best_bid >= best_ask:
            self.logger.log("Invalid bid/ask prices", "ERROR")
            raise ValueError("Invalid bid/ask prices")

        order_price = (best_bid + best_ask) / 2

        active_orders = await self.get_active_orders(self.config.contract_id)
        close_orders = [order for order in active_orders if order.side == self.config.close_order_side]
        for order in close_orders:
            if side == 'buy':
                order_price = min(order_price, order.price - self.config.tick_size)
            else:
                order_price = max(order_price, order.price + self.config.tick_size)

        return order_price

    async def cancel_order(self, order_id: str) -> OrderResult:
        """Cancel an order with Lighter."""
        # Ensure client is initialized
        if self.lighter_client is None:
            await self._initialize_lighter_client()

        # Cancel order using official SDK
        cancel_order, tx_hash, error = await self.lighter_client.cancel_order(
            market_index=self.config.contract_id,
            order_index=int(order_id)  # Assuming order_id is the order index
        )

        if error is not None:
            return OrderResult(success=False, error_message=f"Cancel order error: {error}")

        if tx_hash:
            return OrderResult(success=True)
        else:
            return OrderResult(success=False, error_message='Failed to send cancellation transaction')

    async def get_order_info(self, order_id: str) -> Optional[OrderInfo]:
        """Get order information from Lighter using official SDK."""
        try:
            # Use shared API client to get account info
            account_api = lighter.AccountApi(self.api_client)

            # Get account orders
            account_data = await account_api.account(by="index", value=str(self.account_index))

            # Check if we have accounts data
            if not account_data.accounts:
                return None

            # Look for the specific order in account positions
            for position in account_data.accounts[0].positions:
                if position.symbol == self.config.ticker:
                    position_amt = abs(float(position.position))
                    if position_amt > 0.001:  # Only include significant positions
                        return OrderInfo(
                            order_id=order_id,
                            side="buy" if float(position.position) > 0 else "sell",
                            size=Decimal(str(position_amt)),
                            price=Decimal(str(position.avg_price)),
                            status="FILLED",  # Positions are filled orders
                            filled_size=Decimal(str(position_amt)),
                            remaining_size=Decimal('0')
                        )

            return None

        except Exception as e:
            self.logger.log(f"Error getting order info: {e}", "ERROR")
            return None

    @query_retry(reraise=True)
    async def _fetch_orders_with_retry(self) -> List[Dict[str, Any]]:
        """Get orders using official SDK."""
        # Ensure client is initialized
        if self.lighter_client is None:
            await self._initialize_lighter_client()

        # Generate auth token for API call
        auth_token, error = self.lighter_client.create_auth_token_with_expiry()
        if error is not None:
            self.logger.log(f"Error creating auth token: {error}", "ERROR")
            raise ValueError(f"Error creating auth token: {error}")

        # Use OrderApi to get active orders
        order_api = lighter.OrderApi(self.api_client)

        # Get active orders for the specific market
        orders_response = await order_api.account_active_orders(
            account_index=self.account_index,
            market_id=self.config.contract_id,
            auth=auth_token
        )

        if not orders_response:
            self.logger.log("Failed to get orders", "ERROR")
            raise ValueError("Failed to get orders")

        return orders_response.orders

    async def get_active_orders(self, contract_id: str) -> List[OrderInfo]:
        """Get active orders for a contract using official SDK."""
        order_list = await self._fetch_orders_with_retry()

        # Filter orders for the specific market
        contract_orders = []
        for order in order_list:
            # Convert Lighter Order to OrderInfo
            side = "sell" if order.is_ask else "buy"
            size = Decimal(order.initial_base_amount)
            price = Decimal(order.price)

            # Only include orders with remaining size > 0
            if size > 0:
                contract_orders.append(OrderInfo(
                    order_id=str(order.order_index),
                    side=side,
                    size=Decimal(order.remaining_base_amount),  # FIXME: This is wrong. Should be size
                    price=price,
                    status=order.status.upper(),
                    filled_size=Decimal(order.filled_base_amount),
                    remaining_size=Decimal(order.remaining_base_amount)
                ))

        return contract_orders

    @query_retry(reraise=True)
    async def _fetch_positions_with_retry(self) -> List[Dict[str, Any]]:
        """Get positions using official SDK."""
        # Use shared API client
        account_api = lighter.AccountApi(self.api_client)

        # Get account info
        account_data = await account_api.account(by="index", value=str(self.account_index))

        if not account_data or not account_data.accounts:
            self.logger.log("Failed to get positions", "ERROR")
            raise ValueError("Failed to get positions")

        return account_data.accounts[0].positions

    async def get_account_positions(self) -> Decimal:
        """Get account positions using official SDK."""
        # Get account info which includes positions
        positions = await self._fetch_positions_with_retry()

        # Find position for current market
        for position in positions:
            try:
                pos_market_id = self._extract_market_id(position)
                if pos_market_id is None:
                    continue
                cfg_market_id_int = int(self.config.contract_id)
                if pos_market_id == cfg_market_id_int:
                    return self._extract_position_size(position)
            except Exception:
                continue

        return Decimal(0)

    async def get_contract_attributes(self) -> Tuple[str, Decimal]:
        """Get contract ID for a ticker."""
        ticker = self.config.ticker
        if len(ticker) == 0:
            self.logger.log("Ticker is empty", "ERROR")
            raise ValueError("Ticker is empty")

        order_api = lighter.OrderApi(self.api_client)
        # Get all order books to find the market for our ticker
        order_books = await order_api.order_books()

        # Find the market that matches our ticker
        market_info = None
        for market in order_books.order_books:
            if market.symbol == ticker:
                market_info = market
                break

        if market_info is None:
            self.logger.log("Failed to get markets", "ERROR")
            raise ValueError("Failed to get markets")

        market_summary = await order_api.order_book_details(market_id=market_info.market_id)
        order_book_details = market_summary.order_book_details[0]
        # Set contract_id to market name (Lighter uses market IDs as identifiers)
        self.config.contract_id = market_info.market_id
        self.base_amount_multiplier = pow(10, market_info.supported_size_decimals)
        self.price_multiplier = pow(10, market_info.supported_price_decimals)

        try:
            self.config.tick_size = Decimal("1") / (Decimal("10") ** order_book_details.price_decimals)
        except Exception:
            self.logger.log("Failed to get tick size", "ERROR")
            raise ValueError("Failed to get tick size")

        # Initialize WebSocket manager now that contract_id is set
        await self.initialize_websocket_manager()

        return self.config.contract_id, self.config.tick_size

    async def get_account_networth(self) -> Decimal:
        """
        Get account net worth for drawdown monitoring.
        Net worth = collateral (cached) + unrealized PnL (fresh).
        
        Returns:
            Decimal: Account net worth for drawdown monitoring
        """
        try:
            current_time = time.time()
            time_since_last_call = current_time - self._last_api_call_time

            # Ensure lighter client is initialized
            if self.lighter_client is None:
                await self._initialize_lighter_client()

            account_api = lighter.AccountApi(self.lighter_client.api_client)

            # Collateral: use cache if valid; otherwise refresh via API (rate limited)
            use_cached_collateral = False
            collateral = Decimal('0')
            account_data = None

            if (self._collateral_cache is not None and
                current_time - self._collateral_cache_time < self._networth_cache_duration and
                time_since_last_call < self._min_api_interval):
                collateral = self._collateral_cache
                use_cached_collateral = True
            else:
                # If too soon since last API call and no cache is available, wait
                if time_since_last_call < self._min_api_interval and self._collateral_cache is None:
                    wait_time = self._min_api_interval - time_since_last_call
                    self.logger.log(f"Rate limit protection: waiting {wait_time:.1f}s before collateral API call", "DEBUG")
                    await asyncio.sleep(wait_time)

                # Update last API call time
                self._last_api_call_time = time.time()

                # Get account data
                account_data = await account_api.account(by="index", value=str(self.account_index))
                if not account_data or not account_data.accounts:
                    self.logger.log("Failed to get account data", "ERROR")
                    # Return cached value if available, otherwise 0
                    return self._networth_cache if self._networth_cache is not None else Decimal('0')

                account = account_data.accounts[0]
                if hasattr(account, 'collateral') and account.collateral is not None:
                    collateral = Decimal(str(account.collateral))
                else:
                    collateral = Decimal('0')
                # Update collateral cache
                self._collateral_cache = collateral
                self._collateral_cache_time = time.time()

            # Unrealized PnL: only use native unrealized_pnl fields from positions
            unrealized_pnl = Decimal('0')
            try:
                # Use positions from fresh account_data if available to avoid extra API call
                if account_data is not None and hasattr(account_data.accounts[0], 'positions'):
                    positions = account_data.accounts[0].positions
                else:
                    positions = await self._fetch_positions_with_retry()

                # Log positions for debugging
                try:
                    self.logger.log(f"Positions count: {len(positions)}", "DEBUG")
                except Exception:
                    pass

                # Aggregate unrealized_pnl from positions that match current market
                matched_any = False
                cfg_market_id_int = int(self.config.contract_id)
                for position in positions:
                    try:
                        pos_market_id_int = self._extract_market_id(position)
                        if pos_market_id_int is None or pos_market_id_int != cfg_market_id_int:
                            continue

                        pos_unrealized_pnl = self._extract_unrealized_pnl(position)
                        if pos_unrealized_pnl is not None:
                            unrealized_pnl += pos_unrealized_pnl
                            matched_any = True
                            self.logger.log(f"Using position unrealized_pnl={pos_unrealized_pnl}", "DEBUG")
                            break
                    except Exception as inner_e:
                        self.logger.log(f"Error processing position for unrealized_pnl: {inner_e}", "WARNING")
                        continue

                if unrealized_pnl == 0:
                    if not positions or len(positions) == 0:
                        self.logger.log("PnL result is 0: no positions returned", "INFO")
                    elif not matched_any:
                        self.logger.log(
                            f"PnL result is 0: no matching position with unrealized_pnl for contract_id={self.config.contract_id}",
                            "INFO"
                        )
            except Exception as e:
                self.logger.log(f"Failed to aggregate unrealized PnL, using 0: {e}", "WARNING")
                unrealized_pnl = Decimal('0')

            total_networth = collateral + unrealized_pnl

            # Update net worth cache for emergency fallback paths
            self._networth_cache = total_networth
            self._networth_cache_time = time.time()

            if use_cached_collateral:
                self.logger.log(
                    f"Net worth (cached collateral): collateral={collateral}, unrealized_pnl={unrealized_pnl}, total={total_networth}",
                    "INFO"
                )
            else:
                self.logger.log(
                    f"Net worth (fresh collateral): collateral={collateral}, unrealized_pnl={unrealized_pnl}, total={total_networth}",
                    "INFO"
                )
            return total_networth
            
        except Exception as e:
            self.logger.log(f"Error fetching account net worth: {e}", "ERROR")
            # Return cached value if available, otherwise 0
            if self._networth_cache is not None:
                self.logger.log(f"Using cached value due to error: {self._networth_cache}", "WARNING")
                return self._networth_cache
            else:
                self.logger.log("No cached value available, returning 0", "WARNING")
                return Decimal('0')

    async def place_market_order_with_retry(self, contract_id: str, quantity: Decimal, direction: str, 
                                          max_retries: int = 5, initial_delay: float = 1.0) -> OrderResult:
        """
        Place a market order with built-in retry mechanism for hedge position closing.
        
        This method encapsulates the retry logic specifically for Lighter exchange,
        avoiding the need for trading_bot.py to handle exchange-specific retry mechanisms.
        
        Args:
            contract_id: The contract identifier
            quantity: Order quantity
            direction: 'buy' or 'sell'
            max_retries: Maximum number of retry attempts (default: 5)
            initial_delay: Initial delay between retries in seconds (default: 0.3)
            
        Returns:
            OrderResult: Final result after all retry attempts
        """
        retry_count = 0
        retry_delay = initial_delay
        
        self.logger.log(f"开始带重试机制的市价单: {direction} {quantity}, 最大重试次数: {max_retries}", "INFO")
        
        while retry_count <= max_retries:
            if retry_count > 0:
                self.logger.log(f"市价单重试 {retry_count}/{max_retries}", "INFO")
                await asyncio.sleep(retry_delay)
                
                # 在重试前检查持仓状态，如果已经没有持仓则无需继续
                try:
                    current_position = await self.get_account_positions()
                    if abs(current_position) == 0:
                        self.logger.log(f"检测到持仓已清零，无需继续重试", "INFO")
                        return OrderResult(
                            success=True,
                            order_id="position_cleared",
                            status="FILLED",
                            filled_size=quantity,
                            side=direction
                        )
                except Exception as e:
                    self.logger.log(f"检查持仓状态失败: {e}", "WARNING")
                    # 继续重试流程
            
            # 尝试下单
            try:
                self.logger.log(f"尝试市价单: {direction} {quantity}", "INFO")
                order_result = await self.place_market_order(
                    contract_id=contract_id,
                    quantity=quantity,
                    direction=direction,
                    reduce_only=True  # 对冲平仓通常是reduce_only
                )
                
                # 检查订单结果
                if order_result.success:
                    if order_result.status in ["FILLED", "PARTIALLY_FILLED"]:
                        filled_size = order_result.filled_size or 0
                        if filled_size > 0:
                            self.logger.log(f"市价单成功: 成交量 {filled_size}", "INFO")
                            return order_result
                    elif order_result.status == "PENDING":
                        # 如果是挂起状态，等待一段时间再检查持仓状态
                        self.logger.log(f"订单状态为PENDING，等待确认", "INFO")
                        await asyncio.sleep(2.0)
                        
                        try:
                            updated_position = await self.get_account_positions()
                            if abs(updated_position) == 0:
                                self.logger.log(f"市价单重试成功: 持仓已清零", "INFO")
                                return OrderResult(
                                    success=True,
                                    order_id=order_result.order_id,
                                    status="FILLED",
                                    filled_size=quantity,
                                    side=direction
                                )
                        except Exception as e:
                            self.logger.log(f"检查更新后持仓状态失败: {e}", "WARNING")
                
                # 如果到这里说明订单没有成功或部分成功，准备重试
                retry_count += 1
                retry_delay *= 1.5  # 指数退避
                
                if retry_count <= max_retries:
                    self.logger.log(f"市价单重试 {retry_count} 失败: {order_result.error_message or '未知错误'}", "WARNING")
                else:
                    self.logger.log(f"市价单重试全部失败，已达到最大重试次数 {max_retries}", "ERROR")
                    return OrderResult(
                        success=False,
                        error_message=f"市价单重试全部失败: {order_result.error_message or '未知错误'}"
                    )
                    
            except Exception as e:
                retry_count += 1
                retry_delay *= 1.5
                
                if retry_count <= max_retries:
                    self.logger.log(f"市价单异常重试 {retry_count}: {e}", "WARNING")
                else:
                    self.logger.log(f"市价单异常重试全部失败: {e}", "ERROR")
                    return OrderResult(success=False, error_message=f"市价单异常: {e}")
        
        # 理论上不应该到达这里
        return OrderResult(success=False, error_message="重试机制异常结束")

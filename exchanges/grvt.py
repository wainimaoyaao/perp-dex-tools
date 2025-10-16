"""
GRVT exchange client implementation.
"""

import os
import asyncio
import time
from decimal import Decimal
from typing import Dict, Any, List, Optional, Tuple
from pysdk.grvt_ccxt import GrvtCcxt
from pysdk.grvt_ccxt_ws import GrvtCcxtWS
from pysdk.grvt_ccxt_env import GrvtEnv, GrvtWSEndpointType

from .base import BaseExchangeClient, OrderResult, OrderInfo, query_retry
from helpers.logger import TradingLogger


class GrvtClient(BaseExchangeClient):
    """GRVT exchange client implementation."""

    def __init__(self, config: Dict[str, Any]):
        """Initialize GRVT client."""
        super().__init__(config)

        # GRVT credentials from environment
        self.trading_account_id = os.getenv('GRVT_TRADING_ACCOUNT_ID')
        self.private_key = os.getenv('GRVT_PRIVATE_KEY')
        self.api_key = os.getenv('GRVT_API_KEY')
        self.environment = os.getenv('GRVT_ENVIRONMENT', 'prod')

        if not self.trading_account_id or not self.private_key or not self.api_key:
            raise ValueError(
                "GRVT_TRADING_ACCOUNT_ID, GRVT_PRIVATE_KEY, and GRVT_API_KEY must be set in environment variables"
            )

        # Convert environment string to proper enum
        env_map = {
            'prod': GrvtEnv.PROD,
            'testnet': GrvtEnv.TESTNET,
            'staging': GrvtEnv.STAGING,
            'dev': GrvtEnv.DEV
        }
        self.env = env_map.get(self.environment.lower(), GrvtEnv.PROD)

        # Initialize logger
        self.logger = TradingLogger(exchange="grvt", ticker=self.config.ticker, log_to_console=False)

        # Initialize GRVT clients
        self._initialize_grvt_clients()

        self._order_update_handler = None
        self._ws_client = None
        self._order_update_callback = None
        
        # Partial fill tracking
        self.partially_filled_size = 0
        self.partially_filled_avg_price = 0

        # Internal WS tracking for fallback flows
        self._ws_update_event = asyncio.Event()
        self._last_order_update: Optional[Dict[str, Any]] = None

        # Networth caching mechanism (similar to Lighter)
        self._networth_cache: Optional[Decimal] = None
        self._networth_cache_time: Optional[float] = None
        self._networth_cache_duration = 5.0  # Cache for 5 seconds

    def _initialize_grvt_clients(self) -> None:
        """Initialize the GRVT REST and WebSocket clients."""
        try:
            # Parameters for GRVT SDK
            parameters = {
                'trading_account_id': self.trading_account_id,
                'private_key': self.private_key,
                'api_key': self.api_key
            }

            # Initialize REST client
            self.rest_client = GrvtCcxt(
                env=self.env,
                parameters=parameters
            )

        except Exception as e:
            raise ValueError(f"Failed to initialize GRVT client: {e}")

    def _validate_config(self) -> None:
        """Validate GRVT configuration."""
        required_env_vars = ['GRVT_TRADING_ACCOUNT_ID', 'GRVT_PRIVATE_KEY', 'GRVT_API_KEY']
        missing_vars = [var for var in required_env_vars if not os.getenv(var)]
        if missing_vars:
            raise ValueError(f"Missing required environment variables: {missing_vars}")

    async def connect(self) -> None:
        """Connect to GRVT WebSocket."""
        try:
            # Initialize WebSocket client - match the working test implementation
            loop = asyncio.get_running_loop()

            # Import logger from pysdk like in the test file
            from pysdk.grvt_ccxt_logging_selector import logger

            # Parameters for GRVT SDK - match test file structure
            parameters = {
                'api_key': self.api_key,
                'trading_account_id': self.trading_account_id,
                'api_ws_version': 'v1',
                'private_key': self.private_key
            }

            self._ws_client = GrvtCcxtWS(
                env=self.env,
                loop=loop,
                logger=logger,  # Add logger parameter like in test file
                parameters=parameters
            )

            # Initialize and connect
            await self._ws_client.initialize()
            await asyncio.sleep(2)  # Wait for connection to establish

            # If an order update callback was set before connect, subscribe now
            if self._order_update_callback is not None:
                asyncio.create_task(self._subscribe_to_orders(self._order_update_callback))
                self.logger.log(f"Deferred subscription started for {self.config.contract_id}", "INFO")

        except Exception as e:
            self.logger.log(f"Error connecting to GRVT WebSocket: {e}", "ERROR")
            raise

    async def disconnect(self) -> None:
        """Disconnect from GRVT."""
        try:
            if self._ws_client:
                await self._ws_client.__aexit__()
        except Exception as e:
            self.logger.log(f"Error during GRVT disconnect: {e}", "ERROR")

    def get_exchange_name(self) -> str:
        """Get the exchange name."""
        return "grvt"

    def setup_order_update_handler(self, handler) -> None:
        """Setup order update handler for WebSocket."""
        self._order_update_handler = handler

        async def order_update_callback(message: Dict[str, Any]):
            """Handle order updates from WebSocket - match working test implementation."""
            # Log raw message for debugging
            self.logger.log(f"Received WebSocket message: {message}", "DEBUG")
            self.logger.log("**************************************************", "DEBUG")
            try:
                # Parse the message structure - match the working test implementation exactly
                if 'feed' in message:
                    data = message.get('feed', {})
                    leg = data.get('legs', [])[0] if data.get('legs') else None

                    if isinstance(data, dict) and leg:
                        contract_id = leg.get('instrument', '')
                        if contract_id != self.config.contract_id:
                            return

                        order_state = data.get('state', {})
                        # Extract order data using the exact structure from test
                        order_id = data.get('order_id', '')
                        status = order_state.get('status', '')
                        side = 'buy' if leg.get('is_buying_asset') else 'sell'
                        size = leg.get('size', '0')
                        price = leg.get('limit_price', '0')
                        filled_size = order_state.get('traded_size')[0] if order_state.get('traded_size') else '0'

                        if order_id and status:
                            # Determine order type based on side
                            if side == self.config.close_order_side:
                                order_type = "CLOSE"
                            else:
                                order_type = "OPEN"

                            # Map GRVT status to our status
                            status_map = {
                                'OPEN': 'OPEN',
                                'FILLED': 'FILLED',
                                'CANCELLED': 'CANCELED',
                                'REJECTED': 'CANCELED'
                            }
                            mapped_status = status_map.get(status, status)

                            # Handle partially filled orders
                            if status == 'OPEN' and Decimal(filled_size) > 0:
                                mapped_status = "PARTIALLY_FILLED"

                            if mapped_status in ['OPEN', 'PARTIALLY_FILLED', 'FILLED', 'CANCELED']:
                                # Store last update for internal fallback tracking
                                try:
                                    self._last_order_update = {
                                        'order_id': order_id,
                                        'side': side,
                                        'status': mapped_status,
                                        'size': size,
                                        'price': price,
                                        'contract_id': contract_id,
                                        'filled_size': filled_size,
                                        'timestamp': time.time(),
                                    }
                                    # Signal awaiting coroutines
                                    self._ws_update_event.set()
                                except Exception:
                                    pass
                                if self._order_update_handler:
                                    self._order_update_handler({
                                        'order_id': order_id,
                                        'side': side,
                                        'order_type': order_type,
                                        'status': mapped_status,
                                        'size': size,
                                        'price': price,
                                        'contract_id': contract_id,
                                        'filled_size': filled_size
                                    })
                            else:
                                self.logger.log(f"Ignoring order update with status: {mapped_status}", "DEBUG")
                        else:
                            self.logger.log(f"Order update missing order_id or status: {data}", "DEBUG")
                    else:
                        self.logger.log(f"Order update data is not dict or missing legs: {data}", "DEBUG")
                else:
                    # Handle other message types (position, fill, etc.)
                    method = message.get('method', 'unknown')
                    self.logger.log(f"Received non-order message: {method}", "DEBUG")

            except Exception as e:
                self.logger.log(f"Error handling order update: {e}", "ERROR")
                self.logger.log(f"Message that caused error: {message}", "ERROR")

        # Store callback for use after connect
        self._order_update_callback = order_update_callback

        # Subscribe immediately if WebSocket is already initialized; otherwise defer to connect()
        if self._ws_client:
            try:
                asyncio.create_task(self._subscribe_to_orders(self._order_update_callback))
                self.logger.log(f"Successfully initiated subscription to order updates for {self.config.contract_id}", "INFO")
            except Exception as e:
                self.logger.log(f"Error subscribing to order updates: {e}", "ERROR")
                raise
        else:
            self.logger.log("WebSocket not ready yet; will subscribe after connect()", "INFO")

    async def _subscribe_to_orders(self, callback):
        """Subscribe to order updates asynchronously."""
        try:
            await self._ws_client.subscribe(
                stream="order",
                callback=callback,
                ws_end_point_type=GrvtWSEndpointType.TRADE_DATA_RPC_FULL,
                params={"instrument": self.config.contract_id}
            )
            await asyncio.sleep(0)  # Small delay like in test file
            self.logger.log(f"Successfully subscribed to order updates for {self.config.contract_id}", "INFO")
        except Exception as e:
            self.logger.log(f"Error in subscription task: {e}", "ERROR")

    @query_retry(reraise=True)
    async def fetch_bbo_prices(self, contract_id: str) -> Tuple[Decimal, Decimal]:
        """Fetch best bid and offer prices for a contract."""
        try:
            # Get order book from GRVT
            order_book = self.rest_client.fetch_order_book(contract_id, limit=10)

            if not order_book or 'bids' not in order_book or 'asks' not in order_book:
                raise ValueError(f"Unable to get order book: {order_book}")

            bids = order_book.get('bids', [])
            asks = order_book.get('asks', [])

            if not bids or not asks:
                raise ValueError(f"Empty bids or asks in order book")

            best_bid = Decimal(bids[0]['price']) if bids and len(bids) > 0 else Decimal(0)
            best_ask = Decimal(asks[0]['price']) if asks and len(asks) > 0 else Decimal(0)

            if best_bid <= 0 or best_ask <= 0:
                raise ValueError(f"Invalid BBO prices: bid={best_bid}, ask={best_ask}")

            return best_bid, best_ask
        except Exception as e:
            self.logger.log(f"Error fetching BBO prices for {contract_id}: {e}", "ERROR")
            raise

    async def place_post_only_order(self, contract_id: str, quantity: Decimal, price: Decimal,
                                    side: str) -> OrderResult:
        """Place a post only order with GRVT using official SDK."""

        # Place the order using GRVT SDK
        order_result = self.rest_client.create_limit_order(
            symbol=contract_id,
            side=side,
            amount=quantity,
            price=price,
            params={'post_only': True}
        )
        if not order_result:
            raise Exception(f"[OPEN] Error placing order")

        client_order_id = order_result.get('metadata').get('client_order_id')
        order_status = order_result.get('state').get('status')
        order_status_start_time = time.time()
        order_info = await self.get_order_info(client_order_id=client_order_id)
        if order_info is not None:
            order_status = order_info.status

        while order_status in ['PENDING'] and time.time() - order_status_start_time < 10:
            # Check order status after a short delay
            await asyncio.sleep(0.05)
            order_info = await self.get_order_info(client_order_id=client_order_id)
            if order_info is not None:
                order_status = order_info.status

        if order_status == 'PENDING':
            raise Exception('Paradex Server Error: Order not processed after 10 seconds')
        else:
            return order_info

    async def get_order_price(self, direction: str) -> Decimal:
        """Get the price of an order with GRVT using official SDK."""
        best_bid, best_ask = await self.fetch_bbo_prices(self.config.contract_id)
        if best_bid <= 0 or best_ask <= 0:
            raise ValueError("Invalid bid/ask prices")

        if direction == 'buy':
            return best_ask - self.config.tick_size
        elif direction == 'sell':
            return best_bid + self.config.tick_size
        else:
            raise ValueError("Invalid direction")

    async def place_open_order(self, contract_id: str, quantity: Decimal, direction: str) -> OrderResult:
        """Place an open order with GRVT."""
        attempt = 0
        while True:
            attempt += 1
            if attempt % 5 == 0:
                self.logger.log(f"[OPEN] Attempt {attempt} to place order", "INFO")
                active_orders = await self.get_active_orders(contract_id)
                active_open_orders = 0
                for order in active_orders:
                    if order.side == self.config.direction:
                        active_open_orders += 1
                if active_open_orders > 1:
                    self.logger.log(f"[OPEN] ERROR: Active open orders abnormal: {active_open_orders}", "ERROR")
                    raise Exception(f"[OPEN] ERROR: Active open orders abnormal: {active_open_orders}")

            # Get current market prices
            try:
                best_bid, best_ask = await self.fetch_bbo_prices(contract_id)
            except Exception as e:
                self.logger.log(f"[OPEN] Error fetching BBO prices: {e}", "ERROR")
                return OrderResult(success=False, error_message=f'Failed to fetch BBO prices: {e}')

            if best_bid <= 0 or best_ask <= 0:
                return OrderResult(success=False, error_message='Invalid bid/ask prices')

            # Determine order side and price
            if direction == 'buy':
                order_price = best_ask - self.config.tick_size
            elif direction == 'sell':
                order_price = best_bid + self.config.tick_size
            else:
                raise Exception(f"[OPEN] Invalid direction: {direction}")

            # Place the order using GRVT SDK
            try:
                order_info = await self.place_post_only_order(contract_id, quantity, order_price, direction)
            except Exception as e:
                self.logger.log(f"[OPEN] Error placing order: {e}", "ERROR")
                continue

            order_status = order_info.status
            order_id = order_info.order_id

            if order_status == 'REJECTED':
                continue
            if order_status in ['OPEN', 'FILLED']:
                return OrderResult(
                    success=True,
                    order_id=order_id,
                    side=direction,
                    size=quantity,
                    price=order_price,
                    status=order_status
                )
            elif order_status == 'PENDING':
                raise Exception("[OPEN] Order not processed after 10 seconds")
            else:
                raise Exception(f"[OPEN] Unexpected order status: {order_status}")

    async def place_close_order(self, contract_id: str, quantity: Decimal, price: Decimal, side: str) -> OrderResult:
        """Place a close order with GRVT."""
        # Store original values for potential rollback
        original_partially_filled_size = self.partially_filled_size
        original_partially_filled_avg_price = self.partially_filled_avg_price
        
        # Merge with partially filled orders if any exist
        if self.partially_filled_size > 0:
            # Calculate weighted average price
            total_size = quantity + self.partially_filled_size
            merged_price = (
                (price * quantity + self.partially_filled_avg_price * self.partially_filled_size) / total_size
            )
            
            # Use merged values
            quantity = total_size
            price = merged_price
            
            self.logger.log(f"[CLOSE] Merging with partially filled order: "
                          f"size={self.partially_filled_size}, avg_price={self.partially_filled_avg_price}, "
                          f"new_total_size={quantity}, new_avg_price={price}", "INFO")
        
        # Get current market prices
        attempt = 0
        active_close_orders = await self._get_active_close_orders(contract_id)
        while True:
            attempt += 1
            if attempt % 5 == 0:
                self.logger.log(f"[CLOSE] Attempt {attempt} to place order", "INFO")
                current_close_orders = await self._get_active_close_orders(contract_id)

                if current_close_orders - active_close_orders > 1:
                    self.logger.log(f"[CLOSE] ERROR: Active close orders abnormal: "
                                    f"{active_close_orders}, {current_close_orders}", "ERROR")
                    raise Exception(f"[CLOSE] ERROR: Active close orders abnormal: "
                                    f"{active_close_orders}, {current_close_orders}")
                else:
                    active_close_orders = current_close_orders

            # Adjust price to ensure maker order
            best_bid, best_ask = await self.fetch_bbo_prices(contract_id)

            if side == 'sell' and price <= best_bid:
                adjusted_price = best_bid + self.config.tick_size
            elif side == 'buy' and price >= best_ask:
                adjusted_price = best_ask - self.config.tick_size
            else:
                adjusted_price = price

            adjusted_price = self.round_to_tick(adjusted_price)
            try:
                order_info = await self.place_post_only_order(contract_id, quantity, adjusted_price, side)
            except Exception as e:
                self.logger.log(f"[CLOSE] Error placing order: {e}", "ERROR")
                # Rollback partial fill state on error
                self.partially_filled_size = original_partially_filled_size
                self.partially_filled_avg_price = original_partially_filled_avg_price
                continue

            order_status = order_info.status
            order_id = order_info.order_id

            if order_status == 'REJECTED':
                # Rollback partial fill state on rejection
                self.partially_filled_size = original_partially_filled_size
                self.partially_filled_avg_price = original_partially_filled_avg_price
                continue
            if order_status in ['OPEN', 'FILLED']:
                # Reset partial fill tracking on successful order placement
                if self.partially_filled_size > 0:
                    self.partially_filled_size = 0
                    self.partially_filled_avg_price = 0
                    self.logger.log(f"[CLOSE] Reset partial fill tracking after successful order placement", "INFO")
                
                return OrderResult(
                    success=True,
                    order_id=order_id,
                    side=side,
                    size=quantity,
                    price=adjusted_price,
                    status=order_status
                )
            elif order_status == 'PENDING':
                # Rollback partial fill state on pending timeout
                self.partially_filled_size = original_partially_filled_size
                self.partially_filled_avg_price = original_partially_filled_avg_price
                raise Exception("[CLOSE] Order not processed after 10 seconds")
            else:
                # Rollback partial fill state on unexpected status
                self.partially_filled_size = original_partially_filled_size
                self.partially_filled_avg_price = original_partially_filled_avg_price
                raise Exception(f"[CLOSE] Unexpected order status: {order_status}")

    async def place_market_order(self, contract_id: str, quantity: Decimal, direction: str, prefer_ws: bool = False) -> OrderResult:
        """
        Place a market order with GRVT.
        
        GRVT SDK supports true market orders through the create_order method with order_type="market".
        Market orders are executed immediately at the best available price.
        
        Args:
            contract_id: The contract identifier
            quantity: Order quantity
            direction: Order direction ('buy' or 'sell')
            
        Returns:
            OrderResult: Result of the order placement
        """
        try:
            self.logger.log(f"[MARKET] Placing {direction} market order for {quantity}", "INFO")
            # Capture pre-order position for fallback verification
            try:
                pre_position = await self.get_account_positions()
            except Exception:
                pre_position = None
            
            # Create true market order using GRVT SDK
            response = self.rest_client.create_order(
                symbol=contract_id,
                order_type="market",  # Use market order type
                side=direction,
                amount=str(quantity),
                price=None,  # No price needed for market orders
                params={
                    'order_duration_secs': 60  # Short duration for market orders
                }
            )
            
            if not response or 'metadata' not in response:
                self.logger.log(f"[MARKET] Invalid response from GRVT: {response}", "ERROR")
                return OrderResult(success=False, error_message="Invalid response from GRVT")
            
            client_order_id = response['metadata'].get('client_order_id')
            server_order_id = response['metadata'].get('order_id')
            self.logger.log(f"[MARKET] Market order placed successfully: client_order_id={client_order_id} server_order_id={server_order_id}", "INFO")
            
            # Market orders should execute immediately, but give it a moment
            await asyncio.sleep(1.0)
            
            # If not preferring WS, try REST polling briefly for quick confirmation
            if not prefer_ws:
                # Check order status multiple times as market orders should fill quickly
                rest_query_failed = False
                first_fetch_done = False
                for attempt in range(5):
                    try:
                        # 优先使用服务端 order_id（更稳定），首次没有则用 client_order_id 获取并提取
                        if server_order_id:
                            order_info = await self.get_order_info(order_id=server_order_id)
                        elif client_order_id:
                            order_info = await self.get_order_info(client_order_id=client_order_id)
                            # 首次成功后，如果返回包含服务端 order_id，则后续切换为 order_id 查询
                            if order_info and order_info.order_id:
                                server_order_id = order_info.order_id
                        else:
                            order_info = None
                        first_fetch_done = True
                    except Exception:
                        rest_query_failed = True
                        break
                    if order_info:
                        if order_info.status in ['FILLED', 'PARTIALLY_FILLED']:
                            self.logger.log(f"[MARKET] Order {server_order_id or client_order_id} filled: {order_info.filled_size}/{quantity}", "INFO")
                            return OrderResult(
                                success=True,
                                order_id=server_order_id or client_order_id,
                                side=direction,
                                size=quantity,
                                price=order_info.price,
                                status=order_info.status
                            )
                        elif order_info.status == 'CANCELLED':
                            self.logger.log(f"[MARKET] Order {server_order_id or client_order_id} was cancelled", "WARNING")
                            return OrderResult(success=False, error_message="Market order cancelled")
                        elif order_info.status == 'OPEN':
                            if attempt < 4:  # Don't sleep on the last attempt
                                await asyncio.sleep(1.0)
                        else:
                            return OrderResult(success=False, error_message=f"Unexpected status: {order_info.status}")
                    else:
                        if attempt < 4:
                            await asyncio.sleep(1.0)
            
            # Degrade to WS update wait and position fact-check for cleaner logs
            self.logger.log(f"[MARKET] REST查询失败或未达终态，降级等待WS回报与持仓校验", "INFO")
            # Clear any previous event and wait for a fresh update
            try:
                self._ws_update_event.clear()
            except Exception:
                pass
            try:
                await asyncio.wait_for(self._ws_update_event.wait(), timeout=3.0)
            except asyncio.TimeoutError:
                pass

            # Check last WS update for this contract and side
            ws_update = self._last_order_update
            if ws_update and ws_update.get('contract_id') == contract_id and ws_update.get('side') == direction:
                ws_status = ws_update.get('status')
                # If server order id is still missing, try to take it from WS update
                if not server_order_id:
                    try:
                        server_order_id = ws_update.get('order_id') or server_order_id
                    except Exception:
                        pass
                if ws_status in ['FILLED', 'PARTIALLY_FILLED']:
                    filled_sz = Decimal(str(ws_update.get('filled_size', '0')))
                    self.logger.log(f"[MARKET] WS确认订单更新: {ws_status} filled={filled_sz}", "INFO")
                    return OrderResult(
                        success=True,
                        order_id=server_order_id or client_order_id,
                        side=direction,
                        size=quantity,
                        price=Decimal(str(ws_update.get('price', '0'))),
                        status=ws_status,
                        filled_size=filled_sz
                    )

            # Position fact-check as final fallback
            if pre_position is not None:
                try:
                    post_position = pre_position
                    for _ in range(10):
                        await asyncio.sleep(0.5)
                        post_position = await self.get_account_positions()
                        if post_position != pre_position:
                            break

                    delta = (pre_position - post_position).copy_abs()
                    if delta > Decimal('0'):
                        status = 'FILLED' if delta >= quantity else 'PARTIALLY_FILLED'
                        self.logger.log(
                            f"[MARKET] 基于持仓校验确认: {status} pre={pre_position} post={post_position} delta={delta}",
                            "INFO"
                        )
                        return OrderResult(
                            success=True,
                            order_id=server_order_id or client_order_id,
                            side=direction,
                            size=quantity,
                            price=None,
                            status=status,
                            filled_size=delta
                        )
                except Exception:
                    pass

            # If we get here, the order might still be processing; keep logs clean
            self.logger.log(f"[MARKET] 市价单已下达，状态待确认（已启用降级流程）", "INFO")
            return OrderResult(success=True, order_id=server_order_id or client_order_id, error_message="Market order placed; awaiting confirmation")
                
        except Exception as e:
            self.logger.log(f"[MARKET] Error placing market order: {e}", "ERROR")
            return OrderResult(success=False, error_message=str(e))

    @query_retry(reraise=True)
    def _cancel_order_with_retry(self, order_id: str):
        """Cancel order with retry mechanism (synchronous)."""
        return self.rest_client.cancel_order(id=order_id)

    async def cancel_order(self, order_id: str) -> OrderResult:
        """Cancel an order with GRVT."""
        try:
            # Execute synchronous cancel_order in thread pool to avoid blocking
            loop = asyncio.get_event_loop()
            cancel_result = await loop.run_in_executor(
                None, self._cancel_order_with_retry, order_id
            )

            if cancel_result:
                return OrderResult(success=True)
            else:
                return OrderResult(success=False, error_message='Failed to cancel order')

        except Exception as e:
            return OrderResult(success=False, error_message=str(e))

    @query_retry(reraise=True)
    async def get_order_info(self, order_id: str = None, client_order_id: str = None) -> Optional[OrderInfo]:
        """Get order information from GRVT."""
        # Get order information using GRVT SDK
        if order_id is not None:
            order_data = self.rest_client.fetch_order(id=order_id)
        elif client_order_id is not None:
            order_data = self.rest_client.fetch_order(params={'client_order_id': client_order_id})
        else:
            raise ValueError("Either order_id or client_order_id must be provided")

        if not order_data or 'result' not in order_data:
            raise ValueError(f"Unable to get order info: {order_id}")

        order = order_data['result']
        legs = order.get('legs', [])
        if not legs:
            raise ValueError(f"Unable to get order info: {order_id}")

        leg = legs[0]  # Get first leg
        state = order.get('state', {})

        return OrderInfo(
            order_id=order.get('order_id', ''),
            side=leg.get('is_buying_asset', False) and 'buy' or 'sell',
            size=Decimal(leg.get('size', 0)),
            price=Decimal(leg.get('limit_price', 0)),
            status=state.get('status', ''),
            filled_size=(Decimal(state.get('traded_size', ['0'])[0])
                         if isinstance(state.get('traded_size'), list) else Decimal(0)),
            remaining_size=(Decimal(state.get('book_size', ['0'])[0])
                            if isinstance(state.get('book_size'), list) else Decimal(0))
        )

    async def _get_active_close_orders(self, contract_id: str) -> int:
        """Get active close orders for a contract using official SDK."""
        active_orders = await self.get_active_orders(contract_id)
        active_close_orders = 0
        for order in active_orders:
            if order.side == self.config.close_order_side:
                active_close_orders += 1
        return active_close_orders

    @query_retry(reraise=True)
    async def get_active_orders(self, contract_id: str) -> List[OrderInfo]:
        """Get active orders for a contract."""
        # Get active orders using GRVT SDK
        orders = self.rest_client.fetch_open_orders(symbol=contract_id)

        if not orders:
            return []

        order_list = []
        for order in orders:
            legs = order.get('legs', [])
            if not legs:
                continue

            leg = legs[0]  # Get first leg
            state = order.get('state', {})

            order_list.append(OrderInfo(
                order_id=order.get('order_id', ''),
                side=leg.get('is_buying_asset', False) and 'buy' or 'sell',
                size=Decimal(leg.get('size', 0)),
                price=Decimal(leg.get('limit_price', 0)),
                status=state.get('status', ''),
                filled_size=(Decimal(state.get('traded_size', ['0'])[0])
                             if isinstance(state.get('traded_size'), list) else Decimal(0)),
                remaining_size=(Decimal(state.get('book_size', ['0'])[0])
                                if isinstance(state.get('book_size'), list) else Decimal(0))
            ))

        return order_list

    @query_retry(reraise=True)
    async def get_account_positions(self) -> Decimal:
        """Get account positions."""
        # Get positions using GRVT SDK
        positions = self.rest_client.fetch_positions()

        for position in positions:
            if position.get('instrument') == self.config.contract_id:
                return abs(Decimal(position.get('size', 0)))

        return Decimal(0)

    @query_retry(reraise=True)
    async def get_account_balance(self) -> Decimal:
        """
        Get account balance for compatibility with trading_bot.py.
        This method returns the account equity which includes unrealized PnL.
        """
        return await self.get_account_equity()

    @query_retry(reraise=True)
    async def get_account_equity(self) -> Decimal:
        """
        Get account equity for drawdown calculation.
        
        Returns the total account equity including unrealized PnL.
        This method uses GRVT's get_account_summary to get comprehensive account information.
        """
        try:
            # Get account summary which includes equity and unrealized PnL
            account_summary = self.rest_client.get_account_summary(type='sub-account')
            
            # Extract equity from account summary - use correct field name 'total_equity'
            if 'total_equity' in account_summary:
                equity = Decimal(str(account_summary['total_equity']))
                self.logger.info(f"Account equity from summary: {equity}")
                return equity
            
            # Fallback: try legacy 'equity' field name
            if 'equity' in account_summary:
                equity = Decimal(str(account_summary['equity']))
                self.logger.info(f"Account equity from summary (legacy): {equity}")
                return equity
            
            # Fallback: try to get balance and calculate equity
            balance_info = self.rest_client.fetch_balance(type='sub-account')
            
            # CCXT format balance includes 'total' which represents equity
            if 'total' in balance_info and 'USDT' in balance_info['total']:
                equity = Decimal(str(balance_info['total']['USDT']))
                self.logger.info(f"Account equity from balance total: {equity}")
                return equity
            
            # Another fallback: calculate from positions
            positions = self.rest_client.fetch_positions()
            total_equity = Decimal('0')
            
            for position in positions:
                # Add unrealized PnL from each position
                if 'unrealizedPnl' in position:
                    unrealized_pnl = Decimal(str(position.get('unrealizedPnl', 0)))
                    total_equity += unrealized_pnl
                elif 'unrealized_pnl' in position:
                    unrealized_pnl = Decimal(str(position.get('unrealized_pnl', 0)))
                    total_equity += unrealized_pnl
            
            # Add available balance
            if 'free' in balance_info and 'USDT' in balance_info['free']:
                free_balance = Decimal(str(balance_info['free']['USDT']))
                total_equity += free_balance
            
            self.logger.info(f"Calculated account equity: {total_equity}")
            return total_equity
            
        except Exception as e:
            self.logger.error(f"Error getting account equity: {e}")
            # Return 0 as fallback to avoid breaking the trading bot
            return Decimal('0')

    async def get_account_networth(self) -> Decimal:
        """Get account net worth with caching mechanism."""
        current_time = time.time()
        
        # Check if we have a valid cached value
        if (self._networth_cache is not None and 
            self._networth_cache_time is not None and 
            current_time - self._networth_cache_time < self._networth_cache_duration):
            self.logger.debug(f"Using cached networth: {self._networth_cache}")
            return self._networth_cache
        
        try:
            # Calculate real-time networth
            networth = await self._calculate_realtime_networth()
            
            # Update cache
            self._networth_cache = networth
            self._networth_cache_time = current_time
            
            self.logger.info(f"Calculated and cached new networth: {networth}")
            return networth
            
        except Exception as e:
            self.logger.error(f"Failed to calculate networth: {e}")
            # Return cached value if available, even if expired
            if self._networth_cache is not None:
                self.logger.warning(f"Returning expired cached networth: {self._networth_cache}")
                return self._networth_cache
            return Decimal('0')
    
    async def _calculate_realtime_networth(self) -> Decimal:
        """Calculate real-time networth using account summary for more accurate data."""
        try:
            # Use get_account_summary for comprehensive account information
            account_summary = self.rest_client.get_account_summary(type='sub-account')
            
            # Extract total equity which already includes unrealized PnL
            if 'total_equity' in account_summary:
                total_equity = Decimal(str(account_summary['total_equity']))
                unrealized_pnl = Decimal(str(account_summary.get('unrealized_pnl', '0')))
                available_balance = Decimal(str(account_summary.get('available_balance', '0')))
                
                self.logger.info(f"Account summary - Total equity: {total_equity}, "
                               f"Unrealized PnL: {unrealized_pnl}, Available balance: {available_balance}")
                
                # total_equity already includes unrealized PnL, so we can return it directly
                self.logger.info(f"Networth from account summary: {total_equity}")
                return total_equity
            
            # Fallback to the original method if account summary doesn't have expected fields
            self.logger.warning("Account summary missing total_equity field, falling back to balance + positions calculation")
            
            # Get available balance (USDT)
            balance = await self.get_account_balance()
            self.logger.debug(f"Available balance: {balance}")
            
            # Get all positions and calculate total unrealized PnL
            total_unrealized_pnl = Decimal('0')
            
            try:
                self.logger.debug(f"Attempting to fetch positions with trading_account_id: {self.trading_account_id}")
                
                # fetch_positions() returns a list directly, not a dict with 'result' key
                positions = self.rest_client.fetch_positions()
                
                self.logger.debug(f"fetch_positions returned: type={type(positions)}, length={len(positions) if positions else 0}")
                
                if positions:
                    self.logger.debug(f"Received {len(positions)} positions from API")
                    
                    for position in positions:
                        self.logger.debug(f"Raw position data: {position}")
                        
                        if position.get('size', '0') != '0':  # Only consider non-zero positions
                            unrealized_pnl = Decimal(str(position.get('unrealizedPnl', '0')))
                            total_unrealized_pnl += unrealized_pnl
                            
                            self.logger.debug(f"Position {position.get('instrument', 'unknown')}: "
                                            f"size={position.get('size', '0')}, "
                                            f"unrealizedPnl={unrealized_pnl}")
                    
                    self.logger.debug(f"Total unrealized PnL: {total_unrealized_pnl}")
                else:
                    self.logger.warning("No positions data received - positions list is empty")
                    
            except Exception as e:
                self.logger.error(f"Failed to get positions for PnL calculation: {e}")
                self.logger.error(f"Exception type: {type(e)}")
                import traceback
                self.logger.error(f"Traceback: {traceback.format_exc()}")
                # Continue with balance only if positions fetch fails
            
            # Calculate total networth: balance + unrealized PnL
            networth = balance + total_unrealized_pnl
            
            self.logger.info(f"Networth calculation: balance={balance} + unrealized_pnl={total_unrealized_pnl} = {networth}")
            return networth
            
        except Exception as e:
            self.logger.error(f"Error in _calculate_realtime_networth: {e}")
            raise

    @query_retry(reraise=True)
    async def get_unrealized_pnl_and_margin(self) -> Tuple[Decimal, Decimal]:
        """
        获取未实现盈亏和初始保证金，用于简化的亏损计算。
        
        Returns:
            Tuple[Decimal, Decimal]: (总未实现盈亏, 总初始保证金)
        """
        try:
            # 优先使用 get_account_summary 获取准确的数据
            account_summary = self.rest_client.get_account_summary(type='sub-account')
            
            if 'unrealized_pnl' in account_summary and 'initial_margin' in account_summary:
                total_unrealized_pnl = Decimal(str(account_summary['unrealized_pnl']))
                total_initial_margin = Decimal(str(account_summary['initial_margin']))
                
                self.logger.info(f"From account summary - Unrealized PnL: {total_unrealized_pnl}, "
                               f"Initial margin: {total_initial_margin}")
                
                return total_unrealized_pnl, total_initial_margin
            
            # 回退到从仓位信息计算
            self.logger.warning("Account summary missing unrealized_pnl or initial_margin, falling back to positions calculation")
            
            # 获取所有仓位信息
            positions = self.rest_client.fetch_positions()
            
            total_unrealized_pnl = Decimal('0')
            total_initial_margin = Decimal('0')
            
            for position in positions:
                # 获取未实现盈亏
                unrealized_pnl = Decimal('0')
                if 'unrealizedPnl' in position:
                    unrealized_pnl = Decimal(str(position.get('unrealizedPnl', 0)))
                elif 'unrealized_pnl' in position:
                    unrealized_pnl = Decimal(str(position.get('unrealized_pnl', 0)))
                elif 'pnl' in position:
                    unrealized_pnl = Decimal(str(position.get('pnl', 0)))
                
                # 获取初始保证金
                initial_margin = Decimal('0')
                if 'initialMargin' in position:
                    initial_margin = Decimal(str(position.get('initialMargin', 0)))
                elif 'initial_margin' in position:
                    initial_margin = Decimal(str(position.get('initial_margin', 0)))
                elif 'margin' in position:
                    initial_margin = Decimal(str(position.get('margin', 0)))
                elif 'marginUsed' in position:
                    initial_margin = Decimal(str(position.get('marginUsed', 0)))
                
                total_unrealized_pnl += unrealized_pnl
                total_initial_margin += initial_margin
                
                self.logger.debug(f"Position {position.get('symbol', 'unknown')}: "
                                f"unrealized_pnl={unrealized_pnl}, initial_margin={initial_margin}")
            
            self.logger.info(f"Total unrealized PnL: {total_unrealized_pnl}, "
                           f"Total initial margin: {total_initial_margin}")
            
            return total_unrealized_pnl, total_initial_margin
            
        except Exception as e:
            self.logger.error(f"Error getting unrealized PnL and margin: {e}")
            # 返回 0 作为回退，避免破坏交易机器人
            return Decimal('0'), Decimal('0')

    async def get_position_loss_value(self) -> Decimal:
        """
        获取整体仓位亏损值的简化计算方法。
        
        使用公式：亏损值 = min(0, 未实现盈亏)
        如果未实现盈亏为负数（亏损），则返回其绝对值；如果为正数（盈利），则返回0。
        
        Returns:
            Decimal: 整体仓位亏损值（总是非负数）
        """
        try:
            unrealized_pnl, initial_margin = await self.get_unrealized_pnl_and_margin()
            
            # 如果未实现盈亏为负数（亏损），返回其绝对值
            # 如果为正数（盈利），返回0
            loss_value = max(Decimal('0'), -unrealized_pnl)
            
            self.logger.info(f"Position loss value: {loss_value} "
                           f"(unrealized_pnl: {unrealized_pnl}, initial_margin: {initial_margin})")
            
            return loss_value
            
        except Exception as e:
            self.logger.error(f"Error calculating position loss value: {e}")
            return Decimal('0')

    async def get_contract_attributes(self) -> Tuple[str, Decimal]:
        """Get contract ID and tick size for a ticker."""
        ticker = self.config.ticker
        if not ticker:
            raise ValueError("Ticker is empty")

        # Get markets from GRVT
        markets = self.rest_client.fetch_markets()

        for market in markets:
            if (market.get('base') == ticker and
                    market.get('quote') == 'USDT' and
                    market.get('kind') == 'PERPETUAL'):

                self.config.contract_id = market.get('instrument', '')
                self.config.tick_size = Decimal(market.get('tick_size', 0))

                # Validate minimum quantity
                min_size = Decimal(market.get('min_size', 0))
                if self.config.quantity < min_size:
                    raise ValueError(
                        f"Order quantity is less than min quantity: {self.config.quantity} < {min_size}"
                    )

                return self.config.contract_id, self.config.tick_size

        raise ValueError(f"Contract not found for ticker: {ticker}")

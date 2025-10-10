"""
Modular Trading Bot - Supports multiple exchanges
"""

import os
import time
import asyncio
import traceback
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

from exchanges import ExchangeFactory
from helpers import TradingLogger
from helpers.lark_bot import LarkBot
from helpers.telegram_bot import TelegramBot
from helpers.drawdown_monitor import DrawdownMonitor, DrawdownConfig


@dataclass
class TradingConfig:
    """Configuration class for trading parameters."""
    ticker: str
    contract_id: str
    quantity: Decimal
    take_profit: Decimal
    tick_size: Decimal
    direction: str
    max_orders: int
    wait_time: int
    exchange: str
    grid_step: Decimal
    stop_price: Decimal
    pause_price: Decimal
    aster_boost: bool
    # Drawdown monitoring parameters
    enable_drawdown_monitor: bool = False
    drawdown_light_threshold: Decimal = Decimal('5.0')  # 5% light warning
    drawdown_medium_threshold: Decimal = Decimal('8.0')  # 8% medium warning
    drawdown_severe_threshold: Decimal = Decimal('12.0')  # 12% severe stop-loss

    @property
    def close_order_side(self) -> str:
        """Get the close order side based on bot direction."""
        return 'buy' if self.direction == "sell" else 'sell'


@dataclass
class OrderMonitor:
    """Thread-safe order monitoring state."""
    order_id: Optional[str] = None
    filled: bool = False
    filled_price: Optional[Decimal] = None
    filled_qty: Decimal = 0.0

    def reset(self):
        """Reset the monitor state."""
        self.order_id = None
        self.filled = False
        self.filled_price = None
        self.filled_qty = 0.0


class TradingBot:
    """Modular Trading Bot - Main trading logic supporting multiple exchanges."""

    def __init__(self, config: TradingConfig):
        self.config = config
        self.logger = TradingLogger(config.exchange, config.ticker, log_to_console=True)

        # Create exchange client
        try:
            self.exchange_client = ExchangeFactory.create_exchange(
                config.exchange,
                config
            )
        except ValueError as e:
            raise ValueError(f"Failed to create exchange client: {e}")

        # Trading state
        self.active_close_orders = []
        self.last_close_orders = 0
        self.last_open_order_time = 0
        self.last_log_time = 0
        self.current_order_status = None
        self.order_filled_event = asyncio.Event()
        self.order_canceled_event = asyncio.Event()
        self.order_filled_amount = 0  # Initialize order filled amount
        self.shutdown_requested = False
        self.loop = None
        self.trading_paused = False  # Flag to pause new orders during medium drawdown
        
        # 止损订单状态跟踪
        self.stop_loss_order_id = None  # 当前止损订单ID
        self.stop_loss_order_time = 0  # 止损订单下单时间
        self.stop_loss_monitoring = False  # 是否正在监控止损订单

        # Initialize drawdown monitor if enabled
        self.drawdown_monitor = None
        if config.enable_drawdown_monitor:
            try:
                drawdown_config = DrawdownConfig(
                    light_warning_threshold=config.drawdown_light_threshold / 100,
                    medium_warning_threshold=config.drawdown_medium_threshold / 100,
                    severe_stop_loss_threshold=config.drawdown_severe_threshold / 100
                )
                # 传递exchange_client和contract_id以启用自动止损功能
                self.drawdown_monitor = DrawdownMonitor(
                    drawdown_config, 
                    self.logger, 
                    self.exchange_client, 
                    config.contract_id
                )
                self.logger.log(f"Drawdown monitor enabled with automatic stop-loss. Thresholds: "
                              f"Light={config.drawdown_light_threshold}%, "
                              f"Medium={config.drawdown_medium_threshold}%, "
                              f"Severe={config.drawdown_severe_threshold}%", "INFO")
            except Exception as e:
                self.logger.log(f"Failed to create drawdown monitor: {e}", "ERROR")
                # 即使创建失败，也设置为 None，避免后续检查问题
                self.drawdown_monitor = None

        # Register order callback
        self._setup_websocket_handlers()

    async def graceful_shutdown(self, reason: str = "Unknown"):
        """Perform graceful shutdown of the trading bot."""
        self.logger.log(f"Starting graceful shutdown: {reason}", "INFO")
        self.shutdown_requested = True

        try:
            # Disconnect from exchange
            await self.exchange_client.disconnect()
            self.logger.log("Graceful shutdown completed", "INFO")

        except Exception as e:
            self.logger.log(f"Error during graceful shutdown: {e}", "ERROR")

    def _setup_websocket_handlers(self):
        """Setup WebSocket handlers for order updates."""
        def order_update_handler(message):
            """Handle order updates from WebSocket."""
            try:
                # Check if this is for our contract
                if message.get('contract_id') != self.config.contract_id:
                    return

                order_id = message.get('order_id')
                status = message.get('status')
                side = message.get('side', '')
                order_type = message.get('order_type', '')
                filled_size = Decimal(message.get('filled_size'))
                if order_type == "OPEN":
                    self.current_order_status = status

                if status == 'FILLED':
                    if order_type == "OPEN":
                        self.order_filled_amount = filled_size
                        # Ensure thread-safe interaction with asyncio event loop
                        if self.loop is not None:
                            self.loop.call_soon_threadsafe(self.order_filled_event.set)
                        else:
                            # Fallback (should not happen after run() starts)
                            self.order_filled_event.set()

                    self.logger.log(f"[{order_type}] [{order_id}] {status} "
                                    f"{message.get('size')} @ {message.get('price')}", "INFO")
                    self.logger.log_transaction(order_id, side, message.get('size'), message.get('price'), status)
                elif status == "CANCELED":
                    if order_type == "OPEN":
                        self.order_filled_amount = filled_size
                        if self.loop is not None:
                            self.loop.call_soon_threadsafe(self.order_canceled_event.set)
                        else:
                            self.order_canceled_event.set()

                        if self.order_filled_amount > 0:
                            self.logger.log_transaction(order_id, side, self.order_filled_amount, message.get('price'), status)

                    self.logger.log(f"[{order_type}] [{order_id}] {status} "
                                    f"{message.get('size')} @ {message.get('price')}", "INFO")
                elif status == "PARTIALLY_FILLED":
                    if order_type == "OPEN":
                        self.order_filled_amount = filled_size
                        self.logger.log(f"[{order_type}] [{order_id}] {status} "
                                        f"Filled: {filled_size}/{message.get('size')} @ {message.get('price')} "
                                        f"(Cumulative filled: {self.order_filled_amount})", "INFO")
                    else:
                        self.logger.log(f"[{order_type}] [{order_id}] {status} "
                                        f"Filled: {filled_size}/{message.get('size')} @ {message.get('price')}", "INFO")
                else:
                    self.logger.log(f"[{order_type}] [{order_id}] {status} "
                                    f"{message.get('size')} @ {message.get('price')}", "INFO")

            except Exception as e:
                self.logger.log(f"Error handling order update: {e}", "ERROR")
                self.logger.log(f"Traceback: {traceback.format_exc()}", "ERROR")

        # Setup order update handler
        self.exchange_client.setup_order_update_handler(order_update_handler)

    def _calculate_wait_time(self) -> Decimal:
        """Calculate wait time between orders."""
        cool_down_time = self.config.wait_time

        if len(self.active_close_orders) < self.last_close_orders:
            self.last_close_orders = len(self.active_close_orders)
            return 0

        self.last_close_orders = len(self.active_close_orders)
        if len(self.active_close_orders) >= self.config.max_orders:
            return 1

        if len(self.active_close_orders) / self.config.max_orders >= 2/3:
            cool_down_time = 2 * self.config.wait_time
        elif len(self.active_close_orders) / self.config.max_orders >= 1/3:
            cool_down_time = self.config.wait_time
        elif len(self.active_close_orders) / self.config.max_orders >= 1/6:
            cool_down_time = self.config.wait_time / 2
        else:
            cool_down_time = self.config.wait_time / 4

        # if the program detects active_close_orders during startup, it is necessary to consider cool_down_time
        if self.last_open_order_time == 0 and len(self.active_close_orders) > 0:
            self.last_open_order_time = time.time()

        if time.time() - self.last_open_order_time > cool_down_time:
            return 0
        else:
            return 1

    async def _place_and_monitor_open_order(self) -> bool:
        """Place an order and monitor its execution."""
        try:
            # Reset state before placing order
            self.order_filled_event.clear()
            self.current_order_status = 'OPEN'
            self.order_filled_amount = 0

            # Place the order
            order_result = await self.exchange_client.place_open_order(
                self.config.contract_id,
                self.config.quantity,
                self.config.direction
            )

            if not order_result.success:
                return False

            if order_result.status == 'FILLED':
                return await self._handle_order_result(order_result)
            elif not self.order_filled_event.is_set():
                try:
                    await asyncio.wait_for(self.order_filled_event.wait(), timeout=10)
                except asyncio.TimeoutError:
                    pass

            # Handle order result
            return await self._handle_order_result(order_result)

        except Exception as e:
            self.logger.log(f"Error placing order: {e}", "ERROR")
            self.logger.log(f"Traceback: {traceback.format_exc()}", "ERROR")
            return False

    async def _handle_order_result(self, order_result) -> bool:
        """Handle the result of an order placement."""
        order_id = order_result.order_id
        filled_price = order_result.price

        if self.order_filled_event.is_set() or order_result.status == 'FILLED':
            if self.config.aster_boost:
                close_order_result = await self.exchange_client.place_market_order(
                    self.config.contract_id,
                    self.config.quantity,
                    self.config.close_order_side
                )
            else:
                self.last_open_order_time = time.time()
                # Place close order
                close_side = self.config.close_order_side
                if close_side == 'sell':
                    close_price = filled_price * (1 + self.config.take_profit/100)
                else:
                    close_price = filled_price * (1 - self.config.take_profit/100)

                close_order_result = await self.exchange_client.place_close_order(
                    self.config.contract_id,
                    self.config.quantity,
                    close_price,
                    close_side
                )

                if not close_order_result.success:
                    self.logger.log(f"[CLOSE] Failed to place close order: {close_order_result.error_message}", "ERROR")
                    raise Exception(f"[CLOSE] Failed to place close order: {close_order_result.error_message}")

                return True

        else:
            new_order_price = await self.exchange_client.get_order_price(self.config.direction)

            def should_wait(direction: str, new_order_price: Decimal, order_result_price: Decimal) -> bool:
                if direction == "buy":
                    return new_order_price <= order_result_price
                elif direction == "sell":
                    return new_order_price >= order_result_price
                return False

            if self.config.exchange == "lighter":
                current_order_status = self.exchange_client.current_order.status
            elif self.config.exchange == "extended":
                # For extended exchange, check order status from open_orders dict
                if order_id in self.exchange_client.open_orders:
                    current_order_status = self.exchange_client.open_orders[order_id].get('status', 'UNKNOWN')
                else:
                    order_info = await self.exchange_client.get_order_info(order_id)
                    if order_info is not None:
                        current_order_status = order_info.status
                    else:
                        current_order_status = 'UNKNOWN' if order_info else 'UNKNOWN'
            else:
                order_info = await self.exchange_client.get_order_info(order_id)
                current_order_status = order_info.status

            while (
                should_wait(self.config.direction, new_order_price, order_result.price)
                and current_order_status == "OPEN"
            ):
                self.logger.log(f"[OPEN] [{order_id}] Waiting for order to be filled", "INFO")
                await asyncio.sleep(5)
                if self.config.exchange == "lighter":
                    current_order_status = self.exchange_client.current_order.status
                elif self.config.exchange == "extended":
                    # For extended exchange, check order status from open_orders dict
                    if order_id in self.exchange_client.open_orders:
                        current_order_status = self.exchange_client.open_orders[order_id].get('status', 'UNKNOWN')
                    else:
                        order_info = await self.exchange_client.get_order_info(order_id)
                        current_order_status = order_info.status if order_info else 'UNKNOWN'
                else:
                    order_info = await self.exchange_client.get_order_info(order_id)
                    if order_info is not None:
                        current_order_status = order_info.status
                    else:
                        current_order_status = 'UNKNOWN'
                new_order_price = await self.exchange_client.get_order_price(self.config.direction)

            self.order_canceled_event.clear()
            # Cancel the order if it's still open
            self.logger.log(f"[OPEN] [{order_id}] Cancelling order and placing a new order", "INFO")
            if self.config.exchange == "lighter":
                cancel_result = await self.exchange_client.cancel_order(order_id)
                start_time = time.time()
                while (time.time() - start_time < 10 and self.exchange_client.current_order.status != 'CANCELED' and
                        self.exchange_client.current_order.status != 'FILLED'):
                    await asyncio.sleep(0.1)

                if self.exchange_client.current_order.status not in ['CANCELED', 'FILLED']:
                    raise Exception(f"[OPEN] Error cancelling order: {self.exchange_client.current_order.status}")
                else:
                    self.order_filled_amount = self.exchange_client.current_order.filled_size
            else:
                try:
                    cancel_result = await self.exchange_client.cancel_order(order_id)
                    if not cancel_result.success:
                        self.order_canceled_event.set()
                        self.logger.log(f"[CLOSE] Failed to cancel order {order_id}: {cancel_result.error_message}", "WARNING")
                    else:
                        self.current_order_status = "CANCELED"

                except Exception as e:
                    self.order_canceled_event.set()
                    self.logger.log(f"[CLOSE] Error canceling order {order_id}: {e}", "ERROR")

                if self.config.exchange == "backpack":
                    self.order_filled_amount = cancel_result.filled_size
                elif self.config.exchange == "extended":
                    # For extended exchange, get filled amount from partially_filled_size
                    self.order_filled_amount = self.exchange_client.partially_filled_size
                else:
                    # Wait for cancel event or timeout
                    if not self.order_canceled_event.is_set():
                        try:
                            await asyncio.wait_for(self.order_canceled_event.wait(), timeout=5)
                        except asyncio.TimeoutError:
                            pass
                    
                    # Always verify filled amount from order info for consistency
                    # This ensures we get the correct filled_size regardless of WebSocket timing
                    try:
                        order_info = await self.exchange_client.get_order_info(order_id)
                        if order_info.filled_size > 0:
                            self.order_filled_amount = order_info.filled_size
                            self.logger.log(f"[OPEN] [{order_id}] Retrieved filled amount from order info: {self.order_filled_amount}", "INFO")
                    except Exception as e:
                        self.logger.log(f"[OPEN] [{order_id}] Failed to get order info: {e}", "WARNING")

            if self.order_filled_amount > 0:
                self.logger.log(f"[CLOSE] Processing partial fill: {self.order_filled_amount} @ {filled_price}", "INFO")
                close_side = self.config.close_order_side
                if self.config.aster_boost:
                    close_order_result = await self.exchange_client.place_close_order(
                        self.config.contract_id,
                        self.order_filled_amount,
                        filled_price,
                        close_side
                    )
                else:
                    if close_side == 'sell':
                        close_price = filled_price * (1 + self.config.take_profit/100)
                    else:
                        close_price = filled_price * (1 - self.config.take_profit/100)

                    close_order_result = await self.exchange_client.place_close_order(
                        self.config.contract_id,
                        self.order_filled_amount,
                        close_price,
                        close_side
                    )
                    if self.config.exchange == "lighter":
                        start_time = time.time()
                        while time.time() - start_time < 5:
                            await asyncio.sleep(1)
                            if self.exchange_client.current_order is not None:
                                if self.exchange_client.current_order.status == 'CANCELED-SELF-TRADE':
                                    close_order_result = await self.exchange_client.place_close_order(
                                        self.config.contract_id,
                                        self.order_filled_amount,
                                        close_price,
                                        close_side
                                    )
                                    start_time = time.time()

                self.last_open_order_time = time.time()
                if not close_order_result.success:
                    self.logger.log(f"[CLOSE] Failed to place close order: {close_order_result.error_message}", "ERROR")

            return True

        return False

    async def _log_status_periodically(self):
        """Log status information periodically, including positions."""
        if time.time() - self.last_log_time > 60 or self.last_log_time == 0:
            print("--------------------------------")
            try:
                # Get active orders
                active_orders = await self.exchange_client.get_active_orders(self.config.contract_id)

                # Filter close orders
                self.active_close_orders = []
                for order in active_orders:
                    if order.side == self.config.close_order_side:
                        self.active_close_orders.append({
                            'id': order.order_id,
                            'price': order.price,
                            'size': order.size
                        })

                # Get positions
                position_amt = await self.exchange_client.get_account_positions()

                # Calculate active closing amount
                active_close_amount = sum(
                    Decimal(order.get('size', 0))
                    for order in self.active_close_orders
                    if isinstance(order, dict)
                )

                self.logger.log(f"Current Position: {position_amt} | Active closing amount: {active_close_amount} | "
                                f"Order quantity: {len(self.active_close_orders)}")
                self.last_log_time = time.time()
                # Check for position mismatch
                if abs(position_amt - active_close_amount) > (2 * self.config.quantity):
                    error_message = f"\n\nERROR: [{self.config.exchange.upper()}_{self.config.ticker.upper()}] "
                    error_message += "Position mismatch detected\n"
                    error_message += "###### ERROR ###### ERROR ###### ERROR ###### ERROR #####\n"
                    error_message += "Please manually rebalance your position and take-profit orders\n"
                    error_message += "请手动平衡当前仓位和正在关闭的仓位\n"
                    error_message += f"current position: {position_amt} | active closing amount: {active_close_amount} | "f"Order quantity: {len(self.active_close_orders)}\n"
                    error_message += "###### ERROR ###### ERROR ###### ERROR ###### ERROR #####\n"
                    self.logger.log(error_message, "ERROR")

                    await self.send_notification(error_message.lstrip())

                    if not self.shutdown_requested:
                        self.shutdown_requested = True

                    mismatch_detected = True
                else:
                    mismatch_detected = False

                return mismatch_detected

            except Exception as e:
                self.logger.log(f"Error in periodic status check: {e}", "ERROR")
                self.logger.log(f"Traceback: {traceback.format_exc()}", "ERROR")

            print("--------------------------------")

    async def _meet_grid_step_condition(self) -> bool:
        if self.active_close_orders:
            picker = min if self.config.direction == "buy" else max
            next_close_order = picker(self.active_close_orders, key=lambda o: o["price"])
            next_close_price = next_close_order["price"]

            best_bid, best_ask = await self.exchange_client.fetch_bbo_prices(self.config.contract_id)
            if best_bid <= 0 or best_ask <= 0 or best_bid >= best_ask:
                raise ValueError("No bid/ask data available")

            if self.config.direction == "buy":
                new_order_close_price = best_ask * (1 + self.config.take_profit/100)
                if next_close_price / new_order_close_price > 1 + self.config.grid_step/100:
                    return True
                else:
                    return False
            elif self.config.direction == "sell":
                new_order_close_price = best_bid * (1 - self.config.take_profit/100)
                if new_order_close_price / next_close_price > 1 + self.config.grid_step/100:
                    return True
                else:
                    return False
            else:
                raise ValueError(f"Invalid direction: {self.config.direction}")
        else:
            return True

    async def _check_price_condition(self) -> bool:
        stop_trading = False
        pause_trading = False

        if self.config.pause_price == self.config.stop_price == -1:
            return stop_trading, pause_trading

        best_bid, best_ask = await self.exchange_client.fetch_bbo_prices(self.config.contract_id)
        if best_bid <= 0 or best_ask <= 0 or best_bid >= best_ask:
            raise ValueError("No bid/ask data available")

        if self.config.stop_price != -1:
            if self.config.direction == "buy":
                if best_ask >= self.config.stop_price:
                    stop_trading = True
            elif self.config.direction == "sell":
                if best_bid <= self.config.stop_price:
                    stop_trading = True

        if self.config.pause_price != -1:
            if self.config.direction == "buy":
                if best_ask >= self.config.pause_price:
                    pause_trading = True
            elif self.config.direction == "sell":
                if best_bid <= self.config.pause_price:
                    pause_trading = True

        return stop_trading, pause_trading

    async def send_notification(self, message: str):
        lark_token = os.getenv("LARK_TOKEN")
        if lark_token:
            async with LarkBot(lark_token) as lark_bot:
                await lark_bot.send_text(message)

        telegram_token = os.getenv("TELEGRAM_BOT_TOKEN")
        telegram_chat_id = os.getenv("TELEGRAM_CHAT_ID")
        if telegram_token and telegram_chat_id:
            with TelegramBot(telegram_token, telegram_chat_id) as tg_bot:
                tg_bot.send_text(message)









    async def run(self):
        """Main trading loop."""
        try:
            self.config.contract_id, self.config.tick_size = await self.exchange_client.get_contract_attributes()

            # Log current TradingConfig
            self.logger.log("=== Trading Configuration ===", "INFO")
            self.logger.log(f"Ticker: {self.config.ticker}", "INFO")
            self.logger.log(f"Contract ID: {self.config.contract_id}", "INFO")
            self.logger.log(f"Quantity: {self.config.quantity}", "INFO")
            self.logger.log(f"Take Profit: {self.config.take_profit}%", "INFO")
            self.logger.log(f"Direction: {self.config.direction}", "INFO")
            self.logger.log(f"Max Orders: {self.config.max_orders}", "INFO")
            self.logger.log(f"Wait Time: {self.config.wait_time}s", "INFO")
            self.logger.log(f"Exchange: {self.config.exchange}", "INFO")
            self.logger.log(f"Grid Step: {self.config.grid_step}%", "INFO")
            self.logger.log(f"Stop Price: {self.config.stop_price}", "INFO")
            self.logger.log(f"Pause Price: {self.config.pause_price}", "INFO")
            self.logger.log(f"Aster Boost: {self.config.aster_boost}", "INFO")

            self.logger.log("=============================", "INFO")

            # Capture the running event loop for thread-safe callbacks
            self.loop = asyncio.get_running_loop()
            # Connect to exchange
            await self.exchange_client.connect()

            # wait for connection to establish
            await asyncio.sleep(5)

            # Initialize drawdown monitor session if enabled
            if self.drawdown_monitor:
                try:
                    initial_networth = await self.exchange_client.get_account_networth()
                    self.drawdown_monitor.start_session(initial_networth)
                    self.logger.log(f"Drawdown monitor session started with initial net worth: {initial_networth}", "INFO")
                except Exception as e:
                    self.logger.log(f"Failed to get initial net worth for drawdown monitor: {e}", "WARNING")
                    # 即使获取初始净值失败，也启动会话，使用默认值 0
                    try:
                        self.drawdown_monitor.start_session(Decimal("0"))
                        self.logger.log("Drawdown monitor session started with default net worth (0) due to initial fetch failure", "WARNING")
                    except Exception as session_error:
                        self.logger.log(f"Failed to start drawdown monitor session: {session_error}", "ERROR")
                        self.drawdown_monitor = None  # 只有在会话启动完全失败时才禁用

            # Main trading loop
            while not self.shutdown_requested:
                
                # Check drawdown if monitor is enabled
                if self.drawdown_monitor:
                    try:
                        # Only fetch networth if update is needed (based on frequency)
                        if self.drawdown_monitor.should_update_networth():
                            current_networth = await self.exchange_client.get_account_networth()
                            should_continue = self.drawdown_monitor.update_networth_with_fallback(current_networth)
                        else:
                            # Skip API call but still check if stop loss was triggered
                            should_continue = not self.drawdown_monitor.is_stop_loss_triggered()
                        
                        # Check if stop loss was triggered (moved from except block to try block)
                        if not should_continue or self.drawdown_monitor.is_stop_loss_triggered():
                            drawdown_percentage = self.drawdown_monitor.get_drawdown_percentage()
                            session_peak = self.drawdown_monitor.session_peak_networth
                            
                            # Execute stop-loss first before stopping the script
                            if self.drawdown_monitor.is_stop_loss_triggered():
                                stop_loss_success = False
                                retry_count = 0
                                max_retries = 100  # 设置最大重试次数，避免真正的无限循环
                                emergency_threshold = 10  # 紧急模式阈值
                                
                                self.logger.log("Starting stop-loss execution with enhanced retry mechanism", "INFO")
                                
                                # 改进的重试循环，支持用户中断
                                while not stop_loss_success and retry_count < max_retries and not self.shutdown_requested:
                                    try:
                                        retry_count += 1
                                        
                                        # 进入紧急模式提醒
                                        if retry_count == emergency_threshold:
                                            emergency_msg = f"⚠️ Stop-loss entering emergency mode after {emergency_threshold} attempts"
                                            self.logger.log(emergency_msg, "WARNING")
                                            await self.send_notification(emergency_msg)
                                        
                                        self.logger.log(f"Executing automatic stop-loss before shutdown (attempt {retry_count}/{max_retries})...", "INFO")
                                        
                                        # 记录执行前的状态
                                        try:
                                            current_positions = await self.exchange_client.get_account_positions()
                                            self.logger.log(f"Current position before stop-loss: {current_positions}", "INFO")
                                        except Exception as pos_e:
                                            self.logger.log(f"Failed to get current position: {pos_e}", "WARNING")
                                        
                                        # 执行止损
                                        await self.drawdown_monitor.execute_pending_stop_loss()
                                        
                                        # 检查止损是否真正执行成功
                                        if self.drawdown_monitor.stop_loss_executed:
                                            stop_loss_success = True
                                            self.logger.log("Automatic stop-loss executed successfully", "INFO")
                                            
                                            # 验证仓位是否真正平仓
                                            try:
                                                final_positions = await self.exchange_client.get_account_positions()
                                                self.logger.log(f"Final position after stop-loss: {final_positions}", "INFO")
                                                if abs(final_positions) > 0.001:  # 允许小的精度误差
                                                    self.logger.log(f"WARNING: Position not fully closed, remaining: {final_positions}", "WARNING")
                                            except Exception as verify_e:
                                                self.logger.log(f"Failed to verify final position: {verify_e}", "WARNING")
                                        else:
                                            # 止损执行失败，记录详细信息
                                            failure_reasons = []
                                            try:
                                                # 检查是否有活跃订单
                                                active_orders = await self.exchange_client.get_active_orders(self.config.contract_id)
                                                if active_orders:
                                                    failure_reasons.append(f"Active orders exist: {len(active_orders)}")
                                                
                                                # 检查当前仓位
                                                current_pos = await self.exchange_client.get_account_positions()
                                                if abs(current_pos) > 0.001:
                                                    failure_reasons.append(f"Position not closed: {current_pos}")
                                                
                                            except Exception as check_e:
                                                failure_reasons.append(f"Failed to check status: {check_e}")
                                            
                                            failure_msg = f"Stop-loss execution failed (attempt {retry_count})"
                                            if failure_reasons:
                                                failure_msg += f": {', '.join(failure_reasons)}"
                                            self.logger.log(failure_msg, "WARNING")
                                            
                                            # 动态等待时间，重试次数越多等待越久
                                            wait_time = min(retry_count * 0.5, 5.0)  # 最多等待5秒
                                            await asyncio.sleep(wait_time)
                                    
                                    except Exception as retry_e:
                                        self.logger.log(f"Error during stop-loss retry {retry_count}: {retry_e}", "ERROR")
                                        await asyncio.sleep(1)
                                
                                # 重试循环结束后的处理
                                if not stop_loss_success:
                                    max_retry_msg = f"🛑 Stop-loss execution interrupted by user after {retry_count} attempts"
                                    max_retry_msg += f"\nManual intervention may be required to close positions"
                                    max_retry_msg += f"\n用户中断了止损执行，可能需要手动平仓"
                                    self.logger.log(max_retry_msg, "WARNING")
                                    await self.send_notification(max_retry_msg)
                                elif retry_count >= max_retries:
                                    max_retry_msg = f"🚨 CRITICAL: Stop-loss failed after {max_retries} attempts!"
                                    max_retry_msg += f"\nAutomatic stop-loss has been exhausted"
                                    max_retry_msg += f"\nManual intervention required immediately!"
                                    max_retry_msg += f"\n自动止损已达到最大重试次数，需要立即手动干预！"
                                    self.logger.log(max_retry_msg, "CRITICAL")
                                    await self.send_notification(max_retry_msg)
                                elif stop_loss_success:
                                    success_msg = f"✅ Stop-loss successfully executed after {retry_count} attempts"
                                    self.logger.log(success_msg, "INFO")
                                    if retry_count > 5:  # 如果重试次数较多，发送通知
                                        await self.send_notification(f"Stop-loss completed after {retry_count} attempts")
                                
                                self.logger.log("Stop-loss successfully executed, proceeding with shutdown", "INFO")
                            
                            # Severe drawdown - stop trading after executing stop-loss
                            msg = f"\n\n🚨 SEVERE DRAWDOWN ALERT 🚨\n"
                            msg += f"Exchange: {self.config.exchange.upper()}\n"
                            msg += f"Ticker: {self.config.ticker.upper()}\n"
                            msg += f"Session Peak Net Worth: {session_peak}\n"
                            msg += f"Current Net Worth: {current_networth}\n"
                            msg += f"Drawdown: {drawdown_percentage:.2f}%\n"
                            msg += f"Threshold: {self.config.drawdown_severe_threshold}%\n"
                            msg += "Automatic stop-loss executed, trading stopped due to severe drawdown!\n"
                            msg += "已执行自动止损，严重回撤，交易已停止！\n"
                            
                            self.logger.log(msg, "ERROR")
                            await self.send_notification(msg)
                            await self.graceful_shutdown("Severe drawdown triggered")
                            break
                        
                        # Check current drawdown level for warnings
                        current_level = self.drawdown_monitor.current_level
                        if current_level.value == "medium_warning":
                            drawdown_percentage = self.drawdown_monitor.get_drawdown_percentage()
                            session_peak = self.drawdown_monitor.session_peak_networth
                            
                            # Medium drawdown - pause new orders
                            if not self.trading_paused:
                                self.trading_paused = True
                                msg = f"⚠️ MEDIUM DRAWDOWN WARNING ⚠️\n"
                                msg += f"Exchange: {self.config.exchange.upper()}\n"
                                msg += f"Ticker: {self.config.ticker.upper()}\n"
                                msg += f"Session Peak Net Worth: {session_peak}\n"
                                msg += f"Current Net Worth: {current_networth}\n"
                                msg += f"Drawdown: {drawdown_percentage:.2f}%\n"
                                msg += f"Threshold: {self.config.drawdown_medium_threshold}%\n"
                                msg += "Pausing new orders, allowing only position closing\n"
                                msg += "中等回撤警告，暂停新订单，仅允许平仓\n"
                                
                                self.logger.log(msg, "WARNING")
                                await self.send_notification(msg)
                                continue  # 立即跳出当前循环迭代，避免继续执行交易逻辑
                        
                        elif current_level.value == "light_warning":
                            # Resume trading if it was paused
                            trading_resumed = False
                            if self.trading_paused:
                                self.trading_paused = False
                                trading_resumed = True
                                self.logger.log("Trading resumed - drawdown level reduced to light warning", "INFO")
                            
                            drawdown_percentage = self.drawdown_monitor.get_drawdown_percentage()
                            session_peak = self.drawdown_monitor.session_peak_networth
                            
                            # Light drawdown - just log and notify
                            msg = f"💡 LIGHT DRAWDOWN NOTICE 💡\n"
                            msg += f"Exchange: {self.config.exchange.upper()}\n"
                            msg += f"Ticker: {self.config.ticker.upper()}\n"
                            msg += f"Session Peak Net Worth: {session_peak}\n"
                            msg += f"Current Net Worth: {current_networth}\n"
                            msg += f"Drawdown: {drawdown_percentage:.2f}%\n"
                            msg += f"Threshold: {self.config.drawdown_light_threshold}%\n"
                            msg += "Light drawdown detected, monitoring closely\n"
                            msg += "轻微回撤提醒，密切监控中\n"
                            
                            self.logger.log(msg, "WARNING")
                            await self.send_notification(msg)
                            
                            # 如果刚刚恢复交易，立即跳出循环以便快速响应
                            if trading_resumed:
                                continue
                        
                        else:
                            # No drawdown warning - resume trading if it was paused
                            if self.trading_paused:
                                self.trading_paused = False
                                self.logger.log("Trading resumed - drawdown level back to normal", "INFO")
                                continue  # 立即跳出循环以便快速恢复交易
                                
                    except Exception as networth_error:
                        self.logger.log(f"Failed to get current net worth: {networth_error}", "WARNING")
                        # 使用缓存值进行更新
                        should_continue = self.drawdown_monitor.update_networth_with_fallback(None)
                        # 即使出现错误，也尝试使用缓存值继续监控
                        try:
                            if not should_continue or self.drawdown_monitor.is_stop_loss_triggered():
                                self.logger.log("Stop-loss triggered during error recovery mode", "CRITICAL")
                                await self.graceful_shutdown("Drawdown stop-loss triggered during error recovery")
                                break
                        except Exception as fallback_error:
                            self.logger.log(f"Failed to use fallback monitoring: {fallback_error}", "ERROR")
                
                # Note: Stop-loss execution is now handled in the severe drawdown check above
                # to ensure it executes before script shutdown
                
                # Update active orders
                active_orders = await self.exchange_client.get_active_orders(self.config.contract_id)

                # Filter close orders
                self.active_close_orders = []
                for order in active_orders:
                    if order.side == self.config.close_order_side:
                        self.active_close_orders.append({
                            'id': order.order_id,
                            'price': order.price,
                            'size': order.size
                        })



                # Periodic logging
                mismatch_detected = await self._log_status_periodically()

                stop_trading, pause_trading = await self._check_price_condition()
                if stop_trading:
                    msg = f"\n\nWARNING: [{self.config.exchange.upper()}_{self.config.ticker.upper()}] \n"
                    msg += "Stopped trading due to stop price triggered\n"
                    msg += "价格已经达到停止交易价格，脚本将停止交易\n"
                    await self.send_notification(msg.lstrip())
                    await self.graceful_shutdown(msg)
                    continue

                if pause_trading:
                    await asyncio.sleep(5)
                    continue

                if not mismatch_detected:
                    wait_time = self._calculate_wait_time()

                    if wait_time > 0:
                        await asyncio.sleep(wait_time)
                        continue
                    else:
                        meet_grid_step_condition = await self._meet_grid_step_condition()
                        if not meet_grid_step_condition:
                            await asyncio.sleep(1)
                            continue

                        # Check if trading is paused due to medium drawdown
                        if self.trading_paused:
                            self.logger.log("Skipping new order placement - trading paused due to medium drawdown", "INFO")
                            await asyncio.sleep(5)
                            continue

                        await self._place_and_monitor_open_order()
                        self.last_close_orders += 1

        except KeyboardInterrupt:
            self.logger.log("Bot stopped by user")
            await self.graceful_shutdown("User interruption (Ctrl+C)")
        except Exception as e:
            self.logger.log(f"Critical error: {e}", "ERROR")
            self.logger.log(f"Traceback: {traceback.format_exc()}", "ERROR")
            await self.graceful_shutdown(f"Critical error: {e}")
            raise
        finally:
            # Ensure all connections are closed even if graceful shutdown fails
            try:
                await self.exchange_client.disconnect()
            except Exception as e:
                self.logger.log(f"Error disconnecting from exchange: {e}", "ERROR")

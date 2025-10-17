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
from helpers.drawdown_monitor import (
    DrawdownMonitor, 
    DrawdownLevel,
    DrawdownConfig,
    NetworthValidationError,
    StopLossExecutionError,
    APIRateLimitError,
    NetworkConnectionError
)


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
    # Hedge trading parameters
    enable_hedge: bool = False                    # 是否启用对冲
    hedge_exchange: str = "lighter"               # 对冲交易所
    hedge_delay: float = 0.1                      # 对冲延迟(秒)

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


@dataclass
class HedgePosition:
    """对冲位置状态管理类"""
    main_order_id: str                    # 主订单ID
    hedge_order_id: str                   # 对冲订单ID  
    take_profit_order_id: Optional[str] = None      # 止盈订单ID
    quantity: Decimal = Decimal('0')      # 数量
    main_side: str = ""                   # 主订单方向 (buy/sell)
    hedge_side: str = ""                  # 对冲方向 (sell/buy)
    status: str = "HEDGING"               # 状态: HEDGING/PROFIT_PENDING/CLOSING/COMPLETED
    created_time: float = 0.0             # 创建时间
    main_fill_price: Optional[Decimal] = None       # 主订单成交价格
    hedge_fill_price: Optional[Decimal] = None      # 对冲订单成交价格

    def is_completed(self) -> bool:
        """检查对冲周期是否已完成"""
        return self.status == "COMPLETED"
    
    def get_profit_side(self) -> str:
        """获取止盈订单方向"""
        return "sell" if self.main_side == "buy" else "buy"
    
    def get_close_hedge_side(self) -> str:
        """获取平仓对冲单方向"""
        return "buy" if self.hedge_side == "sell" else "sell"


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

        # Create hedge exchange if hedge is enabled
        self.hedge_exchange = None
        self.hedge_contract_id = None  # Store hedge exchange's contract_id
        if config.enable_hedge:
            try:
                # Create a separate config for hedge exchange to avoid contract_id conflicts
                from copy import deepcopy
                hedge_config = deepcopy(config)
                hedge_config.exchange = config.hedge_exchange
                
                self.hedge_exchange = ExchangeFactory.create_exchange(
                    config.hedge_exchange,
                    hedge_config
                )
                self.logger.log(f"Hedge exchange initialized for {config.hedge_exchange}", "INFO")
            except ValueError as e:
                self.logger.log(f"Failed to create hedge exchange: {e}", "ERROR")
                raise ValueError(f"Failed to create hedge exchange: {e}")

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

        # 对冲相关状态
        self.active_hedge_positions = []  # 活跃的对冲位置列表
        self.hedge_closing_in_progress = False  # 对冲平仓是否正在进行中

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
                
                # 注册回调函数以增强集成
                self.drawdown_monitor.set_warning_callback(DrawdownLevel.LIGHT_WARNING, self._on_light_drawdown_warning)
                self.drawdown_monitor.set_warning_callback(DrawdownLevel.MEDIUM_WARNING, self._on_medium_drawdown_warning)
                self.drawdown_monitor.set_warning_callback(DrawdownLevel.SEVERE_STOP_LOSS, self._on_severe_drawdown_warning)
                self.drawdown_monitor.set_stop_loss_callback(self._on_stop_loss_triggered)
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
            # 注意：对冲平仓现在在主循环中提前执行，这里只处理连接断开
            self.logger.log("执行最终清理和连接断开", "INFO")
            
            # Disconnect from main exchange
            await self.exchange_client.disconnect()
            self.logger.log("Main exchange disconnected", "INFO")
            
            # Disconnect from hedge exchange only if hedge mode is enabled
            if self.config.enable_hedge and self.hedge_exchange:
                await self.hedge_exchange.disconnect()
                self.logger.log("Hedge exchange disconnected", "INFO")
            elif not self.config.enable_hedge:
                self.logger.log("Hedge mode disabled, skipping hedge exchange disconnect", "INFO")
            
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
                    elif order_type == "CLOSE":
                        # 检查是否是止盈订单成交，需要平仓对冲单
                        if self.config.enable_hedge and self.hedge_exchange:
                            hedge_position = self._find_hedge_position_by_profit_order(order_id)
                            if hedge_position:
                                # 异步执行对冲平仓
                                if self.loop is not None:
                                    self.loop.call_soon_threadsafe(
                                        lambda: asyncio.create_task(self._handle_take_profit_filled(hedge_position))
                                    )

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
            # 主订单成交，检查是否需要执行对冲
            hedge_position = None
            if self.config.enable_hedge and self.hedge_exchange:
                try:
                    hedge_position = await self._execute_immediate_hedge(order_id, filled_price, self.config.quantity, self.config.direction)
                    self.logger.log(f"[HEDGE] 对冲订单已执行: {hedge_position.hedge_order_id}", "INFO")
                except Exception as e:
                    self.logger.log(f"[HEDGE] 对冲执行失败: {e}", "ERROR")
                    # 启动对冲开仓失败补救机制
                    hedge_position = await self._handle_hedge_opening_failure(
                        order_id, filled_price, self.config.quantity, self.config.direction, str(e)
                    )
                    if hedge_position:
                        self.logger.log(f"[HEDGE] 对冲开仓补救成功: {hedge_position.hedge_order_id}", "INFO")
                    else:
                        self.logger.log(f"[HEDGE] 对冲开仓补救失败，存在风险敞口", "ERROR")
            
            if self.config.aster_boost:
                close_order_result = await self.exchange_client.place_market_order(
                    self.config.contract_id,
                    self.config.quantity,
                    self.config.close_order_side
                )
                
                if not close_order_result.success:
                    self.logger.log(f"[CLOSE] Failed to place market order: {close_order_result.error_message}", "ERROR")
                    raise Exception(f"[CLOSE] Failed to place market order: {close_order_result.error_message}")
                
                return True
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

                # 如果有对冲位置，更新止盈订单ID
                if hedge_position:
                    hedge_position.take_profit_order_id = close_order_result.order_id
                    hedge_position.status = "PROFIT_PENDING"
                    self.logger.log(f"[HEDGE] 止盈订单已挂单: {close_order_result.order_id}", "INFO")

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
                
                # 部分成交时也执行对冲
                hedge_position = None
                if self.config.enable_hedge and self.hedge_exchange:
                    try:
                        hedge_position = await self._execute_immediate_hedge(order_id, filled_price, self.order_filled_amount, self.config.direction)
                        self.logger.log(f"[HEDGE] 部分成交对冲订单已执行: {hedge_position.hedge_order_id}", "INFO")
                    except Exception as e:
                        self.logger.log(f"[HEDGE] 部分成交对冲执行失败: {e}", "ERROR")
                        # 启动对冲开仓失败补救机制
                        hedge_position = await self._handle_hedge_opening_failure(
                            order_id, filled_price, self.order_filled_amount, self.config.direction, str(e)
                        )
                        if hedge_position:
                            self.logger.log(f"[HEDGE] 部分成交对冲开仓补救成功: {hedge_position.hedge_order_id}", "INFO")
                        else:
                            self.logger.log(f"[HEDGE] 部分成交对冲开仓补救失败，存在风险敞口", "ERROR")
                
                close_side = self.config.close_order_side
                if self.config.aster_boost:
                    close_order_result = await self.exchange_client.place_market_order(
                        self.config.contract_id,
                        self.order_filled_amount,
                        close_side
                    )
                    if not close_order_result.success:
                        self.logger.log(f"[CLOSE] Failed to place market order for partial fill: {close_order_result.error_message}", "ERROR")
                        raise Exception(f"[CLOSE] Failed to place market order for partial fill: {close_order_result.error_message}")
                    return True
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
                else:
                    # 如果有对冲位置，更新止盈订单ID
                    if hedge_position:
                        hedge_position.take_profit_order_id = close_order_result.order_id
                        hedge_position.status = "PROFIT_PENDING"
                        self.logger.log(f"[HEDGE] 部分成交止盈订单已挂单: {close_order_result.order_id}", "INFO")

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
                if active_orders is not None:
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

    # 对冲位置管理方法
    def _find_hedge_position_by_main_order(self, main_order_id: str) -> Optional[HedgePosition]:
        """根据主订单ID查找对冲位置"""
        for position in self.active_hedge_positions:
            if position.main_order_id == main_order_id:
                return position
        return None
    
    def _find_hedge_position_by_profit_order(self, profit_order_id: str) -> Optional[HedgePosition]:
        """根据止盈订单ID查找对冲位置"""
        for position in self.active_hedge_positions:
            if position.take_profit_order_id == profit_order_id:
                return position
        return None
    
    def _remove_completed_hedge_positions(self):
        """移除已完成的对冲位置"""
        self.active_hedge_positions = [
            pos for pos in self.active_hedge_positions 
            if not pos.is_completed()
        ]
    
    def _log_hedge_cycle_completed(self, hedge_position: HedgePosition):
        """记录对冲周期完成日志"""
        duration = time.time() - hedge_position.created_time
        self.logger.log(
            f"对冲周期完成 - 主订单:{hedge_position.main_order_id} "
            f"数量:{hedge_position.quantity} 耗时:{duration:.2f}秒", 
            "INFO"
        )

    async def _execute_immediate_hedge(self, main_order_id: str, main_fill_price: Decimal, quantity: Decimal, main_side: str) -> HedgePosition:
        """执行立即对冲订单"""
        # 确定对冲方向（与主订单相反）
        hedge_side = "sell" if main_side == "buy" else "buy"
        
        # 添加对冲延迟
        if self.config.hedge_delay > 0:
            await asyncio.sleep(self.config.hedge_delay)
        
        # 验证对冲交易所价格可用性（带重试）
        max_retries = 3
        retry_delay = 1.0
        
        for attempt in range(max_retries):
            try:
                if hasattr(self.hedge_exchange, 'fetch_bbo_prices'):
                    bid_price, ask_price = await self.hedge_exchange.fetch_bbo_prices(self.hedge_contract_id)
                    if bid_price <= 0 or ask_price <= 0:
                        raise Exception(f"对冲交易所价格无效: bid={bid_price}, ask={ask_price}")
                    self.logger.log(f"[HEDGE] 对冲交易所价格验证通过: bid={bid_price}, ask={ask_price}", "DEBUG")
                    break  # 价格验证成功，跳出重试循环
            except Exception as e:
                self.logger.log(f"[HEDGE] 对冲交易所价格验证失败 (尝试 {attempt + 1}/{max_retries}): {e}", "WARNING")
                if attempt == max_retries - 1:
                    # 最后一次尝试失败
                    raise Exception(f"对冲交易所价格验证失败，已重试 {max_retries} 次: {e}")
                else:
                    # 等待后重试
                    await asyncio.sleep(retry_delay)
                    retry_delay *= 2  # 指数退避
        
        # 在对冲交易所下市价单（带重试和滑点处理）
        hedge_order_result = None
        for attempt in range(max_retries):
            try:
                hedge_order_result = await self.hedge_exchange.place_market_order(
                    self.hedge_contract_id,
                    quantity,
                    hedge_side
                )
                
                # 检查订单结果
                if hedge_order_result.success:
                    # 检查订单状态，处理滑点取消情况
                    if hasattr(hedge_order_result, 'status') and hedge_order_result.status:
                        if hedge_order_result.status in ["FILLED", "PARTIALLY_FILLED"]:
                            # 订单成功执行
                            break
                        elif "SLIPPAGE" in hedge_order_result.status.upper() or hedge_order_result.status == "CANCELED":
                            # 滑点过大被取消，需要重试
                            self.logger.log(f"[HEDGE] 对冲订单因滑点被取消 (尝试 {attempt + 1}/{max_retries}): {hedge_order_result.status}", "WARNING")
                            if attempt == max_retries - 1:
                                raise Exception(f"对冲订单因滑点被取消，已重试 {max_retries} 次: {hedge_order_result.status}")
                            else:
                                await asyncio.sleep(1.0)
                                continue
                        elif hedge_order_result.status == "PENDING":
                            # 订单挂起，等待确认
                            await asyncio.sleep(2.0)
                            # 检查是否有成交
                            if hasattr(hedge_order_result, 'filled_size') and hedge_order_result.filled_size and hedge_order_result.filled_size > 0:
                                break
                            else:
                                self.logger.log(f"[HEDGE] 对冲订单挂起状态超时 (尝试 {attempt + 1}/{max_retries})", "WARNING")
                                if attempt == max_retries - 1:
                                    raise Exception(f"对冲订单挂起状态超时，已重试 {max_retries} 次")
                                else:
                                    await asyncio.sleep(1.0)
                                    continue
                        else:
                            # 其他状态，直接成功
                            break
                    else:
                        # 没有状态信息，假设成功
                        break
                else:
                    # 订单下单失败
                    error_msg = hedge_order_result.error_message if hasattr(hedge_order_result, 'error_message') else "未知错误"
                    self.logger.log(f"[HEDGE] 对冲订单下单失败 (尝试 {attempt + 1}/{max_retries}): {error_msg}", "WARNING")
                    if attempt == max_retries - 1:
                        raise Exception(f"对冲订单下单失败，已重试 {max_retries} 次: {error_msg}")
                    else:
                        await asyncio.sleep(1.0)
                        continue
                        
            except Exception as e:
                self.logger.log(f"[HEDGE] 对冲订单执行异常 (尝试 {attempt + 1}/{max_retries}): {e}", "WARNING")
                if attempt == max_retries - 1:
                    # 最后一次尝试失败
                    raise Exception(f"对冲订单执行异常，已重试 {max_retries} 次: {e}")
                else:
                    # 等待后重试
                    await asyncio.sleep(1.0)
        
        # 最终检查订单结果
        if not hedge_order_result or not hedge_order_result.success:
            error_msg = hedge_order_result.error_message if hedge_order_result and hasattr(hedge_order_result, 'error_message') else "未知错误"
            raise Exception(f"对冲订单最终失败: {error_msg}")
        
        # 创建对冲位置记录
        hedge_position = HedgePosition(
            main_order_id=main_order_id,
            hedge_order_id=hedge_order_result.order_id,
            quantity=quantity,
            main_side=main_side,
            hedge_side=hedge_side,
            status="HEDGING",
            created_time=time.time(),
            main_fill_price=main_fill_price,
            hedge_fill_price=hedge_order_result.price  # 市价单立即成交
        )
        
        # 添加到活跃对冲位置列表
        self.active_hedge_positions.append(hedge_position)
        
        self.logger.log(
            f"[HEDGE] 对冲订单执行成功 - 主订单:{main_order_id} 对冲订单:{hedge_order_result.order_id} "
            f"数量:{quantity} 主价格:{main_fill_price} 对冲价格:{hedge_order_result.price}",
            "INFO"
        )
        
        return hedge_position

    async def _handle_take_profit_filled(self, hedge_position: HedgePosition):
        """处理止盈订单成交后的对冲平仓"""
        try:
            self.logger.log(f"止盈订单成交，开始平仓对冲单: {hedge_position.hedge_order_id}", "INFO")
            
            # 更新对冲位置状态
            hedge_position.status = "CLOSING"
            
            # 在对冲交易所平仓对冲单
            close_side = hedge_position.get_close_hedge_side()
            
            close_order_result = await self.hedge_exchange.place_market_order(
                contract_id=self.hedge_contract_id,
                quantity=hedge_position.quantity,
                direction=close_side,
                reduce_only=True
            )
            
            if close_order_result and close_order_result.order_id:
                self.logger.log(f"对冲平仓订单已下单: {close_order_result.order_id} "
                               f"[{close_side}] {hedge_position.quantity}", "INFO")
                
                # 检查订单实际执行状态
                order_success = False
                
                # 检查订单状态字段
                if close_order_result.status:
                    if close_order_result.status in ['FILLED', 'PARTIALLY_FILLED']:
                        order_success = True
                        self.logger.log(f"对冲平仓订单执行成功: {close_order_result.order_id} "
                                       f"状态: {close_order_result.status}", "INFO")
                    elif close_order_result.status in ['CANCELED', 'CANCELED-TOO-MUCH-SLIPPAGE']:
                        self.logger.log(f"对冲平仓订单被取消: {close_order_result.order_id} "
                                       f"状态: {close_order_result.status}", "WARNING")
                    else:
                        self.logger.log(f"对冲平仓订单状态未知: {close_order_result.order_id} "
                                       f"状态: {close_order_result.status}", "WARNING")
                
                # 检查成交数量字段
                elif close_order_result.filled_size is not None and close_order_result.filled_size > 0:
                    order_success = True
                    self.logger.log(f"对冲平仓订单部分成交: {close_order_result.order_id} "
                                   f"成交数量: {close_order_result.filled_size}", "INFO")
                
                # 检查错误消息字段
                elif close_order_result.error_message:
                    if "awaiting confirmation" in close_order_result.error_message:
                        self.logger.log(f"对冲平仓订单等待确认: {close_order_result.order_id} "
                                       f"消息: {close_order_result.error_message}", "WARNING")
                    else:
                        self.logger.log(f"对冲平仓订单出现错误: {close_order_result.order_id} "
                                       f"错误: {close_order_result.error_message}", "ERROR")
                
                # 如果没有明确的状态信息，记录警告
                else:
                    self.logger.log(f"对冲平仓订单状态不明确: {close_order_result.order_id} "
                                   f"需要进一步确认", "WARNING")
                
                # 只有在订单真正成功执行时才标记为完成
                if order_success:
                    # 更新状态为已完成
                    hedge_position.status = "COMPLETED"
                    
                    # 记录对冲周期完成
                    self._log_hedge_cycle_completed(hedge_position)
                    
                    # 清理已完成的对冲位置
                    self._remove_completed_hedge_positions()
                else:
                    # 订单失败或状态不明确，启动重试机制
                    self.logger.log(f"对冲平仓订单执行失败或状态不明确，启动重试机制: {hedge_position.hedge_order_id}", "ERROR")
                    await self._handle_hedge_close_failure(hedge_position, close_order_result)
                
            else:
                self.logger.log(f"对冲平仓订单下单失败: {hedge_position.hedge_order_id}", "ERROR")
                
        except Exception as e:
            self.logger.log(f"处理止盈成交后对冲平仓时出错: {e}", "ERROR")
            self.logger.log(f"Traceback: {traceback.format_exc()}", "ERROR")

    async def _handle_hedge_close_failure(self, hedge_position: HedgePosition, failed_order_result):
        """
        处理对冲平仓失败的情况，使用Lighter交易所的内置重试机制
        
        Args:
            hedge_position: 对冲位置
            failed_order_result: 失败的订单结果
        """
        try:
            self.logger.log(f"对冲平仓失败，使用内置重试机制: {failed_order_result.error_message}", "WARNING")
            
            # 使用Lighter交易所的带重试机制的市价单方法
            close_side = hedge_position.get_close_hedge_side()
            current_size = abs(hedge_position.quantity)
            
            # 检查对冲交易所是否支持带重试机制的方法
            if hasattr(self.hedge_exchange, 'place_market_order_with_retry'):
                self.logger.log(f"使用带重试机制的市价单进行对冲平仓: {close_side} {current_size}", "INFO")
                
                retry_order_result = await self.hedge_exchange.place_market_order_with_retry(
                    contract_id=self.config.contract_id,
                    direction=close_side,
                    quantity=Decimal(str(current_size)),
                    max_retries=5,
                    initial_delay=0.3
                )
                
                if retry_order_result.success:
                    self.logger.log(f"对冲平仓重试成功", "INFO")
                    hedge_position.status = "COMPLETED"
                    return
                else:
                    # 重试机制也失败了
                    self.logger.log(f"对冲平仓重试机制失败: {retry_order_result.error_message}", "ERROR")
                    error_msg = f"🚨 对冲平仓失败警报\n" \
                               f"合约: {self.config.contract_id}\n" \
                               f"对冲订单ID: {hedge_position.hedge_order_id}\n" \
                               f"重试机制失败: {retry_order_result.error_message}\n" \
                               f"请手动检查并处理对冲持仓！"
                    await self.send_notification(error_msg)
                    hedge_position.status = "CLOSING"
            else:
                # 如果对冲交易所不支持重试机制，回退到原始方法
                self.logger.log(f"对冲交易所不支持重试机制，使用原始方法", "WARNING")
                error_msg = f"🚨 对冲平仓失败警报\n" \
                           f"合约: {self.config.contract_id}\n" \
                           f"对冲订单ID: {hedge_position.hedge_order_id}\n" \
                           f"错误: {failed_order_result.error_message}\n" \
                           f"请手动检查并处理对冲持仓！"
                await self.send_notification(error_msg)
                hedge_position.status = "CLOSING"
                
        except Exception as e:
            self.logger.log(f"调用重试机制时发生异常: {e}", "ERROR")
            self.logger.log(f"Traceback: {traceback.format_exc()}", "ERROR")
            error_msg = f"🚨 对冲平仓异常警报\n" \
                       f"合约: {self.config.contract_id}\n" \
                       f"对冲订单ID: {hedge_position.hedge_order_id}\n" \
                       f"异常: {str(e)}\n" \
                       f"请手动检查并处理对冲持仓！"
            await self.send_notification(error_msg)
            hedge_position.status = "CLOSING"

    async def _handle_hedge_opening_failure(self, main_order_id: str, main_fill_price: Decimal, quantity: Decimal, main_side: str, original_error: str) -> Optional[HedgePosition]:
        """
        处理对冲开仓失败的情况，实现重试和补救机制
        
        Args:
            main_order_id: 主订单ID
            main_fill_price: 主订单成交价格
            quantity: 对冲数量
            main_side: 主订单方向
            original_error: 原始错误信息
            
        Returns:
            HedgePosition: 成功时返回对冲位置，失败时返回None
        """
        try:
            max_retries = 5  # 额外重试2次
            retry_delay = 0.3  # 初始重试延迟2秒
            
            self.logger.log(f"[HEDGE] 对冲开仓失败，启动补救机制。原始错误: {original_error}", "WARNING")
            
            for retry_count in range(1, max_retries + 1):
                self.logger.log(f"[HEDGE] 对冲开仓补救重试 {retry_count}/{max_retries}", "INFO")
                
                # 等待一段时间，让市场条件可能改善
                await asyncio.sleep(retry_delay)
                
                try:
                    # 重新尝试对冲开仓
                    hedge_position = await self._execute_immediate_hedge(main_order_id, main_fill_price, quantity, main_side)
                    self.logger.log(f"[HEDGE] 对冲开仓补救成功: {hedge_position.hedge_order_id}", "INFO")
                    return hedge_position
                    
                except Exception as e:
                    self.logger.log(f"[HEDGE] 对冲开仓补救重试 {retry_count} 失败: {e}", "WARNING")
                    retry_delay *= 1.2  # 指数退避
            
            # 所有补救重试都失败了
            self.logger.log(f"[HEDGE] 对冲开仓补救全部失败，已达到最大重试次数 {max_retries}", "ERROR")
            
            # 发送紧急通知
            error_msg = f"🚨 对冲开仓失败警报\n" \
                       f"合约: {self.config.contract_id}\n" \
                       f"主订单ID: {main_order_id}\n" \
                       f"主订单价格: {main_fill_price}\n" \
                       f"对冲数量: {quantity}\n" \
                       f"主订单方向: {main_side}\n" \
                       f"补救重试次数: {max_retries}\n" \
                       f"原始错误: {original_error}\n" \
                       f"⚠️ 存在未对冲风险敞口，请立即手动处理！"
            
            await self.send_notification(error_msg)
            
            return None
            
        except Exception as e:
            self.logger.log(f"[HEDGE] 处理对冲开仓失败时出错: {e}", "ERROR")
            self.logger.log(f"Traceback: {traceback.format_exc()}", "ERROR")
            return None

    async def _close_all_hedge_positions_on_stop_loss(self) -> dict:
        """
        在止损触发后平仓所有活跃的对冲位置
        优化版本：通过获取实际持仓总量一次性平仓，而不是逐个平仓
        
        Returns:
            dict: 平仓结果统计 {
                'total_positions': int,      # 总对冲位置数
                'closed_successfully': int,  # 成功平仓数
                'failed_to_close': int,      # 平仓失败数
                'errors': list              # 错误信息列表
            }
        """
        result = {
            'total_positions': 0,
            'closed_successfully': 0,
            'failed_to_close': 0,
            'errors': []
        }
        
        try:
            # 检查是否启用对冲功能
            if not self.config.enable_hedge:
                self.logger.log("对冲功能未启用，跳过对冲平仓", "INFO")
                return result
            
            # 检查是否有对冲客户端
            if not hasattr(self, 'hedge_exchange') or self.hedge_exchange is None:
                error_msg = "对冲客户端未初始化，无法执行对冲平仓"
                self.logger.log(error_msg, "ERROR")
                result['errors'].append(error_msg)
                return result
            
            # 获取所有活跃的对冲位置
            active_hedge_positions = [
                pos for pos in self.active_hedge_positions 
                if not pos.is_completed() and pos.status in ["HEDGING", "PROFIT_PENDING", "CLOSING"]
            ]
            
            result['total_positions'] = len(active_hedge_positions)
            
            if result['total_positions'] == 0:
                self.logger.log("没有活跃的对冲位置需要平仓", "INFO")
                return result
            
            self.logger.log("=" * 60, "WARNING")
            self.logger.log("开始执行止损时对冲平仓操作（优化版本：一次性平仓）", "WARNING")
            self.logger.log(f"发现 {result['total_positions']} 个活跃对冲位置需要平仓", "WARNING")
            self.logger.log("=" * 60, "WARNING")
            
            # 获取对冲交易所的实际持仓总量（增强版本：延迟+重试）
            try:
                self.logger.log("正在获取对冲交易所的实际持仓总量...", "INFO")
                
                # 等待3秒让对冲交易所数据同步
                self.logger.log("等待对冲交易所数据同步（3秒）...", "INFO")
                await asyncio.sleep(3)
                
                # 重试机制：最多重试3次
                current_hedge_position = None
                for retry_count in range(3):
                    try:
                        current_hedge_position = await self.hedge_exchange.get_account_positions()
                        self.logger.log(f"对冲交易所持仓查询结果（第{retry_count + 1}次）: {current_hedge_position}", "INFO")
                        
                        # 调试日志：显示详细的判断过程
                        abs_position = abs(current_hedge_position)
                        self.logger.log(f"🔍 持仓判断详情: abs({current_hedge_position}) = {abs_position}, 阈值: 0.0001", "INFO")
                        
                        # 如果查询到有持仓，立即跳出重试循环（降低阈值到0.0001）
                        if abs_position > 0.0001:
                            self.logger.log(f"✅ 对冲交易所确认有持仓: {current_hedge_position}，继续执行平仓", "INFO")
                            break
                        
                        # 如果是最后一次重试，记录详细信息
                        if retry_count == 2:
                            self.logger.log(f"⚠️ 重试{retry_count + 1}次后仍无持仓，活跃对冲位置数: {len(active_hedge_positions)}", "WARNING")
                            break
                        
                        # 等待2秒后重试
                        self.logger.log(f"❌ 第{retry_count + 1}次查询无持仓（{abs_position} <= 0.0001），2秒后重试...", "INFO")
                        await asyncio.sleep(2)
                        
                    except Exception as e:
                        self.logger.log(f"第{retry_count + 1}次持仓查询失败: {str(e)}", "ERROR")
                        if retry_count == 2:  # 最后一次重试
                            raise
                        await asyncio.sleep(2)
                
                # 检查是否真的无持仓（使用与上面一致的阈值）
                if abs(current_hedge_position) <= 0.0001:
                    # 记录详细的诊断信息
                    self.logger.log("🔍 对冲平仓诊断信息:", "WARNING")
                    self.logger.log(f"  - 活跃对冲位置数量: {len(active_hedge_positions)}", "WARNING")
                    self.logger.log(f"  - 对冲交易所查询持仓: {current_hedge_position}", "WARNING")
                    self.logger.log(f"  - 对冲交易所名称: {self.hedge_exchange.get_exchange_name()}", "WARNING")
                    
                    # 如果有活跃对冲位置但查询无持仓，可能是数据同步问题
                    if len(active_hedge_positions) > 0:
                        self.logger.log("⚠️ 检测到数据不一致：有活跃对冲位置但查询无持仓", "WARNING")
                        self.logger.log("可能原因：1) 对冲交易所数据同步延迟 2) API连接问题 3) 对冲订单已被其他方式平仓", "WARNING")
                    
                    self.logger.log("对冲交易所无持仓，标记所有对冲位置为已完成", "INFO")
                    # 标记所有对冲位置为已完成
                    for hedge_position in active_hedge_positions:
                        hedge_position.status = "COMPLETED"
                        self._log_hedge_cycle_completed(hedge_position)
                        result['closed_successfully'] += 1
                    
                    # 清理已完成的对冲位置
                    self._remove_completed_hedge_positions()
                    
                    self.logger.log(f"所有 {result['total_positions']} 个对冲位置已标记为完成", "INFO")
                    return result
                
                # 确定平仓方向和数量（修复：使用对冲位置的正确方向信息）
                close_quantity = abs(current_hedge_position)
                
                # 从活跃对冲位置获取正确的平仓方向
                # 注意：所有活跃对冲位置应该有相同的对冲方向，因为它们都是同一策略的对冲
                if active_hedge_positions:
                    # 使用第一个活跃对冲位置的平仓方向（所有对冲位置方向应该一致）
                    close_side = active_hedge_positions[0].get_close_hedge_side()
                    hedge_side = active_hedge_positions[0].hedge_side
                    self.logger.log(f"🔧 平仓方向计算: 对冲方向={hedge_side} -> 平仓方向={close_side}", "INFO")
                else:
                    # 备用逻辑：如果没有活跃对冲位置，根据持仓数量判断（不应该发生）
                    close_side = "sell" if current_hedge_position > 0 else "buy"
                    self.logger.log(f"⚠️ 使用备用平仓方向逻辑: 持仓={current_hedge_position} -> 平仓方向={close_side}", "WARNING")
                
                self.logger.log(f"对冲交易所实际持仓: {current_hedge_position}, 平仓方向: {close_side}, 平仓数量: {close_quantity}", "INFO")
                
                # 使用带重试机制的市价单一次性平仓所有持仓
                if hasattr(self.hedge_exchange, 'place_market_order_with_retry'):
                    self.logger.log("使用带重试机制的市价单进行一次性对冲平仓", "INFO")
                    
                    close_order_result = await self.hedge_exchange.place_market_order_with_retry(
                        contract_id=self.hedge_contract_id,
                        direction=close_side,
                        quantity=Decimal(str(close_quantity)),
                        max_retries=5,
                        initial_delay=0.5  # 增加初始延迟，避免滑点
                    )
                    
                    if close_order_result.success:
                        self.logger.log(f"一次性对冲平仓成功: {close_order_result.order_id} [{close_side}] {close_quantity}", "INFO")
                        
                        # 标记所有对冲位置为已完成
                        for hedge_position in active_hedge_positions:
                            hedge_position.status = "COMPLETED"
                            self._log_hedge_cycle_completed(hedge_position)
                            result['closed_successfully'] += 1
                        
                        # 清理已完成的对冲位置
                        self._remove_completed_hedge_positions()
                        
                    else:
                        error_msg = f"一次性对冲平仓失败: {close_order_result.error_message}"
                        self.logger.log(error_msg, "ERROR")
                        result['failed_to_close'] = result['total_positions']
                        result['errors'].append(error_msg)
                        
                        # 回退到逐个平仓模式
                        self.logger.log("回退到逐个平仓模式...", "WARNING")
                        return await self._fallback_individual_hedge_close(active_hedge_positions, result)
                
                else:
                    # 对冲交易所不支持重试机制，使用普通市价单
                    self.logger.log("对冲交易所不支持重试机制，使用普通市价单", "WARNING")
                    
                    close_order_result = await self.hedge_exchange.place_market_order(
                        contract_id=self.hedge_contract_id,
                        direction=close_side,
                        quantity=Decimal(str(close_quantity)),
                        reduce_only=True
                    )
                    
                    if close_order_result and close_order_result.order_id:
                        self.logger.log(f"一次性对冲平仓成功: {close_order_result.order_id} [{close_side}] {close_quantity}", "INFO")
                        
                        # 标记所有对冲位置为已完成
                        for hedge_position in active_hedge_positions:
                            hedge_position.status = "COMPLETED"
                            self._log_hedge_cycle_completed(hedge_position)
                            result['closed_successfully'] += 1
                        
                        # 清理已完成的对冲位置
                        self._remove_completed_hedge_positions()
                        
                    else:
                        error_msg = "一次性对冲平仓失败"
                        self.logger.log(error_msg, "ERROR")
                        result['failed_to_close'] = result['total_positions']
                        result['errors'].append(error_msg)
                        
                        # 回退到逐个平仓模式
                        self.logger.log("回退到逐个平仓模式...", "WARNING")
                        return await self._fallback_individual_hedge_close(active_hedge_positions, result)
                
            except Exception as e:
                error_msg = f"获取对冲交易所持仓或执行一次性平仓时出错: {e}"
                self.logger.log(error_msg, "ERROR")
                self.logger.log(f"Traceback: {traceback.format_exc()}", "ERROR")
                result['errors'].append(error_msg)
                
                # 回退到逐个平仓模式
                self.logger.log("回退到逐个平仓模式...", "WARNING")
                return await self._fallback_individual_hedge_close(active_hedge_positions, result)
            
            # 记录最终结果
            self.logger.log("=" * 60, "WARNING")
            self.logger.log("止损时对冲平仓操作完成（一次性平仓模式）", "WARNING")
            self.logger.log(f"总对冲位置: {result['total_positions']}", "WARNING")
            self.logger.log(f"成功平仓: {result['closed_successfully']}", "WARNING")
            self.logger.log(f"平仓失败: {result['failed_to_close']}", "WARNING")
            if result['errors']:
                self.logger.log(f"错误数量: {len(result['errors'])}", "WARNING")
            self.logger.log("=" * 60, "WARNING")
            
        except Exception as e:
            error_msg = f"执行止损时对冲平仓操作时发生严重错误: {e}"
            self.logger.log(error_msg, "ERROR")
            self.logger.log(f"Traceback: {traceback.format_exc()}", "ERROR")
            result['errors'].append(error_msg)
        
        return result

    async def _fallback_individual_hedge_close(self, active_hedge_positions: list, result: dict) -> dict:
        """
        回退到逐个平仓模式的方法
        当一次性平仓失败时使用此方法作为备用方案
        
        Args:
            active_hedge_positions: 活跃的对冲位置列表
            result: 当前的结果统计字典
            
        Returns:
            dict: 更新后的平仓结果统计
        """
        try:
            self.logger.log("开始执行回退逐个平仓模式", "WARNING")
            
            # 重置计数器
            result['closed_successfully'] = 0
            result['failed_to_close'] = 0
            
            # 逐个平仓所有对冲位置
            for i, hedge_position in enumerate(active_hedge_positions, 1):
                try:
                    self.logger.log(f"[{i}/{result['total_positions']}] 正在平仓对冲位置: "
                                   f"主订单={hedge_position.main_order_id}, "
                                   f"对冲订单={hedge_position.hedge_order_id}, "
                                   f"状态={hedge_position.status}", "INFO")
                    
                    # 确定平仓方向
                    close_side = hedge_position.get_close_hedge_side()
                    
                    # 优先使用带重试机制的市价单
                    if hasattr(self.hedge_exchange, 'place_market_order_with_retry'):
                        close_order_result = await self.hedge_exchange.place_market_order_with_retry(
                            contract_id=self.hedge_contract_id,
                            direction=close_side,
                            quantity=hedge_position.quantity,
                            max_retries=3,
                            initial_delay=0.3
                        )
                        
                        if close_order_result.success:
                            self.logger.log(f"[{i}/{result['total_positions']}] 对冲平仓订单成功下单（重试模式）: "
                                           f"{close_order_result.order_id} [{close_side}] {hedge_position.quantity}", "INFO")
                            
                            # 更新对冲位置状态
                            hedge_position.status = "COMPLETED"
                            result['closed_successfully'] += 1
                            
                            # 记录对冲周期完成
                            self._log_hedge_cycle_completed(hedge_position)
                        else:
                            error_msg = f"[{i}/{result['total_positions']}] 对冲平仓订单下单失败（重试模式）: {close_order_result.error_message}"
                            self.logger.log(error_msg, "ERROR")
                            result['failed_to_close'] += 1
                            result['errors'].append(error_msg)
                    else:
                        # 使用普通市价单
                        close_order_result = await self.hedge_exchange.place_market_order(
                            contract_id=self.hedge_contract_id,
                            direction=close_side,
                            quantity=hedge_position.quantity,
                            reduce_only=True
                        )
                        
                        if close_order_result and hasattr(close_order_result, 'order_id') and close_order_result.order_id:
                            self.logger.log(f"[{i}/{result['total_positions']}] 对冲平仓订单成功下单: "
                                           f"{close_order_result.order_id} [{close_side}] {hedge_position.quantity}", "INFO")
                            
                            # 更新对冲位置状态
                            hedge_position.status = "COMPLETED"
                            result['closed_successfully'] += 1
                            
                            # 记录对冲周期完成
                            self._log_hedge_cycle_completed(hedge_position)
                        else:
                            error_msg = f"[{i}/{result['total_positions']}] 对冲平仓订单下单失败: {hedge_position.hedge_order_id}"
                            self.logger.log(error_msg, "ERROR")
                            result['failed_to_close'] += 1
                            result['errors'].append(error_msg)
                    
                    # 添加短暂延迟，避免API限制
                    if i < result['total_positions']:
                        await asyncio.sleep(0.1)
                        
                except Exception as e:
                    error_msg = f"[{i}/{result['total_positions']}] 平仓对冲位置时出错: {hedge_position.hedge_order_id}, 错误: {e}"
                    self.logger.log(error_msg, "ERROR")
                    self.logger.log(f"Traceback: {traceback.format_exc()}", "ERROR")
                    result['failed_to_close'] += 1
                    result['errors'].append(error_msg)
            
            # 清理已完成的对冲位置
            self._remove_completed_hedge_positions()
            
            self.logger.log("回退逐个平仓模式执行完成", "WARNING")
            
        except Exception as e:
            error_msg = f"执行回退逐个平仓模式时发生错误: {e}"
            self.logger.log(error_msg, "ERROR")
            self.logger.log(f"Traceback: {traceback.format_exc()}", "ERROR")
            result['errors'].append(error_msg)
        
        return result

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
    
    # Drawdown monitor callback functions
    async def _on_light_drawdown_warning(self, current_drawdown: float, peak_networth: float, current_networth: float):
        """Callback for light drawdown warning."""
        message = f"⚠️ Light Drawdown Warning\n"
        message += f"Current Drawdown: {current_drawdown:.2%}\n"
        message += f"Peak Net Worth: ${peak_networth:,.2f}\n"
        message += f"Current Net Worth: ${current_networth:,.2f}"
        await self.send_notification(message)
    
    async def _on_medium_drawdown_warning(self, current_drawdown: float, peak_networth: float, current_networth: float):
        """Callback for medium drawdown warning."""
        self.trading_paused = True
        message = f"🟡 Medium Drawdown Warning - Trading Paused\n"
        message += f"Current Drawdown: {current_drawdown:.2%}\n"
        message += f"Peak Net Worth: ${peak_networth:,.2f}\n"
        message += f"Current Net Worth: ${current_networth:,.2f}\n"
        message += f"New orders are paused until drawdown reduces."
        await self.send_notification(message)
    
    async def _on_severe_drawdown_warning(self, current_drawdown: float, peak_networth: float, current_networth: float):
        """Callback for severe drawdown warning."""
        message = f"🔴 Severe Drawdown Warning - Stop Loss Imminent\n"
        message += f"Current Drawdown: {current_drawdown:.2%}\n"
        message += f"Peak Net Worth: ${peak_networth:,.2f}\n"
        message += f"Current Net Worth: ${current_networth:,.2f}\n"
        message += f"Automatic stop-loss will be triggered."
        await self.send_notification(message)
    
    async def _on_stop_loss_triggered(self, current_drawdown: float, peak_networth: float, current_networth: float, loss_amount: float):
        """Callback for stop-loss trigger."""
        message = f"🚨 STOP LOSS TRIGGERED\n"
        message += f"Current Drawdown: {current_drawdown:.2%}\n"
        message += f"Peak Net Worth: ${peak_networth:,.2f}\n"
        message += f"Current Net Worth: ${current_networth:,.2f}\n"
        message += f"Loss Amount: ${loss_amount:,.2f}\n"
        message += f"Automatic position closure initiated."
        await self.send_notification(message)
        
        # 在主订单止损完成后，执行对冲平仓操作
        try:
            # 仅在启用对冲时执行对冲平仓
            if self.config.enable_hedge and self.active_hedge_positions:
                self.logger.log("主订单止损完成，开始执行对冲平仓操作", "INFO")
                self.hedge_closing_in_progress = True  # 设置对冲平仓进行中标志
                
                # 执行对冲平仓
                hedge_close_result = await self._close_all_hedge_positions_on_stop_loss()
            
                # 发送对冲平仓结果通知
                if hedge_close_result['total_positions'] > 0:
                    hedge_message = f"🔄 对冲平仓操作完成\n"
                    hedge_message += f"总对冲位置: {hedge_close_result['total_positions']}\n"
                    hedge_message += f"成功平仓: {hedge_close_result['closed_successfully']}\n"
                    hedge_message += f"平仓失败: {hedge_close_result['failed_to_close']}\n"
                    
                    if hedge_close_result['failed_to_close'] > 0:
                        hedge_message += f"⚠️ 部分对冲位置平仓失败，请检查日志\n"
                        hedge_message += f"错误数量: {len(hedge_close_result['errors'])}"
                    else:
                        hedge_message += f"✅ 所有对冲位置已成功平仓"
                    
                    await self.send_notification(hedge_message)
                else:
                    self.logger.log("没有活跃的对冲位置需要平仓", "INFO")
                    
                # 对冲平仓完成，清除标志
                self.hedge_closing_in_progress = False
                self.logger.log("对冲平仓操作完成，清除进行中标志", "INFO")
            else:
                self.logger.log("未启用对冲或无活跃对冲位置，跳过对冲平仓操作", "INFO")
                
        except Exception as e:
            # 即使出错也要清除标志
            self.hedge_closing_in_progress = False
            error_message = f"❌ 对冲平仓操作失败: {e}"
            self.logger.log(f"止损回调中执行对冲平仓时出错: {e}", "ERROR")
            self.logger.log(f"Traceback: {traceback.format_exc()}", "ERROR")
            await self.send_notification(error_message)









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
            # Ensure drawdown monitor has the updated contract_id for stop-loss
            if self.drawdown_monitor is not None:
                try:
                    self.drawdown_monitor.contract_id = self.config.contract_id
                except Exception as e:
                    self.logger.log(f"Failed to update DrawdownMonitor contract_id: {e}", "WARNING")
            # Connect to exchange
            await self.exchange_client.connect()

            # Initialize hedge client if enabled
            if self.hedge_exchange is not None:
                try:
                    # Set the ticker for hedge client
                    self.hedge_exchange.config.ticker = self.config.ticker
                    
                    # Connect hedge client
                    await self.hedge_exchange.connect()
                    
                    # Get contract attributes for hedge client (this will set the correct contract_id and tick_size)
                    hedge_contract_id, hedge_tick_size = await self.hedge_exchange.get_contract_attributes()
                    self.hedge_contract_id = hedge_contract_id  # Save hedge client's contract_id
                    self.logger.log(f"Hedge client connected successfully with contract_id: {hedge_contract_id}, tick_size: {hedge_tick_size}", "INFO")
                except Exception as e:
                    self.logger.log(f"Failed to connect hedge client: {e}", "ERROR")
                    # Don't raise exception here, just disable hedging
                    self.hedge_exchange = None
                    self.config.enable_hedge = False
                    self.logger.log("Hedging disabled due to connection failure", "WARNING")

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
                                        
                                        # 早期成功检测：如果持仓=0且无活跃订单，立即标记成功
                                        try:
                                            current_pos = await self.exchange_client.get_account_positions()
                                            active_orders = await self.exchange_client.get_active_orders(self.config.contract_id)
                                            
                                            if abs(current_pos) <= 0.001 and not active_orders:
                                                self.logger.log(f"Early success detection: Position={current_pos}, Active orders={len(active_orders) if active_orders else 0}", "INFO")
                                                self.logger.log("Stop-loss already completed - position closed and no active orders", "INFO")
                                                stop_loss_success = True
                                                self.drawdown_monitor.stop_loss_executed = True
                                                break
                                        except Exception as early_check_e:
                                            self.logger.log(f"Early success check failed: {early_check_e}", "WARNING")
                                        
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
                                    
                                    except StopLossExecutionError as retry_e:
                                        self.logger.log(f"Stop-loss execution error during retry {retry_count}: {retry_e}", "ERROR")
                                        await asyncio.sleep(1)
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
                                
                                self.logger.log("Stop-loss successfully executed, proceeding with hedge position closure", "INFO")
                            
                            # 只有在启用对冲模式且对冲交易所存在时才执行对冲平仓
                            hedge_close_result = {'total_positions': 0, 'closed_successfully': 0, 'failed_to_close': 0, 'errors': []}
                            if self.config.enable_hedge and self.hedge_exchange:
                                # 检查对冲平仓是否已经在进行中或已完成，避免重复执行
                                if self.hedge_closing_in_progress:
                                    self.logger.log("对冲平仓已在进行中，跳过重复执行", "INFO")
                                    # 等待对冲平仓完成
                                    max_wait_time = 60  # 最多等待60秒
                                    wait_start = time.time()
                                    while self.hedge_closing_in_progress and (time.time() - wait_start) < max_wait_time:
                                        await asyncio.sleep(0.5)
                                    
                                    if self.hedge_closing_in_progress:
                                        self.logger.log("等待对冲平仓完成超时，继续执行", "WARNING")
                                    else:
                                        self.logger.log("对冲平仓已完成，无需重复执行", "INFO")
                                else:
                                    self.logger.log("主订单止损完成，开始执行对冲平仓操作", "INFO")
                                    hedge_close_result = await self._close_all_hedge_positions_on_stop_loss()
                            else:
                                self.logger.log("对冲模式未启用或对冲交易所不存在，跳过对冲平仓操作", "INFO")
                            
                            # 记录对冲平仓结果
                            if hedge_close_result['total_positions'] > 0:
                                self.logger.log(f"对冲平仓结果: 总计{hedge_close_result['total_positions']}个位置, "
                                               f"成功{hedge_close_result['closed_successfully']}个, "
                                               f"失败{hedge_close_result['failed_to_close']}个", "INFO")
                                if hedge_close_result['errors']:
                                    for error in hedge_close_result['errors']:
                                        self.logger.log(f"对冲平仓错误: {error}", "ERROR")
                            else:
                                self.logger.log("没有需要平仓的对冲位置", "INFO")
                            
                            # Severe drawdown - stop trading after executing stop-loss and hedge closure
                            msg = f"\n\n🚨 SEVERE DRAWDOWN ALERT 🚨\n"
                            msg += f"Exchange: {self.config.exchange.upper()}\n"
                            msg += f"Ticker: {self.config.ticker.upper()}\n"
                            msg += f"Session Peak Net Worth: {session_peak}\n"
                            msg += f"Current Net Worth: {current_networth}\n"
                            msg += f"Drawdown: {drawdown_percentage:.2f}%\n"
                            msg += f"Threshold: {self.config.drawdown_severe_threshold}%\n"
                            
                            if self.config.enable_hedge and self.hedge_exchange:
                                msg += "Automatic stop-loss and hedge closure executed, trading stopped due to severe drawdown!\n"
                                msg += "已执行自动止损和对冲平仓，严重回撤，交易已停止！\n"
                            else:
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
                                
                    except (APIRateLimitError, NetworkConnectionError) as api_error:
                        self.logger.log(f"API/Network error during networth update: {api_error}", "WARNING")
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
                    except NetworthValidationError as validation_error:
                        self.logger.log(f"Networth validation error: {validation_error}", "ERROR")
                        # 净值验证失败，跳过本次更新但继续监控
                        continue
                    except Exception as networth_error:
                        self.logger.log(f"Unexpected error during networth update: {networth_error}", "WARNING")
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
                if active_orders is not None:
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

                        # Check if stop loss has been triggered - prevent new orders during hedge closing
                        if self.drawdown_monitor and self.drawdown_monitor.is_stop_loss_triggered():
                            self.logger.log("Skipping new order placement - stop loss triggered, waiting for hedge positions to close", "INFO")
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

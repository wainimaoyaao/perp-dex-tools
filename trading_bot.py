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
    # 回撤控制参数
    max_drawdown: Decimal  # 最大回撤百分比

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
        self.shutdown_requested = False
        self.loop = None
        
        # 回撤控制状态
        self.peak_balance = Decimal('0')  # 账户余额峰值
        self.current_balance = Decimal('0')  # 当前账户余额
        self.drawdown_triggered = False  # 回撤是否已触发
        
        # 止损订单状态跟踪
        self.stop_loss_order_id = None  # 当前止损订单ID
        self.stop_loss_order_time = 0  # 止损订单下单时间
        self.stop_loss_monitoring = False  # 是否正在监控止损订单

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
                    self.logger.log(f"[{order_type}] [{order_id}] {status} "
                                    f"{filled_size} @ {message.get('price')}", "INFO")
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
            self.order_filled_amount = 0.0

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
                else:
                    order_info = await self.exchange_client.get_order_info(order_id)
                    current_order_status = order_info.status
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
                else:
                    # Wait for cancel event or timeout
                    if not self.order_canceled_event.is_set():
                        try:
                            await asyncio.wait_for(self.order_canceled_event.wait(), timeout=5)
                        except asyncio.TimeoutError:
                            order_info = await self.exchange_client.get_order_info(order_id)
                            self.order_filled_amount = order_info.filled_size

            if self.order_filled_amount > 0:
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

    async def _check_loss_percentage(self) -> bool:
        """检查基于未实现盈亏和保证金的亏损百分比。返回True表示需要止损。
        只有在达到最大订单数后才会触发止损检查。"""
        try:
            # 检查是否达到最大订单数，只有达到最大订单数后才进行止损检查
            if len(self.active_close_orders) < self.config.max_orders:
                return False
            
            # 获取未实现盈亏和已使用保证金
            if hasattr(self.exchange_client, 'get_unrealized_pnl_and_margin'):
                unrealized_pnl, used_margin = await self.exchange_client.get_unrealized_pnl_and_margin()
                
                # 计算亏损百分比：亏损 / 已使用保证金 * 100
                if used_margin > 0 and unrealized_pnl < 0:
                    loss_percentage = abs(unrealized_pnl) / used_margin * 100
                    
                    # 检查是否达到亏损阈值
                    if loss_percentage >= self.config.max_drawdown:
                        self.logger.log(f"亏损百分比触发止损！当前订单数: {len(self.active_close_orders)}/{self.config.max_orders}, 未实现盈亏: {unrealized_pnl}, 已使用保证金: {used_margin}, 亏损百分比: {loss_percentage:.2f}%", "WARNING")
                        return True
                    
                    # 记录监控信息（每分钟记录一次）
                    if time.time() - self.last_log_time > 60:
                        self.logger.log(f"亏损监控 - 订单数: {len(self.active_close_orders)}/{self.config.max_orders}, 未实现盈亏: {unrealized_pnl}, 已使用保证金: {used_margin}, 亏损百分比: {loss_percentage:.2f}%", "INFO")
                        self.last_log_time = time.time()
                else:
                    # 如果没有亏损或没有保证金使用，记录状态
                    if time.time() - self.last_log_time > 60:
                        self.logger.log(f"亏损监控 - 订单数: {len(self.active_close_orders)}/{self.config.max_orders}, 未实现盈亏: {unrealized_pnl}, 已使用保证金: {used_margin} (无亏损)", "INFO")
                        self.last_log_time = time.time()
            else:
                # 对于不支持 get_unrealized_pnl_and_margin 的交易所，使用原有逻辑
                self.logger.log("交易所不支持未实现盈亏和保证金监控，跳过亏损检查", "WARNING")
            
            return False
            
        except Exception as e:
            self.logger.log(f"检查亏损百分比时出错: {e}", "ERROR")
            return False

    async def _emergency_stop_loss(self):
        """紧急止损：取消所有挂单并限价平仓所有持仓"""
        try:
            self.logger.log("开始执行紧急止损...", "WARNING")
            
            # 1. 取消所有活跃的止盈单
            cancel_tasks = []
            for order in self.active_close_orders:
                order_id = order.get('id')
                if order_id:
                    cancel_tasks.append(self.exchange_client.cancel_order(order_id))
            
            if cancel_tasks:
                self.logger.log(f"取消 {len(cancel_tasks)} 个挂单...", "INFO")
                await asyncio.gather(*cancel_tasks, return_exceptions=True)
                await asyncio.sleep(2)  # 等待取消完成
            
            # 2. 获取当前持仓并限价平仓
            position_amt = await self.exchange_client.get_account_positions()
            if abs(position_amt) > 0:
                # 确定平仓方向
                close_side = 'sell' if position_amt > 0 else 'buy'
                close_quantity = abs(position_amt)
                
                # 获取当前市价
                current_price = await self.exchange_client.get_current_price()
                
                # 计算限价平仓价格（稍微有利的价格确保快速成交）
                if close_side == 'sell':
                    # 卖出时，价格稍微低一点确保快速成交
                    close_price = current_price * Decimal('0.999')  # 降低0.1%
                else:
                    # 买入时，价格稍微高一点确保快速成交
                    close_price = current_price * Decimal('1.001')  # 提高0.1%
                
                # 调整价格精度
                close_price = self.exchange_client.round_price(close_price)
                
                self.logger.log(f"限价平仓: {close_side} {close_quantity} @ {close_price}", "WARNING")
                
                # 限价平仓
                close_result = await self.exchange_client.place_limit_order(
                    self.config.contract_id,
                    close_quantity,
                    close_price,
                    close_side
                )
                
                if close_result.success:
                    # 记录止损订单ID和状态
                    self.stop_loss_order_id = close_result.order_id
                    self.stop_loss_order_time = time.time()
                    self.stop_loss_monitoring = True
                    self.logger.log(f"限价止损订单已下达，订单ID: {self.stop_loss_order_id}", "INFO")
                else:
                    self.logger.log(f"限价止损订单下达失败: {close_result.error_message}", "ERROR")
            else:
                self.logger.log("无持仓需要平仓", "INFO")
            
            # 3. 设置触发状态
            self.drawdown_triggered = True
            
            # 4. 获取亏损信息用于通知
            loss_info = ""
            try:
                if hasattr(self.exchange_client, 'get_unrealized_pnl_and_margin'):
                    unrealized_pnl, used_margin = await self.exchange_client.get_unrealized_pnl_and_margin()
                    if used_margin > 0 and unrealized_pnl < 0:
                        loss_percentage = abs(unrealized_pnl) / used_margin * 100
                        loss_info = f"未实现盈亏: {unrealized_pnl}\n已使用保证金: {used_margin}\n亏损百分比: {loss_percentage:.2f}%\n"
            except Exception as e:
                self.logger.log(f"获取亏损信息失败: {e}", "ERROR")
            
            # 5. 发送通知
            message = f"\n🚨 亏损止损触发 🚨\n"
            message += f"交易所: {self.config.exchange.upper()}\n"
            message += f"交易对: {self.config.ticker.upper()}\n"
            message += loss_info
            message += f"止损阈值: {self.config.max_drawdown}%\n"
            message += "所有挂单已取消，已下达限价止损订单\n"
            message += "程序将在平仓完成后自动停止"
            
            await self.send_notification(message)
            
        except Exception as e:
            self.logger.log(f"紧急止损执行失败: {e}", "ERROR")
            self.logger.log(f"Traceback: {traceback.format_exc()}", "ERROR")

    async def _monitor_stop_loss_order(self):
        """监控止损订单状态，如果3秒内未成交则重新挂单"""
        if not self.stop_loss_monitoring or not self.stop_loss_order_id:
            return
        
        try:
            # 检查订单是否已经超过3秒
            elapsed_time = time.time() - self.stop_loss_order_time
            if elapsed_time < 3:
                return
            
            # 检查订单状态
            order_status = await self.exchange_client.get_order_status(self.stop_loss_order_id)
            
            if order_status and order_status.get('status') == 'filled':
                # 订单已成交，检查持仓并停止程序
                self.logger.log(f"止损订单已成交: {self.stop_loss_order_id}", "INFO")
                self.stop_loss_monitoring = False
                self.stop_loss_order_id = None
                self.stop_loss_order_time = 0
                
                # 等待2秒确保订单状态更新
                await asyncio.sleep(2)
                
                # 检查当前持仓
                position_amt = await self.exchange_client.get_account_positions()
                
                # 发送通知并停止程序
                message = f"\n✅ 止损平仓完成 ✅\n"
                message += f"交易所: {self.config.exchange.upper()}\n"
                message += f"交易对: {self.config.ticker.upper()}\n"
                message += f"当前持仓: {position_amt}\n"
                if abs(position_amt) == 0:
                    message += "✅ 已完全平仓，程序将自动停止"
                    self.logger.log("止损平仓完成，已完全平仓，程序将自动停止", "INFO")
                else:
                    message += f"⚠️ 仍有持仓 {position_amt}，程序将自动停止"
                    self.logger.log(f"止损平仓完成，仍有持仓 {position_amt}，程序将自动停止", "WARNING")
                
                await self.send_notification(message)
                await self.graceful_shutdown("止损平仓完成")
                return
            
            # 订单未成交，取消并重新挂单
            self.logger.log(f"止损订单 {self.stop_loss_order_id} 超过3秒未成交，重新挂单", "WARNING")
            
            # 取消当前订单
            try:
                await self.exchange_client.cancel_order(self.stop_loss_order_id)
                await asyncio.sleep(1)  # 等待取消完成
            except Exception as e:
                self.logger.log(f"取消止损订单失败: {e}", "ERROR")
            
            # 获取当前持仓并重新挂限价单
            position_amt = await self.exchange_client.get_account_positions()
            if abs(position_amt) > 0:
                # 确定平仓方向
                close_side = 'sell' if position_amt > 0 else 'buy'
                close_quantity = abs(position_amt)
                
                # 获取当前市价
                current_price = await self.exchange_client.get_current_price()
                
                # 计算限价平仓价格（稍微有利的价格确保快速成交）
                if close_side == 'sell':
                    # 卖出时，价格稍微低一点确保快速成交
                    close_price = current_price * Decimal('0.999')  # 降低0.1%
                else:
                    # 买入时，价格稍微高一点确保快速成交
                    close_price = current_price * Decimal('1.001')  # 提高0.1%
                
                # 调整价格精度
                close_price = self.exchange_client.round_price(close_price)
                
                self.logger.log(f"重新挂止损单: {close_side} {close_quantity} @ {close_price}", "WARNING")
                
                # 重新下限价单
                close_result = await self.exchange_client.place_limit_order(
                    self.config.contract_id,
                    close_quantity,
                    close_price,
                    close_side
                )
                
                if close_result.success:
                    # 更新止损订单信息
                    self.stop_loss_order_id = close_result.order_id
                    self.stop_loss_order_time = time.time()
                    self.logger.log(f"止损订单重新下达成功，订单ID: {self.stop_loss_order_id}", "INFO")
                else:
                    self.logger.log(f"重新下达止损订单失败: {close_result.error_message}", "ERROR")
                    self.stop_loss_monitoring = False
            else:
                # 无持仓，发送通知并停止程序
                self.logger.log("无持仓需要平仓，程序将自动停止", "INFO")
                self.stop_loss_monitoring = False
                self.stop_loss_order_id = None
                self.stop_loss_order_time = 0
                
                # 发送通知并停止程序
                message = f"\n✅ 止损检查完成 ✅\n"
                message += f"交易所: {self.config.exchange.upper()}\n"
                message += f"交易对: {self.config.ticker.upper()}\n"
                message += "当前无持仓需要平仓\n"
                message += "✅ 程序将自动停止"
                
                await self.send_notification(message)
                await self.graceful_shutdown("无持仓需要平仓")
                
        except Exception as e:
            self.logger.log(f"监控止损订单时出错: {e}", "ERROR")
            self.logger.log(f"Traceback: {traceback.format_exc()}", "ERROR")



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
            self.logger.log(f"Max Drawdown: {self.config.max_drawdown}%", "INFO")
            self.logger.log("=============================", "INFO")

            # Capture the running event loop for thread-safe callbacks
            self.loop = asyncio.get_running_loop()
            # Connect to exchange
            await self.exchange_client.connect()

            # wait for connection to establish
            await asyncio.sleep(5)

            # Main trading loop
            while not self.shutdown_requested:
                # 监控止损订单状态（如果有的话）
                await self._monitor_stop_loss_order()
                
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

                # 2. 检查回撤控制（在获取订单信息后）
                drawdown_triggered = await self._check_loss_percentage()
                if drawdown_triggered:
                    await self._emergency_stop_loss()
                    continue  # 止损后继续循环，等待平仓完成

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

"""
回撤监控模块 - 实现会话重置策略的回撤止损功能
"""

import time
import asyncio
from decimal import Decimal
from typing import Dict, Any, Optional, Callable
from enum import Enum
from dataclasses import dataclass
from helpers.logger import TradingLogger


# ==================== 自定义异常类型 ====================

class DrawdownMonitorError(Exception):
    """回撤监控基础异常类"""
    def __init__(self, message: str, context: Dict[str, Any] = None):
        super().__init__(message)
        self.context = context or {}
        self.timestamp = time.time()


class NetworthValidationError(DrawdownMonitorError):
    """净值验证异常"""
    def __init__(self, message: str, networth_value: Any = None, context: Dict[str, Any] = None):
        super().__init__(message, context)
        self.networth_value = networth_value


class StopLossExecutionError(DrawdownMonitorError):
    """止损执行异常"""
    def __init__(self, message: str, execution_step: str = None, context: Dict[str, Any] = None):
        super().__init__(message, context)
        self.execution_step = execution_step


class OrderMonitoringError(DrawdownMonitorError):
    """订单监控异常"""
    def __init__(self, message: str, order_id: str = None, order_status: str = None, context: Dict[str, Any] = None):
        super().__init__(message, context)
        self.order_id = order_id
        self.order_status = order_status


class APIRateLimitError(DrawdownMonitorError):
    """API限流异常"""
    def __init__(self, message: str, retry_after: int = None, context: Dict[str, Any] = None):
        super().__init__(message, context)
        self.retry_after = retry_after


class NetworkConnectionError(DrawdownMonitorError):
    """网络连接异常"""
    def __init__(self, message: str, endpoint: str = None, context: Dict[str, Any] = None):
        super().__init__(message, context)
        self.endpoint = endpoint


class DataIntegrityError(DrawdownMonitorError):
    """数据完整性异常"""
    def __init__(self, message: str, data_type: str = None, expected_format: str = None, context: Dict[str, Any] = None):
        super().__init__(message, context)
        self.data_type = data_type
        self.expected_format = expected_format


class ConfigurationError(DrawdownMonitorError):
    """配置错误异常"""
    def __init__(self, message: str, config_key: str = None, context: Dict[str, Any] = None):
        super().__init__(message, context)
        self.config_key = config_key


# ==================== 枚举和数据类 ====================

class DrawdownLevel(Enum):
    """回撤警告级别"""
    NORMAL = "normal"
    LIGHT_WARNING = "light_warning"
    MEDIUM_WARNING = "medium_warning"
    SEVERE_STOP_LOSS = "severe_stop_loss"


@dataclass
class DrawdownConfig:
    """回撤监控配置"""
    light_warning_threshold: Decimal = Decimal("0.05")  # 5% 轻度警告
    medium_warning_threshold: Decimal = Decimal("0.08")  # 8% 中度警告
    severe_stop_loss_threshold: Decimal = Decimal("0.12")  # 12% 严重止损
    update_frequency_seconds: int = 15  # 净值更新频率（秒）
    smoothing_window_size: int = 3  # 平滑窗口大小


class DrawdownMonitor:
    """回撤监控器 - 会话重置策略"""
    
    def __init__(self, config: DrawdownConfig, logger: TradingLogger, exchange_client=None, contract_id: str = None):
        """
        初始化回撤监控器
        
        Args:
            config: 回撤监控配置
            logger: 日志记录器
            exchange_client: 交易所客户端
            contract_id: 合约ID
        """
        self.config = config
        self.logger = logger
        self.exchange_client = exchange_client
        self.contract_id = contract_id
        
        # 会话状态
        self.session_peak_networth: Optional[Decimal] = None
        self.current_networth: Optional[Decimal] = None
        self.initial_networth: Optional[Decimal] = None
        
        # 监控状态
        self.current_level = DrawdownLevel.NORMAL
        self.last_update_time = 0
        self.is_monitoring = False
        self.stop_loss_triggered = False
        self.stop_loss_executed = False
        
        # 缓存相关状态
        self.last_successful_networth: Optional[Decimal] = None
        self.last_successful_update_time: float = 0
        self.consecutive_failures: int = 0
        self.max_consecutive_failures: int = 5  # 最大连续失败次数
        self.cache_timeout_minutes: int = 30  # 缓存超时时间（分钟）
        self.use_cached_value: bool = False  # 是否正在使用缓存值
        self.strict_threshold_multiplier: Decimal = Decimal("0.8")  # 缓存模式下的严格阈值倍数
        
        # 平滑处理
        self.networth_history = []
        
        # 回调函数
        self.warning_callbacks: Dict[DrawdownLevel, Callable] = {}
        self.stop_loss_callback: Optional[Callable] = None
        
        self.logger.log("DrawdownMonitor initialized with session reset strategy", "INFO")
    
    def set_warning_callback(self, level: DrawdownLevel, callback: Callable):
        """设置警告级别回调函数"""
        self.warning_callbacks[level] = callback
        self.logger.log(f"Warning callback set for level: {level.value}", "DEBUG")
    
    def set_stop_loss_callback(self, callback: Callable):
        """设置止损回调函数"""
        self.stop_loss_callback = callback
        self.logger.log("Stop loss callback set", "DEBUG")
    
    def start_session(self, initial_networth: Decimal):
        """
        开始新的交易会话
        
        Args:
            initial_networth: 初始净值
        """
        # 如果初始净值为None或无效，使用0作为默认值
        if initial_networth is None:
            initial_networth = Decimal("0")
            self.logger.log("Warning: Initial net worth is None, using 0 as default", "WARNING")
        
        self.initial_networth = initial_networth
        self.session_peak_networth = initial_networth
        self.current_networth = initial_networth
        self.current_level = DrawdownLevel.NORMAL
        self.last_update_time = time.time()
        self.is_monitoring = True
        self.stop_loss_triggered = False
        self.networth_history = [initial_networth]
        
        # 初始化缓存状态
        self.last_successful_networth = initial_networth
        self.last_successful_update_time = time.time()
        self.consecutive_failures = 0
        self.use_cached_value = False
        
        self.logger.log(f"Trading session started with initial net worth: ${initial_networth}", "INFO")
        self.logger.log(f"Drawdown thresholds - Light: {self.config.light_warning_threshold*100}%, "
                       f"Medium: {self.config.medium_warning_threshold*100}%, "
                       f"Severe: {self.config.severe_stop_loss_threshold*100}%", "INFO")
    
    def update_networth_with_fallback(self, current_networth: Optional[Decimal] = None) -> bool:
        """
        更新净值，支持失败时使用缓存值
        
        Args:
            current_networth: 当前净值，如果为None表示获取失败
            
        Returns:
            bool: 是否应该继续交易（False表示触发止损）
        """
        if current_networth is not None:
            # 净值获取成功，使用正常逻辑
            return self._update_networth_success(current_networth)
        else:
            # 净值获取失败，使用缓存逻辑
            return self._update_networth_failure()
    
    def _update_networth_success(self, current_networth: Decimal) -> bool:
        """处理净值获取成功的情况"""
        # 重置失败计数
        self.consecutive_failures = 0
        self.use_cached_value = False
        
        # 更新缓存
        self.last_successful_networth = current_networth
        self.last_successful_update_time = time.time()
        
        # 使用原有的更新逻辑
        return self.update_networth(current_networth)
    
    def _update_networth_failure(self) -> bool:
        """处理净值获取失败的情况"""
        self.consecutive_failures += 1
        current_time = time.time()
        
        self.logger.log(f"Net worth fetch failed (attempt {self.consecutive_failures}/{self.max_consecutive_failures})", "WARNING")
        
        # 检查是否超过最大失败次数
        if self.consecutive_failures >= self.max_consecutive_failures:
            self.logger.log(f"Exceeded maximum consecutive failures ({self.max_consecutive_failures}), using cached value", "ERROR")
        
        # 检查缓存是否过期
        cache_age_minutes = (current_time - self.last_successful_update_time) / 60
        if cache_age_minutes > self.cache_timeout_minutes:
            self.logger.log(f"Cached net worth is too old ({cache_age_minutes:.1f} minutes > {self.cache_timeout_minutes} minutes)", "ERROR")
            # 即使缓存过期，也继续使用，但记录警告
        
        # 使用缓存值进行监控
        if self.last_successful_networth is not None:
            self.use_cached_value = True
            self.logger.log(f"Using cached net worth: ${self.last_successful_networth} (age: {cache_age_minutes:.1f} minutes)", "INFO")
            
            # 使用缓存值更新监控状态
            return self.update_networth(self.last_successful_networth)
        else:
            self.logger.log("No cached net worth available, cannot perform drawdown monitoring", "ERROR")
            # 没有缓存值时，保持当前状态不变，继续交易但记录错误
            return True

    def update_networth(self, current_networth: Decimal) -> bool:
        """
        更新当前净值并检查回撤
        
        Args:
            current_networth: 当前净值
            
        Returns:
            bool: 是否应该继续交易（False表示触发止损）
        """
        method_start_time = time.time()
        
        try:
            # 记录方法调用详情
            self.logger.log(f"update_networth called with value: ${current_networth}", "DEBUG")
            
            # 状态检查
            if not self.is_monitoring:
                self.logger.log("Drawdown monitoring is not active, skipping update", "DEBUG")
                return False
                
            if self.stop_loss_triggered:
                self.logger.log("Stop loss already triggered, skipping update", "DEBUG")
                return False
            
            # 数据验证
            try:
                validation_result = self._validate_networth_input(current_networth)
                if not validation_result['valid']:
                    self.logger.log(f"Invalid networth input: {validation_result['reason']}", "ERROR")
                    return True  # 跳过此次更新但继续监控
            except NetworthValidationError as e:
                self.logger.log(f"Networth validation failed: {e}. Context: {e.context}", "ERROR")
                self.logger.log(f"Invalid networth value: {e.networth_value}", "ERROR")
                return True  # 跳过此次更新但继续监控
            
            current_time = time.time()
            
            # 频率检查
            if self.config.update_frequency_seconds > 0:
                time_since_last = current_time - self.last_update_time
                if time_since_last < self.config.update_frequency_seconds:
                    self.logger.log(f"Update frequency check: {time_since_last:.1f}s < {self.config.update_frequency_seconds}s, skipping", "DEBUG")
                    return True
            
            # 保存上一次的净值用于比较
            previous_networth = self.current_networth
            
            # 更新净值历史（用于平滑处理）
            try:
                self._update_networth_history(current_networth)
            except Exception as e:
                self.logger.log(f"Error updating networth history: {e}", "ERROR")
                # 使用当前值作为备用方案
                self.networth_history = [current_networth]
            
            # 计算平滑后的净值
            try:
                smoothed_networth = self._calculate_smoothed_networth()
                self.current_networth = smoothed_networth
                self.logger.log(f"Smoothing calculation: raw=${current_networth}, smoothed=${smoothed_networth}, history_size={len(self.networth_history)}", "DEBUG")
            except Exception as e:
                self.logger.log(f"Error calculating smoothed networth: {e}, using raw value", "ERROR")
                self.current_networth = current_networth
                smoothed_networth = current_networth
            
            # 记录净值变化
            try:
                self._log_networth_change(previous_networth, current_networth)
            except Exception as e:
                self.logger.log(f"Error logging networth change: {e}", "ERROR")
            
            # 更新会话峰值
            try:
                peak_updated = self._update_session_peak(current_networth)
                if peak_updated:
                    self.logger.log(f"Session peak updated to ${self.session_peak_networth}", "DEBUG")
            except Exception as e:
                self.logger.log(f"Error updating session peak: {e}", "ERROR")
            
            # 计算回撤率
            try:
                drawdown_rate = self._calculate_drawdown_rate()
                raw_drawdown_rate = self._calculate_raw_drawdown_rate(current_networth)
                self.logger.log(f"Drawdown calculation: smoothed={drawdown_rate*100:.4f}%, raw={raw_drawdown_rate*100:.4f}%", "DEBUG")
            except Exception as e:
                self.logger.log(f"Error calculating drawdown rates: {e}", "ERROR")
                drawdown_rate = Decimal("0")
                raw_drawdown_rate = Decimal("0")
            
            # 检查回撤级别
            try:
                new_level = self._determine_drawdown_level(drawdown_rate, raw_drawdown_rate)
                
                # 处理级别变化
                if new_level != self.current_level:
                    self.logger.log(f"Drawdown level change detected: {self.current_level.value} -> {new_level.value}", "DEBUG")
                    self._handle_level_change(self.current_level, new_level, drawdown_rate)
                    self.current_level = new_level
                else:
                    self.logger.log(f"Drawdown level unchanged: {new_level.value}", "DEBUG")
                    
            except Exception as e:
                self.logger.log(f"Error in drawdown level processing: {e}", "ERROR")
                # 保持当前级别不变
            
            # 更新时间戳
            self.last_update_time = current_time
            
            # 记录详细状态
            self._log_detailed_status(current_networth, smoothed_networth, drawdown_rate, new_level)
            
            # 性能监控
            execution_time = time.time() - method_start_time
            if execution_time > 0.1:  # 如果执行时间超过100ms则记录
                self.logger.log(f"update_networth execution time: {execution_time:.3f}s", "WARNING")
            else:
                self.logger.log(f"update_networth completed in {execution_time:.3f}s", "DEBUG")
            
            # 返回结果
            result = not self.stop_loss_triggered
            self.logger.log(f"update_networth returning: {result} (stop_loss_triggered={self.stop_loss_triggered})", "DEBUG")
            return result
            
        except Exception as e:
            execution_time = time.time() - method_start_time
            self.logger.log(f"Critical error in update_networth after {execution_time:.3f}s: {e}", "ERROR")
            import traceback
            self.logger.log(f"Traceback: {traceback.format_exc()}", "ERROR")
            # 在发生严重错误时，保守地返回True以继续监控
            return True
    
    def _calculate_drawdown_rate(self) -> Decimal:
        """计算当前回撤率"""
        if not self.session_peak_networth or self.session_peak_networth <= 0:
            return Decimal("0")
        
        # 确保current_networth不为None
        if self.current_networth is None:
            return Decimal("0")
        
        drawdown = self.session_peak_networth - self.current_networth
        drawdown_rate = drawdown / self.session_peak_networth
        
        return max(Decimal("0"), drawdown_rate)  # 确保回撤率不为负
    
    def _calculate_raw_drawdown_rate(self, raw_networth: Decimal) -> Decimal:
        """计算基于原始净值的回撤率（用于严重止损检测）"""
        if not self.session_peak_networth or self.session_peak_networth <= 0:
            return Decimal("0")
        
        # 确保raw_networth不为None
        if raw_networth is None:
            return Decimal("0")
        
        drawdown = self.session_peak_networth - raw_networth
        drawdown_rate = drawdown / self.session_peak_networth
        
        return max(Decimal("0"), drawdown_rate)  # 确保回撤率不为负
    
    def _determine_drawdown_level(self, drawdown_rate: Decimal, raw_drawdown_rate: Decimal = None) -> DrawdownLevel:
        """根据回撤率确定警告级别"""
        # 对于严重止损，使用原始回撤率（如果提供）以获得更敏感的检测
        severe_check_rate = raw_drawdown_rate if raw_drawdown_rate is not None else drawdown_rate
        
        # 在缓存模式下使用更严格的阈值
        if self.use_cached_value:
            strict_severe_threshold = self.config.severe_stop_loss_threshold * self.strict_threshold_multiplier
            strict_medium_threshold = self.config.medium_warning_threshold * self.strict_threshold_multiplier
            strict_light_threshold = self.config.light_warning_threshold * self.strict_threshold_multiplier
            
            self.logger.log(f"Using strict thresholds (cached mode): severe={strict_severe_threshold*100:.2f}%, "
                           f"medium={strict_medium_threshold*100:.2f}%, light={strict_light_threshold*100:.2f}%", "DEBUG")
            
            if severe_check_rate >= strict_severe_threshold:
                return DrawdownLevel.SEVERE_STOP_LOSS
            elif drawdown_rate >= strict_medium_threshold:
                return DrawdownLevel.MEDIUM_WARNING
            elif drawdown_rate >= strict_light_threshold:
                return DrawdownLevel.LIGHT_WARNING
            else:
                return DrawdownLevel.NORMAL
        else:
            # 正常模式下使用标准阈值
            if severe_check_rate >= self.config.severe_stop_loss_threshold:
                return DrawdownLevel.SEVERE_STOP_LOSS
            elif drawdown_rate >= self.config.medium_warning_threshold:
                return DrawdownLevel.MEDIUM_WARNING
            elif drawdown_rate >= self.config.light_warning_threshold:
                return DrawdownLevel.LIGHT_WARNING
            else:
                return DrawdownLevel.NORMAL
    
    def _handle_level_change(self, old_level: DrawdownLevel, new_level: DrawdownLevel, drawdown_rate: Decimal):
        """处理回撤级别变化"""
        self.logger.log(f"Drawdown level changed: {old_level.value} -> {new_level.value} "
                       f"(Drawdown: {drawdown_rate*100:.2f}%)", "WARN")
        
        # 触发相应的回调函数
        if new_level in self.warning_callbacks:
            try:
                self.warning_callbacks[new_level](drawdown_rate, self.current_networth, self.session_peak_networth)
            except Exception as e:
                self.logger.log(f"Error in warning callback for {new_level.value}: {e}", "ERROR")
        
        # 处理严重止损 - 标记需要触发止损，但不在这里执行异步操作
        if new_level == DrawdownLevel.SEVERE_STOP_LOSS:
            self._mark_stop_loss_needed(drawdown_rate)
    
    def _mark_stop_loss_needed(self, drawdown_rate: Decimal):
        """标记需要触发止损（同步方法）"""
        self.stop_loss_triggered = True
        self.is_monitoring = False
        self._pending_stop_loss_drawdown = drawdown_rate
        
        loss_amount = self.session_peak_networth - self.current_networth
        
        self.logger.log("=" * 60, "ERROR")
        self.logger.log("SEVERE DRAWDOWN STOP LOSS TRIGGERED!", "ERROR")
        self.logger.log(f"Session Peak Net Worth: ${self.session_peak_networth}", "ERROR")
        self.logger.log(f"Current Net Worth: ${self.current_networth}", "ERROR")
        self.logger.log(f"Drawdown Rate: {drawdown_rate*100:.2f}%", "ERROR")
        self.logger.log(f"Loss Amount: ${loss_amount}", "ERROR")
        self.logger.log("Trading will be stopped immediately!", "ERROR")
        self.logger.log("Automatic stop-loss will be executed...", "ERROR")
        self.logger.log("=" * 60, "ERROR")
    
    async def execute_pending_stop_loss(self):
        """执行待处理的止损（异步方法）"""
        if not hasattr(self, '_pending_stop_loss_drawdown') or not self.stop_loss_triggered:
            return
        
        drawdown_rate = self._pending_stop_loss_drawdown
        
        # 执行自动止损（如果配置了交易所客户端和合约ID）
        if self.exchange_client and self.contract_id:
            self.logger.log("Executing automatic stop-loss...", "INFO")
            try:
                stop_loss_result = await self._execute_auto_stop_loss(
                    self.exchange_client, 
                    self.contract_id
                )
                # _execute_auto_stop_loss 成功时返回True，失败时返回None
                if stop_loss_result is True:
                    self.logger.log("Automatic stop-loss executed successfully", "INFO")
                else:
                    self.logger.log("Automatic stop-loss execution failed", "ERROR")
            except Exception as e:
                self.logger.log(f"Error during automatic stop-loss: {e}", "ERROR")
        else:
            self.logger.log("Automatic stop-loss not configured (missing exchange_client or contract_id)", "WARNING")
        
        # 触发止损回调
        if self.stop_loss_callback:
            try:
                loss_amount = self.session_peak_networth - self.current_networth
                self.stop_loss_callback(drawdown_rate, self.current_networth, self.session_peak_networth, loss_amount)
            except Exception as e:
                self.logger.log(f"Error in stop loss callback: {e}", "ERROR")
        
        # 清除待处理标记
        delattr(self, '_pending_stop_loss_drawdown')
    

    
    async def _execute_auto_stop_loss(self, exchange_client, contract_id: str, retry_interval: int = 3):
        """
        执行智能止损，使用bid1/ask1价格并包含重试机制
        新逻辑：取消所有挂单 → 读取持仓 → 挂买1/卖1 → 监控5秒 → 未成交则重试
        持续循环直至所有止损挂单成交完成，并确认无未成交订单
        
        Args:
            exchange_client: 交易所客户端
            contract_id: 合约ID
            retry_interval: 重试间隔秒数（默认3秒）
        """
        execution_start_time = time.time()
        attempt = 0
        total_orders_placed = 0
        total_orders_filled = 0
        
        try:
            self.logger.log("Starting intelligent stop-loss execution with 5-second monitoring", "INFO")
            self.logger.log(f"Execution parameters: contract_id={contract_id}, retry_interval={retry_interval}s", "DEBUG")
            
            # 智能止损重试循环 - 持续重试直至完全成交
            while True:
                attempt += 1
                attempt_start_time = time.time()
                
                self.logger.log(f"Stop-loss attempt {attempt}: Starting execution cycle", "INFO")
                
                try:
                    # 步骤1: 取消所有挂单
                    cancel_start_time = time.time()
                    try:
                        cancel_result = await self._cancel_all_pending_orders(exchange_client, contract_id)
                        cancel_duration = time.time() - cancel_start_time
                        self.logger.log(f"Cancel orders completed in {cancel_duration:.3f}s", "DEBUG")
                    except Exception as e:
                        cancel_duration = time.time() - cancel_start_time
                        # 包装为自定义异常但不中断执行
                        cancel_error = StopLossExecutionError(
                            f"Failed to cancel orders: {e}",
                            execution_step="cancel_orders",
                            context={
                                'attempt': attempt,
                                'duration': cancel_duration,
                                'contract_id': contract_id
                            }
                        )
                        self.logger.log(f"Error canceling orders after {cancel_duration:.3f}s: {cancel_error}", "ERROR")
                        import traceback
                        self.logger.log(f"Cancel orders traceback: {traceback.format_exc()}", "DEBUG")
                        # 继续执行，不因取消订单失败而中断
                    
                    # 步骤2: 读取当前持仓信息（带重试机制）
                    position_start_time = time.time()
                    try:
                        position_amt = await self._get_position_with_retry(exchange_client, max_retries=3)
                        position_duration = time.time() - position_start_time
                        
                        if position_amt is None:
                            self.logger.log(f"Failed to read position after {position_duration:.3f}s and 3 retries, will retry entire cycle", "WARNING")
                            await asyncio.sleep(retry_interval)
                            continue
                        
                        self.logger.log(f"Position read in {position_duration:.3f}s: {position_amt}", "DEBUG")
                        
                        if abs(position_amt) < 0.001:  # 考虑浮点精度，基本无持仓
                            execution_duration = time.time() - execution_start_time
                            self.logger.log(f"No significant position remaining, stop-loss execution completed in {execution_duration:.3f}s", "INFO")
                            self.logger.log(f"Execution summary: {attempt} attempts, {total_orders_placed} orders placed, {total_orders_filled} orders filled", "INFO")
                            break
                            
                    except Exception as e:
                        position_duration = time.time() - position_start_time
                        # 包装为自定义异常
                        position_error = StopLossExecutionError(
                            f"Failed to read position: {e}",
                            execution_step="read_position",
                            context={
                                'attempt': attempt,
                                'duration': position_duration,
                                'contract_id': contract_id,
                                'max_retries': 3
                            }
                        )
                        self.logger.log(f"Error reading position after {position_duration:.3f}s: {position_error}", "ERROR")
                        import traceback
                        self.logger.log(f"Position read traceback: {traceback.format_exc()}", "DEBUG")
                        await asyncio.sleep(retry_interval)
                        continue
                    
                    # 确定持仓方向和大小
                    position_side = "long" if position_amt > 0 else "short"
                    position_size = abs(position_amt)
                    
                    self.logger.log(f"Current position: {position_side} {position_size}", "INFO")
                    
                    # 步骤3: 获取最新的bid1/ask1价格并下单
                    price_start_time = time.time()
                    try:
                        best_bid, best_ask = await exchange_client.fetch_bbo_prices(contract_id)
                        price_duration = time.time() - price_start_time
                        
                        self.logger.log(f"BBO prices fetched in {price_duration:.3f}s: bid={best_bid}, ask={best_ask}", "DEBUG")
                        
                        if best_bid <= 0 or best_ask <= 0 or best_bid >= best_ask:
                            self.logger.log(f"Invalid bid/ask prices: bid={best_bid}, ask={best_ask}", "WARNING")
                            await asyncio.sleep(retry_interval)
                            continue
                            
                    except Exception as e:
                        price_duration = time.time() - price_start_time
                        self.logger.log(f"Error fetching BBO prices after {price_duration:.3f}s: {e}", "ERROR")
                        import traceback
                        self.logger.log(f"BBO price fetch traceback: {traceback.format_exc()}", "DEBUG")
                        await asyncio.sleep(retry_interval)
                        continue
                    
                    # 使用bid1/ask1价格确保立即成交
                    if position_side == "long":
                        # 多头持仓：挂bid1价格的限价卖单，确保能立即成交
                        stop_price = best_bid
                        order_side = "sell"
                    else:
                        # 空头持仓：挂ask1价格的限价买单，确保能立即成交
                        stop_price = best_ask
                        order_side = "buy"
                    
                    self.logger.log(f"Placing stop-loss order: {order_side} {position_size} at {stop_price} (bid: {best_bid}, ask: {best_ask})", "INFO")
                    
                    # 下止损订单
                    order_start_time = time.time()
                    try:
                        result = await exchange_client.place_close_order(
                            contract_id=contract_id,
                            quantity=position_size,
                            price=stop_price,
                            side=order_side
                        )
                        order_duration = time.time() - order_start_time
                        total_orders_placed += 1
                        
                        if not result.success:
                            self.logger.log(f"Failed to place stop-loss order after {order_duration:.3f}s: {result.error_message}", "WARNING")
                            self.logger.log(f"Order placement failure details: side={order_side}, size={position_size}, price={stop_price}", "DEBUG")
                            await asyncio.sleep(retry_interval)
                            continue
                        
                        order_id = result.order_id
                        self.logger.log(f"Stop-loss order placed in {order_duration:.3f}s: {order_id}", "INFO")
                        
                        # 如果订单立即成交，检查是否还有持仓
                        if result.status == 'FILLED':
                            total_orders_filled += 1
                            self.logger.log(f"Stop-loss order filled immediately: {order_id}", "INFO")
                            continue  # 继续循环检查是否还有持仓
                            
                    except Exception as e:
                        order_duration = time.time() - order_start_time
                        # 包装为自定义异常
                        order_error = StopLossExecutionError(
                            f"Failed to place stop-loss order: {e}",
                            execution_step="place_order",
                            context={
                                'attempt': attempt,
                                'duration': order_duration,
                                'contract_id': contract_id,
                                'position_side': position_side,
                                'position_size': position_size,
                                'best_bid': locals().get('best_bid'),
                                'best_ask': locals().get('best_ask')
                            }
                        )
                        self.logger.log(f"Error placing stop-loss order after {order_duration:.3f}s: {order_error}", "ERROR")
                        import traceback
                        self.logger.log(f"Order placement traceback: {traceback.format_exc()}", "DEBUG")
                        await asyncio.sleep(retry_interval)
                        continue
                    
                    # 步骤4: 监控订单状态5秒
                    monitor_start_time = time.time()
                    try:
                        filled = await self._monitor_stop_loss_order_with_timeout(exchange_client, order_id, timeout=5)
                        monitor_duration = time.time() - monitor_start_time
                        
                        if filled:
                            total_orders_filled += 1
                            self.logger.log(f"Stop-loss order filled within 5 seconds after {monitor_duration:.3f}s monitoring: {order_id}", "INFO")
                            continue  # 继续循环检查是否还有持仓
                        else:
                            self.logger.log(f"Stop-loss order not filled within 5 seconds after {monitor_duration:.3f}s monitoring, will retry", "WARNING")
                            # 订单未成交，将在下次循环开始时取消所有挂单
                            
                    except Exception as e:
                        monitor_duration = time.time() - monitor_start_time
                        # 包装为自定义异常
                        monitor_error = OrderMonitoringError(
                            f"Failed to monitor order: {e}",
                            order_id=order_id,
                            context={
                                'attempt': attempt,
                                'duration': monitor_duration,
                                'contract_id': contract_id,
                                'timeout': 5
                            }
                        )
                        self.logger.log(f"Error monitoring order {order_id} after {monitor_duration:.3f}s: {monitor_error}", "ERROR")
                        import traceback
                        self.logger.log(f"Order monitoring traceback: {traceback.format_exc()}", "DEBUG")
                        # 继续下一次循环
                        
                except Exception as e:
                    attempt_duration = time.time() - attempt_start_time
                    self.logger.log(f"Error in stop-loss attempt {attempt} after {attempt_duration:.3f}s: {e}", "ERROR")
                    import traceback
                    self.logger.log(f"Attempt {attempt} traceback: {traceback.format_exc()}", "DEBUG")
                    await asyncio.sleep(retry_interval)
                
                # 记录每次尝试的性能统计
                attempt_duration = time.time() - attempt_start_time
                if attempt_duration > 10:  # 如果单次尝试超过10秒则记录警告
                    self.logger.log(f"Attempt {attempt} took {attempt_duration:.3f}s (longer than expected)", "WARNING")
                else:
                    self.logger.log(f"Attempt {attempt} completed in {attempt_duration:.3f}s", "DEBUG")
            
            # 步骤5: 最终完整性检查 - 确认无未成交订单
            integrity_start_time = time.time()
            try:
                await self._final_integrity_check(exchange_client, contract_id)
                integrity_duration = time.time() - integrity_start_time
                self.logger.log(f"Final integrity check completed in {integrity_duration:.3f}s", "DEBUG")
            except Exception as e:
                integrity_duration = time.time() - integrity_start_time
                self.logger.log(f"Error in final integrity check after {integrity_duration:.3f}s: {e}", "ERROR")
                import traceback
                self.logger.log(f"Integrity check traceback: {traceback.format_exc()}", "DEBUG")
            
            # 记录执行总结
            total_execution_time = time.time() - execution_start_time
            self.logger.log("Stop-loss execution completed successfully", "INFO")
            self.logger.log(f"Execution summary: {total_execution_time:.3f}s total, {attempt} attempts, "
                           f"{total_orders_placed} orders placed, {total_orders_filled} orders filled", "INFO")
            
            self.stop_loss_executed = True
            return True
                
        except Exception as e:
            total_execution_time = time.time() - execution_start_time
            self.logger.log(f"Critical error in auto stop-loss execution after {total_execution_time:.3f}s: {e}", "ERROR")
            import traceback
            self.logger.log(f"Critical error traceback: {traceback.format_exc()}", "ERROR")
            self.logger.log(f"Execution summary at failure: {total_execution_time:.3f}s total, {attempt} attempts, "
                           f"{total_orders_placed} orders placed, {total_orders_filled} orders filled", "ERROR")
            return None
    
    async def _monitor_stop_loss_order(self, exchange_client, order_id: str, timeout: int = None) -> bool:
        """
        监控止损订单状态，持续等待直至成交
        
        Args:
            exchange_client: 交易所客户端
            order_id: 订单ID
            timeout: 超时时间（秒），为None时表示无限等待
            
        Returns:
            bool: 是否成交
        """
        start_time = time.time()
        last_status_log_time = 0
        status_log_interval = 10  # 每10秒记录一次状态
        last_status = None
        status_change_timeline = []  # 记录状态变化时间线
        api_call_count = 0
        api_error_count = 0
        rate_limit_count = 0
        
        try:
            self.logger.log(f"Starting order monitoring: {order_id}, timeout: {timeout}s", "INFO")
            
            # 无限循环监控，直至订单成交或被取消/拒绝
            while True:
                # 检查超时
                current_time = time.time()
                if timeout is not None and current_time - start_time >= timeout:
                    elapsed_time = current_time - start_time
                    self.logger.log(f"Order {order_id} monitoring timeout after {elapsed_time:.3f}s", "WARNING")
                    self.logger.log(f"Monitoring summary: {api_call_count} API calls, {api_error_count} errors, {rate_limit_count} rate limits", "INFO")
                    return False
                
                # 获取订单状态
                api_start_time = time.time()
                try:
                    order_info = await exchange_client.get_order_info(order_id)
                    api_call_count += 1
                    api_duration = time.time() - api_start_time
                    
                    if api_duration > 2.0:  # API调用超过2秒记录警告
                        self.logger.log(f"Slow API response for order {order_id}: {api_duration:.3f}s", "WARNING")
                    
                    if order_info is None:
                        self.logger.log(f"Cannot get order info for {order_id} after {api_duration:.3f}s", "WARNING")
                        await asyncio.sleep(2)
                        continue
                        
                except Exception as api_error:
                    api_error_count += 1
                    api_duration = time.time() - api_start_time
                    error_msg = str(api_error).lower()
                    
                    # 检查是否为API限流错误
                    if any(keyword in error_msg for keyword in ['rate limit', 'too many requests', '429', 'throttle']):
                        rate_limit_count += 1
                        rate_limit_error = APIRateLimitError(
                            f"API rate limit hit: {api_error}",
                            retry_after=5,
                            context={
                                'order_id': order_id,
                                'duration': api_duration,
                                'api_call_count': api_call_count,
                                'rate_limit_count': rate_limit_count
                            }
                        )
                        self.logger.log(f"API rate limit hit for order {order_id} after {api_duration:.3f}s: {rate_limit_error}", "WARNING")
                        # 对于限流错误，等待更长时间
                        await asyncio.sleep(5)
                        continue
                    elif any(keyword in error_msg for keyword in ['timeout', 'connection', 'network']):
                        network_error = NetworkConnectionError(
                            f"Network error: {api_error}",
                            endpoint="get_order_info",
                            context={
                                'order_id': order_id,
                                'duration': api_duration,
                                'api_call_count': api_call_count
                            }
                        )
                        self.logger.log(f"Network error getting order {order_id} info after {api_duration:.3f}s: {network_error}", "WARNING")
                        await asyncio.sleep(3)
                        continue
                    else:
                        order_error = OrderMonitoringError(
                            f"API error getting order info: {api_error}",
                            order_id=order_id,
                            context={
                                'duration': api_duration,
                                'api_call_count': api_call_count,
                                'api_error_count': api_error_count
                            }
                        )
                        self.logger.log(f"API error getting order {order_id} info after {api_duration:.3f}s: {order_error}", "ERROR")
                        import traceback
                        self.logger.log(f"API error traceback: {traceback.format_exc()}", "DEBUG")
                        await asyncio.sleep(2)
                        continue
                
                status = order_info.status
                current_time = time.time()
                
                # 记录状态变化
                if status != last_status:
                    status_change_timeline.append({
                        'timestamp': current_time,
                        'status': status,
                        'elapsed_time': current_time - start_time
                    })
                    if last_status is not None:
                        self.logger.log(f"Order {order_id} status changed: {last_status} -> {status} at {current_time - start_time:.3f}s", "INFO")
                    last_status = status
                
                # 定期记录订单状态，避免日志过多
                if current_time - last_status_log_time >= status_log_interval:
                    elapsed_time = current_time - start_time
                    self.logger.log(f"Order {order_id} status: {status} (monitoring for {elapsed_time:.1f}s, {api_call_count} API calls)", "INFO")
                    last_status_log_time = current_time
                
                if status == 'FILLED':
                    elapsed_time = current_time - start_time
                    self.logger.log(f"Order {order_id} filled successfully after {elapsed_time:.3f}s", "INFO")
                    self.logger.log(f"Monitoring summary: {api_call_count} API calls, {api_error_count} errors, {rate_limit_count} rate limits", "INFO")
                    if len(status_change_timeline) > 1:
                        self.logger.log(f"Status timeline: {status_change_timeline}", "DEBUG")
                    return True
                elif status in ['CANCELED', 'REJECTED', 'EXPIRED']:
                    elapsed_time = current_time - start_time
                    self.logger.log(f"Order {order_id} terminated with status: {status} after {elapsed_time:.3f}s", "WARNING")
                    self.logger.log(f"Monitoring summary: {api_call_count} API calls, {api_error_count} errors, {rate_limit_count} rate limits", "INFO")
                    if len(status_change_timeline) > 1:
                        self.logger.log(f"Status timeline: {status_change_timeline}", "DEBUG")
                    return False
                elif status == 'OPEN':
                    # 订单仍在等待成交，继续监控
                    await asyncio.sleep(2)  # 增加检查间隔，减少API调用频率
                    continue
                elif status in ['PARTIALLY_FILLED', 'PENDING']:
                    # 部分成交或待处理状态，继续监控
                    await asyncio.sleep(1)  # 更频繁检查部分成交状态
                    continue
                else:
                    self.logger.log(f"Unknown order status for {order_id}: {status}", "WARNING")
                    await asyncio.sleep(2)
                    continue
            
        except Exception as e:
            elapsed_time = time.time() - start_time
            self.logger.log(f"Critical error monitoring order {order_id} after {elapsed_time:.3f}s: {e}", "ERROR")
            import traceback
            self.logger.log(f"Order monitoring traceback: {traceback.format_exc()}", "ERROR")
            self.logger.log(f"Monitoring summary at failure: {api_call_count} API calls, {api_error_count} errors, {rate_limit_count} rate limits", "ERROR")
            if len(status_change_timeline) > 0:
                self.logger.log(f"Status timeline at failure: {status_change_timeline}", "DEBUG")
            return False
    
    async def _cancel_order_safely(self, exchange_client, order_id: str) -> bool:
        """
        安全取消订单，包含错误处理
        
        Args:
            exchange_client: 交易所客户端
            order_id: 订单ID
            
        Returns:
            bool: 是否成功取消
        """
        try:
            self.logger.log(f"Attempting to cancel order: {order_id}", "INFO")
            
            cancel_result = await exchange_client.cancel_order(order_id)
            
            if cancel_result.success:
                self.logger.log(f"Order {order_id} canceled successfully", "INFO")
                return True
            else:
                self.logger.log(f"Failed to cancel order {order_id}: {cancel_result.error_message}", "WARNING")
                return False
                
        except Exception as e:
            self.logger.log(f"Error canceling order {order_id}: {e}", "ERROR")
            return False
    
    async def _cancel_all_pending_orders(self, exchange_client, contract_id: str):
        """
        取消指定合约的所有挂单
        
        Args:
            exchange_client: 交易所客户端
            contract_id: 合约ID
        """
        try:
            # 获取所有活跃订单
            active_orders = await exchange_client.get_active_orders(contract_id)
            
            if not active_orders:
                self.logger.log("No pending orders to cancel", "INFO")
                return
            
            self.logger.log(f"Found {len(active_orders)} pending orders, cancelling all", "INFO")
            
            # 取消所有订单
            for order in active_orders:
                await self._cancel_order_safely(exchange_client, order.order_id)
                
            # 等待一小段时间确保取消操作完成
            await asyncio.sleep(0.5)
            
        except Exception as e:
            self.logger.log(f"Error cancelling all pending orders: {e}", "ERROR")
    
    async def _monitor_stop_loss_order_with_timeout(self, exchange_client, order_id: str, timeout: int = 5) -> bool:
        """
        监控止损订单状态，带超时机制
        
        Args:
            exchange_client: 交易所客户端
            order_id: 订单ID
            timeout: 超时时间（秒）
            
        Returns:
            bool: 是否在超时时间内成交
        """
        start_time = time.time()
        last_status = None
        status_change_timeline = []  # 记录状态变化时间线
        api_call_count = 0
        api_error_count = 0
        rate_limit_count = 0
        
        try:
            self.logger.log(f"Starting timeout order monitoring: {order_id}, timeout: {timeout}s", "DEBUG")
            
            while time.time() - start_time < timeout:
                current_time = time.time()
                
                # 获取订单状态
                api_start_time = time.time()
                try:
                    order_info = await exchange_client.get_order_info(order_id)
                    api_call_count += 1
                    api_duration = time.time() - api_start_time
                    
                    if api_duration > 1.0:  # 超时监控中API调用超过1秒记录警告
                        self.logger.log(f"Slow API response in timeout monitoring for order {order_id}: {api_duration:.3f}s", "WARNING")
                    
                    if order_info is None:
                        self.logger.log(f"Cannot get order info for {order_id} after {api_duration:.3f}s", "WARNING")
                        await asyncio.sleep(0.5)
                        continue
                        
                except Exception as api_error:
                    api_error_count += 1
                    api_duration = time.time() - api_start_time
                    error_msg = str(api_error).lower()
                    
                    # 检查是否为API限流错误
                    if any(keyword in error_msg for keyword in ['rate limit', 'too many requests', '429', 'throttle']):
                        rate_limit_count += 1
                        remaining_time = timeout - (time.time() - start_time)
                        wait_time = min(2.0, remaining_time / 2)
                        
                        rate_limit_error = APIRateLimitError(
                            f"API rate limit hit in timeout monitoring: {api_error}",
                            retry_after=int(wait_time),
                            context={
                                'order_id': order_id,
                                'duration': api_duration,
                                'timeout': timeout,
                                'remaining_time': remaining_time,
                                'api_call_count': api_call_count,
                                'rate_limit_count': rate_limit_count
                            }
                        )
                        self.logger.log(f"API rate limit hit in timeout monitoring for order {order_id} after {api_duration:.3f}s: {rate_limit_error}", "WARNING")
                        # 对于限流错误，等待更长时间，但不超过剩余超时时间
                        if wait_time > 0:
                            await asyncio.sleep(wait_time)
                        continue
                    elif any(keyword in error_msg for keyword in ['timeout', 'connection', 'network']):
                        network_error = NetworkConnectionError(
                            f"Network error in timeout monitoring: {api_error}",
                            endpoint="get_order_info_timeout",
                            context={
                                'order_id': order_id,
                                'duration': api_duration,
                                'timeout': timeout,
                                'api_call_count': api_call_count
                            }
                        )
                        self.logger.log(f"Network error in timeout monitoring for order {order_id} after {api_duration:.3f}s: {network_error}", "WARNING")
                        await asyncio.sleep(0.5)
                        continue
                    else:
                        order_error = OrderMonitoringError(
                            f"API error in timeout monitoring: {api_error}",
                            order_id=order_id,
                            context={
                                'duration': api_duration,
                                'timeout': timeout,
                                'api_call_count': api_call_count,
                                'api_error_count': api_error_count
                            }
                        )
                        self.logger.log(f"API error in timeout monitoring for order {order_id} after {api_duration:.3f}s: {order_error}", "ERROR")
                        import traceback
                        self.logger.log(f"Timeout monitoring API error traceback: {traceback.format_exc()}", "DEBUG")
                        await asyncio.sleep(0.5)
                        continue
                
                status = order_info.status
                current_time = time.time()
                
                # 记录状态变化
                if status != last_status:
                    status_change_timeline.append({
                        'timestamp': current_time,
                        'status': status,
                        'elapsed_time': current_time - start_time
                    })
                    if last_status is not None:
                        self.logger.log(f"Order {order_id} status changed in timeout monitoring: {last_status} -> {status} at {current_time - start_time:.3f}s", "DEBUG")
                    last_status = status
                
                if status == 'FILLED':
                    elapsed_time = time.time() - start_time
                    self.logger.log(f"Order {order_id} filled after {elapsed_time:.3f}s", "INFO")
                    self.logger.log(f"Timeout monitoring summary: {api_call_count} API calls, {api_error_count} errors, {rate_limit_count} rate limits", "DEBUG")
                    if len(status_change_timeline) > 1:
                        self.logger.log(f"Timeout monitoring status timeline: {status_change_timeline}", "DEBUG")
                    return True
                elif status in ['CANCELED', 'REJECTED', 'EXPIRED']:
                    elapsed_time = time.time() - start_time
                    self.logger.log(f"Order {order_id} terminated with status: {status} after {elapsed_time:.3f}s", "WARNING")
                    self.logger.log(f"Timeout monitoring summary: {api_call_count} API calls, {api_error_count} errors, {rate_limit_count} rate limits", "DEBUG")
                    if len(status_change_timeline) > 1:
                        self.logger.log(f"Timeout monitoring status timeline: {status_change_timeline}", "DEBUG")
                    return False
                elif status in ['PARTIALLY_FILLED', 'PENDING']:
                    # 部分成交或待处理状态，更频繁检查
                    await asyncio.sleep(0.3)
                    continue
                elif status == 'OPEN':
                    # 等待0.5秒后再次检查
                    await asyncio.sleep(0.5)
                    continue
                else:
                    self.logger.log(f"Unknown order status in timeout monitoring for {order_id}: {status}", "WARNING")
                    await asyncio.sleep(0.5)
                    continue
            
            # 超时
            elapsed_time = time.time() - start_time
            self.logger.log(f"Order {order_id} monitoring timeout after {elapsed_time:.3f}s", "WARNING")
            self.logger.log(f"Timeout monitoring summary: {api_call_count} API calls, {api_error_count} errors, {rate_limit_count} rate limits", "INFO")
            if len(status_change_timeline) > 0:
                self.logger.log(f"Timeout monitoring status timeline: {status_change_timeline}", "DEBUG")
            return False
            
        except Exception as e:
            elapsed_time = time.time() - start_time
            self.logger.log(f"Critical error in timeout monitoring for order {order_id} after {elapsed_time:.3f}s: {e}", "ERROR")
            import traceback
            self.logger.log(f"Timeout monitoring critical error traceback: {traceback.format_exc()}", "ERROR")
            self.logger.log(f"Timeout monitoring summary at failure: {api_call_count} API calls, {api_error_count} errors, {rate_limit_count} rate limits", "ERROR")
            if len(status_change_timeline) > 0:
                self.logger.log(f"Timeout monitoring status timeline at failure: {status_change_timeline}", "DEBUG")
            return False
    
    async def _get_position_with_retry(self, exchange_client, max_retries: int = 3) -> Optional[float]:
        """
        带重试机制的持仓读取方法
        
        Args:
            exchange_client: 交易所客户端
            max_retries: 最大重试次数
            
        Returns:
            float: 持仓数量，失败时返回None
        """
        for retry in range(max_retries):
            try:
                position_amt = await exchange_client.get_account_positions()
                
                # 检查返回值是否有效
                if position_amt is not None:
                    self.logger.log(f"Position read successfully: {position_amt}", "INFO")
                    return float(position_amt)
                else:
                    self.logger.log(f"Position read returned None (attempt {retry + 1}/{max_retries})", "WARNING")
                    
            except Exception as e:
                self.logger.log(f"Error reading position (attempt {retry + 1}/{max_retries}): {e}", "WARNING")
            
            # 如果不是最后一次重试，等待一下再重试
            if retry < max_retries - 1:
                await asyncio.sleep(1)
        
        self.logger.log(f"Failed to read position after {max_retries} attempts", "ERROR")
        return None

    async def _final_integrity_check(self, exchange_client, contract_id: str):
        """
        最终完整性检查 - 确认无未成交订单和持仓
        
        Args:
            exchange_client: 交易所客户端
            contract_id: 合约ID
        """
        try:
            self.logger.log("Performing final integrity check...", "INFO")
            
            # 检查是否还有活跃订单
            active_orders = await exchange_client.get_active_orders(contract_id)
            if active_orders:
                self.logger.log(f"Warning: {len(active_orders)} active orders still exist after stop-loss", "WARNING")
                # 取消剩余订单
                for order in active_orders:
                    await self._cancel_order_safely(exchange_client, order.order_id)
            else:
                self.logger.log("No active orders remaining", "INFO")
            
            # 检查是否还有持仓（使用重试机制）
            position_amt = await self._get_position_with_retry(exchange_client, max_retries=3)
            if position_amt is not None and abs(position_amt) > 0.001:  # 考虑浮点精度
                self.logger.log(f"Warning: Position still exists after stop-loss: {position_amt}", "WARNING")
            elif position_amt is not None:
                self.logger.log("No position remaining", "INFO")
            else:
                self.logger.log("Warning: Could not verify final position status", "WARNING")
            
            self.logger.log("Final integrity check completed", "INFO")
            
        except Exception as e:
            self.logger.log(f"Error in final integrity check: {e}", "ERROR")
    
    def get_status(self) -> Dict[str, Any]:
        """获取当前监控状态"""
        if not self.is_monitoring:
            return {
                "monitoring": False,
                "stop_loss_triggered": self.stop_loss_triggered
            }
        
        drawdown_rate = self._calculate_drawdown_rate()
        
        # 计算缓存状态
        cache_age_minutes = 0
        if self.last_successful_update_time:
            cache_age_minutes = (time.time() - self.last_successful_update_time) / 60
        
        status = {
            "monitoring": True,
            "stop_loss_triggered": self.stop_loss_triggered,
            "initial_networth": float(self.initial_networth) if self.initial_networth else None,
            "session_peak_networth": float(self.session_peak_networth) if self.session_peak_networth else None,
            "current_networth": float(self.current_networth) if self.current_networth else None,
            "drawdown_rate": float(drawdown_rate),
            "drawdown_percentage": float(drawdown_rate * 100),
            "current_level": self.current_level.value,
            "thresholds": {
                "light_warning": float(self.config.light_warning_threshold * 100),
                "medium_warning": float(self.config.medium_warning_threshold * 100),
                "severe_stop_loss": float(self.config.severe_stop_loss_threshold * 100)
            },
            "cache_status": {
                "using_cached_value": self.use_cached_value,
                "consecutive_failures": self.consecutive_failures,
                "cache_age_minutes": round(cache_age_minutes, 2),
                "cache_timeout_minutes": self.cache_timeout_minutes,
                "last_successful_networth": float(self.last_successful_networth) if self.last_successful_networth else None
            }
        }
        
        # 如果使用缓存值，添加严格阈值信息
        if self.use_cached_value:
            status["thresholds"]["strict_multiplier"] = float(self.strict_threshold_multiplier)
            status["thresholds"]["effective_severe_stop_loss"] = float(
                self.config.severe_stop_loss_threshold * self.strict_threshold_multiplier * 100
            )
        
        return status
    
    def stop_monitoring(self):
        """停止监控"""
        self.is_monitoring = False
        self.logger.log("Drawdown monitoring stopped", "INFO")
    
    def is_stop_loss_triggered(self) -> bool:
        """检查是否已触发止损"""
        return self.stop_loss_triggered
    
    def get_drawdown_percentage(self) -> float:
        """
        获取当前回撤百分比
        
        Returns:
            float: 回撤百分比 (0-100)
        """
        if not self.is_monitoring:
            return 0.0
        
        drawdown_rate = self._calculate_drawdown_rate()
        return float(drawdown_rate * 100)
    
    def _validate_networth_input(self, networth: Decimal) -> Dict[str, Any]:
        """
        验证净值输入的有效性
        
        Args:
            networth: 待验证的净值
            
        Returns:
            Dict: 包含验证结果和原因的字典
            
        Raises:
            NetworthValidationError: 当净值验证失败时
        """
        try:
            # 检查是否为None
            if networth is None:
                raise NetworthValidationError(
                    "Networth cannot be None", 
                    networth_value=networth,
                    context={'validation_step': 'null_check'}
                )
            
            # 检查是否为有效的Decimal类型
            if not isinstance(networth, Decimal):
                try:
                    networth = Decimal(str(networth))
                except (ValueError, TypeError) as e:
                    raise NetworthValidationError(
                        f"Cannot convert to Decimal: {e}", 
                        networth_value=networth,
                        context={'validation_step': 'type_conversion', 'original_type': type(networth).__name__}
                    )
            
            # 检查是否为有限数值
            if not networth.is_finite():
                raise NetworthValidationError(
                    "Networth is not finite (inf or nan)", 
                    networth_value=networth,
                    context={'validation_step': 'finite_check'}
                )
            
            # 检查是否为负数
            if networth < 0:
                raise NetworthValidationError(
                    f"Networth cannot be negative: {networth}", 
                    networth_value=networth,
                    context={'validation_step': 'negative_check'}
                )
            
            # 检查是否过小（可能是错误数据）
            if networth < Decimal("0.01"):
                raise NetworthValidationError(
                    f"Networth too small (< $0.01): {networth}", 
                    networth_value=networth,
                    context={'validation_step': 'minimum_value_check', 'minimum_threshold': '0.01'}
                )
            
            # 检查是否过大（可能是错误数据）
            max_reasonable_networth = Decimal("1000000000")  # 10亿美元
            if networth > max_reasonable_networth:
                raise NetworthValidationError(
                    f"Networth unreasonably large (> ${max_reasonable_networth}): {networth}", 
                    networth_value=networth,
                    context={'validation_step': 'maximum_value_check', 'maximum_threshold': str(max_reasonable_networth)}
                )
            
            return {'valid': True, 'reason': 'Valid networth'}
            
        except NetworthValidationError:
            # 重新抛出自定义异常
            raise
        except Exception as e:
            # 包装其他未预期的异常
            raise NetworthValidationError(
                f"Unexpected validation error: {e}", 
                networth_value=networth,
                context={'validation_step': 'unexpected_error', 'original_exception': str(e)}
            )
    
    def _update_networth_history(self, current_networth: Decimal):
        """
        更新净值历史记录
        
        Args:
            current_networth: 当前净值
        """
        try:
            self.networth_history.append(current_networth)
            
            # 维护历史记录大小
            if len(self.networth_history) > self.config.smoothing_window_size:
                removed_count = len(self.networth_history) - self.config.smoothing_window_size
                self.networth_history = self.networth_history[-self.config.smoothing_window_size:]
                self.logger.log(f"Trimmed {removed_count} old networth records, history size: {len(self.networth_history)}", "DEBUG")
            
            self.logger.log(f"Added networth to history: ${current_networth}, history size: {len(self.networth_history)}", "DEBUG")
            
        except Exception as e:
            data_error = DataIntegrityError(
                f"Failed to update networth history: {e}",
                data_type="networth_history",
                context={
                    'current_networth': str(current_networth),
                    'history_size': len(self.networth_history) if hasattr(self, 'networth_history') else 0,
                    'max_window_size': self.config.smoothing_window_size if hasattr(self, 'config') else None
                }
            )
            self.logger.log(f"Error updating networth history: {data_error}", "ERROR")
            raise data_error
    
    def _calculate_smoothed_networth(self) -> Decimal:
        """
        计算平滑后的净值
        
        Returns:
            Decimal: 平滑后的净值
        """
        try:
            if not self.networth_history:
                raise ValueError("Networth history is empty")
            
            # 计算平均值
            total = sum(self.networth_history)
            count = len(self.networth_history)
            smoothed = total / Decimal(count)
            
            self.logger.log(f"Smoothed networth calculation: sum=${total}, count={count}, result=${smoothed}", "DEBUG")
            
            return smoothed
            
        except Exception as e:
            data_error = DataIntegrityError(
                f"Failed to calculate smoothed networth: {e}",
                data_type="networth_calculation",
                context={
                    'history_size': len(self.networth_history) if hasattr(self, 'networth_history') else 0,
                    'history_empty': not bool(self.networth_history) if hasattr(self, 'networth_history') else True,
                    'smoothing_window_size': self.config.smoothing_window_size if hasattr(self, 'config') else None
                }
            )
            self.logger.log(f"Error calculating smoothed networth: {data_error}", "ERROR")
            raise data_error
    
    def _log_networth_change(self, previous_networth: Optional[Decimal], current_networth: Decimal):
        """
        记录净值变化
        
        Args:
            previous_networth: 上一次的净值
            current_networth: 当前净值
        """
        try:
            if previous_networth is not None:
                change = current_networth - previous_networth
                change_percent = (change / previous_networth * 100) if previous_networth != 0 else Decimal("0")
                
                if change > 0:
                    self.logger.log(f"Net worth increased: ${previous_networth} -> ${current_networth} (+${change}, +{change_percent:.2f}%)", "INFO")
                elif change < 0:
                    self.logger.log(f"Net worth decreased: ${previous_networth} -> ${current_networth} (${change}, {change_percent:.2f}%)", "INFO")
                else:
                    self.logger.log(f"Net worth unchanged: ${current_networth}", "INFO")
                    
                # 记录详细的变化信息用于调试
                self.logger.log(f"Networth change details: prev=${previous_networth}, curr=${current_networth}, "
                               f"change=${change}, change_pct={change_percent:.4f}%", "DEBUG")
            else:
                self.logger.log(f"Initial net worth recorded: ${current_networth}", "INFO")
                
        except Exception as e:
            self.logger.log(f"Error logging networth change: {e}", "ERROR")
            raise
    
    def _update_session_peak(self, current_networth: Decimal) -> bool:
        """
        更新会话峰值
        
        Args:
            current_networth: 当前净值
            
        Returns:
            bool: 是否更新了峰值
        """
        try:
            if current_networth > self.session_peak_networth:
                old_peak = self.session_peak_networth
                self.session_peak_networth = current_networth
                peak_increase = current_networth - old_peak
                
                self.logger.log(f"New session peak net worth: ${self.session_peak_networth} "
                               f"(previous peak: ${old_peak}, increase: +${peak_increase})", "INFO")
                
                # 记录峰值更新的详细信息
                self.logger.log(f"Peak update details: old=${old_peak}, new=${self.session_peak_networth}, "
                               f"increase=${peak_increase}", "DEBUG")
                
                return True
            else:
                return False
                
        except Exception as e:
            self.logger.log(f"Error updating session peak: {e}", "ERROR")
            raise
    
    def _log_detailed_status(self, current_networth: Decimal, smoothed_networth: Decimal, 
                           drawdown_rate: Decimal, level):
        """
        记录详细的状态信息
        
        Args:
            current_networth: 当前净值
            smoothed_networth: 平滑后的净值
            drawdown_rate: 回撤率
            level: 当前回撤级别
        """
        try:
            # 基本状态信息
            status_info = (f"Net worth status - Raw: ${current_networth}, "
                          f"Smoothed: ${smoothed_networth}, "
                          f"Peak: ${self.session_peak_networth}, "
                          f"Drawdown: {drawdown_rate*100:.2f}%, "
                          f"Level: {level.value}")
            
            self.logger.log(status_info, "INFO")
            
            # 详细调试信息
            debug_info = (f"Detailed status - History size: {len(self.networth_history)}, "
                         f"Initial: ${self.initial_networth}, "
                         f"Monitoring: {self.is_monitoring}, "
                         f"Stop loss triggered: {self.stop_loss_triggered}")
            
            self.logger.log(debug_info, "DEBUG")
            
        except Exception as e:
            self.logger.log(f"Error logging detailed status: {e}", "ERROR")
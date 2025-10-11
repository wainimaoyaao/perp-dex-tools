"""
回撤监控模块 - 实现会话重置策略的回撤止损功能
"""

import time
import asyncio
import inspect
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
    rapid_mode_timeout: int = 30  # 极速模式超时时间（秒）
    cancel_timeout: int = 5  # 订单取消超时时间（秒）


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
        
        # 初始化缓存状态
        self.last_successful_networth = initial_networth
        self.last_successful_update_time = time.time()
        self.consecutive_failures = 0
        self.use_cached_value = False
        
        self.logger.log(f"Trading session started with initial net worth: ${initial_networth}", "INFO")
        self.logger.log(f"Drawdown thresholds - Light: {self.config.light_warning_threshold*100}%, "
                       f"Medium: {self.config.medium_warning_threshold*100}%, "
                       f"Severe: {self.config.severe_stop_loss_threshold*100}%", "INFO")
    
    def should_update_networth(self) -> bool:
        """
        检查是否需要更新净值（基于频率限制）
        
        Returns:
            bool: 是否需要更新净值
        """
        if not self.is_monitoring:
            return False
            
        if self.stop_loss_triggered:
            return False
            
        if self.config.update_frequency_seconds <= 0:
            return True
            
        current_time = time.time()
        time_since_last = current_time - self.last_update_time
        return time_since_last >= self.config.update_frequency_seconds

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
        
        # 直接调用核心更新逻辑，跳过频率检查（因为在 trading_bot.py 中已经检查过了）
        return self._update_networth_core(current_networth)
    
    def _update_networth_core(self, current_networth: Decimal) -> bool:
        """
        核心净值更新逻辑，包含频率检查
        
        Args:
            current_networth: 当前净值
            
        Returns:
            bool: 是否应该继续交易（False表示触发止损）
        """
        method_start_time = time.time()
        
        try:
            # 记录方法调用详情
            self.logger.log(f"_update_networth_core called with value: ${current_networth}", "DEBUG")
            
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
            
            # 直接使用原始净值，不进行平滑处理
            self.current_networth = current_networth
            self.logger.log(f"Using raw networth: ${current_networth}", "DEBUG")
            
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
                self.logger.log(f"Drawdown calculation: {drawdown_rate*100:.4f}%", "DEBUG")
            except Exception as e:
                self.logger.log(f"Error calculating drawdown rates: {e}", "ERROR")
                drawdown_rate = Decimal("0")
            
            # 检查回撤级别
            try:
                new_level = self._determine_drawdown_level(drawdown_rate)
                
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
            self._log_detailed_status(current_networth, drawdown_rate, new_level)
            
            # 性能监控
            execution_time = time.time() - method_start_time
            if execution_time > 0.1:  # 如果执行时间超过100ms则记录
                self.logger.log(f"_update_networth_core execution time: {execution_time:.3f}s", "WARNING")
            else:
                self.logger.log(f"_update_networth_core completed in {execution_time:.3f}s", "DEBUG")
            
            # 返回结果
            result = not self.stop_loss_triggered
            self.logger.log(f"_update_networth_core returning: {result} (stop_loss_triggered={self.stop_loss_triggered})", "DEBUG")
            return result
            
        except Exception as e:
            execution_time = time.time() - method_start_time
            self.logger.log(f"Critical error in _update_networth_core after {execution_time:.3f}s: {e}", "ERROR")
            import traceback
            self.logger.log(f"Traceback: {traceback.format_exc()}", "ERROR")
            # 在发生严重错误时，保守地返回True以继续监控
            return True
    
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
            
            # 直接使用原始净值，不进行平滑处理
            self.current_networth = current_networth
            self.logger.log(f"Using raw networth: ${current_networth}", "DEBUG")
            
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
                self.logger.log(f"Drawdown calculation: {drawdown_rate*100:.4f}%", "DEBUG")
            except Exception as e:
                self.logger.log(f"Error calculating drawdown rates: {e}", "ERROR")
                drawdown_rate = Decimal("0")
            
            # 检查回撤级别
            try:
                new_level = self._determine_drawdown_level(drawdown_rate)
                
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
            self._log_detailed_status(current_networth, drawdown_rate, new_level)
            
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
    
    def _determine_drawdown_level(self, drawdown_rate: Decimal) -> DrawdownLevel:
        """根据回撤率确定警告级别"""
        # 使用当前回撤率进行检测
        severe_check_rate = drawdown_rate
        
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
                cb = self.warning_callbacks[new_level]
                # 统一参数顺序为：当前回撤、峰值净值、当前净值，并将 Decimal 转为 float 以便格式化
                args = (
                    float(drawdown_rate),
                    float(self.session_peak_networth) if self.session_peak_networth is not None else 0.0,
                    float(self.current_networth) if self.current_networth is not None else 0.0,
                )
                if inspect.iscoroutinefunction(cb):
                    asyncio.create_task(cb(*args))
                else:
                    cb(*args)
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
        """
        执行待处理的止损（异步方法）
        
        现在只使用极速止损模式（15-30秒目标），不再支持传统模式
        """
        if not hasattr(self, '_pending_stop_loss_drawdown') or not self.stop_loss_triggered:
            return
        
        drawdown_rate = self._pending_stop_loss_drawdown
        
        # 执行自动止损（如果配置了交易所客户端和合约ID）
        if self.exchange_client and self.contract_id:
            self.logger.log("Executing RAPID stop-loss (target: 15-30 seconds)...", "INFO")
            try:
                stop_loss_result = await self._execute_rapid_stop_loss(
                    self.exchange_client, 
                    self.contract_id
                )
                if stop_loss_result is True:
                    self.logger.log("Rapid stop-loss executed successfully", "INFO")
                else:
                    self.logger.log("Rapid stop-loss execution failed", "ERROR")
            except Exception as e:
                self.logger.log(f"Error during rapid stop-loss: {e}", "ERROR")
        else:
            self.logger.log("Automatic stop-loss not configured (missing exchange_client or contract_id)", "WARNING")
        
        # 触发止损回调
        if self.stop_loss_callback:
            try:
                # 与 TradingBot 中的回调签名保持一致：当前回撤、峰值净值、当前净值
                cb = self.stop_loss_callback
                # 计算损失金额（峰值净值 - 当前净值）
                try:
                    if self.session_peak_networth is not None and self.current_networth is not None:
                        loss_amount = self.session_peak_networth - self.current_networth
                    else:
                        loss_amount = Decimal(0)
                except Exception:
                    loss_amount = Decimal(0)

                args = (
                    float(drawdown_rate),
                    float(self.session_peak_networth) if self.session_peak_networth is not None else 0.0,
                    float(self.current_networth) if self.current_networth is not None else 0.0,
                    float(loss_amount),
                )
                if inspect.iscoroutinefunction(cb):
                    asyncio.create_task(cb(*args))
                else:
                    cb(*args)
            except Exception as e:
                self.logger.log(f"Error in stop loss callback: {e}", "ERROR")
        
        # 清除待处理标记
        delattr(self, '_pending_stop_loss_drawdown')
    

    


    async def _execute_rapid_stop_loss(self, exchange_client, contract_id: str) -> bool:
        """
        执行极速止损策略：快速取消 + 一次性市价单
        目标：15-30秒内完成整个止损流程
        
        流程：
        1. 快速并行取消所有挂单（5秒内完成）
        2. 获取当前持仓
        3. 一次性市价单平仓
        4. 监控订单执行状态
        
        Args:
            exchange_client: 交易所客户端
            contract_id: 合约ID
            
        Returns:
            bool: 执行是否成功
        """
        execution_start_time = time.time()
        
        try:
            self.logger.log("Starting rapid stop-loss execution", "INFO")
            self.logger.log(f"Target: Complete within 15-30 seconds for contract {contract_id}", "INFO")
            
            # 阶段1: 快速取消所有挂单（目标：5秒内完成）
            cancel_start_time = time.time()
            cancel_success = False
            
            try:
                self.logger.log("Phase 1: Fast cancellation of all pending orders", "INFO")
                cancel_success = await self._fast_cancel_all_orders(exchange_client, contract_id, max_wait=self.config.cancel_timeout)
                cancel_duration = time.time() - cancel_start_time
                
                if cancel_success:
                    self.logger.log(f"Fast cancellation completed successfully in {cancel_duration:.3f}s", "INFO")
                else:
                    self.logger.log(f"Fast cancellation failed after {cancel_duration:.3f}s, switching to aggressive mode", "WARNING")
                    
            except Exception as e:
                cancel_duration = time.time() - cancel_start_time
                self.logger.log(f"Error in fast cancellation after {cancel_duration:.3f}s: {e}", "ERROR")
                cancel_success = False
            
            # 如果快速取消失败，启用激进模式
            if not cancel_success:
                try:
                    self.logger.log("Switching to aggressive cancel mode", "WARNING")
                    aggressive_result = await self._aggressive_cancel_mode(exchange_client, contract_id)
                    if aggressive_result:
                        self.logger.log("Aggressive cancel mode activated, proceeding with position closure", "INFO")
                    else:
                        self.logger.log("Aggressive cancel mode failed, but continuing with position closure", "WARNING")
                except Exception as e:
                    self.logger.log(f"Error in aggressive cancel mode: {e}", "ERROR")
            
            # 阶段2: 获取当前持仓（目标：3秒内完成）
            position_start_time = time.time()
            try:
                self.logger.log("Phase 2: Reading current position", "INFO")
                position_amt = await self._get_position_with_retry(exchange_client, max_retries=2)
                position_duration = time.time() - position_start_time
                
                if position_amt is None:
                    self.logger.log(f"Failed to read position after {position_duration:.3f}s", "ERROR")
                    return False
                
                self.logger.log(f"Position read in {position_duration:.3f}s: {position_amt}", "INFO")
                
                if abs(position_amt) < 0.001:  # 基本无持仓
                    execution_duration = time.time() - execution_start_time
                    self.logger.log(f"No significant position remaining, rapid stop-loss completed in {execution_duration:.3f}s", "INFO")
                    # 收尾：确保无挂单且无持仓
                    try:
                        await self._final_integrity_check(exchange_client, contract_id)
                    except Exception as e:
                        self.logger.log(f"Error during final integrity check: {e}", "WARNING")
                    return True
                    
            except Exception as e:
                position_duration = time.time() - position_start_time
                self.logger.log(f"Error reading position after {position_duration:.3f}s: {e}", "ERROR")
                return False
            
            # 阶段3: 一次性市价单平仓（目标：10秒内完成）
            market_order_start_time = time.time()
            try:
                self.logger.log("Phase 3: Placing emergency market order for full position closure", "INFO")
                position_size = abs(position_amt)
                
                order_success = await self._place_emergency_market_order(
                    exchange_client, 
                    contract_id, 
                    position_size
                )
                
                market_order_duration = time.time() - market_order_start_time
                
                if not order_success:
                    self.logger.log(f"Failed to place emergency market order after {market_order_duration:.3f}s", "ERROR")
                    try:
                        await self._final_integrity_check(exchange_client, contract_id)
                    except Exception as e:
                        self.logger.log(f"Error during final integrity check: {e}", "WARNING")
                    return False
                
                self.logger.log(f"Emergency market order placed successfully in {market_order_duration:.3f}s", "INFO")
                
            except Exception as e:
                market_order_duration = time.time() - market_order_start_time
                self.logger.log(f"Error placing emergency market order after {market_order_duration:.3f}s: {e}", "ERROR")
                try:
                    integrity_passed = await self._final_integrity_check(exchange_client, contract_id)
                    if integrity_passed:
                        self.logger.log("Stop-loss execution verified successful despite market order error", "INFO")
                        self.stop_loss_executed = True
                        return True
                except Exception as ie:
                    self.logger.log(f"Error during final integrity check: {ie}", "WARNING")
                return False
            
            # 阶段4: 最终验证（目标：5秒内完成）
            verification_start_time = time.time()
            try:
                self.logger.log("Phase 4: Final position verification", "INFO")
                
                # 等待一小段时间让订单处理
                await asyncio.sleep(2)
                
                final_position = await self._get_position_with_retry(exchange_client, max_retries=2)
                verification_duration = time.time() - verification_start_time
                
                if final_position is None:
                    self.logger.log(f"Failed to verify final position after {verification_duration:.3f}s", "WARNING")
                elif abs(final_position) < 0.001:
                    self.logger.log(f"Position successfully closed, verified in {verification_duration:.3f}s", "INFO")
                else:
                    self.logger.log(f"Warning: Remaining position {final_position} after {verification_duration:.3f}s", "WARNING")
                    
            except Exception as e:
                verification_duration = time.time() - verification_start_time
                self.logger.log(f"Error in final verification after {verification_duration:.3f}s: {e}", "WARNING")
            
            # 记录执行总结
            total_execution_time = time.time() - execution_start_time
            self.logger.log("Rapid stop-loss execution completed", "INFO")
            self.logger.log(f"Total execution time: {total_execution_time:.3f}s", "INFO")
            
            # 性能评估
            if total_execution_time <= 15:
                self.logger.log("Excellent performance: Completed within 15 seconds", "INFO")
            elif total_execution_time <= 30:
                self.logger.log("Good performance: Completed within 30 seconds", "INFO")
            else:
                self.logger.log(f"Performance warning: Took {total_execution_time:.3f}s (target: 15-30s)", "WARNING")
            
            # 收尾：确保无挂单且无持仓
            try:
                integrity_passed = await self._final_integrity_check(exchange_client, contract_id)
                if integrity_passed:
                    self.logger.log("Stop-loss execution verified successful", "INFO")
                    self.stop_loss_executed = True
                    return True
                else:
                    self.logger.log("Final integrity check failed - stop-loss may not be complete", "WARNING")
                    return False
            except Exception as e:
                self.logger.log(f"Error during final integrity check: {e}", "WARNING")
                return False
                
        except Exception as e:
            total_execution_time = time.time() - execution_start_time
            self.logger.log(f"Critical error in rapid stop-loss execution after {total_execution_time:.3f}s: {e}", "ERROR")
            import traceback
            self.logger.log(f"Rapid stop-loss execution traceback: {traceback.format_exc()}", "DEBUG")
            try:
                integrity_passed = await self._final_integrity_check(exchange_client, contract_id)
                if integrity_passed:
                    self.logger.log("Stop-loss execution verified successful despite execution error", "INFO")
                    self.stop_loss_executed = True
                    return True
            except Exception as ie:
                self.logger.log(f"Error during final integrity check: {ie}", "WARNING")
            return False
    
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
    
    async def _fast_cancel_all_orders(self, exchange_client, contract_id: str, max_wait: int = 5) -> bool:
        """
        快速取消所有挂单：并行取消 + 快速验证
        目标：5秒内完成所有取消操作
        
        Args:
            exchange_client: 交易所客户端
            contract_id: 合约ID
            max_wait: 最大等待时间（秒）
            
        Returns:
            bool: 是否成功取消所有订单
        """
        start_time = time.time()
        
        try:
            # 第1步：获取所有活跃订单（1秒）
            self.logger.log("Fast cancel: Getting active orders...", "INFO")
            active_orders = await exchange_client.get_active_orders(contract_id)
            
            if not active_orders:
                self.logger.log("Fast cancel: No orders to cancel", "INFO")
                return True
            
            order_count = len(active_orders)
            self.logger.log(f"Fast cancel: Found {order_count} orders, starting parallel cancellation", "INFO")
            
            # 第2步：并行发送取消请求（1-2秒）
            cancel_tasks = []
            for order in active_orders:
                task = asyncio.create_task(exchange_client.cancel_order(order.order_id))
                cancel_tasks.append(task)
            
            # 等待所有取消请求完成，但不超过2秒
            try:
                await asyncio.wait_for(asyncio.gather(*cancel_tasks, return_exceptions=True), timeout=2.0)
                self.logger.log("Fast cancel: All cancel requests sent", "INFO")
            except asyncio.TimeoutError:
                self.logger.log("Fast cancel: Cancel requests timeout, continuing verification...", "WARNING")
            
            # 第3步：快速验证（最多2秒，每0.5秒检查一次）
            for i in range(4):  # 最多检查4次
                await asyncio.sleep(0.5)
                remaining_orders = await exchange_client.get_active_orders(contract_id)
                
                if not remaining_orders:
                    duration = time.time() - start_time
                    self.logger.log(f"Fast cancel: All orders canceled successfully in {duration:.2f}s", "INFO")
                    return True
                
                if i < 3:  # 不是最后一次检查
                    self.logger.log(f"Fast cancel: {len(remaining_orders)} orders still active, checking again...", "DEBUG")
            
            # 最终检查失败
            duration = time.time() - start_time
            remaining_orders = await exchange_client.get_active_orders(contract_id)
            self.logger.log(f"Fast cancel: WARNING - {len(remaining_orders)} orders still active after {duration:.2f}s", "WARNING")
            return False
            
        except Exception as e:
            duration = time.time() - start_time
            self.logger.log(f"Fast cancel: Error after {duration:.2f}s - {e}", "ERROR")
            return False

    async def _aggressive_cancel_mode(self, exchange_client, contract_id: str) -> bool:
        """
        激进取消模式：如果常规取消失败，直接进入平仓
        适用于极端市场条件下的紧急止损
        
        Args:
            exchange_client: 交易所客户端
            contract_id: 合约ID
            
        Returns:
            bool: 总是返回True，允许继续执行平仓流程
        """
        self.logger.log("AGGRESSIVE MODE: Skipping order cancellation due to emergency", "WARNING")
        self.logger.log("Reason: Market emergency detected, proceeding directly to position closing", "WARNING")
        
        try:
            # 记录未取消的订单（用于后续处理）
            active_orders = await exchange_client.get_active_orders(contract_id)
            if active_orders:
                order_ids = [order.order_id for order in active_orders]
                self.logger.log(f"Aggressive mode: {len(order_ids)} uncanceled orders: {order_ids}", "WARNING")
                
                # 异步继续尝试取消（不阻塞主流程）
                asyncio.create_task(self._background_cancel_orders(exchange_client, order_ids))
            else:
                self.logger.log("Aggressive mode: No active orders found", "INFO")
                
        except Exception as e:
            self.logger.log(f"Aggressive mode: Error checking orders - {e}", "ERROR")
        
        return True  # 直接返回成功，继续平仓流程

    async def _background_cancel_orders(self, exchange_client, order_ids: list):
        """
        后台异步取消订单，不阻塞主流程
        
        Args:
            exchange_client: 交易所客户端
            order_ids: 订单ID列表
        """
        try:
            self.logger.log(f"Background cancel: Attempting to cancel {len(order_ids)} orders", "INFO")
            
            for order_id in order_ids:
                try:
                    await exchange_client.cancel_order(order_id)
                    self.logger.log(f"Background cancel: Order {order_id} canceled", "INFO")
                except Exception as e:
                    self.logger.log(f"Background cancel: Failed to cancel {order_id} - {e}", "WARNING")
                    
                # 小延迟避免过于频繁的请求
                await asyncio.sleep(0.1)
                
        except Exception as e:
            self.logger.log(f"Background cancel: Error in background cancellation - {e}", "ERROR")

    async def _place_emergency_market_order(self, exchange_client, contract_id: str, position_size: float) -> bool:
        """
        紧急市价单平仓：一次性市价单关闭所有持仓
        
        Args:
            exchange_client: 交易所客户端
            contract_id: 合约ID
            position_size: 持仓大小（正数为多头，负数为空头）
            
        Returns:
            bool: 是否成功执行
        """
        start_time = time.time()
        
        try:
            # 确定平仓方向和数量
            if position_size > 0:
                # 多头持仓，需要卖出平仓
                side = "sell"
                quantity = abs(position_size)
            else:
                # 空头持仓，需要买入平仓
                side = "buy"
                quantity = abs(position_size)
            
            self.logger.log(f"Emergency market order: {side} {quantity} to close position", "INFO")
            
            # 使用交易所支持的市价单接口立即平仓（兼容不同交易所的参数差异）
            # 不同交易所的实现需兼容：这里调用统一的 place_market_order(direction)
            # 优先尝试启用 WS 优先策略以降低 REST 轮询依赖（仅在交易所实现支持时生效）
            try:
                # 首先尝试完整参数（适用于 Lighter 等支持 reduce_only 的交易所）
                order_result = await exchange_client.place_market_order(
                    contract_id=contract_id,
                    quantity=Decimal(str(quantity)),
                    direction=side,
                    prefer_ws=True,
                    reduce_only=True
                )
                self.logger.log("Emergency market order: prefer_ws=True and reduce_only=True enabled", "DEBUG")
            except TypeError as e:
                if "reduce_only" in str(e):
                    # GRVT 等交易所不支持 reduce_only 参数，尝试不带该参数
                    try:
                        order_result = await exchange_client.place_market_order(
                            contract_id=contract_id,
                            quantity=Decimal(str(quantity)),
                            direction=side,
                            prefer_ws=True
                        )
                        self.logger.log("Emergency market order: prefer_ws=True enabled (reduce_only not supported)", "DEBUG")
                    except TypeError:
                        # 交易所也不支持 prefer_ws 参数，使用最基本的调用方式
                        order_result = await exchange_client.place_market_order(
                            contract_id=contract_id,
                            quantity=Decimal(str(quantity)),
                            direction=side
                        )
                        self.logger.log("Emergency market order: basic parameters only (exchange compatibility mode)", "DEBUG")
                else:
                    # 其他 TypeError，可能是 prefer_ws 参数问题，尝试不带 prefer_ws
                    try:
                        order_result = await exchange_client.place_market_order(
                            contract_id=contract_id,
                            quantity=Decimal(str(quantity)),
                            direction=side,
                            reduce_only=True
                        )
                        self.logger.log("Emergency market order: reduce_only=True enabled (prefer_ws not supported)", "DEBUG")
                    except TypeError:
                        # 最后回退到最基本的调用方式
                        order_result = await exchange_client.place_market_order(
                            contract_id=contract_id,
                            quantity=Decimal(str(quantity)),
                            direction=side
                        )
                        self.logger.log("Emergency market order: basic parameters only (full compatibility mode)", "DEBUG")
            
            if not order_result.success:
                duration = time.time() - start_time
                self.logger.log(f"Emergency market order: Failed after {duration:.2f}s - {order_result.error_message}", "ERROR")
                return False
            
            order_id = order_result.order_id
            self.logger.log(f"Emergency market order: Order {order_id} placed successfully", "INFO")
            
            # 监控订单执行（最多等待30秒）
            fill_success = await self._monitor_emergency_order(exchange_client, order_id, timeout=30)
            
            duration = time.time() - start_time
            if fill_success:
                self.logger.log(f"Emergency market order: Completed successfully in {duration:.2f}s", "INFO")
                return True
            else:
                self.logger.log(f"Emergency market order: Failed to fill completely in {duration:.2f}s", "ERROR")
                return False
                
        except Exception as e:
            duration = time.time() - start_time
            self.logger.log(f"Emergency market order: Error after {duration:.2f}s - {e}", "ERROR")
            return False

    async def _monitor_emergency_order(self, exchange_client, order_id: str, timeout: int = None) -> bool:
        """
        监控紧急市价单的执行状态
        
        Args:
            exchange_client: 交易所客户端
            order_id: 订单ID
            timeout: 超时时间（秒，None时使用配置默认值）
            
        Returns:
            bool: 是否完全成交
        """
        # 如果没有指定超时时间，使用配置中的设置
        if timeout is None:
            timeout = self.config.rapid_mode_timeout
            
        start_time = time.time()
        check_interval = 1.0  # 每秒检查一次
        
        try:
            while time.time() - start_time < timeout:
                try:
                    order_info = await exchange_client.get_order_info(order_id)
                    
                    if order_info and hasattr(order_info, 'status'):
                        status = order_info.status.lower()
                        
                        if status in ['filled', 'completely_filled']:
                            duration = time.time() - start_time
                            self.logger.log(f"Emergency order {order_id}: Completely filled in {duration:.2f}s", "INFO")
                            return True
                        elif status in ['cancelled', 'rejected', 'expired']:
                            duration = time.time() - start_time
                            self.logger.log(f"Emergency order {order_id}: Failed with status {status} after {duration:.2f}s", "ERROR")
                            return False
                        elif status in ['partially_filled']:
                            filled_qty = getattr(order_info, 'filled_quantity', 0)
                            total_qty = getattr(order_info, 'quantity', 0)
                            self.logger.log(f"Emergency order {order_id}: Partially filled {filled_qty}/{total_qty}", "INFO")
                        else:
                            self.logger.log(f"Emergency order {order_id}: Status {status}", "DEBUG")
                    
                except Exception as e:
                    self.logger.log(f"Emergency order monitor: Error checking order {order_id} - {e}", "WARNING")
                
                await asyncio.sleep(check_interval)
            
            # 超时
            duration = time.time() - start_time
            self.logger.log(f"Emergency order {order_id}: Monitoring timeout after {duration:.2f}s", "ERROR")
            return False
            
        except Exception as e:
            duration = time.time() - start_time
            self.logger.log(f"Emergency order monitor: Error after {duration:.2f}s - {e}", "ERROR")
            return False
    
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

    async def _final_integrity_check(self, exchange_client, contract_id: str) -> bool:
        """
        简化的最终完整性检查 - 仅验证无活跃订单和持仓
        
        Args:
            exchange_client: 交易所客户端
            contract_id: 合约ID
            
        Returns:
            bool: True表示检查通过（持仓=0且无活跃订单），False表示检查失败
        """
        try:
            self.logger.log("Performing final integrity check...", "INFO")
            
            # 检查活跃订单
            try:
                active_orders = await exchange_client.get_active_orders(contract_id)
                active_count = len(active_orders) if active_orders else 0
            except Exception as e:
                self.logger.log(f"Final check: Error fetching active orders - {e}", "WARNING")
                active_count = -1  # 未知状态
            
            # 检查持仓
            try:
                position_amt = await exchange_client.get_account_positions()
                position_closed = abs(position_amt) <= 0.001
            except Exception as e:
                self.logger.log(f"Final check: Error fetching position - {e}", "WARNING")
                position_amt = None
                position_closed = False
            
            # 判断检查结果
            if active_count == 0 and position_closed:
                self.logger.log(f"✅ Final integrity check PASSED: Position={position_amt}, Active orders={active_count}", "INFO")
                return True
            else:
                self.logger.log(f"❌ Final integrity check FAILED: Position={position_amt}, Active orders={active_count}", "WARNING")
                return False
            
        except Exception as e:
            self.logger.log(f"Error in final integrity check: {e}", "ERROR")
            return False
    
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
    
    def _log_detailed_status(self, current_networth: Decimal, 
                           drawdown_rate: Decimal, level):
        """
        记录详细的状态信息
        
        Args:
            current_networth: 当前净值
            drawdown_rate: 回撤率
            level: 当前回撤级别
        """
        try:
            # 基本状态信息
            status_info = (f"Net worth status - Current: ${current_networth}, "
                          f"Peak: ${self.session_peak_networth}, "
                          f"Drawdown: {drawdown_rate*100:.2f}%, "
                          f"Level: {level.value}")
            
            self.logger.log(status_info, "INFO")
            
            # 详细调试信息
            debug_info = (f"Detailed status - "
                         f"Initial: ${self.initial_networth}, "
                         f"Monitoring: {self.is_monitoring}, "
                         f"Stop loss triggered: {self.stop_loss_triggered}")
            
            self.logger.log(debug_info, "DEBUG")
            
        except Exception as e:
            self.logger.log(f"Error logging detailed status: {e}", "ERROR")
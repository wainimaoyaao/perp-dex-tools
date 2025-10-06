"""
回撤监控模块 - 实现会话重置策略的回撤止损功能
"""

import time
from decimal import Decimal
from typing import Dict, Any, Optional, Callable
from enum import Enum
from dataclasses import dataclass
from helpers.logger import TradingLogger


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
    
    def __init__(self, config: DrawdownConfig, logger: TradingLogger):
        """
        初始化回撤监控器
        
        Args:
            config: 回撤监控配置
            logger: 日志记录器
        """
        self.config = config
        self.logger = logger
        
        # 会话状态
        self.session_peak_networth: Optional[Decimal] = None
        self.current_networth: Optional[Decimal] = None
        self.initial_networth: Optional[Decimal] = None
        
        # 监控状态
        self.current_level = DrawdownLevel.NORMAL
        self.last_update_time = 0
        self.is_monitoring = False
        self.stop_loss_triggered = False
        
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
        self.initial_networth = initial_networth
        self.session_peak_networth = initial_networth
        self.current_networth = initial_networth
        self.current_level = DrawdownLevel.NORMAL
        self.last_update_time = time.time()
        self.is_monitoring = True
        self.stop_loss_triggered = False
        self.networth_history = [initial_networth]
        
        self.logger.log(f"Trading session started with initial net worth: ${initial_networth}", "INFO")
        self.logger.log(f"Drawdown thresholds - Light: {self.config.light_warning_threshold*100}%, "
                       f"Medium: {self.config.medium_warning_threshold*100}%, "
                       f"Severe: {self.config.severe_stop_loss_threshold*100}%", "INFO")
    
    def update_networth(self, current_networth: Decimal) -> bool:
        """
        更新当前净值并检查回撤
        
        Args:
            current_networth: 当前净值
            
        Returns:
            bool: 是否应该继续交易（False表示触发止损）
        """
        if not self.is_monitoring or self.stop_loss_triggered:
            return False
        
        current_time = time.time()
        
        # 检查更新频率（如果设置为0则跳过时间检查，用于测试）
        if self.config.update_frequency_seconds > 0 and current_time - self.last_update_time < self.config.update_frequency_seconds:
            return True
        
        # 更新净值历史（用于平滑处理）
        self.networth_history.append(current_networth)
        if len(self.networth_history) > self.config.smoothing_window_size:
            self.networth_history.pop(0)
        
        # 计算平滑后的净值
        smoothed_networth = sum(self.networth_history) / Decimal(len(self.networth_history))
        self.current_networth = smoothed_networth
        
        # 更新会话峰值
        if smoothed_networth > self.session_peak_networth:
            self.session_peak_networth = smoothed_networth
            self.logger.log(f"New session peak net worth: ${self.session_peak_networth}", "INFO")
        
        # 计算回撤率
        drawdown_rate = self._calculate_drawdown_rate()
        
        # 检查回撤级别
        new_level = self._determine_drawdown_level(drawdown_rate)
        
        # 如果级别发生变化，触发相应的处理
        if new_level != self.current_level:
            self._handle_level_change(self.current_level, new_level, drawdown_rate)
            self.current_level = new_level
        
        self.last_update_time = current_time
        
        # 记录当前状态
        self.logger.log(f"Net worth update - Current: ${smoothed_networth}, "
                       f"Peak: ${self.session_peak_networth}, "
                       f"Drawdown: {drawdown_rate*100:.2f}%, "
                       f"Level: {new_level.value}", "DEBUG")
        
        # 如果触发严重止损，返回 False
        return not self.stop_loss_triggered
    
    def _calculate_drawdown_rate(self) -> Decimal:
        """计算当前回撤率"""
        if not self.session_peak_networth or self.session_peak_networth <= 0:
            return Decimal("0")
        
        drawdown = self.session_peak_networth - self.current_networth
        drawdown_rate = drawdown / self.session_peak_networth
        
        return max(Decimal("0"), drawdown_rate)  # 确保回撤率不为负
    
    def _determine_drawdown_level(self, drawdown_rate: Decimal) -> DrawdownLevel:
        """根据回撤率确定警告级别"""
        if drawdown_rate >= self.config.severe_stop_loss_threshold:
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
        
        # 处理严重止损
        if new_level == DrawdownLevel.SEVERE_STOP_LOSS:
            self._trigger_stop_loss(drawdown_rate)
    
    def _trigger_stop_loss(self, drawdown_rate: Decimal):
        """触发止损"""
        self.stop_loss_triggered = True
        self.is_monitoring = False
        
        loss_amount = self.session_peak_networth - self.current_networth
        
        self.logger.log("=" * 60, "ERROR")
        self.logger.log("SEVERE DRAWDOWN STOP LOSS TRIGGERED!", "ERROR")
        self.logger.log(f"Session Peak Net Worth: ${self.session_peak_networth}", "ERROR")
        self.logger.log(f"Current Net Worth: ${self.current_networth}", "ERROR")
        self.logger.log(f"Drawdown Rate: {drawdown_rate*100:.2f}%", "ERROR")
        self.logger.log(f"Loss Amount: ${loss_amount}", "ERROR")
        self.logger.log("Trading will be stopped immediately!", "ERROR")
        self.logger.log("=" * 60, "ERROR")
        
        # 触发止损回调
        if self.stop_loss_callback:
            try:
                self.stop_loss_callback(drawdown_rate, self.current_networth, self.session_peak_networth, loss_amount)
            except Exception as e:
                self.logger.log(f"Error in stop loss callback: {e}", "ERROR")
    
    def get_status(self) -> Dict[str, Any]:
        """获取当前监控状态"""
        if not self.is_monitoring:
            return {
                "monitoring": False,
                "stop_loss_triggered": self.stop_loss_triggered
            }
        
        drawdown_rate = self._calculate_drawdown_rate()
        
        return {
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
            }
        }
    
    def get_drawdown_percentage(self) -> float:
        """获取当前回撤百分比"""
        if not self.is_monitoring:
            return 0.0
        
        drawdown_rate = self._calculate_drawdown_rate()
        return float(drawdown_rate * 100)
    
    def stop_monitoring(self):
        """停止监控"""
        self.is_monitoring = False
        self.logger.log("Drawdown monitoring stopped", "INFO")
    
    def is_stop_loss_triggered(self) -> bool:
        """检查是否已触发止损"""
        return self.stop_loss_triggered
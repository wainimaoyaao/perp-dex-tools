# 回撤监控命令行参数使用示例

## 概述
回撤监控功能允许您通过命令行参数自定义监控阈值，提供三级保护：
- **轻微回撤 (Light)**: 仅记录和通知
- **中等回撤 (Medium)**: 暂停新订单，仅允许平仓
- **严重回撤 (Severe)**: 立即停止交易并退出

## 可用参数

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `--enable-drawdown-monitor` | flag | False | 启用回撤监控功能 |
| `--drawdown-light-threshold` | Decimal | 5 | 轻微回撤警告阈值 (%) |
| `--drawdown-medium-threshold` | Decimal | 8 | 中等回撤警告阈值 (%) |
| `--drawdown-severe-threshold` | Decimal | 12 | 严重回撤止损阈值 (%) |

## 使用示例

### 1. 使用默认阈值启用回撤监控
```bash
python runbot.py --enable-drawdown-monitor
```
- 轻微回撤: 5%
- 中等回撤: 8%
- 严重回撤: 12%

### 2. 保守策略 - 较低的回撤阈值
```bash
python runbot.py --enable-drawdown-monitor \
  --drawdown-light-threshold 3.0 \
  --drawdown-medium-threshold 5.0 \
  --drawdown-severe-threshold 8.0
```
适用于风险厌恶型交易者，更早触发保护机制。

### 3. 激进策略 - 较高的回撤阈值
```bash
python runbot.py --enable-drawdown-monitor \
  --drawdown-light-threshold 8.0 \
  --drawdown-medium-threshold 12.0 \
  --drawdown-severe-threshold 18.0
```
适用于风险承受能力较强的交易者，允许更大的回撤。

### 4. 完整的交易配置示例
```bash
python runbot.py \
  --exchange edgex \
  --ticker BTC \
  --quantity 0.05 \
  --direction buy \
  --enable-drawdown-monitor \
  --drawdown-light-threshold 4.0 \
  --drawdown-medium-threshold 7.0 \
  --drawdown-severe-threshold 10.0
```

## 监控行为说明

### 轻微回撤 (Light Drawdown)
- **触发条件**: 当前净值相对于会话峰值的回撤达到轻微阈值
- **行为**: 记录警告日志并发送通知，交易继续正常进行
- **通知内容**: 包含当前净值、峰值净值、回撤百分比等信息

### 中等回撤 (Medium Drawdown)
- **触发条件**: 回撤达到中等阈值
- **行为**: 暂停新订单的创建，仅允许现有仓位的平仓操作
- **恢复**: 当回撤降低到中等阈值以下时，自动恢复正常交易

### 严重回撤 (Severe Drawdown)
- **触发条件**: 回撤达到严重阈值
- **行为**: 立即停止所有交易活动并优雅退出程序
- **不可恢复**: 需要手动重启程序才能继续交易

## 注意事项

1. **阈值顺序**: 必须满足 `light < medium < severe` 的关系
2. **实时监控**: 回撤监控在主交易循环中实时进行
3. **净值计算**: 基于交易所账户的实际净值进行计算
4. **会话峰值**: 每次启动程序时重新计算会话峰值
5. **通知系统**: 支持 Telegram 和 Lark 通知（需要配置相应的 bot）

## 最佳实践

1. **首次使用**: 建议从保守的阈值开始，逐步调整到适合的水平
2. **回测验证**: 在实盘使用前，建议通过历史数据验证阈值设置的合理性
3. **定期调整**: 根据市场条件和交易表现定期调整阈值
4. **监控日志**: 密切关注回撤监控的日志输出，了解触发频率和效果
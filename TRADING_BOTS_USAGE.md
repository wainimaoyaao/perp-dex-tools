# 交易机器人启动脚本使用说明

## 概述

现在每个交易所都有独立的启动脚本，可以单独配置和管理。这样更灵活，便于调整不同交易所的参数。

## 文件结构

```
├── scripts/                # 脚本文件夹
│   ├── bot_configs.sh      # 配置文件 - 存储所有交易所的参数
│   ├── start_bots.sh       # 主启动脚本 - 启动所有交易所
│   ├── start_paradex.sh    # Paradex 独立启动脚本
│   ├── start_grvt.sh       # GRVT 独立启动脚本
│   ├── stop_bots.sh        # 主停止脚本
│   ├── stop_paradex.sh     # Paradex 独立停止脚本
│   ├── stop_grvt.sh        # GRVT 独立停止脚本
│   ├── check_bots.sh       # 主检查脚本
│   ├── check_paradex.sh    # Paradex 独立检查脚本
│   └── check_grvt.sh       # GRVT 独立检查脚本
```

## 配置参数

在 `bot_configs.sh` 文件中，每个交易所都有独立的配置：

### Paradex 配置
- `PARADEX_TICKER="BTC"`                        # 交易标的
- `PARADEX_QUANTITY="0.002"`                    # 订单数量
- `PARADEX_TAKE_PROFIT="0.005"`                 # 止盈百分比
- `PARADEX_DIRECTION="buy"`                     # 交易方向 (buy/sell)
- `PARADEX_MAX_ORDERS="20"`                     # 最大订单数
- `PARADEX_WAIT_TIME="450"`                     # 等待时间(秒)
- `PARADEX_GRID_STEP="0.1"`                     # 网格步长百分比
- `PARADEX_STOP_PRICE="-1"`                     # 停止价格 (-1表示不启用)
- `PARADEX_PAUSE_PRICE="-1"`                    # 暂停价格 (-1表示不启用)
- `PARADEX_ASTER_BOOST="false"`                 # Aster加速模式
- `PARADEX_ENV_PATH="./para_env"`               # 虚拟环境路径
- `PARADEX_ENV_FILE=".env"`                     # 环境变量文件
- `PARADEX_LOG_FILE="paradex_output.log"`       # 日志文件
- `PARADEX_ENABLE_DRAWDOWN_MONITOR="true"`      # 启用回撤监控
- `PARADEX_DRAWDOWN_LIGHT_THRESHOLD="5"`        # 轻度回撤阈值(%)
- `PARADEX_DRAWDOWN_MEDIUM_THRESHOLD="8"`       # 中度回撤阈值(%)
- `PARADEX_DRAWDOWN_SEVERE_THRESHOLD="12"`      # 严重回撤阈值(%)

### GRVT 配置
- `GRVT_TICKER="BTC"`                           # 交易标的
- `GRVT_QUANTITY="0.001"`                       # 订单数量 (不同于 Paradex)
- `GRVT_TAKE_PROFIT="0.008"`                    # 止盈百分比 (不同于 Paradex)
- `GRVT_DIRECTION="buy"`                        # 交易方向 (buy/sell)
- `GRVT_MAX_ORDERS="15"`                        # 最大订单数 (不同于 Paradex)
- `GRVT_WAIT_TIME="300"`                        # 等待时间(秒) (不同于 Paradex)
- `GRVT_GRID_STEP="0.15"`                       # 网格步长百分比 (不同于 Paradex)
- `GRVT_STOP_PRICE="-1"`                        # 停止价格 (-1表示不启用)
- `GRVT_PAUSE_PRICE="-1"`                       # 暂停价格 (-1表示不启用)
- `GRVT_ASTER_BOOST="false"`                    # Aster加速模式
- `GRVT_ENV_PATH="./env"`                       # 虚拟环境路径
- `GRVT_ENV_FILE=".env"`                        # 环境变量文件
- `GRVT_LOG_FILE="grvt_output.log"`             # 日志文件
- `GRVT_ENABLE_DRAWDOWN_MONITOR="true"`         # 启用回撤监控
- `GRVT_DRAWDOWN_LIGHT_THRESHOLD="5"`           # 轻度回撤阈值(%)
- `GRVT_DRAWDOWN_MEDIUM_THRESHOLD="8"`          # 中度回撤阈值(%)
- `GRVT_DRAWDOWN_SEVERE_THRESHOLD="12"`         # 严重回撤阈值(%)

## 使用方法

### 1. 启动所有机器人
```bash
./scripts/start_bots.sh
```

### 2. 启动单个机器人
```bash
# 只启动 Paradex
./scripts/start_paradex.sh

# 只启动 GRVT
./scripts/start_grvt.sh
```

### 3. 修改配置
```bash
# 编辑配置文件
nano scripts/bot_configs.sh

# 修改后重启对应的机器人
./scripts/start_paradex.sh  # 如果修改了 Paradex 配置
./scripts/start_grvt.sh     # 如果修改了 GRVT 配置
```

### 4. 停止机器人
```bash
# 停止所有机器人
./scripts/stop_bots.sh

# 停止单个机器人
./scripts/stop_paradex.sh   # 只停止 Paradex
./scripts/stop_grvt.sh      # 只停止 GRVT

# 使用主脚本的参数方式停止单个机器人
./scripts/stop_bots.sh --paradex    # 只停止 Paradex
./scripts/stop_bots.sh --grvt       # 只停止 GRVT

# 查看停止脚本帮助
./scripts/stop_bots.sh --help
```

### 5. 监控和管理

#### 状态检查
```bash
# 检查所有机器人状态
./scripts/check_bots.sh

# 检查单个机器人状态
./scripts/check_paradex.sh     # 只检查 Paradex
./scripts/check_grvt.sh        # 只检查 GRVT

# 使用主脚本的参数方式检查单个机器人
./scripts/check_bots.sh --paradex    # 只检查 Paradex
./scripts/check_bots.sh --grvt       # 只检查 GRVT

# 查看检查脚本帮助
./scripts/check_bots.sh --help
```

#### 日志监控
```bash
# 查看日志
tail -f paradex_output.log
tail -f grvt_output.log

# 同时查看两个日志
tail -f paradex_output.log grvt_output.log

# 查看停止操作日志
tail -f stop_bots.log
tail -f stop_paradex.log
tail -f stop_grvt.log
```

## 停止功能详细说明

### 停止脚本类型

1. **主停止脚本**: `stop_bots.sh`
   - 默认停止所有交易机器人
   - 支持参数化停止单个交易所
   - 包含完整的止损检查和安全停止逻辑

2. **独立停止脚本**: `stop_paradex.sh`, `stop_grvt.sh`
   - 专门停止对应交易所的机器人
   - 轻量化设计，快速执行
   - 包含基本的安全检查

### 停止方式对比

| 停止方式 | 命令 | 特点 | 适用场景 |
|---------|------|------|----------|
| 停止所有 | `./scripts/stop_bots.sh` | 完整的安全检查 | 日常维护 |
| 参数化停止 | `./scripts/stop_bots.sh --paradex` | 调用独立脚本 | 快速操作 |
| 独立停止 | `./scripts/stop_paradex.sh` | 直接执行 | 紧急停止 |

### 安全特性

- **止损检查**: 检测是否有正在执行的止损操作
- **优雅停止**: 先发送 SIGTERM 信号，等待进程自然退出
- **强制终止**: 超时后使用 SIGKILL 强制终止
- **进程验证**: 确认进程完全停止
- **文件清理**: 清理 PID 文件和临时文件
- **日志记录**: 详细记录停止过程

### 故障排除

如果停止失败，可以尝试：

```bash
# 1. 查看进程状态
ps aux | grep runbot.py

# 2. 强制终止所有相关进程
pkill -9 -f runbot.py

# 3. 清理 PID 文件
rm -f *.pid

# 4. 检查日志文件
grep -i error stop_*.log
```

## 检查功能详细说明

### 检查脚本类型

1. **主检查脚本**: `check_bots.sh`
   - 默认检查所有交易机器人状态
   - 支持参数化检查单个交易所
   - 包含完整的系统资源和网络检查
   - 提供详细的问题诊断和建议

2. **独立检查脚本**: `check_paradex.sh`, `check_grvt.sh`
   - 专门检查对应交易所的机器人
   - 针对性强，检查更深入
   - 包含交易所特定的配置和状态检查

### 检查方式对比

| 检查方式 | 命令 | 特点 | 适用场景 |
|---------|------|------|----------|
| 检查所有 | `./scripts/check_bots.sh` | 全面系统检查 | 日常监控 |
| 参数化检查 | `./scripts/check_bots.sh --paradex` | 调用独立脚本 | 快速检查 |
| 独立检查 | `./scripts/check_paradex.sh` | 深度专项检查 | 问题诊断 |

### 检查内容

#### 通用检查项目
- **进程状态**: 检查机器人进程是否正在运行
- **PID 文件**: 验证 PID 文件的有效性
- **日志文件**: 分析日志大小、错误和活跃度
- **配置文件**: 验证环境文件和配置参数
- **虚拟环境**: 检查 Python 环境和依赖

#### 独立检查额外项目
- **交易所特定配置**: 详细显示当前交易参数
- **回撤监控状态**: 检查止损和风险控制
- **进程详细信息**: CPU、内存使用率和运行时间
- **错误分析**: 最近错误的详细分析
- **快捷操作提示**: 针对性的操作建议

### 检查功能特性

- **问题分级**: 将问题分为严重、警告和信息三个级别
- **实时状态**: 显示当前的运行状态和资源使用
- **安全检查**: 验证配置文件权限和敏感信息保护
- **性能监控**: 检查系统资源使用情况
- **网络检测**: 验证网络连接状态
- **智能建议**: 根据检查结果提供操作建议

### 故障排除

如果检查发现问题，可以参考：

```bash
# 1. 查看详细错误信息
./scripts/check_paradex.sh  # 或 ./scripts/check_grvt.sh

# 2. 检查日志文件中的错误
grep -i error paradex_output.log | tail -10
grep -i error grvt_output.log | tail -10

# 3. 验证配置文件
cat .env | grep -v "^#" | grep -v "^$"

# 4. 重启有问题的机器人
./scripts/stop_paradex.sh && ./scripts/start_paradex.sh
./scripts/stop_grvt.sh && ./scripts/start_grvt.sh

# 5. 清理过期文件
rm -f .*.pid
```

## 优势

1. **独立配置**: 每个交易所可以有不同的交易参数
2. **灵活管理**: 可以单独启动/停止某个交易所的机器人
3. **易于扩展**: 添加新交易所只需创建新的配置和启动脚本
4. **配置集中**: 所有参数都在 `bot_configs.sh` 中统一管理

## 添加新交易所

1. 在 `scripts/bot_configs.sh` 中添加新交易所的配置
2. 创建新的启动脚本（参考 `scripts/start_paradex.sh`）
3. 在 `scripts/start_bots.sh` 中添加对新脚本的调用

## 注意事项

- 修改配置后需要重启对应的机器人才能生效
- 每个交易所使用不同的虚拟环境和日志文件
- 确保 `.env` 文件中包含所有交易所的 API 配置
# 参数映射关联说明

## 概述
本文档详细说明了 `bot_configs.sh` 中的配置变量如何映射到 `runbot.py` 的命令行参数。

## 参数映射表

### Paradex 交易所参数映射

| bot_configs.sh 变量 | runbot.py 命令行参数 | 当前值 | 说明 |
|---|---|---|---|
| `PARADEX_TICKER` | `--ticker` | `"BTC"` | 交易标的符号 |
| `PARADEX_QUANTITY` | `--quantity` | `"0.002"` | 每次订单数量 |
| `PARADEX_TAKE_PROFIT` | `--take-profit` | `"0.005"` | 止盈百分比 |
| `PARADEX_DIRECTION` | `--direction` | `"buy"` | 交易方向 (buy/sell) |
| `PARADEX_MAX_ORDERS` | `--max-orders` | `"20"` | 最大订单数量 |
| `PARADEX_WAIT_TIME` | `--wait-time` | `"450"` | 订单间等待时间(秒) |
| `PARADEX_GRID_STEP` | `--grid-step` | `"0.1"` | 网格步长百分比 |
| `PARADEX_STOP_PRICE` | `--stop-price` | `"-1"` | 停止价格 (-1表示禁用) |
| `PARADEX_PAUSE_PRICE` | `--pause-price` | `"-1"` | 暂停价格 (-1表示禁用) |
| `PARADEX_ASTER_BOOST` | `--aster-boost` | `"false"` | 是否启用Aster加速 |
| `PARADEX_ENV_FILE` | `--env-file` | `".env"` | 环境变量文件路径 |
| `PARADEX_ENABLE_DRAWDOWN_MONITOR` | `--enable-drawdown-monitor` | `"true"` | 是否启用回撤监控 |
| `PARADEX_DRAWDOWN_LIGHT_THRESHOLD` | `--drawdown-light-threshold` | `"5"` | 轻度回撤阈值(%) |
| `PARADEX_DRAWDOWN_MEDIUM_THRESHOLD` | `--drawdown-medium-threshold` | `"8"` | 中度回撤阈值(%) |
| `PARADEX_DRAWDOWN_SEVERE_THRESHOLD` | `--drawdown-severe-threshold` | `"12"` | 严重回撤阈值(%) |

### GRVT 交易所参数映射

| bot_configs.sh 变量 | runbot.py 命令行参数 | 当前值 | 说明 |
|---|---|---|---|
| `GRVT_TICKER` | `--ticker` | `"BTC"` | 交易标的符号 |
| `GRVT_QUANTITY` | `--quantity` | `"0.002"` | 每次订单数量 |
| `GRVT_TAKE_PROFIT` | `--take-profit` | `"0.005"` | 止盈百分比 |
| `GRVT_DIRECTION` | `--direction` | `"buy"` | 交易方向 (buy/sell) |
| `GRVT_MAX_ORDERS` | `--max-orders` | `"20"` | 最大订单数量 |
| `GRVT_WAIT_TIME` | `--wait-time` | `"450"` | 订单间等待时间(秒) |
| `GRVT_GRID_STEP` | `--grid-step` | `"0.1"` | 网格步长百分比 |
| `GRVT_STOP_PRICE` | `--stop-price` | `"-1"` | 停止价格 (-1表示禁用) |
| `GRVT_PAUSE_PRICE` | `--pause-price` | `"-1"` | 暂停价格 (-1表示禁用) |
| `GRVT_ASTER_BOOST` | `--aster-boost` | `"false"` | 是否启用Aster加速 |
| `GRVT_ENV_FILE` | `--env-file` | `".env"` | 环境变量文件路径 |
| `GRVT_ENABLE_DRAWDOWN_MONITOR` | `--enable-drawdown-monitor` | `"true"` | 是否启用回撤监控 |
| `GRVT_DRAWDOWN_LIGHT_THRESHOLD` | `--drawdown-light-threshold` | `"5"` | 轻度回撤阈值(%) |
| `GRVT_DRAWDOWN_MEDIUM_THRESHOLD` | `--drawdown-medium-threshold` | `"8"` | 中度回撤阈值(%) |
| `GRVT_DRAWDOWN_SEVERE_THRESHOLD` | `--drawdown-severe-threshold` | `"12"` | 严重回撤阈值(%) |

## 实际映射示例

### 1. 配置文件中的变量定义 (bot_configs.sh)
```bash
# Paradex 配置
PARADEX_TICKER="BTC"
PARADEX_QUANTITY="0.002"
PARADEX_TAKE_PROFIT="0.005"
PARADEX_DIRECTION="buy"
```

### 2. 启动脚本中的映射使用 (start_paradex.sh)
```bash
# 构建启动命令
START_CMD="python3 runbot.py \
  --exchange paradex \
  --ticker $PARADEX_TICKER \
  --quantity $PARADEX_QUANTITY \
  --take-profit $PARADEX_TAKE_PROFIT \
  --direction $PARADEX_DIRECTION \
  --max-orders $PARADEX_MAX_ORDERS \
  --wait-time $PARADEX_WAIT_TIME \
  --grid-step $PARADEX_GRID_STEP \
  --stop-price $PARADEX_STOP_PRICE \
  --pause-price $PARADEX_PAUSE_PRICE \
  --env-file $PARADEX_ENV_FILE"
```

### 3. 最终执行的命令
```bash
python3 runbot.py \
  --exchange paradex \
  --ticker BTC \
  --quantity 0.002 \
  --take-profit 0.005 \
  --direction buy \
  --max-orders 20 \
  --wait-time 450 \
  --grid-step 0.1 \
  --stop-price -1 \
  --pause-price -1 \
  --env-file .env
```

## 特殊参数处理

### 布尔类型参数
某些参数是布尔类型，在启动脚本中有特殊处理：

```bash
# Aster Boost 参数
if [ "$PARADEX_ASTER_BOOST" = "true" ]; then
    START_CMD="$START_CMD --aster-boost"
fi

# 回撤监控参数
if [ "$PARADEX_ENABLE_DRAWDOWN_MONITOR" = "true" ]; then
    START_CMD="$START_CMD --enable-drawdown-monitor \
      --drawdown-light-threshold $PARADEX_DRAWDOWN_LIGHT_THRESHOLD \
      --drawdown-medium-threshold $PARADEX_DRAWDOWN_MEDIUM_THRESHOLD \
      --drawdown-severe-threshold $PARADEX_DRAWDOWN_SEVERE_THRESHOLD"
fi
```

## 如何验证映射关系

1. **查看配置文件**：
   ```bash
   cat bot_configs.sh
   ```

2. **查看启动脚本**：
   ```bash
   cat start_paradex.sh | grep "START_CMD"
   ```

3. **测试参数展开**：
   ```bash
   source bot_configs.sh
   echo "PARADEX_TICKER=$PARADEX_TICKER"
   echo "映射为: --ticker $PARADEX_TICKER"
   ```

## 修改配置的影响

当您修改 `bot_configs.sh` 中的任何变量时，下次启动机器人时，这些新值会自动传递给 `runbot.py`，无需修改启动脚本。

例如，如果您将：
```bash
PARADEX_QUANTITY="0.002"
```
改为：
```bash
PARADEX_QUANTITY="0.005"
```

下次启动时，实际执行的命令会变成：
```bash
python3 runbot.py --exchange paradex --ticker BTC --quantity 0.005 ...
```
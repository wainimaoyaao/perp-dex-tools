
**English speakers**: Please read README_EN.md for the English version of this documentation.

## 📢 分享说明

**欢迎分享本项目！** 如果您要分享或修改此代码，请务必包含对原始仓库的引用。我们鼓励开源社区的发展，但请保持对原作者工作的尊重和认可。

---

## 自动交易机器人

一个支持多个交易所（目前包括 EdgeX, Backpack, Paradex, Aster, Lighter, GRVT）的模块化交易机器人。该机器人实现了自动下单并在盈利时自动平仓的策略，主要目的是取得高交易量。



## 安装

Python 版本要求（最佳选项是 Python 3.10 - 3.12）：
 - grvt要求python版本在 3.10 及以上
 - Paradex要求python版本在 3.9 - 3.12
 - 其他交易所需要python版本在 3.8 及以上


1. **克隆仓库**：

   ```bash
   git clone <repository-url>
   cd perp-dex-tools
   ```

2. **创建并激活虚拟环境**：

   首先确保你目前不在任何虚拟环境中：

   ```bash
   deactivate
   ```

   创建虚拟环境：

   ```bash
   python3 -m venv env
   ```

   激活虚拟环境（每次使用脚本时，都需要激活虚拟环境）：

   ```bash
   source env/bin/activate  # Windows: env\Scripts\activate
   ```

3. **安装依赖**：
   首先确保你目前不在任何虚拟环境中：

   ```bash
   deactivate
   ```

   激活虚拟环境（每次使用脚本时，都需要激活虚拟环境）：

   ```bash
   source env/bin/activate  # Windows: env\Scripts\activate
   ```

   ```bash
   pip install -r requirements.txt
   ```

   **grvt 用户**：如果您想使用 grvt 交易所，需要额外安装grvt专用依赖：
   激活虚拟环境（每次使用脚本时，都需要激活虚拟环境）：

   ```bash
   source env/bin/activate  # Windows: env\Scripts\activate
   ```

   ```bash
   pip install grvt-pysdk
   ```

   **Paradex 用户**：如果您想使用 Paradex 交易所，需要额外创建一个虚拟环境并安装 Paradex 专用依赖：

   首先确保你目前不在任何虚拟环境中：

   ```bash
   deactivate
   ```

   创建 Paradex 专用的虚拟环境（名称为 para_env）：

   ```bash
   python3 -m venv para_env
   ```

   激活虚拟环境（每次使用脚本时，都需要激活虚拟环境）：

   ```bash
   source para_env/bin/activate  # Windows: para_env\Scripts\activate
   ```

   安装 Paradex 依赖

   ```bash
   pip install -r para_requirements.txt
   ```

4. **设置环境变量**：
   在项目根目录创建`.env`文件，并使用 env_example.txt 作为样本，修改为你的 api 密匙。

5. **Telegram 机器人设置（可选）**：
   如需接收交易通知，请参考 [Telegram 机器人设置指南](docs/telegram-bot-setup.md) 配置 Telegram 机器人。

## 策略概述

**重要提醒**：大家一定要先理解了这个脚本的逻辑和风险，这样你就能设置更适合你自己的参数，或者你也可能觉得这不是一个好策略，根本不想用这个策略来刷交易量。我在推特也说过，我不是为了分享而写这些脚本，而是我真的在用这个脚本，所以才写了，然后才顺便分享出来。
这个脚本主要还是要看长期下来的磨损，只要脚本持续开单，如果一个月后价格到你被套的最高点，那么你这一个月的交易量就都是零磨损的了。所以我认为如果把`--quantity`和`--wait-time`设置的太小，并不是一个好的长期的策略，但确实适合短期内高强度冲交易量。我自己一般用 40 到 60 的 quantity，450 到 650 的 wait-time，以此来保证即使市场和你的判断想法，脚本依然能够持续稳定地下单，直到价格回到你的开单点，实现零磨损刷了交易量。

该机器人实现了简单的交易策略：

1. **订单下单**：在市场价格附近下限价单
2. **订单监控**：等待订单成交
3. **平仓订单**：在止盈水平自动下平仓单
4. **持仓管理**：监控持仓和活跃订单
5. **风险管理**：限制最大并发订单数
6. **网格步长控制**：通过 `--grid-step` 参数控制新订单与现有平仓订单之间的最小价格距离
7. **停止交易控制**：通过 `--stop-price` 参数控制停止交易的的价格条件

#### ⚙️ 关键参数

- **quantity**: 每笔订单的交易数量
- **take-profit**: 止盈百分比（如 0.02 表示 0.02%）
- **max-orders**: 最大同时活跃订单数（风险控制）
- **wait-time**: 订单间等待时间（避免过于频繁交易）
- **grid-step**: 网格步长控制（防止平仓订单过于密集）
- **stop-price**: 当市场价格达到该价格时退出脚本
- **pause-price**: 当市场价格达到该价格时暂停脚本

#### 网格步长功能详解

`--grid-step` 参数用于控制新订单的平仓价格与现有平仓订单之间的最小距离：

- **默认值 -100**：无网格步长限制，按原策略执行
- **正值（如 0.5）**：新订单的平仓价格必须与最近的平仓订单价格保持至少 0.5% 的距离
- **作用**：防止平仓订单过于密集，提高成交概率和风险管理

例如，当看多且 `--grid-step 0.5` 时：

- 如果现有平仓订单价格为 2000 USDT
- 新订单的平仓价格必须低于 1990 USDT（2000 × (1 - 0.5%)）
- 这样可以避免平仓订单过于接近，提高整体策略效果

#### 📊 交易流程示例

假设当前 ETH 价格为 $2000，设置止盈为 0.02%：

1. **开仓**：在 $2000.40 下买单（略高于市价）
2. **成交**：订单被市场成交，获得多头仓位
3. **平仓**：立即在 $2000.80 下卖单（止盈价格）
4. **完成**：平仓单成交，获得 0.02% 利润
5. **重复**：继续下一轮交易

#### 🛡️ 风险控制

- **订单限制**：通过 `max-orders` 限制最大并发订单数
- **网格控制**：通过 `grid-step` 确保平仓订单有合理间距
- **下单频率控制**：通过 `wait-time` 确保下单的时间间隔，防止短时间内被套
- **实时监控**：持续监控持仓和订单状态
- **回撤监控**：可选的智能回撤监控系统，提供多级风险预警和自动止损
- **⚠️ 基础策略无止损机制**：基础策略不包含止损功能，但可通过回撤监控功能实现风险管理

#### 📈 PnL 和保证金监控功能

机器人现在支持实时监控账户的盈亏（PnL）和保证金状态，提供更全面的风险管理：

##### 🔍 监控功能

- **账户余额监控**：实时获取账户可用余额
- **账户权益监控**：监控账户总权益（包括未实现盈亏）
- **未实现盈亏计算**：实时计算所有持仓的未实现盈亏
- **保证金使用监控**：监控初始保证金使用情况
- **持仓损失评估**：计算当前持仓的潜在损失

##### 🎯 支持的交易所

目前 PnL 和保证金监控功能支持以下交易所：

- **Paradex**：完整支持所有 PnL 和保证金监控功能
- **其他交易所**：正在逐步添加支持

##### 📊 监控数据

机器人会定期记录以下关键指标：

- **账户余额**：当前可用于交易的资金
- **账户权益**：账户总价值（余额 + 未实现盈亏）
- **未实现盈亏**：所有开仓位的浮动盈亏
- **初始保证金**：维持当前仓位所需的保证金
- **持仓损失**：当前持仓的潜在损失金额

##### ⚠️ 风险管理增强

- **实时风险评估**：基于 PnL 数据进行风险评估
- **保证金监控**：防止保证金不足导致的强制平仓
- **损失预警**：当持仓损失超过预设阈值时提供预警
- **数据记录**：所有 PnL 和保证金数据都会记录到日志中

#### 📉 回撤监控功能

机器人现在支持智能回撤监控系统，提供多级风险预警和自动止损功能：

##### 🎯 监控级别

- **轻微回撤（默认 5%）**：发送通知提醒，继续正常交易
- **中等回撤（默认 8%）**：暂停新订单，仅允许平仓操作
- **严重回撤（默认 12%）**：立即停止所有交易，触发自动止损

##### ⚙️ 配置参数

- `--enable-drawdown-monitor`: 启用回撤监控功能
- `--drawdown-light-threshold`: 轻微回撤阈值（默认 5.0%）
- `--drawdown-medium-threshold`: 中等回撤阈值（默认 8.0%）
- `--drawdown-severe-threshold`: 严重回撤阈值（默认 12.0%）

##### 🔄 工作原理

1. **会话初始化**：交易开始时记录初始净值作为基准
2. **实时监控**：持续获取账户净值，计算相对于会话峰值的回撤百分比
3. **智能平滑**：使用移动平均算法减少净值波动的误报
4. **分级响应**：根据回撤程度采取不同的风险管理措施
5. **自动恢复**：当回撤水平降低时，自动恢复正常交易

##### 📊 监控数据

- **会话峰值净值**：交易会话中达到的最高净值
- **当前净值**：实时账户净值
- **回撤百分比**：(峰值净值 - 当前净值) / 峰值净值 × 100%
- **平滑净值**：经过移动平均处理的净值，减少噪音

##### 🚨 风险管理增强

- **实时通知**：通过 Telegram/Lark 发送回撤警报
- **自动止损**：严重回撤时自动停止交易
- **渐进式响应**：根据回撤严重程度采取不同措施
- **会话重置**：每次启动交易时重新计算基准净值

## 示例命令：

### EdgeX 交易所：

ETH：

```bash
python runbot.py --exchange edgex --ticker ETH --quantity 0.1 --take-profit 0.02 --max-orders 40 --wait-time 450
```

ETH（带网格步长控制）：

```bash
python runbot.py --exchange edgex --ticker ETH --quantity 0.1 --take-profit 0.02 --max-orders 40 --wait-time 450 --grid-step 0.5
```

ETH（带停止交易的价格控制）：

```bash
python runbot.py --exchange edgex --ticker ETH --quantity 0.1 --take-profit 0.02 --max-orders 40 --wait-time 450 --stop-price 5500
```

BTC：

```bash
python runbot.py --exchange edgex --ticker BTC --quantity 0.05 --take-profit 0.02 --max-orders 40 --wait-time 450
```

### Backpack 交易所：

ETH 永续合约：

```bash
python runbot.py --exchange backpack --ticker ETH --quantity 0.1 --take-profit 0.02 --max-orders 40 --wait-time 450
```

ETH 永续合约（带网格步长控制）：

```bash
python runbot.py --exchange backpack --ticker ETH --quantity 0.1 --take-profit 0.02 --max-orders 40 --wait-time 450 --grid-step 0.3
```

### Aster 交易所：

ETH：

```bash
python runbot.py --exchange aster --ticker ETH --quantity 0.1 --take-profit 0.02 --max-orders 40 --wait-time 450
```

ETH（启用 Boost 模式）：

```bash
python runbot.py --exchange aster --ticker ETH --direction buy --quantity 0.1 --aster-boost
```

### GRVT 交易所：

BTC：

```bash
python runbot.py --exchange grvt --ticker BTC --quantity 0.05 --take-profit 0.02 --max-orders 40 --wait-time 450
```

### 回撤监控详细使用指南：

#### 📋 可用参数

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `--enable-drawdown-monitor` | flag | False | 启用回撤监控功能 |
| `--drawdown-light-threshold` | Decimal | 5 | 轻微回撤警告阈值 (%) |
| `--drawdown-medium-threshold` | Decimal | 8 | 中等回撤警告阈值 (%) |
| `--drawdown-severe-threshold` | Decimal | 12 | 严重回撤止损阈值 (%) |

#### 💡 使用示例

##### 1. 使用默认阈值启用回撤监控
```bash
python runbot.py --exchange edgex --ticker ETH --quantity 0.1 --take-profit 0.02 --enable-drawdown-monitor
```
- 轻微回撤: 5%
- 中等回撤: 8%
- 严重回撤: 12%

##### 2. 保守策略 - 较低的回撤阈值
```bash
python runbot.py --exchange edgex --ticker ETH --quantity 0.1 --take-profit 0.02 --enable-drawdown-monitor \
  --drawdown-light-threshold 3.0 \
  --drawdown-medium-threshold 5.0 \
  --drawdown-severe-threshold 8.0
```
适用于风险厌恶型交易者，更早触发保护机制。

##### 3. 激进策略 - 较高的回撤阈值
```bash
python runbot.py --exchange backpack --ticker ETH --quantity 0.1 --take-profit 0.02 --enable-drawdown-monitor \
  --drawdown-light-threshold 8.0 \
  --drawdown-medium-threshold 12.0 \
  --drawdown-severe-threshold 18.0
```
适用于风险承受能力较强的交易者，允许更大的回撤。

##### 4. 完整的交易配置示例
```bash
python runbot.py \
  --exchange edgex \
  --ticker BTC \
  --quantity 0.05 \
  --direction buy \
  --max-orders 40 \
  --wait-time 450 \
  --enable-drawdown-monitor \
  --drawdown-light-threshold 4.0 \
  --drawdown-medium-threshold 7.0 \
  --drawdown-severe-threshold 10.0
```

#### 🎯 监控行为详解

##### 轻微回撤 (Light Drawdown)
- **触发条件**: 当前净值相对于会话峰值的回撤达到轻微阈值
- **行为**: 记录警告日志并发送通知，交易继续正常进行
- **通知内容**: 包含当前净值、峰值净值、回撤百分比等信息

##### 中等回撤 (Medium Drawdown)
- **触发条件**: 回撤达到中等阈值
- **行为**: 暂停新订单的创建，仅允许现有仓位的平仓操作
- **恢复**: 当回撤降低到中等阈值以下时，自动恢复正常交易

##### 严重回撤 (Severe Drawdown)
- **触发条件**: 回撤达到严重阈值
- **行为**: 立即停止所有交易活动并优雅退出程序
- **不可恢复**: 需要手动重启程序才能继续交易

#### ⚠️ 注意事项

1. **阈值顺序**: 必须满足 `light < medium < severe` 的关系
2. **实时监控**: 回撤监控在主交易循环中实时进行
3. **净值计算**: 基于交易所账户的实际净值进行计算
4. **会话峰值**: 每次启动程序时重新计算会话峰值
5. **通知系统**: 支持 Telegram 和 Lark 通知（需要配置相应的 bot）

#### 🏆 最佳实践

1. **首次使用**: 建议从保守的阈值开始，逐步调整到适合的水平
2. **回测验证**: 在实盘使用前，建议通过历史数据验证阈值设置的合理性
3. **定期调整**: 根据市场条件和交易表现定期调整阈值
4. **监控日志**: 密切关注回撤监控的日志输出，了解触发频率和效果

## 配置

### 环境变量

#### 通用配置

- `ACCOUNT_NAME`: 环境变量中当前账号的名称，用于多账号日志区分，可自定义，非必须

#### Telegram 配置（可选）

- `TELEGRAM_BOT_TOKEN`: Telegram 机器人令牌
- `TELEGRAM_CHAT_ID`: Telegram 对话 ID

#### EdgeX 配置

- `EDGEX_ACCOUNT_ID`: 您的 EdgeX 账户 ID
- `EDGEX_STARK_PRIVATE_KEY`: 您的 EdgeX API 私钥
- `EDGEX_BASE_URL`: EdgeX API 基础 URL（默认：https://pro.edgex.exchange）
- `EDGEX_WS_URL`: EdgeX WebSocket URL（默认：wss://quote.edgex.exchange）

#### Backpack 配置

- `BACKPACK_PUBLIC_KEY`: 您的 Backpack API Key
- `BACKPACK_SECRET_KEY`: 您的 Backpack API Secret

#### Paradex 配置

- `PARADEX_L1_ADDRESS`: L1 钱包地址
- `PARADEX_L2_PRIVATE_KEY`: L2 钱包私钥（点击头像，钱包，"复制 paradex 私钥"）

#### Aster 配置

- `ASTER_API_KEY`: 您的 Aster API Key
- `ASTER_SECRET_KEY`: 您的 Aster API Secret

#### Lighter 配置

- `API_KEY_PRIVATE_KEY`: Lighter API 私钥
- `LIGHTER_ACCOUNT_INDEX`: Lighter 账户索引
- `LIGHTER_API_KEY_INDEX`: Lighter API 密钥索引

#### GRVT 配置

- `GRVT_TRADING_ACCOUNT_ID`: 您的 GRVT 交易账户 ID
- `GRVT_PRIVATE_KEY`: 您的 GRVT 私钥
- `GRVT_API_KEY`: 您的 GRVT API 密钥

**获取 LIGHTER_ACCOUNT_INDEX 的方法**：

1. 在下面的网址最后加上你的钱包地址：

   ```
   https://mainnet.zklighter.elliot.ai/api/v1/account?by=l1_address&value=
   ```

2. 在浏览器中打开这个网址

3. 在结果中搜索 "account_index" - 如果你有子账户，会有多个 account_index，短的那个是你主账户的，长的是你的子账户。

### 命令行参数

- `--exchange`: 使用的交易所：'edgex'、'backpack'、'paradex'、'aster'、'lighter'或'grvt'（默认：edgex）
- `--ticker`: 标的资产符号（例如：ETH、BTC、SOL）。合约 ID 自动解析。
- `--quantity`: 订单数量（默认：0.1）
- `--take-profit`: 止盈百分比（例如 0.02 表示 0.02%）
- `--direction`: 交易方向：'buy'或'sell'（默认：buy）
- `--env-file`: 账户配置文件 (默认：.env)
- `--max-orders`: 最大活跃订单数（默认：40）
- `--wait-time`: 订单间等待时间（秒）（默认：450）
- `--grid-step`: 与下一个平仓订单价格的最小距离百分比（默认：-100，表示无限制）
- `--stop-price`: 当 `direction` 是 'buy' 时，当 price >= stop-price 时停止交易并退出程序；'sell' 逻辑相反（默认：-1，表示不会因为价格原因停止交易），参数的目的是防止订单被挂在”你认为的开多高点或开空低点“。
- `--pause-price`: 当 `direction` 是 'buy' 时，当 price >= pause-price 时暂停交易，并在价格回到 pause-price 以下时重新开始交易；'sell' 逻辑相反（默认：-1，表示不会因为价格原因停止交易），参数的目的是防止订单被挂在”你认为的开多高点或开空低点“。
- `--aster-boost`: 启用 Aster 交易所的 Boost 模式进行交易量提升（仅适用于 aster 交易所）
- `--enable-drawdown-monitor`: 启用回撤监控功能（可选）
- `--drawdown-light-threshold`: 轻微回撤阈值，百分比（默认 5.0）
- `--drawdown-medium-threshold`: 中等回撤阈值，百分比（默认 8.0）
- `--drawdown-severe-threshold`: 严重回撤阈值，百分比（默认 12.0）
  `--aster-boost` 的下单逻辑：下 maker 单开仓，成交后立即用 taker 单关仓，以此循环。磨损为一单 maker，一单 taker 的手续费，以及滑点。

## 日志记录

该机器人提供全面的日志记录：

- **交易日志**：包含订单详情的 CSV 文件
- **调试日志**：带时间戳的详细活动日志
- **控制台输出**：实时状态更新
- **错误处理**：全面的错误日志记录和处理

## Q & A

### 如何在同一设备配置同一交易所的多个账号？

1. 为每个账户创建一个 .env 文件，如 account_1.env, account_2.env
2. 在每个账户的 .env 文件中设置 `ACCOUNT_NAME=`, 如`ACCOUNT_NAME=MAIN`。
3. 在每个文件中配置好每个账户的 API key 或是密匙
4. 通过更改命令行中的 `--env-file` 参数来开始不同的账户，如 `python runbot.py --env-file account_1.env [其他参数...]`

### 如何在同一设备配置不同交易所的多个账号？

将不同交易所的账号都配置在同一 `.env` 文件后，通过更改命令行中的 `--exchange` 参数来开始不同的交易所，如 `python runbot.py --exchange backpack [其他参数...]`

### 如何在同一设备用同一账号配置同一交易所的多个合约？

将账号配置在 `.env` 文件后，通过更改命令行中的 `--ticker` 参数来开始不同的合约，如 `python runbot.py --ticker ETH [其他参数...]`

## 贡献

1. Fork 仓库
2. 创建功能分支
3. 进行更改
4. 如适用，添加测试
5. 提交拉取请求

## 许可证

本项目采用非商业许可证 - 详情请参阅[LICENSE](LICENSE)文件。

**重要提醒**：本软件仅供个人学习和研究使用，严禁用于任何商业用途。如需商业使用，请联系作者获取商业许可证。

## 免责声明

本软件仅供教育和研究目的。加密货币交易涉及重大风险，可能导致重大财务损失。使用风险自负，切勿用您无法承受损失的资金进行交易。


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
8. **🛡️ 智能止损系统**：集成多层次止损保护机制
   - **价格止损**：基于 `--stop-price` 参数的价格触发止损
   - **回撤止损**：基于回撤监控的自动止损保护
   - **智能执行**：使用 bid1/ask1 价格的智能止损订单执行
   - **重试机制**：包含完整的重试和错误恢复机制

#### ⚙️ 关键参数

- **quantity**: 每笔订单的交易数量
- **take-profit**: 止盈百分比（如 0.02 表示 0.02%）
- **max-orders**: 最大同时活跃订单数（风险控制）
- **wait-time**: 订单间等待时间（避免过于频繁交易）
- **grid-step**: 网格步长控制（防止平仓订单过于密集）
- **stop-price**: 价格止损触发点，当市场价格达到该价格时退出脚本并执行止损
- **drawdown-severe-threshold**: 严重回撤止损阈值（默认12%），触发自动止损保护
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
- **严重回撤（默认 12%）**：立即停止所有交易，触发智能自动止损系统

##### ⚙️ 配置参数

###### 基础监控参数
- `--enable-drawdown-monitor`: 启用回撤监控功能
- `--drawdown-light-threshold`: 轻微回撤阈值（默认 5.0%）
- `--drawdown-medium-threshold`: 中等回撤阈值（默认 8.0%）
- `--drawdown-severe-threshold`: 严重回撤阈值（默认 12.0%）

###### 缓存配置参数（高级选项）
- `cache_duration`: 缓存数据有效期，单位秒（默认 300秒/5分钟）
- `strict_mode`: 严格模式开关（默认 False）
  - `True`: 缓存过期时停止监控，等待网络恢复
  - `False`: 容错模式，缓存过期时继续使用并发出警告
- `enable_cache`: 启用缓存机制（默认 True，建议保持启用）

###### 模式选择说明
- **容错模式（推荐）**: 网络故障时使用缓存数据维持监控连续性，最大化保护效果
- **严格模式**: 确保数据绝对准确性，缓存过期时暂停监控直到网络恢复

##### 🔄 工作原理

1. **会话初始化**：交易开始时记录初始净值作为基准
2. **实时监控**：持续获取账户净值，计算相对于会话峰值的回撤百分比
3. **智能缓存**：每次成功获取净值时自动缓存，包含时间戳和验证信息
4. **故障检测**：智能识别网络异常、API限流等故障情况
5. **缓存回退**：故障时自动使用最近的有效缓存数据维持监控连续性
6. **智能平滑**：使用移动平均算法减少净值波动的误报
7. **分级响应**：根据回撤程度采取不同的风险管理措施
8. **自动恢复**：当回撤水平降低或网络恢复时，自动恢复正常交易

###### 💾 缓存工作流程

1. **数据获取**：尝试从交易所API获取实时净值数据
2. **成功缓存**：获取成功时，更新缓存并记录时间戳
3. **故障检测**：检测到网络异常、API错误或数据异常时触发缓存机制
4. **缓存验证**：检查缓存数据的有效性和时效性（默认5分钟）
5. **回退决策**：
   - 缓存有效：使用缓存数据继续监控
   - 缓存过期且严格模式：暂停监控直到网络恢复
   - 缓存过期且容错模式：使用过期缓存并发出警告
6. **恢复检测**：持续尝试获取实时数据，成功后立即切换回实时监控

##### 📊 监控数据

- **会话峰值净值**：交易会话中达到的最高净值
- **当前净值**：实时账户净值
- **回撤百分比**：(峰值净值 - 当前净值) / 峰值净值 × 100%
- **平滑净值**：经过移动平均处理的净值，减少噪音

##### 🚨 风险管理增强

- **实时通知**：通过 Telegram/Lark 发送回撤警报
- **智能自动止损**：严重回撤时触发多层次止损保护
  - **智能价格执行**：使用 bid1/ask1 价格确保最优成交
  - **持续监控机制**：5秒间隔监控订单状态直至完全成交
  - **重试保护**：包含完整的重试机制和错误恢复
  - **状态验证**：确认所有持仓完全平仓后才结束止损流程
- **渐进式响应**：根据回撤严重程度采取不同措施
- **会话重置**：每次启动交易时重新计算基准净值
- **异常处理集成**：集成了完整的异常处理机制，确保监控系统的稳定性
- **错误恢复**：在遇到临时性错误时自动恢复监控功能
- **数据验证**：严格的净值数据验证，防止异常数据影响监控准确性

##### 💾 智能缓存机制

机器人现在配备了先进的缓存系统，确保在网络故障或API异常时仍能维持回撤监控的连续性：

###### 🔄 网络故障缓存

- **自动缓存**：每次成功获取净值时自动缓存数据，包含时间戳和净值信息
- **故障检测**：智能检测网络连接问题、API限流、数据异常等故障情况
- **缓存回退**：当无法获取实时净值时，自动使用最近的有效缓存数据
- **时效性控制**：缓存数据有效期为5分钟，超时后会标记为过期
- **数据完整性**：严格验证缓存数据的有效性，确保监控准确性

###### ⚙️ 缓存配置选项

- **缓存有效期**：默认300秒（5分钟），可通过 `cache_duration` 参数调整
- **严格模式**：可选择启用严格模式，在缓存过期时停止监控而非继续使用过期数据
- **容错模式**：默认模式，在网络故障时使用缓存数据维持监控连续性

###### 🛡️ 故障保护机制

- **多层次回退**：实时数据 → 缓存数据 → 监控暂停（严格模式）
- **智能恢复**：网络恢复后自动切换回实时监控
- **状态透明**：详细记录缓存使用情况和故障恢复过程
- **性能优化**：缓存机制对正常交易性能影响微乎其微

###### 📊 缓存监控信息

- **缓存状态**：实时显示当前是否使用缓存数据
- **缓存时效**：显示缓存数据的时间戳和剩余有效期
- **故障统计**：记录网络故障次数和缓存使用频率
- **恢复日志**：详细记录故障检测和恢复过程

#### 🛡️ 异常处理与错误管理

机器人现在配备了全面的异常处理系统，提供强大的错误诊断和恢复能力：

##### 🎯 自定义异常体系

机器人实现了完整的自定义异常类体系，提供精确的错误分类和上下文信息：

- **DrawdownMonitorError**: 所有自定义异常的基类，提供统一的上下文信息存储
- **NetworthValidationError**: 净值验证异常，处理净值输入验证失败
- **StopLossExecutionError**: 止损执行异常，处理止损订单执行错误
- **OrderMonitoringError**: 订单监控异常，处理订单状态监控错误
- **APIRateLimitError**: API限流异常，处理API调用频率限制
- **NetworkConnectionError**: 网络连接异常，处理网络连接失败
- **DataIntegrityError**: 数据完整性异常，处理数据验证失败
- **ConfigurationError**: 配置错误异常，处理配置文件或参数错误

##### 🔍 错误诊断功能

- **详细上下文信息**：每个异常都包含丰富的上下文数据，便于问题定位
- **异常链追踪**：支持异常链，可以追踪错误的根本原因
- **结构化错误信息**：提供标准化的错误格式，便于日志分析
- **时间戳记录**：自动记录异常发生的精确时间

##### 🔧 错误恢复机制

- **优雅降级**：在遇到非致命错误时，系统会优雅降级而不是崩溃
- **自动重试**：对于临时性错误（如网络问题），系统会自动重试
- **状态保护**：确保在错误发生时交易状态的一致性
- **智能恢复**：根据错误类型采取相应的恢复策略

##### 📊 错误监控与报告

- **实时错误监控**：持续监控系统运行状态，及时发现异常
- **错误统计分析**：统计错误发生频率和类型，便于系统优化
- **详细错误日志**：记录完整的错误信息和调用栈
- **通知机制**：重要错误会通过 Telegram/Lark 发送通知

##### ⚡ 性能优化

- **高效异常处理**：优化的异常处理逻辑，最小化性能影响
- **内存管理**：合理的异常对象生命周期管理
- **日志优化**：智能的日志级别控制，避免日志洪水

## 🚀 脚本使用方法

本项目提供了便捷的脚本来管理交易机器人的启动、停止和状态检查。所有脚本都位于 `scripts/` 目录中，支持 Ubuntu/Linux/macOS 系统，并针对 `env` 和 `para_env` 虚拟环境进行了优化。

### 📁 脚本目录结构

所有管理脚本都已整理到 `scripts/` 目录中：
```
scripts/
├── bot_configs.sh      # 机器人配置文件
├── start_bots.sh       # 启动所有机器人
├── stop_bots.sh        # 停止所有机器人
├── check_bots.sh       # 检查所有机器人状态
├── start_paradex.sh    # 启动 Paradex 机器人
├── stop_paradex.sh     # 停止 Paradex 机器人
├── check_paradex.sh    # 检查 Paradex 机器人状态
├── start_grvt.sh       # 启动 GRVT 机器人
├── stop_grvt.sh        # 停止 GRVT 机器人
└── check_grvt.sh       # 检查 GRVT 机器人状态
```

### 📋 可用脚本

#### 1. `start_bots.sh` - 启动交易机器人

**功能特性：**
- 自动检查虚拟环境是否存在
- 同时启动 Paradex 和 GRVT 交易机器人
- 后台运行并生成独立的日志文件
- 显示进程 PID 便于管理
- 彩色输出提升用户体验

**使用方法：**
```bash
# 给脚本添加执行权限（首次使用）
chmod +x scripts/start_bots.sh

# 启动所有机器人
./scripts/start_bots.sh
```

**输出示例：**
```
🚀 启动交易机器人...
✅ 虚拟环境 para_env 存在
✅ 虚拟环境 env 存在
🤖 启动 Paradex 机器人...
🤖 启动 GRVT 机器人...
✅ 机器人启动完成！

📊 运行状态：
- Paradex 机器人 PID: 12345
- GRVT 机器人 PID: 12346

📝 日志文件：
- Paradex: paradex_bot.log
- GRVT: grvt_bot.log

💡 使用提示：
- 查看实时日志: tail -f paradex_bot.log
- 停止机器人: ./scripts/stop_bots.sh
- 检查状态: ./scripts/check_bots.sh
```

#### 2. `stop_bots.sh` - 停止交易机器人

**功能特性：**
- 优雅地停止所有运行中的机器人
- 基于 PID 文件进行精确停止
- **🛡️ 智能止损保护检查**：自动检测正在执行的止损操作，包括价格止损和回撤止损
- **⚠️ 用户确认机制**：止损进行中时提示用户确认是否强制停止，防止意外中断止损流程
- **📊 止损状态分析**：详细分析止损执行进度和完成状态
- **⏰ 延长等待时间**：从 10 秒延长到 15 秒，确保优雅关闭
- 自动清理残留进程
- 显示停止后的状态信息

**使用方法：**
```bash
# 停止所有机器人
./scripts/stop_bots.sh
```

**输出示例（正常情况）：**
```
🛑 停止交易机器人...
✅ 成功停止 Paradex 机器人 (PID: 12345)
✅ 成功停止 GRVT 机器人 (PID: 12346)
🧹 清理残留的 runbot.py 进程...
✅ 所有机器人已停止

📊 当前状态：
- 运行中的 runbot.py 进程: 0
- Paradex 日志大小: 1.2MB
- GRVT 日志大小: 0.8MB
```

**输出示例（检测到止损）：**
```
🛑 停止交易机器人...
⚠️  检测到 Paradex 机器人正在执行止损操作！
强制停止可能导致风险暴露。是否继续？(y/N): n
❌ 用户取消停止操作
```

#### 3. `safe_stop_bots.sh` - 安全停止交易机器人 🆕

**功能特性：**
- **🔍 智能止损检测**：自动扫描日志文件，检测活跃的止损操作（包括价格触发和回撤触发的止损）
- **🛡️ 三种停止模式**：等待完成、强制停止、取消操作
- **⏰ 超时保护**：最长等待 5 分钟，防止无限等待
- **📊 实时状态显示**：显示止损进度和剩余等待时间
- **🔄 自动重试**：定期检查止损状态，智能判断完成时机

**使用方法：**
```bash
# 给脚本添加执行权限（首次使用）
chmod +x safe_stop_bots.sh

# 安全停止所有机器人
./safe_stop_bots.sh
```

**输出示例（无活跃止损）：**
```
🔍 检查活跃的止损操作...
✅ 未检测到活跃的止损操作
🛑 调用 stop_bots.sh 停止机器人...
✅ 机器人安全停止完成
```

**输出示例（检测到活跃止损）：**
```
🔍 检查活跃的止损操作...
⚠️  检测到以下活跃的止损操作：
  - Paradex: 正在执行止损 (最后活动: 30秒前)
  - GRVT: 正在重试止损 (最后活动: 15秒前)

请选择操作：
1) 等待止损完成 (最多等待 5 分钟)
2) 强制停止 (可能有风险)
3) 取消操作
请输入选择 (1-3): 1

⏳ 等待止损操作完成... (剩余时间: 4分30秒)
🔄 检查止损状态... Paradex: 仍在执行, GRVT: 已完成
⏳ 等待止损操作完成... (剩余时间: 4分00秒)
🔄 检查止损状态... Paradex: 已完成, GRVT: 已完成
✅ 所有止损操作已完成
🛑 调用 stop_bots.sh 停止机器人...
✅ 机器人安全停止完成
```

**止损检测机制：**

- 扫描 `paradex_output.log` 和 `grvt_output.log` 的最后 20 行
- 搜索关键词：`executing stop loss`、`placing stop loss`、`retrying stop loss`、`severe drawdown triggered`、`automatic stop-loss`
- 使用不区分大小写的模式匹配
- 实时监控止损状态变化

#### 4. `check_bots.sh` - 检查机器人状态

**功能特性：**
- 全面的系统状态检查
- 虚拟环境和配置文件验证
- 进程状态和资源使用监控
- **🛡️ 止损状态监控**：实时显示止损监控状态和历史记录
- **📊 回撤分析**：显示当前回撤率和警告级别
- **🔍 异常处理监控**：检测和分析异常处理系统状态
- **📈 错误统计分析**：统计错误类型和发生频率
- 日志文件分析和错误检测
- 网络连接状态检查
- **⚡ 性能监控**：监控系统资源使用和性能指标

**使用方法：**
```bash
# 检查所有机器人状态
./scripts/check_bots.sh

# 检查特定机器人状态
./scripts/check_bots.sh --paradex    # 仅检查 Paradex
./scripts/check_bots.sh --grvt       # 仅检查 GRVT

# 查看帮助信息
./scripts/check_bots.sh --help
```

**输出示例：**
```
🔍 交易机器人状态检查

📁 虚拟环境状态：
✅ para_env: 存在 (Python 3.10.12)
✅ env: 存在 (Python 3.10.12)

⚙️ 配置文件状态：
✅ .env 文件存在
✅ PARADEX_L1_ADDRESS 已配置
✅ GRVT_TRADING_ACCOUNT_ID 已配置

🤖 进程状态：
✅ 发现 2 个运行中的 runbot.py 进程
  - PID 12345: Paradex 机器人 (运行时间: 2小时)
  - PID 12346: GRVT 机器人 (运行时间: 2小时)

🛡️ 止损监控状态：
📊 Paradex (paradex_output.log):
  - 当前回撤率: 3.2% (正常)
  - 警告级别: 无
  - 止损执行历史: 今日 0 次
  - 活跃止损: 无
  - 异常处理状态: ✅ 正常
  - 错误恢复次数: 0

📊 GRVT (grvt_output.log):
  - 当前回撤率: 1.8% (正常)
  - 警告级别: 无
  - 止损执行历史: 今日 0 次
  - 活跃止损: 无
  - 异常处理状态: ✅ 正常
  - 错误恢复次数: 0

🔍 异常处理系统状态：
  - 自定义异常类: ✅ 已加载 (7个异常类型)
  - 错误上下文记录: ✅ 正常
  - 异常链追踪: ✅ 启用
  - 错误统计: 今日异常 0 次

📝 日志文件状态：
📄 paradex_output.log: 1.2MB, 1,234 行, 最后修改: 2分钟前
📄 grvt_output.log: 0.8MB, 987 行, 最后修改: 1分钟前

🚨 最近错误: 无

📊 最新日志 (最后3行):
[Paradex] 2024-01-15 10:30:15 - 订单已提交: ETH-USD-PERP
[GRVT] 2024-01-15 10:30:20 - 持仓更新: BTC-USD-PERP

💻 系统资源：
- 内存使用: 45%
- 磁盘空间: 78%

🌐 网络连接: ✅ 正常

💡 快速操作：
- 启动机器人: ./scripts/start_bots.sh
- 停止机器人: ./scripts/stop_bots.sh
- 检查状态: ./scripts/check_bots.sh
- 查看实时日志: tail -f paradex_output.log
- 单独管理 Paradex: ./scripts/start_paradex.sh | ./scripts/stop_paradex.sh | ./scripts/check_paradex.sh
- 单独管理 GRVT: ./scripts/start_grvt.sh | ./scripts/stop_grvt.sh | ./scripts/check_grvt.sh
```

### 🔧 脚本配置说明

#### 虚拟环境要求
脚本会自动检查以下虚拟环境：
- `para_env`: 用于 Paradex 交易机器人
- `env`: 用于 GRVT 交易机器人

#### 日志文件
- `paradex_output.log`: Paradex 机器人的输出日志（包含止损监控信息）
- `grvt_output.log`: GRVT 机器人的输出日志（包含止损监控信息）
- `.paradex_pid`: Paradex 机器人的进程 ID 文件
- `.grvt_pid`: GRVT 机器人的进程 ID 文件

#### 止损监控集成
所有脚本现在都集成了止损监控功能：
- **实时检测**：自动检测日志中的止损活动
- **状态保护**：防止在止损执行期间意外停止机器人
- **历史分析**：跟踪止损执行历史和频率
- **风险评估**：基于回撤率提供风险级别评估

#### 异常处理集成
脚本现在支持完整的异常处理监控：
- **异常检测**：自动检测和分类各种异常类型
- **错误统计**：统计异常发生频率和类型分布
- **恢复监控**：监控系统的错误恢复状态
- **诊断工具**：提供详细的错误诊断信息
- **性能监控**：监控异常处理对系统性能的影响

#### 自定义配置
如需修改脚本行为，可以编辑脚本文件中的以下变量：
```bash
# 在 start_bots.sh 中
PARADEX_ENV="para_env"              # Paradex 虚拟环境名称
GRVT_ENV="env"                     # GRVT 虚拟环境名称
PARADEX_LOG="paradex_output.log"   # Paradex 日志文件名
GRVT_LOG="grvt_output.log"         # GRVT 日志文件名

# 在 safe_stop_bots.sh 中
PARADEX_LOG_FILE="paradex_output.log"  # Paradex 止损监控日志
GRVT_LOG_FILE="grvt_output.log"        # GRVT 止损监控日志
MAX_WAIT_TIME=300                      # 最大等待时间（秒）
```

### 📝 脚本路径更新说明

**重要更新**：所有管理脚本已从项目根目录迁移到 `scripts/` 目录中，并修正了所有内部路径引用。

- ✅ **新路径**: 所有脚本现在位于 `scripts/` 目录
- ✅ **路径修正**: 脚本内部的快捷操作提示已更新为正确的 `./scripts/` 路径
- ✅ **向后兼容**: 保持了所有原有功能和参数

### ⚠️ 注意事项

1. **权限设置**: 首次使用前需要给脚本添加执行权限
2. **虚拟环境**: 确保 `para_env` 和 `env` 虚拟环境已正确创建并安装依赖
3. **配置文件**: 确保 `.env` 文件已正确配置所需的 API 密钥
4. **Python 版本**: 脚本使用 `python3` 命令，确保系统已安装 Python 3
5. **日志管理**: 定期清理日志文件以避免占用过多磁盘空间
6. **异常处理**: 系统现在具备完整的异常处理机制，遇到错误时会自动记录详细信息
7. **脚本路径**: 请使用 `./scripts/` 前缀调用所有管理脚本
7. **错误恢复**: 大部分临时性错误会自动恢复，无需手动干预
8. **监控检查**: 建议定期运行 `./scripts/check_bots.sh` 检查系统健康状态

### 🚨 故障排除

#### 常见问题及解决方案：

**问题1: 虚拟环境不存在**
```bash
❌ 虚拟环境 para_env 不存在
```
**解决方案**: 创建虚拟环境
```bash
python3 -m venv para_env
python3 -m venv env
```

**问题2: 权限被拒绝**
```bash
bash: ./scripts/start_bots.sh: Permission denied
```
**解决方案**: 添加执行权限
```bash
chmod +x scripts/*.sh
```

**问题3: 进程无法启动**
```bash
❌ 启动 Paradex 机器人失败
```
**解决方案**: 检查配置和依赖
```bash
# 检查配置文件
./scripts/check_bots.sh

# 手动测试启动
source para_env/bin/activate
python3 runbot.py --help
```

#### 🔍 错误诊断指南

##### 异常处理相关错误

**问题4: 净值验证失败**
```bash
NetworthValidationError: 净值验证失败: 值必须为正数
```
**解决方案**: 检查账户余额和API连接
```bash
# 检查账户状态
./scripts/check_bots.sh

# 验证API配置
python3 -c "from helpers.drawdown_monitor import DrawdownMonitor; print('API配置正常')"
```

**问题5: 回撤监控异常**
```bash
DrawdownMonitorError: 回撤监控更新失败
```
**解决方案**: 检查网络连接和数据完整性
```bash
# 检查网络连接
ping api.exchange.com

# 重启监控系统
./scripts/stop_bots.sh && ./scripts/start_bots.sh
```

**问题6: API限流错误**
```bash
APIRateLimitError: API调用频率超限，请等待60秒后重试
```
**解决方案**: 等待限流解除或调整请求频率
```bash
# 检查API使用情况
grep "rate limit" *.log

# 调整等待时间参数
python3 runbot.py --wait-time 600 [其他参数]
```

##### 监控系统诊断

**问题7: 回撤监控未启用**
```bash
⚠️ 未检测到回撤监控启用信息
```
**解决方案**: 确认启用回撤监控参数
```bash
# 启用回撤监控
python3 runbot.py --enable-drawdown-monitor [其他参数]

# 检查监控状态
./scripts/check_bots.sh
```

**问题8: 止损执行失败**
```bash
StopLossExecutionError: 止损订单执行失败
```
**解决方案**: 检查订单状态和账户权限
```bash
# 检查订单历史
grep "stop loss" *.log | tail -10

# 验证账户权限
python3 -c "import exchange_client; client.get_account_info()"
```

**问题9: 价格止损未触发**
```bash
价格已达到stop-price但未执行止损
```
**解决方案**: 确认stop-price参数设置正确
```bash
# 检查价格止损配置
grep "stop.price\|price.*stop" *.log | tail -5

# 验证交易方向与止损逻辑
python3 runbot.py --stop-price 5500 --direction buy [其他参数]
```

**问题10: 回撤止损过于敏感**
```bash
频繁触发回撤止损，影响正常交易
```
**解决方案**: 调整回撤阈值参数
```bash
# 调整为更宽松的阈值
python3 runbot.py --drawdown-severe-threshold 15.0 [其他参数]

# 检查净值计算准确性
grep "drawdown\|networth" *.log | tail -10
```

**问题11: 止损订单未完全成交**
```bash
止损订单部分成交，仍有剩余持仓
```
**解决方案**: 系统会自动重试直至完全成交
```bash
# 检查止损重试状态
grep "retrying.*stop\|stop.*retry" *.log | tail -10

# 监控重试进度
tail -f *.log | grep "stop loss"
```

##### 🛠️ 高级诊断工具

**日志分析命令**:
```bash
# 查看异常统计
grep -c "Error\|Exception" *.log

# 分析错误类型分布
grep "Error:" *.log | cut -d':' -f2 | sort | uniq -c

# 检查最近的异常
tail -100 *.log | grep -A5 -B5 "Exception\|Error"

# 止损相关诊断
grep -E "(stop.loss|drawdown|severe)" *.log | tail -15

# 分析止损执行时间
grep "stop.loss.*executed\|stop.loss.*completed" *.log | tail -10
```

**性能监控命令**:
```bash
# 检查内存使用
ps aux | grep runbot.py

# 监控网络连接
netstat -an | grep ESTABLISHED | grep -E "(443|80)"

# 检查磁盘空间
df -h | grep -E "(/$|/home)"

# 监控系统资源
top -p $(pgrep -f runbot)

# 检查网络延迟
ping -c 5 api.paradex.trade

# 分析交易延迟
grep "order.*placed\|order.*filled" *.log | tail -10

# 止损执行性能分析
grep "stop.loss.*start\|stop.loss.*end" *.log | tail -10

# 监控止损响应时间
grep -E "stop.loss.*[0-9]+ms|stop.loss.*[0-9]+s" *.log | tail -5
```

**系统健康检查**:
```bash
# 完整系统检查
./scripts/check_bots.sh

# 验证异常处理系统
python3 -c "
from helpers.drawdown_monitor import *
print('✅ 异常处理系统正常')
print('✅ 自定义异常类加载成功')
"

# 检查异常处理系统状态
grep "Exception.*loaded\|Error.*handler" *.log | tail -5

# 验证错误恢复机制
grep "recovery.*attempt\|retry.*success" *.log | tail -10

# 止损系统健康检查
grep "stop.loss.*system.*ready\|stop.loss.*initialized" *.log | tail -3

# 验证止损保护机制
grep "stop.loss.*protection.*active\|drawdown.*monitoring" *.log | tail -5

# 检查止损历史记录
grep "stop.loss.*executed.*successfully" *.log | wc -l
```

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

#### 📋 回撤参数

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `--enable-drawdown-monitor` | flag | False | 启用回撤监控功能 |
| `--drawdown-light-threshold` | Decimal | 5 | 轻微回撤警告阈值 (%) |
| `--drawdown-medium-threshold` | Decimal | 8 | 中等回撤警告阈值 (%) |
| `--drawdown-severe-threshold` | Decimal | 12 | 严重回撤智能止损阈值 (%) - 触发自动止损保护 |

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

##### 5. 缓存功能配置示例

###### 容错模式（推荐）- 最大化保护效果
```bash
python runbot.py --exchange paradex --ticker ETH --quantity 0.1 --enable-drawdown-monitor \
  --drawdown-severe-threshold 10.0
```
- 使用默认缓存设置（容错模式，5分钟缓存有效期）
- 网络故障时自动使用缓存数据维持监控连续性

###### 严格模式 - 确保数据绝对准确
```python
# 在 DrawdownConfig 中配置严格模式
config = DrawdownConfig(
    light_warning_threshold=Decimal("5.0"),
    medium_warning_threshold=Decimal("8.0"), 
    severe_warning_threshold=Decimal("12.0"),
    strict_mode=True,  # 启用严格模式
    cache_duration=300  # 5分钟缓存有效期
)
```

###### 自定义缓存有效期
```python
# 配置更长的缓存有效期（10分钟）
config = DrawdownConfig(
    light_warning_threshold=Decimal("5.0"),
    medium_warning_threshold=Decimal("8.0"),
    severe_warning_threshold=Decimal("12.0"),
    cache_duration=600,  # 10分钟缓存有效期
    strict_mode=False   # 容错模式
)
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

##### 💾 缓存机制行为

###### 正常运行状态
- **数据获取**: 每次成功获取净值时自动更新缓存
- **缓存状态**: 日志显示 "Using real-time net worth data"
- **性能影响**: 缓存操作对交易性能影响微乎其微

###### 网络故障状态
- **故障检测**: 自动检测网络异常、API限流、数据异常等情况
- **缓存回退**: 日志显示 "Using cached net worth data due to network issues"
- **时效提醒**: 显示缓存数据的时间戳和剩余有效期

###### 容错模式（默认）
- **缓存有效**: 使用缓存数据继续监控，确保保护连续性
- **缓存过期**: 继续使用过期缓存并发出警告，最大化保护效果
- **恢复行为**: 网络恢复后立即切换回实时监控

###### 严格模式
- **缓存有效**: 使用缓存数据继续监控
- **缓存过期**: 暂停监控并记录警告，等待网络恢复
- **恢复行为**: 网络恢复后自动重启监控功能

#### ⚠️ 注意事项

1. **阈值顺序**: 必须满足 `light < medium < severe` 的关系
2. **实时监控**: 回撤监控在主交易循环中实时进行
3. **净值计算**: 基于交易所账户的实际净值进行计算
4. **会话峰值**: 每次启动程序时重新计算会话峰值
5. **通知系统**: 支持 Telegram 和 Lark 通知（需要配置相应的 bot）
6. **缓存有效期**: 默认5分钟，可根据网络环境和交易频率调整
7. **模式选择**: 容错模式适合大多数场景，严格模式适合对数据准确性要求极高的场景
8. **缓存监控**: 关注日志中的缓存状态信息，了解网络质量和缓存使用情况
9. **故障恢复**: 网络恢复后系统会自动切换回实时监控，无需手动干预

#### 🏆 最佳实践

##### 基础配置建议
1. **首次使用**: 建议从保守的阈值开始，逐步调整到适合的水平
2. **回测验证**: 在实盘使用前，建议通过历史数据验证阈值设置的合理性
3. **定期调整**: 根据市场条件和交易表现定期调整阈值
4. **监控日志**: 密切关注回撤监控的日志输出，了解触发频率和效果

##### 缓存功能最佳实践
5. **模式选择**: 
   - 🔄 **容错模式**（推荐）: 适合大多数交易场景，最大化保护连续性
   - ⚡ **严格模式**: 适合对数据准确性要求极高的高频交易场景
6. **缓存有效期设置**:
   - 🕐 **5分钟**（默认）: 适合大多数交易频率
   - 🕐 **3分钟**: 适合高频交易，更快的数据更新
   - 🕐 **10分钟**: 适合低频交易，减少网络请求
7. **网络环境优化**:
   - 📡 监控网络质量，关注缓存使用频率
   - 🔄 网络不稳定时适当延长缓存有效期
   - 📊 定期检查日志中的缓存命中率
8. **故障处理策略**:
   - 🚨 关注 "Using cached data" 日志，了解网络状况
   - ⏰ 缓存过期警告出现时检查网络连接
   - 🔧 必要时手动重启以刷新缓存状态

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
- `--stop-price`: 价格止损触发点。当 `direction` 是 'buy' 时，当 price >= stop-price 时触发止损并退出程序；'sell' 逻辑相反（默认：-1，表示不启用价格止损）。触发时会执行智能止损流程，确保持仓安全平仓。参数的目的是防止订单被挂在"你认为的开多高点或开空低点"。
- `--pause-price`: 当 `direction` 是 'buy' 时，当 price >= pause-price 时暂停交易，并在价格回到 pause-price 以下时重新开始交易；'sell' 逻辑相反（默认：-1，表示不会因为价格原因停止交易），参数的目的是防止订单被挂在”你认为的开多高点或开空低点“。
- `--aster-boost`: 启用 Aster 交易所的 Boost 模式进行交易量提升（仅适用于 aster 交易所）
- `--enable-drawdown-monitor`: 启用回撤监控功能（可选）
- `--drawdown-light-threshold`: 轻微回撤阈值，百分比（默认 5.0）
- `--drawdown-medium-threshold`: 中等回撤阈值，百分比（默认 8.0）
- `--drawdown-severe-threshold`: 严重回撤智能止损阈值，百分比（默认 12.0）。触发时会立即执行自动止损保护，使用智能价格执行和重试机制确保持仓安全平仓
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

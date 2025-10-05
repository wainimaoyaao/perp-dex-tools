##### Follow Me - **X (Twitter)**: [@yourQuantGuy](https://x.com/yourQuantGuy)

## 📢 Sharing Notice

**Sharing is encouraged!** If you share or modify this code, please include attribution to the original repository. We encourage the growth of the open-source community, but please maintain respect and recognition for the original author's work.

---

## Multi-Exchange Trading Bot

A modular trading bot that supports multiple exchanges including EdgeX, Backpack, Paradex, Aster, Lighter, and GRVT. The bot implements an automated strategy that places orders and automatically closes them at a profit.



## Installation

1. **Clone the repository**:

   ```bash
   git clone <repository-url>
   cd perp-dex-tools
   ```

2. **Create and activate virtual environment**:

   First, make sure you are not currently in any virtual environment:

   ```bash
   deactivate
   ```

   Create virtual environment:

   ```bash
   python3 -m venv env
   ```

   Activate virtual environment (you need to activate the virtual environment every time you use the script):

   ```bash
   source env/bin/activate  # Windows: env\Scripts\activate
   ```

3. **Install dependencies**:
   First, make sure you are not currently in any virtual environment:

   ```bash
   deactivate
   ```

   Activate virtual environment (you need to activate the virtual environment every time you use the script):

   ```bash
   source env/bin/activate  # Windows: env\Scripts\activate
   ```

   ```bash
   pip install -r requirements.txt
   ```

   **Paradex Users**: If you want to use Paradex exchange, you need to create an additional virtual environment and install Paradex-specific dependencies:

   First, make sure you are not currently in any virtual environment:

   ```bash
   deactivate
   ```

   Create a dedicated virtual environment for Paradex (named para_env):

   ```bash
   python3 -m venv para_env
   ```

   Activate virtual environment (you need to activate the virtual environment every time you use the script):

   ```bash
   source para_env/bin/activate  # Windows: para_env\Scripts\activate
   ```

   Install Paradex dependencies

   ```bash
   pip install -r para_requirements.txt
   ```

4. **Set up environment variables**:
   Create a `.env` file in the project root directory and use env_example.txt as a template to modify with your API keys.

5. **Telegram Bot Setup (Optional)**:
   To receive trading notifications, please refer to the [Telegram Bot Setup Guide](docs/telegram-bot-setup-en.md) to configure your Telegram bot.

## Strategy Overview

**Important Notice**: Everyone must first understand the logic and risks of this script so you can set parameters that are more suitable for yourself, or you might think this is not a good strategy and don't want to use it at all. As I mentioned on Twitter, I didn't write these scripts for sharing purposes, but because I'm actually using this script myself, so I wrote it, and then shared it.
This script mainly focuses on long-term wear and tear. As long as the script continues to place orders, if the price reaches your highest trapped point after a month, then all your trading volume for that month will be zero-wear. Therefore, I believe that setting `--quantity` and `--wait-time` too small is not a good long-term strategy, but it is indeed suitable for short-term high-intensity volume trading. I usually use quantity between 40-60 and wait-time between 450-650 to ensure that even if the market goes against your judgment, the script can still place orders continuously and stably until the price returns to your entry point, achieving zero-wear volume trading.

The bot implements a simple trading strategy:

1. **Order Placement**: Places limit orders near the current market price
2. **Order Monitoring**: Waits for orders to be filled
3. **Close Order**: Automatically places close orders at the take-profit level
4. **Position Management**: Monitors positions and active orders
5. **Risk Management**: Limits maximum number of concurrent orders
6. **Grid Step Control**: Controls minimum price distance between new orders and existing close orders via `--grid-step` parameter
7. **Stop Trading Control**: Controls the price conditions for stopping transactions through the `--stop-price` parameter

#### ⚙️ Key Parameters

- **quantity**: Trading amount per order
- **take-profit**: Take-profit percentage (e.g., 0.02 means 0.02%)
- **max-orders**: Maximum concurrent active orders (risk control)
- **wait-time**: Wait time between orders (prevents overtrading)
- **grid-step**: Grid step control (prevents close orders from being too dense)
- **stop-price**: When `direction` is 'buy', exit when price >= stop-price; 'sell' logic is opposite (default: -1, no price-based termination)
- **pause-price**: When `direction` is 'buy', pause when price >= pause-price; 'sell' logic is opposite (default: -1, no price-based pausing)

#### Grid Step Feature

The `--grid-step` parameter controls the minimum distance between new order close prices and existing close order prices:

- **Default -100**: No grid step restriction, executes original strategy
- **Positive value (e.g., 0.5)**: New order close price must maintain at least 0.5% distance from the nearest close order price
- **Purpose**: Prevents close orders from being too dense, improving fill probability and risk management

For example, when Long and `--grid-step 0.5`:

- If existing close order price is 2000 USDT
- New order close price must be lower than 1990 USDT (2000 × (1 - 0.5%))
- This prevents close orders from being too close together, improving overall strategy effectiveness

#### 📊 Trading Flow Example

Assuming current ETH price is $2000 with take-profit set to 0.02%:

1. **Open Position**: Places buy order at $2000.40 (slightly above market price)
2. **Fill**: Order gets filled by the market, acquiring long position
3. **Close Position**: Immediately places sell order at $2000.80 (take-profit price)
4. **Complete**: Close order gets filled, earning 0.02% profit
5. **Repeat**: Continues to the next trading cycle

#### 🛡️ Risk Management

- **Order Limits**: Limits maximum concurrent orders via `max-orders`
- **Grid Control**: Ensures reasonable spacing between close orders via `grid-step`
- **Order Frequency Control**: Controls order timing via `wait-time` to prevent being trapped in short periods
- **Real-time Monitoring**: Continuously monitors positions and order status
- **Drawdown Monitoring**: Optional intelligent drawdown monitoring system with multi-level risk alerts and automatic stop-loss
- **⚠️ Basic Strategy No Stop Loss**: The basic strategy does not include stop-loss functionality, but risk management can be achieved through drawdown monitoring

#### 📈 PnL and Margin Monitoring Features

The bot now supports real-time monitoring of account profit and loss (PnL) and margin status, providing comprehensive risk management:

##### 🔍 Monitoring Features

- **Account Balance Monitoring**: Real-time tracking of available account balance
- **Account Equity Monitoring**: Monitor total account equity (including unrealized PnL)
- **Unrealized PnL Calculation**: Real-time calculation of unrealized PnL for all positions
- **Margin Usage Monitoring**: Monitor initial margin requirements
- **Position Loss Assessment**: Calculate potential losses of current positions

##### 🎯 Supported Exchanges

Currently, PnL and margin monitoring features support the following exchanges:

- **Paradex**: Full support for all PnL and margin monitoring features
- **Other Exchanges**: Support is being gradually added

##### 📊 Monitoring Data

The bot periodically records the following key metrics:

- **Account Balance**: Current funds available for trading
- **Account Equity**: Total account value (balance + unrealized PnL)
- **Unrealized PnL**: Floating profit/loss of all open positions
- **Initial Margin**: Margin required to maintain current positions
- **Position Loss**: Potential loss amount of current positions

##### ⚠️ Enhanced Risk Management

- **Real-time Risk Assessment**: Risk evaluation based on PnL data
- **Margin Monitoring**: Prevent forced liquidation due to insufficient margin
- **Loss Alerts**: Provide warnings when position losses exceed preset thresholds
- **Data Logging**: All PnL and margin data are recorded in logs

#### 📉 Drawdown Monitoring Feature

The bot now supports an intelligent drawdown monitoring system with multi-level risk alerts and automatic stop-loss functionality:

##### 🎯 Monitoring Levels

- **Light Drawdown (default 5%)**: Send notification alerts, continue normal trading
- **Medium Drawdown (default 8%)**: Pause new orders, only allow closing positions
- **Severe Drawdown (default 12%)**: Immediately stop all trading, trigger automatic stop-loss

##### ⚙️ Configuration Parameters

- `--enable-drawdown-monitor`: Enable drawdown monitoring feature
- `--drawdown-light-threshold`: Light drawdown threshold (default 5.0%)
- `--drawdown-medium-threshold`: Medium drawdown threshold (default 8.0%)
- `--drawdown-severe-threshold`: Severe drawdown threshold (default 12.0%)

##### 🔄 How It Works

1. **Session Initialization**: Record initial net worth as baseline when trading starts
2. **Real-time Monitoring**: Continuously get account net worth, calculate drawdown percentage relative to session peak
3. **Smart Smoothing**: Use moving average algorithm to reduce false alarms from net worth fluctuations
4. **Tiered Response**: Take different risk management measures based on drawdown severity
5. **Auto Recovery**: Automatically resume normal trading when drawdown level decreases

##### 📊 Monitoring Data

- **Session Peak Net Worth**: Highest net worth achieved during the trading session
- **Current Net Worth**: Real-time account net worth
- **Drawdown Percentage**: (Peak Net Worth - Current Net Worth) / Peak Net Worth × 100%
- **Smoothed Net Worth**: Net worth processed with moving average to reduce noise

##### 🚨 Enhanced Risk Management

- **Real-time Notifications**: Send drawdown alerts via Telegram/Lark
- **Automatic Stop-loss**: Automatically stop trading during severe drawdowns
- **Progressive Response**: Take different measures based on drawdown severity
- **Session Reset**: Recalculate baseline net worth each time trading starts

## Sample commands:

### EdgeX Exchange:

ETH:

```bash
python runbot.py --exchange edgex --ticker ETH --quantity 0.1 --take-profit 0.02 --max-orders 40 --wait-time 450
```

ETH (with grid step control):

```bash
python runbot.py --exchange edgex --ticker ETH --quantity 0.1 --take-profit 0.02 --max-orders 40 --wait-time 450 --grid-step 0.5
```

ETH (with stop price control):

```bash
python runbot.py --exchange edgex --ticker ETH --quantity 0.1 --take-profit 0.02 --max-orders 40 --wait-time 450 --stop-price 5500
```

BTC:

```bash
python runbot.py --exchange edgex --ticker BTC --quantity 0.05 --take-profit 0.02 --max-orders 40 --wait-time 450
```

### Backpack Exchange:

ETH Perpetual:

```bash
python runbot.py --exchange backpack --ticker ETH --quantity 0.1 --take-profit 0.02 --max-orders 40 --wait-time 450
```

ETH Perpetual (with grid step control):

```bash
python runbot.py --exchange backpack --ticker ETH --quantity 0.1 --take-profit 0.02 --max-orders 40 --wait-time 450 --grid-step 0.3
```

### Aster Exchange:

ETH:

```bash
python runbot.py --exchange aster --ticker ETH --quantity 0.1 --take-profit 0.02 --max-orders 40 --wait-time 450
```

ETH (with Boost mode enabled):

```bash
python runbot.py --exchange aster --ticker ETH --direction buy --quantity 0.1 --aster-boost
```

### GRVT Exchange:

BTC:

```bash
python runbot.py --exchange grvt --ticker BTC --quantity 0.05 --take-profit 0.02 --max-orders 40 --wait-time 450
```

### Detailed Drawdown Monitoring Guide:

#### 📋 Available Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `--enable-drawdown-monitor` | flag | False | Enable drawdown monitoring feature |
| `--drawdown-light-threshold` | Decimal | 5 | Light drawdown warning threshold (%) |
| `--drawdown-medium-threshold` | Decimal | 8 | Medium drawdown warning threshold (%) |
| `--drawdown-severe-threshold` | Decimal | 12 | Severe drawdown stop-loss threshold (%) |

#### 💡 Usage Examples

##### 1. Enable with Default Thresholds
```bash
python runbot.py --exchange edgex --ticker ETH --quantity 0.1 --take-profit 0.02 --enable-drawdown-monitor
```
- Light drawdown: 5%
- Medium drawdown: 8%
- Severe drawdown: 12%

##### 2. Conservative Strategy - Lower Thresholds
```bash
python runbot.py --exchange edgex --ticker ETH --quantity 0.1 --take-profit 0.02 --enable-drawdown-monitor \
  --drawdown-light-threshold 3.0 \
  --drawdown-medium-threshold 5.0 \
  --drawdown-severe-threshold 8.0
```
Suitable for risk-averse traders, triggers protection mechanisms earlier.

##### 3. Aggressive Strategy - Higher Thresholds
```bash
python runbot.py --exchange backpack --ticker ETH --quantity 0.1 --take-profit 0.02 --enable-drawdown-monitor \
  --drawdown-light-threshold 8.0 \
  --drawdown-medium-threshold 12.0 \
  --drawdown-severe-threshold 18.0
```
Suitable for traders with higher risk tolerance, allows larger drawdowns.

##### 4. Complete Trading Configuration Example
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

#### 🎯 Monitoring Behavior Details

##### Light Drawdown
- **Trigger Condition**: Current net worth drawdown relative to session peak reaches light threshold
- **Behavior**: Log warning and send notification, trading continues normally
- **Notification Content**: Includes current net worth, peak net worth, drawdown percentage, etc.

##### Medium Drawdown
- **Trigger Condition**: Drawdown reaches medium threshold
- **Behavior**: Pause new order creation, only allow closing existing positions
- **Recovery**: Automatically resume normal trading when drawdown falls below medium threshold

##### Severe Drawdown
- **Trigger Condition**: Drawdown reaches severe threshold
- **Behavior**: Immediately stop all trading activities and gracefully exit the program
- **Non-recoverable**: Manual program restart required to continue trading

#### ⚠️ Important Notes

1. **Threshold Order**: Must satisfy `light < medium < severe` relationship
2. **Real-time Monitoring**: Drawdown monitoring occurs in real-time within the main trading loop
3. **Net Worth Calculation**: Based on actual account net worth from the exchange
4. **Session Peak**: Session peak is recalculated each time the program starts
5. **Notification System**: Supports Telegram and Lark notifications (requires bot configuration)

#### 🏆 Best Practices

1. **First Use**: Recommend starting with conservative thresholds, gradually adjusting to suitable levels
2. **Backtesting**: Validate threshold settings with historical data before live trading
3. **Regular Adjustment**: Periodically adjust thresholds based on market conditions and trading performance
4. **Monitor Logs**: Pay close attention to drawdown monitoring log output to understand trigger frequency and effectiveness

## Configuration

### Environment Variables

#### General Configuration

- `ACCOUNT_NAME`: The name of the current account in the environment variable, used for distinguishing between multiple account logs, customizable, not mandatory

#### Telegram Configuration (Optional)

- `TELEGRAM_BOT_TOKEN`: Telegram bot token
- `TELEGRAM_CHAT_ID`: Telegram chat ID

#### EdgeX Configuration

- `EDGEX_ACCOUNT_ID`: Your EdgeX account ID
- `EDGEX_STARK_PRIVATE_KEY`: Your EdgeX api private key
- `EDGEX_BASE_URL`: EdgeX API base URL (default: https://pro.edgex.exchange)
- `EDGEX_WS_URL`: EdgeX WebSocket URL (default: wss://quote.edgex.exchange)

#### Backpack Configuration

- `BACKPACK_PUBLIC_KEY`: Your Backpack API key
- `BACKPACK_SECRET_KEY`: Your Backpack API Secret

#### Paradex Configuration

- `PARADEX_L1_ADDRESS`: L1 wallet address
- `PARADEX_L2_PRIVATE_KEY`: L2 wallet private key (click avatar, wallet, "copy paradex private key")

#### Aster Configuration

- `ASTER_API_KEY`: Your Aster API Key
- `ASTER_SECRET_KEY`: Your Aster API Secret

#### Lighter Configuration

- `API_KEY_PRIVATE_KEY`: Your Lighter API private key
- `LIGHTER_ACCOUNT_INDEX`: Lighter account index
- `LIGHTER_API_KEY_INDEX`: Lighter API key index

#### GRVT Configuration

- `GRVT_TRADING_ACCOUNT_ID`: Your GRVT trading account ID
- `GRVT_PRIVATE_KEY`: Your GRVT private key
- `GRVT_API_KEY`: Your GRVT API key

**How to get LIGHTER_ACCOUNT_INDEX**:

1. Add your wallet address to the end of the following URL:

   ```
   https://mainnet.zklighter.elliot.ai/api/v1/account?by=l1_address&value=
   ```

2. Open this URL in your browser

3. Search for "account_index" in the results - if you have subaccounts, there will be multiple account_index values. The shorter one is your main account, and the longer ones are your subaccounts.

### Command Line Arguments

- `--exchange`: Exchange to use: 'edgex', 'backpack', 'paradex', 'aster', 'lighter', or 'grvt' (default: edgex)
- `--ticker`: Base asset symbol (e.g., ETH, BTC, SOL). Contract ID is auto-resolved.
- `--quantity`: Order quantity (default: 0.1)
- `--take-profit`: Take profit percent (e.g., 0.02 means 0.02%)
- `--direction`: Trading direction: 'buy' or 'sell' (default: buy)
- `--env-file`: Account configuration file (default: .env)
- `--max-orders`: Maximum number of active orders (default: 40)
- `--wait-time`: Wait time between orders in seconds (default: 450)
- `--grid-step`: Minimum distance in percentage to the next close order price (default: -100, means no restriction)
- `--stop-price`: When `direction` is 'buy', stop trading and exit the program when price >= stop-price; 'sell' logic is opposite (default: -1, no price-based termination). The purpose of this parameter is to prevent orders from being placed at "high points for long positions or low points for short positions that you consider".
- `--pause-price`: When `direction` is 'buy', pause trading when price >= pause-price and resume trading when price falls back below pause-price; 'sell' logic is opposite (default: -1, no price-based pausing). The purpose of this parameter is to prevent orders from being placed at "high points for long positions or low points for short positions that you consider".
- `--aster-boost`: Enable Boost mode for volume boosting on Aster exchange (only available for aster exchange)
- `--enable-drawdown-monitor`: Enable drawdown monitoring feature (optional)
- `--drawdown-light-threshold`: Light drawdown threshold, percentage (default 5.0)
- `--drawdown-medium-threshold`: Medium drawdown threshold, percentage (default 8.0)
- `--drawdown-severe-threshold`: Severe drawdown threshold, percentage (default 12.0)
  `--aster-boost` trading logic: Place maker orders to open positions, immediately close with taker orders after fill, repeat this cycle. Wear consists of one maker order, one taker order fees, and slippage.

## Logging

The bot provides comprehensive logging:

- **Transaction Logs**: CSV files with order details
- **Debug Logs**: Detailed activity logs with timestamps
- **Console Output**: Real-time status updates
- **Error Handling**: Comprehensive error logging and handling

## Q & A

### How to configure multiple accounts for the same exchange on the same device?

1. Create a .env file for each account, such as account_1.env, account_2.env
2. Set `ACCOUNT_NAME=` in each account's .env file, such as `ACCOUNT_NAME=MAIN`.
3. Configure the API keys or secrets for each account in each file
4. Use different `--env-file` parameters in the command line to start different accounts, such as `python runbot.py --env-file account_1.env [other parameters...]`

### How to configure multiple accounts for different exchanges on the same device?

Configure all different exchange accounts in the same `.env` file, then use different `--exchange` parameters in the command line to start different exchanges, such as `python runbot.py --exchange backpack [other parameters...]`

### How to configure multiple contracts for the same account and exchange on the same device?

Configure the account in the `.env` file, then use different `--ticker` parameters in the command line to start different contracts, such as `python runbot.py --ticker ETH [other parameters...]`

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests if applicable
5. Submit a pull request

## License

This project is licensed under a Non-Commercial License - see the [LICENSE](LICENSE) file for details.

**Important Notice**: This software is for personal learning and research purposes only. Commercial use is strictly prohibited. For commercial use, please contact the author for a commercial license.

## Disclaimer

This software is for educational and research purposes only. Trading cryptocurrencies involves significant risk and can result in substantial financial losses. Use at your own risk and never trade with money you cannot afford to lose.

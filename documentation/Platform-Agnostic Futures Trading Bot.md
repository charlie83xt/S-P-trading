# Platform-Agnostic Futures Trading Bot

A sophisticated, platform-agnostic futures trading bot that supports multiple trading platforms through a unified interface. The bot implements the Opening Range Breakthrough strategy and can seamlessly switch between different API providers by simply changing configuration settings.

## 🚀 Features

### Multi-Platform Support
- **Binance Futures** - Cryptocurrency futures trading
- **Tradovate** - Traditional futures (S&P 500, Nasdaq, etc.)
- **NinjaTrader** - Professional futures trading platform
- **Easy Platform Switching** - Change platforms by updating a single environment variable

### Trading Strategy
- **Opening Range Breakthrough** - Automated strategy based on market opening ranges
- **Configurable Parameters** - Customizable range periods, breakout thresholds, and risk parameters
- **Volume Confirmation** - Optional volume-based signal validation

### Risk Management
- **Position Sizing** - Configurable position limits and maximum exposure
- **Daily Loss Limits** - Automatic trading halt on daily loss thresholds
- **Drawdown Protection** - Maximum drawdown percentage controls
- **Stop Loss & Take Profit** - Automated risk management orders

### Bot Control Features
- **Start/Stop/Pause** - Full control over bot operations
- **Cooldown Periods** - Configurable waiting periods between trades
- **Emergency Stop** - Immediate halt with order cancellation
- **Status Monitoring** - Real-time bot status and performance tracking

### Data Management
- **Historical Data** - Automated collection and storage of market data
- **Price Analysis** - Min/max price calculations over custom time periods
- **Opening Range Calculation** - Automated daily opening range detection
- **Database Storage** - Local SQLite database for data persistence

### Web Interface
- **Dashboard** - Real-time monitoring and control interface
- **REST API** - Programmatic control and status endpoints
- **Configuration Management** - Dynamic parameter updates

## 📋 Prerequisites

- Python 3.8 or higher
- Trading account with your chosen platform
- API credentials for your selected platform

## 🛠️ Installation

1. **Clone the repository:**
   ```bash
   git clone <repository-url>
   cd futures_trading_bot
   ```

2. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

3. **Configure environment:**
   ```bash
   cp .env.example .env
   # Edit .env with your credentials and preferences
   ```

## ⚙️ Configuration

### Platform Selection

Set your desired trading platform in the `.env` file:

```bash
# Choose: binance, tradovate, or ninjatrader
TRADING_PLATFORM=tradovate
```

### Platform-Specific Setup

#### Binance Futures
```bash
BINANCE_API_KEY=your_api_key
BINANCE_API_SECRET=your_api_secret
BINANCE_TESTNET=true  # Use testnet for testing
```

#### Tradovate
```bash
TRADOVATE_USERNAME=your_username
TRADOVATE_PASSWORD=your_password
TRADOVATE_APP_ID=your_app_id
TRADOVATE_APP_VERSION=your_app_version
TRADOVATE_CID=your_client_id
TRADOVATE_SEC=your_secret
TRADOVATE_DEMO=true  # Use demo environment for testing
```

#### NinjaTrader
```bash
NINJATRADER_API_URL=http://localhost:8080
NINJATRADER_API_KEY=your_api_key  # Optional for local access
NINJATRADER_SIMULATION=true  # Use simulation mode for testing
```

### Trading Configuration

```bash
# Symbol Configuration (ES for S&P 500, NQ for Nasdaq)
DEFAULT_SYMBOL=ES
DEFAULT_QUANTITY=1.0
MAX_POSITION_SIZE=5.0

# Risk Management
MAX_DAILY_LOSS=500.0
MAX_DRAWDOWN_PERCENT=5.0
STOP_LOSS_PERCENT=2.0
TAKE_PROFIT_PERCENT=4.0

# Strategy Parameters
OPENING_RANGE_MINUTES=30
BREAKOUT_THRESHOLD_PERCENT=0.1
VOLUME_CONFIRMATION=true
```

## 🚀 Quick Start

### 1. Basic Usage

```python
from trading_bot import TradingBot

# Initialize bot
bot = TradingBot()

# Start trading
bot.start()

# Check status
status = bot.get_status()
print(f"Bot running: {status['is_running']}")
print(f"Platform: {status['platform']}")

# Stop trading
bot.stop()
```

### 2. Web Interface

Start the web dashboard:

```bash
cd web_interface
source venv/bin/activate  # If using virtual environment
python src/main.py
```

Access the dashboard at `http://localhost:5000`

### 3. Testing the Strategy

Run the strategy test:

```bash
python test_strategy.py
```

## 🔧 API Reference

### TradingBot Class

#### Methods

- `start()` - Start the trading bot
- `stop()` - Stop the trading bot and cancel all orders
- `pause(minutes=0)` - Pause trading for specified minutes (0 = indefinite)
- `resume()` - Resume trading from pause
- `get_status()` - Get current bot status and metrics
- `get_positions()` - Get current trading positions
- `get_orders()` - Get active orders

#### Status Response
```python
{
    'is_running': bool,
    'is_paused': bool,
    'platform': str,
    'is_connected': bool,
    'daily_pnl': float,
    'active_orders_count': int,
    'positions_count': int,
    'last_trade_time': str,
    'account_balance': float,
    'available_margin': float
}
```

### REST API Endpoints

- `GET /api/status` - Get bot status
- `POST /api/start` - Start the bot
- `POST /api/stop` - Stop the bot
- `POST /api/pause` - Pause the bot
- `POST /api/resume` - Resume the bot
- `GET /api/positions` - Get current positions
- `GET /api/orders` - Get active orders
- `GET /api/config` - Get current configuration
- `POST /api/config` - Update configuration

## 🔄 Platform Switching

To switch between platforms:

1. **Stop the bot** (if running):
   ```python
   bot.stop()
   ```

2. **Update the platform** in `.env`:
   ```bash
   TRADING_PLATFORM=tradovate  # Change to desired platform
   ```

3. **Ensure credentials** are configured for the new platform

4. **Restart the bot**:
   ```python
   bot = TradingBot()  # Will use new platform
   bot.start()
   ```

## 📊 Strategy Details

### Opening Range Breakthrough

The bot implements a classic opening range breakthrough strategy:

1. **Range Calculation**: Identifies the high and low prices during the opening period (default: 30 minutes)
2. **Breakout Detection**: Monitors for price breaks above the range high (buy signal) or below the range low (sell signal)
3. **Volume Confirmation**: Optionally validates signals with volume analysis
4. **Risk Management**: Automatically sets stop-loss and take-profit levels

### Signal Generation

```python
# Example signal structure
{
    'signal_type': 'BUY',  # BUY, SELL, or HOLD
    'symbol': 'ES',
    'entry_price': 4500.0,
    'quantity': 1.0,
    'stop_loss': 4490.0,
    'take_profit': 4520.0,
    'confidence': 0.85,
    'timestamp': '2024-01-15T09:45:00'
}
```

## 🛡️ Risk Management

### Built-in Protections

- **Daily Loss Limits**: Automatic shutdown when daily losses exceed configured thresholds
- **Position Limits**: Maximum number of concurrent positions
- **Drawdown Protection**: Halt trading when account drawdown exceeds limits
- **Emergency Stop**: Immediate order cancellation and position closure

### Risk Parameters

```bash
MAX_DAILY_LOSS=500.0          # Maximum daily loss in account currency
MAX_DRAWDOWN_PERCENT=5.0      # Maximum account drawdown percentage
MAX_OPEN_POSITIONS=3          # Maximum concurrent positions
STOP_LOSS_PERCENT=2.0         # Default stop-loss percentage
TAKE_PROFIT_PERCENT=4.0       # Default take-profit percentage
```

## 📈 Monitoring and Logging

### Log Files

- `trading_bot.log` - Main bot operations and errors
- `strategy.log` - Strategy-specific signals and decisions
- `risk_manager.log` - Risk management actions

### Log Levels

Configure logging detail in `.env`:
```bash
LOG_LEVEL=INFO  # DEBUG, INFO, WARNING, ERROR
```

### Performance Metrics

The bot tracks:
- Daily P&L
- Win/loss ratio
- Average trade duration
- Maximum drawdown
- Sharpe ratio (when sufficient data available)

## 🧪 Testing

### Strategy Backtesting

```bash
python test_strategy.py --symbol ES --days 30 --platform tradovate
```

### Unit Tests

```bash
python -m pytest tests/
```

### Paper Trading

All platforms support simulation/testnet modes:
- **Binance**: Set `BINANCE_TESTNET=true`
- **Tradovate**: Set `TRADOVATE_DEMO=true`
- **NinjaTrader**: Set `NINJATRADER_SIMULATION=true`

## 🚨 Important Notes

### Platform-Specific Considerations

#### Binance Futures
- Supports cryptocurrency futures only
- No traditional stock index futures (S&P 500, Nasdaq)
- Excellent for crypto futures testing and development

#### Tradovate
- Supports traditional futures (ES, NQ, etc.)
- Requires live account with minimum balance for API access
- Demo environment available for testing

#### NinjaTrader
- Professional futures platform
- Free paper trading simulator
- Local API requires NinjaTrader installation
- Best for S&P 500 and traditional futures

### Security Best Practices

1. **Never commit** `.env` files to version control
2. **Use testnet/demo** environments for development
3. **Start with small position sizes** in live trading
4. **Monitor bot performance** regularly
5. **Keep API keys secure** and rotate them periodically

### Performance Optimization

- **Database Maintenance**: Regularly clean old data to maintain performance
- **Memory Management**: Monitor memory usage during extended runs
- **Network Stability**: Ensure stable internet connection for API reliability
- **System Resources**: Allocate sufficient CPU and memory for real-time operations

## 🔧 Troubleshooting

### Common Issues

#### API Connection Errors
```bash
# Check credentials in .env file
# Verify platform-specific requirements
# Test network connectivity
```

#### Strategy Not Generating Signals
```bash
# Verify market hours for your symbol
# Check opening range parameters
# Review historical data availability
```

#### Database Errors
```bash
# Check file permissions
# Verify disk space
# Reset database if corrupted: rm trading_bot.db
```

### Debug Mode

Enable detailed logging:
```bash
LOG_LEVEL=DEBUG
```

### Support

For issues and questions:
1. Check the logs for error messages
2. Verify configuration settings
3. Test with paper trading first
4. Review platform-specific documentation

## 📝 License

This project is licensed under the MIT License - see the LICENSE file for details.

## ⚠️ Disclaimer

This software is for educational and research purposes only. Trading futures involves substantial risk of loss and is not suitable for all investors. Past performance is not indicative of future results. Use at your own risk and never trade with money you cannot afford to lose.

## 🤝 Contributing

Contributions are welcome! Please read the contributing guidelines and submit pull requests for any improvements.

---

**Happy Trading! 🚀📈**


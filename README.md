# Futures Trading Bot with Platform-Agnostic Architecture

A sophisticated, platform-agnostic futures trading bot that implements the Opening Range Breakthrough strategy with comprehensive risk management. Switch between different trading platforms (Binance, Tradovate, NinjaTrader) by simply changing a configuration setting.


### 3. Choose Your Trading Platform
Edit `.env` and set your preferred platform:

**For S&P 500 Futures (Recommended):**
```bash
TRADING_PLATFORM=tradovate
DEFAULT_SYMBOL=ES
TRADOVATE_USERNAME=your_username
TRADOVATE_PASSWORD=your_password
TRADOVATE_DEMO=true
```


## 🔄 Platform Switching

The bot is truly platform-agnostic. 


## 📊 Features

### Core Trading Features
- ✅ **Opening Range Breakthrough Strategy** - Configurable opening range period and breakout thresholds
- ✅ **Real-time Market Data** - Live price feeds and historical data analysis
- ✅ **Risk Management** - Position sizing, stop loss, take profit, daily limits
- ✅ **Platform Agnostic** - Switch between Binance, Tradovate, NinjaTrader
- ✅ **Bot Control** - Start/stop/pause/resume with cooldown periods
- ✅ **Emergency Stop** - Immediate halt of all trading activities

### Helper Functions (As Requested)
- ✅ **Historical Price Analysis** - Min/max prices from N hours back
- ✅ **Yesterday's Ranges** - Day and night session price ranges
- ✅ **Symbol Selection** - Configurable trading symbols
- ✅ **Cooldown Management** - Automatic pause periods after losses
- ✅ **Performance Tracking** - Win rate, P&L, drawdown analysis

### Technical Features
- ✅ **Data Caching** - SQLite database for historical data storage
- ✅ **Comprehensive Logging** - Detailed activity logs and error tracking
- ✅ **Configuration Management** - Environment-based settings
- ✅ **Thread-safe Operations** - Concurrent monitoring and execution
- ✅ **Error Handling** - Robust error recovery and reporting

## 🏗️ Architecture

### Platform-Agnostic Design
```
TradingBot
├── DataManager (Platform-agnostic data handling)
├── OpeningRangeStrategy (Pure strategy logic)
├── RiskManager (Platform-independent risk controls)
└── APIFactory → Creates platform-specific APIs
    ├── BinanceAPI (Crypto futures)
    ├── TradovateAPI (Traditional futures)
    └── NinjaTraderAPI (Desktop platform)
```

### File Structure
```
futures_trading_bot/
├── main.py                    # Main entry point
├── trading_bot.py            # Core bot orchestration
├── config.py                 # Configuration management
├── data_manager.py           # Market data handling
├── opening_range_strategy.py # Strategy implementation
├── risk_manager.py           # Risk management
├── api_interface.py          # Abstract API interface
├── api_factory.py            # Platform selection factory
├── binance_api.py            # Binance implementation
├── tradovate_api.py          # Tradovate implementation
├── ninjatrader_api.py        # NinjaTrader implementation
├── test_strategy.py          # Strategy testing
├── requirements.txt          # Dependencies
├── .env.example             # Configuration template
└── README.md                # This file
```

## 🎯 Opening Range Strategy

The bot implements a sophisticated Opening Range Breakthrough strategy:

1. **Range Establishment** - Identifies high/low during opening period (default: 30 minutes)
2. **Breakout Detection** - Monitors for price breaks above/below the range
3. **Signal Generation** - Creates buy/sell signals with confidence scoring
4. **Risk Calculation** - Determines position size based on range and account balance
5. **Exit Management** - Automatic stop loss and take profit execution

### Strategy Parameters
- `OPENING_RANGE_MINUTES` - Opening range period (default: 30)
- `BREAKOUT_THRESHOLD_PERCENT` - Minimum breakout percentage (default: 0.1%)
- `STOP_LOSS_PERCENTAGE` - Stop loss level (default: 2%)
- `TAKE_PROFIT_PERCENTAGE` - Take profit level (default: 4%)

## 🛡️ Risk Management

Comprehensive risk controls protect your capital:

- **Position Sizing** - Maximum 10% of account per trade
- **Daily Limits** - Maximum trades and loss limits per day
- **Stop Loss/Take Profit** - Automatic exit levels
- **Cooldown Periods** - Mandatory pause after losses
- **Emergency Stop** - Immediate halt capability
- **Drawdown Protection** - Maximum drawdown monitoring

## 🔧 Configuration

### Environment Variables (.env)
```bash
# Platform Selection
TRADING_PLATFORM=binance|tradovate|ninjatrader
DEFAULT_SYMBOL=BTCUSDT|ES|NQ

# Risk Management
MAX_POSITION_SIZE=0.1          # 10% max position
STOP_LOSS_PERCENTAGE=2.0       # 2% stop loss
TAKE_PROFIT_PERCENTAGE=4.0     # 4% take profit
MAX_DAILY_TRADES=10            # Max 10 trades/day
COOLDOWN_PERIOD=300            # 5 min cooldown

# Strategy Settings
OPENING_RANGE_MINUTES=30       # 30 min opening range
BREAKOUT_THRESHOLD_PERCENT=0.1         # 0.1% breakout threshold
```

### Platform-Specific Settings

**Binance (Crypto Futures):**
```bash
BINANCE_API_KEY=your_api_key
BINANCE_API_SECRET=your_api_secret
BINANCE_TESTNET=true
```

**Tradovate (S&P 500 Futures):**
```bash
TRADOVATE_USERNAME=your_username
TRADOVATE_PASSWORD=your_password
TRADOVATE_DEMO=true
```

**NinjaTrader (Desktop Platform):**
```bash
NINJATRADER_API_URL=http://localhost:8080
NINJATRADER_SIMULATION=true
```

## 📈 Usage Examples

### Strategy Testing
```bash
# Run comprehensive strategy tests
python test_strategy.py

# This tests:
# - Opening range calculation
# - Signal generation
# - Risk management
# - Platform switching
# - Data caching
```

## 🚨 Important Notes

### For S&P 500 Trading (Your Goal)
- **Recommended Platform**: Start with NinjaTrader (free simulation) for testing
- **Production Platform**: Tradovate (requires funded account for live trading)
- **Symbol**: Use `ES` for S&P 500 E-mini futures

### For Testing/Development
- **Binance Testnet**: Free testing with crypto futures
- **No real money required**: All platforms support simulation/demo modes
- **Full functionality**: All features work in test environments

### Connection Requirements
- **Tradovate**: Requires valid account credentials
- **NinjaTrader**: Requires NinjaTrader desktop application running
- **Binance**: Requires API keys (free testnet available)

## 🔍 Troubleshooting

### Common Issues

**Import Errors**: ✅ FIXED - All files are now in the root directory

**Connection Failures**: 
- Check your API credentials in `.env`
- Verify platform-specific requirements
- Use test/demo modes for initial setup

**Permission Errors**:
- Ensure API keys have futures trading permissions
- Check account funding requirements for live trading

### Testing Connection
```bash
# Test each platform
python main.py --mode test --platform binance
python main.py --mode test --platform tradovate  
python main.py --mode test --platform ninjatrader
```

## 📞 Support

The bot includes comprehensive logging and error reporting. Check `trading_bot.log` for detailed information about bot activities and any issues.

### Log Levels
- `INFO`: Normal operations and trade executions
- `WARNING`: Non-critical issues and risk management actions
- `ERROR`: Connection failures and critical errors

## 🎉 Success!

Your futures trading bot is now ready to use! The platform-agnostic architecture allows you to:

1. **Start with testing** on Binance testnet or NinjaTrader simulation
2. **Switch to S&P 500 futures** on Tradovate when ready
3. **Adapt to any platform** by simply changing configuration
4. **Scale your strategies** across multiple markets and platforms

The bot is production-ready and includes all the features you requested for professional futures trading.


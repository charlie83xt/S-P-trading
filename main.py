"""
Main entry point for the Futures Trading Bot.
"""

import argparse
import time
import signal
import sys
from datetime import datetime

from trading_bot import TradingBot
from config import Config
from debug_config import debug_print, production_print, MAGNI, CHECK, CROSS, BOT, TREND, CHART, RED, STICKS, ROCKET


def signal_handler(signum, frame):
    """Handle interrupt signals gracefully."""
    debug_print("\nReceived interrupt signal. Stopping bot...")
    if 'bot' in globals():
        bot.emergency_stop()
    sys.exit(0)

def main():
    config = Config()
    """Main function to run the trading bot."""
    parser = argparse.ArgumentParser(description='Futures Trading Bot')
    parser.add_argument('--symbol', type=str, default=config.DEFAULT_SYMBOL,
                       help='Trading symbol (default: from config)')
    parser.add_argument('--platform', type=str, choices=['binance', 'tradovate', 'ninjatrader', ' tradovate_ui'],
                       help='Trading platform (default: from config)')
    parser.add_argument('--mode', type=str, choices=['run', 'test', 'status'],
                       default='run', help='Bot mode (default: run)')
    
    args = parser.parse_args()
    
    # Set up signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    debug_print("=" * 60)
    debug_print(f"{BOT} FUTURES TRADING BOT")
    debug_print("=" * 60)
    debug_print(f"Platform: {args.platform or config.TRADING_PLATFORM}")
    debug_print(f"Symbol: {args.symbol}")
    debug_print(f"Mode: {args.mode}")
    debug_print(f"Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    debug_print("=" * 60)
    
    
    # Create bot instance
    global bot
    # bot = TradingBot(platform=args.platform)
    bot = TradingBot(config=config)
    
    
    if args.mode == 'test':
        # Test mode - check connections and basic functionality
        debug_print(f"{MAGNI} Running in TEST mode...")
        
        debug_print("Testing platform connection...")
        if bot.connect():
            debug_print(f"{CHECK} Connection successful")
            
            debug_print(f"Testing market data for {args.symbol}...")
            try:
                price = bot.data_manager.get_current_price(args.symbol)
                debug_print(f"{CHECK} Current price: {price}")
                
                debug_print("Testing historical data...")
                data = bot.data_manager.get_historical_data(args.symbol, '1m', 10)
                debug_print(f"{CHECK} Retrieved {len(data)} historical data points")
                
                debug_print("Testing strategy...")
                analysis = bot.get_market_analysis()
                debug_print(f"{CHECK} Market analysis: {len(analysis)} metrics")
                
            except Exception as e:
                print(f"{CROSS} Error during testing: {e}")
            
            bot.disconnect()
        else:
            debug_print(f"{CROSS} Connection failed")
        
        debug_print("Test completed.")
        
    elif args.mode == 'status':
        # Status mode - show current bot status
        debug_print(f"{CHART} Bot Status:")
        status = bot.get_status()
        
        for key, value in status.items():
            debug_print(f"  {key}: {value}")
    
    else:
        # Run mode - start the bot
        debug_print(f"{ROCKET} Starting trading bot...")
        
        if bot.start(args.symbol):
            debug_print(f"{CHECK} Bot started successfully")
            debug_print(f"{TREND} Monitoring market for trading opportunities...")
            debug_print("Press Ctrl+C to stop the bot")
            
            try:
                # Keep the main thread alive and show periodic status
                while bot.is_running:
                    time.sleep(30)  # Show status every 30 seconds
                    
                    status = bot.get_status()
                    debug_print(f"\n{CHART} Status Update - {datetime.now().strftime('%H:%M:%S')}")
                    debug_print(f"  Current Price: {status.get('current_price', 'N/A')}")
                    debug_print(f"  Signals Generated: {status['total_signals']}")
                    debug_print(f"  Trades Executed: {status['executed_trades']}")
                    debug_print(f"  Daily Trades: {status['risk_metrics']['daily_trades']}")
                    debug_print(f"  Daily P&L: {status['risk_metrics']['daily_pnl']:.2f}")
                    
                    if status['is_paused']:
                        debug_print(f"  {STICKS}  Bot is PAUSED")
                    
            except KeyboardInterrupt:
                print(f"\n{RED} Stopping bot...")
                bot.stop()
                print(f"{CHECK} Bot stopped successfully")
        else:
            print(f"{CROSS} Failed to start bot")

if __name__ == "__main__":
    main()


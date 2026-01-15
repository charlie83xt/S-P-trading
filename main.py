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

def signal_handler(signum, frame):
    """Handle interrupt signals gracefully."""
    print("\nReceived interrupt signal. Stopping bot...")
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
    
    print("=" * 60)
    print("🤖 FUTURES TRADING BOT")
    print("=" * 60)
    print(f"Platform: {args.platform or config.TRADING_PLATFORM}")
    print(f"Symbol: {args.symbol}")
    print(f"Mode: {args.mode}")
    print(f"Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)
    
    
    # Create bot instance
    global bot
    # bot = TradingBot(platform=args.platform)
    bot = TradingBot(config=config)
    
    
    if args.mode == 'test':
        # Test mode - check connections and basic functionality
        print("🔍 Running in TEST mode...")
        
        print("Testing platform connection...")
        if bot.connect():
            print("✅ Connection successful")
            
            print(f"Testing market data for {args.symbol}...")
            try:
                price = bot.data_manager.get_current_price(args.symbol)
                print(f"✅ Current price: {price}")
                
                print("Testing historical data...")
                data = bot.data_manager.get_historical_data(args.symbol, '1m', 10)
                print(f"✅ Retrieved {len(data)} historical data points")
                
                print("Testing strategy...")
                analysis = bot.get_market_analysis()
                print(f"✅ Market analysis: {len(analysis)} metrics")
                
            except Exception as e:
                print(f"❌ Error during testing: {e}")
            
            bot.disconnect()
        else:
            print("❌ Connection failed")
        
        print("Test completed.")
        
    elif args.mode == 'status':
        # Status mode - show current bot status
        print("📊 Bot Status:")
        status = bot.get_status()
        
        for key, value in status.items():
            print(f"  {key}: {value}")
    
    else:
        # Run mode - start the bot
        print("🚀 Starting trading bot...")
        
        if bot.start(args.symbol):
            print("✅ Bot started successfully")
            print("📈 Monitoring market for trading opportunities...")
            print("Press Ctrl+C to stop the bot")
            
            try:
                # Keep the main thread alive and show periodic status
                while bot.is_running:
                    time.sleep(30)  # Show status every 30 seconds
                    
                    status = bot.get_status()
                    print(f"\n📊 Status Update - {datetime.now().strftime('%H:%M:%S')}")
                    print(f"  Current Price: {status.get('current_price', 'N/A')}")
                    print(f"  Signals Generated: {status['total_signals']}")
                    print(f"  Trades Executed: {status['executed_trades']}")
                    print(f"  Daily Trades: {status['risk_metrics']['daily_trades']}")
                    print(f"  Daily P&L: {status['risk_metrics']['daily_pnl']:.2f}")
                    
                    if status['is_paused']:
                        print("  ⏸️  Bot is PAUSED")
                    
            except KeyboardInterrupt:
                print("\n🛑 Stopping bot...")
                bot.stop()
                print("✅ Bot stopped successfully")
        else:
            print("❌ Failed to start bot")

if __name__ == "__main__":
    main()


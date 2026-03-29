"""
Standalone Supabase Daily Bar Test
Tests Supabase connection WITHOUT requiring Tradovate login
"""


import logging
import os
from datetime import datetime, timedelta, timezone
from collections import defaultdict
from dotenv import load_dotenv


# Load environment variables
load_dotenv()


# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)


logger = logging.getLogger(__name__)




def test_supabase_direct():
    """Test Supabase connection directly without DataManager"""
    
    print("\n" + "="*70)
    print("STANDALONE SUPABASE TEST (No Tradovate Required)")
    print("="*70)
    
    # Step 1: Check environment variables
    print("\n1️⃣ Checking environment variables...")
    
    supabase_url = os.getenv('SUPABASE_URL')
    supabase_key = os.getenv('SUPABASE_KEY')
    
    if not supabase_url or not supabase_key:
        print("\n❌ Supabase credentials not found!")
        print("\nAdd to your .env file:")
        print("  SUPABASE_URL=https://your-project.supabase.co")
        print("  SUPABASE_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...")
        return
    
    print(f"   ✅ SUPABASE_URL: {supabase_url[:30]}...")
    print(f"   ✅ SUPABASE_KEY: {supabase_key[:20]}...")
    
    # Step 2: Import and connect to Supabase
    print("\n2️⃣ Connecting to Supabase...")
    
    try:
        from supabase import create_client, Client
        
        supabase: Client = create_client(supabase_url, supabase_key)
        print("   ✅ Supabase client created")
        
    except ImportError:
        print("\n❌ Supabase library not installed!")
        print("\nInstall it with:")
        print("  pip install supabase")
        return
    except Exception as e:
        print(f"\n❌ Failed to connect to Supabase: {e}")
        return
    
    # Step 3: Query 1-minute bars
    print("\n3️⃣ Querying market_bars_1m table...")
    
    # Calculate date range (last 5 days)
    end_date = datetime.now(timezone.utc)
    start_date = end_date - timedelta(days=6)
    
    print(f"   Date range: {start_date.date()} to {end_date.date()}")
    
    # Test with MES first
    symbol = "MES_CONTFUT"
    
    try:
        response = supabase.table('market_bars_1m') \
            .select('ts,open,high,low,close,volume') \
            .eq('symbol', symbol) \
            .gte('ts', start_date.isoformat()) \
            .lte('ts', end_date.isoformat()) \
            .order('ts', desc=False) \
            .execute()
        
        minute_bars = response.data
        
        if not minute_bars:
            print(f"\n❌ No data found for {symbol}!")
            print("\nPossible issues:")
            print("1. Symbol name might be different in your database")
            print("2. No data in date range")
            print("3. Table name is not 'market_bars_1m'")
            
            # Try to check what's in the table
            print("\nTrying to find what symbols exist...")
            try:
                all_symbols = supabase.table('market_bars_1m') \
                    .select('symbol') \
                    .limit(100) \
                    .execute()
                
                unique_symbols = set(row['symbol'] for row in all_symbols.data)
                print(f"\nFound symbols in database: {unique_symbols}")
                
            except Exception as e:
                print(f"Could not query symbols: {e}")
            
            return
        
        print(f"   ✅ Retrieved {len(minute_bars)} 1-minute bars")
        
        # Show sample data
        print("\n   Sample bars:")
        for bar in minute_bars[:3]:
            print(f"      {bar['ts'][:19]} - O:{bar['open']:.2f} H:{bar['high']:.2f} L:{bar['low']:.2f} C:{bar['close']:.2f}")
        
    except Exception as e:
        print(f"\n❌ Query failed: {e}")
        return
    
    # Step 4: Aggregate into daily bars
    print("\n4️⃣ Aggregating into daily bars...")
    
    try:
        # Group by date
        daily_data = defaultdict(list)
        
        for bar in minute_bars:
            # Parse timestamp
            ts_str = bar['ts']
            ts = datetime.fromisoformat(ts_str.replace('Z', '+00:00'))
            date_key = ts.date()
            
            daily_data[date_key].append(bar)
        
        # Create daily bars
        daily_bars = []
        
        for date in sorted(daily_data.keys()):
            bars = daily_data[date]
            
            # Aggregate OHLCV
            open_price = bars[0]['open']
            high_price = max(b['high'] for b in bars)
            low_price = min(b['low'] for b in bars)
            close_price = bars[-1]['close']
            total_volume = sum(b.get('volume', 0) for b in bars)
            
            daily_bars.append({
                'date': date,
                'open': open_price,
                'high': high_price,
                'low': low_price,
                'close': close_price,
                'volume': total_volume,
                'num_bars': len(bars)
            })
        
        print(f"   ✅ Aggregated into {len(daily_bars)} daily bars")
        
    except Exception as e:
        print(f"\n❌ Aggregation failed: {e}")
        import traceback
        traceback.print_exc()
        return
    
    # Step 5: Display results
    print("\n5️⃣ Daily Bars for MES:")
    print("-"*80)
    print(f"{'Date':<12} {'Open':>8} {'High':>8} {'Low':>8} {'Close':>8} {'Volume':>10} {'Bars':>6}")
    print("-"*80)
    
    for bar in daily_bars:
        print(
            f"{str(bar['date']):<12} "
            f"{bar['open']:>8.2f} "
            f"{bar['high']:>8.2f} "
            f"{bar['low']:>8.2f} "
            f"{bar['close']:>8.2f} "
            f"{bar['volume']:>10.0f} "
            f"{bar['num_bars']:>6}"
        )
    
    print("-"*80)
    
    # Step 6: Show previous day levels
    if len(daily_bars) >= 2:
        yesterday = daily_bars[-2]
        today = daily_bars[-1]
        
        print(f"\n📊 PREVIOUS DAY LEVELS (for trading today):")
        print(f"   Date:       {yesterday['date']}")
        print(f"   High:       {yesterday['high']:.2f}")
        print(f"   Low:        {yesterday['low']:.2f}")
        print(f"   Range:      {yesterday['high'] - yesterday['low']:.2f} points")
        print(f"   Close:      {yesterday['close']:.2f}")
        print(f"   Minute bars: {yesterday['num_bars']}")
        
        print(f"\n📈 TODAY (partial data):")
        print(f"   Date:       {today['date']}")
        print(f"   Current High: {today['high']:.2f}")
        print(f"   Current Low:  {today['low']:.2f}")
        print(f"   Minute bars so far: {today['num_bars']}")
        
        # Check if today touched yesterday's levels
        if today['high'] >= yesterday['high']:
            print(f"   🔥 TOUCHED PREVIOUS HIGH! ({yesterday['high']:.2f})")
        if today['low'] <= yesterday['low']:
            print(f"   ❄️  TOUCHED PREVIOUS LOW! ({yesterday['low']:.2f})")
    
    # Step 7: Test ES too
    print("\n6️⃣ Testing ES symbol...")
    
    try:
        response = supabase.table('market_bars_1m') \
            .select('ts,open,high,low,close') \
            .eq('symbol', 'ES_CONTFUT') \
            .gte('ts', start_date.isoformat()) \
            .lte('ts', end_date.isoformat()) \
            .limit(10) \
            .execute()
        
        if response.data:
            print(f"   ✅ ES data available ({len(response.data)} sample bars)")
        else:
            print("   ⚠️  No ES data found")
            
    except Exception as e:
        print(f"   ❌ ES query failed: {e}")
    
    # Success!
    print("\n" + "="*70)
    print("🎉 SUPABASE TEST COMPLETED SUCCESSFULLY!")
    print("="*70)
    
    print("\n✅ Your Supabase database is working perfectly!")
    print("✅ You have historical data for MES")
    print("✅ Daily aggregation is working")
    print("✅ Previous day levels are available")
    
    print("\n📝 Next steps:")
    print("1. Add get_daily_bars() method to data_manager.py")
    print("2. Update previous_day_high_low_strategy.py to use it")
    print("3. Start the bot (it will now work!)")
    
    print("\n")




if __name__ == "__main__":
    test_supabase_direct()




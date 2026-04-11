"""
Daily Trade Export Script

Exports your trades to CSV for backup and analysis.
Run this at the end of each trading day.
"""

import sqlite3
import pandas as pd
from datetime import datetime, timedelta
import os
import sys

# Configuration
DATABASE_PATH = 'market_data.db'  # Adjust to your actual database location
BACKUP_DIR = 'data/daily_backups'
WEEKLY_BACKUP_DIR = 'data/weekly_backups'


def ensure_directories():
    """Create backup directories if they don't exist"""
    os.makedirs(BACKUP_DIR, exist_ok=True)
    os.makedirs(WEEKLY_BACKUP_DIR, exist_ok=True)


def export_today_trades():
    """
    Export today's trades to CSV.
    
    Returns:
        str: Path to created file, or None if no trades
    """
    try:
        # Connect to database
        conn = sqlite3.connect(DATABASE_PATH)
        
        # Get today's date
        today = datetime.now().strftime('%Y-%m-%d')
        today_display = datetime.now().strftime('%B %d, %Y')  # e.g., "February 12, 2026"
        
        # Query today's trades
        query = f"""
            SELECT 
                t.*,
                COALESCE(t.strategy_name, 'Unknown') as strategy
            FROM trades_enhanced t
            WHERE DATE(ts_open) = '{today}'
            ORDER BY ts_open
        """
        
        df = pd.read_sql(query, conn)
        conn.close()
        
        if len(df) == 0:
            print(f"📊 No trades found for {today_display}")
            return None
        
        # Create filename
        filename = f"{BACKUP_DIR}/trades_{today}.csv"
        
        # Export to CSV
        df.to_csv(filename, index=False)
        
        # Calculate summary statistics
        total_trades = len(df)
        winning_trades = len(df[df['pnl'] > 0]) if 'pnl' in df.columns else 0
        losing_trades = len(df[df['pnl'] < 0]) if 'pnl' in df.columns else 0
        total_pnl = df['pnl'].sum() if 'pnl' in df.columns else 0
        
        print(f"\n✅ Exported {total_trades} trades for {today_display}")
        print(f"   📁 File: {filename}")
        print(f"\n   📈 Summary:")
        print(f"      Winning trades: {winning_trades}")
        print(f"      Losing trades: {losing_trades}")
        print(f"      Total P&L: ${total_pnl:.2f}")
        
        if winning_trades + losing_trades > 0:
            win_rate = (winning_trades / (winning_trades + losing_trades)) * 100
            print(f"      Win rate: {win_rate:.1f}%")

        # Show Breakdown by Strategy
        if 'strategy' in df.columns:
            print(f"\n  📊 By Strategy:")
            for strategy in df["strategy"].unique():
                strategy_df = df[df['strategy'] == strategy]
                strat_wins = len(strategy_df[strategy_df['pnl'] > 0])
                strat_total =  len(strategy_df)
                strat_pnl = strategy_df['pnl'].sum()
                strat_wr = (strat_wins / strat_total * 100) if strat_total > 0 else 0

                print(f"    {strategy}: {strat_total} trades | "
                      f"WR: {strat_wr:.1f}% | P&L: ${strat_pnl:.2f}")
        
        return filename
        
    except sqlite3.Error as e:
        print(f"❌ Database error: {e}")
        return None
    except Exception as e:
        print(f"❌ Export error: {e}")
        return None


def export_week_summary():
    """
    Export this week's trades summary.
    Run this on Fridays or end of trading week.
    """
    try:
        conn = sqlite3.connect(DATABASE_PATH)
        
        # Get this week's date range
        today = datetime.now()
        week_start = today - timedelta(days=today.weekday())  # Monday
        week_end = week_start + timedelta(days=4)  # Friday
        
        week_label = week_start.strftime('%Y-W%U')  # e.g., "2026-W06"
        week_display = f"{week_start.strftime('%b %d')} - {week_end.strftime('%b %d, %Y')}"
        
        query = f"""
            SELECT * FROM trades_enhanced
            WHERE DATE(ts_open) BETWEEN '{week_start.strftime('%Y-%m-%d')}' 
                                       AND '{week_end.strftime('%Y-%m-%d')}'
            ORDER BY ts_open
        """
        
        df = pd.read_sql(query, conn)
        conn.close()
        
        if len(df) == 0:
            print(f"\n📊 No trades found for week {week_display}")
            return None
        
        # Export weekly summary
        filename = f"{WEEKLY_BACKUP_DIR}/trades_{week_label}.csv"
        df.to_csv(filename, index=False)
        
        # Calculate weekly statistics
        total_trades = len(df)
        total_pnl = df['pnl'].sum() if 'pnl' in df.columns else 0
        winning_days = 0
        
        # Group by day
        if 'ts_open' in df.columns and 'pnl' in df.columns:
            df['date'] = pd.to_datetime(df['ts_open']).dt.date
            daily_pnl = df.groupby('date')['pnl'].sum()
            winning_days = len(daily_pnl[daily_pnl > 0])
        
        print(f"\n✅ Exported weekly summary for {week_display}")
        print(f"   📁 File: {filename}")
        print(f"\n   📊 Weekly Statistics:")
        print(f"      Total trades: {total_trades}")
        print(f"      Total P&L: ${total_pnl:.2f}")
        print(f"      Winning days: {winning_days}/5")
        
        return filename
        
    except Exception as e:
        print(f"❌ Weekly export error: {e}")
        return None


def backup_entire_database():
    """
    Create a complete backup of the database.
    Good to run weekly or before major changes.
    """
    try:
        today = datetime.now().strftime('%Y-%m-%d')
        backup_path = f"{WEEKLY_BACKUP_DIR}/trade_history_backup_{today}.db"
        
        # Copy database file
        import shutil
        shutil.copy2(DATABASE_PATH, backup_path)
        
        # Get file size
        size_mb = os.path.getsize(backup_path) / (1024 * 1024)
        
        print(f"\n✅ Database backup created")
        print(f"   📁 File: {backup_path}")
        print(f"   💾 Size: {size_mb:.2f} MB")
        
        return backup_path
        
    except Exception as e:
        print(f"❌ Database backup error: {e}")
        return None


def main():
    """Main export function"""
    print("=" * 60)
    print("📊 DAILY TRADE EXPORT TOOL")
    print("=" * 60)
    
    # Ensure directories exist
    ensure_directories()
    
    # Check if database exists
    if not os.path.exists(DATABASE_PATH):
        print(f"\n❌ Database not found: {DATABASE_PATH}")
        print("   Make sure you're in the correct directory.")
        sys.exit(1)
    
    # Export today's trades
    print("\n🔄 Exporting today's trades...")
    export_today_trades()
    
    # Check if it's Friday (end of week)
    if datetime.now().weekday() == 4:  # Friday = 4
        print("\n🔄 It's Friday! Exporting weekly summary...")
        export_week_summary()
        
        print("\n🔄 Creating weekly database backup...")
        backup_entire_database()
    
    print("\n" + "=" * 60)
    print("✅ Export complete!")
    print("=" * 60)


if __name__ == '__main__':
    main()

#!/usr/bin/env python3
"""Query local analytics database for insights"""


import sqlite3
import pandas as pd
from datetime import datetime, timedelta
from debug_config import debug_print, production_print


DB_PATH = 'data/db/market_data.db'


def get_recent_performance(days=7):
    """Get performance for last N days"""
    conn = sqlite3.connect(DB_PATH)
   
    query = f"""
        SELECT
            DATE(ts_open) as date,
            COUNT(*) as trades,
            SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) as wins,
            SUM(CASE WHEN pnl < 0 THEN 1 ELSE 0 END) as losses,
            SUM(pnl) as total_pnl,
            AVG(pnl) as avg_pnl,
            MAX(pnl) as max_win,
            MIN(pnl) as max_loss
        FROM trades_enhanced
        WHERE DATE(ts_open) >= date('now', '-{days} days')
        GROUP BY DATE(ts_open)
        ORDER BY date DESC
    """
   
    df = pd.read_sql(query, conn)
    conn.close()
   
    if len(df) == 0:
        debug_print(f"📊 No trades in last {days} days")
        return
   
    debug_print(f"\n{'='*70}")
    debug_print(f"📊 PERFORMANCE - LAST {days} DAYS")
    debug_print(f"{'='*70}\n")
   
    for _, row in df.iterrows():
        win_rate = (row['wins'] / row['trades'] * 100) if row['trades'] > 0 else 0
       
        pnl_emoji = "🟢" if row['total_pnl'] > 0 else "🔴"
       
        debug_print(f"{row['date']}")
        debug_print(f"  Trades: {row['trades']} | W:{row['wins']} L:{row['losses']} | WR: {win_rate:.1f}%")
        debug_print(f"  P&L: {pnl_emoji} ${row['total_pnl']:.2f} (Avg: ${row['avg_pnl']:.2f})")
        debug_print(f"  Range: ${row['max_loss']:.2f} to ${row['max_win']:.2f}\n")
   
    # Overall stats
    total_trades = df['trades'].sum()
    total_wins = df['wins'].sum()
    total_pnl = df['total_pnl'].sum()
    overall_wr = (total_wins / total_trades * 100) if total_trades > 0 else 0
   
    debug_print(f"{'='*70}")
    debug_print(f"TOTALS: {total_trades} trades | {total_wins}W | WR: {overall_wr:.1f}% | P&L: ${total_pnl:.2f}")
    debug_print(f"{'='*70}\n")


def get_strategy_comparison():
    """Compare different strategies"""
    conn = sqlite3.connect(DB_PATH)
   
    query = """
        SELECT
            s.strategy_name,
            COUNT(t.trade_id) as trades,
            SUM(CASE WHEN t.pnl > 0 THEN 1 ELSE 0 END) as wins,
            SUM(t.pnl) as total_pnl,
            AVG(t.pnl) as avg_pnl,
            MAX(t.pnl) as max_win,
            MIN(t.pnl) as max_loss
        FROM signals s
        LEFT JOIN trades_enhanced t ON s.signal_id = t.signal_id
        WHERE s.executed = 1
        AND DATE(s.ts) >= date('now', '-30 days')
        GROUP BY s.strategy_name
    """
   
    df = pd.read_sql(query, conn)

    # Check if we got data BEFORE closing connection
    if len(df) == 0:
        debug_print("📊 No strategy data in signals table, trying trades_enhanced...")
        
        # Try to get strategy from trades_enhanced directly
        fallback_query = """
            SELECT
                COALESCE(strategy_name, 'Unknown') as strategy_name,
                COUNT(*) as trades,
                SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) as wins,
                SUM(pnl) as total_pnl,
                AVG(pnl) as avg_pnl,
                MAX(pnl) as max_win,
                MIN(pnl) as max_loss
            FROM trades_enhanced
            WHERE DATE(ts_open) >= date('now', '-30 days')
            GROUP BY COALESCE(strategy_name, 'Unknown')
        """
        
        df = pd.read_sql(fallback_query, conn)

    conn.close()
    
    if len(df) == 0 or df.iloc[0]['trades'] == 0:
        debug_print("📊 No trade data available")
        return

   
    debug_print(f"\n{'='*70}")
    debug_print(f"📊 STRATEGY COMPARISON - LAST 30 DAYS")
    debug_print(f"{'='*70}\n")
   
    for _, row in df.iterrows():
        if row['trades'] == 0:
            continue
           
        win_rate = (row['wins'] / row['trades'] * 100)
       
        debug_print(f"{row['strategy_name']}")
        debug_print(f"  Trades: {row['trades']} | Win Rate: {win_rate:.1f}%")
        debug_print(f"  Total P&L: ${row['total_pnl']:.2f}")
        debug_print(f"  Avg P&L: ${row['avg_pnl']:.2f}")
        debug_print(f"  Best/Worst: ${row['max_win']:.2f} / ${row['max_loss']:.2f}\n")


def get_time_of_day_analysis():
    """Analyze performance by hour"""
    conn = sqlite3.connect(DB_PATH)
   
    query = """
        SELECT
            CAST(strftime('%H', ts_open) AS INTEGER) as hour,
            COUNT(*) as trades,
            SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) as wins,
            AVG(pnl) as avg_pnl
        FROM trades_enhanced
        WHERE DATE(ts_open) >= date('now', '-30 days')
        GROUP BY hour
        ORDER BY hour
    """
   
    df = pd.read_sql(query, conn)
    conn.close()
   
    if len(df) == 0:
        debug_print("📊 No time-of-day data yet")
        return
   
    debug_print(f"\n{'='*70}")
    debug_print(f"📊 PERFORMANCE BY HOUR (UTC)")
    debug_print(f"{'='*70}\n")
   
    for _, row in df.iterrows():
        win_rate = (row['wins'] / row['trades'] * 100) if row['trades'] > 0 else 0
       
        # Convert hour to int (SQLite returns as float)
        hour_utc = int(row['hour'])
        et_hour = (hour_utc - 5) % 24
       
        debug_print(f"{hour_utc:02d}:00 UTC ({et_hour:02d}:00 ET) | "
              f"Trades: {row['trades']} | WR: {win_rate:.1f}% | "
              f"Avg: ${row['avg_pnl']:.2f}")


def export_for_analysis():
    """Export all data to CSV for external analysis"""
    conn = sqlite3.connect(DB_PATH)
   
    # Export trades
    trades_df = pd.read_sql("SELECT * FROM trades_enhanced", conn)
    trades_df.to_csv('data/trades_export.csv', index=False)
    debug_print(f"✅ Exported {len(trades_df)} trades to data/trades_export.csv")
   
    # Export signals
    signals_df = pd.read_sql("SELECT * FROM signals", conn)
    signals_df.to_csv('data/signals_export.csv', index=False)
    debug_print(f"✅ Exported {len(signals_df)} signals to data/signals_export.csv")
   
    conn.close()


def main():
    """Run all analytics"""
    debug_print("\n" + "="*70)
    debug_print("📊 TRADING BOT ANALYTICS")
    debug_print("="*70)
   
    get_recent_performance(days=7)
    get_strategy_comparison()
    get_time_of_day_analysis()
   
    debug_print("\n" + "="*70)
    debug_print("💾 EXPORT")
    debug_print("="*70 + "\n")
    export_for_analysis()


if __name__ == '__main__':
    main()

"""
Enhanced trade analytics and data collection for ML feature engineering.
Builds on existing market_data.db infrastructure.
"""


import sqlite3
import json
import os
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional
import logging


class TradeAnalytics:
    """
    Collects and stores trade data, signals, and market context
    for ML model training and strategy optimization.
    """
    
    def __init__(self, db_path='market_data.db', use_supabase=True):
        """Use same DB as data_manager for efficiency"""
        self.db_path = db_path
        self.logger = logging.getLogger(__name__)
        self._init_analytics_tables()

        # Remote Supabase (Permanent, accessible)
        self.supabase_enabled = use_supabase
        if use_supabase:
            from supabase import create_client
            self.supabase = create_client(
                os.getenv("SUPABASE_URL"),
                os.getenv("SUPABASE_KEY")
            )
    
    def _init_analytics_tables(self):
        """Create analytics tables if they don't exist"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Table 1: Signals (both executed and skipped)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS signals (
                signal_id TEXT PRIMARY KEY,
                ts TEXT NOT NULL,
                ts_epoch REAL NOT NULL,
                symbol TEXT NOT NULL,
                signal_type TEXT NOT NULL,  -- BUY/SELL
                signal_price REAL NOT NULL,
                executed BOOLEAN NOT NULL,
                skip_reason TEXT,
                
                -- Opening Range context
                or_low REAL,
                or_high REAL,
                or_range REAL,
                minutes_since_or_start REAL,
                
                -- Market context at signal time
                volatility REAL,
                time_of_day TEXT,
                day_of_week INTEGER,
                
                -- Metadata
                strategy_name TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Table 2: Enhanced trades (links to signals)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS trades_enhanced (
                trade_id TEXT PRIMARY KEY,
                signal_id TEXT REFERENCES signals(signal_id),
                fill_id TEXT,
                attempt_id TEXT,
                
                symbol TEXT NOT NULL,
                side TEXT NOT NULL,
                qty INTEGER NOT NULL,
                
                entry_price REAL NOT NULL,
                exit_price REAL,
                pnl REAL,
                pnl_points REAL,
                
                ts_open TEXT NOT NULL,
                ts_close TEXT,
                duration_seconds INTEGER,
                
                entry_reason TEXT,
                exit_reason TEXT,
                
                -- Execution quality
                entry_slippage_points REAL,
                exit_slippage_points REAL,
                signal_to_fill_ms INTEGER,
                
                -- Market context
                entry_volatility REAL,
                exit_volatility REAL,
                market_context TEXT,  -- JSON blob
                
                status TEXT,  -- opened/closed
                dry_run BOOLEAN,
                
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Table 3: Daily summary stats
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS daily_stats (
                date TEXT PRIMARY KEY,
                symbol TEXT,
                
                total_signals INTEGER,
                signals_executed INTEGER,
                signals_skipped INTEGER,
                
                total_trades INTEGER,
                winning_trades INTEGER,
                losing_trades INTEGER,
                
                total_pnl REAL,
                max_win REAL,
                max_loss REAL,
                avg_win REAL,
                avg_loss REAL,
                
                win_rate REAL,
                profit_factor REAL,
                
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Indexes for fast queries
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_signals_ts ON signals(ts_epoch)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_signals_symbol ON signals(symbol)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_trades_symbol ON trades_enhanced(symbol)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_trades_ts ON trades_enhanced(ts_open)')
        
        conn.commit()
        conn.close()
        self.logger.info("Analytics tables initialized in %s", self.db_path)
    
    def log_signal(self, 
                   signal_id: str,
                   symbol: str,
                   signal_type: str,
                   price: float,
                   executed: bool,
                   or_bounds: Optional[tuple] = None,
                   volatility: Optional[float] = None,
                   skip_reason: Optional[str] = None,
                   strategy_name: str = "OpeningRange"):
        """
        Log every signal generated (executed or not).
        This is CRITICAL for ML - we need to know what we DIDN'T trade too!
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        now = datetime.now(timezone.utc)
        ts_epoch = now.timestamp()
        
        or_low, or_high, or_range = None, None, None
        if or_bounds and len(or_bounds) >= 2:
            or_low, or_high = or_bounds[0], or_bounds[1]
            or_range = or_high - or_low
        
        cursor.execute('''
            INSERT INTO signals (
                signal_id, ts, ts_epoch, symbol, signal_type, signal_price,
                executed, skip_reason, or_low, or_high, or_range,
                volatility, time_of_day, day_of_week, strategy_name
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            signal_id,
            now.isoformat(),
            ts_epoch,
            symbol,
            signal_type,
            price,
            executed,
            skip_reason,
            or_low,
            or_high,
            or_range,
            volatility,
            now.strftime('%H:%M'),
            now.weekday(),
            strategy_name
        ))
        
        conn.commit()
        conn.close()
    
    def log_trade(self, trade_record: Dict[str, Any]):
        """
        Log a completed or ongoing trade.
        Links to signal_id for full context.
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Calculate metrics
        pnl_points = None
        if trade_record.get('exit_price') and trade_record.get('entry_price'):
            side = trade_record.get('side', '').upper()
            entry = float(trade_record['entry_price'])
            exit_p = float(trade_record['exit_price'])
            
            if side == 'BUY':
                pnl_points = exit_p - entry
            else:  # SELL
                pnl_points = entry - exit_p
        
        cursor.execute('''
            INSERT OR REPLACE INTO trades_enhanced (
                trade_id, signal_id, fill_id, attempt_id,
                symbol, side, qty,
                entry_price, exit_price, pnl, pnl_points,
                ts_open, ts_close, duration_seconds,
                entry_reason, exit_reason,
                market_context, status, dry_run
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            trade_record.get('trade_id') or trade_record.get('fill_id'),
            trade_record.get('signal_id'),
            trade_record.get('fill_id'),
            trade_record.get('attempt_id'),
            trade_record['symbol'],
            trade_record['side'],
            trade_record['qty'],
            trade_record['entry_price'],
            trade_record.get('exit_price'),
            trade_record.get('pnl'),
            pnl_points,
            trade_record['ts'],
            trade_record.get('ts_close'),
            trade_record.get('duration_seconds'),
            trade_record.get('reason'),
            trade_record.get('exit_reason'),
            json.dumps(trade_record.get('market_context', {})),
            trade_record.get('status', 'opened'),
            trade_record.get('dry', False)
        ))
        
        conn.commit()
        conn.close()
    
    def get_win_rate(self, days: int = 30) -> Dict[str, Any]:
        """Calculate win rate and stats for last N days"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT 
                COUNT(*) as total,
                SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) as wins,
                SUM(CASE WHEN pnl < 0 THEN 1 ELSE 0 END) as losses,
                AVG(pnl) as avg_pnl,
                SUM(pnl) as total_pnl,
                AVG(CASE WHEN pnl > 0 THEN pnl END) as avg_win,
                AVG(CASE WHEN pnl < 0 THEN pnl END) as avg_loss
            FROM trades_enhanced
            WHERE status = 'closed'
            AND date(ts_open) >= date('now', '-' || ? || ' days')
        ''', (days,))
        
        row = cursor.fetchone()
        conn.close()
        
        if not row or row[0] == 0:
            return {'trades': 0, 'win_rate': 0, 'message': 'No trades yet'}
        
        total, wins, losses = row[0], row[1] or 0, row[2] or 0
        avg_pnl, total_pnl = row[3] or 0, row[4] or 0
        avg_win, avg_loss = row[5] or 0, row[6] or 0
        
        win_rate = (wins / total * 100) if total > 0 else 0
        profit_factor = abs(avg_win / avg_loss) if avg_loss else 0
        
        return {
            'trades': total,
            'wins': wins,
            'losses': losses,
            'win_rate': round(win_rate, 2),
            'total_pnl': round(total_pnl, 2),
            'avg_pnl': round(avg_pnl, 2),
            'avg_win': round(avg_win, 2),
            'avg_loss': round(avg_loss, 2),
            'profit_factor': round(profit_factor, 2)
        }


    def get_strategy_performance(self, days: int = 30) -> Dict[str, Any]:
        """
        Compare performance across all strategies.
        Returns dict with strategy names as keys.
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
    
        cursor.execute('''
            SELECT
                s.strategy_name,
                COUNT(t.trade_id) as total_trades,
                SUM(CASE WHEN t.pnl > 0 THEN 1 ELSE 0 END) as wins,
                SUM(CASE WHEN t.pnl < 0 THEN 1 ELSE 0 END) as losses,
                AVG(t.pnl) as avg_pnl,
                SUM(t.pnl) as total_pnl,
                AVG(CASE WHEN t.pnl > 0 THEN t.pnl END) as avg_win,
                AVG(CASE WHEN t.pnl < 0 THEN t.pnl END) as avg_loss,
                MAX(t.pnl) as max_win,
                MIN(t.pnl) as max_loss
            FROM signals s
            LEFT JOIN trades_enhanced t ON s.signal_id = t.signal_id
            WHERE s.executed = 1
            AND date(s.ts) >= date('now', '-' || ? || ' days')
            GROUP BY s.strategy_name
        ''', (days,))
    
        results = {}
        for row in cursor.fetchall():
            strategy_name = row[0]
            total, wins, losses = row[1], row[2] or 0, row[3] or 0
            avg_pnl, total_pnl = row[4] or 0, row[5] or 0
            avg_win, avg_loss = row[6] or 0, row[7] or 0
            max_win, max_loss = row[8] or 0, row[9] or 0
        
            win_rate = (wins / total * 100) if total > 0 else 0
            profit_factor = abs(avg_win / avg_loss) if avg_loss != 0 else 0
        
            # Calculate Sharpe ratio (simplified)
            std_dev = self._get_pnl_std(strategy_name, days, conn)
            sharpe = (avg_pnl / std_dev) if std_dev > 0 else 0
        
            results[strategy_name] = {
                'trades': total,
                'wins': wins,
                'losses': losses,
                'win_rate': round(win_rate, 2),
                'total_pnl': round(total_pnl, 2),
                'avg_pnl': round(avg_pnl, 2),
                'avg_win': round(avg_win, 2),
                'avg_loss': round(avg_loss, 2),
                'max_win': round(max_win, 2),
                'max_loss': round(max_loss, 2),
                'profit_factor': round(profit_factor, 2),
                'sharpe_ratio': round(sharpe, 2)
            }
    
        conn.close()
        return results


    def _get_pnl_std(self, strategy_name: str, days: int, conn) -> float:
        """Calculate standard deviation of PnL for Sharpe ratio"""
        cursor = conn.cursor()
        cursor.execute('''
            SELECT t.pnl
            FROM signals s
            JOIN trades_enhanced t ON s.signal_id = t.signal_id
            WHERE s.strategy_name = ?
            AND t.status = 'closed'
            AND date(s.ts) >= date('now', '-' || ? || ' days')
        ''', (strategy_name, days))
    
        pnls = [row[0] for row in cursor.fetchall() if row[0] is not None]
    
        if len(pnls) < 2:
            return 0.0
    
        mean = sum(pnls) / len(pnls)
        variance = sum((x - mean) ** 2 for x in pnls) / len(pnls)
        return variance ** 0.5



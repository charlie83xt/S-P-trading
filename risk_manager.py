"""
Risk Management Module for the Trading Bot.
"""

from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple, Any
import logging
import os, json
import threading
from config import Config
from debug_config import CHECK, CROSS

class RiskManager:
    """
    Risk management system for controlling trading exposure and losses.
    """
    
    def __init__(self, config: Config, max_position_size: float = 0.1, stop_loss_pct: float = 2.0,
                 take_profit_pct: float = 4.0, max_daily_trades: int = 10,
                 max_daily_loss: float = 5.0, cooldown_period: int = 300):
        """
        Initialize Risk Manager.
        
        Args:
            max_position_size: Maximum position size as percentage of account (default: 10%)
            stop_loss_pct: Stop loss percentage (default: 2%)
            take_profit_pct: Take profit percentage (default: 4%)
            max_daily_trades: Maximum number of trades per day (default: 10)
            max_daily_loss: Maximum daily loss percentage (default: 5%)
            cooldown_period: Cooldown period in seconds after a loss (default: 300)
        """
        self.max_position_size = max_position_size
        self.stop_loss_pct = stop_loss_pct
        self.take_profit_pct = take_profit_pct
        self.max_daily_trades = max_daily_trades
        self.max_daily_loss = max_daily_loss
        self.cooldown_period = cooldown_period
        self.config = config
        
        # Trading state tracking
        self.daily_trades = 0
        self.daily_pnl = 0.0
        self.last_trade_time = None
        self.last_loss_time = None
        self.current_positions = {}
        # self.trade_history = []
        self.trade_history: List[Dict[str, Any]] = []

        self.instant_close = "hold"
        self.dry_run_mode = "hold"
        
        self.logger = logging.getLogger(__name__)
        
        self.history_path: str | None = None
        self._hist_lock = threading.Lock() 
        # Reset daily counters if it's a new day
        self._check_new_day()

        # running P&L and virtual positions
        self.positions: dict[str, dict] = {} # {symbol: {"qty": 0, "avg_price": 0.0, "unrealised": 0.0}}
        self.realized_pnl: float = 0.0
        self.daily_pnl: float = 0.0
        self._last_reset_date = datetime.utcnow().date()
        # ES default multiplier (adjust per symbol if we want)
        self.contract_multipliers: dict[str, float] = getattr(config, 'CONTRACT_MULTIPLIERS', {"ES": 50.0, "MES": 5.0, "NQ": 20.0, "MNQ": 2.0})

        self.wins = 0
        self.losses = 0
        self.vol = {}

        # Trailing stop settings — tightened for sniper exits
        self.use_trailing_stops = True
        self.trail_activation_points = 4.0  # activate after 4 pts profit (was 2.0)
        self.trail_distance_points = 2.5    # trail 2.5 pts behind (was 1.5)

        # Track highest/lowest price per position
        self.position_extremes: dict = {}

        # Sniper exit state per symbol
        self.position_entry_times: dict  = {}   # sym -> datetime (UTC) when position opened
        self.position_breakeven_set: dict = {}  # sym -> bool, True once breakeven stop armed
    
    def _check_new_day(self):
        """Check if it's a new trading day and reset daily counters."""
        current_date = datetime.now().date()
        
        if hasattr(self, '_last_reset_date') and self._last_reset_date == current_date:
            return
        
        self.daily_trades = 0
        self.daily_pnl = 0.0
        self._last_reset_date = current_date
        
        self.logger.info(f"Daily counters reset for {current_date}")
    
    def validate_trade(self, signal: Dict, account_balance: float, current_price: float) -> Tuple[bool, str, float]:
        """
        Validate if a trade should be executed based on risk parameters.
        
        Args:
            signal: Trading signal dictionary
            account_balance: Current account balance
            current_price: Current market price
            
        Returns:
            Tuple of (is_valid, reason, suggested_quantity)
        """
        self._check_new_day()
        
        # Check daily trade limit
        if self.daily_trades >= self.max_daily_trades:
            return False, f"Daily trade limit reached ({self.max_daily_trades})", 0.0
        
        # Check daily loss limit
        daily_loss_pct = abs(self.daily_pnl) / account_balance * 100 if account_balance > 0 else 0
        if self.daily_pnl < 0 and daily_loss_pct >= self.max_daily_loss:
            return False, f"Daily loss limit reached ({self.max_daily_loss}%)", 0.0
        
        # Check cooldown period after loss
        if self.last_loss_time and self._is_in_cooldown():
            remaining_cooldown = self.cooldown_period - (datetime.now() - self.last_loss_time).total_seconds()
            return False, f"In cooldown period ({remaining_cooldown:.0f}s remaining)", 0.0
        
        # Check for existing position in same symbol
        symbol = signal['symbol']
        qty_now = self.get_position_qty(symbol)
        if qty_now != 0:
            side = (signal.get("type") or signal.get("side") or "").upper()
            is_close = (qty_now > 0 and side == "SELL") or (qty_now < 0 and side == "BUY")
            if not is_close:
                    return False, f"Already have position in {symbol}", 0.0
        
        # Calculate suggested position size
        suggested_quantity = self._calculate_position_size(account_balance, current_price, signal)
        
        if suggested_quantity <= 0:
            return False, "Calculated position size is zero or negative", 0.0
        
        return True, "Trade validated", suggested_quantity

    def update_volatility(self, symbol: str, price:float, alpha: float = 0.05) -> float:
        """
        EWMA of absolute price changes in *points* (ATR-ish from ticks/loop prices).
        Returns current volatility estimate in points
        """

        sym = (symbol or "").upper()
        px = float(price)

        st = self.vol.get(sym)
        if not st:
            self.vol[sym] = {"last_px": px, "ewma_abs": 0.0}
            return 0.0

        last_px = float(st["last_px"])
        abs_move = abs(px - last_px)

        ewma = float(st["ewma_abs"])
        ewma = (1 - alpha) * ewma + alpha * abs_move

        st["last_px"] = px
        st["ewma_abs"] = ewma
        return ewma

    def calculate_dynamic_stops(self, symbol: str, current_price: float) -> tuple[float, float]:
        """ 
        Calculate adaptive stop/take points based on recent volatility. 
        Returns: (stop_points, take_points)
        """

        vol = self.update_volatility(symbol, current_price, alpha=0.05)

        sym_norm = self._norm_sym(symbol)
        is_nq = sym_norm in ("NQ", "MNQ")

        if is_nq:
            # MNQ/NQ move ~4x MES per point-equivalent; give D its structural room.
            stop_loss_base_points = getattr(self.config, "NQ_STOP_LOSS_BASE_POINTS", 10.0) 
            take_profit_base_points = getattr(self.config, "NQ_TAKE_PROFIT_BASE_POINTS", 15.0)
            volatility_stop_multiplier = getattr(self.config, "VOLATILITY_STOP_MULTIPLIER", 2.5)
            volaility_take_multiplier = getattr(self.config, "VOLATILITY_TAKE_MULTIPLIER", 4.0)
            max_stop_loss_points = getattr(self.config, "NQ_MAX_STOP_LOSS_POINTS", 30.0)
            min_stop_loss_point = getattr(self.config, "NQ_MIN_STOP_LOSS_POINTS", 6.0)
            max_take_profit_points = getattr(self.config, "NQ_MAX_TAKE_PROFIT_POINTS", 45.0)
            min_take_profit_points  = getattr(self.config, "NQ_MIN_TAKE_PROFIT_POINTS", 10.0)
        
        else:

            stop_loss_base_points = getattr(self.config, "STOP_LOSS_BASE_POINTS", 4.0) 
            take_profit_base_points = getattr(self.config, "TAKE_PROFIT_BASE_POINTS", 6.0)
            volatility_stop_multiplier = getattr(self.config, "VOLATILITY_STOP_MULTIPLIER", 2.5)
            volaility_take_multiplier = getattr(self.config, "VOLATILITY_TAKE_MULTIPLIER", 4.0)
            max_stop_loss_points = getattr(self.config, "MAX_STOP_LOSS_POINTS", 12.0)
            min_stop_loss_point = getattr(self.config, "MIN_STOP_LOSS_POINTS", 2.0)
            max_take_profit_points = getattr(self.config, "MAX_TAKE_PROFIT_POINTS", 20.0)
            min_take_profit_points  = getattr(self.config, "MIN_TAKE_PROFIT_POINTS", 4.0)

        
        stop_pts = max( 
            min_stop_loss_point, 
            min( 
                max_stop_loss_points, 
                max(stop_loss_base_points, vol * volatility_stop_multiplier) 
            ) 
        )

        # After computing stop_pts from volatility:
        # If the signal provided a structure-based stop, use it as the floor
        pos = self.positions.get(self._norm_sym(symbol), {})
        signal_stop = pos.get("stop_est_points")
        if signal_stop and float(signal_stop) > 0:
            if is_nq:
                stop_pts = min(float(signal_stop), max_stop_loss_points) # trust
            else:
                stop_pts = min(stop_pts, float(signal_stop))
                # stop_pts = float(signal_stop)


        take_pts = max( 
            min_take_profit_points, 
            min( 
                max_take_profit_points, 
                max(take_profit_base_points, vol * volaility_take_multiplier) 
            ) 
        )

        # Ensure minimum risk/reward ratio (target >= 1.2x stop) 
        if take_pts < stop_pts * 1.2: 
            take_pts = stop_pts * 1.5 
        return stop_pts, take_pts

    
    def _calculate_position_size(self, account_balance: float, current_price: float, signal: Dict) -> float:
        """
        Calculate appropriate position size based on risk parameters.
        """
        max_position_value = account_balance * self.max_position_size
        
        if 'range_high' in signal and 'range_low' in signal:
            if signal['type'] == 'BUY':
                stop_loss_price = signal['range_low'] * 0.999
                risk_per_unit = current_price - stop_loss_price
            else:
                stop_loss_price = signal['range_high'] * 1.001
                risk_per_unit = stop_loss_price - current_price
            
            max_risk_amount = account_balance * (self.stop_loss_pct / 100)
            
            if risk_per_unit > 0:
                risk_based_quantity = max_risk_amount / risk_per_unit
            else:
                risk_based_quantity = 0
        else:
            risk_based_quantity = max_position_value / current_price
        
        balance_based_quantity = max_position_value / current_price
        suggested_quantity = min(risk_based_quantity, balance_based_quantity)
        
        min_quantity = 0.001
        
        return max(suggested_quantity, min_quantity) if suggested_quantity > 0 else 0
    
    def _is_in_cooldown(self) -> bool:
        """Check if currently in cooldown period."""
        if self.last_loss_time is None:
            return False
        
        time_since_loss = datetime.now() - self.last_loss_time
        return time_since_loss.total_seconds() < self.cooldown_period
    
    def record_trade_entry(self, symbol: str, side: str, quantity: float, price: float, order_id: str = None):
        self.logger.warning("record_trade_entry() legacy call ignored; use paper_fill()")
    
    def record_trade_exit(self, symbol: str, exit_price: float, exit_reason: str = "manual"):
        self.logger.warning("record_trade_exit() legacy call ignored; use paper_fill()")
    
    def check_stop_loss_take_profit(self, symbol: str, current_price: float) -> Optional[str]:
        stop_pts = getattr(self.config, "STOP_LOSS_POINTS", None)
        take_pts = getattr(self.config, "TAKE_PROFIT_POINTS", None)

        if stop_pts is not None and take_pts is not None:
            return self.check_exit_points(symbol, current_price, stop_pts, take_pts)

        return None 

        if symbol not in self.current_positions:
            return None
        
    
    def get_risk_metrics(self) -> Dict:
        """
        Get current risk metrics and statistics.
        """
        self._check_new_day()
        
        closed_trades = [t for t in self.trade_history if t['status'] == 'closed']
        winning_trades = [t for t in closed_trades if t.get('pnl', 0) > 0]
        
        win_rate = len(winning_trades) / len(closed_trades) * 100 if closed_trades else 0
        
        total_pnl = sum(t.get('pnl', 0) for t in closed_trades)
        avg_pnl = total_pnl / len(closed_trades) if closed_trades else 0
        
        running_pnl = 0
        peak = 0
        max_drawdown = 0
        
        for trade in closed_trades:
            running_pnl += trade.get('pnl', 0)
            if running_pnl > peak:
                peak = running_pnl
            drawdown = peak - running_pnl
            if drawdown > max_drawdown:
                max_drawdown = drawdown
        
        return {
            'daily_trades': self.daily_trades,
            'max_daily_trades': self.max_daily_trades,
            'daily_pnl': self.daily_pnl,
            'max_daily_loss_pct': self.max_daily_loss,
            'current_positions': sum(1 for p in self.positions.values() if int(p.get("qty") or 0) != 0),
            'total_trades': len(closed_trades),
            'win_rate': win_rate,
            'avg_pnl': avg_pnl,
            'max_drawdown': max_drawdown,
            'in_cooldown': self._is_in_cooldown(),
            'cooldown_remaining': max(0, self.cooldown_period - (datetime.now() - self.last_loss_time).total_seconds()) if self.last_loss_time else 0
        }
    
    def emergency_stop(self) -> Dict:
        """Emergency stop all trading activities."""
        self.daily_trades = self.max_daily_trades
        self.last_loss_time = datetime.now()
        
        emergency_status = {
            'emergency_stop_activated': True,
            'timestamp': datetime.now().isoformat(),
            'open_positions': sum(1 for p in self.positions.values() if int(p.get("qty") or 0) != 0),
            'daily_pnl': self.daily_pnl
        }
        
        self.logger.warning("EMERGENCY STOP ACTIVATED - All trading halted")
        
        return emergency_status
    
    def reset_daily_limits(self):
        """Reset daily trading limits (use with caution)."""
        self.daily_trades = 0
        self.daily_pnl = 0.0
        self.last_loss_time = None
        
        self.logger.warning("Daily limits manually reset")
    
    def get_position_info(self, symbol: str) -> Optional[Dict]:
        """Get information about a specific position."""
        sym = (symbol or "").upper() 
        pos = self.positions.get(sym) or self.positions.get(symbol)
        if not pos:
            return None

        qty = int(pos.get("qty") or 0)
        if qty == 0:
            return None
        
        side = "buy" if qty > 0 else "sell"
        return {
            "symbol": sym,
            "side": side,
            "quantity": abs(qty),
            "entry_price": float(pos.get("avg_price") or 0.0),
            "status": "open",
        }

    ### --- extra-helper methods --- ####
    def _norm_sym(self, symbol: str) -> str:
        return (symbol or "").upper().strip()

    
    def update_trailing_stop(self, symbol: str, current_price: float):
        """Update trailing stop and breakeven protection for an open position."""

        sym = self._norm_sym(symbol)
        pos = self.positions.get(sym)
        if not pos:
            return None

        qty   = int(pos["qty"])
        entry = float(pos["avg_price"])

        if qty == 0:
            return None

        # Read sniper config (safe defaults keep behaviour unchanged if env missing)
        be_trigger = float(getattr(self.config,
            "NQ_BREAKEVEN_TRIGGER_POINTS" if self._norm_sym(sym) in ("MNQ", "NQ")
            else "BREAKEVEN_TRIGGER_POINTS", 8.0 if self._norm_sym(sym) in ("MNQ", "NQ") 
            else 2.0))
        be_buffer  = float(getattr(self.config, "BREAKEVEN_BUFFER_POINTS",  0.25))

        # Bootstrap extremes in case position was opened before this code ran
        if sym not in self.position_extremes:
            self.position_extremes[sym] = entry
        if sym not in self.position_breakeven_set:
            self.position_breakeven_set[sym] = False

        if qty > 0:  # ──────── LONG ────────
            # Update best (highest) price seen
            if current_price > self.position_extremes[sym]:
                self.position_extremes[sym] = current_price

            best_profit = self.position_extremes[sym] - entry

            # Step 1 – arm breakeven once we've touched the trigger in profit
            if best_profit >= be_trigger and not self.position_breakeven_set[sym]:
                self.position_breakeven_set[sym] = True
                self.logger.info(
                    "BREAKEVEN armed %s: entry=%.2f trigger=%.2f best_profit=%.2f",
                    sym, entry, be_trigger, best_profit
                )

            # Step 2 – enforce breakeven stop (never let a winner fully reverse)
            if self.position_breakeven_set[sym]:
                be_stop = entry + be_buffer
                if current_price <= be_stop:
                    locked = current_price - entry
                    return f"breakeven_stop (locked={locked:.2f}pts)"

            # Step 3 – full trailing stop once deeper in profit
            profit_points = current_price - entry
            if profit_points >= self.trail_activation_points:
                trail_stop = self.position_extremes[sym] - self.trail_distance_points
                if current_price <= trail_stop:
                    locked = trail_stop - entry
                    return f"trailing_stop (locked_in_profit: {locked:.2f} pts)"

        else:  # ──────── SHORT ────────
            # Update best (lowest) price seen
            if current_price < self.position_extremes[sym]:
                self.position_extremes[sym] = current_price

            best_profit = entry - self.position_extremes[sym]

            # Step 1 – arm breakeven
            if best_profit >= be_trigger and not self.position_breakeven_set[sym]:
                self.position_breakeven_set[sym] = True
                self.logger.info(
                    "BREAKEVEN armed %s: entry=%.2f trigger=%.2f best_profit=%.2f",
                    sym, entry, be_trigger, best_profit
                )

            # Step 2 – enforce breakeven stop
            if self.position_breakeven_set[sym]:
                be_stop = entry - be_buffer
                if current_price >= be_stop:
                    locked = entry - current_price
                    return f"breakeven_stop (locked={locked:.2f}pts)"

            # Step 3 – full trailing stop
            profit_points = entry - current_price
            if profit_points >= self.trail_activation_points:
                trail_stop = self.position_extremes[sym] + self.trail_distance_points
                if current_price >= trail_stop:
                    locked = entry - trail_stop
                    return f"trailing_stop (locked_in_profit: {locked:.2f} pts)"

        return None

    def check_exit_points(self, symbol: str, current_price: float, stop_points: float, take_points: float) -> str | None:

        # 1) Trailing stop / breakeven protection (highest priority)
        if self.use_trailing_stops:
            trail_reason = self.update_trailing_stop(symbol, current_price)
            if trail_reason:
                return trail_reason

        sym = self._norm_sym(symbol)
        pos = self.positions.get(sym)
        if not pos:
            return None

        qty = int(pos.get("qty") or 0)
        avg = float(pos.get("avg_price") or 0.0)
        px  = float(current_price)

        # 2) Time-based exit — flat if trade has drifted beyond the max window
        max_minutes = int(getattr(self.config, "MAX_TRADE_DURATION_MINUTES", 20))
        entry_time  = self.position_entry_times.get(sym)
        if entry_time is not None:
            elapsed_min = (datetime.now(timezone.utc) - entry_time).total_seconds() / 60.0
            if elapsed_min >= max_minutes:
                direction = "long" if qty > 0 else "short"
                pnl_pts   = (px - avg) if qty > 0 else (avg - px)
                self.logger.info(
                    "TIME EXIT %s: elapsed=%.1fmin pnl_pts=%.2f side=%s",
                    sym, elapsed_min, pnl_pts, direction
                )
                return f"time_exit ({elapsed_min:.0f}min)"

        # 3) Hard stop-loss / take-profit
        if qty > 0:
            if px <= avg - float(stop_points):
                return "stop_loss_points"
            if px >= avg + float(take_points):
                return "take_profit_points"

        if qty < 0:
            if px >= avg + float(stop_points):
                return "stop_loss_points"
            if px <= avg - float(take_points):
                return "take_profit_points"

        return None


    def _mult(self, symbol: str) -> float:
        # fallback to 1 if unknown
        return float(self.contract_multipliers.get(symbol.split()[0], 50.0))


    def reset_if_new_day(self):
        d = datetime.utcnow().date()
        if d != self._last_reset_date:
            self._last_reset_date = d
            self.realized_pnl = 0.0
            self.daily_pnl = 0.0
        self._rotate_daily_if_needed()

    def paper_fill(
        self, 
        symbol: str, 
        side: str, 
        qty: int, 
        price: float,
        dry_run: bool = True, 
        fill_id: str | None = None,
        signal_id: str | None = None, 
        attempt_id: str | None = None, 
        exit_reason: str | None = None, 
        strategy_name: str | None = None
    ) -> dict:
        """
        Simulate an immediate market fill and update positions & realized PnL.
        Returns a trade record we can append to history
        """

        mode = getattr(self, "instant_close", "hold")
        self.logger.info("paper_fill(): mode=%s", mode)

        if mode == "instant_close":
            return self._paper_fill_instant_close(symbol, side, qty, price, dry_run)

        sym = self._norm_sym(symbol)
        side = (side or "").upper()
        qty = int(qty)
        px = float(price)
        cm = float(self.contract_multipliers.get(sym, 1.0))

        pos = self.positions.setdefault(sym, {"qty": 0, "avg_price": 0.0, "last_px": px, "unrealized": 0.0})
        meta = {"fill_id": fill_id, "signal_id": signal_id, "attempt_id": attempt_id, "strategy_name": strategy_name}

        cur_qty = int(pos["qty"])
        avg = float(pos["avg_price"])

        position_fully_closed = False

        def _new_avg(old_qty, old_avg, add_qty, add_px):
            notional = old_qty * old_avg + add_qty * add_px
            tot  = old_qty + add_qty
            return (notional / tot) if tot != 0 else 0.0

        realized_this_trade = 0.0
        trade_record = None
        open_record = None

        if side == "BUY":
            if cur_qty >= 0:
                # adding/increasing long
                new_qty = cur_qty + qty
                new_avg = _new_avg(cur_qty, avg, qty, px) if new_qty != 0 else 0.0
                pos["qty"] = new_qty
                pos["avg_price"] = new_avg

                # arm sniper state on brand-new position
                if cur_qty == 0:
                    self.position_entry_times[sym] = datetime.now(timezone.utc)
                    self.position_breakeven_set[sym] = False
                    self.position_extremes[sym] = px

                open_record = {
                    **meta,
                    "symbol": symbol,
                    "side": "BUY",
                    "qty": qty,
                    "entry_price": px,
                    "exit_price": None,
                    "pnl": 0.0,
                    "exit_reason": None,
                    "dry": dry_run,
                    "ts": datetime.now(timezone.utc).isoformat(),
                }

            else:
                # reducing a short
                reduce_qty = min(qty, -cur_qty)
                realized_this_trade += (avg - px) * reduce_qty * cm
                cur_qty += reduce_qty
                qty -= reduce_qty

                if cur_qty == 0:
                    pos["qty"] = 0
                    pos["avg_price"] = 0.0
                    position_fully_closed = True
                else:
                    pos["qty"] = cur_qty
                    pos["avg_price"] = avg

                if qty > 0:
                    pos["avg_price"] = px
                    pos["qty"] = qty
                    open_record = {
                        **meta,
                        "symbol": symbol,
                        "side": "BUY",
                        "qty": qty,
                        "entry_price": px,
                        "exit_price": None,
                        "pnl": 0.0,
                        "exit_reason": None,
                        "dry": dry_run,
                        "ts": datetime.now(timezone.utc).isoformat(),
                    }

                if reduce_qty > 0:
                    trade_record = {
                        **meta,
                        "symbol": symbol,
                        "side": "BUY",
                        "qty": reduce_qty,
                        "entry_price": avg,
                        "exit_price": px,
                        "pnl": float((avg - px) * reduce_qty * cm),
                        "exit_reason": exit_reason,
                        "status": "closed",
                        "ts": datetime.now(timezone.utc).isoformat(),
                    }

        elif side == "SELL":
            if cur_qty <= 0:
                # adding/increasing short
                new_qty = cur_qty - qty
                new_avg = _new_avg(abs(cur_qty), avg, qty, px) if new_qty != 0 else 0.0
                pos["qty"] = new_qty
                pos["avg_price"] = new_avg

                # arm sniper state on brand-new position
                if cur_qty == 0:
                    self.position_entry_times[sym] = datetime.now(timezone.utc)
                    self.position_breakeven_set[sym] = False
                    self.position_extremes[sym] = px

                open_record = {
                    **meta,
                    "symbol": symbol,
                    "side": "SELL",
                    "qty": qty,
                    "entry_price": px,
                    "exit_price": None,
                    "pnl": 0.0,
                    "exit_reason": None,
                    "dry": dry_run,
                    "ts": datetime.now(timezone.utc).isoformat(),
                }

            else:
                # reducing a long
                reduce_qty = min(qty, cur_qty)
                realized_this_trade += (px - avg) * reduce_qty * cm
                cur_qty -= reduce_qty
                qty -= reduce_qty

                if cur_qty == 0:
                    pos["qty"] = 0
                    pos["avg_price"] = 0.0
                    position_fully_closed = True
                else:
                    pos["qty"] = cur_qty
                    pos["avg_price"] = avg

                # meta = {"fill_id": fill_id, "signal_id": signal_id, "attempt_id": attempt_id}

                if qty > 0:
                    pos["avg_price"] = px
                    pos["qty"] = -qty
                    open_record = {
                        **meta,
                        "symbol": symbol,
                        "side": "SELL",
                        "qty": qty,
                        "entry_price": px,
                        "exit_price": None,
                        "pnl": 0.0,
                        "exit_reason": None,
                        "dry": dry_run,
                        "ts": datetime.now(timezone.utc).isoformat(),
                    }

                if reduce_qty > 0:
                    trade_record = {
                        **meta,
                        "symbol": symbol,
                        "side": "SELL",
                        "qty": reduce_qty,
                        "entry_price": avg,
                        "exit_price": px,
                        "pnl": float((px - avg) * reduce_qty * cm),
                        "exit_reason": exit_reason,
                        "status": "closed",
                        "ts": datetime.now(timezone.utc).isoformat(),
                    }

        # Log to analytics
        try:
            from trade_analytics import TradeAnalytics
            analytics = TradeAnalytics(config=self.config)
            if trade_record:
                analytics.log_trade(trade_record)
                self.logger.info(f'{CHECK} Logged trade to analytics: {trade_record.get("signal_id")}')
        except Exception:
            self.logger.error(f"{CROSS} Failed to trade to analytics", exc_info=True) 

        # update last price & unrealized
        pos["last_px"] = px
        self.mark_to_market(sym, last_price=px)

        # Remove closed positions from dict and clear sniper state
        if position_fully_closed and sym in self.positions:
            del self.positions[sym]
            self.position_entry_times.pop(sym, None)
            self.position_breakeven_set.pop(sym, None)
            self.position_extremes.pop(sym, None)

        # realize P&L & append trade if we closed/reduced
        if trade_record is not None:
            self.realized_pnl = float(self.realized_pnl + realized_this_trade)
            self.trade_history.append(trade_record)

            if open_record is not None:
                self.trade_history.append(open_record)
                return {"closed": trade_record, "opened": open_record}
            return {"closed": trade_record}

        # otherwise this was a pure OPEN / ADD -> still append so UI sees it
        if open_record is not None:
            self.trade_history.append(open_record)
            return {"opened": open_record}
        
        self.logger.info("paper_fill(): mode=%r id=%s price=%s", getattr(self, "instant_close", None), id(self), price)
        return None


    def _paper_fill_instant_close(self, symbol: str, side: str, qty: int, price: float, dry_run: bool = True, strategy_name: str | None = None) -> dict:
        """
        Simulate an immediate market fill and immediately close it at the same price.
        """
        sym = self._norm_sym(symbol)
        side = (side or "").upper()
        qty = int(qty)
        px = float(price)
        cm = float(self.contract_multipliers.get(sym, 1.0))

        opened_at = datetime.now(timezone.utc).isoformat()

        open_record = {
            "symbol": symbol,
            "side": side,
            "qty": qty,
            "entry_price": px,
            "ts": opened_at,
            "status": "opened",
            "exit_reason": "dry_run",
            "strategy_name": strategy_name,
        }

        if side == "BUY":
            pnl = (px - px) * qty * cm
        else:
            pnl = (px - px) * qty * cm

        closed_at = datetime.now(timezone.utc).isoformat()
        close_record = {
            "symbol": symbol,
            "side": side,
            "qty": qty,
            "entry_price": px,
            "exit_price": px,
            "pnl": float(pnl),
            "exit_reason": "dry_run",
            "ts": closed_at,
            "status": "closed",
            "strategy_name": strategy_name,
        }

        self.daily_pnl = float(getattr(self, "daily_pnl", 0.0) + pnl)
        self.realized_pnl = float(getattr(self, "realized_pnl", 0.0) + pnl)

        self.positions.setdefault(sym, {})
        self.positions[sym] = {
            "qty": 0,
            "avg_price": 0.0,
            "last_px": px,
            "unrealized": 0.0,
            "opened_at": opened_at,
        }

        self.trade_history.append(close_record)

        if len(self.trade_history) > 1000:
            self.trade_history = self.trade_history[-1000:]

        return close_record


    def mark_to_market(self, symbol: str, last_price: float | None = None):
        """Update unrealised PnL for one symbol, and refresh daily_pnl."""
        if hasattr(self, "reset_if_new_day"):
            self.reset_if_new_day()

        sym = self._norm_sym(symbol)
        pos = self.positions.get(sym)
        if not pos:
            return

        px = float(last_price) if last_price is not None else float(pos.get("last_px", 0.0))
        pos["last_px"] = px

        cm = float(self.contract_multipliers.get(sym, 1.0))
        qty = int(pos["qty"])

        if qty > 0:
            pos["unrealized"] = (px - pos["avg_price"]) * qty * cm
        elif qty < 0:
            pos["unrealized"] = (pos["avg_price"] - px) * (-qty) * cm
        else:
            pos["unrealized"] = 0.0

        unreal = 0.0
        for _sym, _p in self.positions.items():
            unreal += float(_p.get("unrealized") or 0.0)
        self.daily_pnl = float(self.realized_pnl + unreal)


    def get_positions(self) -> list[dict]:
        """Return a UI-friendly snapshot of positions."""
        out = []
        for sym, p in self.positions.items():
            out.append({
                "symbol": sym,
                "qty": p["qty"],
                "avg_price": p["avg_price"],
                "unrealized": p.get("unrealized", 0.0),
            })
        return out


    # --- persistence ---
    def save_history(self, path: str | None = None):
        path = path or self.history_path
        if not path:
            return
        try:
            with self._hist_lock:
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(self.trade_history, f, ensure_ascii=False, indent=2)
        except Exception:
            try: 
                self.logger.exception("save_history failed")
            except: 
                pass


    def load_history(self, path: str | None = None):
        path = path or self.history_path
        if not path:
            return
        with self._hist_lock:
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, list):
                    self.trade_history = data


    def load_history_silent(self, path: str | None = None):
        try:
            self.load_history(path)
        except Exception as e:
            self.logger.debug(f"Expected error in [RiskManager.load_history_silent]: {e}")


    def _rotate_daily_if_needed(self):
        if not getattr(self, "history_path", None):
            return
        today = datetime.utcnow().strftime("%Y%m%d")
        base = os.path.splitext(self.history_path)[0]
        new_path = f"{base}-{today}.json"
        if self.history_path != new_path:
            self.history_path = new_path
            self.save_history(new_path)

    def get_position_qty(self, symbol: str) -> int:
        sym = self._norm_sym(symbol)
        pos = self.positions.get(sym) or self.positions.get(sym)
        if not pos:
            return 0
        try:
            return int(pos.get("qty") or 0)
        except Exception:
            return 0


    def get_open_position(self, symbol: str) -> dict | None:
        sym = (symbol or "").upper()
        pos = self.positions.get(sym) or self.positions.get(symbol)
        if not pos:
            return None
        if int(pos.get("qty") or 0) == 0:
            return None
        return pos


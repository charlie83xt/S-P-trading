"""
Risk Management Module for the Trading Bot.
"""

from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple, Any
import logging
import os, json
import threading

class RiskManager:
    """
    Risk management system for controlling trading exposure and losses.
    """
    
    def __init__(self, max_position_size: float = 0.1, stop_loss_pct: float = 2.0,
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
        # if config is not None:
        #     self.instant_close = bool(getattr(config, "INSTANT_CLOSE_TRADES", False))
        
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
        self.contract_multipliers: dict[str, float] = {"ES": 50.0}

        self.wins = 0
        self.losses = 0
    
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
        if symbol in self.current_positions:
            return False, f"Already have position in {symbol}", 0.0
        
        # Calculate suggested position size
        suggested_quantity = self._calculate_position_size(account_balance, current_price, signal)
        
        if suggested_quantity <= 0:
            return False, "Calculated position size is zero or negative", 0.0
        
        return True, "Trade validated", suggested_quantity
    
    def _calculate_position_size(self, account_balance: float, current_price: float, signal: Dict) -> float:
        """
        Calculate appropriate position size based on risk parameters.
        
        Args:
            account_balance: Current account balance
            current_price: Current market price
            signal: Trading signal
            
        Returns:
            Suggested position size
        """
        # Calculate maximum position value based on account balance
        max_position_value = account_balance * self.max_position_size
        
        # Calculate position size based on stop loss
        if 'range_high' in signal and 'range_low' in signal:
            if signal['type'] == 'BUY':
                stop_loss_price = signal['range_low'] * 0.999  # 0.1% buffer
                risk_per_unit = current_price - stop_loss_price
            else:  # SELL
                stop_loss_price = signal['range_high'] * 1.001  # 0.1% buffer
                risk_per_unit = stop_loss_price - current_price
            
            # Calculate position size based on maximum risk
            max_risk_amount = account_balance * (self.stop_loss_pct / 100)
            
            if risk_per_unit > 0:
                risk_based_quantity = max_risk_amount / risk_per_unit
            else:
                risk_based_quantity = 0
        else:
            # Fallback calculation
            risk_based_quantity = max_position_value / current_price
        
        # Use the smaller of the two calculations
        balance_based_quantity = max_position_value / current_price
        suggested_quantity = min(risk_based_quantity, balance_based_quantity)
        
        # Ensure minimum viable quantity
        min_quantity = 0.001  # Minimum trade size
        
        return max(suggested_quantity, min_quantity) if suggested_quantity > 0 else 0
    
    def _is_in_cooldown(self) -> bool:
        """Check if currently in cooldown period."""
        if self.last_loss_time is None:
            return False
        
        time_since_loss = datetime.now() - self.last_loss_time
        return time_since_loss.total_seconds() < self.cooldown_period
    
    def record_trade_entry(self, symbol: str, side: str, quantity: float, price: float, order_id: str = None):
        """
        Record a trade entry.
        
        Args:
            symbol: Trading symbol
            side: 'buy' or 'sell'
            quantity: Trade quantity
            price: Entry price
            order_id: Order ID from exchange
        """
        self._check_new_day()
        
        trade_record = {
            'symbol': symbol,
            'side': side,
            'quantity': quantity,
            'entry_price': price,
            'entry_time': datetime.now(),
            'order_id': order_id,
            'status': 'open'
        }
        
        # Add to current positions
        self.current_positions[symbol] = trade_record
        
        # Increment daily trade counter
        self.daily_trades += 1
        self.last_trade_time = datetime.now()
        
        self.logger.info(f"Trade entry recorded: {side.upper()} {quantity} {symbol} at {price}")
    
    def record_trade_exit(self, symbol: str, exit_price: float, exit_reason: str = "manual"):
        """
        Record a trade exit and calculate P&L.
        
        Args:
            symbol: Trading symbol
            exit_price: Exit price
            exit_reason: Reason for exit ('stop_loss', 'take_profit', 'manual')
        """
        if symbol not in self.current_positions:
            self.logger.warning(f"No open position found for {symbol}")
            return
        
        position = self.current_positions[symbol]
        
        # Calculate P&L
        entry_price = position['entry_price']
        quantity = position['quantity']
        side = position['side']
        
        if side.lower() == 'buy':
            pnl = (exit_price - entry_price) * quantity
        else:  # sell
            pnl = (entry_price - exit_price) * quantity
        
        # Update position record
        position.update({
            'exit_price': exit_price,
            'exit_time': datetime.now(),
            'exit_reason': exit_reason,
            'pnl': pnl,
            'status': 'closed'
        })
        
        # Move to trade history
        self.trade_history.append(position.copy())
        
        # Remove from current positions
        del self.current_positions[symbol]
        
        # Update daily P&L
        self.daily_pnl += pnl
        
        # Record loss time for cooldown
        if pnl < 0:
            self.last_loss_time = datetime.now()
        
        self.logger.info(f"Trade exit recorded: {symbol} at {exit_price}, P&L: {pnl:.2f}, Reason: {exit_reason}")
    
    def check_stop_loss_take_profit(self, symbol: str, current_price: float) -> Optional[str]:
        """
        Check if stop loss or take profit should be triggered.
        
        Args:
            symbol: Trading symbol
            current_price: Current market price
            
        Returns:
            'stop_loss', 'take_profit', or None
        """
        if symbol not in self.current_positions:
            return None
        
        position = self.current_positions[symbol]
        entry_price = position['entry_price']
        side = position['side']
        
        # Calculate stop loss and take profit levels
        stop_loss_level = entry_price * (1 - self.stop_loss_pct / 100) if side.lower() == 'buy' else entry_price * (1 + self.stop_loss_pct / 100)
        take_profit_level = entry_price * (1 + self.take_profit_pct / 100) if side.lower() == 'buy' else entry_price * (1 - self.take_profit_pct / 100)
        
        if side.lower() == 'buy':
            if current_price <= stop_loss_level:
                return 'stop_loss'
            elif current_price >= take_profit_level:
                return 'take_profit'
        else:  # sell
            if current_price >= stop_loss_level:
                return 'stop_loss'
            elif current_price <= take_profit_level:
                return 'take_profit'
        
        return None
    
    def get_risk_metrics(self) -> Dict:
        """
        Get current risk metrics and statistics.
        
        Returns:
            Dictionary with risk metrics
        """
        self._check_new_day()
        
        # Calculate win rate from trade history
        closed_trades = [t for t in self.trade_history if t['status'] == 'closed']
        winning_trades = [t for t in closed_trades if t.get('pnl', 0) > 0]
        
        win_rate = len(winning_trades) / len(closed_trades) * 100 if closed_trades else 0
        
        # Calculate average P&L
        total_pnl = sum(t.get('pnl', 0) for t in closed_trades)
        avg_pnl = total_pnl / len(closed_trades) if closed_trades else 0
        
        # Calculate maximum drawdown
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
            'current_positions': len(self.current_positions),
            'total_trades': len(closed_trades),
            'win_rate': win_rate,
            'avg_pnl': avg_pnl,
            'max_drawdown': max_drawdown,
            'in_cooldown': self._is_in_cooldown(),
            'cooldown_remaining': max(0, self.cooldown_period - (datetime.now() - self.last_loss_time).total_seconds()) if self.last_loss_time else 0
        }
    
    def emergency_stop(self) -> Dict:
        """
        Emergency stop all trading activities.
        
        Returns:
            Dictionary with emergency stop status
        """
        self.daily_trades = self.max_daily_trades  # Prevent new trades
        self.last_loss_time = datetime.now()  # Trigger cooldown
        
        emergency_status = {
            'emergency_stop_activated': True,
            'timestamp': datetime.now().isoformat(),
            'open_positions': len(self.current_positions),
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
        """
        Get information about a specific position.
        
        Args:
            symbol: Trading symbol
            
        Returns:
            Position information or None if no position exists
        """
        return self.current_positions.get(symbol)

    ### --- extra-helper methods --- ####

    def _mult(self, symbol: str) -> float:
        # fallback to 1 if unknown
        return float(self.contract_multipliers.get(symbol.split()[0], 50.0))


    def reset_if_new_day(self):
        d = datetime.utcnow().date()
        if d != self._last_reset_date:
            self._last_reset_date = d
            self.realized_pnl = 0.0
            self.daily_pnl = 0.0
            # keep positions open across days (common in futures), or clear if you prefer
        self._rotate_daily_if_needed()

    def paper_fill(self, symbol: str, side: str, qty: int, price: float, dry_run: bool = True, fill_id: str | None = None, signal_id: str | None = None, attempt_id: str | None = None) -> dict:
        """
        Simulate and immediate market fill and update positions & realized PnL.
        Returns a trade record we can append to history
        """

        # When we want to the "always closed" behaviour
        mode = getattr(self, "instant_close", "hold")
        self.logger.info("paper_fill(): mode=%s", mode)

        if mode == "instant_close":
            return self._paper_fill_instant_close(symbol, side, qty, price, dry_run)

        side = (side or "").upper()
        qty = int(qty)
        # pos = self.positions.setdefault(symbol, {"qty": 0, "avg_price": 0.0, "unrealized": 0.0})
        px = float(price)
        cm = float(self.contract_multipliers.get(symbol, 1.0))
        # side = side.upper()
        # ts = ts or datetime.utcnow().isoformat(timespec="seconds")

        pos = self.positions.setdefault(symbol, {"qty": 0, "avg_price": 0.0, "last_px": px, "unrealized": 0.0})

        cur_qty = int(pos["qty"])
        avg = float(pos["avg_price"])

        # helper to recompute avg on adds: (old notional + new notional)/(old qty + new qty)
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

                # make an OPEN record so web_app can show it
                open_record = {
                    "symbol": symbol,
                    "side": "BUY",
                    "qty":qty,
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
                # realize P&L for the reduced shares: short P&L = (avg - exit)*reduce_qty*cm
                realized_this_trade += (avg - px) * reduce_qty * cm
                cur_qty += reduce_qty  # closer to zero
                qty -= reduce_qty


                if cur_qty == 0:
                    # fully closed short
                    pos["qty"] = 0
                    pos["avg_price"] = 0.0
                else:
                    # still short after partial reduce
                    pos["qty"] = cur_qty
                    pos["avg_price"] = avg


                # if we still have qty left after reducing, that turns into a new long add
                if qty > 0:
                    pos["avg_price"] = px
                    pos["qty"] = qty
                    # create an open record for that leftover
                    open_record = {
                        "symbol": symbol,
                        "side": "BUY",
                        "qty":qty,
                        "entry_price": px,
                        "exit_price": None,
                        "pnl": 0.0,
                        "exit_reason": None,
                        "dry": dry_run,
                        "ts": datetime.now(timezone.utc).isoformat(),
                    }


                # record a realized trade for the reduced portion
                if reduce_qty > 0:
                    trade_record = {
                        "symbol": symbol,
                        "side": "BUY",  # buy to cover short
                        "qty": reduce_qty,
                        "entry_price": avg,
                        "exit_price": px,
                        "pnl": float((avg - px) * reduce_qty * cm),
                        "exit_reason": "dry_run_close",
                        "ts": datetime.now(timezone.utc).isoformat(),
                    }


        elif side == "SELL":
            if cur_qty <= 0:
                # adding/increasing short
                new_qty = cur_qty - qty  # more negative
                # avg for short: compute avg on absolute sizes
                new_avg = _new_avg(abs(cur_qty), avg, qty, px) if new_qty != 0 else 0.0
                pos["qty"] = new_qty
                pos["avg_price"] = new_avg

                open_record = {
                    "symbol": symbol,
                    "side": "SELL",
                    "qty":qty,
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
                # realize P&L for reduced shares: long P&L = (exit - avg)*reduce_qty*cm
                realized_this_trade += (px - avg) * reduce_qty * cm
                cur_qty -= reduce_qty
                qty -= reduce_qty


                if cur_qty == 0:
                    pos["qty"] = 0
                    pos["avg_price"] = 0.0
                else:
                    pos["qty"] = cur_qty
                    pos["avg_price"] = avg

                meta = {"fill_id": fill_id, "signal_id": signal_id, "attempt_id": attempt_id}

                # if we still have qty left after reducing, that turns into a new short add
                if qty > 0:
                    pos["avg_price"] = px
                    pos["qty"] = -qty
                    open_record = {
                        **meta,
                        "symbol": symbol,
                        "side": "SELL",
                        "qty":qty,
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
                        "side": "SELL",  # sell to close long
                        "qty": reduce_qty,
                        "entry_price": avg,
                        "exit_price": px,
                        "pnl": float((px - avg) * reduce_qty * cm),
                        "exit_reason": "dry_run_close",
                        "ts": datetime.now(timezone.utc).isoformat(),
                    }


        # update last price & unrealized
        pos["last_px"] = px
        self.mark_to_market(symbol, last_price=px)

        # realize P&L & append trade if we closed/reduced
        if trade_record is not None:
            self.realized_pnl = float(self.realized_pnl + realized_this_trade)
            self.trade_history.append(trade_record)

            # if also opened a new leg in same call, append that too
            if open_record is not None:
                self.trade_history.append(open_record)
                return {"closed": trade_record, "opened": open_record}
            return {"closed": trade_record}
            # return open_record

        # otherwise this was a pure OPEN / ADD -> still append so UI sees it
        if open_record is not None:
            self.trade_history.append(open_record)
            return {"opened": open_record}

            # emit a synthetic closed record too
            # if getattr(self, "emit_closed_on_hold", False) and False:
            #     closed_for_ui = dict(open_record)
            #     closed_for_ui["exit_price"] = px
            #     closed_for_ui["pnl"] = 0.0
            #     closed_for_ui["exit_reason"] = "ui_mirror"
            #     closed_for_ui["status"] = "closed"
            #     self.trade_history.append(closed_for_ui)

            # return open_record
        
        self.logger.info("paper_fill(): mode=%r id=%s price=%s", getattr(self, "instant_close", None), id(self), price)
        # fallback
        # return trade_record
        return None


    def _paper_fill_instant_close(self, symbol: str, side: str, qty: int, price: float, dry_run: bool = True) -> dict:
        """
        Option B: simulate an immediate market fill and immediately close it at the
        same (or provided) price. This guarantees:
        - trade_history gets a *closed* trade
        - daily_pnl gets updated
        - win-rate can be computed
        - /api/trades has something to show
        We still keep self.positions[...] in case the UI wants to show “current positions”,
        but we zero it right after closing.
        """
        side = (side or "").upper()
        qty = int(qty)
        px = float(price)
        cm = float(self.contract_multipliers.get(symbol, 1.0))


        # 1) “open” record (for completeness — some UIs like to know the original side)
        opened_at = datetime.now(timezone.utc).isoformat()

        open_record = {
            "symbol": symbol,
            "side": side,
            "qty": qty,
            "entry_price": px,
            "ts": opened_at,
            "status": "opened",
            "exit_reason": "dry_run",
        }


        # 2) immediately “close” it at the same price (Option B)
        # if later you want to test P&L changes, just call this with a slightly
        # different price than the signal price.
        if side == "BUY":
            pnl = (px - px) * qty * cm  # 0 right now
        else:
            pnl = (px - px) * qty * cm  # 0 right now


        closed_at = datetime.now(timezone.utc).isoformat()
        close_record = {
            "symbol": symbol,
            "side": side,               # keep original side for history
            "qty": qty,
            "entry_price": px,
            "exit_price": px,
            "pnl": float(pnl),
            "exit_reason": "dry_run",
            "ts": closed_at,
            "status": "closed",
        }


        # 3) update daily / realized P&L
        # web_app.py already does:
        #   _status["risk_metrics"]["daily_pnl"] = rm.daily_pnl ...
        # so we must keep this number current
        self.daily_pnl = float(getattr(self, "daily_pnl", 0.0) + pnl)
        # keep a running total too (web_app looks at realized_total)
        self.realized_pnl = float(getattr(self, "realized_pnl", 0.0) + pnl)


        # 4) keep positions shape the UI expects, but flat
        # web_app /api/positions is reading rm.positions[sym] -> {qty, avg_price, unrealized}
        # so we write it, then zero it
        self.positions.setdefault(symbol, {})
        self.positions[symbol] = {
            "qty": 0,
            "avg_price": 0.0,
            "last_px": px,
            "unrealized": 0.0,
            "opened_at": opened_at,
        }


        # 5) append to trade_history so /api/trades sees it
        # IMPORTANT: your flask logs show it dumps the tail of trade_history,
        # so we actually need the *closed* record in there.
        self.trade_history.append(close_record)


        # (optional) cap history
        if len(self.trade_history) > 1000:
            self.trade_history = self.trade_history[-1000:]

        return close_record

        # remaining = qty # IMPORTANT: consume this as we close/open

        # mult = self._mult(symbol)

        # if side_u == "BUY":
        #     # 1) if we are short, this BUY first closest short
        #     if pos["qty"] < 0 and remaining > 0:
        #         close_qty = min(remaining, -pos["qty"])
        #         realized_this += (pos["avg_price"] - px) * close_qty * cm # short PnL
        #         pos["qty"] += close_qty
        #         remaining -= close_qty
        #         if pos["qty"] == 0:
        #             pos["avg_price"] = 0.0 # flat
            
        #     # 2) Any remaining increases / opens long 
        #     if remaining > 0:
        #         new_qty = pos["qty"] + remaining
        #         if new_qty > 0:
        #             pos["avg_price"] = ((pos["avg_price"] * pos["qty"]) + (px * remaining)) / new_qty
        #         else:
        #             # shouldn't happen on BUY, but keep safe
        #             pos["qty"] = 0.0
        #         pos["qty"] = new_qty

        # elif side_u == "SELL":
        #     # 1) if we are long, this SELL first closes longs
        #     if pos["qty"] > 0 and remaining > 0:
        #         # selling out long
        #         close_qty = min(remaining, pos["qty"])
        #         realized_this += (px - pos["avg_price"]) * close_qty * cm # long PnL
        #         # self.realized_pnl += realized_this
        #         # trade["realized_pnl"] += (price - pos["avg_price"]) * close_qty * mult 
        #         pos["qty"] -= close_qty
        #         remaining -= close_qty
        #         if pos["qty"] == 0:
        #             pos["avg_price"] = 0.0 # flat

        #     # 2) Any remaining increases / opens short
        #     if remaining > 0:
        #         # increasing a short (or opening)
        #         new_qty = pos["qty"] - remaining
        #         # Weighted avg for shorts uses abs() to keep arimethic simple
        #         if new_qty < 0:
        #             pos["avg_price"] = ((abs(pos["qty"]) * pos["avg_price"]) + (px * remaining)) / abs(new_qty)
        #         else:
        #             # shouldn't happen on SELL increasing shorts, but keep safe
        #             pos["avg_price"] = 0.0
        #         pos["qty"] = new_qty # more negative

        # else:
        #     # Unrealized will be set by mark_to_market; we still return a record now.
        #     sec = {"symbol": symbol, "side": side_u, "qty": qty, "price": px, "error": "unsupported_side"}
        #     return rec

        # # NOTE: unrealized will be updated by mark_to_market
        # record = {
        #     "time": time.strftime("%Y-%m-%dT%H:%M:%S"),
        #     "symbol":symbol, 
        #     "side": side_u, 
        #     "qty": qty, 
        #     "price": px,
        #     "realized_delta": float(realized_this),
        #     # "realized_total": float(self.realized_pnl + realized_this), # include this trade immediately
        #     "realized_total": float(self.realized_pnl),
        #     "position_qty": int(pos["qty"]), 
        #     "avg_price": float(pos["avg_price"]),
        #     "dry_run": bool(dry_run),
        # }

        # # persist exactly once
        # if hasattr(self, "trade_history"):
        #     self.trade_history.append(record)
        #     try:
        #         self.save_history()
        #     except Exception:
        #         pass

        # # try:
        # #     self.logger.info("RM APPEND: %s", record)
        # # except Exception:
        # #     pass

        # # Update class-level realized now that we've recorded it
        # self.realized_pnl += realized_this

        # return record


    def mark_to_market(self, symbol: str, last_price: float | None = None):
        """Update unrealised PnL for one symbol, and refresh daily_pnl."""
        # roll daily counters first
        if hasattr(self, "reset_if_new_day"):
            self.reset_if_new_day()

        pos = self.positions.get(symbol)
        if not pos:
            return

        px = float(last_price) if last_price is not None else float(pos.get("last_px", 0.0))
        pos["last_px"] = px

        cm = float(self.contract_multipliers.get(symbol, 1.0))
        qty = int(pos["qty"])

        # unrealized (long: (px - avg)*qty*cm; short: (avg - px)*|qty|*cm)
        if qty > 0:
            pos["unrealized"] = (px - pos["avg_price"]) * qty * cm
        elif qty < 0:
            pos["unrealized"] = (pos["avg_price"] - px) * (-qty) * cm
        else:
            pos["unrealized"] = 0.0

        # mult = self._mult(symbol)
        # pos["unrealized"] = (last_price - pos["avg_price"]) * pos["qty"] * mult
        # daily pnl = realized + sum of unrealized accross symbols
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
                os.makedirs(os.path.dirname(path), exist_ok=true)
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(self.trade_history, f, ensure_ascii=False, indent=2)
        except Exception:
            try: 
                self.logger.exception("save_history failed")
            except: 
                pass


    def load_history(self, path: str | None = None):
        path = path or self.history_path
        if not patgh:
            return
        with self._hist_lock:
            if os.path.exist(path):
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, list):
                    self.trade_history = data


    def load_history_silent(self, path: str | None = None):
        try:
            self.load_history(path)
        except Exception:
            pass


    def _rotate_daily_if_needed(self):
        # optional: rotate to history YYYYMMDD.json when day changes
        if not getattr(self, "history_path", None):
            return
        today = datetime.utcnow().strftime("%Y%m%d")
        base = os.path.splitext(self.history_path)[0]
        new_path = f"{base}-{today}.json"
        if self.history_path != new_path:
            self.history_path = new_path
            self.save_history(new_path)

    def get_position_qty(self, symbol: str) -> int:
        sym = (symbol or "").upper()

        # keys in self.positions are whatever you used when recording (looks like ES)
        pos = self.positions.get(sym) or self.positions.get(symbol)
        return int((pos or {}).get("qty") or 0)
        # if pos:
        #     return int(pos.get("qty") or 0)

        # # fallback: try prefix match (e.g., "ES" might correspond to "ESH6")
        # for k, p in self.positions.items():
        #     if (k or "").upper().startswith(sym):
        #         return int(p.get("qty") or 0)

        # return 0 

        
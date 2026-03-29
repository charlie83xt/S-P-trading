"""
Main Trading Bot Implementation.
"""

import time
import threading
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Any
import logging
import json

from config import Config
from data_manager import DataManager
from opening_range_strategy import OpeningRangeStrategy
from risk_manager import RiskManager
from api_factory import APIFactory
from strategy_factory import create as create_strategy
from trade_analytics import TradeAnalytics
from strategy_manager import StrategyManager

# ================= tiny helpers =====================
import uuid
def _new_id(prefix: str) -> str:
    # short readable id
    return f"{prefix}_{uuid.uuid4().hex[:10]}"

def _utc_ts() -> str:
    return datetime.now(timezone.utc).isoformat()


class TradingBot:
    """
    Main trading bot that orchestrates strategy execution, risk management, and order placement.
    """
    
    # def __init__(self, platform: Optional[str] = None):
    def __init__(self, config: Config):
        """
        Initialize the Trading Bot.
        
        Args:
            platform: Trading platform to use. If None, uses config default.
        """
        # Initialize components
        self.config = config
        # self.trade_history = []
        self.trades_executed = 0
        self.signals_generated = 0
        # self.data_manager = DataManager(self.config, platform)
        self.data_manager = DataManager(config = self.config)
         # Initialise analytics
        self.analytics = TradeAnalytics(db_path='market_data.db') # <= Wired for analytics

        self.strategy_manager = StrategyManager(
            self.data_manager,
            self.config,
            self.analytics
        )
        
        self.strategy = self.strategy_manager.get_active_strategy()
        self.risk_manager = RiskManager(
            self.config.MAX_POSITION_SIZE,
            self.config.STOP_LOSS_PERCENTAGE,
            self.config.TAKE_PROFIT_PERCENTAGE,
            self.config.MAX_DAILY_TRADES,
            cooldown_period=self.config.COOLDOWN_PERIOD
        )
        
        # self.strategy = create_strategy(
        #     "OpeningRange",
        #     data_manager = self.data_manager,
        #     opening_range_minutes = self.config.OPENING_RANGE_MINUTES,
        #     breakout_threshold = self.config.BREAKOUT_THRESHOLD_PERCENT
        # )
        
        
        self.risk_manager.instant_close = getattr(self.config, "INSTANT_CLOSE_TRADES", "hold")
        self.risk_manager.emit_closed_on_hold = getattr(self.config, "RM_EMIT_CLOSED_ON_HOLD", True)
        self.risk_manager.dry_run_mode = getattr(self.config, "DRY_RUN_ACCOUNTING", True)
        self.risk_manager.contract_multipliers = getattr(self.config, "CONTRACT_MULTIPLIERS", {"ES": 50.0 })
        
        # Bot state
        self.is_running = False
        self.is_paused = False
        self.symbol = self.config.DEFAULT_SYMBOL
        self.monitoring_thread = None
        self.last_price_check = None
        
        # Logging
        self.logger = logging.getLogger(__name__)
        self._setup_logging()
        
        # Performance tracking
        self.start_time = None
        self.total_signals = 0
        self.executed_trades = 0

        # Temporary single per order guard
        self._last_fill_key = None
        self._last_fill_ts = 0.0
        self._seen_fill_ids: set[str] = set()
        self._seen_attempt_ids = set()

        # Avoid spamming exits repeatedly
        self._last_exit_ts: dict[str, float] = {}

        #startup grace
        self._startup_ts = time.time()
        
    def _setup_logging(self):
        """Setup logging configuration."""
        logging.basicConfig(
            level=getattr(logging, self.config.LOG_LEVEL),
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(self.config.LOG_FILE),
                logging.StreamHandler()
            ]
        )

    
    def connect(self) -> bool:
        """
        Connect to the trading platform.
        
        Returns:
            True if connection successful, False otherwise
        """
        try:
            if self.data_manager.connect():
                self.logger.info(f"Successfully connected to {self.data_manager.get_platform_name()}")
                return True
            else:
                self.logger.error("Failed to connect to trading platform")
                return False
        except Exception as e:
            self.logger.error(f"Connection error: {e}")
            return False
    
    def disconnect(self):
        """Disconnect from the trading platform."""
        try:
            self.data_manager.disconnect()
            self.logger.info("Disconnected from trading platform")
        except Exception as e:
            self.logger.error(f"Disconnection error: {e}")
    
    def start(self, symbol: Optional[str] = None) -> bool:
        """
        Start the trading bot.
        
        Args:
            symbol: Trading symbol to monitor. If None, uses default from config.
            
        Returns:
            True if started successfully, False otherwise
        """
        ###### NEW STUFF NEED REMOVING #############
        
        ###### NEW STUFF NEED REMOVING #############

        symbol = symbol or self.symbol or getattr(self.config, "DEFAULT_SYMBOL", "ES")

        if not getattr(self.data_manager, "is_connected", lambda: False)():
            if not self.connect():
                self.logger.error("start(): cannot connect to platform; aborting.")
                return False

        # ensure the UI is on the right symbol (only adapters that implement it)
        try:
            api = getattr(self.data_manager, "api", None)
            if api and hasattr(api, "ensure_symbol_loaded"):
                api.ensure_symbol_loaded(symbol)
        except Exception:
            self.logger.debug("ensure_symbol_loaded failed (non-fatal)", exc_info=True)

        
        # UI PRE-FLIGHT: force Positions/Orders panels into a known-good state 
        try:
            if api and hasattr(api, "ensure_trading_panels_ready"):
                ok = api.ensure_trading_panels_ready(timeout_ms=12000)
                self.logger.info("UI preflight panels ready=%s", ok)
        except Exception:
            self.logger.debug("UI preflight failed (non-fatal)", exc_info=True)

        try:
            self._sync_rm_from_broker(symbol)
        except Exception:
            self.logger.debug("SYNC-RM failed (non-fatal)", exc_info=True)

        self.is_running = True
        self.is_paused = False
        self.symbol = symbol
        self.start_time = datetime.now()
        self.logger.info("Bot loop started for %s (%s)", symbol, type(self.strategy).__name__)
        self.logger.info("RM id (bot thread) = %s", id(getattr(self, "risk_manager", None)))

        # PRE-FLIGHT: get an initial price (try DM first, then API fallback)
        api = getattr(self.data_manager, "api", None)
        first = None
        for _ in range(20):
            first = self.data_manager.get_current_price(symbol)
            if first is None and api and hasattr(api, "get_current_price"):
                try:
                    first = api.get_current_price(symbol)
                except Exception:
                    first = None
            if first is not None:
                break
            time.sleep(0.5)
        if first is None:
            self.logger.warning("No price yet for %s; continuing but signals may delay.", symbol)

        misses = 0 # NEW: count consecutive


        last_log = 0.0
        while self.is_running:
            try:
                # 1) Pull a price (this also feeds the tick buffer in DataManager after our patch)
                price = self.data_manager.get_current_price(symbol)

                ########################
                # Feed ticks to bar store:
                if price is not None:
                    try:
                        self.data_manager.live.ingest_tick(symbol, time.time(), price)
                    except Exception as e:
                        self.logger.warning(f"failed to ingest tick: {e}")
                ########################

                self.logger.debug(f"🎯 BOT GOT PRICE: {price}") # ADD THIS
                
                ## ---- NEW ----
                if price is None:
                    misses += 1
                    if misses in (3, 6):
                        try:
                            if api and hasattr(api, "ensure_symbol_loaded"):
                                api.ensure_symbol_loaded(symbol)
                        except Exception:
                            pass
                    if misses >= 10:
                        self.logger.warning("No ticks for a while; attempting reconnect...")
                        try:
                            self.disconnect()
                        except Exception:
                            pass
                        if not self.connect():
                            self.logger.error("reconnect failed; will keep trying...")
                        misses = 0
                else:
                    misses = 0

                try:
                    if price is not None and hasattr(self, "risk_manager") and hasattr(self.risk_manager, "mark_to_market"):
                        self.risk_manager.mark_to_market(symbol=symbol, last_price=float(price))
                except Exception:
                    # Never let P&L calc break the loop
                    pass

                try:
                    rm = self.risk_manager
                    unreal_total = 0.0
                    for p in rm.positions.values():
                        unreal_total += float(p.get("unrealized") or 0.0)

                    from web_app import _status, _status_lock
                    with _status_lock:
                        _status.setdefault("risk_metrics", {})
                        _status["risk_metrics"]["unrealized_total"] = float(unreal_total)
                except Exception:
                    pass

                try:
                    rm = getattr(self, "risk_manager", None)
                    if rm is not None:
                        rm.dry_run_mode = "hold"
                    analysis = {
                        "current_price": float(price) if price is not None else None,
                        "pnl_daily": float(getattr(self.risk_manager, "daily_pnl", 0.0)),
                        "open_positions": getattr(self.risk_manager, "get_positions", lambda: [])(),
                        "signals_today": int(getattr(self, "signals_generated", 0)),
                        "strategy": type(self.strategy).__name__,
                        "range_position": "unknown",
                        "opening_range": None,
                        "yesterday_day_range": None,
                    }

                    try:
                        sc = self.strategy.analyze_market_context(self.symbol) or {}
                        for k, v in sc.items():
                            # if k not in analysis:
                            analysis[k] = v
                    except Exception:
                        pass

                    self._latest_analysis = analysis

                except Exception as e:
                    self.logger.debug(f"Failed to update  _latest_analysis: {e}")

                try:
                    from web_app import _status, _status_lock # top level singletons in the app
                    with _status_lock:
                        if price is not None:
                            _status["current_price"] = float(price)
                except Exception:
                    pass

                try:
                    lp = getattr(self.strategy, "last_price", None)
                    if (time.time() - last_log) > 5:
                        self.logger.debug(
                            "DBG price=%s last_price=%s last_sig_age=%s", 
                            price, 
                            lp, 
                            0.0 if not hasattr(self.strategy, "last_signal_ts") else (time.time() - self.strategy.last_signal_ts))
                except Exception:
                    pass

                if hasattr(self.strategy, "ingest_tick"):
                    try:
                        # pass epoch seconds (float) for convenience
                        self.strategy.ingest_tick(symbol, time.time(), price)
                    except Exception:
                        # never let UI hiccups kill the loop
                        pass
                
                # Check exits FIRST
                try:
                    self._maybe_exit_position(symbol, price)
                except Exception as e:
                    self.logger.exception("Exit check failed: %s", e)


                # 2) Ask strategy for a signal
                sig = None
                try:
                    # sig = self.strategy.check_breakout(symbol, price)
                    self.strategy = self.strategy_manager.get_active_strategy()
                    sig = self.strategy.check_breakout(symbol, price)
                except Exception as e:
                    self.logger.exception("Strategy error: %s", e)


                # 3) Act on signal
                if sig:
                    self.logger.info("Signal: %s", sig)
                    self._process_signal(sig, price)   # your existing order-routing (respects DRY_RUN)
                    self.analytics.log_signal(
                        signal_id=sig.get("_signal_id", "sig_unknown"),
                        symbol=symbol,
                        signal_type=sig["type"],
                        price=sig["price"],
                        executed=True,
                        or_bounds=getattr(self.strategy, "or_bounds", None),
                        volatility=getattr(self.risk_manager, "vol", {}).get(symbol, {}).get("ewma_abs", None),
                        strategy_name=type(self.strategy).__name__
                    )


                # 4) Optional: update analysis cache (for /api/market_analysis)
                # try:
                #     self._latest_analysis = self.strategy.analyze_market_context(symbol)
                # except Exception:
                #     self._latest_analysis = {"current_price": price}

                #####
                # if not self.data_manager.is_connected():
                #     if not self.connect():
                #         self.logger.error("Cannot connect, aborting start()")
                #         return False
                #####

                # 5) Heartbeat every ~10s
                now = time.time()
                if now - last_log > 10:
                    # adding new here
                    rm = getattr(self, "risk_manager", None)
                    rh_len = len(getattr(rm, "trade_history", []))
                    self.logger.info("HB: price=%s strategy=%s running=%s | RM id=%s trade_history_len=%d", price, type(self.strategy).__name__, self.is_running, id(rm), rh_len)
                    last_log = now
                time.sleep(1)
            except Exception as e:
                self.logger.exception("Main loop exception: %s", e)
                time.sleep(1)

    
    def stop(self):
        """Stop the trading bot."""
        if not self.is_running:
            self.logger.warning("Bot is not running")
            return
        
        self.is_running = False
        
        # Wait for monitoring thread to finish
        if self.monitoring_thread and self.monitoring_thread.is_alive():
            self.monitoring_thread.join(timeout=5)
        
        # Disconnect from platform
        self.disconnect()
        
        self.logger.info("Trading bot stopped")
    
    def pause(self):
        """Pause the trading bot (stops signal generation but keeps monitoring)."""
        if not self.is_running:
            self.logger.warning("Bot is not running")
            return
        
        self.is_paused = True
        self.logger.info("Trading bot paused")
    
    def resume(self):
        """Resume the trading bot."""
        if not self.is_running:
            self.logger.warning("Bot is not running")
            return
        
        self.is_paused = False
        self.logger.info("Trading bot resumed")
    
    def _monitoring_loop(self):
        """Main monitoring loop that runs in a separate thread."""
        self.logger.info("Monitoring loop started")
        
        while self.is_running:
            try:
                if not self.is_paused:
                    self._process_market_data()
                    # self._check_existing_positions()
                
                # Sleep for a short interval
                time.sleep(1)  # Check every second
                
            except Exception as e:
                self.logger.error(f"Error in monitoring loop: {e}")
                time.sleep(5)  # Wait longer on error
        
        self.logger.info("Monitoring loop ended")
    
    def _process_market_data(self):
        """Process current market data and generate signals."""
        try:
            # Get current price
            current_price = self.data_manager.get_current_price(self.symbol)

            self._maybe_exit_position(self.symbol, current_price) # NEW (first)
            
            if current_price <= 0:
                self.logger.warning(f"Invalid price received for {self.symbol}: {current_price}")
                return
            
            self.last_price_check = datetime.now()
            
            # Check for breakout signals
            signal = self.strategy.check_breakout(self.symbol, current_price)
            
            if signal:
                self.total_signals += 1
                self.logger.info(f"Signal generated: {signal}")
                
                # Process the signal
                self._process_signal(signal, current_price)
            
        except Exception as e:
            self.logger.error(f"Error processing market data: {e}")
    
    def _process_signal(self, signal: Dict, current_price: float):
        """
        Process a trading signal and execute if valid.
        
        Args:
            signal: Trading signal dictionary
            current_price: Current market price
        """
        try:
            self.total_signals = getattr(self, "total_signals", 0) + 1
            self.signals_generated = getattr(self, "signals_generated", 0) + 1

            if current_price is None:
                self.logger.warning("No current_price; skipping trade.")
                return

            # config flags
            # figure out if we are in dry-run
            cfg_dry = getattr(self.config, "DRY_RUN", "true")
            cfg_dry_ui = getattr(self.config, "DRY_RUN_UI", "true")
            cfg_dry_acct = getattr(self.config, "DRY_RUN_ACCOUNTING", False)

            is_dry = (str(cfg_dry).lower() == "true")
            is_dry_ui = (str(cfg_dry_ui).lower() == "true")
            is_dry_acct = (str(cfg_dry_acct).lower() == "true") or (cfg_dry_acct is True)
            # 3-state -> bool
            # acct_mode = cfg_dry_acct

            side = (signal.get("type") or signal.get("side") or "BUY").upper()
            sym = signal.get("symbol", self.symbol)
            qty = int(signal.get("qty", 1)) or 1
            price = float(current_price)

            signal_id = _new_id("sig")
            signal["_signal_id"] = signal_id # attach so downstream has it

            self.logger.info(
                "SIG %s side=%s sym=%s qty=%s px=%.2f reason=%s",
                signal_id, side, sym, qty, price, signal.get("reason")
            )

            # ------------------------
            # DRY-RUN BRANCH
            # ------------------------
            if is_dry:
                # drive UI if allowed
                api = getattr(self.data_manager, "api", None)
                if is_dry_ui and api:
                    try:
                        # prefer public method; fallback to private if that's what exist
                        if hasattr(api, "ensure_symbol_loaded"):
                            api.ensure_symbol_loaded(sym)
                        elif hasattr(api, "_ensure_symbol_loaded"):
                            api._ensure_symbol_loaded(sym)
                    except Exception:
                        pass
                    
                    try:
                        if hasattr(api, "set_quantity"):
                            api.set_quantity(qty)
                    except Exception:
                        pass
                    
                    try:
                        if hasattr(api, "click_market_button"):
                            api.click_market_button(side) # do NOT confirm in dry-run
                    except Exception as e:
                        self.logger.warning("Dry-run UI action failed %s", e)                
                    
                
            # Get account balance
            account_balance = self._get_account_balance()
            
            if account_balance <= 0:
                self.logger.warning("Invalid account balance, skipping trade")
                return
            
            # Validate trade with risk manager
            is_valid, reason, quantity = self.risk_manager.validate_trade(
                signal, account_balance, current_price
            )
            
            if not is_valid:
                self.logger.info(f"Trade rejected: {reason}")
                return

            # TEST SAFETY: cap UI execution qty to 1
            exec_qty = int(round(quantity)) if quantity else 1
            exec_qty = max(1, min(exec_qty, 1)) # hard cap to 1 while testing
            
            # Execute the trade
            # Before adding 'exec_qty' this was the original implementation
            success = self._execute_trade(signal, exec_qty, current_price)
            
            if success:
                self.trades_executed = getattr(self, "trades_executed", 0) + 1
                self.logger.info(f"Trade executed successfully: {signal['type']} {exec_qty} {self.symbol}")

                
        except Exception as e:
            self.logger.error(f"Error processing signal: {e}")

    
    def _handle_signal(self, signal: dict):
        sym = signal["symbol"]
        qty = self.risk_manager.get_position_qty(sym)

        # If in a position, ignore strategy entry signals unless we explicitly want flips
        if qty != 0 and not signal.get("is_exit") and not signal.get("allow_flip"):
            self.logger.info("Signal ignored (in position): %s", signal)
            return

        self._execute_trade(signal, signal.get("qty", 1), signal.get("price"))

    
    def _execute_trade(self, signal: Dict, quantity: float, current_price: float) -> bool:
        """
        Execute a trade based on the signal.
        
        Args:
            signal: Trading signal
            quantity: Trade quantity
            current_price: Current market price
            
        Returns:
            True if trade executed successfully, False otherwise
        """
        
        try:
            side = (signal.get("type") or signal.get("side") or "").upper()
            sym = signal.get("symbol") or self.symbol
            qty = int(quantity or 1)
            px = float(current_price or (self.data_manager.get_current_price(sym) or 0.0))
            # api = self.data_manager.api
            # side = signal['type'].lower()  # 'buy' or 'sell'

            signal_id = (signal.get("_signal_id") or _new_id("sig"))
            attempt_id = _new_id("att")

            # is_dry_acct = str(getattr(self.config, "DRY_RUN_ACCOUNTING", "false")).lower() == "true"
            cfg_dry = str(getattr(self.config, "DRY_RUN", "true")).lower()
            cfg_dry_acct = str(getattr(self.config, "DRY_RUN_ACCOUNTING", "hold")).lower()
            api = getattr(self.data_manager, "api", None)

            is_dry = (cfg_dry == "true")
            # 3-state -> bool
            acct_mode = cfg_dry_acct

            self.logger.info(
                "INTENT att=%s sig=%s side=%s sym=%s qty=%d px=%.2f reason=%s",
                attempt_id,
                signal_id, 
                side,
                sym,
                qty,
                px,
                signal.get("reason")
            )

            if is_dry:
                # paper: drive UI up to the final submit (no confirm click)
                # self.logger.info("DRY_RUN %s %s x%s @ %s", side, sym, qty, px)
                if api:
                    try:
                        if hasattr(api, "ensure_symbol_loaded"):
                            api.ensure_symbol_loaded(sym)
                        if hasattr(api, "set_quantity"):
                            api.set_quantity(qty)
                        if hasattr(api, "click_market_button"):
                            api.click_market_button(side.lower(), symbol=sym, skip_position_checks=True)
                        
                    except Exception as e:
                        self.logger.warning("Dry-run UI action failed: %s", e)
                        return False

                
                # self._record_fill(sym, side, qty, px, dry_run=(acct_mode != "false"))
                self._record_fill(sym, side, qty, px, dry_run=True, signal_id=signal_id, attempt_id=attempt_id, exit_reason=signal.get("reason"))
                return True

            # LIVE: actually send the order
            if not api:
                # self.logger.error("No API available for live trade.")
                self.logger.error("Cannot execute live trade: no API adapter attached.")
                return False
            
            ui_enabled = getattr(api, "ui_enabled", True)
            if not ui_enabled:
                self.logger.error("Cannot execute live trade: API UI is disabled.")
                return False

            # self.logger.info(
            #     "LIVE order via UI for %s %s qty=%d @ $%.2f.",
            #     sym,
            #     side,
            #     qty,
            #     px
            # )

            try:
                ui_sym = None
                pos = None
                pos_sym = pos_qty = None

                # 1) Load symbol & set size
                api.ensure_symbol_loaded(sym)

                try:
                    if hasattr(api, "get_active_contract_symbol"):
                        ui_sym = api.get_active_contract_symbol()
                except Exception:
                    ui_sym = None

                try:
                    if hasattr(api, "get_positions"):
                        api._switch_to("positions.tab", "positions.tab_active")
                        pos = api.get_positions(root_symbol=sym, ui_symbol=ui_sym)
                except Exception:
                    pos = None

                # Debug broker position snapshot (so we know WHY we block)
                if pos is None:
                    self.logger.warning("BROKER POS: None (unknown)")
                elif isinstance(pos, list):
                    self.logger.info("BROKER POS: rows=%d sample=%s", len(pos), pos[0] if pos else None)
                else:
                    self.logger.warning("BROKER POS: unexpected type=%s value=%r", type(pos).__name__, pos)

                def _find_broker_row(pos_rows, root_sym, ui_sym):
                    if not isinstance(pos_rows, list):
                        return None
                    want_root = (root_sym or "").upper()
                    want_exact = (ui_sym or "").upper()

                    for r in pos_rows:
                        rs = (r.get("symbol") or "").upper()
                        if want_exact and rs == want_exact:
                            return r
                        if want_root and rs.startswith(want_root):
                            return r
                    return None


                broker_row = _find_broker_row(pos, sym, ui_sym)
                # broker_known = broker_row is not None
                broker_qty_now = broker_row.get("qty") if broker_row else None

                if isinstance(pos, list):
                    # prefer the active contract symbol if available, else the sygnal symbol
                    want = ui_sym or sym
                    match = next((r for r in pos if (r.get("symbol") or "").upper() == (want or "").upper()), None)
                    if match:
                        pos_sym = match.get("symbol")
                        pos_qty = match.get("qty") 

                self.logger.info(
                    "UI STATE: signal_symbol=%s ui_active_symbol=%s matched_symbol=%s matched_quantity=%s",
                    signal.get("symbol"), 
                    ui_sym,
                    pos_sym,
                    pos_qty
                )
                
                api.set_quantity(qty)

                baseline_rows = set()
                if hasattr(api, "snapshot_orders_rows"):
                    br = api.snapshot_orders_rows(limit=40)
                    baseline_rows = br if br else None 

                
                # 2) Click Buy Mkt / Sell Mkt
                # If get_positions() cannot be trusted, treat "None" as unknown.
                # If you choose to also block on "non-empty", uncomment that check too.
                if pos is None:
                    # During the first ~20 seconds after startup, UI can be mid-layout / wrong tab.
                    # Allow orders ONLY if internal RM thinks we're flat AND direction is not stacking.
                    grace = (time.time() - getattr(self, "_startup_ts", 0.0)) < 20.0

                    internal_qty_pre = 0
                    try:
                        internal_qty_pre = int(self.risk_manager.get_position_qty(sym))
                    except Exception:
                        internal_qty_pre = 0

                    if grace and internal_qty_pre == 0:
                        self.logger.warning("Broker Positions unknown -> STARTUP GRACE allowing (internal flat).")
                    else:
                        self.logger.warning("Broker Positions unknown (scrapped failed) -> blocking.")
                        return False

                if isinstance(pos, list) and len(pos) == 0:
                    self.logger.warning("Broker Positions flat (empty list) -> allowing.")
                    # confidently flat -> allow
                    # broker_row = None
                    # return False
                    # pass
                else:
                    broker_row = _find_broker_row(pos, sym, ui_sym)
                    if broker_row is None:
                        # show that symbols we actually saw
                        seen = []
                        for r in (pos if isinstance(pos, list) else []):
                            seen.append((r.get("symbol"), r.get("qty")))
                        self.logger.warning(
                            "Broker positions known but row not matched sym=%s ui_sym=%s seen->%s -> blocking", 
                            sym, ui_sym, seen[:10]
                        )
                        return False

                # Optional stricter rule: block if ANY open position exists (avoid stacking completely)
                # if len(pos) > 0:
                #       self.logger.warning("Existing position(s) detected - blocking live order to avoid stacking.")
                #       return False
                # api.click_market_button(side.lower())

                # INTERNAL stacking guard (independent of broker)
                try:
                    internal_qty_pre = self.risk_manager.get_position_qty(sym)
                except Exception:
                    internal_qty_pre = None

                if internal_qty_pre not in (None, 0):
                    is_close_direction = (
                        (internal_qty_pre > 0 and side == "SELL") or 
                        (internal_qty_pre < 0 and side == "BUY")
                    )
                    if not is_close_direction:
                        self.logger.warning(
                            "BLOCKED by Internal guard: Internal_qty_pre=%s side=%s sym=%s sig=%s",
                            internal_qty_pre, side, sym, signal_id
                        )
                        return False

                # if internal_qty_pre not in (None, 0):
                #     self.logger.warning(
                #         "Internal position not flat (qty=%s) -> blocking new entry to avoid stacking. sig=%s",
                #         internal_qty_pre, signal_id
                #     )
                #     return False

                self.logger.info(
                    "LIVE order via UI for %s %s qty=%d @ $%.2f.",
                    sym,
                    side,
                    qty,
                    px
                )
                # self.logger.info(
                #     "ATT %s sig=%s outer_click side=%s sym=%s qty=%d",
                #     attempt_id, signal_id, side, sym, qty
                # )

                clicked = api.click_market_button(side.lower(), symbol=sym, skip_position_checks=True)
                if not clicked:
                    self.logger.error(
                        "Outer market click failed/blocked; will NOT attempt confirm."
                    )
                    return False

                t0 = time.time()
                # 3) Confirm the popup (if supported)
                # sent = True
                confirmed = True
                if hasattr(api, "confirm_order"):
                    confirmed = api.confirm_order(side)
                    
                self.logger.info(
                    "CNF %s sig=%s confirmed=%s side=%s sym=%s qty=%d",
                    attempt_id, signal_id, bool(confirmed), side, sym, qty
                )

                if not confirmed:
                    self.logger.error(
                        "LIVE order UI for %s %s qty=%d @ %.2f "
                        "NOT confirmed (confirm_order returned False); aborting",
                        sym, 
                        side,
                        qty,
                        px
                    )
                    self.logger.error("INVARIANT: confirm_order=False -> must NOT record fill (sig=%s att=%s)", signal_id, attempt_id)
                    return False

                # wait briefly for Orders table to update
                fill_px = None
                if hasattr(api, "get_latest_filled_order"):
                    deadline = time.time() + 4.0
                    while time.time() < deadline:
                        try:
                            o = api.get_latest_filled_order(symbol=sym, side=side, since_ts=t0, baseline_rows=baseline_rows)
                            if o and o.get("avg_fill") is not None:
                                fill_px = float(o["avg_fill"])
                                self.logger.info("EXEC PX from orders table: %.2f (was %.2f) row=%s", fill_px, px, o.get("row_text"))
                                break
                        except Exception as e:
                            # fill_px = None
                            self.logger.warning("Orders-table exec px scrape failed: %s", e)
                        time.sleep(0.25)

                    if fill_px is None:
                        self.logger.info("Orders-table: no matching FILLED row found (sym=%s side=%s)", sym, side)

                px_exec = fill_px if fill_px is not None else px # fallback

                # Temporary logging info
                self.logger.info(
                    "POST-CNF Will record fill now (sig=%s att=%s side=%s sym=%s)",
                    signal_id, attempt_id, side, sym
                )

                # 4) Only now do we record the fill
                self.logger.info(
                    "LIVE %s %s x%s @ %s | sig=%s att=%s",
                    side, sym, qty, px_exec, signal_id, attempt_id
                )
                # self.logger.info("LIVE %s %s x%s @ %s", side, sym, qty, px)
                # Only after UI worked, record live fill
                # self._record_fill(sym, side, qty, px, dry_run=(acct_mode != "false"))
                fill = self._record_fill(sym, side, qty, px_exec, dry_run=False, signal_id=signal_id, attempt_id=attempt_id, exit_reason=signal.get("reason"))

                try:
                    self.logger.info(
                        "AFTER-FILL: internal_qty=%s pos=%s",
                        self.risk_manager.get_position_qty(sym),
                        (self.risk_manager.get(sym) if hasattr(self.risk_manager, "positions") else None)
                    )
                except Exception:
                    pass

                if not isinstance(fill, dict):
                    self.logger.error("FILL missing after confirmed order: sig=%s att=%s (dedupe or RM error)", signal_id, attempt_id)

                # Broker truth
                broker_qty = None
                try:
                    match = None
                    for attempt in range(3):
                        api._switch_to("positions.tab", "positions.tab_active")
                        pos_rows = api.get_positions(root_symbol=sym, ui_symbol=ui_sym, include_zero_rows=True) if hasattr(api, "get_positions") else None
                        if not isinstance(pos_rows, list):
                            broker_qty = None
                        else:
                            # Prefer the active contract symbol if we can read it
                            ui_sym2 = None
                            if hasattr(api, "get_active_contract_symbol"):
                                try:
                                    ui_sym2 = api.get_active_contract_symbol()
                                except Exception:
                                    ui_sym2 = None

                            want_root = (sym or "").upper()
                            want_exact = (ui_sym2 or "").upper()

                            for r in pos_rows:
                                rs = (r.get("symbol") or "").upper()
                                if want_exact and rs == want_exact:
                                    match = r
                                    break
                                if rs == want_root or rs.startswith(want_root): # ES -> ESH6
                                    match = r
                                    break

                            # match = next((r for r in pos_rows if (r.get("symbol") or "").upper() == want), None)
                            broker_qty = match.get("qty") if match else None

                        # break early once broker shows non-zero (or if we got a confident 0 on last try)
                        if broker_qty is not None and (broker_qty != 0 or attempt == 2):
                            break

                        if attempt < 2:
                            time.sleep(0.5)
                            
                except Exception:
                    broker_qty = None

                # Internal truth (simple, use your RM view)
                try:
                    internal_qty = self.risk_manager.get_position_qty(sym)  # implement if missing (see below)
                except Exception:
                    internal_qty = None

                opened = fill.get("opened") if isinstance(fill, dict) else None
                closed = fill.get("closed") if isinstance(fill, dict) else None
                fill_id = fill.get("fill_id") if isinstance(fill, dict) else None
                self.logger.info(
                    "TRUTH sig=%s fill=%s sym=%s broker_qty=%s internal_qty=%s broker_row_text=%s",
                    signal_id, fill_id, sym, broker_qty, internal_qty,
                    (match.get("row_text") if match else None)
                )

                return True

            except Exception as e:
                self.logger.error(f"LIVE order UI failed: %s", e)
                return False

        except Exception as e:
            self.logger.error(f"Error executing trade: {e}")
            return False
    
    def _check_existing_positions(self):
        """Check existing positions for stop loss or take profit triggers."""
        try:
            for symbol in list(self.risk_manager.current_positions.keys()):
                current_price = self.data_manager.get_current_price(symbol)
                
                if current_price <= 0:
                    continue
                
                # Check if stop loss or take profit should be triggered
                exit_reason = self.risk_manager.check_stop_loss_take_profit(symbol, current_price)
                
                if exit_reason:
                    self._close_position(symbol, current_price, exit_reason)
                    
        except Exception as e:
            self.logger.error(f"Error checking positions: {e}")
    
    def _close_position(self, symbol: str, current_price: float, reason: str):
        """
        Close a position.
        
        Args:
            symbol: Trading symbol
            current_price: Current market price
            reason: Reason for closing
        """
        try:
            position = self.risk_manager.get_position_info(symbol)
            
            if not position:
                self.logger.warning(f"No position found for {symbol}")
                return
            
            # Determine opposite side for closing
            close_side = 'sell' if position['side'].lower() == 'buy' else 'buy'
            quantity = position['quantity']
            
            # Place closing order
            api = self.data_manager.api
            order_result = api.place_market_order(symbol, close_side, quantity)
            
            if 'error' in order_result:
                self.logger.error(f"Failed to close position: {order_result['error']}")
                return
            
            # Record trade exit
            self.risk_manager.record_trade_exit(symbol, current_price, reason)
            
            self.logger.info(f"Position closed: {symbol} at {current_price}, Reason: {reason}")
            
        except Exception as e:
            self.logger.error(f"Error closing position: {e}")
    
    def _get_account_balance(self) -> float:
        """
        Get current account balance.
        
        Returns:
            Account balance in base currency
        """
        try:
            bal = self.data_manager.api.get_balance() or {}
            usd = bal.get("USD", {})
            free = usd.get("total") or usd.get("free")

            # Check for None or NaN
            if free is None or (isinstance(free, float) and free != free):
                # fallback to cached UI value
                free = getattr(self.data_manager.api, "_last_equity", None)

            # Still bad? Fallback to configured SIM_BALANCE
            if free is None or (isinstance(free, float) and free != free):
                free = float(self.config.SIM_BALANCE)

            return float(free)
            
            if not balance_info:
                return 0.0
            
            
        except Exception as e:
            self.logger.error(f"Error getting account balance: {e}")
            # return 0.0
            return float(self.config.SIM_BALANCE)
    
    def get_status(self) -> Dict[str, Any]:
        """
        Get current bot status.
        
        Returns:
            Dictionary with bot status information
        """
        uptime = datetime.now() - self.start_time if self.start_time else timedelta(0)
        
        status = {
            'is_running': self.is_running,
            'is_paused': self.is_paused,
            'symbol': self.symbol,
            'platform': self.data_manager.get_platform_name(),
            'connected': self.data_manager.is_connected(),
            'uptime_seconds': uptime.total_seconds(),
            'last_price_check': self.last_price_check.isoformat() if self.last_price_check else None,
            'total_signals': self.total_signals,
            'executed_trades': self.executed_trades,
            'strategy_status': self.strategy.get_strategy_status(),
            'risk_metrics': self.risk_manager.get_risk_metrics()
        }
        
        # Add current price if connected
        if self.data_manager.is_connected():
            try:
                status['current_price'] = self.data_manager.get_current_price(self.symbol)
            except:
                status['current_price'] = None
        
        return status
    
    def get_market_analysis(self) -> Dict:
        """
        Get current market analysis.
        
        Returns:
            Dictionary with market analysis
        """
        try:
            return self.strategy.analyze_market_context(self.symbol)
        except Exception as e:
            self.logger.error(f"Error getting market analysis: {e}")
            return {}
    
    def emergency_stop(self) -> Dict:
        """
        Emergency stop all trading activities.
        
        Returns:
            Emergency stop status
        """
        self.logger.warning("EMERGENCY STOP INITIATED")
        
        # Stop the bot
        self.stop()
        
        # Activate risk manager emergency stop
        risk_status = self.risk_manager.emergency_stop()
        
        return {
            'bot_stopped': True,
            'timestamp': datetime.now().isoformat(),
            'risk_manager_status': risk_status
        }
    
    def set_symbol(self, symbol: str):
        """
        Change the trading symbol.
        
        Args:
            symbol: New trading symbol
        """
        old_symbol = self.symbol
        self.symbol = symbol
        
        # Reset strategy for new symbol
        self.strategy.reset_strategy()
        
        self.logger.info(f"Symbol changed from {old_symbol} to {symbol}")
    
    def get_trade_history(self) -> List[Dict]:
        """
        Get trade history.
        
        Returns:
            List of completed trades
        """
        return self.risk_manager.trade_history.copy()
    
    def get_open_positions(self) -> Dict:
        """
        Get current open positions.
        
        Returns:
            Dictionary of open positions
        """
        return {p["symbol"]: p for p in self.risk_manager.get_positions()}
        # return self.risk_manager.current_positions.copy()


    def set_strategy(self, name: str, params: Dict[str, Any] | None = None):
        """
        Swap the active strategy at runtime.
        Safe to call before start(), or while paused.
        """
        self.logger.info(f"🔥 SET_STRATEGY CALLED: name={name} params={params}")
        params = params or {}

        # 1) Persist user params on the bot (so the trading loop can read them later)
        #  These keys match what your dashboard sends.
        self.opening_range_minutes = int(params.get("opening_range_minutes", getattr(self, "opening_range_minutes", 30)))
        self.breakout_threshold = float(params.get("breakout_threshold", getattr(self, "breakout_threshold", 0.1)))
        self.stop_loss_percent = float(params.get("stop_loss_percent", getattr(self, "stop_loss_percent", 2.0)))
        self.take_profit_percent = float(params.get("take_profit_percent", getattr(self, "take_profit_percent", 4.0)))
        self.breakout_points = float(params.get("breakout_points", getattr(self, "breakout_points", getattr(self.config, "BREAKOUT_POINTS", 2.0))))
        self.min_move_from_or = float(params.get("min_move_from_or", getattr(self, "min_move_from_or", getattr(self.config, "MIN_MOVE_FROM_OR", 1.5))))

        old = type(self.strategy).__name__ if hasattr(self, "strategy") else None

        # 2) Rebuild the strategy via the factory (pass params through so
        #  strategies that accept them can consume directly)
        merged = {
            "opening_range_minutes": self.opening_range_minutes,
            "breakout_threshold": self.breakout_threshold,
            "stop_loss_percent": self.stop_loss_percent,
            "take_profit_percent": self.take_profit_percent,
            "breakout_points": self.breakout_points,
            "min_move_from_or": self.min_move_from_or,
            **params, # explicit params from caller win over defaults move
        }

        self.strategy = create_strategy(
            name,
            data_manager=self.data_manager,
            **merged
        )
        self.logger.info(f"✅ STRATEGY NOW: {type(self.strategy).__name__}")

        # 3) (Optional) also reflect params onto strategy instance for convenience
        for k in ("opening_range_minutes", "breakout_threshold", "stop_loss_percent", "take_profit_percent", "breakout_points", "min_move_from_or"):
            try:
                setattr(self.strategy, k, getattr(self, k))
            except Exception:
                pass
        
        # 4) Reset strategy internal state if available
        try:
            # Reset internal state if the strategy supports it
            if hasattr(self.strategy, "reset_strategy"):
                self.strategy.reset_strategy()
        except Exception:
            pass
        
        self.logger.info(f"Strategy changed from {old} to {type(self.strategy).__name__} with params={params}")


    def _record_fill(
        self,
        symbol: str,
        side: str,
        qty: int,
        price: float,
        dry_run: bool,
        # new debug addition
        signal_id=None,
        attempt_id=None,
        exit_reason: str | None = None
    ):
        fill_id = f"fill_{signal_id}_{attempt_id}" if signal_id and attempt_id else _new_id("fill")

        if fill_id in self._seen_fill_ids:
            self.logger.error("FILL DUPED: fill_id:=%s already seen", fill_id)
            return None
        self._seen_fill_ids.add(fill_id)

        rm = getattr(self, "risk_manager", None)
        if not rm:
            self.logger.error("FILL skipped: no risk_manager attached")
            return None

        if attempt_id:
            if attempt_id in self._seen_attempt_ids:
                # if getattr(self, "_last_attempt_id", None) == attempt_id:
                self.logger.warning("FILL deduped by attempt_id=%s sig=%s", attempt_id, signal_id)
                return None
            # self._last_attempt_id = attempt_id
            self._seen_attempt_ids.add(attempt_id)

        # Prevent double-recording the same event (common with UI + polling threads)
        if not attempt_id:
            key = (str(symbol).upper(), str(side).upper(), int(qty), float(price), bool(dry_run))
            now = time.time()
            if getattr(self, "_last_fill_key", None) == key and (now - getattr(self, "_last_fill_ts", 0.0)) < 2.0:
                self.logger.warning("FILL deduped by key: %s", key)
                return None

            self._last_fill_key = key
            self._last_fill_ts = now

        try:
            before = len(rm.trade_history)
            trade = rm.paper_fill(
                #NEW
                fill_id=fill_id,
                signal_id=signal_id,
                attempt_id=attempt_id,
                symbol=symbol,
                side=side,
                qty=int(qty),
                price=float(price),
                dry_run=bool(dry_run),
                exit_reason=exit_reason
            )
            # after = len(rm.trade_history)
            self.logger.info(
                "RM paper_fill: %s | sig: %s | att: %s | recorded: %s | trades=%d | mode=%s",
                fill_id,
                signal_id,
                attempt_id,
                trade,
                len(rm.trade_history),
                getattr(rm, "instant_close", None)
            )
            return {
                "fill_id": fill_id,
                "signal_id": signal_id,
                "attempt_id": attempt_id,
                "trade": trade, # only for logging fine by now, in the future might need to adjust to match paper_fill {"closed":..., "opened":...}
            }

        except Exception as e:
            self.logger.error("RM paper_fill failed %s", e)


    def get_position_qty(self, symbol: str) -> int:
        sym = (symbol or "").upper()
        qty = 0
        for t in getattr(self, "trade_history", []):
            if (t.get("symbol") or "").upper() != sym:
                continue
            side = (t.get("side") or "").upper()
            q = int(t.get("qty") or 0)
            qty += q if side == "BUY" else -q
        return qty


    def _maybe_exit_position(self, symbol: str, current_price: float):
        rm = self.risk_manager

        qty = rm.get_position_qty(symbol)
        if qty == 0:
            self.logger.debug("EXIT-CHECK: qty=0 -> skip (sym=%s px=%s)", symbol, current_price)
            return

        # prevent exit spam (2s)
        now = time.time()
        if (now - self._last_exit_ts.get(symbol, 0.0)) < 2.0:
            self.logger.info("EXIT-CHECK: rate-limited -> skip (sym=%s)", symbol)
            return

        # Option B: Clean - Use helper from RM)
        stop_pts, take_pts = rm.calculate_dynamic_stops(symbol, current_price)


        # logging the position state we are using
        sym = (symbol or "").upper()
        pos = rm.positions.get(sym) or {}
        self.logger.info(
            "EXIT-CHECK: sym=%s qty=%s px=%s avg=%s stop_pts=%s take_pts=%s", 
            symbol, qty, current_price, pos.get("avg_price"), stop_pts, take_pts
        )
        
        reason = rm.check_exit_points(symbol, current_price, stop_pts, take_pts)
        if not reason:
            self.logger.info("EXIT-CHECK: no trigger (sym=%s)", symbol)
            return

        self._last_exit_ts[symbol] = now

        close_side = "SELL" if qty > 0 else "BUY"
        self.logger.info("EXIT: reason=%s qty=%s -> sending %s", reason, qty, close_side)
        # self.logger.info("EXIT-ATR: vol=%.2f stop_pts=%.2f take_pts=%.2f", vol, stop_pts, take_pts)

        exit_signal = {"type": close_side, "symbol": symbol, "reason": reason, "is_exit": True, "_signal_id": _new_id("exit")}
        self._execute_trade(exit_signal, abs(qty), current_price)


    def _sync_rm_from_broker(self, symbol: str):
        api = getattr(self.data_manager, "api", None)
        if not api or not hasattr(api, "get_positions"):
            return

        ui_sym = None
        try:
            if hasattr(api, "get_active_contract_symbol"):
                ui_sym = api.get_active_contract_symbol()
        except Exception:
            ui_sym = None

        pos_rows = None
        try:
            pos_rows = api.get_positions(root_symbol=symbol, ui_symbol=ui_sym, include_zero_rows=True)
        except Exception:
            pos_rows = None

        if not isinstance(pos_rows, list):
            return

        # find a matching row for ES / ESH6, etc
        want_root = (symbol or "").upper()
        want_exact = (ui_sym or "").upper()
        match = None
        for r in pos_rows:
            rs = (r.get("symbol") or "").upper()
            if want_exact and rs == want_exact:
                match = r
                break
            if want_root and rs.startswith(want_root):
                match = r
                break

        if not match:
            return

        qty = match.get("qty")
        # if qty is None, do nothing
        if qty is None:
            return

        # ✅ IMPORTANT: update RM's current position qty so exit checks work after restart
        # We'll preserve avg_price if RM already has it; otherwise set avg_price to current price
        rm = self.risk_manager
        sym = want_root
        existing = rm.positions.get(sym) or {}
        rm.positions[sym] = {
            "qty": int(qty),
            "avg_price": float(existing.get("avg_price") or self.data_manager.get_current_price(sym) or 0.0),
        }
        self.logger.info("SYNC-RM: sym=%s qty=%s avg=%s", sym, rm.positions[sym]["qty"], rm.positions[sym]["avg_price"])


    def set_strategy_manual(self, strategy_name: str, params: dict = None):
        """Manually override auto-switching for special events"""
        if not hasattr(self, 'strategy_manager'):
            return False
    
        if strategy_name not in self.strategy_manager.strategies:
            self.logger.error(f"Unknown strategy: {strategy_name}")
            return False
    
        self.strategy_manager.manual_override = True
        self.strategy_manager.manual_strategy_name = strategy_name
        self.logger.info(f"🔧 MANUAL OVERRIDE: {strategy_name}")
        return True


    def clear_strategy_override(self):
        """Return to auto-switching"""
        if hasattr(self, 'strategy_manager'):
            self.strategy_manager.manual_override = False
            self.strategy_manager.manual_strategy_name = None
            self.logger.info("✅ Returning to auto-switching")
            return True
        return False





    
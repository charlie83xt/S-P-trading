"""
Flask Web Application for Futures Trading Bot Dashboard
"""

from flask import Flask, render_template, request, jsonify, redirect, url_for, send_from_directory
from queue import Queue, Empty
import json
import threading
import time
from datetime import datetime
import logging, os
import traceback
import sys

from trading_bot import TradingBot
from config import Config
from api_factory import APIFactory
from minute_bar_builder import MinuteBarBuilder

APP_DIR = os.path.dirname(os.path.abspath(__file__))
# DASHBOARD_FILE = os.path.join(APP_DIR, "dashboard.html")

log = logging.getLogger("startup")

app = Flask(__name__, static_folder=None)
app.logger.info("=== web_app boot ===")
app.secret_key = 'trading_bot_secret_key_2024'

# ---- ADD THIS BLOCK HERE ----
import trading_bot, risk_manager, api_factory, config
import tradovate_web_ui_api  # wherever it is imported from

log.info("Loaded trading_bot from: %s", trading_bot.__file__)
log.info("Loaded api_factory from: %s", api_factory.__file__)
log.info("Loaded config from: %s", config.__file__)
log.info("Loaded tradovate_web_ui_api from: %s", tradovate_web_ui_api.__file__)
log.info("CWD: %s", os.getcwd())
# ---- END BLOCK ----

cfg = Config()
api = APIFactory.create_api(cfg) # uses TRADING_PLATFORM=tradovate_ui
bot = TradingBot(config=cfg)

#### ---- Adding this thing here ------- ####
# bot.risk_manager.dry_run_mode = "hold"
# bot.risk_manager.instant_close = "hold"
bot.risk_manager.contract_multipliers = getattr(cfg, "CONTRACT_MULTIPLIERS", {"ES": 50.0})
#### ---- closing this thing here ------- ####

_status_lock = threading.Lock()

_status = {
    "is_running": False,
    "is_paused": False,
    "symbol": getattr(cfg, "DEFAULT_SYMBOL", "ES"),
    "platform": getattr(cfg, "TRADING_PLATFORM", "tradovate_ui"),
    "connected": False,
    "strategy": None,
    "strategy_params": {},
    "current_price": None,
    "total_signals": 0,
    "executed_trades": 0,
    "daily_trades": 0,
    "daily_pnl": 0.0,
    "risk_metrics": {"win_rate": 0.0, "daily_pnl": 0.0},
}
# _status = {}

# >>> Adding Safe priming (no playwright calls here)
try:
    # Make sure the bot's DataManager uses the API we just created.
    if hasattr(bot, "data_manager"):
        bot.data_manager.api = api
    # Seed  symbol immediately so UI shows it even before Start
    bot.symbol = getattr(cfg, "DEFAULT_SYMBOL", "ES")

    # prime a minimal analyst object so /api/market_analysis renders nicely
    bot._latest_analysis = {
        "current_price": None,   # trading thread will fill it
        "pnl_daily": float(getattr(getattr(bot, "risk_manager", None), "daily_pnl", 0.0)),
        "open_positions": [],
        "signals_today": int(getattr(bot, "signals_generated", 0)),
        "strategy": (type(s).__name__ if (s := getattr(bot, "strategy", None)) else None),
        "range_position": "unknown",
        "opening_range": None,
        "yesterday_day_range": None,
    }

    # Also seed _status so the header doesn't look empty pre-start
    with _status_lock:
        _status["symbol"] = bot.symbol
        _status["strategy"] = bot._latest_analysis["strategy"]
        _status["current_price"] = None # Trading thread will keep this alive
except Exception as e:
    app.logger.debug("startup priming failed (non-fatal): %s", e)

# --- background trading thread + command queue ---
_trading_thread = None
_cmd_q: Queue = Queue()
_thread_ready = threading.Event()
_thread_connected = threading.Event()
_thread_error = None
_last_strategy_name = None
_last_strategy_params = {}


# Global bot instance
bot_thread = None
PRICE_POLL = True

def _snap_status(from_trading_thread: bool = False):
    try:
        dm = getattr(bot, "data_manager", None)
        api = getattr(dm, "api", None)
        rm  = getattr(bot, "risk_manager", None)
        s_obj = getattr(bot, "strategy", None)


        with _status_lock:
            _status["connected"] = bool(_thread_connected.is_set())
            _status["is_running"] = bool(getattr(bot, "is_running", False))
            _status["is_paused"] = bool(getattr(bot, "is_paused", False))
            _status["platform"] = getattr(cfg, "TRADING_PLATFORM", "tradovate_ui")


            # symbol + strategy name
            _status["symbol"] = getattr(bot, "symbol", None) or getattr(cfg, "DEFAULT_SYMBOL", "ES")
            _status["strategy"] = type(s_obj).__name__ if s_obj else None


            # keep a current_price even if heartbeat hasn’t filled it yet
            _status.setdefault("current_price", None)
            if _status["current_price"] in (None, 0, 0.0) and api and hasattr(api, "get_current_price"):
                try:
                    p = api.get_current_price(_status["symbol"])  # if your method is get_current_price, use that
                except Exception:
                    p = None
                if p is not None:
                    _status["current_price"] = float(p)


            # strategy params (sandboxed so errors here don't break counters)
            if s_obj:
                try:
                    params = {}
                    for k in ("opening_range_minutes", "breakout_threshold", "stop_loss_percent", "take_profit_percent"):
                        if hasattr(s_obj, k):
                            v = getattr(s_obj, k)
                            params[k] = float(v) if isinstance(v, (int, float)) else v
                    _status["strategy_params"] = params
                except Exception:
                    _status["strategy_params"] = {}
            else:
                _status["strategy_params"] = {}


            # === COUNTERS ===
            # web_app.py  (_snap_status)
            rm  = getattr(bot, "risk_manager", None)
            trade_hist = list(getattr(rm, "trade_history", []) or [])
            positions = getattr(rm, "positions", {}) or {}


            # Signals
            signals_val = getattr(bot, "total_signals", None)
            if signals_val is None:
                # older name
                swignal_val = getattr(bot, "signals_generated", 0)
                if not signals_val:
                    signals_val = len(getattr(bot, "signal_history", []))

            # _status["total_signals"] = int(
            #     getattr(bot, "signals_generated", 0) or len(getattr(bot, "signal_history", []))
            # )
            _status["total_signals"] = int(signals_val)

            # Executed trades = closed trades from history
            _status["executed_trades"] = len(trade_hist)


            # Daily trades / Daily PnL (UTC date match on t['ts'])
            from datetime import datetime, timezone
            def _is_today(ts):
                try:
                    dt = datetime.fromisoformat(str(ts).replace("Z","+00:00"))
                    return dt.date() == datetime.now(timezone.utc).date()
                except Exception:
                    return False


            daily_trades = [t for t in trade_hist if _is_today(t.get("ts"))]
            _status["daily_trades"] = len(daily_trades)

            # realized PnL for trades closed today
            daily_realized = 0.0
            for t in daily_trades:
                try:
                    daily_realized += float(t.get("pnl", 0.0) or 0.0)
                except Exception:
                    pass

            # unrealized PnL across all open positions right now         
            unreal_total = 0.0
            for ppos in positions.values():
                try:
                    unreal_total += float(ppos.get("unrealized", 0.0) or 0.0)
                except Exception:
                    pass

            # expose open positions count at top-level for the dashboard tile
            _status["open_positions_count"] = int(len(positions))

            # 1) realized today = only closed if it has an exit_price 
            # daily_realized = sum(float(t.get("pnl", 0.0) or 0.0) for t in daily_trades)
            # keep your existing unrealized calc:
            # positions = getattr(rm, "positions", {}) or {}
            # unreal = float(sum((p or {}).get("unrealized", 0.0) for p in positions.values())) if positions else 0.0


            # Win rate from history
            wins = 0
            # wins = sum(1 for t in trade_hist if float(t.get("pnl", 0.0) or 0.0) > 0.0)
            closed = 0 
            for trade in trade_hist:
                # consider it "closed" if we actually have an exit_price
                if t.get("exit_price") is not None:
                    closed += 1
                    try:
                        if float(t.get("pnl", 0.0) or 0.0) > 0.0:
                            wins += 1
                    except Exception:
                        pass

            # losses = sum(1 for t in trade_hist if float(t.get("pnl", 0.0) or 0.0) < 0.0)
            # win_rate = (wins / (wins + losses)) * 100.0 if (wins + losses) else 0.0
            win_rate = 100.0 * (wins / closed) if closed > 0 else 0.0

            # build risk_metrics blob for the UI
            # daily_pnl:
            # prefer rm.daily_pnl (mark-to-market view),
            # fallback to sum of realized pnl on today's closed trades
            rm_daily_pnl = getattr(rm, "daily_pnl", None)
            if rm_daily_pnl is None:
                rm_daily_pnl = daily_realized


            _status["risk_metrics"] = {
                # "daily_pnl": float(getattr(rm, "daily_pnl", daily_realized) or daily_realized),
                "daily_pnl": float(daily_realized),
                "win_rate": float(win_rate),
                # "win_rate": float(getattr(bot, "win_rate", win_rate) or win_rate),
                "realized_total": float(getattr(rm, "realized_pnl", 0.0) or 0.0),
                # "unrealized_total": unreal,
                "unrealized_total": float(unreal_total),
                "open_positions_count": int(len(positions)),
            }

            # # Signals: use bot.signals_generated if you maintain it; else fall back to bot.signal_history length if you have it
            # _status["total_signals"] = int(getattr(bot, "signals_generated", 0) or len(getattr(bot, "signal_history", [])))


            # # Trades executed: prefer bot.trades_executed, else count risk_manager.trades (closed trades)
            # trades_in_rm = getattr(rm, "trades", None)
            # _status["executed_trades"] = int(getattr(bot, "trades_executed", 0) or (len(trades_in_rm) if isinstance(trades_in_rm, (list, dict)) else 0))


            # # Open positions: expose both top-level and inside risk_metrics for backward/forward compatibility
            # positions = getattr(rm, "positions", {}) or {}
            # open_cnt = len(positions)
            # _status["open_positions_count"] = int(open_cnt)


            # # Risk metrics block (keep open_positions_count mirrored here too)
            # realized = float(getattr(rm, "realized_pnl", 0.0)) if rm else 0.0
            # unreal = float(sum((p or {}).get("unrealized", 0.0) for p in positions.values())) if positions else 0.0
            # _status["risk_metrics"] = {
            #     "daily_pnl": float(getattr(rm, "daily_pnl", 0.0)) if rm else 0.0,
            #     "win_rate": float(getattr(bot, "win_rate", 0.0)),
            #     "realized_total": realized,
            #     "unrealized_total": unreal,
            #     "open_positions_count": int(open_cnt),
            # }


        # outside lock, update current_price from heartbeat or latest_analysis if available
        sym = _status["symbol"]
        if from_trading_thread:
            try:
                if api and hasattr(api, "get_current_price"):
                    p = api.get_current_price(sym)
                    if p is not None:
                        with _status_lock:
                            _status["current_price"] = float(p)
            except Exception:
                pass
        else:
            try:
                p = (getattr(bot, "_latest_analysis", {}) or {}).get("current_price")  # if your key is _latest_analysis, use that
                if p is not None:
                    with _status_lock:
                        _status["current_price"] = float(p)
            except Exception:
                pass


    except Exception:
        # never let this raise; STATUS must keep flowing
        pass



def _get_json() -> dict:
    """Robust JSON body parsing that never returns None."""
    try:
        data = request.get_json(force=False, silent=True)
        if isinstance(data, dict):
            return data
        raw = request.data.decode("utf-8", errors="replace") if request.data else ""
        return json.loads(raw) if raw else {}
    except Exception:
        return {}


def _rpc(cmd: str, payload: dict | None = None, timeout: float = 30.0) -> dict:
    """
    Send a command to the trading thread and wait for a JSON result.
    The trading thread must put a dict onto payload['reply'].
    """
    payload = payload or {}
    reply_q: Queue = Queue()
    payload['reply'] = reply_q
    _ensure_trading_thread()
    _cmd_q.put((cmd, payload))
    try:
        result = reply_q.get(timeout=timeout)
        if not isinstance(result, dict):
            return {"success": False, "message": f"Bad reply type: {type(result)}"}
        return result
    except Empty:
        return {"success": False, "message": f"Timeout waiting for: {cmd} reply"}

@app.errorhandler(Exception)
def _any_error(e):
    # Log full stack on the server; always return JSON to the client
    app.logger.exception("Unhandled error")
    return jsonify({"success": False, "message": str(e)}), 500


@app.route('/')
def dashboard():
    """Main dashboard page."""
    return render_template('dashboard.html')


@app.errorhandler(404)
def not_found(e):
    app.logger.warning("404 on %s %s", request.method, request.path)
    return jsonify({"success": False, "error": "Not Found", "path": request.path}), 404


def _trading_main():
    """Owns Playwright (TradovateWebUIAPI) and runs the bot. All UI actions happen here"""
    global cfg, api, bot, _thread_error, _trading_thread, _last_strategy_name, _last_strategy_params
    _trading_thread = threading.current_thread()
    _thread_error = None
    _thread_ready.set()
    # connected = False
    last_hb = 0.0

    _last_strategy_name = None
    _last_strategy_params = {}


    while True:
        # heatbeat: refresh status every ~1s even if nop commands
        now = time.time()
        if now - last_hb > 1.0:
            _snap_status(from_trading_thread=True)
            # NEW: push chart price scoped to the current symbol
            if PRICE_POLL and api: # keep your env guard if you added it]
                try:
                    sym = getattr(bot, "symbol", getattr(cfg, "DEFAULT_SYMBOL", "ES"))
                    price = api.get_current_price(sym)
                    if price is not None and price == price:
                        with _status_lock:
                            s = getattr(bot, "strategy", None)
                            _status["current_price"] = float(price)
                            _status["strategy"] = type(s).__name__ if s else None

                        # Keep the analysis snapshot in sync so api/market_analysis shows it
                        try:
                            if not hasattr(bot, "_latest_analysis") or bot._latest_analysis is None:
                                bot._latest_analysis = {}
                            bot._latest_analysis["current_price"] = float(price)
                        except Exception:
                            pass
                        # app.logger.info("HB: sym=%s price=%s (poll)", sym, price)
                    else:
                        app.logger.debug("HB: sym=%s price unavailable from API", sym)
                except Exception as e:
                    app.logger.debug("HB: api.get_current_price failed: %s", e)
            last_hb = now

        try:
            item = _cmd_q.get(timeout=0.1)
        except Empty:
            continue

        cmd, payload = None, {}
        try:
            if isinstance(item, tuple):
                if len(item) > 1:
                    cmd = item[0]
                if len(item) >= 2 and isinstance(item[1], dict):
                    payload = item[1] or {}
            elif isinstance(item, dict):
                cmd = item.get("cmd")
                payload = item.get("payload", {}) or {}
            else:
                # unknown shape; ignore
                continue
        except Exception:
            continue

        if not cmd:
            continue

        try:
            if cmd == "shutdown":
                try:
                    if getattr(bot, "is_running", False):
                        bot.stop()
                    if api:
                        api.disconnect()
                except Exception:
                    pass
                _snap_status(from_trading_thread=True)
                return

            if cmd == "connect":
                platform = payload.get("platform") or cfg.TRADING_PLATFORM
                symbol = payload.get("symbol") or getattr(cfg, "DEFAULT_SYMBOL", "ES")

                # Rebuild config+API+bot to requested platform inside THIS thread
                cfg = Config()
                cfg.TRADING_PLATFORM = platform
                api = APIFactory.create_api(cfg)
                bot = TradingBot(config=cfg)
                bot.symbol = symbol

                # re-apply last requested strategy (from UI) after bot recreation
                if _last_strategy_name:
                    try:
                        bot.set_strategy(_last_strategy_name, _last_strategy_params or {})
                        app.logger.info("Thread: reapplied strategy %s %s after connect", _last_strategy_name, _last_strategy_params)
                    except Exception as e:
                        app.logger.exception("Reapply strategy failed: %s", e)

                try:
                    bot.data_manager.api = api
                except Exception:
                    pass

                ok = True
                if api and not api.is_connected():
                    ok = api.connect()
                if ok:
                    # connected = True
                    _thread_connected.set()
                    try:
                        if hasattr(api, "ensure_symbol_loaded"):
                            api.ensure_symbol_loaded(symbol)
                            app.logger.info("connect: ensured symbol loaded: %s", symbol)
                    except Exception as e:
                        app.logger.debug("connect: ensure_symbol_loaded failed (non-fatal): %s", e)
                else:
                    # connected = False
                    _thread_connected.clear()
                _snap_status(from_trading_thread=True)
            
            elif cmd == "start":
                sym = payload.get("symbol") or getattr(bot, "symbol", getattr(cfg, "DEFAULT_SYMBOL", "ES"))
                name = (payload.get("strategy") or "").strip()
                params = payload.get("params") or {}

                # remember desired strategy in case a later 'connect' recreates the bot
                # global _last_strategy_name, _last_strategy_params
                _last_strategy_name, _last_strategy_params = name, params

                # ensure connected
                if not _thread_connected.is_set():
                    #connect first if needed 
                    _cmd_q.put(("connect", {"platform": cfg.TRADING_PLATFORM, "symbol": sym}))
                    # spin until connected or timeout
                    t0 = time.time()
                    while not _thread_connected.is_set() and time.time() - t0 < 60:
                        time.sleep(0.1)
                        # _snap_status(from_trading_thread=True)


                if name:
                    try:
                        bot.set_strategy(name, params)
                        app.logger.info("Thread: strategy set to %s with %s", name, params)
                    except Exception as e:
                        app.logger.exception("set_strategy in start failed: %s", e)

                # mark as running and publish snapshot so UI flips to green immediately
                bot.symbol = sym
                bot.is_running = True
                _snap_status(from_trading_thread=True)

                # Start bot loop (your TradingBot.start will block inside this thread)
                if not hasattr(bot, "_worker") or not getattr(bot._worker, "is_alive", lambda: False)():
                    bot._worker = threading.Thread(target=bot.start, args=(sym,), daemon=True)
                    bot._worker.start()


            elif cmd == "stop":
                if getattr(bot, "is_running", False):
                    bot.stop()
                try:
                    bot.is_running = False
                except Exception:
                    pass
                _snap_status(from_trading_thread=True)

            elif cmd == "pause":
                if getattr(bot, "is_running", False) and hasattr(bot, "pause"):
                    bot.pause()
                _snap_status(from_trading_thread=True)  

            elif cmd == "resume":
                if getattr(bot, "is_running", False) and hasattr(bot, "resume"):
                    bot.resume()
                _snap_status(from_trading_thread=True)

            elif cmd == "emergency":
                if hasattr(bot, "emergency_stop"):
                    bot.emergency_stop()
                _snap_status(from_trading_thread=True)

            elif cmd == "probe":
                # no Playwright calls in routes; all here
                ok = False
                details = {}
                try: 
                    if api is None:
                        details = {"error": "API not initialised"}
                    else:
                        details = api.probe_logged_in() # returns dict of booleans (see driver method below)
                        ok = any(details.values())
                except Exception as e:
                    details = {"error": str(e)}
                if 'reply' in payload and payload['reply']:
                    payload['reply'].put({"success": ok, "probe": details})

            elif cmd == "dryrun_market":
                symbol = payload.get("symbol")
                side = payload.get("side")
                qty = payload.get("qty")
                outcome = {"steps": {}, "dry_run": True, "symbol": symbol, "side": side, "qty": qty}
                ok = False
                err = None
                try:
                    if api is None:
                        err = "API not initialised"
                    else:
                        # make sure we are connected (thread is the only place calling PlayWright)
                        if not _thread_connected.is_set():
                            # queue a connect and wait briefly
                            _cmd_q.put(("connect", {"platform": cfg.TRADING_PLATFORM, "symbol": symbol}))
                            t0 = time.time()
                            while not _thread_connected.is_set() and time.time() - t0 < 60:
                                time.sleep(0.1)

                        # perform dry-run steps
                        outcome["steps"]["ensure_symbol"] = bool(api.ensure_symbol_loaded(symbol))
                        outcome["steps"]["set_quantity"] = bool(api.set_quantity(qty))
                        # Click the market button but DO NOT submit any confirmation
                        clicked = api.click_market_button(side)
                        outcome["steps"]["click_market_button"] = bool(clicked)

                        ok = all(outcome["steps"].values())
                except Exception as e:
                    err = str(e)
                if err:
                    outcome["error"] = err
                if 'reply' in payload and payload['reply']:
                    payload['reply'].put({"success": ok, **outcome})

            elif cmd == "set_strategy":
                name = (payload.get("strategy") or "").strip()
                params = payload.get("params") or {}
                ok, err = False, None
                try:
                    if hasattr(bot, "set_strategy"):
                        bot.set_strategy(name, params)
                        ok = True
                    else:
                        err = "Bot does not support set_strategy"
                except Exception as e:
                    err = str(e)
                _snap_status(from_trading_thread=True)
                if payload.get("reply"):
                    payload["reply"].put({"success": ok, "message": "Strategy set" if ok else err})


        except Exception as e:
            _thread_error = str(e)
            app.logger.exception("Trading thread command error: %s", e)

def _ensure_trading_thread():
    global _trading_thread
    if _trading_thread and _trading_thread.is_alive():
        return
    _thread_ready.clear()
    _trading_thread = threading.Thread(target=_trading_main, daemon=True)
    _trading_thread.start()
    _thread_ready.wait(timeout=5) # thread booted


def _persist_state():
    """Best-effort dump of trades & positions for post-mortem or restart continuity."""
    try:
        rm = getattr(getattr(bot, "risk_manager", None), "__dict__", None)
        if not rm:
            return
        out_dir = API_DIR
        # Trade history
        try:
            trades = list(getattr(bot.risk_manager, "trade_history", []))
            with open(os.path.join(out_dir, "trade_history.json"), "w") as f:
                json.dump(trades, f, indent=2, default=str)
        except Exception as e:
            app.logger.debug("persist trade_history failed: %s", e)
        # Positions snapshot
        try:
            pos = getattr(bot.risk_manager, "positions", {})
            with open(os.path.join(out_dir, "positions_snapshot.json"), "w") as f:
                json.dumps(pos, f, indent=2, default=str)
        except Exception as e:
            app.logger.debug("persist positions failed: %s", e)
    except Exception as e:
            app.logger.debug("persist_state outer failed: %s", e)       

# Start trading thread early so heartbeat keeps status fresh
# @app.before_first_request()
# def _kick_bg_thread_once():
#     try:
#         _ensure_trading_thread()
#         app.logger.info("Background trading thread ensured (on first request.)")
#     except Exception:
#         app.logger.exception("Failed to start background trading thread on startup")

@app.route('/api/status')
def get_status():
    # Refresh in memory snapshot before reading it.
    _snap_status()

    with _status_lock:
        """Return current bot status for the dashboard."""
        s = dict(_status)

        try:
            app.logger.info("STATUS OUT: sym=%s price=%s running=%s",
                            s.get("symbol"), s.get("current_price"), s.get("is_running"))
        except Exception:
            pass

        # return jsonify(dict(_status))
        return jsonify({"success": True, "status": s})

@app.route('/api/start', methods=['POST'])
def start_bot():
    """Start the trading bot."""
    # global cfg, api, bot, bot_thread
    data = _get_json()
    platform = data.get("platform") or cfg.TRADING_PLATFORM
    symbol = data.get("symbol") or getattr(cfg, "DEFAULT_SYMBOL", "ES")
    strategy = data.get("strategy") or "OpeningRange" # Default
    params = data.get("params") or {}

    # Te3mporary check ---
    app.logger.info("UI start: strategy=%s params%s platform=%s symbol=%s", strategy, params, platform, symbol)
    #####

    _ensure_trading_thread()

    if not _thread_connected.is_set():
        _cmd_q.put(("connect", {"platform": platform, "symbol": symbol}))

    # queue connect (if not already connected) then start
    # _cmd_q.put(("connect", {"platform": platform, "symbol": symbol}))
    # _cmd_q.put(("set_strategy", {"strategy": strategy, "params": params}))
    _cmd_q.put(("start", {
        "symbol": symbol, 
        "strategy": strategy,
        "params":params
    }))

    return jsonify({'success': True, 'message': f'Bot starting on {platform} / {symbol} with {strategy}...'})
    # --- robust body parsing ---
    

@app.route('/api/stop', methods=['POST'])
def stop_bot():
    """Stop the trading bot."""
    # global bot
    _ensure_trading_thread()
    _cmd_q.put(("stop", {}))
    return jsonify({'success': True, 'message': 'Stop requested'})
    


@app.route('/api/pause', methods=['POST'])
def pause_bot():
    """Pause the trading bot."""
    # global bot
    _ensure_trading_thread()
    _cmd_q.put(("pause", {}))
    return jsonify({'success': True, 'message': 'Pause requested'})
    


@app.route('/api/resume', methods=['POST'])
def resume_bot():
    """Resume the trading bot."""
    # global bot
    _ensure_trading_thread()
    _cmd_q.put(("resume", {}))
    return jsonify({'success': True, 'message': 'Resume requested'})
    
   

@app.route('/api/emergency_stop', methods=['POST'])
def emergency_stop():
    """Emergency stop the trading bot."""
    # global bot
    _ensure_trading_thread()
    _cmd_q.put(("emergency", {}))
    return jsonify({'success': True, 'message': 'Emergency stop requested'})
    
    

@app.route('/api/positions')
def get_positions():
    """Get current positions."""
    global bot
    
    try:
        if bot and hasattr(bot, "risk_manager"):
            rm = bot.risk_manager
            # --- ADAPTER: turn rm.positions -> UI schema ---
            ui_positions = {}
            pos_map = getattr(rm, "positions", {}) # {symbol: {qty, avg_price, unralized, ...}}
            for sym, p in pos_map.items():
                qty = int(p.get("qty", 0))
                if qty == 0:
                    continue
                side = "long" if qty > 0 else "short"
                ui_positions[sym] = {
                    "side": side,
                    "quantity": abs(qty),
                    "entry_price": float(p.get("avg_price", 0.0)),
                    "entry_time": (p.get("opened_at") or datetime.utcnow().isoformat(timespec="seconds"))
                }
            # positions = bot.risk_manager.get_positions()
            return jsonify({'success': True, 'positions': ui_positions})
        else:
            return jsonify({'success': True, 'positions': []})
    except Exception as e:
        return jsonify({'success': False, 'message': f'Error getting positions: {str(e)}'})

@app.route('/api/trades')
def get_trades():
    """Get trade history."""
    global bot
    
    try:
        if bot:
            trades = bot.get_trade_history()
            # >>> DEBUG: log count + one sample
            rm = getattr(bot, "risk_manager", None)
            app.logger.info("TRADES API: %d records | RM id=%s | instant_close=%r", len(trades), id(rm), getattr(rm, "instant_close", None))
            try:
                app.logger.info("RM id (flask thread) = %s len=%d",
                id(getattr(bot, "risk_manager", None)),
                len(getattr(getattr(bot, "risk_manager", None), "trade_history", [])))
                if trades:
                    app.logger.info("TRADES API SAMPLE: %s", str(trades[-1])[:300])
            except Exception:
                pass
            return jsonify({'success': True, 'trades': trades})
        else:
            app.logger.info("TRADES API: bot missing -> 0 records")
            return jsonify({'success': True, 'trades': []})
    except Exception as e:
        return jsonify({'success': False, 'message': f'Error getting trades: {str(e)}'})

@app.route('/api/market_analysis')
def get_market_analysis():
    try:
        """Get market analysis."""
        global bot, cfg, _status
        
        analysis = dict(getattr(bot, "_latest_analysis", {}) or {}) # if 'bot' in globals() else None
        # if snap:
        #     analysis = dict(snap)
        # else:
        #     # resolve API: bot.data_manager.api -> bot.api -> None
        #     api = None
        #     if 'bot' in globals() and bot:
        #         dm = getattr(bot, "data_manager", None)
        #         api = getattr(dm, "api", None) if dm else getattr(bot, "api", None)

            # Choose a symbol (UI/status first, then config, then ES)
            # sym = None
            # if bot is not None and getattr(bot, "_latest_analysis", None):
            #     analysis = dict(bot._latest_analysis)
            # else:
            #     api = getattr(dm, "api", None)
        sym = None
        if isinstance(_status, dict):
            sym = _status.get("symbol") or _status.get("sym")
        if not sym:
            sym = getattr(cfg, "DEFAULT_SYMBOL", "ES")
            
            # analysis = getattr(bot, "_latest_analysis", {}) or {}
            # return jsonify({'success': True, 'analysis': bot._latest_analysis})
        has_price = analysis.get("current_price") is not None
        if not has_price:
            api_local = None
            # Fallback: show a price even before the loop updates
            # price = None
            # analysis = {}
            # if api and hasattr(api, "get_current_price"):
            #     try:
                    # sym = getattr(bot, "symbol", getattr(cfg,"DEFAULT_SYMBOL", "ES"))
            dm = getattr(bot, "data_manager", None)
            if dm:
                api_local = getattr(dm, "api", None)
            if not api_local:
                api_local = getattr(bot, "api", None)

            if api_local and hasattr(api_local, "get_current_price"):
                try:
                    p = api_local.get_current_price(sym)
                    if p is not None:
                        analysis["current_price"] = float(p)
                    # a = getattr(dm, "api", None)
                    # price = api.get_current_price(sym) # if a else None
                except Exception:
                    # price = None
                    pass

        # Ensure required keys exist so the UI never breaks
        analysis.setdefault("range_position", "unknown")
        analysis.setdefault("opening_range", None)
        analysis.setdefault("yesterday_day_range", None)

                # if api:
                #     sym = getattr(bot, "symbol", getattr(cfg, "DEFAULT_SYMBOL", "ES"))
                #     price = api.get_current_price(sym)
            # analysis = {
            #     "current_price": float(price) if price is not None else None,
            #     "range_position": "unknown",
            #     "opening_range": None,
            #     "yesterday_day_range": None,
            # }
        # except Exception:
        #     analysis = { "current_price": None, "range_position": "unknown"}
            # pass
        # else:
        return jsonify({'success': True, 'analysis': analysis })
            # {
            #     "current_price": float(price) if price is not None else None,
            #     "range_position": "unknown",
            #     "opening_range": None,
            #     "yesterday_day_range": None,
            # }})
            
    except Exception as e:
        app.logger.exception("get_market_analysis failed: %s", e)
        return jsonify({'success': False, 'message': f'Error getting market analysis: {str(e)}'})

@app.route('/api/config')
def get_config():
    """Get current configuration."""
    return jsonify({
        'platforms': ['binance', 'tradovate', 'ninjatrader', 'tradovate_ui'],
        'current_platform': cfg.TRADING_PLATFORM,
        'default_symbol': getattr(cfg, "DEFAULT_SYMBOL", "ES"),
        'opening_range_minutes': getattr(cfg, "OPENING_RANGE_MINUTES", 30),
        'breakout_threshold': getattr(cfg, "BREAKOUT_THRESHOLD", 0.1),
        'max_position_size': getattr(cfg, "MAX_POSITION_SIZE", 1),
        'stop_loss_percentage': getattr(cfg, "STOP_LOSS_PERCENTAGE", 2.0),
        'take_profit_percentage': getattr(cfg, "TAKE_PROFIT_PERCENTAGE", 4.0),
        'max_daily_trades': getattr(cfg, "MAX_DAILY_TRADES", 10)
    })

@app.route('/api/test_connection', methods=['POST'])
def test_connection():
    """Test connection to trading platform."""
    # global cfg, api
    data = _get_json()
    platform = data.get("platform") or cfg.TRADING_PLATFORM
    symbol = data.get("symbol") or getattr(cfg, "DEFAULT_SYMBOL", "ES")

    _ensure_trading_thread()
    _thread_connected.clear()
    _cmd_q.put(("connect", {"platform": platform, "symbol": symbol}))

    # wait up to ~90s for manual login
    t0 = time.time()
    while time.time() - t0 < 90 and not _thread_connected.is_set():
        if _thread_error:
            return jsonify({'success': False, 'message': _thread_error}), 500
        time.sleep(0.2)

    ok = _thread_connected.is_set()
    return jsonify({
        "success": bool(ok),
        "message": ("Connected to "  + platform) if ok else ("Failed to connect to " + platform)
    })


@app.route("/api/shutdown", methods=["POST"])
def shutdown():
    # >>> ADD: save state before we ask the trading thread to quit
    try:
        _persist_state()
    except Exception:
        pass
    if _trading_thread and _trading_thread.is_alive():
        _cmd_q.put(("shutdown", {}))
    return jsonify({"success": True})

@app.route("/api/ui/probe", methods=["POST"])
def ui_probe():
    """Check presence of critical UI controls after login (buy/sell, qty, tabs, balance)."""
    data = _get_json()
    # optional symbol (not required just to probe)
    res = _rpc("probe", {"symbol": data.get("symbol")})
    return jsonify(res), (200 if res.get("success") else 500)


@app.route("/api/ui/dryrun/market", methods=["POST"])
def ui_dryrun_market():
    """
    Dry-run a market order:
        - Ensure symbol area is loaded
        - Fill quantity
        - Click Buy Mkt or Sell Mkt
        - STOP before any confirmation submit (no real order)
    Always returns JSON with step-by-step booleans.
    """
    data = _get_json()
    symbol = data.get("symbol") or getattr(cfg, "DEFAULT_SYMBOL", "ES")
    side = (data.get("side") or "BUY").upper()
    qty = int(data.get("qty") or 1)
    res = _rpc("dryrun_market", {"symbol": symbol, "side": side, "qty": qty})
    return jsonify(res), (200 if res.get("success") else 500)


def _log_routes():
    print("\nRegistered routes:")
    for r in app.url_map.iter_rules():
        print(f" {r.rule:30s} -> {','.join(sorted(r.methods))}")
    print()

import atexit
atexit.register(lambda: _persist_state())

if __name__ == '__main__':
    _log_routes()
    print("🌐 Starting Futures Trading Bot Web Dashboard...")
    print("📊 Dashboard will be available at: http://localhost:5050")
    print("🔧 Use Ctrl+C to stop the web server")
    
    app.run(host='0.0.0.0', port=5050, debug=True)


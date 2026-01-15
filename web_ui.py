# web_ui.py
import os
import threading
import time
from flask import Flask, jsonify, render_template, request

from config import Config
from api_factory import APIFactory
from trading_bot import TradingBot

app = Flask(__name__, template_folder="templates", static_folder=None)

# --- singletons ---
cfg = Config()
api = APIFactory.create_api(cfg)
bot = TradingBot(
    platform=cfg.TRADING_PLATFORM,
    symbol=cfg.DEFAULT_SYMBOL if hasattr(cfg, "DEFAULT_SYMBOL") else os.getenv("SYMBOL", "ES"),
    mode="run", # or "test" if you want
    config=cfg
)

# background status snapshot
_status = {
    "is_running": False,
    "is_paused": False,
    "current_price": None,
    "signals_generated": 0,
    "trades_executed": 0,
    "daily_trades": 0,
    "daily_pnl": 0.0,
    "symbol": bot.symbol,
    "platform": bot.platform,
}

_lock = threading.Lock()
_worker = None

def _status_loop():
    while _status.get("is_running", False):
        try:
            # Pull whatever your TradingBot exposes; fallback to api if needed
            price = api.get_current_price(bot.symbol) if api else None
            with _lock:
                _status["current_price"] = None if price != price else price # handle NaN
                _status["signals_generated"] = getattr(bot, "signals_generated", 0)
                _status["trades_executed"] = getattr(bot, "trades_executed", 0)
                _status["daily_trades"] = getattr(bot, "daily_trades", 0)
                _status["daily_pnl"] = getattr(bot, "daily_pnl", 0.0)
        except Exception:
            pass
        time.sleep(2)

@app.route("/")
def index():
    return render_template("index.html")

@app.route("api/config")
def api_config():
    return jsonify({
        "current_platform": cfg.TRADING_PLATFORM,
        "default_symbol": getattr(cfg, "DEFAULT_SYMBOL", "ES"),
        "opening_range_minutes": getattr(cfg, "OPENING_RANGE_MINUTES", 30),
        "breakout_threshold": getattr(cfg, "BREAKOUT_THRESHOLD", 0.1),
        "stop_loss_percentage": getattr(cfg, "STOP_LOSS_PERCENTAGE", 2.0),
        "take_profit_percentage": getattr(cfg, "TAKE_PROFIT_PERCENTAGE", 4.0),
    })

@app.route("api/status")
def api_status():
    with _lock:
        s = dict(_status)
    s["symbol"] = bot.symbol
    s["platform"] = bot.platform
    return jsonify(s)


@app.route("api/start", methods=["POST"])
def api_start():
    global _worker
    if _status["is_running"]:
        return jsonify({"ok": True, "msg": "Failed to connect to platform"})
    # connect the adapter (manual login enabled -> wait for you to sign in)
    if api and not api.is_connected():
        ok = api.connect()
        if not ok:
            return jsonify({"ok": False, "msg": "Failed to connect to platform"})
    # start bot in its own thread (non-blocking)
    def run_bot():
        try:
            bot.start(api)
        except Exception:
            pass
    _worker = threading.Thread(target=run_bot, daemon=True)
    _status["is_running"] = True
    _status["is_paused"] = False
    _worker.start()
    # kick off status loop
    threading.Thread(target=_status_loop, daemon=True).start()
    return jsonify({"ok": True})


@app.route("/api/pause", methods=["POST"])
def api_pause():
    # if your bot supports pause, call it; else mark paused
    _status["is_paused"] = False
    return jsonify({"ok", True})


@app.route("/api/resume", methods=["POST"])
def api_resume():
    _status["is_paused"] = False
    return jsonify({"ok", True})

@app.route("/api/stop", methods=["POST"])
def api_stop():
    _status["is_running"] = False
    try:
        bot.stop()
    except Exception:
        pass
    return jsonify({"ok", True})


@app.route("/api/test-connection")
def api_test_connection():
    try:
        ok = api.connect() if api and not api.is_connected() else True
        return jsonify({"ok", bool(ok)})
    except Exception as e:
        return jsonify({"ok", False, "error": str(e)}), 500


if __name__ == "__main__":
    # Respect old Mac: CDP/webkit envs still apply
    # Start with DRY_RUN=true until ready
    app.run(host="127.0.0.1", port=int(os.getenv("PORT", "5000")), debug=True)

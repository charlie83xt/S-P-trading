"""Send clean, signed events to the Bot-Log_Front dashboard.

Fire-and-forget: events go on a queue and a background thread posts them, so a slow or failed
upload can never delay an order or an exit. Does nothing unless both settings are present (.env):
    FEED_URL=https://<your-dashboard>/api/events
    FEED_SECRET=<long random string, the same value as on the dashboard server>

Only short codes and numbers are sent - never account numbers, balances, dollar P&L, URLs or
raw log lines. Every event is signed with HMAC-SHA256 so the dashboard can reject forgeries.
"""
import hashlib
import hmac
import json
import logging
import math
import os
import queue
import re
import threading
import time
import uuid
from datetime import datetime, timezone

import requests

log = logging.getLogger(__name__)

_queue: "queue.Queue[dict]" = queue.Queue(maxsize=500)
_worker = None
_worker_lock = threading.Lock()
_SAFE = re.compile(r"[^A-Za-z0-9_.\-]")
_last_error_log = 0.0


def account_type() -> str:
    """'simulation' for Tradovate DEMO accounts, 'live' otherwise - never the account number."""
    acct = os.getenv("EXPECTED_ACCOUNT", "").strip().upper()
    if not acct:
        return "unknown"
    return "simulation" if acct.startswith("DEMO") else "live"


def _clean(value):
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return round(float(value), 2) if math.isfinite(float(value)) else None
    return _SAFE.sub("_", str(value).strip())[:60]


def code(text) -> str:
    """Turn a free-text reason into a short code, e.g. 'ranging_regime_block (conf=0.75)' -> 'ranging_regime_block'."""
    first = re.split(r"[\s(:]", str(text or "").strip(), maxsplit=1)[0]
    return _clean(first.lower()) or "unknown"


def publish(event_type: str, **fields) -> None:
    """Queue one event. Never raises."""
    try:
        url, secret = os.getenv("FEED_URL", "").strip(), os.getenv("FEED_SECRET", "").strip()
        if not url or not secret:
            return
        event = {
            "event_id": uuid.uuid4().hex,
            "type": _clean(event_type),
            "occurred_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "account_type": account_type(),
            **{k: _clean(v) for k, v in fields.items() if v is not None},
        }
        _queue.put_nowait(event)
        _ensure_worker()
    except queue.Full:
        pass
    except Exception as e:  # never let the feed affect trading
        log.debug("feed publish skipped: %s", e)


def _ensure_worker():
    global _worker
    with _worker_lock:
        if _worker is None or not _worker.is_alive():
            _worker = threading.Thread(target=_run, name="feed-publisher", daemon=True)
            _worker.start()


def _run():
    while True:
        event = _queue.get()
        try:
            _send(event)
        except Exception as e:
            _log_error(f"feed post failed: {e}")


def _send(event: dict):
    url, secret = os.getenv("FEED_URL", "").strip(), os.getenv("FEED_SECRET", "").strip()
    body = json.dumps(event, separators=(",", ":"), sort_keys=True)
    ts = str(int(time.time()))
    sig = hmac.new(secret.encode(), f"{ts}.{body}".encode(), hashlib.sha256).hexdigest()
    r = requests.post(url, data=body.encode(), timeout=10, headers={
        "Content-Type": "application/json", "X-Feed-Timestamp": ts, "X-Feed-Signature": sig})
    if r.status_code >= 300:
        _log_error(f"feed rejected event ({r.status_code}): {r.text[:200]}")


def _log_error(msg: str):
    global _last_error_log
    if time.time() - _last_error_log > 300:          # at most one warning every 5 minutes
        _last_error_log = time.time()
        log.warning(msg)

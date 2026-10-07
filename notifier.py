"""Fire-and-forget Telegram alerts. No-op unless TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID are set."""
import os
import logging
import threading

import requests

log = logging.getLogger(__name__)


def notify(text: str) -> None:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        return

    def _send():
        try:
            requests.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat_id, "text": f"S-P Bot: {text}"},
                timeout=10,
            )
        except Exception as e:
            log.warning("telegram notify failed: %s", e)

    # never block the trading thread on the network
    threading.Thread(target=_send, daemon=True).start()

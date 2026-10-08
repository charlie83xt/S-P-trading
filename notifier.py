"""Non-blocking Telegram notifications."""

import logging
import os
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
            response = requests.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={
                    "chat_id": chat_id,
                    "text": f"S-P Bot: {text}",
                },
                timeout=10,
            )

            if not response.ok:
                log.warning(
                    "Telegram notification rejected: HTTP %s",
                    response.status_code,
                )
                return

            result = response.json()

            if result.get("ok") is not True:
                log.warning(
                    "Telegram notification was not accepted"
                )

        except Exception as exc:
            # Exception text can include the URL containing the token.
            log.warning(
                "Telegram notification failed: %s",
                type(exc).__name__,
            )

    threading.Thread(
        target=_send,
        name="telegram-notification",
        daemon=True,
    ).start()

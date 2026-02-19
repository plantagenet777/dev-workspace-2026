"""Telegram alert delivery for monitoring team."""
import logging

import requests

from config.config import Config

logger = logging.getLogger("pump_engine")


def send_telegram_alert(message: str) -> None:
    """Send critical pump status notification to Telegram.

    If TG_TOKEN or TG_CHAT_ID are not set in config, sending is skipped.

    Args:
        message: Notification text (Markdown supported).
    """
    if not Config.TELEGRAM_TOKEN or not Config.TELEGRAM_CHAT_ID:
        logger.warning("Telegram Notifier: Token or Chat ID not configured. Skipping.")
        return

    url = f"https://api.telegram.org/bot{Config.TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": Config.TELEGRAM_CHAT_ID,
        "text": f"🚨 **PUMP PREDICTIVE MAINTENANCE ALERT** 🚨\n\n{message}",
        "parse_mode": "Markdown",
    }

    try:
        response = requests.post(url, json=payload, timeout=5)
        if response.status_code == 200:
            logger.info("Telegram alert sent successfully.")
        else:
            logger.error("Failed to send Telegram alert: %s", response.text)
    except Exception as e:
        logger.error("Telegram API Error: %s", e)

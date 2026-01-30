import logging
import requests
from config.config import Config

logger = logging.getLogger("icl_engine")


def send_telegram_alert(message):
    """Отправка критических уведомлений инженерам ICL в Telegram"""
    if not Config.TELEGRAM_TOKEN or not Config.TELEGRAM_CHAT_ID:
        logger.warning("Telegram Notifier: Token or Chat ID not configured. Skipping.")
        return

    url = f"https://api.telegram.org/bot{Config.TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": Config.TELEGRAM_CHAT_ID,
        "text": f"🚨 **ICL ROTEM ALERT** 🚨\n\n{message}",
        "parse_mode": "Markdown"
    }

    try:
        response = requests.post(url, json=payload, timeout=5)
        if response.status_code == 200:
            logger.info("Telegram alert sent successfully.")
        else:
            logger.error("Failed to send Telegram alert: %s", response.text)
    except Exception as e:
        logger.error("Telegram API Error: %s", e)
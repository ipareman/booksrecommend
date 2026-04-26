"""
Тонкая обёртка над Telegram Bot API.
Не использует aiogram/python-telegram-bot — только requests.
Бот только отправляет сообщения, входящие не обрабатывает.

Как получить chat_id пользователя:
  1. Пользователь указывает @username в профиле
  2. Пишет боту /start
  3. Бот сохраняет chat_id через webhook или polling (bot.py)
"""
import logging
import requests
from django.conf import settings

logger = logging.getLogger(__name__)

API = "https://api.telegram.org/bot{token}/{method}"


def _call(method: str, **params) -> dict | None:
    token = settings.TELEGRAM_BOT_TOKEN

    if not token:
        logger.warning("TELEGRAM_BOT_TOKEN не задан, уведомление пропущено")
        return None
    try:
        r = requests.post(
            API.format(token=token, method=method),
            json=params,
            timeout=10,
        )
        data = r.json()
        if not data.get("ok"):
            logger.error("Telegram API error: %s", data)
        return data
    except requests.RequestException as e:
        logger.error("Telegram request failed: %s", e)
        return None


def send_message(chat_id: str, text: str, parse_mode: str = "HTML") -> bool:
    """Отправить сообщение пользователю."""
    result = _call(
        "sendMessage",
        chat_id=chat_id,
        text=text,
        parse_mode=parse_mode,
        disable_web_page_preview=True,
    )
    return bool(result and result.get("ok"))


def get_updates(offset: int = 0) -> list:
    """Получить входящие обновления (для polling при настройке бота)."""
    result = _call("getUpdates", offset=offset, timeout=5)
    if result and result.get("ok"):
        return result.get("result", [])
    return []


def set_webhook(url: str) -> bool:
    result = _call("setWebhook", url=url)
    return bool(result and result.get("ok"))

"""
Тонкая обёртка над MAX Bot API (https://dev.max.ru/docs-api).
Не использует SDK — только requests. Параллельна notifications/telegram.py.

Авторизация — заголовок `Authorization: <token>` (query-параметр больше не
поддерживается). Rate-limit платформы — 30 rps.

Используется в проекте:
  • notify_book_added (books/tasks.py, notifications/tasks.py)
  • send_weekly_digest (users/tasks.py)
  • _notify_review_status (reviews/views.py)

Как получить user_id (аналог chat_id в TG):
  1. Пользователь указывает @username MAX в профиле.
  2. Пишет боту /start, проходит логин/пароль.
  3. max_bot.py сохраняет поле max_user_id в UserProfile.
"""
import logging
import requests
from django.conf import settings

logger = logging.getLogger(__name__)

API_BASE = "https://platform-api.max.ru"


def _request(method: str, path: str, *, params: dict | None = None,
             json_body: dict | None = None, timeout: int = 10) -> dict | None:
    token = getattr(settings, "MAX_BOT_TOKEN", "")
    if not token:
        logger.warning("MAX_BOT_TOKEN не задан, уведомление пропущено")
        return None
    url = f"{API_BASE}{path}"
    headers = {"Authorization": token}
    try:
        r = requests.request(
            method, url,
            params=params or {},
            json=json_body,
            headers=headers,
            timeout=timeout,
        )
        try:
            data = r.json()
        except ValueError:
            data = {"_raw": r.text}
        if r.status_code >= 400:
            logger.error("MAX API %s %s → %s: %s", method, path, r.status_code, data)
            return None
        return data
    except requests.RequestException as e:
        logger.error("MAX request failed: %s", e)
        return None


def send_message(user_id: str | int, text: str, fmt: str = "html",
                 notify: bool = True) -> bool:
    """Отправить сообщение пользователю. fmt: 'html' или 'markdown'."""
    if not user_id:
        return False
    payload = {
        "text": text,
        "format": fmt,
        "notify": notify,
    }
    result = _request(
        "POST", "/messages",
        params={"user_id": str(user_id)},
        json_body=payload,
    )
    return bool(result and result.get("message"))


def get_updates(marker: int | None = None, timeout: int = 30,
                types: list[str] | None = None) -> dict | None:
    """Long-polling: получить новые апдейты. Возвращает {updates, marker}."""
    params: dict = {"timeout": timeout}
    if marker is not None:
        params["marker"] = marker
    if types:
        params["types"] = ",".join(types)
    return _request("GET", "/updates", params=params, timeout=timeout + 5)


def set_webhook(url: str) -> bool:
    """Подписаться на webhook (альтернатива long-polling для production)."""
    result = _request("POST", "/subscriptions", json_body={"url": url})
    return bool(result)


def get_me() -> dict | None:
    """Проверка токена: информация о боте."""
    return _request("GET", "/me")

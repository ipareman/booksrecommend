"""
MAX-бот для Строки.

Запуск:
    python max_bot.py

Или отдельным сервисом в docker-compose (параллельно telegram_bot).

Команды:
    /start  — привязать MAX к аккаунту сайта (ввести логин + пароль)
    /stop   — отвязать аккаунт
    /me     — показать текущий аккаунт

Логика полностью параллельна telegram_bot.py. SDK для Python официально нет —
работаем голым long-polling'ом через notifications.max.
"""
import logging
import os
import time
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from django.conf import settings
from django.contrib.auth import authenticate

from notifications.max import get_updates, send_message

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ── FSM-стейт ────────────────────────────────────────────────────────────────
# Простая память в процессе. Для single-worker деплоя этого достаточно.
# Ключ — max_user_id (str), значение — {"state": str, "data": dict}.
STATES: dict[str, dict] = {}

ST_WAITING_USERNAME = "waiting_username"
ST_WAITING_PASSWORD = "waiting_password"


def _reply(user_id: str, text: str, fmt: str = "html") -> None:
    send_message(user_id, text, fmt=fmt)


# ── Хендлеры ────────────────────────────────────────────────────────────────


def handle_start(user_id: str, max_username: str) -> None:
    from users.models import UserProfile

    try:
        profile = UserProfile.objects.get(max_user_id=str(user_id))
        _reply(
            user_id,
            f"Вы уже привязаны к аккаунту <b>{profile.user.username}</b>.\n"
            f"Чтобы отвязать — /stop",
        )
        return
    except UserProfile.DoesNotExist:
        pass

    STATES[user_id] = {"state": ST_WAITING_USERNAME, "data": {"max_username": max_username}}
    _reply(
        user_id,
        "👋 Привет! Это бот <b>Строка</b>.\n\n"
        "Чтобы получать уведомления о новых книгах любимых авторов, "
        "привяжите ваш аккаунт.\n\n"
        "Введите ваш <b>логин</b> на сайте:",
    )


def handle_stop(user_id: str) -> None:
    from users.models import UserProfile

    updated = UserProfile.objects.filter(max_user_id=str(user_id)).update(
        max_user_id="", max_username=""
    )
    STATES.pop(user_id, None)
    if updated:
        _reply(user_id, "✅ Аккаунт отвязан. Уведомления отключены.")
    else:
        _reply(user_id, "Аккаунт и так не привязан. /start — чтобы привязать.")


def handle_me(user_id: str) -> None:
    from users.models import UserProfile, AuthorSubscription

    try:
        profile = UserProfile.objects.select_related("user").get(max_user_id=str(user_id))
    except UserProfile.DoesNotExist:
        _reply(user_id, "Аккаунт не привязан. /start — чтобы привязать.")
        return

    subs = AuthorSubscription.objects.filter(user=profile.user).select_related("author")
    sub_list = "\n".join(f"  • {s.author.name}" for s in subs) or "  (нет подписок)"
    _reply(
        user_id,
        f"👤 Аккаунт: <b>{profile.user.username}</b>\n\n"
        f"📖 Подписки на авторов:\n{sub_list}",
    )


def handle_text(user_id: str, text: str, max_username: str) -> None:
    """Сообщение вне команды: возможно, это шаг FSM."""
    from users.models import UserProfile

    st = STATES.get(user_id)
    if not st:
        _reply(
            user_id,
            "Доступные команды:\n"
            "/start — привязать аккаунт\n"
            "/stop — отвязать\n"
            "/me — показать текущий аккаунт",
        )
        return

    if st["state"] == ST_WAITING_USERNAME:
        st["data"]["username"] = text.strip()
        st["state"] = ST_WAITING_PASSWORD
        _reply(user_id, "Теперь введите ваш <b>пароль</b>:")
        return

    if st["state"] == ST_WAITING_PASSWORD:
        username = st["data"].get("username", "")
        password = text.strip()
        # Очищаем стейт сразу — не хотим зацикливаться.
        STATES.pop(user_id, None)

        user = authenticate(username=username, password=password)
        if user is None:
            _reply(user_id, "❌ Неверный логин или пароль. Попробуйте ещё раз — /start")
            return

        profile, _ = UserProfile.objects.get_or_create(user=user)
        profile.max_user_id = str(user_id)
        profile.max_username = max_username or ""
        profile.save(update_fields=["max_user_id", "max_username"])
        _reply(
            user_id,
            f"✅ Аккаунт <b>{user.username}</b> привязан!\n\n"
            f"Теперь вы будете получать уведомления о новых книгах авторов, "
            f"на которых подписаны.",
        )
        return

    # Незнакомое состояние — сбросить.
    STATES.pop(user_id, None)


# ── Диспетчер апдейтов ──────────────────────────────────────────────────────


def dispatch(update: dict) -> None:
    """
    Форматы апдейтов по документации dev.max.ru:

    • message_created:
        {
          "update_type": "message_created",
          "message": {
            "sender":    {"user_id": 42, "username": "ivan", "name": "Иван"},
            "recipient": {"chat_type": "dialog", "user_id": 42},
            "body":      {"mid": "...", "seq": 1, "text": "/start"},
            ...
          }
        }

    • bot_started (deep-link): не используем в v1 — логика такая же, как /start.
    """
    t = update.get("update_type")
    if t not in ("message_created", "bot_started"):
        return

    msg = update.get("message") or {}
    sender = msg.get("sender") or {}
    user_id = sender.get("user_id")
    if not user_id:
        # bot_started шлёт user на верхнем уровне
        user = update.get("user") or {}
        user_id = user.get("user_id")
        max_username = user.get("username") or ""
    else:
        max_username = sender.get("username") or ""

    if not user_id:
        return
    user_id = str(user_id)

    body = msg.get("body") or {}
    text = (body.get("text") or "").strip()

    # bot_started трактуем как /start (с опциональным payload)
    if t == "bot_started":
        handle_start(user_id, max_username)
        return

    # Игнорируем нетекстовые сообщения.
    if not text:
        return

    # Команды
    cmd = text.split()[0].lower()
    if cmd in ("/start",):
        handle_start(user_id, max_username)
    elif cmd in ("/stop",):
        handle_stop(user_id)
    elif cmd in ("/me",):
        handle_me(user_id)
    else:
        handle_text(user_id, text, max_username)


# ── main: long-polling ─────────────────────────────────────────────────────


def main() -> None:
    if not getattr(settings, "MAX_BOT_TOKEN", ""):
        logger.error("MAX_BOT_TOKEN не задан. Укажите в .env и перезапустите.")
        return

    logger.info("MAX-бот запущен")
    marker: int | None = None
    while True:
        try:
            resp = get_updates(marker=marker, timeout=30)
        except Exception as exc:
            logger.error("get_updates failed: %s", exc)
            time.sleep(3)
            continue

        if not resp:
            time.sleep(2)
            continue

        for upd in resp.get("updates", []) or []:
            try:
                dispatch(upd)
            except Exception as exc:
                logger.exception("dispatch failed for update: %s", exc)

        new_marker = resp.get("marker")
        if new_marker is not None:
            marker = new_marker


if __name__ == "__main__":
    main()

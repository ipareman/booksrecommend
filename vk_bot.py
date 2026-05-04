import logging
import os
import time

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from django.conf import settings
from django.contrib.auth import authenticate

from notifications.vk import get_updates, get_user, groups_get_long_poll_server, send_message

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

STATES: dict[str, dict] = {}

ST_WAITING_USERNAME = "waiting_username"
ST_WAITING_PASSWORD = "waiting_password"


def _reply(user_id: str, text: str) -> None:
    send_message(user_id, text)


def handle_start(user_id: str, vk_username: str) -> None:
    from users.models import UserProfile

    try:
        profile = UserProfile.objects.get(vk_user_id=str(user_id))
        _reply(
            user_id,
            f"Вы уже привязаны к аккаунту {profile.user.username}.\n"
            f"Чтобы отвязать — /stop",
        )
        return
    except UserProfile.DoesNotExist:
        pass

    STATES[user_id] = {"state": ST_WAITING_USERNAME, "data": {"vk_username": vk_username}}
    _reply(
        user_id,
        "👋 Привет! Это бот Строка.\n\n"
        "Чтобы получать уведомления о новых книгах любимых авторов, "
        "привяжите ваш аккаунт.\n\n"
        "Введите ваш логин на сайте:",
    )


def handle_stop(user_id: str) -> None:
    from users.models import UserProfile

    updated = UserProfile.objects.filter(vk_user_id=str(user_id)).update(
        vk_user_id="", vk_username=""
    )
    STATES.pop(user_id, None)
    if updated:
        _reply(user_id, "✅ Аккаунт отвязан. Уведомления отключены.")
    else:
        _reply(user_id, "Аккаунт и так не привязан. /start — чтобы привязать.")


def handle_me(user_id: str) -> None:
    from users.models import AuthorSubscription, UserProfile

    try:
        profile = UserProfile.objects.select_related("user").get(vk_user_id=str(user_id))
    except UserProfile.DoesNotExist:
        _reply(user_id, "Аккаунт не привязан. /start — чтобы привязать.")
        return

    subs = AuthorSubscription.objects.filter(user=profile.user).select_related("author")
    sub_list = "\n".join(f"  • {s.author.name}" for s in subs) or "  (нет подписок)"
    _reply(
        user_id,
        f"👤 Аккаунт: {profile.user.username}\n\n"
        f"📖 Подписки на авторов:\n{sub_list}",
    )


def handle_text(user_id: str, text: str, vk_username: str) -> None:
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
        _reply(user_id, "Теперь введите ваш пароль:")
        return

    if st["state"] == ST_WAITING_PASSWORD:
        username = st["data"].get("username", "")
        password = text.strip()
        STATES.pop(user_id, None)

        user = authenticate(username=username, password=password)
        if user is None:
            _reply(user_id, "❌ Неверный логин или пароль. Попробуйте ещё раз — /start")
            return

        profile, _ = UserProfile.objects.get_or_create(user=user)
        profile.vk_user_id = str(user_id)
        profile.vk_username = vk_username or st["data"].get("vk_username", "")
        profile.save(update_fields=["vk_user_id", "vk_username"])
        _reply(
            user_id,
            f"✅ Аккаунт {user.username} привязан!\n\n"
            f"Теперь вы будете получать уведомления о новых книгах авторов, "
            f"на которых подписаны.",
        )
        return

    STATES.pop(user_id, None)


def dispatch(update: dict) -> None:
    if update.get("type") != "message_new":
        return

    obj = update.get("object") or {}
    message = obj.get("message") or obj
    user_id = message.get("from_id")
    text = (message.get("text") or "").strip()
    if not user_id or not text:
        return

    user_id = str(user_id)
    vk_user = get_user(user_id) or {}
    vk_username = vk_user.get("screen_name") or f"id{user_id}"
    cmd = text.split()[0].lower()

    if cmd in ("/start", "начать"):
        handle_start(user_id, vk_username)
    elif cmd == "/stop":
        handle_stop(user_id)
    elif cmd == "/me":
        handle_me(user_id)
    else:
        handle_text(user_id, text, vk_username)


def _connect_long_poll() -> tuple[str, str, str] | None:
    data = groups_get_long_poll_server()
    if not data:
        return None
    return data.get("server"), data.get("key"), data.get("ts")


def main() -> None:
    if not getattr(settings, "VK_BOT_TOKEN", ""):
        logger.error("VK_BOT_TOKEN не задан. Укажите в .env и перезапустите.")
        return
    if not getattr(settings, "VK_GROUP_ID", ""):
        logger.error("VK_GROUP_ID не задан. Укажите в .env и перезапустите.")
        return

    logger.info("VK-бот запущен")
    connection = _connect_long_poll()
    while True:
        if not connection:
            time.sleep(5)
            connection = _connect_long_poll()
            continue

        server, key, ts = connection
        data = get_updates(server, key, ts)
        if not data:
            time.sleep(2)
            continue

        if data.get("failed"):
            logger.warning("VK Long Poll failed=%s, reconnecting", data.get("failed"))
            connection = _connect_long_poll()
            continue

        ts = data.get("ts", ts)
        connection = (server, key, ts)
        for upd in data.get("updates", []) or []:
            try:
                dispatch(upd)
            except Exception as exc:
                logger.exception("dispatch failed for update: %s", exc)


if __name__ == "__main__":
    main()

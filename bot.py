#!/usr/bin/env python
"""
Минимальный Telegram-бот для привязки chat_id к аккаунту Строкаа.

Работает в режиме polling — не требует публичного URL/webhook.
Запуск: python bot.py

Пользователь пишет /start — бот сохраняет его chat_id в UserProfile
по совпадению telegram_username.

Установка на сервер (systemd):
  [Unit]
  Description=Bookopolis Telegram Bot
  After=network.target

  [Service]
  WorkingDirectory=/path/to/bookopolis
  ExecStart=/path/to/venv/bin/python bot.py
  Restart=always
  RestartSec=5

  [Install]
  WantedBy=multi-user.target
"""
import os
import sys
import time
import logging
import requests
import django

# ── Инициализация Django ──────────────────────────────────────────────────────
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
sys.path.insert(0, os.path.dirname(__file__))
django.setup()

from django.conf import settings
from users.models import UserProfile

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [BOT] %(message)s",
)
logger = logging.getLogger(__name__)

TOKEN  = settings.TELEGRAM_BOT_TOKEN
API    = f"https://api.telegram.org/bot{TOKEN}"
OFFSET = 0


def get_updates(offset: int) -> list:
    try:
        r = requests.get(f"{API}/getUpdates", params={"offset": offset, "timeout": 30}, timeout=35)
        data = r.json()
        return data.get("result", []) if data.get("ok") else []
    except Exception as e:
        logger.error("getUpdates failed: %s", e)
        time.sleep(5)
        return []


def send(chat_id: int, text: str):
    try:
        requests.post(f"{API}/sendMessage",
                      json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
                      timeout=10)
    except Exception as e:
        logger.error("sendMessage failed: %s", e)


def handle(update: dict):
    msg = update.get("message", {})
    if not msg:
        return

    chat_id  = msg["chat"]["id"]
    username = (msg.get("from") or {}).get("username", "").lower()
    text     = (msg.get("text") or "").strip()

    if text.startswith("/start"):
        if not username:
            send(chat_id,
                 "❌ У вас не задан username в Telegram. "
                 "Установите его в настройках Telegram, затем попробуйте снова.")
            return

        # Ищем профиль по telegram_username
        try:
            profile = UserProfile.objects.get(telegram_username__iexact=username)
        except UserProfile.DoesNotExist:
            send(chat_id,
                 f"❌ Аккаунт с Telegram @{username} не найден в Строкае.\n"
                 "Сначала укажите ваш Telegram-логин в профиле на сайте.")
            return

        profile.telegram_chat_id = str(chat_id)
        profile.save(update_fields=["telegram_chat_id"])

        send(chat_id,
             f"✅ <b>Готово!</b> Аккаунт @{username} привязан к Строке.\n\n"
             "Теперь вы будете получать уведомления о новых книгах авторов, "
             "на которых подписаны.")
        logger.info("Linked @%s → chat_id %s", username, chat_id)

    elif text.startswith("/stop"):
        try:
            profile = UserProfile.objects.get(telegram_chat_id=str(chat_id))
            profile.telegram_chat_id = ""
            profile.save(update_fields=["telegram_chat_id"])
            send(chat_id, "🔕 Уведомления отключены.")
        except UserProfile.DoesNotExist:
            send(chat_id, "Вы не были подписаны.")

    elif text.startswith("/status"):
        try:
            profile = UserProfile.objects.get(telegram_chat_id=str(chat_id))
            subs = profile.user.author_subscriptions.count()
            send(chat_id,
                 f"👤 Аккаунт: <b>{profile.user.username}</b>\n"
                 f"📚 Подписок на авторов: {subs}")
        except UserProfile.DoesNotExist:
            send(chat_id, "Аккаунт не привязан. Отправьте /start.")

    else:
        send(chat_id,
             "/start — привязать аккаунт\n"
             "/stop — отключить уведомления\n"
             "/status — информация об аккаунте")


def main():
    global OFFSET
    logger.warning(f'my-token: {TOKEN}')
    if not TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN не задан в .env")
        sys.exit(1)

    logger.info("Бот запущен")
    while True:
        updates = get_updates(OFFSET)
        for upd in updates:
            try:
                handle(upd)
            except Exception as e:
                logger.error("handle error: %s", e)
            OFFSET = upd["update_id"] + 1


if __name__ == "__main__":
    main()

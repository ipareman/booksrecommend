"""
Telegram-бот для Строкаа.

Запуск (на сервере, вне Docker):
    python telegram_bot.py

Или добавить в docker-compose как отдельный сервис.

Команды:
    /start  — привязать Telegram к аккаунту сайта (ввести логин + пароль)
    /stop   — отвязать аккаунт
    /me     — показать текущий аккаунт
"""
import asyncio
import logging
import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from django.conf import settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bot = Bot(token=settings.TELEGRAM_BOT_TOKEN)
dp  = Dispatcher(storage=MemoryStorage())


class LinkStates(StatesGroup):
    waiting_username = State()
    waiting_password = State()


# ── /start ────────────────────────────────────────────────────────────────────

@dp.message(CommandStart())
async def cmd_start(message: types.Message, state: FSMContext):
    from users.models import UserProfile

    # Проверить — может уже привязан
    try:
        profile = UserProfile.objects.get(telegram_chat_id=str(message.chat.id))
        await message.answer(
            f"Вы уже привязаны к аккаунту <b>{profile.user.username}</b>.\n"
            f"Чтобы отвязать — /stop",
            parse_mode="HTML"
        )
        return
    except UserProfile.DoesNotExist:
        pass

    await message.answer(
        "👋 Привет! Это бот <b>Строкаа</b>.\n\n"
        "Чтобы получать уведомления о новых книгах любимых авторов, "
        "привяжите ваш аккаунт.\n\n"
        "Введите ваш <b>логин</b> на сайте:",
        parse_mode="HTML"
    )
    await state.set_state(LinkStates.waiting_username)


@dp.message(LinkStates.waiting_username)
async def got_username(message: types.Message, state: FSMContext):
    await state.update_data(username=message.text.strip())
    await message.answer("Теперь введите ваш <b>пароль</b>:", parse_mode="HTML")
    await state.set_state(LinkStates.waiting_password)


@dp.message(LinkStates.waiting_password)
async def got_password(message: types.Message, state: FSMContext):
    from django.contrib.auth import authenticate
    from users.models import UserProfile

    data     = await state.get_data()
    username = data.get("username", "")
    password = message.text.strip()

    # Удаляем сообщение с паролем сразу
    try:
        await message.delete()
    except Exception:
        pass

    user = authenticate(username=username, password=password)
    if user is None:
        await message.answer(
            "❌ Неверный логин или пароль. Попробуйте ещё раз — /start"
        )
        await state.clear()
        return

    profile, _ = UserProfile.objects.get_or_create(user=user)
    profile.telegram_chat_id  = str(message.chat.id)
    profile.telegram_username = message.from_user.username or ""
    profile.save(update_fields=["telegram_chat_id", "telegram_username"])

    await state.clear()
    await message.answer(
        f"✅ Аккаунт <b>{user.username}</b> привязан!\n\n"
        f"Теперь вы будете получать уведомления о новых книгах авторов, "
        f"на которых подписаны.",
        parse_mode="HTML"
    )


# ── /stop ─────────────────────────────────────────────────────────────────────

@dp.message(Command("stop"))
async def cmd_stop(message: types.Message):
    from users.models import UserProfile

    updated = UserProfile.objects.filter(
        telegram_chat_id=str(message.chat.id)
    ).update(telegram_chat_id="", telegram_username="")

    if updated:
        await message.answer("✅ Аккаунт отвязан. Уведомления отключены.")
    else:
        await message.answer("Аккаунт и так не привязан. /start — чтобы привязать.")


# ── /me ───────────────────────────────────────────────────────────────────────

@dp.message(Command("me"))
async def cmd_me(message: types.Message):
    from users.models import UserProfile, AuthorSubscription

    try:
        profile = UserProfile.objects.select_related("user").get(
            telegram_chat_id=str(message.chat.id)
        )
        subs = AuthorSubscription.objects.filter(user=profile.user).select_related("author")
        sub_list = "\n".join(f"  • {s.author.name}" for s in subs) or "  (нет подписок)"
        await message.answer(
            f"👤 Аккаунт: <b>{profile.user.username}</b>\n\n"
            f"📖 Подписки на авторов:\n{sub_list}",
            parse_mode="HTML"
        )
    except UserProfile.DoesNotExist:
        await message.answer("Аккаунт не привязан. /start — чтобы привязать.")


# ── main ──────────────────────────────────────────────────────────────────────

async def main():
    logger.info("Бот запущен")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())

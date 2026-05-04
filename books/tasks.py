import re
import logging
from decimal import Decimal, InvalidOperation
from celery import shared_task

logger = logging.getLogger(__name__)


def _parse_price(text: str):
    """
    Извлечь числовое значение цены из произвольной строки.

    Удаляет пробелы между разрядами и приводит число к Decimal,
    возвращает None, если цену определить не удалось.
    """
    text = re.sub(r"(\d)\s+(\d)", r"\1\2", text.strip())
    m = re.search(r"\d+[.,]?\d*", text)
    if not m:
        return None
    try:
        return Decimal(m.group().replace(",", "."))
    except InvalidOperation:
        return None


@shared_task(bind=True, max_retries=2, default_retry_delay=30)
def scrape_book_prices(self, book_id: int):
    """
    Спарсить актуальные цены книги во всех активных магазинах.

    Обновляет текущие цены в BookStore, пишет историю BookPrice
    и пересчитывает среднюю цену книги.
    """
    import requests
    from bs4 import BeautifulSoup
    from django.conf import settings
    from django.utils import timezone
    from books.models import Book, BookStore, BookPrice

    try:
        book = Book.objects.get(pk=book_id)
    except Book.DoesNotExist:
        return

    links = (
        BookStore.objects
        .filter(book=book, store__is_active=True)
        .exclude(product_url="")
        .select_related("store")
    )

    headers = {"User-Agent": settings.SCRAPER_USER_AGENT}
    prices  = []

    for link in links:
        selector = link.store.price_selector.strip()
        if not selector:
            continue
        try:
            resp = requests.get(link.product_url, headers=headers,
                                timeout=settings.SCRAPER_TIMEOUT)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "lxml")
            el   = soup.select_one(selector)
            if el is None:
                link.in_stock = False
                link.last_checked = timezone.now()
                link.save(update_fields=["in_stock", "last_checked"])
                continue

            price = _parse_price(el.get_text())
            if price is None:
                continue

            # Обновляем текущую цену
            link.current_price = price
            link.in_stock      = True
            link.last_checked  = timezone.now()
            link.save(update_fields=["current_price", "in_stock", "last_checked"])

            # Сохраняем в историю
            BookPrice.objects.create(book_store=link, price=price)

            prices.append(price)
            logger.info("Book #%d @ %s: %s ₽", book_id, link.store.name, price)

        except requests.RequestException as exc:
            logger.error("Book #%d @ %s: %s", book_id, link.store.name, exc)

    # Пересчитываем среднюю цену и дату
    if prices:
        book.avg_price = sum(prices) / len(prices)
    book.price_last_requested = timezone.now()
    book.save(update_fields=["avg_price", "price_last_requested"])


@shared_task
def extract_tags_from_description(book_id: int):
    """Извлечь AI-теги из описания книги при её создании."""
    from django.conf import settings as conf
    if not getattr(conf, "ANTHROPIC_API_KEY", ""):
        return

    from books.models import Book
    from books.tag_extraction import apply_tag_to_book
    from core.llm import chat_completion

    try:
        book = Book.objects.prefetch_related("authors", "genres").get(pk=book_id)
    except Book.DoesNotExist:
        return

    if not book.description:
        return

    authors = ", ".join(a.name for a in book.authors.all())
    genres  = ", ".join(g.name for g in book.genres.all())

    prompt = (
        f"Книга: «{book.title}» ({authors}). Жанры: {genres}.\n"
        f"Описание: {book.description[:500]}\n\n"
        "Выдели 3 характерные черты этой книги из её описания. "
        "Каждая черта — содержательная характеристика (атмосфера, тема, стиль, темп, эпоха). "
        "Не оценочные суждения. Каждая черта: 2-4 слова на русском, без точки. "
        "Ответь ТОЛЬКО тремя строками, по одной черте на строку. "
        "Пример:\nатмосфера тревоги\nисторический детектив\nмедленный темп"
    )

    try:
        resp = chat_completion(
            tier="light",
            feature="tag",
            max_tokens=60,
            messages=[{"role": "user", "content": prompt}],
        )
        lines = (resp.choices[0].message.content or "").strip().splitlines()
        for line in lines[:3]:
            tag = line.strip().strip("«»\"'").strip()
            if 2 <= len(tag) <= 80:
                apply_tag_to_book(book, tag)
        logger.info("Description tags extracted for book #%d", book_id)
    except Exception as exc:
        logger.error("extract_tags_from_description error for book #%d: %s", book_id, exc)


@shared_task
def classify_book_mood(book_id: int):
    """AI-классификация книги по mood-тегам."""
    from core.llm import chat_completion
    from books.models import Book, MoodTag, BookMood
    import json

    MOOD_TAXONOMY = [
        "уютная", "мрачная", "напряжённая", "лёгкая", "меланхоличная", "мистическая",
        "стремительная", "размеренная", "медленная",
        "вдохновляющая", "трогательная", "пугающая", "смешная", "философская",
        "лёгкое чтение", "средняя сложность", "требует вдумчивости",
    ]

    try:
        book = Book.objects.prefetch_related("authors", "genres", "tags").get(pk=book_id)
    except Book.DoesNotExist:
        return

    # Собираем контекст
    authors = ", ".join(a.name for a in book.authors.all())
    genres = ", ".join(g.name for g in book.genres.all())
    tags = ", ".join(t.name for t in book.tags.all()[:10])
    desc = (book.description or "")[:500]

    if not desc and not genres:
        return

    prompt = (
        f"Книга: «{book.title}»\n"
        f"Автор: {authors}\n"
        f"Жанры: {genres}\n"
        f"Теги: {tags}\n"
        f"Описание: {desc}\n\n"
        f"Классифицируй книгу по настроению. Выбери 3-5 подходящих тегов из списка:\n"
        f"{', '.join(MOOD_TAXONOMY)}\n\n"
        f"Для каждого тега укажи уверенность от 0.5 до 1.0."
    )

    tools = [{
        "type": "function",
        "function": {
            "name": "classify_moods",
            "parameters": {
                "type": "object",
                "properties": {
                    "moods": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string"},
                                "confidence": {"type": "number"},
                            },
                            "required": ["name", "confidence"],
                        },
                    },
                },
                "required": ["moods"],
            },
        },
    }]

    try:
        resp = chat_completion(
            tier="light",
            feature="mood",
            messages=[{"role": "user", "content": prompt}],
            tools=tools,
            tool_choice={"type": "function", "function": {"name": "classify_moods"}},
            max_tokens=300,
        )
    except Exception as exc:
        logger.error("classify_book_mood API error for book #%d: %s", book_id, exc)
        return

    for choice in resp.choices:
        if not choice.message.tool_calls:
            continue
        for tc in choice.message.tool_calls:
            data = json.loads(tc.function.arguments)
            for mood_item in data.get("moods", []):
                mood_name = mood_item["name"].lower().strip()
                confidence = float(mood_item.get("confidence", 0.8))
                mood_tag = MoodTag.objects.filter(name=mood_name).first()
                if mood_tag and confidence >= 0.5:
                    BookMood.objects.update_or_create(
                        book=book, mood=mood_tag,
                        defaults={"confidence": confidence, "source": "ai"},
                    )

    logger.info("Mood classification done for book #%d", book_id)


@shared_task(bind=True)
def import_library_task(self, user_id: int, file_content: str):
    """Фоновый импорт библиотеки из Goodreads CSV."""
    from django.contrib.auth.models import User
    from .import_library import import_library
    from .ai_recommendations import invalidate as invalidate_ai_cache

    try:
        user = User.objects.get(pk=user_id)
        stats = import_library(user, file_content)
        invalidate_ai_cache(user_id)
        logger.info("Library import for user #%d: %s", user_id, stats)
        return stats
    except Exception as exc:
        logger.error("Library import failed for user #%d: %s", user_id, exc)
        raise


@shared_task
def generate_smart_quotes(book_id: int):
    """AI-генерация умных цитат для книги."""
    from core.llm import chat_completion
    from books.models import Book, Quote, MoodTag
    from django.contrib.auth.models import User
    import json

    try:
        book = Book.objects.prefetch_related("authors", "genres").get(pk=book_id)
    except Book.DoesNotExist:
        return

    # Не генерируем, если уже есть AI-цитаты
    if book.quotes.filter(is_ai_generated=True).count() >= 3:
        return

    authors = ", ".join(a.name for a in book.authors.all())
    genres = ", ".join(g.name for g in book.genres.all())
    desc = (book.description or "")[:500]

    if not desc:
        return

    mood_names = list(MoodTag.objects.values_list("name", flat=True))

    prompt = (
        f"Книга: «{book.title}»\n"
        f"Автор: {authors}\n"
        f"Жанры: {genres}\n"
        f"Описание: {desc}\n\n"
        f"Сгенерируй 3 вдохновляющие цитаты, которые МОГЛИ БЫ быть в этой книге. "
        f"Цитаты должны отражать стиль автора и тематику книги. "
        f"Для каждой цитаты подбери подходящее настроение из списка:\n"
        f"{', '.join(mood_names)}"
    )

    tools = [{
        "type": "function",
        "function": {
            "name": "save_quotes",
            "parameters": {
                "type": "object",
                "properties": {
                    "quotes": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "text": {"type": "string"},
                                "mood": {"type": "string"},
                            },
                            "required": ["text", "mood"],
                        },
                    },
                },
                "required": ["quotes"],
            },
        },
    }]

    try:
        resp = chat_completion(
            tier="light",
            feature="quotes",
            messages=[{"role": "user", "content": prompt}],
            tools=tools,
            tool_choice={"type": "function", "function": {"name": "save_quotes"}},
            max_tokens=500,
        )
    except Exception as exc:
        logger.error("generate_smart_quotes API error for book #%d: %s", book_id, exc)
        return

    # Используем первого staff-пользователя как автора AI-цитат
    ai_user = User.objects.filter(is_staff=True).first()
    if not ai_user:
        return

    for choice in resp.choices:
        if not choice.message.tool_calls:
            continue
        for tc in choice.message.tool_calls:
            data = json.loads(tc.function.arguments)
            for q_item in data.get("quotes", [])[:3]:
                text = q_item.get("text", "").strip()
                if not text or len(text) < 10:
                    continue
                mood_name = q_item.get("mood", "").lower().strip()
                mood = MoodTag.objects.filter(name=mood_name).first()
                Quote.objects.create(
                    user=ai_user,
                    book=book,
                    text=text,
                    is_ai_generated=True,
                    mood_tag=mood,
                )

    logger.info("Smart quotes generated for book #%d", book_id)


@shared_task
def check_price_alerts():
    """Celery Beat: проверяем алерты цен раз в сутки."""
    from django.utils import timezone
    from books.models import PriceAlert
    from notifications.telegram import send_message
    from notifications.max import send_message as max_send_message
    from notifications.vk import send_message as vk_send_message
    from notifications.models import NotificationSetting
    from django.conf import settings as conf

    site_url = getattr(conf, "SITE_URL", "")
    now = timezone.now()

    ch = NotificationSetting.channels_for(NotificationSetting.EVENT_PRICE_ALERT)

    alerts = (
        PriceAlert.objects
        .filter(triggered_at__isnull=True)
        .select_related("user__profile", "book")
    )

    from notifications.email import send_price_alert_email

    for alert in alerts:
        book = alert.book
        if book.avg_price is None:
            continue
        if book.avg_price <= alert.threshold:
            notified = False
            profile = getattr(alert.user, "profile", None)

            if profile:
                book_url = f"{site_url}/books/{book.pk}/"
                text = (
                    f"🔔 <b>Цена снизилась!</b>\n\n"
                    f"<b>{book.title}</b>\n"
                    f"Текущая цена: {book.avg_price} ₽\n"
                    f"Ваш порог: {alert.threshold} ₽\n"
                )
                if site_url:
                    text += f"\n<a href='{book_url}'>Открыть в 'Строка'</a>"

                # Telegram
                if ch["telegram"] and profile.telegram_chat_id:
                    send_message(profile.telegram_chat_id, text)
                    notified = True

                if ch["max"] and profile.max_user_id:
                    max_send_message(profile.max_user_id, text)
                    notified = True

                if ch["vk"] and profile.vk_user_id:
                    vk_send_message(profile.vk_user_id, text)
                    notified = True

            # Email (fallback если нет мессенджеров)
            if ch["email"] and not notified and alert.user.email:
                send_price_alert_email(
                    alert.user, book, book.avg_price, alert.threshold
                )

            alert.triggered_at = now
            alert.save(update_fields=["triggered_at"])
            logger.info(
                "Price alert triggered: user %s, book #%d, price %s <= %s",
                alert.user.username, book.pk, book.avg_price, alert.threshold
            )


# ─── РЕГИСТРАЦИЯ AI-ТАСКОВ ────────────────────────────────────────────────────
# Celery autodiscover импортирует только `tasks.py` в каждом app. Наши AI-таски
# живут в `books/ai_tasks.py`, поэтому импортируем модуль здесь — это
# регистрирует все его `@shared_task`-функции (summarize_chapter,
# summarize_all_chapters, extract_book_quotes, extract_book_themes,
# build_style_profile) в Celery-реестре воркера при старте.
from . import ai_tasks  # noqa: E402,F401

"""
Извлечение тега из отзыва через LLM (OpenRouter).
Вызывается асинхронно (Celery) после одобрения отзыва модератором.

Логика:
  - Пропускаем отзывы короче 20 символов
  - LLM возвращает одну фразу (2-4 слова) — характерную черту книги
  - Ищем похожий тег у книги (case-insensitive), если есть — инкрементируем
  - Если нет и тегов < 5 — создаём новый
"""

import logging
from django.conf import settings
from core.llm import chat_completion
from .models import BookTag

logger = logging.getLogger(__name__)

MIN_REVIEW_LEN = 20
MAX_TAGS_PER_BOOK = 5


def extract_tag_from_review(review) -> str | None:
    """Вызвать LLM и вернуть тег (строку) или None."""
    if not review.text or len(review.text.strip()) < MIN_REVIEW_LEN:
        return None

    api_key = getattr(settings, "ANTHROPIC_API_KEY", "")
    if not api_key:
        logger.warning("API-ключ LLM не задан — тег не извлечён")
        return None

    book = review.book
    authors = ", ".join(a.name for a in book.authors.all())

    prompt = (
        f"Книга: «{book.title}» ({authors})\n"
        f"Отзыв читателя (оценка {review.rating}/5):\n{review.text}\n\n"
        "Выдели ОДНУ характерную черту этой книги, которую упоминает читатель. "
        "Это должна быть содержательная характеристика книги (жанр, атмосфера, темп, стиль, тема), "
        "а не оценочное суждение («хорошая», «плохая»). "
        "Ответь ТОЛЬКО фразой из 2-4 слов на русском, без точки в конце. "
        "Примеры: «психологический триллер», «медленный темп», «неожиданная концовка», «атмосфера тревоги»."
    )

    try:
        resp = chat_completion(
            tier="light",
            feature="tag",
            max_tokens=30,
            messages=[{"role": "user", "content": prompt}],
        )
        tag = (resp.choices[0].message.content or "").strip().strip(".")
        # Базовая санитизация: убираем кавычки, ограничиваем длину
        tag = tag.strip("«»\"'").strip()
        return tag if 2 <= len(tag) <= 80 else None
    except Exception as exc:
        logger.error("LLM tag extraction error for review #%d: %s", review.pk, exc)
        return None


def apply_tag_to_book(book, tag_name: str) -> None:
    """Добавить тег к книге или инкрементировать счётчик существующего."""

    tag_lower = tag_name.lower()

    # Ищем существующий тег (case-insensitive)
    existing = BookTag.objects.filter(book=book, name__iexact=tag_lower).first()
    if existing:
        existing.count += 1
        existing.save(update_fields=["count"])
        return

    # Лимит 5 тегов на книгу
    current_count = BookTag.objects.filter(book=book).count()
    if current_count >= MAX_TAGS_PER_BOOK:
        # Новый тег вытесняет самый редкий если он популярнее
        weakest = BookTag.objects.filter(book=book).order_by("count").first()
        if weakest and weakest.count < 2:
            weakest.name = tag_name
            weakest.count = 1
            weakest.save(update_fields=["name", "count"])
        return

    BookTag.objects.create(book=book, name=tag_name)


def decrement_tag_from_review(review) -> None:
    """
    Уменьшить счётчик тега при отклонении отзыва.
    Если тег стал 0 — удалить.
    """

    if not hasattr(review, "_extracted_tag") or not review._extracted_tag:
        return

    tag = BookTag.objects.filter(
        book=review.book, name__iexact=review._extracted_tag
    ).first()
    if not tag:
        return

    if tag.count <= 1:
        tag.delete()
    else:
        tag.count -= 1
        tag.save(update_fields=["count"])

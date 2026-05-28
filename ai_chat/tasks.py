from celery import shared_task
from django.conf import settings
from django.contrib.auth import get_user_model

from books.models import Book

from .discovery_engine import ask_discovery, ask_elaborate
from .engine import ask_about_book
from .models import BookChat, DiscoveryChat


AI_TASK_LIMITS = {
    "soft_time_limit": settings.AI_CELERY_TASK_SOFT_TIME_LIMIT,
    "time_limit": settings.AI_CELERY_TASK_TIME_LIMIT,
}


@shared_task(**AI_TASK_LIMITS)
def discovery_send_task(user_id, message, exclude_ids=None, mode="standard"):
    user = get_user_model().objects.get(pk=user_id)
    chat, _ = DiscoveryChat.objects.get_or_create(user=user)
    result = ask_discovery(user, message, chat, extra_exclude_ids=exclude_ids or [], mode=mode)
    return {
        "ok": True,
        "chat_id": chat.pk,
        "assistant_message_id": result.get("message_id"),
        "from_cache": bool(result.get("from_cache")),
    }


@shared_task(**AI_TASK_LIMITS)
def discovery_elaborate_task(user_id, book_id, short_reason=""):
    user = get_user_model().objects.get(pk=user_id)
    book = Book.objects.prefetch_related("authors", "genres").get(pk=book_id)
    chat = DiscoveryChat.objects.filter(user=user).first()
    if not chat:
        return {"ok": False, "error": "context_lost"}
    text = ask_elaborate(user, chat, book, short_reason=short_reason or "")
    return {"ok": True, "text": text}


@shared_task(**AI_TASK_LIMITS)
def book_chat_send_task(user_id, book_id, message):
    user = get_user_model().objects.get(pk=user_id)
    book = Book.objects.get(pk=book_id)
    chat, _ = BookChat.objects.get_or_create(user=user, book=book)
    ai_text = ask_about_book(chat, message)
    return {"ok": True, "text": ai_text}

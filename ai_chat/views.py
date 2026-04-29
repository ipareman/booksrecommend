from django.shortcuts import render, get_object_or_404
from django.http import HttpResponse
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST, require_GET
from celery.result import AsyncResult

from books.models import Book
from .models import BookChat, DiscoveryChat, DiscoveryChatMessage
from .discovery_engine import (
    save_last_recommendations_as_list,
)
from .discovery_helpers import enrich_books_with_prices, find_similar_public_lists
from .tasks import book_chat_send_task, discovery_elaborate_task, discovery_send_task


# ─── BOOK CHAT (без изменений) ────────────────────────────────────────────────

@login_required
def book_chat(request, book_id):
    book = get_object_or_404(Book.objects.prefetch_related("authors"), pk=book_id)
    chat, _ = BookChat.objects.get_or_create(user=request.user, book=book)
    messages = chat.messages.order_by("created_at")[:100]
    return render(request, "ai_chat/book_chat.html", {
        "book": book,
        "chat": chat,
        "messages_dial": messages,
    })


@login_required
@require_POST
def book_chat_send(request, book_id):
    book = get_object_or_404(Book.objects.prefetch_related("authors"), pk=book_id)
    user_message = request.POST.get("message", "").strip()

    if not user_message:
        return HttpResponse("")

    try:
        task = book_chat_send_task.delay(request.user.pk, book.pk, user_message)
    except Exception:
        return render(request, "ai_chat/_book_chat_result.html", {
            "book": book,
            "text": "Очередь AI сейчас недоступна. Проверьте Redis/Celery worker и попробуйте ещё раз.",
        })

    request.session[f"book_chat_task_{book.pk}"] = task.id

    return render(request, "ai_chat/_book_chat_pending.html", {
        "book": book,
        "user_message": user_message,
        "task_id": task.id,
    })


@login_required
@require_GET
def book_chat_status(request, book_id):
    book = get_object_or_404(Book.objects.prefetch_related("authors"), pk=book_id)
    task_id = request.GET.get("task_id") or request.session.get(f"book_chat_task_{book.pk}")
    result = AsyncResult(task_id) if task_id else None

    try:
        is_ready = result.ready() if result else False
    except Exception:
        return render(request, "ai_chat/_book_chat_result.html", {
            "book": book,
            "text": "Очередь AI сейчас недоступна. Проверьте Redis/Celery worker и попробуйте ещё раз.",
        })

    if is_ready:
        if result.successful():
            payload = result.result or {}
            return render(request, "ai_chat/_book_chat_result.html", {
                "book": book,
                "text": payload.get("text", ""),
            })
        return render(request, "ai_chat/_book_chat_result.html", {
            "book": book,
            "text": "Извините, не удалось получить ответ AI. Попробуйте ещё раз.",
        })

    return render(request, "ai_chat/_book_chat_status.html", {
        "book": book,
        "task_id": task_id,
    })


@login_required
@require_POST
def book_chat_clear(request, book_id):
    book = get_object_or_404(Book, pk=book_id)
    BookChat.objects.filter(user=request.user, book=book).delete()
    return HttpResponse('<p style="font-size:13px;color:var(--ghost);text-align:center;padding:24px 0">История очищена. Задайте вопрос о книге.</p>')


# ─── DISCOVERY CHAT ──────────────────────────────────────────────────────────

def _hydrate_persisted_message(msg: DiscoveryChatMessage) -> list[dict]:
    """
    Подготавливает recommended_books с ценами + reason для рендера истории.
    Используется, чтобы при перезаходе в чат карточки показывались корректно.
    """
    items = msg.books_with_reasons()
    if items:
        enrich_books_with_prices(items)
    return items


@login_required
def discovery_chat(request):
    chat = DiscoveryChat.objects.filter(user=request.user).first()
    messages_hydrated = []
    if chat:
        for m in chat.messages.order_by("created_at")[:50]:
            messages_hydrated.append({
                "role":             m.role,
                "content":          m.content,
                "msg_id":           m.pk,
                "followup_options": m.followup_options if m.role == "assistant" else [],
                "books":            _hydrate_persisted_message(m) if m.role == "assistant" else [],
            })
    return render(request, "ai_chat/discovery.html", {
        "chat": chat,
        "messages": messages_hydrated,
        "suppress_toasts": True,
    })


@login_required
@require_POST
def discovery_send(request):
    """HTMX: отправить сообщение discovery-чату."""
    user_message = request.POST.get("message", "").strip()
    if not user_message:
        return HttpResponse("")

    # exclude_ids может приходить как строка "1,2,3" (из скрытого поля)
    exclude_raw = request.POST.get("exclude_ids", "")
    exclude_ids = []
    for x in exclude_raw.split(","):
        x = x.strip()
        if x.isdigit():
            exclude_ids.append(int(x))

    try:
        task = discovery_send_task.delay(request.user.pk, user_message, exclude_ids)
    except Exception:
        return render(request, "ai_chat/_discovery_error.html")

    request.session["discovery_task"] = task.id

    return render(request, "ai_chat/_discovery_pending.html", {
        "user_message": user_message,
        "task_id": task.id,
    })


@login_required
@require_GET
def discovery_status(request):
    task_id = request.GET.get("task_id") or request.session.get("discovery_task")
    result = AsyncResult(task_id) if task_id else None

    try:
        is_ready = result.ready() if result else False
    except Exception:
        return render(request, "ai_chat/_discovery_error.html")

    if is_ready:
        if not result.successful():
            return render(request, "ai_chat/_discovery_error.html")

        payload = result.result or {}
        chat = get_object_or_404(DiscoveryChat, pk=payload.get("chat_id"), user=request.user)
        msg = get_object_or_404(
            DiscoveryChatMessage,
            pk=payload.get("assistant_message_id"),
            chat=chat,
            role="assistant",
        )
        books = _hydrate_persisted_message(msg)
        return render(request, "ai_chat/_discovery_assistant_result.html", {
            "text": msg.content,
            "books": books,
            "followup_options": msg.followup_options,
            "public_lists": find_similar_public_lists([item["book"].pk for item in books], request.user.pk) if books else [],
            "from_cache": payload.get("from_cache", False),
            "chat": chat,
            "message_id": msg.pk,
        })

    return render(request, "ai_chat/_discovery_status.html", {"task_id": task_id})


@login_required
@require_POST
def discovery_clear(request):
    DiscoveryChat.objects.filter(user=request.user).delete()
    return HttpResponse(
        '<p style="font-size:13px;color:var(--ghost);text-align:center;'
        'padding:24px 0">Начните новый диалог. Опишите, какую книгу ищете.</p>'
    )


# ─── DISCOVERY: FEEDBACK / ELABORATE / SAVE-AS-LIST ───────────────────────────

@login_required
@require_POST
def discovery_dislike(request):
    """
    👎 «Не то» под книгой.
    Вход: message_id, book_id, reason (тон|жанр|объём|автор|другое).
    Помечает книгу как отвергнутую → в след. запросе она не появится.
    Возвращает пустой ответ (HTMX удалит карточку через hx-swap="outerHTML").
    """
    try:
        message_id = int(request.POST.get("message_id", 0))
        book_id    = int(request.POST.get("book_id", 0))
    except (TypeError, ValueError):
        return HttpResponse(status=400)

    reason = (request.POST.get("reason") or "").strip()[:50]

    msg = get_object_or_404(
        DiscoveryChatMessage,
        pk=message_id,
        chat__user=request.user,
    )

    disliked = msg.disliked_book_ids or []
    if not any(isinstance(d, dict) and d.get("book_id") == book_id for d in disliked):
        disliked.append({"book_id": book_id, "reason": reason})
    msg.disliked_book_ids = disliked
    msg.save(update_fields=["disliked_book_ids"])

    # Возвращаем «заглушку» вместо карточки
    return HttpResponse(
        f'<div style="padding:8px 12px;font-size:12px;color:var(--ghost);'
        f'border:1px dashed var(--border);border-radius:8px;max-width:340px">'
        f'👎 Учли. В следующей рекомендации эту книгу не покажем.'
        f'</div>'
    )


@login_required
@require_POST
def discovery_elaborate(request):
    """
    «Подробнее» — разворачивает reason в абзац-рассуждение.
    Вход: book_id. Возвращает HTML-фрагмент для swap в карточке.
    """
    try:
        book_id = int(request.POST.get("book_id", 0))
    except (TypeError, ValueError):
        return HttpResponse(status=400)

    book = get_object_or_404(Book.objects.prefetch_related("authors", "genres"), pk=book_id)
    chat = DiscoveryChat.objects.filter(user=request.user).first()
    short_reason = (request.POST.get("short_reason") or "").strip()

    if not chat:
        return HttpResponse(
            '<div style="font-size:12px;color:var(--ghost)">'
            'Контекст чата утерян. Обновите страницу.</div>'
        )

    try:
        task = discovery_elaborate_task.delay(request.user.pk, book.pk, short_reason)
    except Exception:
        return render(request, "ai_chat/_elaborate_result.html", {
            "text": "Очередь AI сейчас недоступна. Проверьте Redis/Celery worker и попробуйте ещё раз.",
        })

    return render(request, "ai_chat/_elaborate_pending.html", {
        "book": book,
        "task_id": task.id,
    })


@login_required
@require_GET
def discovery_elaborate_status(request):
    task_id = request.GET.get("task_id")
    result = AsyncResult(task_id) if task_id else None

    try:
        is_ready = result.ready() if result else False
    except Exception:
        return render(request, "ai_chat/_elaborate_result.html", {
            "text": "Очередь AI сейчас недоступна. Проверьте Redis/Celery worker и попробуйте ещё раз.",
        })

    if is_ready:
        if result.successful():
            payload = result.result or {}
            if payload.get("ok"):
                return render(request, "ai_chat/_elaborate_result.html", {"text": payload.get("text", "")})
        return render(request, "ai_chat/_elaborate_result.html", {
            "text": "Не удалось получить развёрнутое объяснение.",
        })

    return render(request, "ai_chat/_elaborate_pending.html", {"task_id": task_id})


@login_required
@require_POST
def discovery_save_list(request):
    """
    «Сохранить эту подборку как список» → создаёт UserList.
    Возвращает HTMX-ответ с ссылкой.
    """
    chat = DiscoveryChat.objects.filter(user=request.user).first()
    if not chat:
        return HttpResponse(
            '<span style="font-size:12px;color:var(--err)">Чат пуст.</span>'
        )

    list_name = (request.POST.get("name") or "").strip()
    ul = save_last_recommendations_as_list(request.user, chat, list_name=list_name)
    if not ul:
        return HttpResponse(
            '<span style="font-size:12px;color:var(--err)">Нечего сохранять.</span>'
        )

    return HttpResponse(
        f'<span style="font-size:12px;color:var(--ok,#0a7a42)">'
        f'✓ Сохранено как список <b>«{ul.name}»</b> '
        f'({ul.books.count()} книг)</span>'
    )

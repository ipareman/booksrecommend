from django.shortcuts import render, get_object_or_404, redirect
from django.http import HttpResponse, JsonResponse
from django.contrib.auth.decorators import login_required
from django.contrib import messages as dj_messages
from django.views.decorators.http import require_POST, require_GET

from books.models import Book
from .models import BookChat, BookChatMessage, DiscoveryChat, DiscoveryChatMessage
from .engine import ask_about_book
from .discovery_engine import (
    ask_discovery,
    ask_elaborate,
    save_last_recommendations_as_list,
)
from .discovery_helpers import enrich_books_with_prices, find_similar_public_lists


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
    chat, _ = BookChat.objects.get_or_create(user=request.user, book=book)
    user_message = request.POST.get("message", "").strip()

    if not user_message:
        return HttpResponse("")

    ai_text = ask_about_book(chat, user_message)

    return render(request, "ai_chat/_messages.html", {
        "book": book,
        "new_messages": [
            {"role": "user", "content": user_message},
            {"role": "assistant", "content": ai_text},
        ],
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

    chat, _ = DiscoveryChat.objects.get_or_create(user=request.user)
    result = ask_discovery(request.user, user_message, chat,
                           extra_exclude_ids=exclude_ids)

    return render(request, "ai_chat/_discovery_response.html", {
        "user_message":      user_message,
        "text":              result["text"],
        "books":             result["books"],
        "followup_options":  result["followup_options"],
        "public_lists":      result["public_lists"],
        "from_cache":        result["from_cache"],
        "chat":              chat,
    })


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

    text = ask_elaborate(request.user, chat, book, short_reason=short_reason)
    return HttpResponse(
        f'<div style="font-size:12px;line-height:1.5;color:var(--muted);'
        f'margin-top:6px;padding:10px;background:var(--surface);border-radius:6px">'
        f'{text}</div>'
    )


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

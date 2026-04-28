from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.db.models import Max, Q, OuterRef, Subquery
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .models import ChatMessage, ChatMessageReaction, ChatParticipant, ChatRoom
from .linkify import linkify_message_text
from books.models import Book

User = get_user_model()


def _get_or_create_dm(user_a, user_b):
    """Return the DM room between two users, creating one if needed."""
    room = (
        ChatRoom.objects.filter(room_type=ChatRoom.ROOM_DM, participants__user=user_a)
        .filter(participants__user=user_b)
        .first()
    )
    if room:
        return room
    room = ChatRoom.objects.create(room_type=ChatRoom.ROOM_DM)
    ChatParticipant.objects.create(room=room, user=user_a)
    ChatParticipant.objects.create(room=room, user=user_b)
    return room


@login_required
def chat_list(request):
    """List of user's chat rooms, sorted by last message."""
    rooms = (
        ChatRoom.objects.filter(participants__user=request.user)
        .exclude(room_type=ChatRoom.ROOM_CLUB_THREAD)
        .annotate(last_msg_at=Max("messages__created_at"))
        .order_by("-last_msg_at")
    )

    last_msg_sub = Subquery(
        ChatMessage.objects.filter(room=OuterRef("pk")).order_by("-created_at").values("body")[:1]
    )
    rooms = rooms.annotate(last_msg_body=last_msg_sub)

    room_data = []
    for room in rooms:
        if room.room_type == ChatRoom.ROOM_DM:
            other = room.participants.exclude(user=request.user).select_related("user").first()
            title = other.user.username if other else "Чат"
        elif room.room_type == ChatRoom.ROOM_CLUB_THREAD:
            thread = getattr(room, "club_book_thread", None)
            title = f"Обсуждение: {thread.club_book.book.title}" if thread else "Обсуждение книги"
        else:
            title = room.club.name if room.club else "Клубный чат"

        participant = room.participants.filter(user=request.user).first()
        unread = 0
        if participant:
            unread = room.messages.filter(created_at__gt=participant.last_read_at).exclude(user=request.user).count()

        room_data.append({
            "room": room,
            "title": title,
            "last_msg": room.last_msg_body or "",
            "unread": unread,
        })

    return render(request, "chat/chat_list.html", {"room_data": room_data})


@login_required
def chat_dm(request, user_id):
    """Open or create a DM with another user."""
    other = get_object_or_404(User, pk=user_id)
    if other == request.user:
        return redirect("chat_list")
    room = _get_or_create_dm(request.user, other)
    return redirect("chat_room", room_id=room.pk)


@login_required
def chat_room(request, room_id):
    """Render chat room page (WebSocket connects from JS)."""
    room = get_object_or_404(ChatRoom, pk=room_id)
    participant = room.participants.filter(user=request.user).first()
    if not participant:
        return redirect("chat_list")
    if room.room_type == ChatRoom.ROOM_CLUB_THREAD:
        thread = getattr(room, "club_book_thread", None)
        if thread:
            return redirect(
                "club_book_thread",
                pk=thread.club_book.club_id,
                book_id=thread.club_book.book_id,
            )

    # mark as read
    from django.utils import timezone
    now = timezone.now()
    participant.last_read_at = now
    participant.save(update_fields=["last_read_at"])

    # также занулить inbox-уведомления о новых сообщениях из этой комнаты
    try:
        from notifications.models import Notification
        Notification.objects.filter(
            user=request.user,
            kind=Notification.KIND_NEW_MESSAGE,
            extra__room_id=room.pk,
            read_at__isnull=True,
        ).update(read_at=now)
    except Exception:
        pass

    messages = list(
        room.messages
        .select_related("user", "user__profile", "attached_book")
        .prefetch_related("attached_book__authors", "reactions__user")
        .order_by("created_at")[:100]
    )

    # Сводка реакций attach-им прямо к каждому сообщению — шаблон обходит её
    # как `for r in msg.reactions_summary`. Порядок чипов — по ALLOWED_EMOJI,
    # чтобы UI не «прыгал» между вкладками.
    for m in messages:
        grouped = {}
        for r in m.reactions.all():
            slot = grouped.setdefault(r.emoji, {"count": 0, "users": [], "mine": False})
            slot["count"] += 1
            slot["users"].append(r.user.username)
            if r.user_id == request.user.id:
                slot["mine"] = True
        m.reactions_summary = [
            {"emoji": e, **grouped[e]}
            for e in ChatMessageReaction.ALLOWED_EMOJI
            if e in grouped
        ]

    if room.room_type == ChatRoom.ROOM_DM:
        other = room.participants.exclude(user=request.user).select_related("user").first()
        title = other.user.username if other else "Чат"
    elif room.room_type == ChatRoom.ROOM_CLUB_THREAD:
        thread = getattr(room, "club_book_thread", None)
        title = f"Обсуждение: {thread.club_book.book.title}" if thread else "Обсуждение книги"
    else:
        title = room.club.name if room.club else "Клубный чат"

    import json as _json
    allowed_emoji_json = _json.dumps(ChatMessageReaction.ALLOWED_EMOJI, ensure_ascii=False)

    return render(request, "chat/chat_room.html", {
        "room": room,
        "title": title,
        "chat_messages": messages,
        "allowed_emoji_json": allowed_emoji_json,
    })


@login_required
@require_POST
def chat_edit_message(request, message_id):
    """
    Редактирование своего сообщения. Поддерживает:
      • изменение body (как раньше),
      • замену прикреплённой книги (новый book_id),
      • открепление книги (book_id="" или "0").

    Параметр book_id обрабатывается ТОЛЬКО если он явно передан в POST.
    Если ключа нет — attached_book не трогаем (чтобы старый клиент,
    шлющий только body, не сбрасывал книгу).
    """
    from django.template.loader import render_to_string

    msg = get_object_or_404(
        ChatMessage.objects.select_related("attached_book"),
        pk=message_id,
        user=request.user,
    )
    body = request.POST.get("body", "").strip()

    # Книга: явно передан ключ → меняем или открепляем
    book_changed = "book_id" in request.POST
    new_book = msg.attached_book  # default — оставить как есть
    if book_changed:
        raw = (request.POST.get("book_id") or "").strip()
        if raw in ("", "0", "null"):
            new_book = None
        else:
            try:
                new_book = Book.objects.prefetch_related("authors").filter(pk=int(raw)).first()
            except (TypeError, ValueError):
                new_book = msg.attached_book  # игнорируем мусор

    # Должно остаться хоть тело, хоть вложение — отдаём дружелюбное сообщение,
    # чтобы клиент мог его показать как есть без жёсткого alert-fallback.
    if not body and not new_book:
        return JsonResponse(
            {"ok": False, "error": "Сообщение не может быть пустым — оставьте текст или прикрепите книгу."},
            status=400,
        )

    update_fields = []
    if body != msg.body:
        msg.body = body
        update_fields.append("body")
    if book_changed and new_book != msg.attached_book:
        msg.attached_book = new_book
        update_fields.append("attached_book")
    if update_fields:
        msg.save(update_fields=update_fields)

    # HTML-partial карточки — фронт просто вставит его, без дублирующего рендера на JS.
    book_html = ""
    book_payload = None
    if msg.attached_book:
        book_html = render_to_string(
            "ai_chat/_book_card.html",
            {"book": msg.attached_book, "reason": ""},
            request=request,
        )
        b = msg.attached_book
        book_payload = {
            "id": b.pk,
            "title": b.title,
            "authors": ", ".join(a.name for a in b.authors.all()),
            "cover_url": b.cover_image.url if b.cover_image else "",
            "url": f"/books/{b.pk}/",
            "avg_rating": float(b.avg_rating) if b.avg_rating else None,
        }

    body_html = str(linkify_message_text(msg.body))

    try:
        from channels.layers import get_channel_layer
        from asgiref.sync import async_to_sync
        layer = get_channel_layer()
        if layer is not None:
            async_to_sync(layer.group_send)(
                f"chat_{msg.room_id}",
                {
                    "type": "chat_edit",
                    "message_id": msg.pk,
                    "body": msg.body,
                    "body_html": body_html,
                    "book": book_payload,
                    "book_html": book_html,
                },
            )
    except Exception:
        pass

    return JsonResponse({
        "ok": True,
        "id": msg.pk,
        "body": msg.body,
        "body_html": body_html,
        "book": book_payload,
        "book_html": book_html,
    })


@login_required
@require_POST
def chat_toggle_reaction(request, message_id):
    """
    Переключатель emoji-реакции: если у юзера уже есть такая реакция — удаляем,
    иначе создаём. Только участники комнаты могут реагировать. После изменения
    шлём событие в room-group, чтобы все клиенты обновили UI без перезагрузки.
    """
    msg = get_object_or_404(
        ChatMessage.objects.select_related("room"),
        pk=message_id,
    )
    # Только участник комнаты может реагировать
    if not ChatParticipant.objects.filter(room=msg.room, user=request.user).exists():
        return JsonResponse({"error": "forbidden"}, status=403)

    emoji = (request.POST.get("emoji") or "").strip()
    if emoji not in ChatMessageReaction.ALLOWED_EMOJI:
        return JsonResponse({"error": "emoji_not_allowed"}, status=400)

    # Toggle
    existing = ChatMessageReaction.objects.filter(
        message=msg, user=request.user, emoji=emoji
    ).first()
    if existing:
        existing.delete()
        action = "removed"
    else:
        ChatMessageReaction.objects.create(message=msg, user=request.user, emoji=emoji)
        action = "added"

    # Считаем актуальные счётчики по этому emoji + список юзеров для тултипа
    counts = _reaction_summary(msg)

    # Реалтайм-broadcast всем участникам комнаты
    try:
        from channels.layers import get_channel_layer
        from asgiref.sync import async_to_sync
        layer = get_channel_layer()
        if layer is not None:
            async_to_sync(layer.group_send)(
                f"chat_{msg.room_id}",
                {
                    "type": "chat_reaction",
                    "message_id": msg.pk,
                    "counts": counts,
                },
            )
    except Exception:
        # Если каналов нет / сетевой пик — UI и так обновится через JSON-ответ
        # этому юзеру. Падать не будем.
        pass

    return JsonResponse({"ok": True, "action": action, "emoji": emoji, "counts": counts})


def _reaction_summary(msg):
    """{emoji: {count, users:[...usernames], allowed: True}} — формат для UI."""
    out = {}
    qs = ChatMessageReaction.objects.filter(message=msg).select_related("user")
    for r in qs:
        slot = out.setdefault(r.emoji, {"count": 0, "users": []})
        slot["count"] += 1
        slot["users"].append(r.user.username)
    return out


@login_required
def chat_history(request, room_id):
    """HTMX partial: load older messages."""
    room = get_object_or_404(ChatRoom, pk=room_id)
    if not room.participants.filter(user=request.user).exists():
        return JsonResponse({"error": "forbidden"}, status=403)

    before = request.GET.get("before")
    qs = (
        room.messages
        .select_related("user", "user__profile", "attached_book")
        .prefetch_related("attached_book__authors")
        .order_by("-created_at")
    )
    if before:
        qs = qs.filter(pk__lt=before)
    msgs = list(qs[:30])
    msgs.reverse()
    return render(request, "chat/_messages_batch.html", {"messages": msgs, "user": request.user})


@login_required
def chat_book_search(request):
    """
    JSON-эндпоинт для пикера книг в чате: GET ?q=… → список книг с минимумом полей.
    Ищем триграммой + icontains по title/authors.
    """
    q = (request.GET.get("q") or "").strip()
    if len(q) < 2:
        return JsonResponse({"results": []})

    try:
        from django.contrib.postgres.search import TrigramWordSimilarity
        from django.db.models import Q as _Q
        qs = (
            Book.objects
            .annotate(sim=TrigramWordSimilarity(q, "title"))
            .filter(_Q(sim__gte=0.15) | _Q(title__icontains=q) | _Q(authors__name__icontains=q))
            .distinct()
            .prefetch_related("authors")
            .order_by("-sim", "-rating_count")[:10]
        )
    except Exception:
        qs = (
            Book.objects
            .filter(title__icontains=q)
            .prefetch_related("authors")
            .order_by("-rating_count")[:10]
        )

    def serialize(b):
        return {
            "id": b.pk,
            "title": b.title,
            "authors": ", ".join(a.name for a in b.authors.all()),
            "cover_url": b.cover_image.url if b.cover_image else "",
            "avg_rating": float(b.avg_rating) if b.avg_rating else None,
        }

    return JsonResponse({"results": [serialize(b) for b in qs]})

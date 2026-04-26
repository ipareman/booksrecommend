from django.shortcuts import render, redirect, get_object_or_404
from django.http import HttpResponse
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST, require_GET
from django.contrib.auth import get_user_model
from django.db.models import Q
from itertools import chain

from .models import Friendship, ActivityEvent, BookRecommendation
from .helpers import get_friends, get_friendship_status, friend_ids_set
from books.models import Book

User = get_user_model()


# ─── ДРУЗЬЯ ────────────────────────────────────────────────────────────────────

@login_required
@require_POST
def friend_request(request, user_id):
    target = get_object_or_404(User, pk=user_id)
    if target == request.user:
        return HttpResponse(status=400)
    fs, created = Friendship.objects.get_or_create(
        from_user=request.user,
        to_user=target,
        defaults={"status": "pending"},
    )
    return render(request, "social/_friend_btn.html", {
        "target_user": target,
        "friendship_status": fs.status,
        "friendship": fs,
        "is_sender": True,
    })


def _clear_friend_request_notifications(recipient, friendship_id):
    """Занулить inbox-уведомления типа friend_request по конкретной заявке."""
    try:
        from django.utils import timezone
        from notifications.models import Notification
        Notification.objects.filter(
            user=recipient,
            kind=Notification.KIND_FRIEND_REQUEST,
            extra__friendship_id=friendship_id,
            read_at__isnull=True,
        ).update(read_at=timezone.now())
    except Exception:
        pass


@login_required
@require_POST
def friend_accept(request, friendship_id):
    fs = get_object_or_404(Friendship, pk=friendship_id, to_user=request.user, status="pending")
    fs.status = "accepted"
    fs.save(update_fields=["status"])
    ActivityEvent.objects.create(
        user=request.user,
        event_type="new_friendship",
        target_user=fs.from_user,
    )
    _clear_friend_request_notifications(request.user, fs.pk)
    return render(request, "social/_friend_btn.html", {
        "target_user": fs.from_user,
        "friendship_status": "accepted",
        "friendship": fs,
        "is_sender": False,
    })


@login_required
@require_POST
def friend_reject(request, friendship_id):
    fs = get_object_or_404(Friendship, pk=friendship_id, to_user=request.user, status="pending")
    fs_pk = fs.pk
    fs.delete()
    _clear_friend_request_notifications(request.user, fs_pk)
    return render(request, "social/_friend_btn.html", {
        "target_user": fs.from_user,
        "friendship_status": None,
        "friendship": None,
        "is_sender": False,
    })


@login_required
@require_POST
def friend_remove(request, user_id):
    target = get_object_or_404(User, pk=user_id)
    fs_ids = list(
        Friendship.objects.filter(
            Q(from_user=request.user, to_user=target)
            | Q(from_user=target, to_user=request.user)
        ).values_list("pk", flat=True)
    )
    Friendship.objects.filter(pk__in=fs_ids).delete()
    for fs_id in fs_ids:
        _clear_friend_request_notifications(request.user, fs_id)
    return render(request, "social/_friend_btn.html", {
        "target_user": target,
        "friendship_status": None,
        "friendship": None,
        "is_sender": False,
    })


@login_required
@require_GET
def friend_list(request):
    friends = get_friends(request.user)
    incoming = Friendship.objects.filter(to_user=request.user, status="pending").select_related("from_user")
    outgoing = Friendship.objects.filter(from_user=request.user, status="pending").select_related("to_user")
    return render(request, "social/friend_list.html", {
        "friends": friends,
        "incoming": incoming,
        "outgoing": outgoing,
    })


# ─── РЕКОМЕНДАЦИЯ КНИГИ ДРУГУ ─────────────────────────────────────────────────

@login_required
@require_POST
def recommend_book(request, book_id):
    book = get_object_or_404(Book, pk=book_id)
    friend_ids = request.POST.getlist("friend_ids")
    message = request.POST.get("message", "").strip()

    friends = get_friends(request.user)
    sent = 0
    for uid in friend_ids:
        if friends.filter(pk=uid).exists():
            _, created = BookRecommendation.objects.get_or_create(
                from_user=request.user,
                to_user_id=uid,
                book=book,
                defaults={"message": message},
            )
            if created:
                ActivityEvent.objects.create(
                    user=request.user,
                    event_type="book_recommend",
                    book=book,
                    target_user_id=uid,
                    metadata={"message": message[:200]},
                )
                sent += 1

    return render(request, "social/_recommend_done.html", {"sent": sent, "book": book})


@login_required
@require_GET
def recommend_friends_partial(request, book_id):
    """HTMX partial: список друзей для модалки рекомендации."""
    book = get_object_or_404(Book, pk=book_id)
    friends = get_friends(request.user)
    return render(request, "social/_recommend_modal_body.html", {
        "book": book,
        "friends": friends,
    })


@login_required
@require_GET
def my_recommendations(request):
    recs = (
        BookRecommendation.objects
        .filter(to_user=request.user)
        .select_related("from_user", "book")
        .prefetch_related("book__authors")
    )
    # Отметить как прочитанные
    recs.filter(is_read=False).update(is_read=True)
    return render(request, "social/my_recommendations.html", {"recs": recs[:50]})


# ─── ЛЕНТА АКТИВНОСТИ ─────────────────────────────────────────────────────────

@login_required
@require_GET
def activity_feed(request):
    mode = request.GET.get("mode", "all")  # "all" или "friends"
    page = int(request.GET.get("page", 1))
    per_page = 20

    fids = friend_ids_set(request.user)

    if mode == "friends":
        events = ActivityEvent.objects.filter(user_id__in=fids)
    else:
        # Все события, но друзья сначала
        friend_events = list(
            ActivityEvent.objects
            .filter(user_id__in=fids)
            .select_related("user", "book", "target_user")
            .prefetch_related("book__authors")
            [:per_page]
        )
        other_events = list(
            ActivityEvent.objects
            .exclude(user_id__in=fids | {request.user.pk})
            .select_related("user", "book", "target_user")
            .prefetch_related("book__authors")
            [:per_page]
        )
        events_list = friend_events + other_events
        events_list = events_list[:per_page]

        ctx = {
            "events": events_list,
            "friend_ids": fids,
            "mode": mode,
            "has_more": len(friend_events) + len(other_events) > per_page,
        }
        tpl = "social/_feed_items.html" if request.htmx else "social/feed.html"
        return render(request, tpl, ctx)

    events = (
        events
        .select_related("user", "book", "target_user")
        .prefetch_related("book__authors")
        [(page - 1) * per_page : page * per_page + 1]
    )
    events_list = list(events)
    has_more = len(events_list) > per_page
    events_list = events_list[:per_page]

    ctx = {
        "events": events_list,
        "friend_ids": fids,
        "mode": mode,
        "has_more": has_more,
        "page": page,
    }
    tpl = "social/_feed_items.html" if request.htmx else "social/feed.html"
    return render(request, tpl, ctx)


# ─── СОВМЕСТНЫЕ РЕКОМЕНДАЦИИ ──────────────────────────────────────────────────

@login_required
@require_GET
def joint_recs(request, friend_id):
    """Книги на пересечении вкусов двух друзей."""
    friend = get_object_or_404(User, pk=friend_id)
    # Проверяем дружбу
    is_friend = Friendship.objects.filter(
        Q(from_user=request.user, to_user=friend, status="accepted") |
        Q(from_user=friend, to_user=request.user, status="accepted")
    ).exists()
    if not is_friend:
        return HttpResponse("Вы не друзья", status=403)

    from books.joint_recommendations import joint_recommendations
    recs = joint_recommendations(request.user, friend, limit=5)

    return render(request, "social/joint_recs.html", {
        "friend": friend,
        "recs": recs,
    })


def unread_counts(user):
    """Количество непрочитанных рекомендаций + заявок в друзья."""
    recs = BookRecommendation.objects.filter(to_user=user, is_read=False).count()
    requests = Friendship.objects.filter(to_user=user, status="pending").count()
    return recs + requests

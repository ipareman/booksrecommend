from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Count, Prefetch, Q
from django.http import Http404, HttpResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from books.models import Book
from social.models import ActivityEvent

from .models import (
    BookClub,
    ClubBook,
    ClubBookVote,
    ClubMembership,
    ClubPoll,
    ClubPollOption,
    ClubPollVote,
)


MANAGER_ROLES = ("owner", "admin")


def _get_membership(club, user):
    if not user or not getattr(user, "is_authenticated", False):
        return None
    return ClubMembership.objects.filter(club=club, user=user).first()


def _assert_club_access(club, user):
    if not club.can_access(user):
        raise Http404()


def _assert_manage_access(club, user):
    membership = get_object_or_404(ClubMembership, club=club, user=user)
    if membership.role not in MANAGER_ROLES:
        raise Http404()
    return membership


def _can_remove_member(actor_membership, target_membership) -> bool:
    if not actor_membership or not target_membership:
        return False
    if actor_membership.club_id != target_membership.club_id:
        return False
    if actor_membership.user_id == target_membership.user_id:
        return False
    if target_membership.role == "owner":
        return False
    if actor_membership.role == "owner":
        return True
    if actor_membership.role == "admin":
        return target_membership.role == "member"
    return False


def _parse_optional_date(raw_value):
    raw_value = (raw_value or "").strip()
    if not raw_value:
        return None
    return parse_date(raw_value)


def _join_club(club, user):
    if club.memberships.count() >= club.max_members:
        return None, False

    membership, created = ClubMembership.objects.get_or_create(
        club=club, user=user, defaults={"role": "member"}
    )
    if created:
        ActivityEvent.objects.create(
            user=user,
            event_type="join_club",
            metadata={"club_name": club.name, "club_id": club.pk},
        )
        from chat.models import ChatParticipant, ChatRoom

        chat_room = ChatRoom.objects.filter(room_type="club", club=club).first()
        if chat_room:
            ChatParticipant.objects.get_or_create(room=chat_room, user=user)
    return membership, created


def _render_books_list(request, club, membership):
    club_books = (
        club.club_books.select_related("book")
        .prefetch_related("book__authors")
        .annotate(votes_count=Count("votes"))
        .order_by("order", "pk")
    )
    current_book = club_books.filter(is_current=True).first()
    schedule_books = [cb for cb in club_books if cb.start_date or cb.end_date]
    user_vote = None
    if request.user.is_authenticated:
        user_vote = (
            ClubBookVote.objects.filter(club=club, user=request.user)
            .values_list("club_book_id", flat=True)
            .first()
        )
    return render(
        request,
        "clubs/_club_books_list.html",
        {
            "club": club,
            "club_books": club_books,
            "current_book": current_book,
            "membership": membership,
            "schedule_books": schedule_books,
            "today": timezone.localdate(),
            "user_book_vote_id": user_vote,
            "member_total": club.memberships.count(),
            "is_manager": bool(membership and membership.role in MANAGER_ROLES),
        },
    )


def _build_polls_queryset(club):
    return (
        club.polls.select_related("created_by")
        .prefetch_related(
            Prefetch(
                "options",
                queryset=ClubPollOption.objects.annotate(votes_count=Count("votes")).prefetch_related(
                    Prefetch(
                        "votes",
                        queryset=ClubPollVote.objects.select_related("user").order_by("created_at"),
                    )
                ),
            ),
            "votes",
        )
        .order_by("-created_at")
    )


def _render_polls_panel(request, club, membership):
    polls = list(_build_polls_queryset(club)[:8])
    my_votes = {}
    if request.user.is_authenticated:
        my_votes = dict(
            ClubPollVote.objects.filter(
                poll__club=club, user=request.user, poll_id__in=[p.pk for p in polls]
            ).values_list("poll_id", "option_id")
        )
    for poll in polls:
        poll.total_votes_count = poll.votes.count()
        poll.user_option_id = my_votes.get(poll.pk)
        poll.can_manage_user = poll.can_manage(request.user)
    return render(
        request,
        "clubs/_polls_panel.html",
        {
            "club": club,
            "membership": membership,
            "polls": polls,
            "my_poll_votes": my_votes,
            "is_manager": bool(membership and membership.role in MANAGER_ROLES),
        },
    )


def _chat_widget_context(request, club, room, membership):
    from chat.models import ChatMessageReaction
    import json as _json

    chat_messages = list(
        room.messages
        .select_related("user", "attached_book")
        .prefetch_related("attached_book__authors", "reactions__user")
        .order_by("-created_at")[:80]
    )
    chat_messages.reverse()
    for m in chat_messages:
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

    mention_candidates = list(
        room.participants
        .exclude(user=request.user)
        .select_related("user")
        .values_list("user__username", flat=True)
    )
    return {
        "room": room,
        "club": club,
        "membership": membership,
        "chat_messages": chat_messages,
        "mention_candidates_json": _json.dumps(mention_candidates, ensure_ascii=False),
        "allowed_emoji_json": _json.dumps(ChatMessageReaction.ALLOWED_EMOJI, ensure_ascii=False),
    }


def clubs_list(request):
    public_clubs = (
        BookClub.objects.filter(is_public=True)
        .annotate(num_members=Count("memberships"))
        .prefetch_related("club_books__book")
    )
    my_club_ids = set()
    my_clubs = []
    if request.user.is_authenticated:
        my_club_ids = set(
            ClubMembership.objects.filter(user=request.user).values_list("club_id", flat=True)
        )
        my_clubs = (
            BookClub.objects.filter(pk__in=my_club_ids)
            .annotate(num_members=Count("memberships"))
            .prefetch_related("club_books__book")
        )
    return render(
        request,
        "clubs/club_list.html",
        {
            "clubs": public_clubs,
            "my_club_ids": my_club_ids,
            "my_clubs": my_clubs,
        },
    )


def club_detail(request, pk):
    club = get_object_or_404(BookClub, pk=pk)
    _assert_club_access(club, request.user)

    memberships = club.memberships.select_related("user").order_by("joined_at")
    membership = _get_membership(club, request.user)
    is_manager = bool(membership and membership.role in MANAGER_ROLES)
    removable_member_ids = set()
    if membership:
        removable_member_ids = {
            ms.user_id for ms in memberships if _can_remove_member(membership, ms)
        }

    chat_room = None
    chat_messages_for_widget = []
    mention_candidates_json = "[]"
    allowed_emoji_json = "[]"
    if membership:
        from chat.models import ChatParticipant, ChatRoom

        chat_room = ChatRoom.objects.filter(room_type="club", club=club).first()
        if not chat_room:
            chat_room = ChatRoom.objects.create(room_type="club", club=club)
        ChatParticipant.objects.get_or_create(room=chat_room, user=request.user)

        widget_ctx = _chat_widget_context(request, club, chat_room, membership)
        chat_messages_for_widget = widget_ctx["chat_messages"]
        mention_candidates_json = widget_ctx["mention_candidates_json"]
        allowed_emoji_json = widget_ctx["allowed_emoji_json"]

    club_books_qs = (
        club.club_books.select_related("book")
        .prefetch_related("book__authors")
        .annotate(votes_count=Count("votes"))
        .order_by("order", "pk")
    )
    club_books = list(club_books_qs)
    current_book = next((cb for cb in club_books if cb.is_current), None)
    schedule_books = [cb for cb in club_books if cb.start_date or cb.end_date]
    meeting_book = club.active_meeting_book()
    vote_candidates = [cb for cb in club_books if not cb.is_current]
    user_book_vote_id = None
    if membership:
        user_book_vote_id = (
            ClubBookVote.objects.filter(club=club, user=request.user)
            .values_list("club_book_id", flat=True)
            .first()
        )

    # Прогресс чтения участниками текущей книги клуба. Группируем по user_id,
    # чтобы при отсутствии прогресса показать «ещё не начал». Сортируем по %
    # — впереди те, кто уже близко к финишу.
    member_progress = []
    if current_book:
        from books.models import ReadingProgress
        member_ids = [ms.user_id for ms in memberships]
        progresses = (
            ReadingProgress.objects.filter(book=current_book.book, user_id__in=member_ids)
            .select_related("user", "current_chapter", "book__text")
        )
        progress_by_user = {p.user_id: p for p in progresses}
        for ms in memberships:
            p = progress_by_user.get(ms.user_id)
            pct = p.percent() if p else 0
            member_progress.append({
                "user": ms.user,
                "percent": pct,
                "current_page": p.current_page if p else 0,
                "started": bool(p and (p.current_page > 0 or pct > 0)),
            })
        member_progress.sort(key=lambda x: (-x["percent"], x["user"].username.lower()))

    polls = list(_build_polls_queryset(club)[:8])
    my_poll_votes = {}
    if membership:
        my_poll_votes = dict(
            ClubPollVote.objects.filter(
                poll__club=club, user=request.user, poll_id__in=[p.pk for p in polls]
            ).values_list("poll_id", "option_id")
        )
    for poll in polls:
        poll.total_votes_count = poll.votes.count()
        poll.user_option_id = my_poll_votes.get(poll.pk)
        poll.can_manage_user = poll.can_manage(request.user)

    invite_url = ""
    if is_manager:
        invite_url = request.build_absolute_uri(
            reverse("club_invite_accept", args=[club.ensure_invite_token()])
        )

    return render(
        request,
        "clubs/club_detail.html",
        {
            "club": club,
            "memberships": memberships,
            "club_books": club_books,
            "current_book": current_book,
            "meeting_book": meeting_book,
            "schedule_books": schedule_books,
            "vote_candidates": vote_candidates,
            "membership": membership,
            "is_manager": is_manager,
            "removable_member_ids": removable_member_ids,
            "chat_room": chat_room,
            "chat_messages_for_widget": chat_messages_for_widget,
            "mention_candidates_json": mention_candidates_json,
            "allowed_emoji_json": allowed_emoji_json,
            "today": timezone.localdate(),
            "user_book_vote_id": user_book_vote_id,
            "member_total": club.memberships.count(),
            "polls": polls,
            "my_poll_votes": my_poll_votes,
            "invite_url": invite_url,
        },
    )


@login_required
def club_book_thread(request, pk, book_id):
    club = get_object_or_404(BookClub, pk=pk)
    _assert_club_access(club, request.user)
    membership = get_object_or_404(ClubMembership, club=club, user=request.user)
    club_book = get_object_or_404(
        club.club_books.select_related("book"),
        book_id=book_id,
    )

    from chat.models import ChatParticipant, ChatRoom, ClubBookThread

    thread = ClubBookThread.objects.select_related("room").filter(club_book=club_book).first()
    if thread:
        room = thread.room
    else:
        room = ChatRoom.objects.create(room_type=ChatRoom.ROOM_CLUB_THREAD)
        ClubBookThread.objects.create(club_book=club_book, room=room)
    participants = [
        ChatParticipant(room=room, user_id=user_id)
        for user_id in club.memberships.values_list("user_id", flat=True)
    ]
    ChatParticipant.objects.bulk_create(participants, ignore_conflicts=True)

    ctx = _chat_widget_context(request, club, room, membership)
    ctx.update({
        "club_book": club_book,
        "title": f"{club.name}: {club_book.book.title}",
    })
    return render(request, "clubs/club_thread.html", ctx)


@login_required
@require_http_methods(["GET", "POST"])
def club_create(request):
    if request.method == "POST":
        name = request.POST.get("name", "").strip()
        description = request.POST.get("description", "").strip()
        max_members_raw = request.POST.get("max_members", "50").strip()
        is_public = request.POST.get("is_public") == "on"
        try:
            max_members = max(2, int(max_members_raw or "50"))
        except ValueError:
            max_members = 50
        if name:
            club = BookClub.objects.create(
                name=name,
                description=description,
                created_by=request.user,
                cover_image=request.FILES.get("cover_image"),
                is_public=is_public,
                max_members=max_members,
            )
            ClubMembership.objects.create(club=club, user=request.user, role="owner")
            return redirect("club_detail", pk=club.pk)
    return render(request, "clubs/club_create.html")


@login_required
@require_POST
def club_join(request, pk):
    club = get_object_or_404(BookClub, pk=pk)
    if not club.is_public:
        return HttpResponse("В приватный клуб можно вступить только по ссылке-приглашению.", status=403)
    membership, _ = _join_club(club, request.user)
    if membership is None:
        return HttpResponse("Клуб заполнен", status=400)
    return redirect("club_detail", pk=club.pk)


@login_required
@require_POST
def club_leave(request, pk):
    club = get_object_or_404(BookClub, pk=pk)
    ClubMembership.objects.filter(club=club, user=request.user).exclude(role="owner").delete()
    from chat.models import ChatParticipant, ChatRoom

    chat_room = ChatRoom.objects.filter(room_type="club", club=club).first()
    if chat_room:
        ChatParticipant.objects.filter(room=chat_room, user=request.user).delete()
    thread_rooms = ChatRoom.objects.filter(
        club_book_thread__in=ClubBookThread.objects.filter(club_book__club=club),
    )
    ChatParticipant.objects.filter(room__in=thread_rooms, user=request.user).delete()
    return redirect("club_detail", pk=club.pk)


@login_required
@require_POST
def club_remove_member(request, pk, user_id):
    club = get_object_or_404(BookClub, pk=pk)
    actor_membership = get_object_or_404(ClubMembership, club=club, user=request.user)
    target_membership = get_object_or_404(
        ClubMembership.objects.select_related("user"),
        club=club,
        user_id=user_id,
    )
    if not _can_remove_member(actor_membership, target_membership):
        return HttpResponse(status=403)

    from chat.models import ChatParticipant, ChatRoom, ClubBookThread

    chat_room = ChatRoom.objects.filter(room_type="club", club=club).first()
    if chat_room:
        ChatParticipant.objects.filter(room=chat_room, user_id=target_membership.user_id).delete()
    thread_rooms = ChatRoom.objects.filter(
        club_book_thread__in=ClubBookThread.objects.filter(club_book__club=club),
    )
    ChatParticipant.objects.filter(room__in=thread_rooms, user_id=target_membership.user_id).delete()

    removed_username = target_membership.user.username
    target_membership.delete()
    messages.success(request, f"Участник @{removed_username} удалён из клуба.")
    return redirect("club_detail", pk=club.pk)


@require_http_methods(["GET", "POST"])
def club_invite_accept(request, token):
    club = get_object_or_404(BookClub, invite_token=token)
    membership = _get_membership(club, request.user)
    if membership:
        return redirect("club_detail", pk=club.pk)
    if request.method == "POST":
        if not request.user.is_authenticated:
            return redirect(f"{reverse('login')}?next={request.path}")
        membership, _ = _join_club(club, request.user)
        if membership is None:
            return HttpResponse("Клуб заполнен", status=400)
        messages.success(request, f"Вы вступили в клуб «{club.name}».")
        return redirect("club_detail", pk=club.pk)
    return render(request, "clubs/club_invite.html", {"club": club})


@login_required
@require_POST
def club_rotate_invite(request, pk):
    club = get_object_or_404(BookClub, pk=pk)
    _assert_manage_access(club, request.user)
    club.rotate_invite_token()
    return redirect("club_detail", pk=club.pk)


@login_required
@require_GET
def club_search_books(request, pk):
    club = get_object_or_404(BookClub, pk=pk)
    _assert_club_access(club, request.user)
    membership = _assert_manage_access(club, request.user)

    q = request.GET.get("q", "").strip()
    existing_ids = set(club.club_books.values_list("book_id", flat=True))

    if q:
        books = (
            Book.objects.filter(Q(title__icontains=q) | Q(authors__name__icontains=q))
            .exclude(pk__in=existing_ids)
            .prefetch_related("authors")
            .distinct()[:20]
        )
    else:
        books = (
            Book.objects.exclude(pk__in=existing_ids)
            .prefetch_related("authors")
            .order_by("-avg_rating")[:20]
        )
    return render(
        request,
        "clubs/_club_search_books.html",
        {"books": books, "club": club, "membership": membership},
    )


@login_required
@require_POST
def club_add_book(request, pk):
    club = get_object_or_404(BookClub, pk=pk)
    membership = _assert_manage_access(club, request.user)

    book = get_object_or_404(Book, pk=request.POST.get("book_id"))
    start_date = _parse_optional_date(request.POST.get("start_date"))
    end_date = _parse_optional_date(request.POST.get("end_date"))
    is_current = request.POST.get("is_current") == "on"

    with transaction.atomic():
        club_book, created = ClubBook.objects.get_or_create(
            club=club,
            book=book,
            defaults={
                "order": club.club_books.count(),
                "start_date": start_date,
                "end_date": end_date,
                "is_current": is_current,
            },
        )
        if not created:
            changed = False
            if start_date != club_book.start_date:
                club_book.start_date = start_date
                changed = True
            if end_date != club_book.end_date:
                club_book.end_date = end_date
                changed = True
            if is_current and not club_book.is_current:
                club_book.is_current = True
                changed = True
            if changed:
                club_book.save()
        if is_current:
            club.club_books.exclude(pk=club_book.pk).update(is_current=False)

    response = _render_books_list(request, club, membership)
    response.content += (
        f'<div id="club-book-option-{book.pk}" hx-swap-oob="delete"></div>'.encode("utf-8")
    )
    return response


@login_required
@require_POST
def club_update_book(request, pk, book_id):
    club = get_object_or_404(BookClub, pk=pk)
    membership = _assert_manage_access(club, request.user)
    club_book = get_object_or_404(ClubBook, club=club, book_id=book_id)

    start_date = _parse_optional_date(request.POST.get("start_date"))
    end_date = _parse_optional_date(request.POST.get("end_date"))
    make_current = request.POST.get("is_current") == "on"

    if start_date and end_date and start_date > end_date:
        return HttpResponseBadRequest("Дата начала позже даты окончания.")

    with transaction.atomic():
        club_book.start_date = start_date
        club_book.end_date = end_date
        club_book.save(update_fields=["start_date", "end_date"])
        if make_current:
            club.club_books.update(is_current=False)
            club_book.is_current = True
            club_book.save(update_fields=["is_current"])

    return _render_books_list(request, club, membership)


@login_required
@require_POST
def club_remove_book(request, pk, book_id):
    club = get_object_or_404(BookClub, pk=pk)
    membership = _assert_manage_access(club, request.user)
    ClubBook.objects.filter(club=club, book_id=book_id).delete()
    return _render_books_list(request, club, membership)


@login_required
@require_POST
def club_set_current_book(request, pk, book_id):
    club = get_object_or_404(BookClub, pk=pk)
    membership = _assert_manage_access(club, request.user)
    with transaction.atomic():
        club.club_books.update(is_current=False)
        ClubBook.objects.filter(club=club, book_id=book_id).update(is_current=True)
    return _render_books_list(request, club, membership)


@login_required
@require_POST
def club_vote_next_book(request, pk, book_id):
    club = get_object_or_404(BookClub, pk=pk)
    membership = get_object_or_404(ClubMembership, club=club, user=request.user)
    club_book = get_object_or_404(ClubBook, club=club, book_id=book_id, is_current=False)

    existing_vote = ClubBookVote.objects.filter(club=club, user=request.user).first()
    if existing_vote and existing_vote.club_book_id == club_book.pk:
        existing_vote.delete()
    else:
        ClubBookVote.objects.update_or_create(
            club=club,
            user=request.user,
            defaults={"club_book": club_book},
        )
    return _render_books_list(request, club, membership)


@login_required
@require_POST
def club_create_poll(request, pk):
    club = get_object_or_404(BookClub, pk=pk)
    membership = get_object_or_404(ClubMembership, club=club, user=request.user)
    question = (request.POST.get("question") or "").strip()[:240]
    options_raw = (request.POST.get("options") or "").splitlines()
    options = [line.strip()[:160] for line in options_raw if line.strip()]

    if not question or len(options) < 2:
        return HttpResponseBadRequest("Нужен вопрос и хотя бы два варианта.")

    with transaction.atomic():
        poll = ClubPoll.objects.create(club=club, question=question, created_by=request.user)
        ClubPollOption.objects.bulk_create(
            [ClubPollOption(poll=poll, text=text, order=index) for index, text in enumerate(options[:8])]
        )
    return _render_polls_panel(request, club, membership)


@login_required
@require_POST
def club_vote_poll(request, pk, poll_id, option_id):
    club = get_object_or_404(BookClub, pk=pk)
    membership = get_object_or_404(ClubMembership, club=club, user=request.user)
    poll = get_object_or_404(ClubPoll, pk=poll_id, club=club)
    if poll.is_closed:
        return HttpResponseBadRequest("Опрос уже закрыт.")
    option = get_object_or_404(ClubPollOption, pk=option_id, poll=poll)

    existing_vote = ClubPollVote.objects.filter(poll=poll, user=request.user).first()
    if existing_vote and existing_vote.option_id == option.pk:
        existing_vote.delete()
    else:
        ClubPollVote.objects.update_or_create(
            poll=poll, user=request.user, defaults={"option": option}
        )
    return _render_polls_panel(request, club, membership)


@login_required
@require_POST
def club_close_poll(request, pk, poll_id):
    club = get_object_or_404(BookClub, pk=pk)
    membership = get_object_or_404(ClubMembership, club=club, user=request.user)
    poll = get_object_or_404(ClubPoll, pk=poll_id, club=club)
    if not poll.can_manage(request.user):
        return HttpResponse(status=403)
    poll.is_closed = True
    poll.save(update_fields=["is_closed"])
    return _render_polls_panel(request, club, membership)


@login_required
@require_POST
def club_delete(request, pk):
    club = get_object_or_404(BookClub, pk=pk)
    get_object_or_404(ClubMembership, club=club, user=request.user, role="owner")
    club.delete()
    return redirect("clubs_list")

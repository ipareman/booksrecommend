from django.shortcuts import get_object_or_404, redirect
from django.contrib.auth.decorators import login_required, user_passes_test
from django.http import HttpResponse, HttpResponseForbidden
from django.template.response import TemplateResponse
from django.views.decorators.http import require_POST, require_GET
from django.db.models import Count, Exists, OuterRef, Prefetch, Sum, Value
from django.db.models.functions import Coalesce
import re
from html.parser import HTMLParser

from .models import (
    Review, ReviewLike,
    Critique, CritiqueCriterion, CritiqueComment, CritiqueCommentVote, CritiqueLike,
)
from books.models import Book
from .tasks import extract_tag_for_review, extract_tag_for_critique
from books.tag_extraction import decrement_tag_from_review

ALLOWED_TAGS = {
    "h1", "h2", "h3", "h4", "h5", "h6",
    "p", "strong", "em", "s", "del", "u", "code", "pre",
    "ul", "ol", "li",
    "blockquote", "a", "img", "br", "hr",
    "figure", "figcaption", "span", "table", "thead", "tbody", "tr", "th", "td",
}
ALLOWED_ATTRS = {
    "a": {"href", "target", "rel"},
    "img": {"src", "alt", "class", "style"},
    "figure": {"class"},
    "span": {"class"},
    "code": {"class"},
    "pre": {"class"},
    "th": {"align"},
    "td": {"align"},
}


class _Sanitizer(HTMLParser):
    """Простой HTML-санитайзер без внешних зависимостей."""

    def __init__(self):
        super().__init__()
        self._out = []

    def handle_starttag(self, tag, attrs):
        if tag not in ALLOWED_TAGS:
            return
        allowed = ALLOWED_ATTRS.get(tag, set())
        safe = []
        for k, v in attrs:
            if k not in allowed:
                continue
            # URL-атрибуты: вырезаем опасные схемы (javascript:, data:, vbscript:)
            if k in ("href", "src"):
                stripped = (v or "").strip().lower()
                if (stripped.startswith("javascript:") or
                    stripped.startswith("vbscript:") or
                    (stripped.startswith("data:") and not stripped.startswith("data:image/"))):
                    continue
            safe.append((k, v))
        attr_str = ""
        if safe:
            parts = []
            for k, v in safe:
                v_esc = (v or "").replace("&", "&amp;").replace('"', "&quot;").replace("<", "&lt;")
                parts.append(f'{k}="{v_esc}"')
            attr_str = " " + " ".join(parts)
        self._out.append(f"<{tag}{attr_str}>")

    def handle_endtag(self, tag):
        if tag in ALLOWED_TAGS:
            self._out.append(f"</{tag}>")

    def handle_data(self, data):
        self._out.append(data.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))

    def get_result(self):
        return "".join(self._out)


def _sanitize_html(html):
    s = _Sanitizer()
    s.feed(html or "")
    return s.get_result()


def _render_markdown(source: str) -> str:
    """Рендерит markdown-текст в безопасный HTML.
    Если библиотека markdown недоступна — fallback на <pre>."""
    if not source:
        return ""
    try:
        import markdown as md
        html = md.markdown(
            source,
            extensions=["extra", "sane_lists", "nl2br"],
            output_format="html",
        )
    except ImportError:
        # Не ломаемся, если зависимость ещё не поставлена — просто оборачиваем исходник.
        from html import escape
        html = f"<pre>{escape(source)}</pre>"
    return _sanitize_html(html)


def _prepare_body(form_data, post) -> tuple[str, str, str]:
    """Из POST-данных формы возвращает (sanitized_html, source, format)
    в зависимости от выбранного редактора."""
    body_format = post.get("body_format", Critique.FORMAT_HTML)
    if body_format == Critique.FORMAT_MARKDOWN:
        source = post.get("body_source", "") or ""
        html = _render_markdown(source)
        return html, source, Critique.FORMAT_MARKDOWN
    # CKEditor: берём уже готовый HTML из form.body и санитайзим
    html = _sanitize_html(form_data.get("body") or "")
    return html, "", Critique.FORMAT_HTML


def _notify_review_status(review, approved: bool) -> None:
    """
    Уведомить автора отзыва:
    - Запись во «входящие» (Notification) — всегда;
    - Telegram → email fallback — сохраняем старую логику.
    """
    profile = getattr(review.user, "profile", None)
    book = review.book

    # DB-уведомление во «входящие» — независимо от Telegram/email
    try:
        from notifications.helpers import emit as _emit_notification
        from notifications.models import Notification as _Notif
        if approved:
            inbox_text = f"Ваш отзыв на «{book.title}» одобрен"
        else:
            inbox_text = f"Ваш отзыв на «{book.title}» отклонён"
        _emit_notification(
            user=review.user,
            kind=_Notif.KIND_REVIEW_MODERATED,
            actor=None,
            target=review,
            text=inbox_text,
            url=f"/books/{book.pk}/#review-{review.pk}",
            extra={
                "review_id": review.pk,
                "book_id": book.pk,
                "approved": bool(approved),
            },
        )
    except Exception:
        pass  # запись в инбокс не должна ломать модерацию

    # Матрица настроек рассылки
    from notifications.models import NotificationSetting
    event = (NotificationSetting.EVENT_REVIEW_APPROVED if approved
             else NotificationSetting.EVENT_REVIEW_REJECTED)
    ch = NotificationSetting.channels_for(event)

    # Telegram / MAX (приоритет над email)
    delivered = False
    if profile:
        from django.conf import settings as conf
        book_url = f"{getattr(conf, 'SITE_URL', '')}/books/{book.pk}/"
        if approved:
            text = (
                f"✅ <b>Ваш отзыв одобрен</b>\n\n"
                f"Книга: <b>{book.title}</b>\n"
                f"<a href='{book_url}'>Открыть</a>"
            )
        else:
            text = (
                f"❌ <b>Ваш отзыв отклонён</b>\n\n"
                f"Книга: <b>{book.title}</b>"
            )
        if ch["telegram"] and profile.telegram_chat_id:
            from notifications.telegram import send_message
            send_message(profile.telegram_chat_id, text)
            delivered = True
        if ch["max"] and profile.max_user_id:
            from notifications.max import send_message as max_send_message
            max_send_message(profile.max_user_id, text)
            delivered = True
        if ch["vk"] and profile.vk_user_id:
            from notifications.vk import send_message as vk_send_message
            vk_send_message(profile.vk_user_id, text)
            delivered = True

    if delivered:
        return

    # Email fallback
    if ch["email"]:
        from notifications.email import send_review_status_email
        send_review_status_email(review.user, book, approved)


@login_required
def review_create(request, book_id):
    book = get_object_or_404(Book, pk=book_id)
    if request.method != "POST":
        return HttpResponse(status=405)

    rating = int(request.POST.get("rating", 0))
    text   = request.POST.get("text", "").strip()

    if not (1 <= rating <= 5) or not text:
        return TemplateResponse(request, "reviews/_review_form.html",
                                {"book": book, "error": "Укажите оценку и текст."})

    Review.objects.get_or_create(
        user=request.user, book=book,
        defaults={"rating": rating, "text": text},
    )
    return TemplateResponse(request, "reviews/_review_done.html")


@user_passes_test(lambda u: u.is_staff)
def review_moderate(request, review_id):
    review = get_object_or_404(Review, pk=review_id)
    action = request.POST.get("action")

    from analytics.models import ModerationLog
    if action == "approve":
        review.status = Review.APPROVED
        review.save(update_fields=["status"])
        extract_tag_for_review.delay(review.pk)
        _notify_review_status(review, approved=True)
        ModerationLog.log(request.user, "review_approve", target=review,
                          note=f'"{review.text[:80]}" by {review.user.username}')

    elif action == "reject":
        _notify_review_status(review, approved=False)
        # Логируем ДО удаления, чтобы target_repr сформировался правильно
        ModerationLog.log(request.user, "review_reject", target=review,
                          note=f'"{review.text[:80]}" by {review.user.username}')
        # Декрементируем тег если он уже был извлечён (повторное модерирование)
        if review.extracted_tag:
            review._extracted_tag = review.extracted_tag
            decrement_tag_from_review(review)
        review.delete()

    return HttpResponse("")


@login_required
@require_POST
def review_delete(request, review_id):
    review = get_object_or_404(Review.objects.select_related("book"), pk=review_id)
    if not request.user.is_staff:
        return HttpResponseForbidden("Только администратор может удалить отзыв.")

    if review.extracted_tag:
        review._extracted_tag = review.extracted_tag
        decrement_tag_from_review(review)
    review.delete()
    return HttpResponse("")


def reviews_page(request, book_id):
    """HTMX: пагинация отзывов книги (по 5 штук)."""
    from django.db.models import Count, Exists, OuterRef
    REVIEWS_PER_PAGE = 5
    book = get_object_or_404(Book, pk=book_id)
    page = int(request.GET.get("page", 1))
    offset = (page - 1) * REVIEWS_PER_PAGE

    _like_filter = (
        ReviewLike.objects.filter(review=OuterRef("pk"), user=request.user)
        if request.user.is_authenticated
        else ReviewLike.objects.none()
    )
    qs = (
        Review.objects
        .filter(book=book, status=Review.APPROVED)
        .select_related("user", "user__profile")
        .annotate(
            likes_count=Count("likes", distinct=True),
            user_liked=Exists(_like_filter),
        )
        .order_by("-likes_count", "-created_at")
    )
    total = qs.count()
    reviews = qs[offset:offset + REVIEWS_PER_PAGE]
    has_more = (offset + REVIEWS_PER_PAGE) < total

    return TemplateResponse(request, "reviews/_review_list.html", {
        "reviews": reviews,
        "book": book,
        "has_more_reviews": has_more,
        "next_page": page + 1,
    })


@login_required
@require_POST
def review_like(request, review_id):
    """HTMX: поставить / снять лайк на одобренном отзыве."""
    review = get_object_or_404(Review, pk=review_id, status=Review.APPROVED)
    like, created = ReviewLike.objects.get_or_create(user=request.user, review=review)
    if not created:
        like.delete()
        liked = False
    else:
        liked = True
    likes_count = review.likes.count()
    return TemplateResponse(request, "reviews/_like_btn.html", {
        "review": review, "liked": liked, "likes_count": likes_count,
    })


# ═══════════════════════════════════════════════════════════════════════════════
# РЕЦЕНЗИИ
# ═══════════════════════════════════════════════════════════════════════════════

@login_required
def critique_create(request, book_id):
    """GET: форма рецензии. POST: создать рецензию + критерии."""
    from .forms import CritiqueForm
    book = get_object_or_404(Book, pk=book_id)

    if request.method == "GET":
        form = CritiqueForm()
        return TemplateResponse(request, "reviews/critique_form.html", {
            "book": book, "form": form,
        })

    form = CritiqueForm(request.POST, request.FILES)
    if not form.is_valid():
        return TemplateResponse(request, "reviews/critique_form.html", {
            "book": book, "form": form, "error": "Заполните обязательные поля.",
        })

    critique = form.save(commit=False)
    critique.user = request.user
    critique.book = book
    critique.body, critique.body_source, critique.body_format = _prepare_body(
        form.cleaned_data, request.POST,
    )
    critique.save()

    # Создаём критерии из динамических полей
    i = 0
    while True:
        name = request.POST.get(f"criterion_name_{i}", "").strip()
        rating_raw = request.POST.get(f"criterion_rating_{i}", "")
        if not name:
            break
        try:
            rating = int(rating_raw)
            if 1 <= rating <= 5:
                CritiqueCriterion.objects.create(critique=critique, name=name, rating=rating)
        except (ValueError, TypeError):
            pass
        i += 1

    return redirect("critique_detail", pk=critique.pk)


@login_required
def critique_edit(request, pk):
    """GET: предзаполненная форма. POST: обновить рецензию."""
    from .forms import CritiqueForm
    critique = get_object_or_404(Critique, pk=pk)
    if request.user != critique.user:
        return HttpResponseForbidden("Только автор может редактировать рецензию.")

    if request.method == "GET":
        form = CritiqueForm(instance=critique)
        return TemplateResponse(request, "reviews/critique_form.html", {
            "book": critique.book, "form": form, "critique": critique, "editing": True,
        })

    form = CritiqueForm(request.POST, request.FILES, instance=critique)
    if not form.is_valid():
        return TemplateResponse(request, "reviews/critique_form.html", {
            "book": critique.book, "form": form, "critique": critique, "editing": True,
            "error": "Заполните обязательные поля.",
        })

    critique = form.save(commit=False)
    critique.body, critique.body_source, critique.body_format = _prepare_body(
        form.cleaned_data, request.POST,
    )
    critique.status = Critique.PENDING  # после редактирования — снова на модерацию
    critique.save()

    # Пересоздаём критерии
    critique.criteria.all().delete()
    i = 0
    while True:
        name = request.POST.get(f"criterion_name_{i}", "").strip()
        rating_raw = request.POST.get(f"criterion_rating_{i}", "")
        if not name:
            break
        try:
            rating = int(rating_raw)
            if 1 <= rating <= 5:
                CritiqueCriterion.objects.create(critique=critique, name=name, rating=rating)
        except (ValueError, TypeError):
            pass
        i += 1

    return redirect("critique_detail", pk=critique.pk)


def critique_detail(request, pk):
    """Полная страница рецензии с критериями и комментариями."""
    critique = get_object_or_404(
        Critique.objects.select_related("user", "user__profile", "book").prefetch_related("criteria"),
        pk=pk,
    )

    # Лайк текущего пользователя
    liked = False
    likes_count = critique.likes.count()
    if request.user.is_authenticated:
        liked = CritiqueLike.objects.filter(user=request.user, critique=critique).exists()

    # Комментарии с голосами
    sort = request.GET.get("sort", "newest")
    comments_qs = (
        CritiqueComment.objects
        .filter(critique=critique, parent__isnull=True)
        .select_related("user", "user__profile")
        .prefetch_related(Prefetch(
            "replies",
            queryset=CritiqueComment.objects
            .select_related("user", "user__profile")
            .annotate(vote_score=Coalesce(Sum("votes__value"), Value(0)))
            .order_by("created_at"),
        ))
        .annotate(
            vote_score=Coalesce(Sum("votes__value"), Value(0)),
        )
    )

    if sort == "oldest":
        comments_qs = comments_qs.order_by("created_at")
    elif sort == "top":
        comments_qs = comments_qs.order_by("-vote_score", "-created_at")
    else:
        comments_qs = comments_qs.order_by("-created_at")

    # Аннотируем голоса пользователя
    user_votes = {}
    if request.user.is_authenticated:
        comment_ids = list(comments_qs.values_list("pk", flat=True))
        reply_ids = list(
            CritiqueComment.objects
            .filter(parent_id__in=comment_ids)
            .values_list("pk", flat=True)
        )
        all_ids = comment_ids + reply_ids
        user_votes = dict(
            CritiqueCommentVote.objects
            .filter(user=request.user, comment_id__in=all_ids)
            .values_list("comment_id", "value")
        )

    return TemplateResponse(request, "reviews/critique_detail.html", {
        "critique": critique,
        "liked": liked,
        "likes_count": likes_count,
        "comments": comments_qs,
        "user_votes": user_votes,
        "sort": sort,
    })


@user_passes_test(lambda u: u.is_staff)
def critique_moderate(request, pk):
    """HTMX POST: approve/reject рецензии."""
    critique = get_object_or_404(Critique, pk=pk)
    action = request.POST.get("action")

    from analytics.models import ModerationLog
    if action == "approve":
        critique.status = Critique.APPROVED
        critique.save(update_fields=["status"])
        extract_tag_for_critique.delay(critique.pk)
        _notify_critique_status(critique, approved=True)
        ModerationLog.log(request.user, "critique_approve", target=critique,
                          note=f'"{critique.title[:80]}" by {critique.user.username}')

    elif action == "reject":
        _notify_critique_status(critique, approved=False)
        ModerationLog.log(request.user, "critique_reject", target=critique,
                          note=f'"{critique.title[:80]}" by {critique.user.username}')
        if critique.extracted_tag:
            from books.tag_extraction import decrement_tag_from_review
            critique._extracted_tag = critique.extracted_tag
            decrement_tag_from_review(critique)
        critique.delete()

    return HttpResponse("")


@login_required
@require_POST
def critique_delete(request, pk):
    critique = get_object_or_404(Critique.objects.select_related("book"), pk=pk)
    if not request.user.is_staff:
        return HttpResponseForbidden("Только администратор может удалить рецензию.")

    book_id = critique.book_id
    if critique.extracted_tag:
        critique._extracted_tag = critique.extracted_tag
        decrement_tag_from_review(critique)
    critique.delete()

    if request.headers.get("HX-Request") == "true":
        return HttpResponse("")
    return redirect("book_detail", pk=book_id)


def _notify_critique_status(critique, approved: bool):
    """Уведомить автора рецензии: Telegram → email fallback."""
    profile = getattr(critique.user, "profile", None)
    book = critique.book

    # Матрица настроек рассылки
    from notifications.models import NotificationSetting
    event = (NotificationSetting.EVENT_CRITIQUE_APPROVED if approved
             else NotificationSetting.EVENT_CRITIQUE_REJECTED)
    ch = NotificationSetting.channels_for(event)

    delivered = False
    if profile:
        from django.conf import settings as conf
        book_url = f"{getattr(conf, 'SITE_URL', '')}/books/{book.pk}/"
        if approved:
            text = (
                f"✅ <b>Ваша рецензия одобрена</b>\n\n"
                f"«{critique.title}»\n"
                f"Книга: <b>{book.title}</b>\n"
                f"<a href='{book_url}'>Открыть</a>"
            )
        else:
            text = (
                f"❌ <b>Ваша рецензия отклонена</b>\n\n"
                f"«{critique.title}»\nКнига: <b>{book.title}</b>"
            )
        if ch["telegram"] and profile.telegram_chat_id:
            from notifications.telegram import send_message
            send_message(profile.telegram_chat_id, text)
            delivered = True
        if ch["max"] and profile.max_user_id:
            from notifications.max import send_message as max_send_message
            max_send_message(profile.max_user_id, text)
            delivered = True
        if ch["vk"] and profile.vk_user_id:
            from notifications.vk import send_message as vk_send_message
            vk_send_message(profile.vk_user_id, text)
            delivered = True

    if delivered:
        return

    if ch["email"]:
        from notifications.email import send_review_status_email
        send_review_status_email(critique.user, book, approved)


@login_required
@require_POST
def critique_like(request, pk):
    """HTMX: toggle лайка на рецензии."""
    critique = get_object_or_404(Critique, pk=pk, status=Critique.APPROVED)
    like, created = CritiqueLike.objects.get_or_create(user=request.user, critique=critique)
    if not created:
        like.delete()
        liked = False
    else:
        liked = True
    likes_count = critique.likes.count()
    return TemplateResponse(request, "reviews/_critique_like_btn.html", {
        "critique": critique, "liked": liked, "likes_count": likes_count,
    })


def critiques_page(request, book_id):
    """HTMX: пагинация рецензий книги (по 5)."""
    CRITIQUES_PER_PAGE = 5
    book = get_object_or_404(Book, pk=book_id)
    page = int(request.GET.get("page", 1))
    offset = (page - 1) * CRITIQUES_PER_PAGE

    qs = (
        Critique.objects
        .filter(book=book, status=Critique.APPROVED)
        .select_related("user", "user__profile")
        .prefetch_related("criteria")
        .annotate(likes_count=Count("likes", distinct=True))
        .order_by("-likes_count", "-created_at")
    )
    total = qs.count()
    critiques = qs[offset:offset + CRITIQUES_PER_PAGE]
    has_more = (offset + CRITIQUES_PER_PAGE) < total

    return TemplateResponse(request, "reviews/_critique_list.html", {
        "critiques": critiques,
        "book": book,
        "has_more_critiques": has_more,
        "next_page": page + 1,
    })


# ── КОММЕНТАРИИ К РЕЦЕНЗИЯМ ────────────────────────────────────────────────

@login_required
@require_POST
def comment_create(request, critique_id):
    """Создать комментарий или ответ на комментарий."""
    critique = get_object_or_404(Critique, pk=critique_id, status=Critique.APPROVED)
    text = request.POST.get("text", "").strip()
    if not text:
        return HttpResponse(status=400)

    parent_id = request.POST.get("parent_id")
    parent = None
    if parent_id:
        parent = CritiqueComment.objects.filter(
            pk=parent_id, critique=critique,
        ).first()

    comment = CritiqueComment.objects.create(
        critique=critique, user=request.user, parent=parent, text=text,
    )

    return TemplateResponse(request, "reviews/_comment.html", {
        "comment": comment, "critique": critique, "user_votes": {},
    })


@login_required
@require_POST
def comment_edit(request, pk):
    """Редактировать свой комментарий."""
    comment = get_object_or_404(CritiqueComment, pk=pk)
    if request.user != comment.user:
        return HttpResponseForbidden("Только автор может редактировать.")

    text = request.POST.get("text", "").strip()
    if not text:
        return HttpResponse(status=400)

    comment.text = text
    comment.save(update_fields=["text", "updated_at"])

    return TemplateResponse(request, "reviews/_comment.html", {
        "comment": comment, "critique": comment.critique, "user_votes": {},
    })


@login_required
@require_POST
def comment_delete(request, pk):
    """Удалить свой комментарий (и все вложенные)."""
    comment = get_object_or_404(CritiqueComment, pk=pk)
    if request.user != comment.user and not request.user.is_staff:
        return HttpResponseForbidden("Только автор может удалить.")
    comment.delete()
    return HttpResponse("")


@login_required
@require_POST
def comment_vote(request, pk):
    """HTMX: голосование +1/-1 за комментарий."""
    comment = get_object_or_404(CritiqueComment, pk=pk)
    value_raw = request.POST.get("value", "")
    try:
        value = int(value_raw)
        if value not in (1, -1):
            return HttpResponse(status=400)
    except (ValueError, TypeError):
        return HttpResponse(status=400)

    existing = CritiqueCommentVote.objects.filter(user=request.user, comment=comment).first()
    if existing:
        if existing.value == value:
            existing.delete()  # toggle off
            user_vote = 0
        else:
            existing.value = value
            existing.save(update_fields=["value"])
            user_vote = value
    else:
        CritiqueCommentVote.objects.create(user=request.user, comment=comment, value=value)
        user_vote = value

    score = CritiqueCommentVote.objects.filter(comment=comment).aggregate(
        s=Coalesce(Sum("value"), Value(0))
    )["s"]

    return TemplateResponse(request, "reviews/_comment_votes.html", {
        "comment": comment, "score": score, "user_vote": user_vote,
    })


def comments_page(request, critique_id):
    """HTMX: пагинация комментариев."""
    COMMENTS_PER_PAGE = 10
    critique = get_object_or_404(Critique, pk=critique_id)
    page = int(request.GET.get("page", 1))
    sort = request.GET.get("sort", "newest")
    offset = (page - 1) * COMMENTS_PER_PAGE

    qs = (
        CritiqueComment.objects
        .filter(critique=critique, parent__isnull=True)
        .select_related("user", "user__profile")
        .prefetch_related(Prefetch(
            "replies",
            queryset=CritiqueComment.objects
            .select_related("user", "user__profile")
            .annotate(vote_score=Coalesce(Sum("votes__value"), Value(0)))
            .order_by("created_at"),
        ))
        .annotate(vote_score=Coalesce(Sum("votes__value"), Value(0)))
    )

    if sort == "oldest":
        qs = qs.order_by("created_at")
    elif sort == "top":
        qs = qs.order_by("-vote_score", "-created_at")
    else:
        qs = qs.order_by("-created_at")

    total = qs.count()
    comments = qs[offset:offset + COMMENTS_PER_PAGE]
    has_more = (offset + COMMENTS_PER_PAGE) < total

    user_votes = {}
    if request.user.is_authenticated:
        comment_ids = [c.pk for c in comments]
        reply_ids = list(
            CritiqueComment.objects
            .filter(parent_id__in=comment_ids)
            .values_list("pk", flat=True)
        )
        user_votes = dict(
            CritiqueCommentVote.objects
            .filter(user=request.user, comment_id__in=comment_ids + reply_ids)
            .values_list("comment_id", "value")
        )

    return TemplateResponse(request, "reviews/_comments_section.html", {
        "comments": comments,
        "critique": critique,
        "user_votes": user_votes,
        "has_more_comments": has_more,
        "next_page": page + 1,
        "sort": sort,
    })

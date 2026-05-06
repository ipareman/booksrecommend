from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login, logout
from django.contrib.auth.models import User
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm, PasswordChangeForm
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.tokens import default_token_generator
from django.contrib import messages
from django.core.mail import send_mail
from django.http import HttpResponse, HttpResponseBadRequest, JsonResponse
from django.db.models import Count, Q, Avg, Sum
from django.utils import timezone
from django.utils.http import urlsafe_base64_encode, urlsafe_base64_decode
from django.utils.encoding import force_bytes, force_str
from django.views.decorators.http import require_GET, require_POST, require_http_methods
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.cache import never_cache
from django.core.exceptions import PermissionDenied
from django.core.cache import cache
from django.conf import settings as conf
from django.template.loader import render_to_string
from functools import wraps

import csv
import json
import os
import re
import subprocess
from celery.result import AsyncResult

from .models import (
    UserProfile, AuthorSubscription, Achievement, AVATAR_GRADIENTS,
    check_achievements, get_achievements_progress,
)
from books.models import (
    Book, UserList, Store, BookStore, Genre, Author, ReadingProgress,
    BookEdition, BookNote, Publisher, Series, Language,
)
from reviews.models import Review, Critique
from search.models import SearchHistory
from books.ai_recommendations import load_from_cache, invalidate as invalidate_ai_cache
from books.recommendations import (
    recommended_for_user, build_explain_context, explain_match,
    diagnose_recommendations, build_ai_reason_bullets,
)
# ↑ build_ai_reason_bullets используется и в profile, и в user_profile_public
from .tasks import generate_ai_recommendations_task
from .profile_data import build_public_profile_context


# ─── RATE LIMITING ────────────────────────────────────────────────────────────

def rate_limit(key_prefix, max_requests=10, period=60):
    """Простой rate-limiter через Django cache. Без внешних зависимостей."""
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped(request, *args, **kwargs):
            if request.user.is_authenticated:
                rl_key = f"rl:{key_prefix}:{request.user.pk}"
            else:
                rl_key = f"rl:{key_prefix}:{request.META.get('REMOTE_ADDR', '?')}"
            count = cache.get(rl_key, 0)
            if count >= max_requests:
                return HttpResponse(
                    "Слишком много запросов. Попробуйте позже.",
                    status=429,
                )
            cache.set(rl_key, count + 1, period)
            return view_func(request, *args, **kwargs)
        return _wrapped
    return decorator

# ─── ДЕКОРАТОРЫ ───────────────────────────────────────────────────────────────

def staff_required(view_func):
    """Декоратор, разрешающий доступ только персоналу (staff)."""
    def _wrapped(request, *args, **kwargs):
        if not request.user.is_staff:
            raise PermissionDenied
        return view_func(request, *args, **kwargs)
    return _wrapped

# ─── ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ─────────────────────────────────────────────────

def _get_user_profile(user):
    """Возвращает профиль пользователя (создаёт при необходимости)."""
    profile, _ = UserProfile.objects.get_or_create(user=user)
    return profile

def _invalidate_ai_cache(user_id):
    """Инвалидирует кеш AI-рекомендаций пользователя."""
    invalidate_ai_cache(user_id)

def _render_lists_panel(request, user):
    """Рендерит частичный шаблон со списками пользователя."""
    lists = UserList.objects.filter(user=user).prefetch_related("books__authors")
    return render(request, "users/_lists_panel.html", {"lists": lists})

def _get_task_status(task_id):
    """Проверяет готовность задачи Celery."""
    if not task_id:
        return True, None
    result = AsyncResult(task_id)
    return result.ready(), result

# ─── AUTH ─────────────────────────────────────────────────────────────────────

@require_http_methods(["GET", "POST"])
def register(request):
    if request.user.is_authenticated:
        return redirect("home")
    form = UserCreationForm(request.POST or None)
    consent_error = request.method == "POST" and request.POST.get("personal_data_consent") != "on"
    if request.method == "POST" and form.is_valid() and not consent_error:
        email = request.POST.get("email", "").strip()
        user = form.save(commit=False)
        user.email = email

        from ai_admin.models import AIConfig
        require_verification = AIConfig.get().require_email_verification

        user.is_active = not require_verification
        user.save()
        profile = _get_user_profile(user)
        if not require_verification:
            if hasattr(profile, "email_verified"):
                profile.email_verified = True
                profile.save(update_fields=["email_verified"])
            login(request, user)
            return redirect("onboarding")
        _send_verification_email(user, request)
        return render(request, "users/email_verify_sent.html", {"email": email})
    return render(request, "users/register.html", {
        "form": form,
        "email_value": request.POST.get("email", "") if request.method == "POST" else "",
        "consent_error": consent_error,
        "consent_checked": request.POST.get("personal_data_consent") == "on",
    })


# def _send_verification_email(user, request):
#     uid = urlsafe_base64_encode(force_bytes(user.pk))
#     token = default_token_generator.make_token(user)
#     link = request.build_absolute_uri(f"/users/verify-email/{uid}/{token}/")
#     send_mail(
#         subject="Подтвердите email — Строка",
#         message=f"Здравствуйте, {user.username}!\n\nПодтвердите email по ссылке:\n{link}",
#         from_email=conf.DEFAULT_FROM_EMAIL,
#         recipient_list=[user.email],
#         fail_silently=True,
#     )

import resend
from django.conf import settings as conf

def _send_verification_email(user, request):
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = default_token_generator.make_token(user)
    link = request.build_absolute_uri(f"/users/verify-email/{uid}/{token}/")
    resend.api_key = conf.RESEND_API_KEY
    try:
        resend.Emails.send({
            "from": conf.DEFAULT_FROM_EMAIL,
            "to": [user.email],
            "subject": "Подтвердите email — Строка",
            "text": f"Здравствуйте, {user.username}!\n\nПодтвердите email:\n{link}",
        })
    except Exception as e:
        print(f"[email] Resend error: {e}")


def verify_email(request, uidb64, token):
    try:
        uid = force_str(urlsafe_base64_decode(uidb64))
        user = User.objects.get(pk=uid)
    except (TypeError, ValueError, OverflowError, User.DoesNotExist):
        user = None
    if user and default_token_generator.check_token(user, token):
        user.is_active = True
        user.save(update_fields=["is_active"])
        profile = _get_user_profile(user)
        profile.email_verified = True
        profile.save(update_fields=["email_verified"])
        login(request, user)
        messages.success(request, "Email подтверждён!")
        return redirect("onboarding")
    return render(request, "users/email_verify_invalid.html")

@require_http_methods(["GET", "POST"])
def user_login(request):
    if request.user.is_authenticated:
        return redirect("home")
    form = AuthenticationForm(request, request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.get_user()
        profile = getattr(user, "profile", None)
        if profile and profile.is_currently_blocked:
            messages.error(request, "Ваш аккаунт заблокирован.")
            return render(request, "users/login.html", {"form": form})
        login(request, user)
        next_url = request.GET.get("next", "")
        if not next_url:
            profile = getattr(user, "profile", None)
            if profile and not profile.onboarding_done:
                return redirect("onboarding")
        return redirect(next_url or "home")
    return render(request, "users/login.html", {"form": form})

@require_POST
def user_logout(request):
    logout(request)
    return redirect("home")

# ─── ОНБОРДИНГ ────────────────────────────────────────────────────────────────

@login_required
@require_http_methods(["GET", "POST"])
def onboarding(request):
    """
    Онбординг-визард в 3 шага: жанры → авторы → книги-эталоны.
    «Книги-эталоны» (cold-start seed) попадают в дефолтный список «Любимые»
    с sentiment_tag=positive — этого достаточно, чтобы система рекомендаций
    начала персонализировать выдачу с первого захода.
    """
    profile = _get_user_profile(request.user)

    if request.method == "POST":
        genre_ids = request.POST.getlist("genres")
        author_ids = request.POST.getlist("authors")
        book_ids = request.POST.getlist("books")

        profile.favorite_genres.set(Genre.objects.filter(pk__in=genre_ids))
        profile.favorite_authors.set(Author.objects.filter(pk__in=author_ids))

        # Книги-эталоны → список «Любимые» (positive). Создаём, если нет.
        if book_ids:
            favorites, _ = UserList.objects.get_or_create(
                user=request.user, name="Любимые",
                defaults={"sentiment_tag": "positive", "is_default": False},
            )
            # Если у юзера уже был такой список с другим sentiment — не трогаем.
            books = Book.objects.filter(pk__in=book_ids)
            favorites.books.add(*books)

        profile.onboarding_done = True
        profile.save(update_fields=["onboarding_done"])
        return redirect("home")

    selected_genre_ids = list(profile.favorite_genres.values_list("pk", flat=True))
    selected_author_ids = list(profile.favorite_authors.values_list("pk", flat=True))

    # Уже выбранные «эталонные» книги (если юзер возвращается в онбординг)
    selected_book_ids = list(
        UserList.objects
        .filter(user=request.user, name="Любимые", sentiment_tag="positive")
        .values_list("books__pk", flat=True)
    )

    # Курированный набор книг для cold-start: берём 30 самых популярных
    # с обложкой (без неё карточка выглядит пусто).
    onboarding_books = list(
        Book.objects
        .exclude(cover_image="")
        .annotate(_rev_count=Count("reviews", distinct=True))
        .filter(_rev_count__gte=1)
        .order_by("-avg_rating", "-_rev_count")[:30]
        .prefetch_related("authors")
    )

    ctx = {
        "onboarding_genres": Genre.objects.order_by("name"),
        "onboarding_authors": (
            Author.objects
            .annotate(book_count=Count("books"))
            .filter(book_count__gt=0)
            .order_by("-book_count")[:40]
        ),
        "onboarding_books": onboarding_books,
        "selected_genre_ids": selected_genre_ids,
        "selected_author_ids": selected_author_ids,
        "selected_book_ids": selected_book_ids,
        "is_returning": profile.onboarding_done,
    }
    return render(request, "users/onboarding.html", ctx)

# ─── ПРОФИЛЬ ──────────────────────────────────────────────────────────────────

@login_required
@require_http_methods(["GET", "POST"])
def profile(request):
    user = request.user
    lists = UserList.objects.filter(user=user).prefetch_related("books__authors")

    if request.method == "POST" and "telegram_username" in request.POST:
        username = request.POST.get("telegram_username", "").strip().lstrip("@")
        profile_obj = _get_user_profile(user)
        profile_obj.telegram_username = username
        profile_obj.save(update_fields=["telegram_username"])
        messages.success(request, "Telegram сохранён.")
        return redirect("profile")

    # AI-рекомендации из кеша
    ai_recs = load_from_cache(user.pk)

    # Обычные рекомендации
    try:
        recs = recommended_for_user(user, limit=10)
    except Exception:
        recs = []

    # Диагностика — почему рекомендации могут быть пусты / почему AI нет
    rec_diag = diagnose_recommendations(user, produced_count=len(recs))
    ai_reason_bullets = build_ai_reason_bullets(user, ai_recs)

    # Статистика пользователя
    total_books = UserList.objects.filter(user=user).aggregate(
        total=Count("books", distinct=True)
    )["total"] or 0

    total_pages = ReadingProgress.objects.filter(user=user).aggregate(
        total=Sum("current_page")
    )["total"] or 0

    top_genres = (
        Genre.objects
        .filter(books__in_lists__user=user, books__in_lists__sentiment_tag="positive")
        .annotate(cnt=Count("books"))
        .order_by("-cnt")[:3]
    )

    avg_rating_given = (
        Review.objects
        .filter(user=user, status=Review.APPROVED)
        .aggregate(avg=Avg("rating"))["avg"]
    )

    # Достижения (проверяем новые при каждом заходе в профиль)
    new_achievements = check_achievements(user)
    if new_achievements:
        names = [dict(Achievement.TYPES).get(a, a) for a in new_achievements]
        messages.success(request, f"Новое достижение: {', '.join(names)}")
    achievements = get_achievements_progress(user)

    my_reviews = Review.objects.filter(user=user).select_related("book")[:30]

    # Понравившиеся подборки — пользователь поставил ♥ этим коллекциям
    from curated.models import Collection
    liked_collections = (
        Collection.objects
        .filter(likes__user=user, is_published=True)
        .prefetch_related("items__book")
        .annotate(num_books=Count("items", distinct=True),
                  num_likes=Count("likes", distinct=True))
        .order_by("-likes__created_at")
    )

    # Приватные заметки к выделенным фрагментам — группируем по книге, чтобы
    # на UI был аккордеон «Книга → её заметки», иначе при 100+ заметках длинная
    # сплошная лента нечитаема. Защищаемся от падения, если миграция 0012 ещё
    # не накачена в окружении (dev / прод после деплоя).
    notes_by_book = []
    try:
        recent_notes = (
            BookNote.objects.filter(user=user)
            .select_related("book", "chapter")
            .order_by("-created_at")[:200]
        )
        grouped = {}
        for n in recent_notes:
            grouped.setdefault(n.book_id, {"book": n.book, "items": []})["items"].append(n)
        notes_by_book = list(grouped.values())
    except Exception:
        notes_by_book = []

    # Активные сессии пользователя
    from django.contrib.sessions.models import Session
    current_session_key = request.session.session_key
    now = timezone.now()
    active_sessions = []
    for s in Session.objects.filter(expire_date__gt=now).order_by("-expire_date"):
        data = s.get_decoded()
        if data.get("_auth_user_id") == str(user.pk):
            ua_str = data.get("_session_ua", "")
            ip = data.get("_session_ip", "")
            active_sessions.append({
                "session_key": s.session_key,
                "expire_date": s.expire_date,
                "is_current": s.session_key == current_session_key,
                "ua": ua_str,
                "ip": ip,
            })

    ctx = {
        "lists": lists,
        "my_reviews": my_reviews,
        "search_history": SearchHistory.objects.filter(user=user)[:20],
        "recommendations": recs,
        "ai_recs": ai_recs,
        "rec_diag": rec_diag,
        "ai_reason_bullets": ai_reason_bullets,
        "subscriptions": user.author_subscriptions.select_related("author"),
        "total_books": total_books,
        "total_pages": total_pages,
        "top_genres": top_genres,
        "avg_rating_given": avg_rating_given,
        "achievements": achievements,
        "liked_collections": liked_collections,
        "notes_by_book": notes_by_book,
        "active_sessions": active_sessions,
    }
    return render(request, "users/profile.html", ctx)

@login_required
@require_POST
def session_terminate(request):
    """Завершить конкретную сессию пользователя (не текущую)."""
    from django.contrib.sessions.models import Session
    session_key = request.POST.get("session_key", "").strip()
    if not session_key or session_key == request.session.session_key:
        return HttpResponseBadRequest("invalid")
    try:
        s = Session.objects.get(session_key=session_key)
        data = s.get_decoded()
        if data.get("_auth_user_id") == str(request.user.pk):
            s.delete()
    except Session.DoesNotExist:
        pass
    return JsonResponse({"ok": True})


@login_required
@require_POST
def sessions_terminate_all(request):
    """Завершить все сессии кроме текущей."""
    from django.contrib.sessions.models import Session
    current_key = request.session.session_key
    now = timezone.now()
    for s in Session.objects.filter(expire_date__gt=now):
        if s.session_key == current_key:
            continue
        data = s.get_decoded()
        if data.get("_auth_user_id") == str(request.user.pk):
            s.delete()
    return JsonResponse({"ok": True})


@login_required
@require_POST
@rate_limit("ai_recs", max_requests=3, period=300)
def ai_recs_refresh(request, user_id=None):
    """Запускает генерацию AI-рекомендаций и возвращает блок с поллингом."""
    task = generate_ai_recommendations_task.delay(request.user.pk)
    request.session["ai_recs_task"] = task.id
    return render(request, "users/_ai_recs_block.html", {
        "pending": True, "task_id": task.id
    })

@login_required
@require_GET
def ai_recs_status(request):
    """Возвращает состояние задачи генерации AI-рекомендаций."""
    task_id = request.GET.get("task_id") or request.session.get("ai_recs_task")
    done, _ = _get_task_status(task_id)

    if done:
        ai_recs = load_from_cache(request.user.pk)
        return render(request, "users/_ai_recs_block.html", {
            "pending": False, "ai_recs": ai_recs
        })
    return render(request, "users/_ai_recs_block.html", {
        "pending": True, "task_id": task_id
    })

# ─── ИМПОРТ БИБЛИОТЕКИ ───────────────────────────────────────────────────────

@login_required
@require_POST
def import_library_view(request):
    """Принимает CSV-файл из Goodreads, запускает фоновый импорт."""
    from books.tasks import import_library_task

    csv_file = request.FILES.get("csv_file")
    if not csv_file:
        return render(request, "users/_import_result.html", {"error": "Файл не выбран"})

    try:
        content = csv_file.read().decode("utf-8")
    except UnicodeDecodeError:
        try:
            csv_file.seek(0)
            content = csv_file.read().decode("cp1251")
        except Exception:
            return render(request, "users/_import_result.html", {"error": "Не удалось прочитать файл"})

    task = import_library_task.delay(request.user.pk, content)
    request.session["import_task"] = task.id
    return render(request, "users/_import_result.html", {
        "pending": True, "task_id": task.id
    })


@login_required
@require_GET
def import_status(request):
    """HTMX polling: статус импорта библиотеки."""
    task_id = request.GET.get("task_id") or request.session.get("import_task")
    if not task_id:
        return render(request, "users/_import_result.html", {"error": "Задача не найдена"})

    from celery.result import AsyncResult
    result = AsyncResult(task_id)

    if result.ready():
        stats = result.result if result.successful() else None
        error = str(result.result) if result.failed() else None
        return render(request, "users/_import_result.html", {
            "pending": False, "stats": stats, "error": error
        })
    return render(request, "users/_import_result.html", {
        "pending": True, "task_id": task_id
    })


@login_required
@require_POST
def save_telegram(request):
    """HTMX — сохранение Telegram username."""
    username = request.POST.get("telegram_username", "").strip().lstrip("@")
    profile = _get_user_profile(request.user)
    profile.telegram_username = username
    profile.save(update_fields=["telegram_username"])
    return render(request, "users/_telegram_block.html", {
        "profile": profile, "saved": True
    })


@login_required
@require_POST
def save_max(request):
    """HTMX — сохранение MAX username."""
    username = request.POST.get("max_username", "").strip().lstrip("@")
    profile = _get_user_profile(request.user)
    profile.max_username = username
    profile.save(update_fields=["max_username"])
    return render(request, "users/_max_block.html", {
        "profile": profile, "saved": True
    })


@login_required
@require_POST
def save_vk(request):
    """HTMX — сохранение VK username."""
    username = request.POST.get("vk_username", "").strip().lstrip("@")
    profile = _get_user_profile(request.user)
    profile.vk_username = username
    profile.save(update_fields=["vk_username"])
    return render(request, "users/_vk_block.html", {
        "profile": profile, "saved": True
    })


@login_required
@require_POST
def save_contacts(request):
    """HTMX — сохранение email + Telegram/MAX/VK username из модалки."""
    user = request.user
    email = request.POST.get("email", "").strip()
    tg_username  = request.POST.get("telegram_username", "").strip().lstrip("@")
    max_username = request.POST.get("max_username", "").strip().lstrip("@")
    vk_username  = request.POST.get("vk_username", "").strip().lstrip("@")

    user.email = email
    user.save(update_fields=["email"])

    profile = _get_user_profile(user)
    profile.telegram_username = tg_username
    profile.max_username      = max_username
    profile.vk_username       = vk_username
    profile.save(update_fields=["telegram_username", "max_username", "vk_username"])

    return render(request, "users/_contacts_saved.html", {
        "profile": profile,
        "user": user,
    })

# ─── НАСТРОЙКИ АККАУНТА ──────────────────────────────────────────────────────

@login_required
@require_http_methods(["GET", "POST"])
def account_settings(request):
    """Страница настроек: смена логина / email / bio / пароля."""
    user = request.user
    profile = _get_user_profile(user)
    password_form = PasswordChangeForm(user=user)
    errors: dict[str, str] = {}

    if request.method == "POST":
        action = request.POST.get("action", "")

        if action == "profile":
            new_username = (request.POST.get("username") or "").strip()
            new_email    = (request.POST.get("email") or "").strip()
            new_bio      = (request.POST.get("bio") or "").strip()
            new_avatar   = request.FILES.get("avatar")
            new_gradient = (request.POST.get("avatar_gradient") or "").strip()
            remove_avatar = request.POST.get("remove_avatar") == "1"

            if not new_username:
                errors["username"] = "Логин не может быть пустым."
            elif len(new_username) < 3:
                errors["username"] = "Минимум 3 символа."
            elif new_username != user.username and User.objects.filter(username__iexact=new_username).exists():
                errors["username"] = "Этот логин уже занят."

            if new_email and User.objects.filter(email__iexact=new_email).exclude(pk=user.pk).exists():
                errors["email"] = "Этот email уже используется."

            if len(new_bio) > 1000:
                errors["bio"] = "Максимум 1000 символов."

            gradient_keys = {key for key, _label in AVATAR_GRADIENTS}
            if new_gradient not in gradient_keys:
                errors["avatar_gradient"] = "Р’С‹Р±РµСЂРёС‚Рµ РІР°СЂРёР°РЅС‚ РіСЂР°РґРёРµРЅС‚Р°."

            if new_avatar:
                if new_avatar.size > 5 * 1024 * 1024:
                    errors["avatar"] = "Файл должен быть не больше 5 МБ."
                elif not (new_avatar.content_type or "").startswith("image/"):
                    errors["avatar"] = "Загрузите изображение."

            if not errors:
                user.username = new_username
                user.email    = new_email
                user.save(update_fields=["username", "email"])
                profile.bio = new_bio
                profile.avatar_gradient = new_gradient
                update_fields = ["bio", "avatar_gradient"]
                if remove_avatar and profile.avatar:
                    profile.avatar.delete(save=False)
                    profile.avatar = None
                    update_fields.append("avatar")
                if new_avatar:
                    if profile.avatar:
                        profile.avatar.delete(save=False)
                    profile.avatar = new_avatar
                    update_fields.append("avatar")
                profile.save(update_fields=update_fields)
                messages.success(request, "Профиль обновлён.")
                return redirect("account_settings")

        elif action == "password":
            password_form = PasswordChangeForm(user=user, data=request.POST)
            if password_form.is_valid():
                password_form.save()
                update_session_auth_hash(request, password_form.user)
                messages.success(request, "Пароль изменён.")
                return redirect("account_settings")

    return render(request, "users/account_settings.html", {
        "profile":       profile,
        "avatar_gradients": AVATAR_GRADIENTS,
        "password_form": password_form,
        "errors":        errors,
    })


# ─── УПРАВЛЕНИЕ СПИСКАМИ ──────────────────────────────────────────────────────

@login_required
@require_POST
def create_list(request):
    name = request.POST.get("name", "").strip()
    if not name:
        return HttpResponseBadRequest("Название списка не может быть пустым")

    if UserList.objects.filter(user=request.user, name=name).exists():
        messages.error(request, f"Список «{name}» уже существует.")
    else:
        UserList.objects.create(user=request.user, name=name)
        _invalidate_ai_cache(request.user.pk)

    return _render_lists_panel(request, request.user)

@login_required
@require_POST
def delete_list(request, list_id):
    user_list = get_object_or_404(UserList, pk=list_id, user=request.user)
    if user_list.is_default:
        return HttpResponseBadRequest("Нельзя удалить список по умолчанию")

    user_list.delete()
    _invalidate_ai_cache(request.user.pk)
    return _render_lists_panel(request, request.user)

@login_required
@require_POST
def rename_list(request, list_id):
    user_list = get_object_or_404(UserList, pk=list_id, user=request.user)
    name = request.POST.get("name", "").strip()
    if not name:
        return HttpResponseBadRequest("Название списка не может быть пустым")
    if UserList.objects.filter(user=request.user, name=name).exclude(pk=user_list.pk).exists():
        return HttpResponseBadRequest(f"Список «{name}» уже существует")

    user_list.name = name
    user_list.save(update_fields=["name"])
    _invalidate_ai_cache(request.user.pk)
    return _render_lists_panel(request, request.user)

@login_required
@require_POST
def remove_book_from_list(request, list_id, book_id):
    user_list = get_object_or_404(UserList, pk=list_id, user=request.user)
    book = get_object_or_404(Book, pk=book_id)
    user_list.books.remove(book)
    _invalidate_ai_cache(request.user.pk)
    return _render_lists_panel(request, request.user)

# ─── ЭКСПОРТ СПИСКОВ ──────────────────────────────────────────────────────────

@login_required
@require_GET
def export_lists(request):
    lists = UserList.objects.filter(user=request.user).prefetch_related(
        "books__authors", "books__genres"
    )
    data = []
    for ul in lists:
        data.append({
            "list": ul.name,
            "sentiment": ul.sentiment_tag,
            "books": [
                {
                    "title": b.title,
                    "authors": [a.name for a in b.authors.all()],
                    "genres": [g.name for g in b.genres.all()],
                    "isbn": b.isbn or "",
                    "year": b.publication_year,
                }
                for b in ul.books.all()
            ],
        })
    fmt = request.GET.get("format", "json")

    if fmt == "csv":
        response = HttpResponse(content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = 'attachment; filename="my_books.csv"'
        response.write("\ufeff")  # BOM для корректного открытия в Excel
        writer = csv.writer(response)
        writer.writerow(["Список", "Тональность", "Название", "Авторы", "Жанры", "ISBN", "Год"])
        for ul_data in data:
            for b in ul_data["books"]:
                writer.writerow([
                    ul_data["list"],
                    ul_data["sentiment"],
                    b["title"],
                    ", ".join(b["authors"]),
                    ", ".join(b["genres"]),
                    b["isbn"],
                    b["year"] or "",
                ])
        return response

    payload = json.dumps(data, ensure_ascii=False, indent=2)
    response = HttpResponse(payload, content_type="application/json; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="my_books.json"'
    return response

# ─── ЭВОЛЮЦИЯ ВКУСА ──────────────────────────────────────────────────────────

@login_required
@require_GET
def taste_data(request):
    """JSON endpoint для Chart.js: данные об эволюции вкуса по месяцам."""
    from django.db.models.functions import TruncMonth, ExtractMonth, ExtractYear
    from collections import defaultdict

    # Все книги пользователя из списков, сгруппированные по месяцу добавления
    list_items = (
        UserList.objects
        .filter(user=request.user)
        .prefetch_related("books__genres")
        .order_by("created_at")
    )

    # Отзывы по месяцам
    reviews = (
        Review.objects
        .filter(user=request.user)
        .order_by("created_at")
    )

    # Агрегация по месяцам
    month_genres = defaultdict(lambda: defaultdict(int))
    month_books_count = defaultdict(int)
    month_ratings = defaultdict(list)

    for ul in list_items:
        month_key = ul.created_at.strftime("%Y-%m")
        for book in ul.books.all():
            month_books_count[month_key] += 1
            for genre in book.genres.all():
                month_genres[month_key][genre.name] += 1

    for r in reviews:
        month_key = r.created_at.strftime("%Y-%m")
        month_ratings[month_key].append(r.rating)

    # Собираем все месяцы
    all_months = sorted(set(list(month_genres.keys()) + list(month_ratings.keys())))
    if not all_months:
        return JsonResponse({"months": [], "genres": {}, "avg_ratings": [], "books_count": []})

    # Топ-5 жанров по суммарной частоте
    total_genre_count = defaultdict(int)
    for m, genres in month_genres.items():
        for g, c in genres.items():
            total_genre_count[g] += c
    top_genres = sorted(total_genre_count.keys(), key=lambda g: total_genre_count[g], reverse=True)[:5]

    genres_data = {}
    for genre in top_genres:
        genres_data[genre] = [month_genres[m].get(genre, 0) for m in all_months]

    avg_ratings = []
    for m in all_months:
        ratings = month_ratings.get(m, [])
        avg_ratings.append(round(sum(ratings) / len(ratings), 1) if ratings else None)

    books_count = [month_books_count.get(m, 0) for m in all_months]

    return JsonResponse({
        "months": all_months,
        "genres": genres_data,
        "avg_ratings": avg_ratings,
        "books_count": books_count,
    })

# ─── ЛИДЕРБОРД (геймификация) ─────────────────────────────────────────────────

@require_GET
def leaderboard(request):
    """
    Топ пользователей по XP + позиция текущего юзера.
    XP считается на лету (см. users/xp.py) — без отдельного поля в БД,
    чтобы исключить рассинхронизацию между «реальностью» и кэшем.
    """
    from .xp import leaderboard as compute_leaderboard, compute_xp, level_progress
    top = compute_leaderboard(limit=20)

    # Позиция и прогресс текущего юзера (если он не в топ-20)
    me_row = None
    me_progress = None
    if request.user.is_authenticated:
        my_xp = compute_xp(request.user)
        me_progress = level_progress(my_xp)
        # Позиция = сколько юзеров впереди + 1
        ahead = sum(1 for r in top if r["xp"] > my_xp)
        in_top = any(r["user"].pk == request.user.pk for r in top)
        if not in_top:
            me_row = {
                "user": request.user,
                "xp": my_xp,
                "level": me_progress["level"],
                "position": ahead + 1,
            }

    return render(request, "users/leaderboard.html", {
        "top": top,
        "me_row": me_row,
        "me_progress": me_progress,
    })


# ─── АДМИНИСТРИРОВАНИЕ ────────────────────────────────────────────────────────

@require_GET
def user_profile_public(request, username):
    target_user = get_object_or_404(User, username=username)
    approved_reviews = (
        Review.objects
        .filter(user=target_user, status=Review.APPROVED)
        .select_related("book")
        .order_by("-created_at")[:20]
    )

    is_own = request.user == target_user
    is_staff_viewer = request.user.is_authenticated and request.user.is_staff

    # Списки пользователя — приватные по определению.
    # На публичном профиле их видит ТОЛЬКО админ (staff).
    # Владелец свои списки смотрит в /profile/.
    if is_staff_viewer:
        target_lists = (
            UserList.objects
            .filter(user=target_user)
            .prefetch_related("books__authors")
        )
    else:
        target_lists = None

    # ── Рекомендации ──────────────────────────────────────────────────────────
    # AI-рекомендации достаём из кеша (НЕ запускаем генерацию с чужого профиля)
    ai_recs = load_from_cache(target_user.pk)

    # Обычные рекомендации — считаем быстро, из БД (без LLM)
    try:
        regular_recs = recommended_for_user(target_user, limit=10)
    except Exception:
        regular_recs = []

    # Диагностика — почему «не сгенерировано» / как сгенерировано.
    # produced_count=len(regular_recs) позволяет отличить «нет данных»
    # от «данные есть, но движок ничего не собрал».
    diag = diagnose_recommendations(target_user, produced_count=len(regular_recs))

    # Причина отсутствия AI-рекомендаций — централизованный helper.
    ai_reason_bullets = build_ai_reason_bullets(target_user, ai_recs)
    if ai_reason_bullets:
        ai_reason_bullets += diag["bullets"]

    # Per-book объяснения для админа (и владельца) — чтобы было понятно,
    # почему именно эти книги оказались в рекомендациях.
    explain_ctx = None
    regular_explained = []
    if is_staff_viewer:
        explain_ctx = build_explain_context(target_user)
        for book in regular_recs:
            regular_explained.append({
                "book":    book,
                "reasons": explain_match(book, explain_ctx),
            })
    else:
        regular_explained = [{"book": b, "reasons": []} for b in regular_recs]

    ctx = {
        "target_user":      target_user,
        "target_profile":   getattr(target_user, "profile", None),
        "approved_reviews": approved_reviews,
        "is_own_profile":   is_own,
        "target_lists":     target_lists,
        "can_see_sentiment": is_staff_viewer,
        "can_see_reasons":   is_staff_viewer,
        "ai_recs":           ai_recs,
        "ai_reason_bullets": ai_reason_bullets,
        "regular_recs":      regular_explained,
        "rec_diag":          diag,
    }

    # ── Богатый набор агрегатов для публичного профиля ──────────────────────
    viewer = request.user if request.user.is_authenticated else None
    ctx.update(build_public_profile_context(target_user, viewer=viewer))

    # Ачивки таргет-пользователя — уже полученные, для плашки
    from .models import get_achievements_progress
    all_ach = get_achievements_progress(target_user)
    ctx["target_achievements_earned"] = [a for a in all_ach if a["earned"]]
    ctx["target_achievements_total"]  = len(all_ach)

    # История блокировок — публично видна всем (по требованию пользователя)
    from .models import UserBlockHistory
    ctx["block_history"] = (
        UserBlockHistory.objects
        .filter(user=target_user)
        .select_related("blocked_by", "unblocked_by")
        .order_by("-blocked_at")[:10]
    )
    ctx["block_history_count"] = UserBlockHistory.objects.filter(user=target_user).count()

    if request.user.is_authenticated and not ctx["is_own_profile"]:
        from social.helpers import get_friendship_status
        status, fs = get_friendship_status(request.user, target_user)
        ctx["friendship_status"] = status
        ctx["friendship"] = fs
        ctx["is_sender"] = fs.from_user == request.user if fs else False
    return render(request, "users/user_profile_public.html", ctx)


@require_GET
def user_activity_public(request, username):
    """
    Публичная страница «Вся активность пользователя» с фильтрами и сортировкой.

    Агрегирует: отзывы, рецензии, комментарии, лайки, дружбы, рекомендации,
    добавления в списки, вступления в клубы. По умолчанию — всё, новое сверху.
    """
    from .activity_data import build_user_activity, CATEGORIES

    target_user = get_object_or_404(User, username=username)

    category = request.GET.get("category", "all")
    order    = request.GET.get("order", "-date")
    try:
        page = max(1, int(request.GET.get("page", "1")))
    except ValueError:
        page = 1

    valid_categories = {c[0] for c in CATEGORIES}
    if category not in valid_categories:
        category = "all"
    if order not in ("-date", "date"):
        order = "-date"

    data = build_user_activity(
        target_user,
        category=category,
        order=order,
        page=page,
        page_size=30,
    )

    ctx = {
        "target_user":   target_user,
        "is_own":        request.user.is_authenticated and request.user == target_user,
        **data,
    }
    return render(request, "users/user_activity.html", ctx)


@staff_required
@require_GET
def admin_panel(request):
    raw = (SearchHistory.objects.values("query")
           .annotate(cnt=Count("query"))
           .order_by("-cnt")[:8])
    max_cnt = raw[0]["cnt"] if raw else 1
    popular_queries = [{"query": r["query"], "pct": int(r["cnt"] / max_cnt * 100)} for r in raw]

    from notifications.models import NotificationSetting
    notif_settings = _build_notif_settings_matrix()
    from graph.models import BookRelation

    ctx = {
        "stat_books": Book.objects.count(),
        "stat_users": User.objects.count(),
        "stat_reviews": Review.objects.count(),
        "stat_searches": SearchHistory.objects.filter(
            created_at__date=timezone.now().date()
        ).count(),
        "popular_books": Book.objects.order_by("-rating_count")[:8],
        "popular_queries": popular_queries,
        "users": User.objects.select_related("profile").order_by("-date_joined")[:50],
        "books": Book.objects.prefetch_related("authors")[:50],
        "pending_reviews": Review.objects.filter(status=Review.PENDING).select_related("user", "book"),
        "stores": Store.objects.annotate(link_count=Count("book_links")),
        "pending_critiques": Critique.objects.filter(status=Critique.PENDING).select_related("user", "book").prefetch_related("criteria"),
        "editions": BookEdition.objects.prefetch_related("books__publisher").order_by("name")[:100],
        "notif_settings": notif_settings,
        "catalog_seed_stats": {
            "books": Book.objects.count(),
            "authors": Author.objects.count(),
            "publishers": Publisher.objects.count(),
            "series": Series.objects.count(),
            "languages": Language.objects.count(),
            "genres": Genre.objects.count(),
            "relations": BookRelation.objects.count(),
        },
        "catalog_seed_prompt": (
            "Собери JSONL seed-файл для русскоязычного книжного каталога.\n\n"
            "Нужно 1500 популярных книг: русская классика, зарубежная классика, "
            "современная проза, фэнтези, фантастика, детективы, young adult, "
            "non-fiction и детские книги.\n\n"
            "Формат: одна книга на строку, каждая строка валидный JSON object.\n"
            "Поля: title, original_title, authors, genres, language, publication_year, "
            "description, series, series_order, publisher, isbn_13, pages, cover_url, "
            "source_urls, popularity_bucket.\n\n"
            "Правила:\n"
            "- Не выдумывай ISBN, publisher, pages и cover_url.\n"
            "- Если поле не найдено в источниках, ставь null.\n"
            "- source_urls обязателен для каждой записи.\n"
            "- Дедуплицируй по title + first author + isbn_13.\n"
            "- Описания делай короткими и нейтральными, не копируй длинные тексты с сайтов.\n"
            "- Для серий указывай series и series_order только если уверен."
        ),
        "catalog_seed_example": (
            '{"title":"Мастер и Маргарита","original_title":"Мастер и Маргарита",'
            '"authors":["Михаил Булгаков"],"genres":["классика","магический реализм"],'
            '"language":"ru","publication_year":1967,"description":"Роман о Москве, '
            'свободе, страхе и цене выбора.","series":null,"series_order":null,'
            '"publisher":null,"isbn_13":null,"pages":null,"cover_url":null,'
            '"source_urls":["https://www.wikidata.org/wiki/Q..."],'
            '"popularity_bucket":"core"}'
        ),
        "author_seed_prompt": (
            "На основе уже готового seed_books.jsonl составь JSONL-файл authors_seed.jsonl "
            "для обогащения авторов в Django-проекте.\n\n"
            "Вход: список книг, где поле authors содержит имена авторов. Сначала извлеки "
            "уникальных авторов, нормализуй написание и убери дубли.\n\n"
            "Формат: одна строка = один валидный JSON object.\n"
            "Поля строго под текущую модель Author: name, bio, birth_year, source_urls.\n\n"
            "Правила:\n"
            "- name обязателен и должен совпадать с написанием автора в seed_books.jsonl.\n"
            "- bio: 1-3 коротких предложения на русском, нейтрально и без рекламного тона.\n"
            "- birth_year: число или null. Не указывай год, если источник не подтверждает его.\n"
            "- source_urls: массив ссылок на источники, минимум одна ссылка для заполненных bio/birth_year.\n"
            "- Не добавляй death_year, country, awards, photo_url и другие поля: их пока нет в модели.\n"
            "- Не копируй большие фрагменты биографий; формулируй кратко своими словами.\n"
            "- Если автор спорный, псевдоним или коллективный автор, оставь birth_year null.\n"
            "- Разбей результат на файлы по 300-500 авторов, если список большой."
        ),
        "author_seed_example": (
            '{"name":"Михаил Булгаков","bio":"Русский писатель и драматург, '
            'автор романов, повестей и пьес, в которых сатира соединяется с фантастикой '
            'и философской прозой. Наиболее известен романом «Мастер и Маргарита».",'
            '"birth_year":1891,'
            '"source_urls":["https://www.wikidata.org/wiki/Q2543"]}'
        ),
    }
    return render(request, "users/admin_panel.html", ctx)


def _build_notif_settings_matrix():
    """
    Собирает матрицу уведомлений для админ-панели.
    Гарантирует, что для каждого известного события есть строка (создаёт на лету).
    """
    from notifications.models import NotificationSetting
    existing = {s.event: s for s in NotificationSetting.objects.all()}
    rows = []
    for event, label in NotificationSetting.EVENT_CHOICES:
        setting = existing.get(event)
        if setting is None:
            setting = NotificationSetting.objects.create(event=event)
        rows.append({
            "event":    event,
            "label":    label,
            "telegram": setting.channel_telegram,
            "max":      setting.channel_max,
            "email":    setting.channel_email,
        })
    return rows


@staff_required
@require_GET
def admin_charts_demo(request):
    """
    Временная демка: сравнение SVG-спарклайна и Chart.js на одних и тех же данных.
    «Регистрации по дням за 30 дней».
    """
    from datetime import timedelta, date as date_cls
    from django.db.models.functions import TruncDate

    since = timezone.now().date() - timedelta(days=29)
    rows = (User.objects
            .filter(date_joined__date__gte=since)
            .annotate(day=TruncDate("date_joined"))
            .values("day").annotate(n=Count("id"))
            .order_by("day"))
    by_day = {r["day"]: r["n"] for r in rows}

    # Заполняем пропуски нулями, чтобы шкала была непрерывной
    series = []
    for i in range(30):
        d = since + timedelta(days=i)
        series.append({"date": d, "n": by_day.get(d, 0)})

    # Готовим полилинию для SVG (viewBox 360x120, padding 8)
    vb_w, vb_h, pad = 360, 120, 8
    inner_w = vb_w - pad * 2
    inner_h = vb_h - pad * 2
    max_n = max((p["n"] for p in series), default=0) or 1
    n_len = len(series) or 1

    svg_points = []
    svg_dots   = []
    for i, p in enumerate(series):
        x = pad + (i * inner_w / (n_len - 1)) if n_len > 1 else pad + inner_w / 2
        # инвертируем Y (SVG ось вниз)
        y = pad + inner_h - (p["n"] / max_n) * inner_h
        svg_points.append(f"{x:.1f},{y:.1f}")
        svg_dots.append({
            "x": round(x, 1), "y": round(y, 1),
            "tip": f"{p['date'].strftime('%d.%m')}: {p['n']}",
        })
    svg_polyline = " ".join(svg_points)
    # Для area-fill замыкаем к оси X
    svg_area = f"M {pad},{pad + inner_h} L " + " L ".join(svg_points) + f" L {pad + inner_w},{pad + inner_h} Z"

    # Спарклайн в мелком варианте (180x40)
    s_w, s_h = 180, 40
    s_points = []
    for i, p in enumerate(series):
        sx = (i * s_w / (n_len - 1)) if n_len > 1 else s_w / 2
        sy = s_h - (p["n"] / max_n) * s_h
        s_points.append(f"{sx:.1f},{sy:.1f}")
    spark_polyline = " ".join(s_points)

    # JSON для Chart.js
    import json as _json
    chart_labels = [p["date"].strftime("%d.%m") for p in series]
    chart_values = [p["n"] for p in series]

    ctx = {
        "series": series,
        "total": sum(p["n"] for p in series),
        "max_n": max_n,
        "vb_w": vb_w, "vb_h": vb_h,
        "svg_polyline": svg_polyline,
        "svg_area":     svg_area,
        "svg_dots":     svg_dots,
        "s_w": s_w, "s_h": s_h,
        "spark_polyline": spark_polyline,
        "chart_labels_json": _json.dumps(chart_labels),
        "chart_values_json": _json.dumps(chart_values),
    }
    return render(request, "users/admin_charts_demo.html", ctx)


@staff_required
@require_POST
def admin_notif_toggle(request):
    """
    HTMX: переключить канал для события. POST event=..., channel=telegram|max|email.
    Возвращает обновлённую строку таблицы.
    """
    from notifications.models import NotificationSetting
    event   = (request.POST.get("event") or "").strip()
    channel = (request.POST.get("channel") or "").strip()

    if channel not in NotificationSetting.CHANNELS:
        return HttpResponseBadRequest("Неверный канал")
    valid_events = {e for e, _ in NotificationSetting.EVENT_CHOICES}
    if event not in valid_events:
        return HttpResponseBadRequest("Неверное событие")

    setting, _ = NotificationSetting.objects.get_or_create(event=event)
    field = f"channel_{channel}"
    new_value = not getattr(setting, field)
    setattr(setting, field, new_value)
    setting.save(update_fields=[field, "updated_at"])

    row = {
        "event":    event,
        "label":    dict(NotificationSetting.EVENT_CHOICES).get(event, event),
        "telegram": setting.channel_telegram,
        "max":      setting.channel_max,
        "email":    setting.channel_email,
    }
    return render(request, "users/_admin_notif_row.html", {"row": row})

@staff_required
@require_GET
def admin_users_partial(request):
    q = request.GET.get("q", "")
    qs = User.objects.select_related("profile").order_by("-date_joined")
    if q:
        qs = qs.filter(Q(username__icontains=q) | Q(email__icontains=q))
    return render(request, "users/_admin_users.html", {"users": qs[:50]})

def _parse_blocked_until(raw: str):
    """Принимает строку 'YYYY-MM-DDTHH:MM' либо число суток — возвращает DateTime или None."""
    raw = (raw or "").strip()
    if not raw:
        return None
    # Число дней
    if raw.isdigit():
        return timezone.now() + timezone.timedelta(days=int(raw))
    # ISO-datetime из <input type="datetime-local">
    from django.utils.dateparse import parse_datetime
    dt = parse_datetime(raw)
    if dt is None:
        return None
    if timezone.is_naive(dt):
        dt = timezone.make_aware(dt, timezone.get_current_timezone())
    return dt


@staff_required
@require_POST
def admin_block_user(request, user_id):
    target = get_object_or_404(User, pk=user_id)
    if target.is_staff:
        return HttpResponseBadRequest("Нельзя заблокировать администратора")

    reason = (request.POST.get("reason") or "").strip()
    blocked_until = _parse_blocked_until(request.POST.get("blocked_until"))

    profile = _get_user_profile(target)
    profile.is_blocked = True
    profile.blocked_until = blocked_until
    profile.save()
    target.refresh_from_db()

    from .models import UserBlockHistory
    UserBlockHistory.objects.create(
        user=target,
        blocked_by=request.user,
        reason=reason,
        blocked_until=blocked_until,
    )

    from analytics.models import ModerationLog
    note_parts = [f"username={target.username}"]
    if reason:
        note_parts.append(f"reason={reason[:120]}")
    if blocked_until:
        note_parts.append(f"until={blocked_until:%Y-%m-%d %H:%M}")
    ModerationLog.log(request.user, "user_block", target=target,
                      note="; ".join(note_parts))
    return render(request, "users/_user_card.html", {"u": target})

@staff_required
@require_POST
def admin_unblock_user(request, user_id):
    target = get_object_or_404(User, pk=user_id)
    unblock_reason = (request.POST.get("unblock_reason") or "").strip()

    profile = _get_user_profile(target)
    profile.is_blocked = False
    profile.blocked_until = None
    profile.save()
    target.refresh_from_db()

    # Закрываем активную запись истории
    from .models import UserBlockHistory
    now = timezone.now()
    active = (UserBlockHistory.objects
              .filter(user=target, unblocked_at__isnull=True)
              .order_by("-blocked_at")
              .first())
    if active:
        active.unblocked_at = now
        active.unblocked_by = request.user
        active.unblock_reason = unblock_reason
        active.save(update_fields=["unblocked_at", "unblocked_by", "unblock_reason"])

    from analytics.models import ModerationLog
    note_parts = [f"username={target.username}"]
    if unblock_reason:
        note_parts.append(f"reason={unblock_reason[:120]}")
    ModerationLog.log(request.user, "user_unblock", target=target,
                      note="; ".join(note_parts))
    return render(request, "users/_user_card.html", {"u": target})


@staff_required
def admin_user_block_history(request, user_id):
    """HTMX-партиал со всей историей блокировок пользователя."""
    target = get_object_or_404(User, pk=user_id)
    from .models import UserBlockHistory
    history = (UserBlockHistory.objects
               .filter(user=target)
               .select_related("blocked_by", "unblocked_by")
               .order_by("-blocked_at"))
    return render(request, "users/_user_block_history.html", {
        "u": target,
        "history": history,
    })


@staff_required
def admin_user_card(request, user_id):
    """HTMX-партиал: одна карточка пользователя. Используется cancel-кнопками
    в форме уведомления и партиале истории блокировок, чтобы вернуть
    карточку на место без перезагрузки всего списка."""
    target = get_object_or_404(User, pk=user_id)
    return render(request, "users/_user_card.html", {"u": target})


@staff_required
def admin_notify_form(request, user_id):
    """HTMX-партиал: форма отправки уведомления пользователю."""
    target = get_object_or_404(User, pk=user_id)
    return render(request, "users/_user_notify_form.html", {"u": target})


@staff_required
@require_POST
def admin_send_notification(request, user_id):
    """Отправить пользователю уведомление от администрации."""
    target = get_object_or_404(User, pk=user_id)
    text = (request.POST.get("text") or "").strip()
    url = (request.POST.get("url") or "").strip()

    if not text:
        return HttpResponseBadRequest("Текст уведомления обязателен")

    from notifications.helpers import emit
    from notifications.models import Notification
    emit(
        user=target,
        kind=Notification.KIND_ADMIN_NOTICE,
        actor=request.user,
        text=text[:300],
        url=url[:500] or "/notifications/",
        extra={"from_admin": True, "admin_username": request.user.username},
    )

    from analytics.models import ModerationLog
    ModerationLog.log(request.user, "user_notify", target=target,
                      note=f"username={target.username}; text={text[:100]}")

    return render(request, "users/_user_card.html", {"u": target})

# ─── УПРАВЛЕНИЕ МАГАЗИНАМИ (ADMIN) ────────────────────────────────────────────

@staff_required
@require_POST
def admin_store_save(request):
    store_id = request.POST.get("store_id")
    data = {
        "name": request.POST.get("name", "").strip(),
        "base_url": request.POST.get("base_url", "").strip(),
        "icon": request.POST.get("icon", "").strip(),
        "price_selector": request.POST.get("price_selector", "").strip(),
        "is_active": request.POST.get("is_active") == "on",
    }
    if not data["name"] or not data["base_url"]:
        return HttpResponseBadRequest("Название и URL обязательны")

    from analytics.models import ModerationLog
    if store_id:
        Store.objects.filter(pk=store_id).update(**data)
        saved = Store.objects.filter(pk=store_id).first()
    else:
        saved = Store.objects.create(**data)
    if saved:
        ModerationLog.log(request.user, "store_save", target=saved,
                          note=f"name={saved.name}")

    stores = Store.objects.annotate(link_count=Count("book_links"))
    return render(request, "users/_admin_stores.html", {"stores": stores})

@staff_required
@require_POST
def admin_store_delete(request, store_id):
    store = get_object_or_404(Store, pk=store_id)
    store_name = store.name
    store.delete()

    from analytics.models import ModerationLog
    # target=None, поскольку объект уже удалён — пишем имя в note
    ModerationLog.objects.create(
        moderator=request.user if request.user.is_authenticated else None,
        action="store_delete",
        target_type="store",
        target_id=store_id,
        target_repr=store_name[:250],
        note=f"deleted: {store_name}"[:500],
    )

    stores = Store.objects.annotate(link_count=Count("book_links"))
    return render(request, "users/_admin_stores.html", {"stores": stores})


@staff_required
@never_cache
def admin_tests(request):
    """Страница запуска тестов в админ-панели."""
    # Получаем список всех тестов
    try:
        result = subprocess.run(
            ["python", "-m", "pytest", "--collect-only", "-qq", "--no-cov", "tests/"],
            capture_output=True,
            text=True,
            cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            timeout=30
        )
        test_output = result.stdout
    except (subprocess.TimeoutExpired, FileNotFoundError):
        test_output = "Не удалось получить список тестов"
    
    # Парсим список тестов
    tests = []
    categories = {}
    tabs = {}
    for line in test_output.split('\n'):
        line = line.strip()
        if line.startswith("tests/") and "::" in line and "test_" in line:
            parts = line.split("::")
            module_path = parts[0]
            class_name = parts[1] if len(parts) > 2 else ""
            test_name = parts[-1]
            category_path = f"{module_path}::{class_name}" if class_name else module_path
            category_name = {
                "test_api.py": "API",
                "test_models.py": "Модели",
                "test_views.py": "Страницы",
            }.get(os.path.basename(module_path), os.path.basename(module_path))
            group_name = {
                "TestAuthor": "Автор",
                "TestBook": "Книга",
                "TestGenre": "Жанр",
                "TestUserList": "Список пользователя",
                "TestBookAPI": "API книг",
                "TestAuthorAPI": "API авторов",
                "TestAPIKeyAuthentication": "API-ключи",
                "TestHomeView": "Главная страница",
                "TestCommunityView": "Сообщество",
                "TestLuckyView": "Мне повезёт",
                "TestDesignDemos": "Дизайн-демо",
                "TestErrorPages": "Страницы ошибок",
            }.get(class_name, class_name or category_name)
            test_data = {
                'name': test_name,
                'path': line,
                'class_name': class_name,
            }
            tests.append(test_data)
            categories.setdefault(category_path, {
                "name": group_name,
                "class_name": class_name,
                "path": category_path,
                "tab_key": os.path.basename(module_path).replace(".", "-"),
                "tests": [],
            })["tests"].append(test_data)
            tabs.setdefault(os.path.basename(module_path).replace(".", "-"), {
                "key": os.path.basename(module_path).replace(".", "-"),
                "name": category_name,
                "path": module_path,
                "count": 0,
            })["count"] += 1
    
    return render(request, "users/admin_tests.html", {
        "tests": tests,
        "categories": categories.values(),
        "tabs": tabs.values(),
        "total_tests": len(tests),
    })


@staff_required
@csrf_exempt
def admin_run_tests(request):
    """Запуск конкретного теста или всех тестов."""
    import logging
    
    logger = logging.getLogger(__name__)
    
    if request.method != "POST":
        return JsonResponse({
            "success": False,
            "error": "Only POST method is allowed"
        }, status=405)
    
    if request.content_type == "application/json":
        try:
            payload = json.loads(request.body.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            return JsonResponse({
                "success": False,
                "error": "Некорректный JSON",
            })
        test_path = payload.get("test_path", "")
    else:
        test_path = request.POST.get("test_path", "")
    if test_path and not re.fullmatch(r"tests/[A-Za-z0-9_./-]+(?:::[A-Za-z0-9_]+){0,2}", test_path):
        return JsonResponse({
            "success": False,
            "error": "Некорректный путь теста",
        })
    
    try:
        # Определяем корневую директорию проекта
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        
        if test_path:
            # Запуск конкретного теста
            cmd = ["python", "-m", "pytest", test_path, "-v", "--no-cov"]
        else:
            # Запуск всех тестов
            cmd = ["python", "-m", "pytest", "tests/", "-v", "--no-cov"]
        
        logger.info(f"Running tests: {' '.join(cmd)}")
        
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=project_root,
            timeout=120
        )
        
        output = result.stdout + result.stderr
        
        if not output:
            output = "Тесты не вернули вывода. Возможно, pytest не установлен или не найден."
        
        # Парсим результаты
        passed = output.count("PASSED")
        failed = output.count("FAILED")
        errors = output.count("ERROR")
        
        response_data = {
            "success": True,
            "output": output,
            "passed": passed,
            "failed": failed,
            "errors": errors,
            "total": passed + failed + errors,
        }
        logger.info(f"Tests completed: passed={passed}, failed={failed}, errors={errors}")
        return JsonResponse(response_data)
    except subprocess.TimeoutExpired:
        logger.error("Tests timeout")
        return JsonResponse({
            "success": False,
            "error": "Тайм-аут при выполнении тестов",
        })
    except Exception as e:
        logger.error(f"Tests error: {e}", exc_info=True)
        return JsonResponse({
            "success": False,
            "error": str(e),
        })

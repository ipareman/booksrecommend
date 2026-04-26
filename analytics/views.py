"""
Views аналитики:
- `redirect_to_store` — редирект-«считалка» для ссылок «Купить».
  Пишем StoreClick и отдаём 302 на product_url.
- `analytics_partial` — HTMX-частный шаблон, вставляется в admin_panel tab.
- `refresh_now` — кнопка «обновить сейчас» (принудительно пересчитать).
"""
from functools import wraps

from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpResponse, HttpResponseBadRequest, HttpResponseRedirect
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_GET, require_POST

from books.models import BookStore
from .compute import get_dashboard
from .models import StoreClick


# ──────────────────────────────────────────────────────────────────────────
# staff_required — используем собственный декоратор, чтобы не зависеть от users.views
# ──────────────────────────────────────────────────────────────────────────

def staff_required(view):
    @wraps(view)
    @login_required
    def _w(request, *args, **kwargs):
        if not request.user.is_staff:
            raise Http404
        return view(request, *args, **kwargs)
    return _w


# ──────────────────────────────────────────────────────────────────────────
# ТРЕКИНГ КЛИКОВ ПО МАГАЗИНАМ
# ──────────────────────────────────────────────────────────────────────────

@require_GET
def redirect_to_store(request, book_id: int, store_id: int):
    """
    /b/<book_id>/s/<store_id>/ — регистрирует клик и делает 302 на реальную
    ссылку магазина (BookStore.product_url). Если связки нет — 404.
    """
    try:
        bs = (BookStore.objects
                       .select_related("book", "store")
                       .get(book_id=book_id, store_id=store_id))
    except BookStore.DoesNotExist:
        raise Http404("Ссылка на магазин не найдена")

    # Достаём session_key (для дедупликации анонимов; безопасно, если сессии ещё нет)
    session_key = request.session.session_key or ""
    if not session_key:
        try:
            request.session.save()
            session_key = request.session.session_key or ""
        except Exception:
            session_key = ""

    try:
        StoreClick.objects.create(
            book=bs.book,
            store=bs.store,
            user=request.user if request.user.is_authenticated else None,
            session_key=session_key[:40],
            referer=(request.META.get("HTTP_REFERER") or "")[:500],
        )
    except Exception:
        # Логируем, но не ломаем юзеру поход в магазин
        import logging
        logging.getLogger(__name__).exception("StoreClick create failed")

    return HttpResponseRedirect(bs.product_url)


# ──────────────────────────────────────────────────────────────────────────
# ADMIN-ЧАСТИ (рендерятся как partial в admin_panel таб "Аналитика")
# ──────────────────────────────────────────────────────────────────────────

def _error_partial(exc: Exception) -> HttpResponse:
    """Человекочитаемый ответ, если compute_dashboard упал."""
    import traceback
    tb = traceback.format_exc()
    hint = ""
    msg = str(exc)
    if "does not exist" in msg or "no such table" in msg:
        hint = (
            "Похоже, миграция analytics ещё не применена. "
            "В контейнере выполни:<br>"
            "<code>docker compose exec web python manage.py migrate analytics</code>"
        )
    html = f"""
    <div style="background:#fff5e6;border:1px solid #e5a552;padding:16px;border-radius:8px;
                font-size:13px;line-height:1.55">
      <b style="color:#b32020">⚠ Аналитика не собралась</b><br>
      <span style="font-family:ui-monospace,Menlo,monospace">{msg}</span>
      {f'<div style="margin-top:10px">{hint}</div>' if hint else ''}
      <details style="margin-top:10px">
        <summary style="cursor:pointer;color:var(--muted)">Traceback</summary>
        <pre style="font-size:11px;max-height:280px;overflow:auto">{tb}</pre>
      </details>
    </div>
    """
    return HttpResponse(html, status=200)


@staff_required
@require_GET
def analytics_partial(request):
    """
    HTMX-частный шаблон. Вставляется в #analytics-pane.
    При ?force=1 — принудительная пересборка (минуя кеш).
    """
    force = request.GET.get("force") == "1"
    try:
        data = get_dashboard(force_refresh=force)
    except Exception as exc:
        import logging
        logging.getLogger(__name__).exception("analytics_partial failed")
        return _error_partial(exc)
    return render(request, "analytics/_dashboard.html", {"d": data})


@staff_required
@require_POST
def refresh_now(request):
    """
    Принудительная пересборка кеша. Возвращает свежий partial.
    """
    try:
        data = get_dashboard(force_refresh=True)
    except Exception as exc:
        import logging
        logging.getLogger(__name__).exception("refresh_now failed")
        return _error_partial(exc)
    return render(request, "analytics/_dashboard.html", {"d": data})


# ──────────────────────────────────────────────────────────────────────────
# DEEP-DIVE СТРАНИЦЫ (каждая — отдельный URL, со своими фильтрами)
# ──────────────────────────────────────────────────────────────────────────

def _int_param(request, key: str, default: int) -> int:
    try:
        return int(request.GET.get(key, default))
    except (TypeError, ValueError):
        return default


@staff_required
@require_GET
def detail_registrations(request):
    from .detail_compute import registrations_detail
    days        = _int_param(request, "days", 30)
    granularity = request.GET.get("g", "day")
    if granularity not in ("hour", "day", "week", "month"):
        granularity = "day"
    data = registrations_detail(days=days, granularity=granularity)
    return render(request, "analytics/detail_registrations.html", {"d": data})


@staff_required
@require_GET
def detail_funnel(request):
    from .detail_compute import funnel_detail
    days = _int_param(request, "days", 30)
    data = funnel_detail(days=days)
    return render(request, "analytics/detail_funnel.html", {"d": data})


@staff_required
@require_GET
def detail_stores(request):
    from .detail_compute import stores_detail
    days = _int_param(request, "days", 30)
    sort = request.GET.get("sort", "clicks")
    data = stores_detail(days=days, sort=sort)
    return render(request, "analytics/detail_stores.html", {"d": data})


@staff_required
@require_GET
def detail_books(request):
    from .detail_compute import books_detail
    days = _int_param(request, "days", 30)
    q    = (request.GET.get("q") or "").strip()
    sort = request.GET.get("sort", "score")
    page = _int_param(request, "page", 1)
    data = books_detail(days=days, q=q, sort=sort, page=page)
    # HTMX-запрос из формы фильтров — возвращаем только блок результатов
    tpl = ("analytics/_detail_books_results.html"
           if getattr(request, "htmx", False)
           else "analytics/detail_books.html")
    return render(request, tpl, {"d": data})


@staff_required
@require_GET
def detail_moderation(request):
    from .detail_compute import moderation_detail
    days      = _int_param(request, "days", 30)
    action    = request.GET.get("action", "")
    moderator = (request.GET.get("moderator") or "").strip()
    q         = (request.GET.get("q") or "").strip()
    page      = _int_param(request, "page", 1)
    data = moderation_detail(days=days, action=action, moderator=moderator,
                             q=q, page=page)
    # HTMX-запрос из формы фильтров — возвращаем только блок результатов
    tpl = ("analytics/_detail_moderation_results.html"
           if getattr(request, "htmx", False)
           else "analytics/detail_moderation.html")
    return render(request, tpl, {"d": data})


@staff_required
@require_GET
def detail_cohorts(request):
    from .detail_compute import cohorts_detail
    cohort_count = _int_param(request, "cohorts", 12)
    depth        = _int_param(request, "depth", 12)
    data = cohorts_detail(cohort_count=cohort_count, depth=depth)
    return render(request, "analytics/detail_cohorts.html", {"d": data})

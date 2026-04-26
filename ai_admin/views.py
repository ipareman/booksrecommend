"""
Админка AI: дашборд, управление Celery-задачами, админ-чат, настройки.
Все view доступны только staff (is_staff=True).
"""

import logging
from datetime import timedelta

from django.contrib.admin.views.decorators import staff_member_required
from django.db.models import Count, Sum, Avg, Q
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .models import AIUsageLog, AIConfig

logger = logging.getLogger(__name__)


# ────────────────────────────  Dashboard  ──────────────────────────────

@staff_member_required
def dashboard(request):
    now = timezone.now()
    day_ago   = now - timedelta(days=1)
    week_ago  = now - timedelta(days=7)

    qs_all  = AIUsageLog.objects.all()
    qs_day  = qs_all.filter(created_at__gte=day_ago)
    qs_week = qs_all.filter(created_at__gte=week_ago)

    def summarize(qs):
        a = qs.aggregate(
            n=Count("id"),
            errs=Count("id", filter=~Q(status="ok")),
            toks=Sum("total_tokens"),
            lat=Avg("latency_ms"),
        )
        n = a["n"] or 0
        return {
            "n":     n,
            "errs":  a["errs"] or 0,
            "toks":  a["toks"] or 0,
            "lat":   int(a["lat"] or 0),
            "ok_pct": round(100 * (n - (a["errs"] or 0)) / n, 1) if n else 0,
        }

    # График: запросы по дням за 7 дней
    chart = []
    for i in range(6, -1, -1):
        day_start = (now - timedelta(days=i)).replace(hour=0, minute=0, second=0, microsecond=0)
        day_end   = day_start + timedelta(days=1)
        day_qs = qs_all.filter(created_at__gte=day_start, created_at__lt=day_end)
        chart.append({
            "label": day_start.strftime("%d.%m"),
            "ok":    day_qs.filter(status="ok").count(),
            "err":   day_qs.exclude(status="ok").count(),
        })
    chart_max = max((d["ok"] + d["err"]) for d in chart) or 1

    # Разбивка по feature (за неделю)
    by_feature = list(
        qs_week.values("feature")
        .annotate(n=Count("id"), errs=Count("id", filter=~Q(status="ok")), toks=Sum("total_tokens"))
        .order_by("-n")
    )

    # Разбивка по моделям (за неделю)
    by_model = list(
        qs_week.exclude(model="")
        .values("model")
        .annotate(n=Count("id"), errs=Count("id", filter=~Q(status="ok")))
        .order_by("-n")[:10]
    )

    recent      = qs_all.select_related("user")[:50]
    recent_errors = qs_all.exclude(status="ok").select_related("user")[:15]

    return render(request, "ai_admin/dashboard.html", {
        "stats_list": [
            ("За 24 часа", summarize(qs_day)),
            ("За 7 дней",  summarize(qs_week)),
            ("Всего",      summarize(qs_all)),
        ],
        "chart":         chart,
        "chart_max":     chart_max,
        "by_feature":    by_feature,
        "by_model":      by_model,
        "recent":        recent,
        "recent_errors": recent_errors,
    })


@staff_member_required
def log_detail(request, log_id: int):
    """HTML-партиал с полным содержимым лог-записи — рендерится в модалку."""
    log = get_object_or_404(AIUsageLog.objects.select_related("user"), pk=log_id)
    return render(request, "ai_admin/_log_detail.html", {"log": log})


# ────────────────────────────  Celery tasks  ───────────────────────────

def _celery_inspect():
    from config.celery import app
    return app.control.inspect(timeout=2)


def _collect_celery_tasks():
    """Опросить Celery и вернуть (unreachable, tasks) — используется
    и полной страницей, и HTMX-партиалом."""
    active = scheduled = reserved = {}
    unreachable = False
    try:
        i = _celery_inspect()
        active    = i.active()    or {}
        scheduled = i.scheduled() or {}
        reserved  = i.reserved()  or {}
    except Exception as exc:
        logger.warning("Celery inspect failed: %s", exc)
        unreachable = True

    def flatten(mapping, kind):
        out = []
        for worker, tasks in (mapping or {}).items():
            for t in tasks or []:
                out.append({
                    "worker": worker,
                    "kind":   kind,
                    "id":     t.get("id") or t.get("request", {}).get("id"),
                    "name":   t.get("name") or t.get("request", {}).get("name"),
                    "args":   t.get("args") or t.get("request", {}).get("args"),
                    "time_start": t.get("time_start"),
                })
        return out

    all_tasks = flatten(active, "active") + flatten(reserved, "reserved") + flatten(scheduled, "scheduled")
    return unreachable, all_tasks


@staff_member_required
def tasks_view(request):
    unreachable, all_tasks = _collect_celery_tasks()
    from books.models import Book
    return render(request, "ai_admin/tasks.html", {
        "unreachable": unreachable,
        "tasks":       all_tasks,
        "books":       Book.objects.order_by("-id")[:500],
        "now":         timezone.now(),
    })


@staff_member_required
def tasks_partial_view(request):
    """Отдаёт только таблицу задач — для HTMX-поллинга с tasks.html."""
    unreachable, all_tasks = _collect_celery_tasks()
    return render(request, "ai_admin/_tasks_table.html", {
        "unreachable": unreachable,
        "tasks":       all_tasks,
        "now":         timezone.now(),
    })


@staff_member_required
@require_POST
def task_revoke(request):
    task_id = request.POST.get("task_id", "").strip()
    terminate = request.POST.get("terminate") == "1"
    if not task_id:
        return redirect("ai_admin_tasks")
    try:
        from config.celery import app
        app.control.revoke(task_id, terminate=terminate, signal="SIGTERM")
    except Exception as exc:
        logger.warning("Revoke failed: %s", exc)
    return redirect("ai_admin_tasks")


# Белый список задач, которые можно дёргать вручную из UI
_ALLOWED_TASKS = {
    "books.tasks.extract_tags_from_description": {"label": "Извлечь теги из описания",        "args": ["book_id"]},
    "books.tasks.classify_book_mood":            {"label": "Классификация mood",               "args": ["book_id"]},
    "books.tasks.generate_smart_quotes":         {"label": "Сгенерировать AI-цитаты",          "args": ["book_id"]},
    "users.tasks.classify_list_sentiment":       {"label": "Тональность списка",               "args": ["list_id"]},
    "users.tasks.send_weekly_digest":            {"label": "Еженедельный дайджест",            "args": []},
    "books.tasks.check_price_alerts":            {"label": "Проверка алертов цен",             "args": []},
}


@staff_member_required
@require_POST
def task_enqueue(request):
    name = request.POST.get("name", "")
    if name not in _ALLOWED_TASKS:
        return redirect("ai_admin_tasks")
    spec = _ALLOWED_TASKS[name]
    args = []
    for arg_name in spec["args"]:
        v = request.POST.get(arg_name, "").strip()
        if not v:
            return redirect("ai_admin_tasks")
        try:
            args.append(int(v))
        except ValueError:
            args.append(v)

    try:
        from config.celery import app
        app.send_task(name, args=args)
    except Exception as exc:
        logger.error("Enqueue failed for %s: %s", name, exc)
    return redirect("ai_admin_tasks")


# ────────────────────────────  Config  ─────────────────────────────────

_FEATURE_FIELDS = [
    ("enable_discovery",       "Discovery chat"),
    ("enable_book_chat",       "Book chat"),
    ("enable_recommendations", "Рекомендации"),
    ("enable_ai_search",       "AI-поиск"),
    ("enable_tag",             "Извлечение тегов"),
    ("enable_mood",            "Классификация mood"),
    ("enable_quotes",          "AI-цитаты"),
    ("enable_sentiment",       "Тональность списков"),
    # Фичи, которые работают с полным текстом книги:
    ("enable_chapter_summary", "Саммари глав"),
    ("enable_book_themes",     "Темы и мотивы"),
    ("enable_book_search",     "Семантический поиск по главам"),
    ("enable_book_style",      "Профиль стиля"),
]


_VALID_PROVIDERS = {v for v, _ in AIConfig.PROVIDER_CHOICES}


@staff_member_required
def config_view(request):
    cfg = AIConfig.get()
    if request.method == "POST":
        provider = (request.POST.get("provider") or "openrouter").strip()
        if provider not in _VALID_PROVIDERS:
            provider = "openrouter"
        cfg.provider        = provider
        cfg.custom_api_key  = (request.POST.get("custom_api_key")  or "").strip()
        cfg.custom_base_url = (request.POST.get("custom_base_url") or "").strip()

        cfg.model_main     = (request.POST.get("model_main")     or "").strip()
        cfg.model_light    = (request.POST.get("model_light")    or "").strip()
        cfg.model_fallback = (request.POST.get("model_fallback") or "").strip()
        for field, _ in _FEATURE_FIELDS:
            setattr(cfg, field, request.POST.get(field) == "on")
        cfg.dry_run_mode = request.POST.get("dry_run_mode") == "on"
        cfg.save()
        return redirect("ai_admin_config")

    from django.conf import settings
    # Передаём список (поле, ярлык, checked?) — шаблон просто рендерит чекбокс.
    feature_rows = [(f, label, getattr(cfg, f, False)) for f, label in _FEATURE_FIELDS]
    return render(request, "ai_admin/config.html", {
        "cfg":              cfg,
        "feature_fields":   _FEATURE_FIELDS,
        "feature_rows":     feature_rows,
        "provider_choices": AIConfig.PROVIDER_CHOICES,
        "defaults": {
            "main":     getattr(settings, "AI_MODEL_MAIN", ""),
            "light":    getattr(settings, "AI_MODEL_LIGHT", ""),
            "fallback": getattr(settings, "AI_MODEL_FALLBACK", ""),
        },
    })

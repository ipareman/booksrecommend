"""
Параметризованные вычисления для deep-dive страниц.
В отличие от compute.py (всегда 30д, фиксированный вид), здесь:
  - принимают диапазон дат / гранулярность / фильтры
  - не кешируются umbrella-функцией (слишком много комбинаций)
  - оптимизированы для одного блока за запрос
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from django.contrib.auth.models import User
from django.db.models import Count, F, Q, Avg, Sum
from django.db.models.functions import TruncDate, TruncHour, TruncWeek, TruncMonth
from django.utils import timezone


# ─── ВСПОМОГАТЕЛЬНЫЕ ─────────────────────────────────────────────────────

GRANULARITY_TRUNC = {
    "hour":  TruncHour,
    "day":   TruncDate,
    "week":  TruncWeek,
    "month": TruncMonth,
}


def parse_range(days_raw: str | int | None, *, default: int = 30,
                min_days: int = 1, max_days: int = 365) -> tuple[datetime, int]:
    """
    Безопасно разбирает параметр «сколько дней назад».
    Возвращает (since_datetime, days).
    """
    try:
        days = int(days_raw) if days_raw is not None else default
    except (TypeError, ValueError):
        days = default
    days = max(min_days, min(max_days, days))
    since = timezone.now() - timedelta(days=days)
    return since, days


def fill_series(rows: list[dict], key: str, since: date, days: int,
                granularity: str = "day") -> list[dict]:
    """Заполнить пропуски нулями для непрерывной временной шкалы (для day/week)."""
    by = {r[key]: r["n"] for r in rows}
    out = []
    if granularity == "day":
        for i in range(days):
            d = since + timedelta(days=i)
            if isinstance(next(iter(by.keys()), None), datetime):
                d_key = datetime.combine(d, datetime.min.time())
                d_key = timezone.make_aware(d_key) if timezone.is_naive(d_key) else d_key
            else:
                d_key = d
            out.append({"key": d, "n": by.get(d, by.get(d_key, 0))})
    else:
        # Для недели/месяца — без заполнения пропусков, пропускаем чистый список
        for r in rows:
            out.append({"key": r[key], "n": r["n"]})
    return out


# ─── РЕГИСТРАЦИИ ─────────────────────────────────────────────────────────

def registrations_detail(days: int = 30, granularity: str = "day") -> dict[str, Any]:
    since, days = parse_range(days)
    trunc = GRANULARITY_TRUNC.get(granularity, TruncDate)

    rows = (User.objects
            .filter(date_joined__gte=since)
            .annotate(bucket=trunc("date_joined"))
            .values("bucket")
            .annotate(n=Count("id"))
            .order_by("bucket"))
    rows = list(rows)
    total = sum(r["n"] for r in rows)
    max_n = max((r["n"] for r in rows), default=0)
    peak  = max(rows, key=lambda r: r["n"], default=None)

    labels = []
    values = []
    for r in rows:
        b = r["bucket"]
        if isinstance(b, datetime):
            labels.append(b.strftime({"hour": "%d.%m %H:00",
                                       "day":  "%d.%m",
                                       "week": "%d.%m",
                                       "month": "%m.%Y"}.get(granularity, "%d.%m")))
        elif isinstance(b, date):
            labels.append(b.strftime("%d.%m"))
        else:
            labels.append(str(b))
        values.append(r["n"])

    # Дни недели
    weekday_map = {i: 0 for i in range(7)}
    for u in User.objects.filter(date_joined__gte=since).values_list("date_joined", flat=True):
        weekday_map[u.weekday()] += 1
    weekday_labels = ["Пн","Вт","Ср","Чт","Пт","Сб","Вс"]
    weekday_values = [weekday_map[i] for i in range(7)]

    return {
        "days":            days,
        "granularity":     granularity,
        "total":           total,
        "avg_per_day":     round(total / max(days, 1), 1),
        "peak_n":          peak["n"] if peak else 0,
        "peak_when":       labels[rows.index(peak)] if peak and peak in rows else "",
        "labels":          labels,
        "values":          values,
        "weekday_labels":  weekday_labels,
        "weekday_values":  weekday_values,
        "max_n":           max_n,
    }


# ─── ВОРОНКА ─────────────────────────────────────────────────────────────

def funnel_detail(days: int = 30) -> dict[str, Any]:
    from books.models import UserList, ReadingProgress
    from reviews.models import Review, Critique

    since, days = parse_range(days)

    step1 = set(UserList.objects
                .filter(created_at__gte=since)
                .values_list("user_id", flat=True))
    step2 = set(ReadingProgress.objects
                .filter(updated_at__gte=since, current_page__gt=0)
                .values_list("user_id", flat=True))
    step3 = set(ReadingProgress.objects
                .filter(updated_at__gte=since,
                        book__pages__gt=0,
                        current_page__gte=F("book__pages") * 0.95)
                .values_list("user_id", flat=True))
    step4 = set(Review.objects.filter(created_at__gte=since).values_list("user_id", flat=True)) | \
            set(Critique.objects.filter(created_at__gte=since).values_list("user_id", flat=True))

    s = [len(step1), len(step2), len(step3), len(step4)]
    labels = ["Создали список", "Начали читать", "Дочитали", "Оставили отзыв"]
    base = max(s[0], s[1], 1)

    steps = []
    for i, (lbl, n) in enumerate(zip(labels, s)):
        prev = s[i-1] if i > 0 else (n or 1)
        steps.append({
            "label":    lbl,
            "n":        n,
            "pct_base": round(n / base * 100, 1),
            "pct_prev": round(n / (prev or 1) * 100, 1) if i > 0 else 100.0,
            "drop":     prev - n if i > 0 else 0,
            "w":        n / base * 100,
        })

    # Дополнительный блок: сколько пришли, но ничего не сделали
    only_list = step1 - step2 - step3 - step4
    only_reading = step2 - step3 - step4
    read_no_review = step3 - step4
    return {
        "days":   days,
        "steps":  steps,
        "conversion_end": round(s[3] / max(s[0], 1) * 100, 1),
        "total":  max(s[0], 1),
        "total_lost": max(s[0] - s[3], 0),
        "segments": {
            "only_list":      len(only_list),
            "only_reading":   len(only_reading),
            "read_no_review": len(read_no_review),
            "full_loop":      len(step4 & step1),
        },
    }


# ─── МАГАЗИНЫ ────────────────────────────────────────────────────────────

def stores_detail(days: int = 30, sort: str = "clicks") -> dict[str, Any]:
    from analytics.models import StoreClick
    from books.models import Store, BookStore

    since, days = parse_range(days)

    # Общие клики за период
    click_agg = (StoreClick.objects.filter(created_at__gte=since)
                 .values("store_id")
                 .annotate(clicks=Count("id"),
                           unique_users=Count("user_id", distinct=True),
                           unique_sessions=Count("session_key", distinct=True))
                 .order_by("-clicks"))

    # Все активные магазины (чтобы показать и нули)
    stores = {s.id: s for s in Store.objects.all()}
    link_counts = dict(BookStore.objects.values("store_id")
                                        .annotate(n=Count("id"))
                                        .values_list("store_id", "n"))
    rows_map = {}
    total_clicks = 0
    for agg in click_agg:
        sid = agg["store_id"]
        s = stores.get(sid)
        if not s:
            continue
        rows_map[sid] = {
            "id":           s.id,
            "name":         s.name,
            "icon":         s.icon or "🛒",
            "is_active":    s.is_active,
            "clicks":       agg["clicks"],
            "unique_users": agg["unique_users"] or 0,
            "unique_sessions": agg["unique_sessions"] or 0,
            "books_linked": link_counts.get(s.id, 0),
        }
        total_clicks += agg["clicks"]

    # Добавляем магазины без кликов (чтобы их видно)
    for sid, s in stores.items():
        if sid not in rows_map:
            rows_map[sid] = {
                "id":           s.id,
                "name":         s.name,
                "icon":         s.icon or "🛒",
                "is_active":    s.is_active,
                "clicks":       0,
                "unique_users": 0,
                "unique_sessions": 0,
                "books_linked": link_counts.get(s.id, 0),
            }
    rows = list(rows_map.values())
    # Sort
    sort_map = {
        "clicks":    lambda r: -r["clicks"],
        "books":     lambda r: -r["books_linked"],
        "name":      lambda r: r["name"].lower(),
        "users":     lambda r: -r["unique_users"],
    }
    rows.sort(key=sort_map.get(sort, sort_map["clicks"]))

    # Временной ряд по дням (все магазины суммарно)
    by_day = list(StoreClick.objects.filter(created_at__gte=since)
                  .annotate(d=TruncDate("created_at"))
                  .values("d").annotate(n=Count("id"))
                  .order_by("d"))
    labels = []
    values = []
    by_d = {r["d"]: r["n"] for r in by_day}
    for i in range(days):
        d = since.date() + timedelta(days=i)
        labels.append(d.strftime("%d.%m"))
        values.append(by_d.get(d, 0))

    # Топ-книги по кликам
    top_books = (StoreClick.objects.filter(created_at__gte=since)
                 .values("book_id", "book__title")
                 .annotate(n=Count("id"))
                 .order_by("-n")[:10])

    return {
        "days":         days,
        "sort":         sort,
        "rows":         rows,
        "total_clicks": total_clicks,
        "unique_users": StoreClick.objects.filter(created_at__gte=since, user__isnull=False)
                                         .values("user_id").distinct().count(),
        "labels":       labels,
        "values":       values,
        "top_books":    list(top_books),
    }


# ─── ТОП-КНИГИ ───────────────────────────────────────────────────────────

def books_detail(days: int = 30, q: str = "", sort: str = "score",
                 page: int = 1, page_size: int = 50) -> dict[str, Any]:
    from books.models import Book
    from reviews.models import Review, Critique
    from analytics.models import StoreClick

    since, days = parse_range(days)
    q = (q or "").strip()

    r_counts = dict(Review.objects.filter(created_at__gte=since)
                                 .values_list("book_id")
                                 .annotate(n=Count("id"))
                                 .values_list("book_id", "n"))
    c_counts = dict(Critique.objects.filter(created_at__gte=since)
                                   .values_list("book_id")
                                   .annotate(n=Count("id"))
                                   .values_list("book_id", "n"))
    click_counts = dict(StoreClick.objects.filter(created_at__gte=since)
                                         .values_list("book_id")
                                         .annotate(n=Count("id"))
                                         .values_list("book_id", "n"))

    book_ids_with_activity = set(r_counts) | set(c_counts) | set(click_counts)

    if q:
        # Поиск: ищем по всем книгам (вне зависимости от наличия активности в окне).
        # Активные метрики остаются — просто могут быть нулевыми.
        books_qs = (Book.objects
                        .filter(Q(title__icontains=q) | Q(authors__name__icontains=q))
                        .distinct()
                        .prefetch_related("authors"))
    else:
        # Без поиска: только книги с активностью за окно.
        if not book_ids_with_activity:
            return {"days": days, "q": q, "sort": sort, "page": page,
                    "rows": [], "total": 0, "page_size": page_size, "pages": 0}
        books_qs = (Book.objects
                        .filter(id__in=book_ids_with_activity)
                        .prefetch_related("authors"))

    scored = []
    for b in books_qs:
        rv = r_counts.get(b.id, 0)
        cr = c_counts.get(b.id, 0)
        ck = click_counts.get(b.id, 0)
        score = rv * 3 + cr * 5 + ck
        authors = ", ".join(a.name for a in b.authors.all()[:2]) or "—"
        scored.append({
            "id": b.id, "title": b.title, "authors": authors,
            "reviews": rv, "critiques": cr, "clicks": ck,
            "score": score, "rating": b.avg_rating, "rating_count": b.rating_count,
        })

    sort_map = {
        "score":     lambda r: -r["score"],
        "reviews":   lambda r: -r["reviews"],
        "critiques": lambda r: -r["critiques"],
        "clicks":    lambda r: -r["clicks"],
        "title":     lambda r: r["title"].lower(),
        "rating":    lambda r: -r["rating"],
    }
    scored.sort(key=sort_map.get(sort, sort_map["score"]))
    total = len(scored)
    pages = (total + page_size - 1) // page_size if total else 0
    page = max(1, min(page, max(pages, 1)))
    paged = scored[(page - 1) * page_size: page * page_size]

    return {
        "days": days, "q": q, "sort": sort, "page": page,
        "rows": paged, "total": total, "pages": pages, "page_size": page_size,
    }


# ─── МОДЕРАЦИЯ ───────────────────────────────────────────────────────────

def moderation_detail(days: int = 30, action: str = "", moderator: str = "",
                      q: str = "", page: int = 1, page_size: int = 50) -> dict[str, Any]:
    from analytics.models import ModerationLog

    since, days = parse_range(days)
    qs = ModerationLog.objects.filter(created_at__gte=since).select_related("moderator")
    if action:
        qs = qs.filter(action=action)
    if moderator:
        qs = qs.filter(moderator__username__icontains=moderator)
    if q:
        qs = qs.filter(Q(target_repr__icontains=q) | Q(note__icontains=q))

    total = qs.count()
    pages = (total + page_size - 1) // page_size if total else 0
    page = max(1, min(page, max(pages, 1)))
    paged = list(qs.order_by("-created_at")[(page - 1) * page_size: page * page_size])

    # Сводка: действия по типу + день
    by_action = dict(ModerationLog.objects.filter(created_at__gte=since)
                                          .values_list("action")
                                          .annotate(n=Count("id"))
                                          .values_list("action", "n"))
    by_day = list(ModerationLog.objects.filter(created_at__gte=since)
                                        .annotate(d=TruncDate("created_at"))
                                        .values("d", "action")
                                        .annotate(n=Count("id"))
                                        .order_by("d"))
    labels = []
    daily_total = []
    by_d: dict = {}
    for r in by_day:
        by_d.setdefault(r["d"], 0)
        by_d[r["d"]] += r["n"]
    for i in range(days):
        d = since.date() + timedelta(days=i)
        labels.append(d.strftime("%d.%m"))
        daily_total.append(by_d.get(d, 0))

    # Активные модераторы
    top_mods = (ModerationLog.objects.filter(created_at__gte=since, moderator__isnull=False)
                .values("moderator__username")
                .annotate(n=Count("id"))
                .order_by("-n"))

    # Действия для фильтра
    action_choices = ModerationLog.ACTION_CHOICES

    return {
        "days":         days,
        "action":       action,
        "moderator":    moderator,
        "q":            q,
        "page":         page,
        "pages":        pages,
        "page_size":    page_size,
        "total":        total,
        "rows":         paged,
        "by_action":    by_action,
        "labels":       labels,
        "daily_total":  daily_total,
        "top_mods":     list(top_mods),
        "action_choices": action_choices,
    }


# ─── КОГОРТЫ (расширенная) ───────────────────────────────────────────────

def cohorts_detail(cohort_count: int = 12, depth: int = 12) -> dict[str, Any]:
    """
    Расширенная версия: настраиваемые размеры сетки (по умолчанию 12×12
    вместо 8×8 на основном дашборде).
    """
    from . import cohorts as cohorts_mod
    # Подменяем глобальные для одного вызова
    old_count = cohorts_mod.COHORT_COUNT
    old_depth = cohorts_mod.COHORT_DEPTH
    cohort_count = max(2, min(cohort_count, 26))
    depth = max(2, min(depth, 26))
    cohorts_mod.COHORT_COUNT = cohort_count
    cohorts_mod.COHORT_DEPTH = depth
    try:
        data = cohorts_mod.compute_retention_cohorts()
    finally:
        cohorts_mod.COHORT_COUNT = old_count
        cohorts_mod.COHORT_DEPTH = old_depth
    data["cohort_count"] = cohort_count
    data["depth"] = depth
    return data

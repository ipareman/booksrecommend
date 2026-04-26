"""
Вычисление блоков дашборда. Разбито на функции — каждая возвращает dict,
готовый для шаблона. Всё собирается в `get_dashboard()` и кешируется целиком
на час (обновляется Celery-беком `refresh_dashboard_cache`).

Блоки:
  A — ключевые KPI (users/books/reviews/clicks) + дельты 7д/30д + спарклайны
  B — регистрации за 30 дней (большой график)
  C — воронка вовлечения: добавил → начал читать → прочёл → оценил
  D — топ-магазины по кликам
  E — топ-книги по активности
  F — модерация: pending + действия за 7 дней
  G — AI: короткая сводка + ссылка на подробности
  H — retention cohort (8×8 недели)
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from django.contrib.auth.models import User
from django.core.cache import cache
from django.db.models import Count, Q, Sum, Avg, F
from django.db.models.functions import TruncDate, TruncWeek
from django.utils import timezone


DASHBOARD_CACHE_KEY = "analytics:dashboard:v2"  # v2: добавлены labels/values для Chart.js
DASHBOARD_CACHE_TTL = 60 * 60  # 1 час; Celery-бек раз в час пересобирает


# ════════════════════════════════════════════════════════════════════════════
# ВСПОМОГАТЕЛЬНЫЕ (построение временных рядов и SVG-полилиний)
# ════════════════════════════════════════════════════════════════════════════

def _fill_series(by_day: dict[date, int], since: date, days: int) -> list[dict]:
    """Заполняет пропуски нулями — чтобы шкала была непрерывной."""
    out = []
    for i in range(days):
        d = since + timedelta(days=i)
        out.append({"date": d, "n": int(by_day.get(d, 0))})
    return out


def _sparkline(series: list[dict], w: int = 120, h: int = 28) -> dict:
    """
    Строит полилинию для SVG-спарклайна И отдельно возвращает
    raw labels/values — для рендера через Chart.js.
    """
    if not series:
        return {"points": "", "w": w, "h": h, "max": 0,
                "labels": [], "values": []}
    max_n = max((p["n"] for p in series), default=0) or 1
    n = len(series)
    pts = []
    labels = []
    values = []
    for i, p in enumerate(series):
        x = (i * w / (n - 1)) if n > 1 else w / 2
        y = h - (p["n"] / max_n) * h
        pts.append(f"{x:.1f},{y:.1f}")
        labels.append(p["date"].strftime("%d.%m"))
        values.append(int(p["n"]))
    return {"points": " ".join(pts), "w": w, "h": h, "max": max_n,
            "labels": labels, "values": values}


def _big_chart(series: list[dict], w: int = 540, h: int = 160, pad: int = 10) -> dict:
    """
    Большой линейный график с точками-hover. Возвращает pre-built SVG-данные:
      polyline, area, dots[{x,y,tip}], max_n, grid-линии.
    """
    if not series:
        return {"polyline": "", "area": "", "dots": [], "max_n": 0,
                "vb_w": w, "vb_h": h, "pad": pad}
    max_n = max((p["n"] for p in series), default=0) or 1
    n = len(series)
    iw = w - pad * 2
    ih = h - pad * 2
    pts = []
    dots = []
    for i, p in enumerate(series):
        x = pad + (i * iw / (n - 1)) if n > 1 else pad + iw / 2
        y = pad + ih - (p["n"] / max_n) * ih
        pts.append(f"{x:.1f},{y:.1f}")
        dots.append({"x": round(x, 1), "y": round(y, 1),
                     "tip": f"{p['date'].strftime('%d.%m')}: {p['n']}"})
    polyline = " ".join(pts)
    area = f"M {pad},{pad + ih} L " + " L ".join(pts) + f" L {pad + iw},{pad + ih} Z"
    return {
        "polyline": polyline, "area": area, "dots": dots, "max_n": max_n,
        "vb_w": w, "vb_h": h, "pad": pad,
    }


def _delta_pct(current: int | float, previous: int | float) -> float:
    """Процент изменения current относительно previous. Безопасно при previous=0."""
    if not previous:
        return 100.0 if current else 0.0
    return round((current - previous) / previous * 100, 1)


# ════════════════════════════════════════════════════════════════════════════
# БЛОК A — ключевые KPI
# ════════════════════════════════════════════════════════════════════════════

def compute_kpis() -> dict[str, Any]:
    """
    4 карточки-KPI: пользователи, книги, отзывы, клики по магазинам.
    Каждая — значение + тренд (дельта 7д) + спарклайн (30д).
    """
    from books.models import Book
    from reviews.models import Review, Critique
    from analytics.models import StoreClick

    now = timezone.now()
    today = now.date()
    day7  = today - timedelta(days=7)
    day14 = today - timedelta(days=14)
    day30 = today - timedelta(days=29)  # включая сегодня = 30 точек

    # ── USERS ─────────────────────────────────────────────────────────────
    users_total = User.objects.count()
    users_7d  = User.objects.filter(date_joined__date__gte=day7).count()
    users_p7d = User.objects.filter(date_joined__date__gte=day14, date_joined__date__lt=day7).count()
    users_by_day = {
        r["day"]: r["n"] for r in
        User.objects.filter(date_joined__date__gte=day30)
            .annotate(day=TruncDate("date_joined"))
            .values("day").annotate(n=Count("id"))
    }
    users_series = _fill_series(users_by_day, day30, 30)

    # ── BOOKS ─────────────────────────────────────────────────────────────
    books_total = Book.objects.count()
    books_7d  = Book.objects.filter(created_at__date__gte=day7).count()
    books_p7d = Book.objects.filter(created_at__date__gte=day14, created_at__date__lt=day7).count()
    books_by_day = {
        r["day"]: r["n"] for r in
        Book.objects.filter(created_at__date__gte=day30)
            .annotate(day=TruncDate("created_at"))
            .values("day").annotate(n=Count("id"))
    }
    books_series = _fill_series(books_by_day, day30, 30)

    # ── REVIEWS ───────────────────────────────────────────────────────────
    reviews_total = Review.objects.count() + Critique.objects.count()
    r_7d  = Review.objects.filter(created_at__date__gte=day7).count()
    c_7d  = Critique.objects.filter(created_at__date__gte=day7).count()
    reviews_7d = r_7d + c_7d
    r_p7d = Review.objects.filter(created_at__date__gte=day14, created_at__date__lt=day7).count()
    c_p7d = Critique.objects.filter(created_at__date__gte=day14, created_at__date__lt=day7).count()
    reviews_p7d = r_p7d + c_p7d

    r_by_day = {
        r["day"]: r["n"] for r in
        Review.objects.filter(created_at__date__gte=day30)
            .annotate(day=TruncDate("created_at"))
            .values("day").annotate(n=Count("id"))
    }
    c_by_day = {
        r["day"]: r["n"] for r in
        Critique.objects.filter(created_at__date__gte=day30)
            .annotate(day=TruncDate("created_at"))
            .values("day").annotate(n=Count("id"))
    }
    reviews_by_day: dict[date, int] = {}
    for d, n in r_by_day.items():
        reviews_by_day[d] = reviews_by_day.get(d, 0) + n
    for d, n in c_by_day.items():
        reviews_by_day[d] = reviews_by_day.get(d, 0) + n
    reviews_series = _fill_series(reviews_by_day, day30, 30)

    # ── CLICKS (только если модель существует и есть записи) ────────────
    clicks_total = StoreClick.objects.count()
    clicks_7d  = StoreClick.objects.filter(created_at__date__gte=day7).count()
    clicks_p7d = StoreClick.objects.filter(created_at__date__gte=day14,
                                           created_at__date__lt=day7).count()
    clicks_by_day = {
        r["day"]: r["n"] for r in
        StoreClick.objects.filter(created_at__date__gte=day30)
            .annotate(day=TruncDate("created_at"))
            .values("day").annotate(n=Count("id"))
    }
    clicks_series = _fill_series(clicks_by_day, day30, 30)

    return {
        "users": {
            "total":   users_total,
            "delta_n": users_7d - users_p7d,
            "delta_p": _delta_pct(users_7d, users_p7d),
            "recent":  users_7d,
            "spark":   _sparkline(users_series),
        },
        "books": {
            "total":   books_total,
            "delta_n": books_7d - books_p7d,
            "delta_p": _delta_pct(books_7d, books_p7d),
            "recent":  books_7d,
            "spark":   _sparkline(books_series),
        },
        "reviews": {
            "total":   reviews_total,
            "delta_n": reviews_7d - reviews_p7d,
            "delta_p": _delta_pct(reviews_7d, reviews_p7d),
            "recent":  reviews_7d,
            "spark":   _sparkline(reviews_series),
        },
        "clicks": {
            "total":   clicks_total,
            "delta_n": clicks_7d - clicks_p7d,
            "delta_p": _delta_pct(clicks_7d, clicks_p7d),
            "recent":  clicks_7d,
            "spark":   _sparkline(clicks_series),
        },
    }


# ════════════════════════════════════════════════════════════════════════════
# БЛОК B — регистрации за 30 дней (большой график)
# ════════════════════════════════════════════════════════════════════════════

def compute_registrations_chart() -> dict[str, Any]:
    today = timezone.now().date()
    since = today - timedelta(days=29)
    by_day = {
        r["day"]: r["n"] for r in
        User.objects.filter(date_joined__date__gte=since)
            .annotate(day=TruncDate("date_joined"))
            .values("day").annotate(n=Count("id"))
    }
    series = _fill_series(by_day, since, 30)
    chart  = _big_chart(series)
    return {
        "series": series,
        "total":  sum(p["n"] for p in series),
        **chart,
        "chart_labels": [p["date"].strftime("%d.%m") for p in series],
        "chart_values": [p["n"] for p in series],
    }


# ════════════════════════════════════════════════════════════════════════════
# БЛОК C — воронка вовлечения
# ════════════════════════════════════════════════════════════════════════════

def compute_funnel() -> dict[str, Any]:
    """
    Воронка за последние 30 дней:
      1. создал список (UserList.created_at)
      2. начал читать (ReadingProgress.current_page > 0, updated за окно)
      3. дочитал (current_page >= 95% pages — приближение к "finished")
      4. оставил отзыв (Review или Critique)

    Каждый шаг — уникальные пользователи. Проценты — относительно базы (шаг 1).
    """
    from books.models import UserList, ReadingProgress
    from reviews.models import Review, Critique

    since = timezone.now() - timedelta(days=30)

    # Шаг 1: создали список
    step1 = set(UserList.objects
                .filter(created_at__gte=since)
                .values_list("user_id", flat=True)
                .distinct())

    # Шаг 2: читают (есть прогресс > 0, updated за окно)
    step2 = set(ReadingProgress.objects
                .filter(updated_at__gte=since, current_page__gt=0)
                .values_list("user_id", flat=True)
                .distinct())

    # Шаг 3: дочитали (current_page >= book.pages * 0.95)
    step3 = set(ReadingProgress.objects
                .filter(updated_at__gte=since,
                        book__pages__gt=0,
                        current_page__gte=F("book__pages") * 0.95)
                .values_list("user_id", flat=True)
                .distinct())

    # Шаг 4: оставили отзыв или рецензию
    step4 = set(Review.objects.filter(created_at__gte=since)
                             .values_list("user_id", flat=True)) | \
            set(Critique.objects.filter(created_at__gte=since)
                                .values_list("user_id", flat=True))

    s1, s2, s3, s4 = len(step1), len(step2), len(step3), len(step4)
    base = max(s1, s2, 1)  # база — наибольший из s1/s2 (чтоб ширина столбиков была нормированной)

    return {
        "steps": [
            {"label": "Создали список",  "n": s1,
             "pct_base": round(s1 / base * 100, 1),
             "pct_prev": 100.0,
             "w":        s1 / base * 100},
            {"label": "Начали читать",   "n": s2,
             "pct_base": round(s2 / base * 100, 1),
             "pct_prev": round(s2 / (s1 or 1) * 100, 1),
             "w":        s2 / base * 100},
            {"label": "Дочитали",        "n": s3,
             "pct_base": round(s3 / base * 100, 1),
             "pct_prev": round(s3 / (s2 or 1) * 100, 1),
             "w":        s3 / base * 100},
            {"label": "Оставили отзыв",  "n": s4,
             "pct_base": round(s4 / base * 100, 1),
             "pct_prev": round(s4 / (s3 or 1) * 100, 1),
             "w":        s4 / base * 100},
        ],
        "window_days": 30,
        "total_users": base,
    }


# ════════════════════════════════════════════════════════════════════════════
# БЛОК D — топ-магазины по кликам
# ════════════════════════════════════════════════════════════════════════════

def compute_top_stores() -> dict[str, Any]:
    """
    Магазины по количеству кликов за 30 дней + общий total.
    """
    from analytics.models import StoreClick
    from books.models import Store

    since = timezone.now() - timedelta(days=30)
    rows = (StoreClick.objects.filter(created_at__gte=since)
            .values("store_id")
            .annotate(n=Count("id"))
            .order_by("-n")[:10])

    # Дополняем данными магазина
    store_map = {s.id: s for s in Store.objects.filter(id__in=[r["store_id"] for r in rows])}
    max_n = rows[0]["n"] if rows else 1
    out = []
    for r in rows:
        s = store_map.get(r["store_id"])
        if not s:
            continue
        out.append({
            "id": s.id,
            "name": s.name,
            "icon": s.icon or "🏪",
            "clicks": r["n"],
            "pct": round(r["n"] / max_n * 100, 1),
        })

    return {
        "rows": out,
        "total_clicks": sum(r["n"] for r in rows),
        "window_days": 30,
    }


# ════════════════════════════════════════════════════════════════════════════
# БЛОК E — топ-книги по активности
# ════════════════════════════════════════════════════════════════════════════

def compute_top_books() -> dict[str, Any]:
    """
    Топ-10 книг за 30 дней, составной score:
        score = отзывы*3 + рецензии*5 + клики по магазинам*1 + списки*0.5
    """
    from books.models import Book, UserList
    from reviews.models import Review, Critique
    from analytics.models import StoreClick

    since = timezone.now() - timedelta(days=30)

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

    # Собираем все book_id, участвовавшие
    book_ids = set(r_counts) | set(c_counts) | set(click_counts)

    scored = []
    for bid in book_ids:
        score = (r_counts.get(bid, 0) * 3
                 + c_counts.get(bid, 0) * 5
                 + click_counts.get(bid, 0) * 1)
        if score <= 0:
            continue
        scored.append((bid, score))
    scored.sort(key=lambda x: -x[1])
    scored = scored[:10]

    books_map = {b.id: b for b in Book.objects.filter(id__in=[bid for bid, _ in scored])
                                              .prefetch_related("authors")}
    rows = []
    for bid, score in scored:
        b = books_map.get(bid)
        if not b:
            continue
        authors = ", ".join(a.name for a in b.authors.all()[:2]) or "—"
        rows.append({
            "id":       b.id,
            "title":    b.title,
            "authors":  authors,
            "reviews":  r_counts.get(bid, 0),
            "critiques": c_counts.get(bid, 0),
            "clicks":   click_counts.get(bid, 0),
            "score":    int(score),
        })
    return {"rows": rows, "window_days": 30}


# ════════════════════════════════════════════════════════════════════════════
# БЛОК F — модерация
# ════════════════════════════════════════════════════════════════════════════

def compute_moderation() -> dict[str, Any]:
    """
    Сколько модерационных действий за 7 дней + топ модераторы + pending.
    """
    from reviews.models import Review, Critique
    from analytics.models import ModerationLog

    since = timezone.now() - timedelta(days=7)

    pending_reviews   = Review.objects.filter(status=Review.PENDING).count()
    pending_critiques = Critique.objects.filter(status=Critique.PENDING).count()

    # Суммарно по action за 7 дней
    by_action = {
        r["action"]: r["n"] for r in
        ModerationLog.objects.filter(created_at__gte=since)
            .values("action").annotate(n=Count("id"))
    }

    # Топ модераторов за 7 дней
    top_mods = (ModerationLog.objects.filter(created_at__gte=since, moderator__isnull=False)
                .values("moderator__username", "moderator_id")
                .annotate(n=Count("id"))
                .order_by("-n")[:5])

    return {
        "pending_reviews":   pending_reviews,
        "pending_critiques": pending_critiques,
        "pending_total":     pending_reviews + pending_critiques,
        "action_counts":     by_action,
        "total_7d":          sum(by_action.values()),
        "top_moderators":    [
            {"username": r["moderator__username"], "id": r["moderator_id"], "n": r["n"]}
            for r in top_mods
        ],
    }


# ════════════════════════════════════════════════════════════════════════════
# БЛОК G — AI (сводка, подробности в ai_admin)
# ════════════════════════════════════════════════════════════════════════════

def compute_ai_summary() -> dict[str, Any]:
    """
    Короткая сводка по AIUsageLog за 7 дней:
      - вызовов всего / ошибок / токенов / средняя задержка.
    Подробная аналитика — в /ai/admin/.
    """
    try:
        from ai_admin.models import AIUsageLog
    except ImportError:
        return {"enabled": False}

    since = timezone.now() - timedelta(days=7)
    qs = AIUsageLog.objects.filter(created_at__gte=since)
    agg = qs.aggregate(
        n=Count("id"),
        tokens=Sum("total_tokens"),
        avg_latency=Avg("latency_ms"),
    )
    errors = qs.filter(status__in=["error", "rate_limit"]).count()
    return {
        "enabled":     True,
        "total":       agg["n"] or 0,
        "errors":      errors,
        "error_rate":  round(errors / (agg["n"] or 1) * 100, 1),
        "tokens":      int(agg["tokens"] or 0),
        "avg_latency": int(agg["avg_latency"] or 0),
        "window_days": 7,
    }


# ════════════════════════════════════════════════════════════════════════════
# УМБРЕЛЬНАЯ ФУНКЦИЯ: собирает всё, кеширует целиком
# ════════════════════════════════════════════════════════════════════════════

def build_dashboard() -> dict[str, Any]:
    """
    Собирает все блоки заново. Возвращает dict для шаблона.
    Тяжёлая функция: гоняется Celery-беком, результат кладётся в кеш.
    """
    import json
    from .cohorts import compute_retention_cohorts

    kpis           = compute_kpis()
    registrations  = compute_registrations_chart()

    # Заранее сериализуем JSON-блоб для Chart.js — чтобы в шаблоне не
    # бороться с Python-str()-форматом списков (одинарные кавычки → не JSON).
    chart_payload = json.dumps({
        "reg": {
            "labels": registrations.get("chart_labels", []),
            "values": registrations.get("chart_values", []),
        },
        "sparks": {
            k: {"labels": v["spark"].get("labels", []),
                "values": v["spark"].get("values", [])}
            for k, v in kpis.items()
        },
    }, ensure_ascii=False)

    return {
        "kpis":          kpis,
        "registrations": registrations,
        "funnel":        compute_funnel(),
        "stores":        compute_top_stores(),
        "top_books":     compute_top_books(),
        "moderation":    compute_moderation(),
        "ai":            compute_ai_summary(),
        "cohorts":       compute_retention_cohorts(),
        "generated_at":  timezone.now().isoformat(),
        "chart_js_payload": chart_payload,
    }


def get_dashboard(*, force_refresh: bool = False) -> dict[str, Any]:
    """
    Кеш-обёртка. Быстрая: читаем кеш, если холодный — строим (редкий путь).
    В проде прогреется Celery-беком.
    """
    if not force_refresh:
        cached = cache.get(DASHBOARD_CACHE_KEY)
        if cached:
            cached["from_cache"] = True
            return cached

    data = build_dashboard()
    data["from_cache"] = False
    cache.set(DASHBOARD_CACHE_KEY, data, DASHBOARD_CACHE_TTL)
    return data


def invalidate_dashboard() -> None:
    cache.delete(DASHBOARD_CACHE_KEY)

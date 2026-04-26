"""
Сбор данных для публичного профиля пользователя.

Весь код тут — read-only агрегаты, безопасные к вызову на чужом профиле:
никаких изменений БД, никаких LLM-вызовов.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import timedelta

from django.db.models import Avg, Count, F, Q, Sum
from django.utils import timezone


# ── СТАТИСТИКА ────────────────────────────────────────────────────────────────

def build_profile_stats(user) -> dict:
    """Сводные числа-якоря для шапки профиля."""
    from books.models import UserList, ReadingProgress, Book
    from reviews.models import Review

    # Книги «прочитано»: ReadingProgress завершён ИЛИ положительные/нейтральные списки
    finished_progress_ids = set(
        ReadingProgress.objects
        .filter(user=user, current_page__gt=0, book__pages__gt=0)
        .filter(current_page__gte=F("book__pages"))
        .values_list("book_id", flat=True)
    )
    # Плюс книги из положительных списков (их «посчитано как прочитано»)
    positive_list_books = set(
        Book.objects
        .filter(
            in_lists__user=user,
            in_lists__sentiment_tag__in=("positive", "neutral"),
        )
        .values_list("pk", flat=True)
    )
    books_read = len(finished_progress_ids | positive_list_books)

    pages_read = ReadingProgress.objects.filter(user=user).aggregate(
        total=Sum("current_page")
    )["total"] or 0

    reviews_qs = Review.objects.filter(user=user, status=Review.APPROVED)
    reviews_count = reviews_qs.count()
    avg_rating = reviews_qs.aggregate(a=Avg("rating"))["a"]

    lists_count = UserList.objects.filter(user=user).count()

    return {
        "books_read":    books_read,
        "pages_read":    pages_read,
        "reviews_count": reviews_count,
        "avg_rating":    round(avg_rating, 1) if avg_rating else None,
        "lists_count":   lists_count,
    }


def build_reader_rank(stats: dict) -> dict:
    """
    Звание читателя на основе статистики.
    Возвращает {title, icon, next_title, progress_percent, next_need}.
    """
    books = stats["books_read"]
    reviews = stats["reviews_count"]
    # Шкала по сумме книг + 2*отзывы (отзыв «ценится» больше, чем просто добавление)
    score = books + reviews * 2

    ranks = [
        (0,    "🌱", "Новичок"),
        (5,    "📖", "Читатель"),
        (20,   "📚", "Книголюб"),
        (50,   "🎓", "Знаток"),
        (100,  "🏆", "Библиофил"),
        (250,  "👑", "Мастер слова"),
    ]
    current = ranks[0]
    nxt = None
    for i, r in enumerate(ranks):
        if score >= r[0]:
            current = r
            nxt = ranks[i + 1] if i + 1 < len(ranks) else None
        else:
            break

    if nxt:
        span = nxt[0] - current[0]
        progress = int((score - current[0]) * 100 / span) if span else 100
        return {
            "title":   current[2],
            "icon":    current[1],
            "next_title": nxt[2],
            "next_need":  max(nxt[0] - score, 0),
            "progress_percent": max(0, min(100, progress)),
            "score":   score,
        }
    return {
        "title":   current[2],
        "icon":    current[1],
        "next_title": None,
        "next_need":  0,
        "progress_percent": 100,
        "score":   score,
    }


# ── ПОЛКИ «СЕЙЧАС ЧИТАЕТ» / «ТОЛЬКО ЧТО ЗАКОНЧИЛ» ────────────────────────────

def build_current_reading(user, limit: int = 3) -> list[dict]:
    """Активно читаемые книги: ReadingProgress с прогрессом, но не завершён."""
    from books.models import ReadingProgress

    qs = (
        ReadingProgress.objects
        .filter(user=user, current_page__gt=0)
        .select_related("book")
        .prefetch_related("book__authors")
        .order_by("-updated_at")
    )
    out = []
    for rp in qs:
        if not rp.book.pages or rp.current_page >= rp.book.pages:
            continue  # уже закончил — в другой блок
        out.append({
            "book":         rp.book,
            "current_page": rp.current_page,
            "total_pages":  rp.book.pages or 0,
            "percent":      rp.percent(),
            "updated_at":   rp.updated_at,
        })
        if len(out) >= limit:
            break
    return out


def build_recent_finished(user, limit: int = 3) -> list[dict]:
    """Недавно закончил читать: ReadingProgress где current_page ≥ book.pages."""
    from books.models import ReadingProgress

    qs = (
        ReadingProgress.objects
        .filter(user=user, current_page__gt=0, book__pages__gt=0)
        .filter(current_page__gte=F("book__pages"))
        .select_related("book")
        .prefetch_related("book__authors")
        .order_by("-updated_at")[:limit]
    )
    return [{"book": rp.book, "finished_at": rp.updated_at} for rp in qs]


# ── ВКУС: ЖАНРЫ / НАСТРОЕНИЯ ─────────────────────────────────────────────────

def build_genre_breakdown(user, limit: int = 5) -> list[dict]:
    """
    Распределение жанров по книгам из положительных/нейтральных списков.
    Возвращает [{name, count, percent}].
    """
    from books.models import Genre

    rows = (
        Genre.objects
        .filter(
            books__in_lists__user=user,
            books__in_lists__sentiment_tag__in=("positive", "neutral"),
        )
        .annotate(cnt=Count("books", distinct=True))
        .filter(cnt__gt=0)
        .order_by("-cnt")[:limit]
    )
    rows = list(rows)
    total = sum(r.cnt for r in rows) or 1
    return [
        {"name": r.name, "count": r.cnt, "percent": round(r.cnt * 100 / total)}
        for r in rows
    ]


def build_mood_profile(user, limit: int = 6) -> list[dict]:
    """
    Топ настроений пользователя — какие moods встречаются у книг из
    положительных списков.  Использует BookMood-through.
    """
    from books.models import BookMood

    rows = (
        BookMood.objects
        .filter(
            book__in_lists__user=user,
            book__in_lists__sentiment_tag__in=("positive", "neutral"),
        )
        .values("mood__id", "mood__name", "mood__icon", "mood__category")
        .annotate(cnt=Count("book", distinct=True))
        .order_by("-cnt")[:limit]
    )
    return [
        {
            "id":       r["mood__id"],
            "name":     r["mood__name"],
            "icon":     r["mood__icon"] or "",
            "category": r["mood__category"],
            "count":    r["cnt"],
        }
        for r in rows
    ]


def build_rating_histogram(user) -> list[dict]:
    """
    Гистограмма выставленных оценок. [{stars, count, percent_of_max}]
    от 5 до 1 (порядок удобный для шаблона).
    """
    from reviews.models import Review

    counts = dict(
        Review.objects
        .filter(user=user, status=Review.APPROVED)
        .values_list("rating")
        .annotate(c=Count("rating"))
        .values_list("rating", "c")
    )
    max_c = max(counts.values()) if counts else 1
    out = []
    for star in (5, 4, 3, 2, 1):
        c = counts.get(star, 0)
        out.append({
            "stars":          star,
            "stars_display":  "★" * star,
            "count":          c,
            "percent_of_max": int(c * 100 / max_c) if max_c else 0,
        })
    return out


# ── АКТИВНОСТЬ: ХИТМАП + СТРИК ───────────────────────────────────────────────

def build_activity_heatmap(user, days: int = 183) -> dict:
    """
    Возвращает {
      "weeks": [[{
         "date": date, "count": int, "level": 0..4,
         "in_range": bool,
         "events":   [ {"time": "HH:MM", "text": str, "icon": str}, ... ],
         "overflow": int,  # сколько событий не влезло в events
      }, ...7...], ...],
      "total_actions": int,
      "days": int,
    }
    Подсчёт событий ведётся из:
      - ActivityEvent.created_at  (добавление в список, рекомендация и т.д.)
      - ReadingProgress.updated_at (значимое изменение — читал в этот день)
      - Review.created_at (опубликованный отзыв)
    """
    from reviews.models import Review
    from books.models import ReadingProgress

    today = timezone.localdate()
    start = today - timedelta(days=days - 1)

    # bucket: date -> list[(datetime_local, icon, text)]
    bucket: dict = defaultdict(list)

    def _add(dt, icon: str, text: str):
        """Добавить событие в бакет соответствующего дня."""
        local = timezone.localtime(dt)
        bucket[local.date()].append((local, icon, text))

    # ── ActivityEvent (если social установлен) ──
    try:
        from social.models import ActivityEvent
        act_qs = (
            ActivityEvent.objects
            .filter(user=user, created_at__date__gte=start)
            .select_related("book", "target_user")
        )
        event_type_labels = {
            "add_to_list":     ("📚", "Добавил(а) в список"),
            "review":          ("✍",  "Написал(а) отзыв"),
            "join_club":       ("👥", "Вступил(а) в клуб"),
            "new_friendship":  ("🤝", "Добавил(а) друга"),
            "book_recommend":  ("💡", "Порекомендовал(а)"),
        }
        for ev in act_qs:
            icon, verb = event_type_labels.get(ev.event_type, ("•", ev.get_event_type_display()))
            if ev.book_id:
                text = f"{verb}: «{ev.book.title}»"
            elif ev.target_user_id:
                text = f"{verb}: {ev.target_user.username}"
            else:
                text = verb
            _add(ev.created_at, icon, text)
    except Exception:
        pass

    # ── Отзывы ──
    review_qs = (
        Review.objects
        .filter(user=user, created_at__date__gte=start)
        .select_related("book")
    )
    for r in review_qs:
        text = f"Отзыв: «{r.book.title}» — ★{r.rating}/5"
        _add(r.created_at, "⭐", text)

    # ── Прогресс чтения ──
    rp_qs = (
        ReadingProgress.objects
        .filter(user=user, updated_at__date__gte=start)
        .select_related("book", "current_chapter")
    )
    for rp in rp_qs:
        pct = rp.percent()
        if rp.current_chapter_id and rp.current_chapter:
            detail = f"гл. {rp.current_chapter.order + 1}"
        elif rp.book.pages:
            detail = f"стр. {rp.current_page}/{rp.book.pages}"
        else:
            detail = f"{pct}%"
        text = f"Чтение: «{rp.book.title}» — {detail}"
        _add(rp.updated_at, "📖", text)

    # ── Упаковываем в недели-колонки (Пн..Вс) ──
    MAX_EVENTS_PER_DAY = 8  # сколько показывать в тултипе, остальные — "…и ещё N"
    weekday = start.weekday()
    col_start = start - timedelta(days=weekday)

    weeks: list[list[dict]] = []
    cursor = col_start
    total = 0
    while cursor <= today:
        week = []
        for _ in range(7):
            in_range = start <= cursor <= today
            day_events_raw = bucket.get(cursor, []) if in_range else []
            # Сортируем события внутри дня по времени (новее сверху читаемее)
            day_events_raw.sort(key=lambda e: e[0])
            c = len(day_events_raw)
            total += c
            events_slim = [
                {"time": e[0].strftime("%H:%M"), "icon": e[1], "text": e[2]}
                for e in day_events_raw[:MAX_EVENTS_PER_DAY]
            ]
            overflow = max(0, c - MAX_EVENTS_PER_DAY)
            week.append({
                "date":     cursor,
                "count":    c,
                "level":    _heatmap_level(c),
                "in_range": in_range,
                "events":   events_slim,
                "overflow": overflow,
            })
            cursor += timedelta(days=1)
        weeks.append(week)

    return {
        "weeks":         weeks,
        "total_actions": total,
        "days":          days,
    }


def _heatmap_level(count: int) -> int:
    if count == 0: return 0
    if count == 1: return 1
    if count <= 3: return 2
    if count <= 7: return 3
    return 4


def build_reading_streak(user) -> dict:
    """
    Стрик — сколько дней подряд была хоть какая-то активность
    (отзыв / обновление прогресса / ActivityEvent).
    Возвращает {current: int, longest: int}.
    """
    from reviews.models import Review
    from books.models import ReadingProgress

    days: set = set()
    for d in Review.objects.filter(user=user).values_list("created_at", flat=True):
        days.add(timezone.localtime(d).date())
    for d in ReadingProgress.objects.filter(user=user).values_list("updated_at", flat=True):
        days.add(timezone.localtime(d).date())
    try:
        from social.models import ActivityEvent
        for d in ActivityEvent.objects.filter(user=user).values_list("created_at", flat=True):
            days.add(timezone.localtime(d).date())
    except Exception:
        pass

    if not days:
        return {"current": 0, "longest": 0}

    sorted_days = sorted(days)

    # Максимальный стрик
    longest = 1
    cur = 1
    for i in range(1, len(sorted_days)):
        if (sorted_days[i] - sorted_days[i - 1]).days == 1:
            cur += 1
            longest = max(longest, cur)
        else:
            cur = 1

    # Текущий — считаем до сегодня или вчера (если сегодня пусто)
    today = timezone.localdate()
    current = 0
    cursor = today
    if cursor not in days:
        cursor -= timedelta(days=1)
    while cursor in days:
        current += 1
        cursor -= timedelta(days=1)

    return {"current": current, "longest": longest}


# ── СОЦИАЛЬНОЕ ───────────────────────────────────────────────────────────────

def build_social_snapshot(target_user, limit: int = 6) -> dict:
    """Друзья (ограниченный список), клубы, подписки на авторов."""
    try:
        from social.helpers import get_friends
        friends_qs = get_friends(target_user)
        friends_count = friends_qs.count()
        friends_preview = list(friends_qs[:limit])
    except Exception:
        friends_count = 0
        friends_preview = []

    clubs = []
    try:
        from clubs.models import ClubMembership
        clubs = list(
            ClubMembership.objects
            .filter(user=target_user)
            .select_related("club")[:limit]
        )
    except Exception:
        pass

    author_subs = list(
        target_user.author_subscriptions
        .select_related("author")
        .order_by("-created_at")[:limit * 2]
    )

    return {
        "friends_count":   friends_count,
        "friends_preview": friends_preview,
        "clubs":           clubs,
        "author_subs":     author_subs,
    }


def common_books_with(target_user, viewer, limit: int = 4) -> dict:
    """
    Пересечение: книги в положительных списках у обоих пользователей.
    Возвращает {count, preview: [Book, ...]}.
    """
    if not viewer or not viewer.is_authenticated or viewer == target_user:
        return {"count": 0, "preview": []}

    from books.models import Book

    target_ids = set(
        Book.objects
        .filter(
            in_lists__user=target_user,
            in_lists__sentiment_tag__in=("positive", "neutral", "wishlist"),
        )
        .values_list("pk", flat=True)
    )
    if not target_ids:
        return {"count": 0, "preview": []}

    common = list(
        Book.objects
        .filter(pk__in=target_ids)
        .filter(
            in_lists__user=viewer,
            in_lists__sentiment_tag__in=("positive", "neutral", "wishlist"),
        )
        .distinct()
        .prefetch_related("authors")
        .order_by("-avg_rating")
    )
    return {
        "count":   len(common),
        "preview": common[:limit],
    }


# ── КОНТЕНТ: ЦИТАТЫ / КРИТИКИ / КОЛЛЕКЦИИ ────────────────────────────────────

def build_user_quotes(target_user, limit: int = 6):
    from books.models import Quote
    return (
        Quote.objects
        .filter(user=target_user, is_ai_generated=False)
        .select_related("book")
        .order_by("-created_at")[:limit]
    )


def build_user_critiques(target_user, limit: int = 6):
    from reviews.models import Critique
    return (
        Critique.objects
        .filter(user=target_user, status=Critique.APPROVED)
        .select_related("book")
        .order_by("-created_at")[:limit]
    )


def build_user_collections(target_user, limit: int = 6):
    try:
        from curated.models import Collection
    except Exception:
        return []
    return list(
        Collection.objects
        .filter(created_by=target_user, is_published=True)
        .order_by("-id")[:limit]
    )


# ── СВОДКА ДЛЯ ШАБЛОНА ───────────────────────────────────────────────────────

def build_public_profile_context(target_user, viewer=None) -> dict:
    """
    Одна точка входа — собирает весь контекст публичного профиля.
    Безопасно вызывать и для неавторизованного зрителя (viewer=None).
    """
    stats = build_profile_stats(target_user)
    ctx = {
        "stats":              stats,
        "reader_rank":        build_reader_rank(stats),
        "current_reading":    build_current_reading(target_user),
        "recent_finished":    build_recent_finished(target_user),
        "genre_breakdown":    build_genre_breakdown(target_user),
        "mood_profile":       build_mood_profile(target_user),
        "rating_histogram":   build_rating_histogram(target_user),
        "activity_heatmap":   build_activity_heatmap(target_user),
        "reading_streak":     build_reading_streak(target_user),
        "social_snapshot":    build_social_snapshot(target_user),
        "common_books":       common_books_with(target_user, viewer),
        "public_quotes":      build_user_quotes(target_user),
        "public_critiques":   build_user_critiques(target_user),
        "public_collections": build_user_collections(target_user),
    }
    return ctx

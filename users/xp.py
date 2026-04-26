"""
Геймификация: XP, уровни, лидерборд.

Принцип — XP вычисляется НА ЛЕТУ из существующих сущностей, без отдельного поля
в БД. Это исключает рассинхронизацию (например, забыли инкрементить при создании
рецензии) и не требует миграции / сигналов на каждое действие. Цена — пересчёт
при каждом запросе, но запросы агрегатные, кэшируем при необходимости.

Правила (из плана):
  • +10 XP — одобренная рецензия (Review APPROVED)
  • +0.1 XP — каждая прочитанная страница (по ReadingProgress)
  • +1 XP — каждый лайк, полученный на твою рецензию
  • +2 XP — каждая книга в любом списке (UserList)
  • +25 XP — каждое полученное достижение

Кривая уровней:
  level(xp) = floor(sqrt(xp / 50)) + 1
  → Lv 1: 0 XP, Lv 2: 50, Lv 3: 200, Lv 4: 450, Lv 5: 800, Lv 10: 4050, Lv 20: 18050
"""
from __future__ import annotations

import math
from django.contrib.auth.models import User
from django.db.models import Count, Sum, F, Value, FloatField, IntegerField
from django.db.models.functions import Coalesce


XP_PER_REVIEW       = 10
XP_PER_PAGE         = 0.1
XP_PER_LIKE         = 1
XP_PER_BOOK_IN_LIST = 2
XP_PER_ACHIEVEMENT  = 25


def compute_xp_components(user: User) -> dict:
    """Разбиение XP по источникам — для прогресс-бара / профиля / тултипа."""
    from books.models import UserList, ReadingProgress
    from reviews.models import Review, ReviewLike
    from .models import Achievement

    review_count = Review.objects.filter(user=user, status=Review.APPROVED).count()
    pages_read = (
        ReadingProgress.objects.filter(user=user)
        .aggregate(total=Sum("current_page"))["total"] or 0
    )
    likes_received = ReviewLike.objects.filter(review__user=user).count()
    books_in_lists = (
        UserList.objects.filter(user=user)
        .values("books").distinct().count()
    )
    achievements_count = Achievement.objects.filter(user=user).count()

    return {
        "reviews":       review_count       * XP_PER_REVIEW,
        "pages":         int(pages_read     * XP_PER_PAGE),
        "likes":         likes_received     * XP_PER_LIKE,
        "books":         books_in_lists     * XP_PER_BOOK_IN_LIST,
        "achievements":  achievements_count * XP_PER_ACHIEVEMENT,
        # Сырые значения для отображения «5 рецензий = 50 XP»
        "_review_count":       review_count,
        "_pages_read":         pages_read,
        "_likes_received":     likes_received,
        "_books_in_lists":     books_in_lists,
        "_achievements_count": achievements_count,
    }


def compute_xp(user: User) -> int:
    """Суммарный XP пользователя."""
    c = compute_xp_components(user)
    return c["reviews"] + c["pages"] + c["likes"] + c["books"] + c["achievements"]


def level_for_xp(xp: int) -> int:
    """Уровень по XP. Кривая: каждый следующий уровень дороже квадратично."""
    if xp < 0:
        return 1
    return int(math.floor(math.sqrt(xp / 50))) + 1


def xp_for_level(level: int) -> int:
    """Сколько XP нужно для достижения уровня `level` (порог)."""
    if level <= 1:
        return 0
    return (level - 1) ** 2 * 50


def level_progress(xp: int) -> dict:
    """
    Прогресс внутри текущего уровня.
    {level, xp, xp_floor, xp_ceiling, xp_into_level, xp_to_next, percent}
    """
    lvl = level_for_xp(xp)
    floor_xp = xp_for_level(lvl)
    ceil_xp = xp_for_level(lvl + 1)
    span = max(ceil_xp - floor_xp, 1)
    into = max(xp - floor_xp, 0)
    return {
        "level":         lvl,
        "xp":            xp,
        "xp_floor":      floor_xp,
        "xp_ceiling":    ceil_xp,
        "xp_into_level": into,
        "xp_to_next":    max(ceil_xp - xp, 0),
        "percent":       min(100, int(into * 100 / span)),
    }


def leaderboard(limit: int = 20) -> list[dict]:
    """
    Топ-N пользователей по XP. Считаем агрегатно — одним запросом, без
    Python-цикла compute_xp на каждого, чтобы лидерборд работал и для 10k юзеров.

    Возвращает список словарей:
        {user, xp, level, components: {reviews, pages, likes, books, achievements}}
    """
    # ВАЖНО: related_name'ы — см. reviews/models.py и books/models.py.
    # User.reviews = его рецензии (Review.user related_name="reviews").
    # User.reading_progress = прогресс по книгам.
    # User.book_lists = его списки.
    # Лайки получены = `reviews__likes` (Review.likes от ReviewLike).
    qs = (
        User.objects
        .filter(is_active=True)
        .annotate(
            _reviews_xp=Coalesce(
                Count(
                    "reviews",
                    filter=models_q_review_approved(),
                    distinct=True,
                ) * XP_PER_REVIEW,
                Value(0),
            ),
            _pages_xp=Coalesce(
                Sum("reading_progress__current_page", output_field=IntegerField()) * XP_PER_PAGE,
                Value(0.0),
                output_field=FloatField(),
            ),
            _likes_xp=Coalesce(
                Count("reviews__likes", distinct=True) * XP_PER_LIKE,
                Value(0),
            ),
            _books_xp=Coalesce(
                Count("book_lists__books", distinct=True) * XP_PER_BOOK_IN_LIST,
                Value(0),
            ),
            _ach_xp=Coalesce(
                Count("achievements", distinct=True) * XP_PER_ACHIEVEMENT,
                Value(0),
            ),
        )
    )

    # XP считаем в Python — складывать FloatField и IntegerField в SQL annotation
    # неудобно из-за CombinedExpression в разных бэкендах.
    rows = []
    for u in qs:
        xp = int(
            (u._reviews_xp or 0)
            + (u._pages_xp or 0)
            + (u._likes_xp or 0)
            + (u._books_xp or 0)
            + (u._ach_xp or 0)
        )
        rows.append({
            "user":  u,
            "xp":    xp,
            "level": level_for_xp(xp),
            "components": {
                "reviews":      int(u._reviews_xp or 0),
                "pages":        int(u._pages_xp or 0),
                "likes":        int(u._likes_xp or 0),
                "books":        int(u._books_xp or 0),
                "achievements": int(u._ach_xp or 0),
            },
        })
    rows.sort(key=lambda r: r["xp"], reverse=True)
    return rows[:limit]


def models_q_review_approved():
    """
    Q-фильтр для Count(reviews, filter=APPROVED).
    Импорт Review лениво, чтобы избежать circular imports на старте.
    """
    from django.db.models import Q
    from reviews.models import Review
    return Q(reviews__status=Review.APPROVED)

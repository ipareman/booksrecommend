"""
Joint Recommendations — книги на пересечении вкусов двух пользователей.
"""

from collections import defaultdict

from django.db.models import Q

from .models import Book, UserList


def joint_recommendations(user1, user2, limit=5) -> list[dict]:
    """
    Рекомендации для двух пользователей на пересечении вкусов.
    Возвращает: [{book, compatibility_score}]
    """
    # Собираем профили жанров и авторов
    genres1 = _get_genre_profile(user1)
    genres2 = _get_genre_profile(user2)
    authors1 = _get_author_profile(user1)
    authors2 = _get_author_profile(user2)

    # Пересечение жанров (произведение весов)
    joint_genres = {}
    for genre_id in set(genres1.keys()) & set(genres2.keys()):
        joint_genres[genre_id] = genres1[genre_id] * genres2[genre_id]

    joint_authors = {}
    for author_id in set(authors1.keys()) & set(authors2.keys()):
        joint_authors[author_id] = authors1[author_id] * authors2[author_id]

    if not joint_genres and not joint_authors:
        # Fallback: нет пересечений — используем top-rated
        return _fallback_recommendations(user1, user2, limit)

    # Книги обоих пользователей (для исключения)
    read_ids = set(
        UserList.objects.filter(user=user1).values_list("books__pk", flat=True)
    ) | set(
        UserList.objects.filter(user=user2).values_list("books__pk", flat=True)
    )
    read_ids.discard(None)

    # Кандидаты: книги в пересекающихся жанрах/авторах
    candidates = (
        Book.objects
        .exclude(pk__in=read_ids)
        .prefetch_related("authors", "genres")
        .filter(
            Q(genres__pk__in=joint_genres.keys()) |
            Q(authors__pk__in=joint_authors.keys())
        )
        .distinct()
        .order_by("-avg_rating")[:100]
    )

    # Scoring
    scored = []
    for book in candidates:
        score = 0.0
        for g in book.genres.all():
            score += joint_genres.get(g.pk, 0) * 3
        for a in book.authors.all():
            score += joint_authors.get(a.pk, 0) * 4
        score += (book.avg_rating or 0) * 0.5
        scored.append({"book": book, "compatibility_score": round(score, 2)})

    scored.sort(key=lambda x: x["compatibility_score"], reverse=True)
    return scored[:limit]


def _get_genre_profile(user) -> dict:
    """Возвращает {genre_id: weight} для пользователя."""
    weights = defaultdict(float)
    lists = UserList.objects.filter(user=user).prefetch_related("books__genres")
    for ul in lists:
        sentiment_w = {"positive": 1.0, "wishlist": 0.6, "neutral": 0.4}.get(ul.sentiment_tag, 0.3)
        for book in ul.books.all():
            for genre in book.genres.all():
                weights[genre.pk] += sentiment_w
    return dict(weights)


def _get_author_profile(user) -> dict:
    """Возвращает {author_id: weight} для пользователя."""
    weights = defaultdict(float)
    lists = UserList.objects.filter(user=user).prefetch_related("books__authors")
    for ul in lists:
        sentiment_w = {"positive": 1.0, "wishlist": 0.6, "neutral": 0.4}.get(ul.sentiment_tag, 0.3)
        for book in ul.books.all():
            for author in book.authors.all():
                weights[author.pk] += sentiment_w
    return dict(weights)


def _fallback_recommendations(user1, user2, limit) -> list[dict]:
    """Если нет пересечений — просто top-rated минус прочитанное."""
    read_ids = set(
        UserList.objects.filter(user=user1).values_list("books__pk", flat=True)
    ) | set(
        UserList.objects.filter(user=user2).values_list("books__pk", flat=True)
    )
    read_ids.discard(None)

    books = (
        Book.objects
        .exclude(pk__in=read_ids)
        .prefetch_related("authors", "genres")
        .order_by("-avg_rating", "-rating_count")[:limit]
    )
    return [{"book": b, "compatibility_score": float(b.avg_rating or 0)} for b in books]

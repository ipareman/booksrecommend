"""
Сборка единой ленты активности пользователя для публичного профиля.

Источники:
- reviews.Review  (status=approved)  — «написал отзыв на X»
- reviews.Critique (status=approved) — «написал рецензию на X»
- reviews.CritiqueComment — «прокомментировал рецензию»
- reviews.ReviewLike — «отметил отзыв полезным»
- reviews.CritiqueLike — «поставил лайк рецензии»
- social.Friendship (status=accepted) — «подружился с X»
- social.BookRecommendation — «рекомендовал книгу X другу Y»
- social.ActivityEvent — add_to_list, join_club (прочие эмитят отдельные блоки)
- clubs.ClubMembership — «вступил в клуб X» (дубли с ActivityEvent возможны, берём
  оба источника и дедупим по (user, club, date) в рамках join_club)

Все элементы приводятся к dict-виду:
    {
        "kind":       "review" | "critique" | "comment" | "review_like" |
                      "critique_like" | "friendship" | "recommend" |
                      "add_to_list" | "join_club",
        "date":       datetime,
        "category":   "reviews" | "critiques" | "comments" | "likes" |
                      "social" | "books" | "clubs",
        "obj":        исходный объект (для шаблона),
    }

Фильтруются публично-видимые вещи:
- Review / Critique берём только со status=APPROVED
- Комментарии — только к approved-критикам
- Лайки — на approved-контент
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime
from typing import Iterable, List, Dict, Any, Optional

from django.core.paginator import Paginator

from reviews.models import (
    Review, Critique, CritiqueComment, ReviewLike, CritiqueLike,
)
from social.models import Friendship, BookRecommendation, ActivityEvent


# Категории для UI-фильтров (left=internal, right=russian label)
CATEGORIES: list[tuple[str, str]] = [
    ("all",       "Всё"),
    ("reviews",   "Отзывы"),
    ("critiques", "Рецензии"),
    ("comments",  "Комментарии"),
    ("likes",     "Лайки"),
    ("books",     "Книги"),
    ("social",    "Социальное"),
    ("clubs",     "Клубы"),
]

# kind → category, строго соответствует CATEGORIES
KIND_TO_CATEGORY: Dict[str, str] = {
    "review":         "reviews",
    "critique":       "critiques",
    "comment":        "comments",
    "review_like":    "likes",
    "critique_like":  "likes",
    "friendship":     "social",
    "recommend":      "social",
    "add_to_list":    "books",
    "join_club":      "clubs",
}


def _collect_reviews(user) -> Iterable[Dict[str, Any]]:
    qs = (
        Review.objects
        .filter(user=user, status=Review.APPROVED)
        .select_related("book")
        .order_by("-created_at")
    )
    for r in qs:
        yield {
            "kind": "review",
            "date": r.created_at,
            "category": "reviews",
            "obj": r,
        }


def _collect_critiques(user) -> Iterable[Dict[str, Any]]:
    qs = (
        Critique.objects
        .filter(user=user, status=Critique.APPROVED)
        .select_related("book")
        .order_by("-created_at")
    )
    for c in qs:
        yield {
            "kind": "critique",
            "date": c.created_at,
            "category": "critiques",
            "obj": c,
        }


def _collect_comments(user) -> Iterable[Dict[str, Any]]:
    qs = (
        CritiqueComment.objects
        .filter(user=user, critique__status=Critique.APPROVED)
        .select_related("critique", "critique__book", "parent", "parent__user")
        .order_by("-created_at")
    )
    for c in qs:
        yield {
            "kind": "comment",
            "date": c.created_at,
            "category": "comments",
            "obj": c,
        }


def _collect_review_likes(user) -> Iterable[Dict[str, Any]]:
    qs = (
        ReviewLike.objects
        .filter(user=user, review__status=Review.APPROVED)
        .select_related("review", "review__book", "review__user")
        .order_by("-created_at")
    )
    for like in qs:
        yield {
            "kind": "review_like",
            "date": like.created_at,
            "category": "likes",
            "obj": like,
        }


def _collect_critique_likes(user) -> Iterable[Dict[str, Any]]:
    qs = (
        CritiqueLike.objects
        .filter(user=user, critique__status=Critique.APPROVED)
        .select_related("critique", "critique__book", "critique__user")
        .order_by("-created_at")
    )
    for like in qs:
        yield {
            "kind": "critique_like",
            "date": like.created_at,
            "category": "likes",
            "obj": like,
        }


def _collect_friendships(user) -> Iterable[Dict[str, Any]]:
    qs = (
        Friendship.objects
        .filter(status="accepted")
        .filter(**{})  # placeholder, ниже через Q
    )
    from django.db.models import Q
    qs = (
        Friendship.objects
        .filter(status="accepted")
        .filter(Q(from_user=user) | Q(to_user=user))
        .select_related("from_user", "to_user")
        .order_by("-created_at")
    )
    for fs in qs:
        yield {
            "kind": "friendship",
            "date": fs.created_at,
            "category": "social",
            "obj": fs,
            # удобная ссылка «с кем подружился»
            "other_user": fs.to_user if fs.from_user_id == user.pk else fs.from_user,
        }


def _collect_recommendations(user) -> Iterable[Dict[str, Any]]:
    """Только ОТПРАВЛЕННЫЕ рекомендации — публично видимое действие."""
    qs = (
        BookRecommendation.objects
        .filter(from_user=user)
        .select_related("book", "to_user")
        .order_by("-created_at")
    )
    for rec in qs:
        yield {
            "kind": "recommend",
            "date": rec.created_at,
            "category": "social",
            "obj": rec,
        }


def _collect_activity_events(user) -> Iterable[Dict[str, Any]]:
    """
    Берём из ActivityEvent только те, что не покрыты другими коллекторами:
    - add_to_list   (нет отдельной модели «добавление в список» с public-статусом)
    - join_club     (покрытие клубов)

    review / new_friendship / book_recommend игнорируем — чтобы не дублировать
    события, которые уже приходят из Review / Friendship / BookRecommendation.
    """
    qs = (
        ActivityEvent.objects
        .filter(user=user, event_type__in=("add_to_list", "join_club"))
        .select_related("book")
        .order_by("-created_at")
    )
    for ev in qs:
        kind = ev.event_type  # совпадает с ключом
        yield {
            "kind": kind,
            "date": ev.created_at,
            "category": KIND_TO_CATEGORY.get(kind, "books"),
            "obj": ev,
        }


def _collect_all(user) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    items.extend(_collect_reviews(user))
    items.extend(_collect_critiques(user))
    items.extend(_collect_comments(user))
    items.extend(_collect_review_likes(user))
    items.extend(_collect_critique_likes(user))
    items.extend(_collect_friendships(user))
    items.extend(_collect_recommendations(user))
    items.extend(_collect_activity_events(user))
    return items


def build_user_activity(
    target_user,
    *,
    category: str = "all",
    order: str = "-date",
    page: int = 1,
    page_size: int = 30,
) -> Dict[str, Any]:
    """
    Собрать активность пользователя для публичной страницы.

    Returns dict:
        {
            "items":       список dict-ов (страница),
            "counts":      Counter категорий (для фильтр-чипов),
            "total":       общее число событий по выбранной категории,
            "page_obj":    Django Paginator Page,
            "category":    выбранная категория,
            "order":       '-date' | 'date',
            "categories":  CATEGORIES (для шаблона),
        }
    """
    all_items = _collect_all(target_user)

    # счётчики для бейджей (независимо от выбранного фильтра)
    counts: Counter = Counter()
    counts["all"] = len(all_items)
    for it in all_items:
        counts[it["category"]] += 1

    # Фильтруем
    if category != "all":
        filtered = [it for it in all_items if it["category"] == category]
    else:
        filtered = list(all_items)

    # Сортировка
    reverse = (order == "-date")
    # fallback-ключ на случай None-дат (не должно быть, но перестрахуемся)
    EPOCH = datetime.min
    filtered.sort(key=lambda x: (x.get("date") or EPOCH), reverse=reverse)

    # Пагинация
    paginator = Paginator(filtered, page_size)
    try:
        page_obj = paginator.page(page)
    except Exception:
        page_obj = paginator.page(1)

    # Категории с подсчётами — удобно для итерации в шаблоне без кастомных фильтров
    categories_with_counts = [
        {"code": code, "label": label, "count": counts.get(code, 0)}
        for code, label in CATEGORIES
    ]

    return {
        "items":      list(page_obj.object_list),
        "counts":     counts,
        "total":      len(filtered),
        "page_obj":   page_obj,
        "paginator":  paginator,
        "category":   category,
        "order":      order,
        "categories": categories_with_counts,
    }

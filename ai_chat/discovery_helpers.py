"""
Утилиты discovery-чата:
- нормализация запроса и кеш-ключ
- сбор профиля пользователя (включая negative-списки и сезон)
- подсчёт минимальной цены по магазинам
- поиск похожих публичных подборок других юзеров
"""
from __future__ import annotations

import hashlib
import re
from datetime import datetime
from typing import Iterable

from django.core.cache import cache
from django.db.models import Count, Q
from django.utils import timezone

from books.models import Book, BookStore, UserList


CACHE_PREFIX = "discovery:v1"
CACHE_TTL = 60 * 60  # 1 час


# ─────────────────────────────────────────────────────────────────────────────
# НОРМАЛИЗАЦИЯ + КЕШ
# ─────────────────────────────────────────────────────────────────────────────

_WS = re.compile(r"\s+")


def normalize_query(text: str) -> str:
    """«Детектив на Вечер!!!» → «детектив на вечер». Для кеш-ключа."""
    t = (text or "").lower().strip()
    t = _WS.sub(" ", t)
    t = re.sub(r"[^\wа-яё \-]", "", t, flags=re.IGNORECASE)
    return t


def cache_key(user_id: int, query: str, exclude_ids: Iterable[int] = ()) -> str:
    norm = normalize_query(query)
    excl = ",".join(str(x) for x in sorted(set(exclude_ids or [])))
    raw = f"{user_id}|{norm}|{excl}"
    h = hashlib.md5(raw.encode("utf-8")).hexdigest()[:16]
    return f"{CACHE_PREFIX}:{h}"


def cache_get(user_id: int, query: str, exclude_ids: Iterable[int] = ()):
    return cache.get(cache_key(user_id, query, exclude_ids))


def cache_set(user_id: int, query: str, payload: dict,
              exclude_ids: Iterable[int] = ()):
    cache.set(cache_key(user_id, query, exclude_ids), payload, timeout=CACHE_TTL)


# ─────────────────────────────────────────────────────────────────────────────
# ПРОФИЛЬ ПОЛЬЗОВАТЕЛЯ: любит / НЕ любит / сезон
# ─────────────────────────────────────────────────────────────────────────────

_SEASON_RU = {
    (12, 1, 2):  "зима",
    (3, 4, 5):   "весна",
    (6, 7, 8):   "лето",
    (9, 10, 11): "осень",
}

_MONTH_RU = [
    "", "январь", "февраль", "март", "апрель", "май", "июнь",
    "июль", "август", "сентябрь", "октябрь", "ноябрь", "декабрь",
]


def current_season_hint() -> str:
    now = timezone.localtime()
    season = next((s for months, s in _SEASON_RU.items() if now.month in months), "")
    return f"Сейчас {_MONTH_RU[now.month]}, {season}."


def build_user_profile_text(user) -> str:
    """
    Профиль для system-промпта. Включает:
      - любимые жанры/авторы из profile
      - книги из positive-списков
      - книги из negative-списков (для исключения)
      - сезонный контекст
    """
    parts: list[str] = []
    profile = getattr(user, "profile", None)
    if profile:
        fav_genres = list(profile.favorite_genres.all())
        fav_authors = list(profile.favorite_authors.all())
        if fav_genres:
            parts.append("Любимые жанры: " + ", ".join(g.name for g in fav_genres))
        if fav_authors:
            parts.append("Любимые авторы: " + ", ".join(a.name for a in fav_authors))

    positive_titles, negative_titles = [], []
    for ul in (UserList.objects
                       .filter(user=user)
                       .prefetch_related("books__authors")[:20]):
        for b in ul.books.all()[:10]:
            label = f"«{b.title}»"
            if ul.sentiment_tag == "positive":
                positive_titles.append(label)
            elif ul.sentiment_tag == "negative":
                negative_titles.append(label)

    if positive_titles:
        parts.append("Недавно понравилось: " + ", ".join(positive_titles[:12]))
    if negative_titles:
        parts.append("НЕ нравится (избегай похожего): " + ", ".join(negative_titles[:12]))

    parts.append(current_season_hint())

    return "\n".join(parts) if parts else f"Новый пользователь. {current_season_hint()}"


# ─────────────────────────────────────────────────────────────────────────────
# ЦЕНЫ
# ─────────────────────────────────────────────────────────────────────────────

def book_price_info(book: Book) -> dict:
    """
    {'min_price': Decimal | None, 'stores_count': int, 'currency': 'руб'}
    Смотрит BookStore.current_price; если нет — возвращает None.
    """
    qs = (BookStore.objects
                   .filter(book=book, current_price__isnull=False,
                           current_price__gt=0)
                   .order_by("current_price"))
    row = qs.first()
    if not row:
        return {"min_price": None, "stores_count": 0, "currency": "₽"}
    return {
        "min_price":    row.current_price,
        "stores_count": qs.count(),
        "currency":     "₽",
    }


def enrich_books_with_prices(items: list[dict]) -> list[dict]:
    """Добавляет item['price'] = {min_price, stores_count} к каждому."""
    book_ids = [it["book"].pk for it in items]
    if not book_ids:
        return items
    price_map: dict[int, dict] = {}
    # один запрос на все книги разом
    qs = (BookStore.objects
                   .filter(book_id__in=book_ids,
                           current_price__isnull=False,
                           current_price__gt=0))
    for bs in qs:
        cur = price_map.get(bs.book_id)
        if cur is None or bs.current_price < cur["min_price"]:
            price_map[bs.book_id] = {
                "min_price":    bs.current_price,
                "stores_count": 0,
            }
    # подсчёт stores_count отдельным запросом, чтобы не ходить по qs дважды
    counts = (qs.values("book_id")
                .annotate(n=Count("id")))
    counts_map = {c["book_id"]: c["n"] for c in counts}
    for bid, info in price_map.items():
        info["stores_count"] = counts_map.get(bid, 0)

    for it in items:
        info = price_map.get(it["book"].pk)
        it["price"] = info or {"min_price": None, "stores_count": 0}
    return items


# ─────────────────────────────────────────────────────────────────────────────
# ПОХОЖИЕ ПУБЛИЧНЫЕ ПОДБОРКИ
# ─────────────────────────────────────────────────────────────────────────────

def find_similar_public_lists(book_ids: list[int], exclude_user_id: int,
                              limit: int = 2) -> list[dict]:
    """
    Ищет публичные UserList, где пересекается максимум книг с текущей подборкой.
    Возвращает [{user, list, overlap}, ...].
    """
    if not book_ids:
        return []
    lists = (UserList.objects
                     .filter(is_public=True, books__in=book_ids)
                     .exclude(user_id=exclude_user_id)
                     .annotate(overlap=Count("books", filter=Q(books__in=book_ids)))
                     .filter(overlap__gte=2)
                     .select_related("user")
                     .prefetch_related("books__authors")
                     .order_by("-overlap")[:limit])
    out = []
    for ul in lists:
        out.append({
            "user":    ul.user,
            "list":    ul,
            "overlap": ul.overlap,
        })
    return out


# ─────────────────────────────────────────────────────────────────────────────
# «ЧТО УЖЕ СОВЕТОВАЛ» — anti-repeat
# ─────────────────────────────────────────────────────────────────────────────

def previously_recommended_ids(chat, limit: int = 50) -> list[int]:
    """Собирает ID всех книг, которые AI уже рекомендовал в этом чате."""
    seen: list[int] = []
    seen_set: set[int] = set()
    for msg in chat.messages.filter(role="assistant").order_by("-created_at")[:10]:
        for item in (msg.books_meta or []):
            bid = item.get("book_id") if isinstance(item, dict) else None
            if bid and bid not in seen_set:
                seen_set.add(bid)
                seen.append(bid)
                if len(seen) >= limit:
                    return seen
    return seen


def previously_disliked_ids(chat) -> list[int]:
    """Все книги, которым юзер поставил 👎 в рамках этого чата."""
    disliked: set[int] = set()
    for msg in chat.messages.filter(role="assistant"):
        for item in (msg.disliked_book_ids or []):
            bid = item.get("book_id") if isinstance(item, dict) else None
            if bid:
                disliked.add(bid)
    return list(disliked)

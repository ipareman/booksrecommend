"""
AI-рекомендации через ИИ (LLM-as-ranker).

Схема:
  1. Строим контекст пользователя (списки + отзывы + предпочтения онбординга)
  2. Жанровый скоринг → 50 кандидатов из БД
  3. Отправляем в ИИ: профиль + кандидаты → топ-10 + объяснения
     Используем tool_use с принудительной схемой — JSON гарантирован API,
     кандидаты передаются по порядковому индексу (не pk) — галлюцинации по ID невозможны
  4. Кешируем в Redis на AI_RECS_CACHE_TTL секунд
  5. Инвалидация кеша при изменении списков пользователя
"""

import logging
from django.conf import settings
from django.core.cache import cache
from books.models import UserList
from reviews.models import Review
from books.recommendations import recommended_for_user
from books.models import Book
from search.models import SearchHistory
import json


logger = logging.getLogger(__name__)

CACHE_KEY = "ai_recs_v1_{user_id}"


def get_cache_key(user_id: int) -> str:
    """Построить ключ кеша для AI-рекомендаций конкретного пользователя."""
    return CACHE_KEY.format(user_id=user_id)


def get_cached(user_id: int):
    """Получить сырые данные рекомендаций из кеша по идентификатору пользователя."""
    return cache.get(get_cache_key(user_id))


def invalidate(user_id: int):
    """Инвалидировать кеш AI-рекомендаций пользователя."""
    cache.delete(get_cache_key(user_id))


def build_user_context(user) -> dict:
    """Собрать профиль пользователя для передачи в ИИ."""

    lists_data = []
    liked_tags: dict[str, int] = {}  # A3: теги из положительных списков
    # A3: добавляем prefetch тегов книг
    for ul in UserList.objects.filter(user=user).prefetch_related(
        "books__authors", "books__genres", "books__tags"
    ):
        books_in_list = [
            {
                "title": b.title,
                "authors": [a.name for a in b.authors.all()],
                "genres": [g.name for g in b.genres.all()],
                "rating": b.avg_rating,
            }
            for b in ul.books.all()[:20]
        ]
        if books_in_list:
            lists_data.append({
                "list_name": ul.name,
                "sentiment": ul.sentiment_tag,
                "books": books_in_list,
            })
        # A3: собираем теги из positive/wishlist-списков
        if ul.sentiment_tag in ("positive", "wishlist"):
            for b in ul.books.all()[:20]:
                for t in b.tags.all():
                    liked_tags[t.name] = liked_tags.get(t.name, 0) + 1

    reviews_data = []
    for r in Review.objects.filter(user=user).select_related("book")[:20]:
        reviews_data.append({
            "title": r.book.title,
            "rating": r.rating,
            "text": r.text[:200] if r.text else "",
        })

    profile = getattr(user, "profile", None)
    fav_genres = list(profile.favorite_genres.values_list("name", flat=True)) if profile else []
    fav_authors = list(profile.favorite_authors.values_list("name", flat=True)) if profile else []

    # A3: топ-10 тегов по частоте
    top_liked_tags = sorted(liked_tags, key=liked_tags.get, reverse=True)[:10]

    # B1: история поиска — последние уникальные запросы
    raw_queries = list(
        SearchHistory.objects.filter(user=user)
        .order_by("-created_at")
        .values_list("query", flat=True)[:15]
    )
    seen_q: set[str] = set()
    unique_queries: list[str] = []
    for q in raw_queries:
        key = q.lower().strip()
        if key and key not in seen_q:
            seen_q.add(key)
            unique_queries.append(q.strip())
    search_queries = unique_queries[:10]

    return {
        "lists": lists_data,
        "reviews": reviews_data,
        "fav_genres": fav_genres,
        "fav_authors": fav_authors,
        "liked_tags": top_liked_tags,       # A3
        "search_queries": search_queries,   # B1
    }


def fetch_candidates(user, limit=50) -> list:
    """Получить кандидатов через жанровый скоринг."""
    return recommended_for_user(user, limit=limit)


# Схема для function calling (OpenAI-совместимый формат)
_RECOMMEND_TOOL = {
    "type": "function",
    "function": {
        "name": "recommend_books",
        "description": "Вернуть список рекомендованных книг с объяснениями",
        "parameters": {
            "type": "object",
            "properties": {
                "recommendations": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "book_index": {
                                "type": "integer",
                                "description": "Порядковый номер книги из списка кандидатов (1-50)"
                            },
                            "reason": {
                                "type": "string",
                                "description": "Краткое объяснение на русском, 1-2 предложения"
                            },
                        },
                        "required": ["book_index", "reason"],
                    },
                    "minItems": 1,
                    "maxItems": 10,
                }
            },
            "required": ["recommendations"],
        },
    },
}


def ask_claude(user_context: dict, candidates: list, user=None) -> list:
    """
    Отправить запрос к ИИ API через tool_use.
    Возвращает список: [{"book_index": int, "reason": str}, ...]
    """

    api_key = getattr(settings, "ANTHROPIC_API_KEY", "")
    if not api_key:
        raise ValueError("API-ключ LLM не задан (OPENROUTER_API_KEY / ANTHROPIC_API_KEY)")

    # Индексированный список кандидатов (1-based) — без реальных pk
    candidates_lines = []
    for i, b in enumerate(candidates):
        authors = ", ".join(a.name for a in b.authors.all())
        genres = ", ".join(g.name for g in b.genres.all())
        line = (
            f"{i + 1}. «{b.title}» — {authors} "
            f"({genres}) рейтинг: {b.avg_rating:.1f}"
        )
        # A3: народные теги из одобренных отзывов
        tags = [t.name for t in b.tags.all()]
        if tags:
            line += f" [{', '.join(tags)}]"
        if b.description:
            line += f"\n   {b.description[:150]}"
        candidates_lines.append(line)
    candidates_text = "\n".join(candidates_lines)

    # Профиль пользователя
    profile_parts = []
    if user_context["fav_genres"]:
        profile_parts.append(f"Любимые жанры: {', '.join(user_context['fav_genres'])}")
    if user_context["fav_authors"]:
        profile_parts.append(f"Любимые авторы: {', '.join(user_context['fav_authors'])}")
    for lst in user_context["lists"]:
        titles = [b["title"] for b in lst["books"][:5]]
        sentiment_hint = {
            "positive": "👍 нравится",
            "negative": "👎 не нравится",
            "wishlist": "📖 хочу прочитать",
            "neutral": "",
        }.get(lst["sentiment"], "")
        label = f"«{lst['list_name']}»{' (' + sentiment_hint + ')' if sentiment_hint else ''}"
        profile_parts.append(f"Список {label}: {', '.join(titles)}")
    for r in user_context["reviews"][:5]:
        profile_parts.append(f"Оценил «{r['title']}» на {r['rating']}/5")
    # A3: теги любимых книг
    if user_context.get("liked_tags"):
        profile_parts.append(
            f"Теги часто встречающиеся в любимых книгах: {', '.join(user_context['liked_tags'])}"
        )
    # B1: история поиска
    if user_context.get("search_queries"):
        profile_parts.append(
            f"Недавно искал: {', '.join(user_context['search_queries'])}"
        )
    profile_text = "\n".join(profile_parts) or "Новый пользователь, предпочтения неизвестны"

    prompt = (
        f"Ты — библиотекарь-эксперт. Твоя задача — выбрать 10 лучших книг для пользователя.\n\n"
        f"ПРОФИЛЬ ПОЛЬЗОВАТЕЛЯ:\n{profile_text}\n\n"
        f"СПИСОК КАНДИДАТОВ (отбор сделан алгоритмически):\n{candidates_text}\n\n"
        f"Выбери ровно 10 книг которые максимально подойдут этому пользователю. "
        f"Списки с пометкой 👎 означают что похожие книги НЕ нужны. "
        f"Используй порядковый номер книги из списка (поле book_index)."
    )

    from core.llm import chat_completion
    response = chat_completion(
        tier="main",
        feature="recommendations",
        user=user,
        max_tokens=1000,
        tools=[_RECOMMEND_TOOL],
        tool_choice={"type": "function", "function": {"name": "recommend_books"}},
        messages=[{"role": "user", "content": prompt}],
    )

    # Достаём аргументы function call — JSON гарантирован схемой
    tool_calls = response.choices[0].message.tool_calls
    if not tool_calls:
        raise ValueError("Модель не вернула function call")

    return json.loads(tool_calls[0].function.arguments).get("recommendations", [])


def generate_ai_recommendations(user) -> list:
    """
    Полный цикл: кандидаты → ИИ → валидация → кеш.
    Возвращает список словарей {"book": Book, "reason": str}.
    """

    candidates = fetch_candidates(user, limit=50)
    if not candidates:
        return []

    # Маппинг: порядковый индекс (1-based) → Book объект
    index_map = {i + 1: book for i, book in enumerate(candidates)}
    valid_indices = set(index_map.keys())

    user_context = build_user_context(user)

    try:
        ranked = ask_claude(user_context, candidates, user=user)
    except Exception as exc:
        logger.error("Claude API error for user %s: %s", user.username, exc)
        return []

    result = []
    for item in ranked:
        idx = item.get("book_index")
        if idx not in valid_indices:
            logger.warning(
                "Claude вернул несуществующий индекс %s для user %s",
                idx, user.username
            )
            continue
        reason = item.get("reason", "")
        if not reason:
            continue
        result.append({"book": index_map[idx], "reason": reason})

    # Fallback: если модель вернула меньше 10 — добираем по рейтингу
    if len(result) < 10:
        used_pks = {r["book"].pk for r in result}
        fallback = [
                       {"book": b, "reason": "Высоко оценена читателями"}
                       for b in sorted(candidates, key=lambda b: -b.avg_rating)
                       if b.pk not in used_pks
                   ][: 10 - len(result)]
        result += fallback
        if fallback:
            logger.info(
                "AI recs fallback: добавлено %d книг по рейтингу для user %s",
                len(fallback), user.username
            )

    # Кешируем
    serialized = [
        {"book_id": item["book"].pk, "reason": item["reason"]}
        for item in result
    ]
    cache.set(
        get_cache_key(user.pk),
        serialized,
        timeout=getattr(settings, "AI_RECS_CACHE_TTL", 86400),
    )

    return result


def load_from_cache(user_id: int) -> list:
    """Загрузить рекомендации из кеша + достать Book-объекты из БД."""

    cached = cache.get(get_cache_key(user_id))
    if not cached:
        return []

    book_ids = [item["book_id"] for item in cached]
    books_map = {
        b.pk: b for b in
        Book.objects.filter(pk__in=book_ids).prefetch_related("authors", "genres")
    }

    result = []
    for item in cached:
        book = books_map.get(item["book_id"])
        if book:
            result.append({"book": book, "reason": item["reason"]})

    return result

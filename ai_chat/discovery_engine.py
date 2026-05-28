"""
Discovery Engine — AI-чат для поиска книг без привязки к конкретной книге.

Фичи v2:
  · Быстрые чипы / preset-запросы (обработка на стороне UI, бэк принимает как обычный текст)
  · Follow-up уточнения — AI возвращает список followup_options, если запрос размыт
  · «Не то» feedback-loop — exclude_ids передаются в промпт, чтобы AI их избегал
  · negative-списки учитываются в профиле («НЕ нравится»)
  · Сезонный контекст в промпте
  · Кеш похожих запросов (1 час, ключ = user+query+exclude_ids)
  · Объяснение-рассуждение по клику — ask_elaborate()
  · Цены в карточках (enrich_books_with_prices)
  · Сохранение подборки — save_last_recommendations_as_list()
  · Anti-repeat — «что уже советовал в этой сессии»
  · Публичные подборки других юзеров с похожим вкусом
"""

import json
import logging
from typing import Optional

from django.contrib.postgres.search import SearchVector, SearchRank, SearchQuery
from django.db.models import Q

from core.llm import chat_completion

from books.models import Book, BookMood, UserList
from .models import DiscoveryChat, DiscoveryChatMessage
from .discovery_helpers import (
    build_user_profile_text,
    cache_get,
    cache_set,
    enrich_books_with_prices,
    find_similar_public_lists,
    previously_disliked_ids,
    previously_recommended_ids,
)


logger = logging.getLogger(__name__)


DISCOVERY_QUERY_TOOL = {
    "type": "function",
    "function": {
        "name": "understand_book_request",
        "description": "Понять книжный запрос пользователя и расширить его для поиска по каталогу.",
        "parameters": {
            "type": "object",
            "properties": {
                "interpreted_request": {
                    "type": "string",
                    "description": "Краткая интерпретация запроса с учётом истории диалога.",
                },
                "search_queries": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "3-8 поисковых формулировок для FTS: темы, сюжет, настроение, жанры.",
                },
                "candidate_titles": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Возможные конкретные названия книг, если пользователь описал известный сюжет.",
                },
                "candidate_authors": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Возможные авторы.",
                },
                "themes": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Ключевые темы, мотивы, конфликты, атмосфера.",
                },
                "needs_followup": {
                    "type": "boolean",
                    "description": "true, если запрос слишком общий и лучше сначала уточнить вкус.",
                },
            },
            "required": ["interpreted_request", "search_queries", "candidate_titles", "candidate_authors", "themes", "needs_followup"],
        },
    },
}


# ─────────────────────────────────────────────────────────────────────────────
# ПОИСК КАНДИДАТОВ
# ─────────────────────────────────────────────────────────────────────────────

def _dedupe_books(books: list[Book], limit: int) -> list[Book]:
    seen = set()
    result = []
    for book in books:
        if book.pk in seen:
            continue
        seen.add(book.pk)
        result.append(book)
        if len(result) >= limit:
            break
    return result


def _safe_text_list(value, max_items: int = 8, max_len: int = 120) -> list[str]:
    if not isinstance(value, list):
        return []
    result = []
    for item in value[:max_items]:
        if not isinstance(item, str):
            continue
        text = item.strip()
        if text:
            result.append(text[:max_len])
    return result


def _history_for_understanding(history: list[DiscoveryChatMessage]) -> str:
    lines = []
    for msg in history[-8:]:
        content = (msg.content or "").strip()
        if content:
            lines.append(f"{msg.role}: {content[:500]}")
    return "\n".join(lines) or "Истории пока нет."


def _contextual_cache_query(message: str, history: list[DiscoveryChatMessage]) -> str:
    context = _history_for_understanding(history[-6:])
    return f"{context}\n\nuser: {message}"


def _understand_query(user, message: str, history: list[DiscoveryChatMessage]) -> dict:
    fallback = {
        "interpreted_request": message,
        "search_queries": [message],
        "candidate_titles": [],
        "candidate_authors": [],
        "themes": [],
        "needs_followup": False,
    }
    try:
        response = chat_completion(
            tier="main",
            feature="discovery",
            user=user,
            messages=[{
                "role": "system",
                "content": (
                    "Ты помогаешь книжному поиску понять реплику пользователя. "
                    "Учитывай историю диалога: короткие ответы вроде «больше сюжета», "
                    "«без насилия», «а что-то старое?» дополняют предыдущий запрос. "
                    "Если пользователь описывает известный сюжет и не называет книгу, "
                    "предположи возможные названия и авторов. Например описание про "
                    "бедного студента, убийство старухи-процентщицы/бабушки и раскаяние "
                    "должно дать кандидат «Преступление и наказание», автор Достоевский. "
                    "Не выдумывай окончательную рекомендацию: верни только поисковое понимание."
                ),
            }, {
                "role": "user",
                "content": (
                    f"История диалога:\n{_history_for_understanding(history)}\n\n"
                    f"Новая реплика пользователя:\n{message}"
                ),
            }],
            tools=[DISCOVERY_QUERY_TOOL],
            tool_choice={"type": "function", "function": {"name": "understand_book_request"}},
            max_tokens=700,
        )
        choice = response.choices[0]
        if not choice.message.tool_calls:
            return fallback
        data = json.loads(choice.message.tool_calls[0].function.arguments)
    except Exception as exc:
        logger.warning("Discovery query understanding failed: %s", exc)
        return fallback

    search_queries = _safe_text_list(data.get("search_queries"))
    candidate_titles = _safe_text_list(data.get("candidate_titles"))
    candidate_authors = _safe_text_list(data.get("candidate_authors"))
    themes = _safe_text_list(data.get("themes"))

    if not search_queries:
        search_queries = [message]

    return {
        "interpreted_request": (data.get("interpreted_request") or message).strip()[:600],
        "search_queries": search_queries,
        "candidate_titles": candidate_titles,
        "candidate_authors": candidate_authors,
        "themes": themes,
        "needs_followup": bool(data.get("needs_followup")),
    }


def _search_catalog(query: str, query_plan: dict | None = None, exclude_ids: set[int] | None = None,
                    limit: int = 12) -> list[Book]:
    """FTS + fallback на топ по рейтингу. Исключает книги из exclude_ids."""
    exclude_ids = exclude_ids or set()
    query_plan = query_plan or {}
    found: list[Book] = []
    search_queries = [query]
    search_queries.extend(query_plan.get("search_queries") or [])
    search_queries.extend(query_plan.get("themes") or [])
    seen_queries = []
    for item in search_queries:
        text = (item or "").strip()
        if text and text.lower() not in {q.lower() for q in seen_queries}:
            seen_queries.append(text)

    title_q = Q()
    for title in query_plan.get("candidate_titles") or []:
        title_q |= Q(title__iexact=title) | Q(title__icontains=title)
    if title_q:
        found.extend(
            Book.objects
            .filter(title_q)
            .exclude(pk__in=exclude_ids)
            .prefetch_related("authors", "genres")
            .order_by("-avg_rating", "-rating_count")[:limit]
        )

    author_q = Q()
    for author in query_plan.get("candidate_authors") or []:
        author_q |= Q(authors__name__icontains=author)
    if author_q and len(found) < limit:
        found.extend(
            Book.objects
            .filter(author_q)
            .exclude(pk__in={b.pk for b in found} | exclude_ids)
            .prefetch_related("authors", "genres")
            .distinct()
            .order_by("-avg_rating", "-rating_count")[:limit - len(found)]
        )

    for search_text in seen_queries:
        if len(found) >= limit:
            break
        try:
            search_query = SearchQuery(search_text, config="russian", search_type="websearch")
            search_vector = (
                SearchVector("title", weight="A", config="russian")
                + SearchVector("description", weight="C", config="russian")
            )

            fts_results = (
                Book.objects
                .annotate(rank=SearchRank(search_vector, search_query))
                .filter(rank__gte=0.03)
                .exclude(pk__in={b.pk for b in found} | exclude_ids)
                .order_by("-rank")[:limit - len(found)]
            )
            found.extend(list(fts_results.prefetch_related("authors", "genres")))
        except Exception:
            fallback_q = (
                Q(title__icontains=search_text)
                | Q(description__icontains=search_text)
                | Q(authors__name__icontains=search_text)
                | Q(genres__name__icontains=search_text)
            )
            found.extend(
                Book.objects
                .filter(fallback_q)
                .exclude(pk__in={b.pk for b in found} | exclude_ids)
                .prefetch_related("authors", "genres")
                .distinct()
                .order_by("-avg_rating", "-rating_count")[:limit - len(found)]
            )

    results = _dedupe_books(found, limit)

    if len(results) < limit:
        remaining = limit - len(results)
        seen_ids = {b.pk for b in results} | exclude_ids
        extra = (Book.objects
                     .exclude(pk__in=seen_ids)
                     .prefetch_related("authors", "genres")
                     .order_by("-avg_rating", "-rating_count")[:remaining])
        results.extend(extra)

    return results


def _build_candidates_text(books: list[Book]) -> str:
    lines = []
    for i, book in enumerate(books, 1):
        authors = ", ".join(a.name for a in book.authors.all())
        genres = ", ".join(g.name for g in book.genres.all())
        moods = ", ".join(
            bm.mood.name for bm in
            BookMood.objects.filter(book=book).select_related("mood")[:5]
        )
        line = f"{i}. «{book.title}»"
        if authors:
            line += f" — {authors}"
        if genres:
            line += f" [{genres}]"
        if moods:
            line += f" ({moods})"
        if book.ai_themes:
            themes = ", ".join(str(t) for t in book.ai_themes[:6])
            line += f" <темы: {themes}>"
        if book.description:
            line += f": {book.description[:260]}"
        lines.append(line)
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# TOOL-СХЕМА: книги + followup_options
# ─────────────────────────────────────────────────────────────────────────────

RECOMMEND_TOOL = {
    "type": "function",
    "function": {
        "name": "recommend_books",
        "description": "Рекомендовать книги или задать уточняющий вопрос",
        "parameters": {
            "type": "object",
            "properties": {
                "explanation": {
                    "type": "string",
                    "description": "Общий текст-ответ пользователю (2–3 предложения)",
                },
                "books": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "index":  {"type": "integer"},
                            "reason": {"type": "string"},
                        },
                        "required": ["index", "reason"],
                    },
                },
                "followup_options": {
                    "type": "array",
                    "description": (
                        "Если запрос размыт — 3-4 варианта-чипа для уточнения. "
                        "Каждый: короткий label (до 30 симв.) и полный prompt."
                    ),
                    "items": {
                        "type": "object",
                        "properties": {
                            "label":  {"type": "string"},
                            "prompt": {"type": "string"},
                        },
                        "required": ["label", "prompt"],
                    },
                },
            },
            "required": ["explanation"],
        },
    },
}


# ─────────────────────────────────────────────────────────────────────────────
# ОСНОВНОЙ ВЫЗОВ
# ─────────────────────────────────────────────────────────────────────────────

def ask_discovery(user, message: str, chat: DiscoveryChat,
                  extra_exclude_ids: Optional[list[int]] = None,
                  mode: str = "standard") -> dict:
    """
    Главный вход. Возвращает:
      {
        "text":                str,
        "books":               [{book, reason, price}],
        "followup_options":    [{label, prompt}],
        "public_lists":        [{user, list, overlap}],
        "from_cache":          bool,
      }
    """
    extra_exclude_ids = list(extra_exclude_ids or [])

    # Собираем всё, что надо избегать в этой сессии
    disliked_ids = previously_disliked_ids(chat)
    recommended_ids = previously_recommended_ids(chat)
    exclude_set = set(disliked_ids) | set(extra_exclude_ids)

    # История чата
    history = list(chat.messages.order_by("-created_at")[:10])
    history.reverse()
    cache_query = _contextual_cache_query(message, history) + f"\nmode: {mode}"

    # ── КЕШ ───────────────────────────────────────────────────────────────
    cached = cache_get(user.pk, cache_query, exclude_set)
    if cached:
        books_qs = Book.objects.filter(pk__in=cached["book_ids"]).prefetch_related("authors")
        books_map = {b.pk: b for b in books_qs}
        books_out = []
        for bid in cached["book_ids"]:
            b = books_map.get(bid)
            if b:
                books_out.append({
                    "book":   b,
                    "reason": cached["reasons"].get(str(bid), ""),
                })
        enrich_books_with_prices(books_out)

        # Сохраняем сообщения даже при hit — чтобы история чата не разъезжалась
        DiscoveryChatMessage.objects.create(chat=chat, role="user", content=message)
        ai_msg = DiscoveryChatMessage.objects.create(
            chat=chat, role="assistant",
            content=cached["text"],
            followup_options=cached.get("followup_options", []),
            books_meta=[{"book_id": bid, "reason": cached["reasons"].get(str(bid), "")}
                        for bid in cached["book_ids"]],
        )
        if cached["book_ids"]:
            ai_msg.recommended_books.set(cached["book_ids"])

        return {
            "text":             cached["text"],
            "books":            books_out,
            "followup_options": cached.get("followup_options", []),
            "public_lists":     find_similar_public_lists(cached["book_ids"], user.pk),
            "from_cache":       True,
            "message_id":        ai_msg.pk,
        }

    # ── ПОНИМАНИЕ ЗАПРОСА + ПОИСК КАНДИДАТОВ ──────────────────────────────
    if mode == "smarter":
        query_plan = _understand_query(user, message, history)
        candidates = _search_catalog(message, query_plan=query_plan, exclude_ids=exclude_set, limit=35)
    elif mode == "standard":
        query_plan = _understand_query(user, message, history)
        candidates = _search_catalog(message, query_plan=query_plan, exclude_ids=exclude_set, limit=15)
    else:  # mode == "faster"
        query_plan = None
        candidates = _search_catalog(message, query_plan=None, exclude_ids=exclude_set, limit=12)

    candidates_text = _build_candidates_text(candidates)
    user_profile = build_user_profile_text(user)

    # Anti-repeat
    already_hint = ""
    if recommended_ids:
        titles = list(
            Book.objects.filter(pk__in=recommended_ids[:10])
                        .values_list("title", flat=True)
        )
        if titles:
            already_hint = (
                "\n\nЭти книги ты уже советовал в этом чате — НЕ повторяй их: "
                + ", ".join(f"«{t}»" for t in titles)
            )

    dislike_hint = ""
    if disliked_ids or extra_exclude_ids:
        dislike_hint = (
            "\n\nПользователь явно отверг часть прошлых рекомендаций — "
            "они уже исключены из каталога. Учти его вкус и предложи ДРУГОЕ."
        )

    plan_to_serialize = query_plan or {
        "interpreted_request": message,
        "search_queries": [message],
        "candidate_titles": [],
        "candidate_authors": [],
        "themes": [],
        "needs_followup": False,
    }

    messages = [{
        "role": "system",
        "content": (
            "Ты — книжный советник. ВСЕГДА отвечай ТОЛЬКО на русском. "
            "Всегда вызывай инструмент recommend_books.\n\n"
            "Правила:\n"
            "• Если запрос конкретный — вернуть 3-6 книг из каталога с полем books и explanation.\n"
            "• Если запрос РАЗМЫТЫЙ («что-то интересное», «посоветуй книгу», «не знаю что хочу») — "
            "вернуть ПУСТОЙ books и заполнить followup_options 3-4 вариантами "
            "(чипы-уточнения: label + prompt). В этом случае explanation — короткое «Что тебе ближе?».\n"
            "• Если этап понимания запроса пометил needs_followup=true, обычно сначала задай уточняющий вопрос, "
            "если только в каталоге нет очевидного точного совпадения.\n"
            "• В reason у каждой книги — 1 предложение, почему она подходит этому юзеру.\n"
            "• Если пользователь описал сюжет известной книги, можно выбрать точное совпадение из каталога, "
            "даже если пользователь не назвал книгу напрямую.\n"
            "• Используй номера (поле index) из каталога, не придумывай книги.\n\n"
            f"Профиль пользователя:\n{user_profile}"
            f"{already_hint}{dislike_hint}\n\n"
            f"Понимание запроса:\n{json.dumps(plan_to_serialize, ensure_ascii=False)}\n\n"
            f"Каталог (1-{len(candidates)}):\n{candidates_text}"
        ),
    }]
    for msg in history:
        messages.append({"role": msg.role, "content": msg.content})
    messages.append({"role": "user", "content": message})

    # Сохраняем сообщение юзера до вызова (идемпотентно)
    DiscoveryChatMessage.objects.create(chat=chat, role="user", content=message)

    try:
        response = chat_completion(
            tier="main",
            feature="discovery",
            user=user,
            messages=messages,
            tools=[RECOMMEND_TOOL],
            tool_choice={"type": "function", "function": {"name": "recommend_books"}},
            max_tokens=1500,
        )
    except Exception as exc:
        logger.error("Discovery AI error: %s", exc)
        ai_msg = DiscoveryChatMessage.objects.create(
            chat=chat, role="assistant",
            content="Извините, произошла ошибка. Попробуйте позже.",
        )
        return {
            "text": ai_msg.content, "books": [],
            "followup_options": [], "public_lists": [], "from_cache": False,
            "message_id": ai_msg.pk,
        }

    # ── ПАРСИНГ ОТВЕТА ────────────────────────────────────────────────────
    choice = response.choices[0]
    recommended_books: list[dict] = []
    explanation = ""
    followup_options: list[dict] = []

    if choice.message.tool_calls:
        for tc in choice.message.tool_calls:
            if tc.function.name == "recommend_books":
                try:
                    data = json.loads(tc.function.arguments)
                    explanation = data.get("explanation", "")
                    followup_options = data.get("followup_options", []) or []
                    for item in data.get("books", []) or []:
                        idx = item.get("index", 0) - 1
                        if 0 <= idx < len(candidates):
                            recommended_books.append({
                                "book":   candidates[idx],
                                "reason": item.get("reason", ""),
                            })
                except (json.JSONDecodeError, KeyError) as exc:
                    logger.warning("Discovery parse error: %s", exc)

    if not explanation and choice.message.content:
        explanation = choice.message.content.strip()

    # Fallback: ни книг, ни чипов — топ-5 по поиску
    if not recommended_books and not followup_options and candidates:
        recommended_books = [{"book": b, "reason": ""} for b in candidates[:5]]
        if not explanation:
            explanation = "Вот что подобрал по вашему запросу:"
    elif not explanation:
        explanation = "Не удалось ничего подобрать — попробуйте уточнить."

    # Обогащаем ценами
    enrich_books_with_prices(recommended_books)

    # ── СОХРАНЕНИЕ ────────────────────────────────────────────────────────
    ai_msg = DiscoveryChatMessage.objects.create(
        chat=chat, role="assistant",
        content=explanation,
        followup_options=followup_options,
    )
    if recommended_books:
        ai_msg.recommended_books.set([rb["book"] for rb in recommended_books])
        ai_msg.books_meta = [
            {"book_id": rb["book"].pk, "reason": rb.get("reason", "")}
            for rb in recommended_books
        ]
        ai_msg.save(update_fields=["books_meta"])

    # ── КЕШ ───────────────────────────────────────────────────────────────
    book_ids = [rb["book"].pk for rb in recommended_books]
    cache_set(user.pk, cache_query, {
        "text":             explanation,
        "book_ids":         book_ids,
        "reasons":          {str(rb["book"].pk): rb.get("reason", "") for rb in recommended_books},
        "followup_options": followup_options,
    }, exclude_ids=exclude_set)

    public_lists = find_similar_public_lists(book_ids, user.pk) if book_ids else []

    return {
        "text":             explanation,
        "books":            recommended_books,
        "followup_options": followup_options,
        "public_lists":     public_lists,
        "from_cache":       False,
        "message_id":       ai_msg.pk,
    }


# ─────────────────────────────────────────────────────────────────────────────
# ДЕТАЛЬНОЕ ОБЪЯСНЕНИЕ («Подробнее почему эта книга»)
# ─────────────────────────────────────────────────────────────────────────────

def ask_elaborate(user, chat: DiscoveryChat, book: Book, short_reason: str = "") -> str:
    """
    Развёрнутый абзац-объяснение почему книга подходит юзеру.
    Кешируется в books_meta последнего assistant-сообщения.
    """
    # Проверка кеша в books_meta
    last_msg = (chat.messages
                    .filter(role="assistant", recommended_books=book)
                    .order_by("-created_at")
                    .first())
    if last_msg:
        for item in (last_msg.books_meta or []):
            if isinstance(item, dict) and item.get("book_id") == book.pk:
                cached = item.get("detailed_reason")
                if cached:
                    return cached

    user_profile = build_user_profile_text(user)
    authors = ", ".join(a.name for a in book.authors.all())
    genres = ", ".join(g.name for g in book.genres.all())

    prompt = (
        f"Профиль юзера:\n{user_profile}\n\n"
        f"Книга: «{book.title}» — {authors} [{genres}]\n"
        f"Описание: {(book.description or '')[:400]}\n"
        f"Краткое объяснение (уже дали): {short_reason or '—'}\n\n"
        "Напиши развёрнутое (4-6 предложений) объяснение, почему именно эта книга "
        "подойдёт этому пользователю. Опирайся на его вкусы и книги, которые он уже читал. "
        "Говори конкретно и живо, без общих слов. Только русский."
    )

    try:
        response = chat_completion(
            tier="main",
            feature="discovery",
            user=user,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=400,
        )
        text = (response.choices[0].message.content or "").strip()
    except Exception as exc:
        logger.error("Elaborate error: %s", exc)
        text = "Не удалось получить развёрнутое объяснение."

    # Записываем в books_meta последнего сообщения
    if last_msg and text:
        meta = last_msg.books_meta or []
        updated = False
        for item in meta:
            if isinstance(item, dict) and item.get("book_id") == book.pk:
                item["detailed_reason"] = text
                updated = True
                break
        if updated:
            last_msg.books_meta = meta
            last_msg.save(update_fields=["books_meta"])

    return text


# ─────────────────────────────────────────────────────────────────────────────
# СОХРАНЕНИЕ ПОДБОРКИ КАК UserList
# ─────────────────────────────────────────────────────────────────────────────

def save_last_recommendations_as_list(user, chat: DiscoveryChat,
                                       list_name: str = "") -> Optional[UserList]:
    """
    Берёт последнее assistant-сообщение с recommended_books → создаёт UserList.
    Возвращает UserList или None если рекомендаций нет.
    """
    last_msg = (chat.messages
                    .filter(role="assistant")
                    .exclude(recommended_books=None)
                    .order_by("-created_at")
                    .first())
    if not last_msg:
        return None
    books = list(last_msg.recommended_books.all())
    if not books:
        return None

    name = list_name.strip() or f"AI-подборка от {last_msg.created_at:%d.%m.%Y %H:%M}"
    ul = UserList.objects.create(
        user=user,
        name=name[:100],
        sentiment_tag="neutral",
    )
    ul.books.set(books)
    return ul

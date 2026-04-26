"""
Семантический (пока FTS-based) поиск по главам книги.

Бюджет: без внешних embeddings / pgvector — используем PostgreSQL FTS
с русской морфологией, плюс опциональный LLM re-rank для осмысленных
вопросов типа «где в книге происходит дуэль?».

LLM-rerank выключен по умолчанию (чтобы не гонять токены каждый раз),
включается параметром rerank=True.
"""

from __future__ import annotations

import logging
from typing import Iterable

from django.contrib.postgres.search import (
    SearchVector, SearchQuery, SearchRank, SearchHeadline,
)
from django.db.models import Q

from .models import BookChapter

logger = logging.getLogger(__name__)


def search_chapters(
    book,
    query: str,
    limit: int = 8,
    rerank: bool = False,
) -> list[dict]:
    """Ищет главы книги, релевантные запросу.

    Возвращает список словарей со структурой:
      {
        "chapter_order": int,
        "title":         str,
        "snippet":       str,   # HTML с <mark> вокруг совпадений
        "score":         float,
      }
    """
    query = (query or "").strip()
    if len(query) < 3:
        return []

    text = getattr(book, "text", None)
    if not text:
        return []

    results = _fts_chapters(text, query, limit)
    if not results:
        # Fallback: icontains по названию и тексту
        results = _icontains_chapters(text, query, limit)

    if rerank and results:
        results = _llm_rerank(book, query, results)

    return results


def _fts_chapters(text, query: str, limit: int) -> list[dict]:
    """PostgreSQL FTS по тексту и заголовкам глав."""
    try:
        sq = SearchQuery(query, config="russian", search_type="websearch")
        vector = (
            SearchVector("title", weight="A", config="russian") +
            SearchVector("text",  weight="C", config="russian")
        )
        qs = (
            BookChapter.objects
            .filter(book_text=text)
            .annotate(
                rank=SearchRank(vector, sq),
                snippet=SearchHeadline(
                    "text", sq, config="russian",
                    start_sel="<mark>", stop_sel="</mark>",
                    max_words=35, min_words=15, max_fragments=1,
                ),
            )
            .filter(rank__gte=0.03)
            .order_by("-rank")[:limit]
        )
        out = []
        for ch in qs:
            out.append({
                "chapter_order": ch.order,
                "title":   ch.title or f"Глава {ch.order + 1}",
                "snippet": ch.snippet,
                "score":   float(ch.rank),
            })
        return out
    except Exception as exc:
        logger.warning("chapter_search FTS failed: %s", exc)
        return []


def _icontains_chapters(text, query: str, limit: int) -> list[dict]:
    """Простой fallback — ищем подстроку без морфологии."""
    qs = (
        BookChapter.objects
        .filter(book_text=text)
        .filter(Q(title__icontains=query) | Q(text__icontains=query))
        .order_by("order")[:limit]
    )
    out = []
    for ch in qs:
        body = ch.text or ""
        i = body.lower().find(query.lower())
        if i < 0:
            snippet = (body[:220] + "…") if len(body) > 220 else body
        else:
            start = max(0, i - 80)
            end   = min(len(body), i + len(query) + 140)
            snippet = ("…" if start else "") + body[start:end] + ("…" if end < len(body) else "")
            # Оборачиваем совпадение тегом <mark> (только первое)
            low = snippet.lower()
            j   = low.find(query.lower())
            if j >= 0:
                snippet = snippet[:j] + "<mark>" + snippet[j:j+len(query)] + "</mark>" + snippet[j+len(query):]
        out.append({
            "chapter_order": ch.order,
            "title":   ch.title or f"Глава {ch.order + 1}",
            "snippet": snippet,
            "score":   0.01,
        })
    return out


def _llm_rerank(book, query: str, candidates: list[dict]) -> list[dict]:
    """Использует LLM, чтобы переранжировать кандидатов по смысловой
    близости к вопросу пользователя («где в книге дуэль?»).

    Делается одним запросом с tool_use — возвращает упорядоченный список
    chapter_order с оценками релевантности.
    """
    if not candidates or len(candidates) < 2:
        return candidates

    from core.llm import chat_completion
    import json as _json

    # Собираем краткий контекст: первые 300 символов сниппета каждой главы
    context_lines = []
    for c in candidates:
        title = c["title"]
        snippet_plain = c["snippet"].replace("<mark>", "").replace("</mark>", "")
        context_lines.append(f"[Глава {c['chapter_order'] + 1}. {title}]\n{snippet_plain[:300]}")
    context = "\n\n".join(context_lines)

    prompt = (
        f"Пользователь ищет в книге «{book.title}»: «{query}».\n\n"
        f"Ниже — кандидаты из глав. Переранжируй их по смысловой близости "
        f"к запросу (максимум 5 самых релевантных). Учитывай синонимы и "
        f"контекст, не только дословное совпадение.\n\n"
        f"{context}"
    )

    tools = [{
        "type": "function",
        "function": {
            "name": "rank_chapters",
            "parameters": {
                "type": "object",
                "properties": {
                    "ordered": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "chapter_order": {"type": "integer"},
                                "score":         {"type": "number"},
                                "why":           {"type": "string"},
                            },
                            "required": ["chapter_order", "score"],
                        },
                    },
                },
                "required": ["ordered"],
            },
        },
    }]

    try:
        resp = chat_completion(
            tier="light",
            feature="book_search",
            messages=[{"role": "user", "content": prompt}],
            tools=tools,
            tool_choice={"type": "function", "function": {"name": "rank_chapters"}},
            max_tokens=400,
        )
    except Exception as exc:
        logger.warning("chapter_search LLM rerank failed: %s", exc)
        return candidates

    ranking = []
    for choice in resp.choices:
        if not choice.message.tool_calls:
            continue
        for tc in choice.message.tool_calls:
            try:
                data = _json.loads(tc.function.arguments or "{}")
            except Exception:
                continue
            ranking = data.get("ordered") or []
            break

    if not ranking:
        return candidates

    # Перестраиваем порядок: берём LLM-ранжирование как приоритет
    by_order = {c["chapter_order"]: c for c in candidates}
    reranked = []
    seen = set()
    for r in ranking:
        cho = r.get("chapter_order")
        if cho in by_order and cho not in seen:
            c = dict(by_order[cho])
            c["score"] = float(r.get("score") or 0) * 0.9 + c["score"] * 0.1
            if r.get("why"):
                c["why"] = r["why"]
            reranked.append(c)
            seen.add(cho)
    # Добавляем не вошедшие в хвост
    for c in candidates:
        if c["chapter_order"] not in seen:
            reranked.append(c)
    return reranked[:5]

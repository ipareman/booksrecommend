import json
import logging

from django.shortcuts import render, redirect
from django.http import HttpResponse
from django.views.decorators.http import require_POST
from django.contrib.postgres.search import (
    SearchVector, SearchQuery, SearchRank, SearchHeadline,
    TrigramWordSimilarity,
)
from django.db.models import Q, Value, FloatField
from books.models import Book, Author, Genre, MoodTag
from .models import SearchHistory

logger = logging.getLogger(__name__)


def search(request):
    query   = request.GET.get("q", "").strip()
    results = []

    if query:
        results = _fts_search(query)

        # Fallback: триграммный поиск (опечатки, неточные запросы)
        if not results:
            results = _trigram_search(query)

        SearchHistory.objects.create(
            user=request.user if request.user.is_authenticated else None,
            query=query,
            results_count=len(results),
        )

    ctx = {"query": query, "results": results}

    if request.htmx:
        return render(request, "search/_results.html", ctx)

    ctx.update({
        "popular": Book.objects.order_by("-rating_count")[:8],
        "newest":  Book.objects.order_by("-publication_year")[:8],
        "mood_tags": MoodTag.objects.all(),
    })
    return render(request, "core/home.html", ctx)


def autocomplete(request):
    q = request.GET.get("q", "").strip()
    if len(q) < 2:
        return HttpResponse("")

    books = (
        Book.objects
        .annotate(sim=TrigramWordSimilarity(q, "title"))
        .filter(Q(sim__gte=0.15) | Q(title__icontains=q))
        .prefetch_related("authors")
        .only("id", "title")
        .order_by("-sim")[:6]
    )
    authors = (
        Author.objects
        .annotate(sim=TrigramWordSimilarity(q, "name"))
        .filter(Q(sim__gte=0.15) | Q(name__icontains=q))
        .only("id", "name")
        .order_by("-sim")[:3]
    )

    if not books and not authors:
        return HttpResponse("")

    return render(request, "search/_autocomplete.html", {
        "books": books,
        "authors": authors,
        "query": q,
    })


def _fts_search(query: str):
    """
    PostgreSQL Full Text Search с русской морфологией.
    Вес A → title, вес B → authors names, вес C → description.
    """
    try:
        search_query = SearchQuery(query, config="russian", search_type="websearch")
        vector = (
            SearchVector("title", weight="A", config="russian") +
            SearchVector("description", weight="C", config="russian")
        )
        qs = (
            Book.objects
            .annotate(rank=SearchRank(vector, search_query))
            .filter(rank__gte=0.05)
            .order_by("-rank")
            .prefetch_related("authors", "genres")
            .distinct()[:30]
        )

        results = list(qs)

        # Дополнительно ищем по именам авторов (триграммы для нечёткости)
        author_books = list(
            Book.objects
            .filter(
                Q(authors__name__icontains=query)
                | Q(authors__name__trigram_word_similar=query)
            )
            .exclude(pk__in={b.pk for b in results})
            .prefetch_related("authors", "genres")
            .distinct()[:10]
        )

        return results + author_books

    except Exception:
        # Если PostgreSQL FTS недоступна — fallback на триграммы
        return _trigram_search(query)


def _trigram_search(query: str):
    """Нечёткий поиск по триграммам (pg_trgm) — работает с опечатками."""
    threshold = 0.15

    books = list(
        Book.objects
        .annotate(sim=TrigramWordSimilarity(query, "title"))
        .filter(sim__gte=threshold)
        .order_by("-sim")
        .prefetch_related("authors", "genres")
        .distinct()[:20]
    )

    seen_ids = {b.pk for b in books}

    author_books = list(
        Book.objects
        .filter(
            authors__in=Author.objects
            .annotate(sim=TrigramWordSimilarity(query, "name"))
            .filter(sim__gte=threshold)
        )
        .exclude(pk__in=seen_ids)
        .prefetch_related("authors", "genres")
        .distinct()[:10]
    )

    return books + author_books


@require_POST
def ai_search(request):
    """
    AI-поиск: Claude разбирает свободный текст на структурированные фильтры,
    затем redirect на каталог с GET-параметрами.
    """
    query = request.POST.get("q", "").strip()
    if not query:
        return redirect("catalog")

    from django.conf import settings as conf
    api_key = getattr(conf, "ANTHROPIC_API_KEY", "")
    if not api_key:
        # Без API — обычный поиск
        return redirect(f"/books/?search={query}")

    from core.llm import chat_completion

    tools = [{
        "type": "function",
        "function": {
            "name": "extract_filters",
            "description": "Извлеки из запроса пользователя структурированные фильтры для поиска книг.",
            "parameters": {
                "type": "object",
                "properties": {
                    "authors": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Имена авторов, упомянутые в запросе",
                    },
                    "genres": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Жанры книг (детектив, фэнтези, роман и т.д.)",
                    },
                    "moods": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Настроения/атмосфера (уютная, мрачная, напряжённая, лёгкая и т.д.)",
                    },
                    "year_from": {
                        "type": "integer",
                        "description": "Год публикации — нижняя граница",
                    },
                    "year_to": {
                        "type": "integer",
                        "description": "Год публикации — верхняя граница",
                    },
                    "keywords": {
                        "type": "string",
                        "description": "Ключевые слова для текстового поиска (тема, сюжет)",
                    },
                },
                "required": [],
            },
        },
    }]

    try:
        response = chat_completion(
            tier="main",
            feature="ai_search",
            user=request.user if request.user.is_authenticated else None,
            max_tokens=300,
            messages=[{
                "role": "user",
                "content": (
                    f"Разбери запрос пользователя на фильтры для поиска книг. "
                    f"Вызови функцию extract_filters.\n\n"
                    f"Запрос: «{query}»"
                ),
            }],
            tools=tools,
            tool_choice={"type": "function", "function": {"name": "extract_filters"}},
        )
    except Exception as e:
        logger.error("AI search error: %s", e)
        return redirect(f"/books/?search={query}")

    # Извлекаем аргументы tool call
    filters = {}
    msg = response.choices[0].message
    if msg.tool_calls:
        try:
            filters = json.loads(msg.tool_calls[0].function.arguments)
        except (json.JSONDecodeError, IndexError):
            pass

    if not filters:
        return redirect(f"/books/?search={query}")

    # Матчим имена → ID в БД
    params = []

    # Авторы
    for name in filters.get("authors", []):
        author = (
            Author.objects.filter(name__iexact=name).first()
            or Author.objects.filter(name__icontains=name).first()
        )
        if author:
            params.append(f"author={author.pk}")

    # Жанры
    for name in filters.get("genres", []):
        genre = (
            Genre.objects.filter(name__iexact=name).first()
            or Genre.objects.filter(name__icontains=name).first()
        )
        if genre:
            params.append(f"genre={genre.pk}")

    # Настроения
    for name in filters.get("moods", []):
        mood = (
            MoodTag.objects.filter(name__iexact=name).first()
            or MoodTag.objects.filter(name__icontains=name).first()
        )
        if mood:
            params.append(f"mood={mood.pk}")

    # Годы
    if filters.get("year_from"):
        params.append(f"year_from={filters['year_from']}")
    if filters.get("year_to"):
        params.append(f"year_to={filters['year_to']}")

    # Ключевые слова
    keywords = filters.get("keywords", "").strip()
    if keywords:
        from urllib.parse import quote
        params.append(f"search={quote(keywords)}")

    if params:
        url = "/books/?" + "&".join(params)
    else:
        url = f"/books/?search={query}"

    return redirect(url)

from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import HttpResponse, JsonResponse, Http404, HttpResponseBadRequest
from django.core.paginator import Paginator
from django.conf import settings
from django.db.models import Q, F, Min, Max, Avg, Count, Exists, OuterRef
from django.db.models.functions import TruncDate
from django.views.decorators.http import require_GET, require_POST, require_http_methods
from django.core.exceptions import PermissionDenied

import logging
import requests as http_req
from datetime import date
from celery.result import AsyncResult

logger = logging.getLogger(__name__)

# ─── PRESET-ФИЛЬТРЫ КАТАЛОГА ─────────────────────────────────────────────────
# Пресет = именованный набор фиксированных query-параметров, который пользователь
# выбирает одним кликом. На бэкенде он не делает ничего особенного — просто
# подсвечивает «активный» чип, если набор GET-параметров точно совпал с пресетом.

# Какие ключи участвуют в матчинге пресета. Если в URL есть что-то ещё
# (например, выбран жанр), пресет считается неактивным — пользователь его дополнил.
_PRESET_RELEVANT_KEYS = ("ordering", "year_from", "year_to", "rating_min", "price_to")

def _build_catalog_presets():
    """Возвращает список словарей-пресетов. Год вычисляется на лету —
    «Новинки» = current_year минус 1, чтобы не править код каждый январь."""
    current_year = date.today().year
    return [
        {"slug": "new",     "label": "Новинки",       "params": {"ordering": "-publication_year", "year_from": str(current_year - 1)}},
        {"slug": "popular", "label": "Популярные",    "params": {"ordering": "-rating_count"}},
        {"slug": "top",     "label": "Топ-рейтинг",   "params": {"ordering": "-avg_rating", "rating_min": "4.5"}},
        {"slug": "classic", "label": "Классика",      "params": {"ordering": "-avg_rating", "year_to": "1960"}},
        {"slug": "cheap",   "label": "До 300 ₽",      "params": {"ordering": "avg_price",   "price_to": "300"}},
    ]

def _detect_active_preset(params, presets):
    """Определяет, какой пресет «выбран» сейчас. Точное совпадение по relevant-ключам;
    дополнительные фильтры (жанр, автор, поиск) — допускаются, считаем сужение пресета.
    """
    incoming = {k: params.get(k, "").strip() for k in _PRESET_RELEVANT_KEYS}
    for preset in presets:
        expected = {k: preset["params"].get(k, "") for k in _PRESET_RELEVANT_KEYS}
        if incoming == expected:
            return preset["slug"]
    return None

from .models import (
    Book, Genre, UserList, Store, BookStore, Language, Author,
    BookPrice, ReadingProgress, Quote, PriceAlert, Publisher, Series,
    MoodTag, BookMood, BookEdition, BookText, BookChapter, BookNote,
)
from reviews.models import Review, ReviewLike, Critique
from .recommendations import similar_books as get_similar, also_read as get_also_read
from users.models import AuthorSubscription
from .ai_recommendations import invalidate as invalidate_ai_cache
from .tasks import scrape_book_prices, generate_smart_quotes
from .isbn_lookup import lookup_by_isbn
from .reading_pace import predict_reading_time

# ─── ДЕКОРАТОРЫ ───────────────────────────────────────────────────────────────

def staff_required(view_func):
    """Декоратор, разрешающий доступ только персоналу (staff)."""
    def _wrapped(request, *args, **kwargs):
        if not request.user.is_staff:
            raise PermissionDenied
        return view_func(request, *args, **kwargs)
    return _wrapped

# ─── ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ─────────────────────────────────────────────────

def _filter_books(params, base_qs=None):
    """
    Применяет фильтры из GET-параметров к queryset книг.
    Возвращает (qs, filter_context), где filter_context — словарь с
    выбранными значениями фильтров для передачи в шаблон.
    """
    if base_qs is None:
        qs = Book.objects.prefetch_related("authors", "genres").select_related("publisher", "language")
    else:
        qs = base_qs

    # Текстовый поиск
    search = params.get("search", "").strip()
    if search:
        qs = qs.filter(
            Q(title__icontains=search)
            | Q(authors__name__icontains=search)
            | Q(genres__name__icontains=search)
            | Q(description__icontains=search)
            | Q(isbn__iexact=search)
        ).distinct()

    # Мультиселекты
    genre_ids = params.getlist("genre")
    for gid in genre_ids:
        qs = qs.filter(genres__id=gid)
    if genre_ids:
        qs = qs.distinct()

    author_ids = params.getlist("author")
    for aid in author_ids:
        qs = qs.filter(authors__id=aid)
    if author_ids:
        qs = qs.distinct()

    language_ids = params.getlist("language")
    if language_ids:
        qs = qs.filter(language__id__in=language_ids)

    # Диапазоны
    year_from = params.get("year_from", "").strip()
    year_to   = params.get("year_to", "").strip()
    if year_from.isdigit():
        qs = qs.filter(publication_year__gte=int(year_from))
    if year_to.isdigit():
        qs = qs.filter(publication_year__lte=int(year_to))

    pages_from = params.get("pages_from", "").strip()
    pages_to   = params.get("pages_to", "").strip()
    if pages_from.isdigit():
        qs = qs.filter(pages__gte=int(pages_from))
    if pages_to.isdigit():
        qs = qs.filter(pages__lte=int(pages_to))

    price_from = params.get("price_from", "").strip()
    price_to   = params.get("price_to", "").strip()
    if price_from:
        try:
            qs = qs.filter(avg_price__gte=float(price_from))
        except ValueError:
            pass
    if price_to:
        try:
            qs = qs.filter(avg_price__lte=float(price_to))
        except ValueError:
            pass

    rating_min = params.get("rating_min", "").strip()
    if rating_min:
        try:
            qs = qs.filter(avg_rating__gte=float(rating_min))
        except ValueError:
            pass

    # Mood-фильтр
    mood_ids = params.getlist("mood")
    if mood_ids:
        qs = qs.filter(moods__mood_id__in=mood_ids).distinct()

    # Сортировка
    ordering = params.get("ordering", "-avg_rating")
    if ordering in {"-avg_rating", "-rating_count", "-publication_year",
                    "publication_year", "avg_price", "-avg_price"}:
        qs = qs.order_by(ordering)

    # Контекст для шаблона (выбранные значения)
    filter_ctx = {
        "search": search,
        "selected_genres": genre_ids,
        "selected_authors": author_ids,
        "selected_languages": language_ids,
        "selected_moods": mood_ids,
        "year_from": year_from,
        "year_to": year_to,
        "pages_from": pages_from,
        "pages_to": pages_to,
        "price_from": price_from,
        "price_to": price_to,
        "rating_min": rating_min,
        "ordering": ordering,
    }
    return qs, filter_ctx

def _get_book_detail_context(book, request):
    # Scope: 'edition' (по умолчанию — только это издание) или 'all' (все книги в группе)
    scope = request.GET.get("scope", "edition")
    if scope == "all" and book.edition_group_id:
        scope_book_ids = list(
            Book.objects.filter(edition_group=book.edition_group).values_list("pk", flat=True)
        )
    else:
        scope = "edition"
        scope_book_ids = [book.pk]

    # Одобренные рецензии — аннотированы лайками, отсортированы по популярности
    _like_filter = (
        ReviewLike.objects.filter(review=OuterRef("pk"), user=request.user)
        if request.user.is_authenticated
        else ReviewLike.objects.none()
    )
    REVIEWS_PER_PAGE = 5
    reviews_qs = (
        Review.objects
        .filter(book_id__in=scope_book_ids, status=Review.APPROVED)
        .select_related("user", "user__profile", "book")
        .annotate(
            likes_count=Count("likes", distinct=True),
            user_liked=Exists(_like_filter),
        )
        .order_by("-likes_count", "-created_at")
    )
    review_count = reviews_qs.count()
    reviews = reviews_qs[:REVIEWS_PER_PAGE]
    has_more_reviews = review_count > REVIEWS_PER_PAGE
    user_has_review = reviews_qs.filter(user=request.user).exists() if request.user.is_authenticated else False

    # Списки пользователя
    user_lists = []
    book_list_ids = set()
    if request.user.is_authenticated:
        user_lists = UserList.objects.filter(user=request.user)
        book_list_ids = set(user_lists.filter(books=book).values_list("id", flat=True))

    # Ссылки на магазины
    store_links = list(book.store_links.select_related("store").filter(store__is_active=True))
    linked_ids = {sl.store_id for sl in store_links}
    unlinked_stores = [s for s in Store.objects.filter(is_active=True) if s.id not in linked_ids]

    # Данные для инлайн-редактирования (только staff)
    edit_author_ids = "[" + ",".join(str(a.pk) for a in book.authors.all()) + "]"
    edit_genre_ids  = "[" + ",".join(str(g.pk) for g in book.genres.all()) + "]"

    # Прогресс чтения и алерт цены текущего пользователя
    reading_progress = None
    user_price_alert = None
    reading_prediction = None
    if request.user.is_authenticated:
        reading_progress = ReadingProgress.objects.filter(user=request.user, book=book).first()
        user_price_alert = PriceAlert.objects.filter(user=request.user, book=book).first()
        reading_prediction = predict_reading_time(request.user, book)

    # Может ли текущий юзер читать полный текст?
    # (staff всегда; обычный юзер — если книга в одном из его списков)
    can_read_text = False
    if request.user.is_authenticated:
        if request.user.is_staff:
            can_read_text = True
        else:
            can_read_text = bool(book_list_ids)

    # Рецензии (Critique) — считаем один раз, чтобы не делать 3 одинаковых COUNT().
    _critiques_qs = (
        Critique.objects
        .filter(book_id__in=scope_book_ids, status=Critique.APPROVED)
        .select_related("user", "user__profile", "book")
        .prefetch_related("criteria")
        .annotate(likes_count=Count("likes", distinct=True))
        .order_by("-likes_count", "-created_at")
    )
    _critique_count = _critiques_qs.count()
    _critiques_first_page = list(_critiques_qs[:5])

    return {
        "book": book,
        "reviews": reviews,
        "review_count": review_count,
        "has_more_reviews": has_more_reviews,
        "next_page": 2,
        "user_lists": user_lists,
        "book_list_ids": book_list_ids,
        "store_links": store_links,
        "unlinked_stores": unlinked_stores,
        "similar": get_similar(book, limit=5),
        "also_read": get_also_read(book, limit=6),
        "user_has_review": user_has_review,
        "active_tab": request.GET.get("tab", "about"),
        "quotes": Quote.objects.filter(book=book).select_related("user", "mood_tag"),
        "quotes_count": Quote.objects.filter(book=book).count(),
        "moods": BookMood.objects.filter(book=book).select_related("mood").order_by("-confidence", "-vote_count"),
        "reading_progress": reading_progress,
        "reading_prediction": reading_prediction,
        "user_price_alert": user_price_alert,
        "can_read_text": can_read_text,
        "all_authors": Author.objects.order_by("name"),
        "all_genres": Genre.objects.order_by("name"),
        "all_languages": Language.objects.order_by("name"),
        "all_publishers": Publisher.objects.order_by("name"),
        "all_series": Series.objects.order_by("name"),
        "edit_author_ids": edit_author_ids,
        "edit_genre_ids": edit_genre_ids,
        "edit_publisher_id": book.publisher_id,
        "edit_publisher_name": book.publisher.name if book.publisher else "",
        "edit_series_id": book.series_id,
        "edit_series_name": book.series.name if book.series else "",
        "critiques": _critiques_first_page,
        "critique_count": _critique_count,
        # has_more_critiques нужен шаблону _critique_list.html, чтобы кнопка
        # «Показать ещё» появилась уже на ПЕРВОМ рендере (а не только после AJAX).
        "has_more_critiques": _critique_count > 5,
        "scope": scope,
        "editions_in_group": (
            list(
                Book.objects
                .filter(edition_group=book.edition_group)
                .exclude(pk=book.pk)
                .select_related("publisher")
                .prefetch_related("authors")
            ) if book.edition_group_id else []
        ),
    }

def _get_author_detail_context(author, request):
    """Собирает контекст для страницы автора."""
    params = request.GET
    base_qs = author.books.prefetch_related("authors", "genres").select_related("publisher", "language")
    qs, filter_ctx = _filter_books(params, base_qs)

    paginator = Paginator(qs, settings.BOOKS_PER_PAGE)
    page = paginator.get_page(params.get("page", 1))

    # Убираем page из query_string для ссылок пагинации
    query_dict = params.copy()
    query_dict.pop("page", None)
    query_string = query_dict.urlencode()

    # Агрегаты для слайдеров
    agg = author.books.aggregate(
        min_year=Min("publication_year"),
        max_year=Max("publication_year"),
    )

    # Подписка
    is_subscribed = False
    if request.user.is_authenticated:
        is_subscribed = AuthorSubscription.objects.filter(user=request.user, author=author).exists()

    # Все жанры, в которых есть книги этого автора
    all_genres = Genre.objects.filter(books__authors=author).distinct()

    has_filters = any([
        filter_ctx["search"], filter_ctx["selected_genres"],
        filter_ctx["year_from"], filter_ctx["year_to"],
        filter_ctx["rating_min"]
    ])

    return {
        "author": author,
        "books": page,
        "total": paginator.count,
        "query_string": query_string,
        "has_filters": has_filters,
        "all_genres": all_genres,
        "selected_genres": filter_ctx["selected_genres"],
        "agg": agg,
        "f": params,
        "is_subscribed": is_subscribed,
    }

def _inline_create(request, model_class, name_field="name"):
    """
    Общая функция для создания объекта через AJAX.
    Принимает POST-запрос с полем name_field, возвращает JSON.
    """
    if request.method != "POST":
        return JsonResponse({"error": "Method not allowed"}, status=405)
    name = request.POST.get(name_field, "").strip()
    if not name:
        return JsonResponse({"error": f"Поле {name_field} обязательно"}, status=400)
    obj, created = model_class.objects.get_or_create(**{name_field: name})
    return JsonResponse({"id": obj.pk, "name": getattr(obj, name_field), "created": created})

# ─── КАТАЛОГ ─────────────────────────────────────────────────────────────────

@require_GET
def catalog(request):
    params = request.GET
    qs, filter_ctx = _filter_books(params)

    # Пагинация
    paginator = Paginator(qs, settings.BOOKS_PER_PAGE)
    page = paginator.get_page(params.get("page", 1))

    # Убираем page из query_string
    query_dict = params.copy()
    query_dict.pop("page", None)
    query_string = query_dict.urlencode()

    # Агрегаты для диапазонов (глобальные минимумы/максимумы)
    agg = Book.objects.aggregate(
        min_year=Min("publication_year"), max_year=Max("publication_year"),
        min_pages=Min("pages"), max_pages=Max("pages"),
        min_price=Min("avg_price"), max_price=Max("avg_price"),
    )

    has_filters = any([
        filter_ctx["search"], filter_ctx["selected_genres"],
        filter_ctx["selected_authors"], filter_ctx["selected_languages"],
        filter_ctx["selected_moods"],
        filter_ctx["year_from"], filter_ctx["year_to"],
        filter_ctx["pages_from"], filter_ctx["pages_to"],
        filter_ctx["price_from"], filter_ctx["price_to"],
        filter_ctx["rating_min"]
    ])

    # Preset-фильтры: одним кликом ставим набор query-параметров.
    presets = _build_catalog_presets()
    active_preset = _detect_active_preset(params, presets)

    ctx = {
        "books": page,
        "total": paginator.count,
        "query_string": query_string,
        "has_filters": has_filters,
        "all_genres": Genre.objects.all(),
        "all_authors": Author.objects.all()[:200],
        "all_languages": Language.objects.all(),
        "all_moods": MoodTag.objects.all(),
        "selected_genres": filter_ctx["selected_genres"],
        "selected_authors": filter_ctx["selected_authors"],
        "selected_languages": filter_ctx["selected_languages"],
        "selected_moods": filter_ctx["selected_moods"],
        "agg": agg,
        "f": params,
        "presets": presets,
        "active_preset": active_preset,
    }
    if getattr(request, "htmx", False):
        return render(request, "books/_catalog_results.html", ctx)
    return render(request, "books/catalog.html", ctx)

# ─── СТРАНИЦА КНИГИ ──────────────────────────────────────────────────────────

@require_GET
def book_detail(request, pk):
    book = get_object_or_404(
        Book.objects.prefetch_related("authors", "genres", "store_links__store"),
        pk=pk
    )
    ctx = _get_book_detail_context(book, request)

    # Запуск генерации AI-цитат, если их ещё нет
    if not book.quotes.filter(is_ai_generated=True).exists():
        generate_smart_quotes.delay(book.pk)

    return render(request, "books/book_detail.html", ctx)


# ─── ГРУППЫ ИЗДАНИЙ: JSON-ENDPOINT ДЛЯ ПЕРЕКЛЮЧЕНИЯ ─────────────────────────

@require_GET
def edition_data(request, pk):
    """JSON с издательскими полями книги для swap-анимации на странице."""
    book = get_object_or_404(
        Book.objects.select_related("publisher").prefetch_related("authors"),
        pk=pk,
    )
    return JsonResponse({
        "id": book.pk,
        "url": f"/books/{book.pk}/",
        "title": book.title,
        "authors": ", ".join(a.name for a in book.authors.all()),
        "publisher": book.publisher.name if book.publisher else "",
        "publication_year": book.publication_year or "",
        "pages": book.pages or "",
        "isbn": book.isbn or "",
        "description": book.description or "",
        "cover_url": book.cover_image.url if book.cover_image else "",
    })


# ─── АДМИН: ГРУППЫ ИЗДАНИЙ ──────────────────────────────────────────────────

@staff_required
@require_GET
def editions_list(request):
    """Список всех групп изданий (для вкладки в админ-панели)."""
    q = request.GET.get("q", "").strip()
    qs = BookEdition.objects.prefetch_related("books__publisher").order_by("name")
    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(books__title__icontains=q)).distinct()
    return render(request, "books/_admin_editions_list.html", {"editions": qs})


@staff_required
@require_http_methods(["GET", "POST"])
def edition_create(request):
    """Создать новую группу изданий."""
    if request.method == "GET":
        all_books = (
            Book.objects
            .prefetch_related("authors")
            .select_related("publisher", "edition_group")
            .order_by("title")[:2000]
        )
        return render(request, "books/edition_form.html", {"all_books": all_books})

    name = (request.POST.get("name") or "").strip()
    book_ids = request.POST.getlist("book_ids")
    if not name:
        return HttpResponseBadRequest("Название обязательно")

    edition = BookEdition.objects.create(name=name)
    if book_ids:
        Book.objects.filter(pk__in=book_ids).update(edition_group=edition)
    return redirect(f"/books/editions/{edition.pk}/edit/")


@staff_required
@require_http_methods(["GET", "POST"])
def edition_edit(request, pk):
    """Редактировать группу: название + состав книг."""
    edition = get_object_or_404(BookEdition, pk=pk)
    if request.method == "POST":
        name = (request.POST.get("name") or "").strip()
        if name:
            edition.name = name
            edition.save(update_fields=["name"])
        return redirect(f"/books/editions/{edition.pk}/edit/")

    edition_books = list(edition.books.prefetch_related("authors").select_related("publisher"))
    # Автопредложения: совпадение title + первого автора у книг без группы
    suggestions = []
    if edition_books:
        base = edition_books[0]
        base_first_author = base.authors.first()
        candidates = Book.objects.filter(
            title__iexact=base.title,
        ).exclude(pk__in=[b.pk for b in edition_books])
        if base_first_author:
            candidates = candidates.filter(authors=base_first_author)
        candidates = candidates.filter(edition_group__isnull=True).select_related("publisher").prefetch_related("authors")[:20]
        suggestions = list(candidates)

    return render(request, "books/edition_edit.html", {
        "edition": edition,
        "books": edition_books,
        "suggestions": suggestions,
    })


@staff_required
@require_POST
def edition_add_book(request, pk):
    """Добавить книгу в группу (заменит старую группу у книги, если была)."""
    edition = get_object_or_404(BookEdition, pk=pk)
    book_id = request.POST.get("book_id")
    book = get_object_or_404(Book, pk=book_id)
    book.edition_group = edition
    book.save(update_fields=["edition_group"])
    return render(request, "books/_admin_edition_book_row.html", {"book": book, "edition": edition})


@staff_required
@require_POST
def edition_remove_book(request, pk, book_id):
    """Убрать книгу из группы (edition_group=NULL)."""
    get_object_or_404(BookEdition, pk=pk)
    book = get_object_or_404(Book, pk=book_id)
    book.edition_group = None
    book.save(update_fields=["edition_group"])
    return HttpResponse("")


@staff_required
@require_POST
def edition_delete(request, pk):
    """Удалить группу (книги становятся одиночными через on_delete=SET_NULL)."""
    edition = get_object_or_404(BookEdition, pk=pk)
    edition.delete()
    return redirect("admin_panel")


@staff_required
@require_GET
def edition_search_books(request):
    """HTMX: поиск книг для добавления в группу.
    Показывает ВСЕ книги, помечая те, что уже входят в другую группу."""
    q = (request.GET.get("q") or "").strip()
    edition_pk = request.GET.get("edition")
    try:
        edition_pk_int = int(edition_pk) if edition_pk else None
    except ValueError:
        edition_pk_int = None

    qs = Book.objects.prefetch_related("authors").select_related("publisher", "edition_group")
    if q:
        qs = qs.filter(Q(title__icontains=q) | Q(authors__name__icontains=q)).distinct()
    qs = qs.order_by("title")[:40]
    return render(request, "books/_admin_edition_search.html", {
        "books": qs, "edition_pk": edition_pk_int,
    })


# ─── УПРАВЛЕНИЕ СПИСКАМИ ─────────────────────────────────────────────────────

@login_required
@require_POST
def toggle_list(request):
    book = get_object_or_404(Book, pk=request.POST.get("book_id"))
    list_id = request.POST.get("list_id")
    user_list = get_object_or_404(UserList, pk=list_id, user=request.user)

    if user_list.books.filter(pk=book.pk).exists():
        user_list.books.remove(book)
    else:
        user_list.books.add(book)
        # Событие для ленты
        from social.models import ActivityEvent
        ActivityEvent.objects.create(
            user=request.user,
            event_type="add_to_list",
            book=book,
            metadata={"list_name": user_list.name},
        )

    # Инвалидация AI‑кеша
    invalidate_ai_cache(request.user.pk)

    # Актуальные списки пользователя
    book_list_ids = set(
        UserList.objects.filter(user=request.user, books=book).values_list("id", flat=True)
    )
    user_lists = UserList.objects.filter(user=request.user)

    return render(request, "books/_list_dropdown.html", {
        "book": book,
        "user_lists": user_lists,
        "book_list_ids": book_list_ids,
        "partial": True
    })

# ─── ЗАПРОС ЦЕНЫ + ПОЛЛИНГ ───────────────────────────────────────────────────

@login_required
@require_POST
def request_price(request, pk):
    book = get_object_or_404(Book, pk=pk)

    # reCAPTCHA v2 verification
    recaptcha_secret = getattr(settings, "RECAPTCHA_PRIVATE_KEY", "")
    if recaptcha_secret:
        token = request.POST.get("g-recaptcha-response", "")
        if not token:
            return render(request, "books/_price_block.html", {
                "book": book, "pending": False, "captcha_error": True
            })
        resp = http_req.post(
            "https://www.google.com/recaptcha/api/siteverify",
            data={"secret": recaptcha_secret, "response": token},
            timeout=10,
        )
        result = resp.json()
        if not result.get("success"):
            return render(request, "books/_price_block.html", {
                "book": book, "pending": False, "captcha_error": True
            })

    result = scrape_book_prices.delay(book.pk)
    request.session[f"price_task_{book.pk}"] = result.id

    return render(request, "books/_price_block.html", {
        "book": book, "pending": True, "task_id": result.id
    })

@login_required
@require_GET
def price_captcha(request, pk):
    book = get_object_or_404(Book, pk=pk)
    return render(request, "books/_price_captcha.html", {
        "book": book,
        "recaptcha_site_key": settings.RECAPTCHA_PUBLIC_KEY,
    })

@require_GET
def price_status(request, pk):
    book = get_object_or_404(Book, pk=pk)
    task_id = request.GET.get("task_id") or request.session.get(f"price_task_{book.pk}")

    done = True
    if task_id:
        result = AsyncResult(task_id)
        done = result.ready()

    if done:
        book.refresh_from_db()
        return render(request, "books/_price_block.html", {"book": book, "pending": False})
    return render(request, "books/_price_block.html", {
        "book": book, "pending": True, "task_id": task_id
    })

@require_GET
def price_chart_data(request, pk):
    book = get_object_or_404(Book, pk=pk)
    store_links = BookStore.objects.filter(book=book).select_related("store")

    datasets = []
    all_dates = set()
    palette = ["#6366f1", "#f59e0b", "#10b981", "#ef4444", "#8b5cf6", "#06b6d4"]

    for i, link in enumerate(store_links):
        rows = (
            BookPrice.objects
            .filter(book_store=link)
            .annotate(day=TruncDate("created_at"))
            .values("day")
            .annotate(avg=Avg("price"))
            .order_by("day")
        )
        if not rows:
            continue

        data = {str(r["day"]): float(r["avg"]) for r in rows}
        all_dates.update(data.keys())

        datasets.append({
            "label": link.store.name,
            "data": data,
            "color": palette[i % len(palette)],
            "borderDash": [],
        })

    if not all_dates:
        return JsonResponse({"labels": [], "datasets": []})

    labels = sorted(all_dates)

    # Средняя по всем магазинам за день
    avg_rows = (
        BookPrice.objects
        .filter(book_store__book=book)
        .annotate(day=TruncDate("created_at"))
        .values("day")
        .annotate(avg=Avg("price"))
        .order_by("day")
    )
    avg_data = {str(r["day"]): float(r["avg"]) for r in avg_rows}

    datasets.append({
        "label": "Средняя",
        "data": avg_data,
        "color": "#111111",
        "borderDash": [6, 3],
    })

    # Нормализуем: для каждого датасета список значений по labels
    for ds in datasets:
        ds["points"] = [ds["data"].get(l) for l in labels]
        del ds["data"]

    return JsonResponse({"labels": labels, "datasets": datasets})

# ─── СТРАНИЦА АВТОРА ─────────────────────────────────────────────────────────

@require_GET
def author_detail(request, pk):
    author = get_object_or_404(Author.objects.prefetch_related("books"), pk=pk)
    ctx = _get_author_detail_context(author, request)
    if getattr(request, "htmx", False):
        return render(request, "books/_book_list.html", ctx)
    return render(request, "books/author_detail.html", ctx)

# ─── УПРАВЛЕНИЕ ССЫЛКАМИ НА МАГАЗИНЫ (STAFF) ─────────────────────────────────

@staff_required
@require_POST
def store_link_save(request, book_id):
    book = get_object_or_404(Book, pk=book_id)
    store = get_object_or_404(Store, pk=request.POST.get("store_id"))
    url = request.POST.get("product_url", "").strip()
    if not url:
        return HttpResponseBadRequest("URL обязателен")
    BookStore.objects.update_or_create(
        book=book, store=store,
        defaults={"product_url": url},
    )
    return _render_store_links(request, book)

@staff_required
@require_POST
def store_link_delete(request, book_id, store_id):
    BookStore.objects.filter(book_id=book_id, store_id=store_id).delete()
    book = get_object_or_404(Book, pk=book_id)
    return _render_store_links(request, book)

def _render_store_links(request, book):
    """Рендерит частичный шаблон со ссылками на магазины."""
    store_links = list(book.store_links.select_related("store").filter(store__is_active=True))
    linked_ids = {sl.store_id for sl in store_links}
    unlinked_stores = [s for s in Store.objects.filter(is_active=True) if s.id not in linked_ids]
    return render(request, "books/_store_links.html", {
        "book": book,
        "store_links": store_links,
        "unlinked_stores": unlinked_stores,
    })

# ─── ADMIN PARTIALS ───────────────────────────────────────────────────────────

@staff_required
@require_POST
def admin_delete_book(request, pk):
    get_object_or_404(Book, pk=pk).delete()
    return HttpResponse("")

@staff_required
@require_GET
def admin_books_partial(request):
    q = request.GET.get("q", "")
    qs = Book.objects.prefetch_related("authors", "genres")
    if q:
        qs = qs.filter(Q(title__icontains=q) | Q(authors__name__icontains=q)).distinct()
    return render(request, "books/_admin_books.html", {"books": qs[:50]})

# ─── ISBN LOOKUP (STAFF) ─────────────────────────────────────────────────────

@staff_required
@require_GET
def isbn_lookup(request):
    """HTMX endpoint: ищет книгу по ISBN через Google Books / Open Library."""
    isbn = request.GET.get("isbn", "").strip()
    if len(isbn) < 10:
        return HttpResponse("")
    data = lookup_by_isbn(isbn)
    if not data:
        return render(request, "books/_isbn_preview.html", {"not_found": True, "isbn": isbn})

    # Матчим авторов из API с авторами в БД
    author_matches = []  # [{api_name, db_author, exact}]
    all_authors_qs = Author.objects.order_by("name")
    for api_name in (data.get("authors") or []):
        api_lower = api_name.lower().strip()
        exact = Author.objects.filter(name__iexact=api_name.strip()).first()
        if exact:
            author_matches.append({"api_name": api_name, "db_author": exact, "exact": True, "candidates": []})
        else:
            # Частичное совпадение — по словам из имени
            words = [w for w in api_lower.split() if len(w) > 2]
            from django.db.models import Q as _Q
            q = _Q()
            for w in words:
                q |= _Q(name__icontains=w)
            candidates = list(Author.objects.filter(q).order_by("name")[:10]) if words else []
            author_matches.append({"api_name": api_name, "db_author": None, "exact": False, "candidates": candidates})

    # Матчим жанры из API с жанрами в БД
    genre_matches = []
    for api_genre in (data.get("genres") or []):
        exact = Genre.objects.filter(name__iexact=api_genre.strip()).first()
        if exact:
            genre_matches.append({"api_name": api_genre, "db_genre": exact, "exact": True, "candidates": []})
        else:
            candidates = list(Genre.objects.filter(name__icontains=api_genre.strip()[:20]).order_by("name")[:10])
            genre_matches.append({"api_name": api_genre, "db_genre": None, "exact": False, "candidates": candidates})

    ctx = {
        "data": data,
        "author_matches": author_matches,
        "genre_matches": genre_matches,
        "all_authors": all_authors_qs,
        "all_genres": Genre.objects.order_by("name"),
    }
    return render(request, "books/_isbn_preview.html", ctx)

# ─── ДОБАВЛЕНИЕ / РЕДАКТИРОВАНИЕ КНИГ (STAFF) ────────────────────────────────

@staff_required
@require_http_methods(["GET", "POST"])
def book_add(request):
    copy_from = None
    form_data = {}
    selected_author_ids = "[]"
    selected_genre_ids = "[]"
    selected_publisher_id = None
    selected_series_id = None

    copy_pk = request.GET.get("copy_from") or request.POST.get("copy_from")
    if copy_pk:
        try:
            copy_from = Book.objects.prefetch_related("authors", "genres").get(pk=copy_pk)
            form_data = {
                "title": copy_from.title + " (копия)",
                "isbn": "",
                "description": copy_from.description,
                "publication_year": copy_from.publication_year,
                "pages": copy_from.pages,
                "language_id": copy_from.language_id,
                "publisher_name": copy_from.publisher.name if copy_from.publisher else "",
                "series_name": copy_from.series.name if copy_from.series else "",
            }
            selected_author_ids = "[" + ",".join(str(a.pk) for a in copy_from.authors.all()) + "]"
            selected_genre_ids = "[" + ",".join(str(g.pk) for g in copy_from.genres.all()) + "]"
            selected_publisher_id = copy_from.publisher_id
            selected_series_id = copy_from.series_id
        except Book.DoesNotExist:
            pass

    if request.method == "POST":
        title = request.POST.get("title", "").strip()
        if not title:
            ctx = _book_form_context()
            ctx.update({
                "error": "Название обязательно",
                "form_data": request.POST,
                "copy_from": copy_from,
                "selected_author_ids": "[" + ",".join(request.POST.getlist("authors")) + "]",
                "selected_genre_ids": "[" + ",".join(request.POST.getlist("genres")) + "]",
                "selected_publisher_id": request.POST.get("publisher_id") or None,
                "selected_series_id": request.POST.get("series_id") or None,
            })
            return render(request, "books/book_add.html", ctx)

        # Издательство и серия
        publisher = _get_or_create_publisher(request)
        series = _get_or_create_series(request)
        language_pk = request.POST.get("language", "").strip()
        language = Language.objects.filter(pk=language_pk).first() if language_pk else None

        pub_year = request.POST.get("publication_year", "").strip()
        pages = request.POST.get("pages", "").strip()

        book = Book.objects.create(
            title=title,
            isbn=request.POST.get("isbn", "").strip() or None,
            description=request.POST.get("description", "").strip(),
            publication_year=int(pub_year) if pub_year.isdigit() else None,
            pages=int(pages) if pages.isdigit() else None,
            publisher=publisher,
            series=series,
            language=language,
        )

        if "cover_image" in request.FILES:
            book.cover_image = request.FILES["cover_image"]
            book.save(update_fields=["cover_image"])

        author_ids = request.POST.getlist("authors")
        genre_ids = request.POST.getlist("genres")
        if author_ids:
            book.authors.set(Author.objects.filter(pk__in=author_ids))
        if genre_ids:
            book.genres.set(Genre.objects.filter(pk__in=genre_ids))

        messages.success(request, f"Книга «{book.title}» добавлена.")
        return redirect("book_detail", pk=book.pk)

    ctx = _book_form_context()
    ctx.update({
        "copy_from": copy_from,
        "form_data": form_data,
        "selected_author_ids": selected_author_ids,
        "selected_genre_ids": selected_genre_ids,
        "selected_publisher_id": selected_publisher_id,
        "selected_series_id": selected_series_id,
    })
    return render(request, "books/book_add.html", ctx)

@staff_required
@require_POST
def book_edit(request, pk):
    book = get_object_or_404(Book, pk=pk)

    title = request.POST.get("title", "").strip()
    if not title:
        messages.error(request, "Название не может быть пустым.")
        return redirect("book_detail", pk=pk)

    publisher = _get_or_create_publisher(request)
    series = _get_or_create_series(request)
    language_pk = request.POST.get("language", "").strip()
    language = Language.objects.filter(pk=language_pk).first() if language_pk else None

    pub_year = request.POST.get("publication_year", "").strip()
    pages = request.POST.get("pages", "").strip()

    book.title = title
    book.isbn = request.POST.get("isbn", "").strip() or None
    book.description = request.POST.get("description", "").strip()
    book.publication_year = int(pub_year) if pub_year.isdigit() else None
    book.pages = int(pages) if pages.isdigit() else None
    book.publisher = publisher
    book.series = series
    book.language = language
    book.save()

    if "cover_image" in request.FILES:
        book.cover_image = request.FILES["cover_image"]
        book.save(update_fields=["cover_image"])

    author_ids = request.POST.getlist("authors")
    genre_ids = request.POST.getlist("genres")
    book.authors.set(Author.objects.filter(pk__in=author_ids))
    book.genres.set(Genre.objects.filter(pk__in=genre_ids))

    messages.success(request, f"Книга «{book.title}» обновлена.")
    return redirect("book_detail", pk=pk)

# ═══════════════════════════════════════════════════════════════════════════════
# ПОЛНЫЙ ТЕКСТ КНИГИ: ЗАГРУЗКА / ЧТЕНИЕ / ПРОГРЕСС
# ═══════════════════════════════════════════════════════════════════════════════

MAX_TEXT_FILE_BYTES = 30 * 1024 * 1024  # 30 MB


@staff_required
@require_POST
def book_text_upload(request, pk):
    """Загрузить EPUB или FB2 для книги. Только staff."""
    book = get_object_or_404(Book, pk=pk)

    f = request.FILES.get("text_file")
    if not f:
        messages.error(request, "Файл не выбран.")
        return redirect("book_detail", pk=pk)

    if f.size > MAX_TEXT_FILE_BYTES:
        messages.error(request, f"Файл слишком большой (> {MAX_TEXT_FILE_BYTES // 1024 // 1024} МБ).")
        return redirect("book_detail", pk=pk)

    from .text_extractor import extract_book_text, detect_format
    fmt = detect_format(f.name)
    if fmt is None:
        messages.error(request, "Поддерживаются только .epub, .fb2 и .fb2.zip.")
        return redirect("book_detail", pk=pk)

    # Читаем файл в память (до 30 МБ — нормально) и сразу пробуем распарсить
    raw = f.read()
    try:
        chapters = extract_book_text(raw, fmt)
    except Exception as exc:
        messages.error(request, f"Не удалось разобрать файл: {exc}")
        return redirect("book_detail", pk=pk)

    # Сбрасываем старые записи, если были
    BookText.objects.filter(book=book).delete()

    # Создаём BookText и главы атомарно
    from django.db import transaction
    from django.core.files.base import ContentFile

    with transaction.atomic():
        bt = BookText.objects.create(
            book=book,
            source_format=fmt,
            uploaded_by=request.user if request.user.is_authenticated else None,
            extract_status=BookText.STATUS_PENDING,
        )
        bt.source_file.save(f.name, ContentFile(raw), save=False)

        total_words = 0
        total_chars = 0
        chapter_objs = []
        for i, ch in enumerate(chapters):
            chapter_objs.append(BookChapter(
                book_text=bt,
                order=i,
                title=ch.title[:300],
                html=ch.html,
                text=ch.text,
                word_count=ch.word_count,
            ))
            total_words += ch.word_count
            total_chars += len(ch.text)
        BookChapter.objects.bulk_create(chapter_objs)

        bt.word_count = total_words
        bt.char_count = total_chars
        bt.extract_status = BookText.STATUS_OK
        bt.save()

    messages.success(request, f"Загружено: {len(chapters)} глав, {total_words:,} слов.".replace(",", " "))
    return redirect("book_detail", pk=pk)


@staff_required
@require_POST
def book_text_delete(request, pk):
    """Удалить загруженный текст книги."""
    book = get_object_or_404(Book, pk=pk)
    BookText.objects.filter(book=book).delete()
    messages.success(request, "Полный текст книги удалён.")
    return redirect("book_detail", pk=pk)


def _user_can_read(request, book) -> bool:
    """Кто может открыть читалку: staff всегда, обычный юзер — если книга в его списках."""
    u = request.user
    if not u.is_authenticated:
        return False
    if u.is_staff:
        return True
    return UserList.objects.filter(user=u, books=book).exists()


@login_required
def book_read(request, pk, chapter_order=None):
    """Страница-читалка. Если chapter_order не указан — открываем текущую
    главу из прогресса пользователя либо первую."""
    book = get_object_or_404(Book, pk=pk)
    if not _user_can_read(request, book):
        raise PermissionDenied("Чтобы читать книгу, добавьте её в любой свой список.")

    text = getattr(book, "text", None)
    if text is None or not text.is_ready:
        messages.info(request, "У этой книги пока нет загруженного текста.")
        return redirect("book_detail", pk=pk)

    chapters = list(text.chapters.order_by("order"))
    if not chapters:
        messages.info(request, "У этой книги пока нет загруженного текста.")
        return redirect("book_detail", pk=pk)

    # Выбор текущей главы
    progress, _ = ReadingProgress.objects.get_or_create(user=request.user, book=book)

    if chapter_order is None:
        if progress.current_chapter_id and progress.current_chapter.book_text_id == text.id:
            current = progress.current_chapter
        else:
            current = chapters[0]
    else:
        current = next((c for c in chapters if c.order == chapter_order), None)
        if current is None:
            raise Http404("Глава не найдена")

    # Соседние главы
    idx = chapters.index(current)
    prev_ch = chapters[idx - 1] if idx > 0 else None
    next_ch = chapters[idx + 1] if idx + 1 < len(chapters) else None

    # Обновим current_chapter в прогрессе (scroll_offset сбросим на 0, если сменилась)
    if progress.current_chapter_id != current.id:
        progress.current_chapter = current
        progress.scroll_offset = 0.0
        progress.save(update_fields=["current_chapter", "scroll_offset", "updated_at"])

    return render(request, "books/read.html", {
        "book":        book,
        "text":        text,
        "chapters":    chapters,
        "current":     current,
        "prev_ch":     prev_ch,
        "next_ch":     next_ch,
        "progress":    progress,
        "total_ch":    len(chapters),
        "current_idx": idx,
    })


@login_required
@require_POST
def book_read_progress(request, pk):
    """JSON-endpoint для сохранения скролла в пределах текущей главы.

    Принимает POST-параметры `chapter_order` и `offset` (0..1).
    """
    book = get_object_or_404(Book, pk=pk)
    if not _user_can_read(request, book):
        return JsonResponse({"ok": False, "error": "forbidden"}, status=403)

    text = getattr(book, "text", None)
    if text is None:
        return JsonResponse({"ok": False, "error": "no_text"}, status=400)

    try:
        chapter_order = int(request.POST.get("chapter_order", ""))
    except ValueError:
        return JsonResponse({"ok": False, "error": "bad_chapter"}, status=400)

    try:
        offset = float(request.POST.get("offset", "0"))
    except ValueError:
        offset = 0.0
    offset = max(0.0, min(1.0, offset))

    chapter = BookChapter.objects.filter(book_text=text, order=chapter_order).first()
    if chapter is None:
        return JsonResponse({"ok": False, "error": "chapter_not_found"}, status=404)

    progress, created = ReadingProgress.objects.get_or_create(user=request.user, book=book)
    progress.current_chapter = chapter
    progress.scroll_offset = offset
    update_fields = ["current_chapter", "scroll_offset", "updated_at"]
    # Если юзер ни разу не выставлял режим вручную (только что созданная запись
    # или всё ещё на manual, но теперь реально читает в читалке) — автоматически
    # переключаем на reader. Если юзер осознанно выбрал manual (уже поменял),
    # не перезаписываем — читалка всё равно сохранит главу/скролл для возврата.
    if created:
        progress.mode = ReadingProgress.MODE_READER
        update_fields.append("mode")
    progress.save(update_fields=update_fields)

    return JsonResponse({"ok": True, "percent": progress.percent(), "mode": progress.mode})


def _book_form_context():
    """Общий контекст для формы добавления/редактирования книги."""
    return {
        "all_genres": Genre.objects.order_by("name"),
        "all_authors": Author.objects.order_by("name"),
        "all_languages": Language.objects.order_by("name"),
        "all_publishers": Publisher.objects.order_by("name"),
        "all_series": Series.objects.order_by("name"),
    }

def _get_or_create_publisher(request):
    """Извлекает или создаёт издательство из POST-данных."""
    pub_id = request.POST.get("publisher_id", "").strip()
    pub_name = request.POST.get("publisher_name", "").strip()
    publisher = None
    if pub_id and pub_id.isdigit():
        publisher = Publisher.objects.filter(pk=pub_id).first()
    if not publisher and pub_name:
        publisher, _ = Publisher.objects.get_or_create(name=pub_name)
    return publisher

def _get_or_create_series(request):
    """Извлекает или создаёт серию из POST-данных."""
    ser_id = request.POST.get("series_id", "").strip()
    ser_name = request.POST.get("series_name", "").strip()
    series = None
    if ser_id and ser_id.isdigit():
        series = Series.objects.filter(pk=ser_id).first()
    if not series and ser_name:
        series, _ = Series.objects.get_or_create(name=ser_name)
    return series

# ─── INLINE-СОЗДАНИЕ ОБЪЕКТОВ (STAFF) ────────────────────────────────────────

@staff_required
def author_create_inline(request):
    return _inline_create(request, Author)

@staff_required
def genre_create_inline(request):
    return _inline_create(request, Genre)

@staff_required
def publisher_create_inline(request):
    return _inline_create(request, Publisher)

@staff_required
def series_create_inline(request):
    return _inline_create(request, Series)

# ─── ПРОГРЕСС ЧТЕНИЯ ─────────────────────────────────────────────────────────

@login_required
@require_POST
def reading_progress_save(request, pk):
    """Ручное обновление прогресса чтения.

    Принимает либо `current_page` (обычный ввод страницы в manual-режиме),
    либо одно только `mode` (переключение режима без смены числа страниц).
    """
    book = get_object_or_404(Book, pk=pk)

    mode_raw = (request.POST.get("mode") or "").strip()
    # Разрешены только известные режимы, иначе — игнорируем
    mode = mode_raw if mode_raw in {ReadingProgress.MODE_MANUAL, ReadingProgress.MODE_READER} else None

    page_raw = (request.POST.get("current_page") or "").strip()

    if page_raw:
        if not page_raw.isdigit():
            return HttpResponseBadRequest("Страница должна быть числом")
        page = min(int(page_raw), book.pages or 999999)
        # Ручной ввод страницы всегда означает manual-режим
        progress, _ = ReadingProgress.objects.update_or_create(
            user=request.user, book=book,
            defaults={"current_page": page, "mode": ReadingProgress.MODE_MANUAL},
        )
    elif mode is not None:
        # Только переключение режима — current_page не трогаем
        progress, _ = ReadingProgress.objects.update_or_create(
            user=request.user, book=book,
            defaults={"mode": mode},
        )
    else:
        return HttpResponseBadRequest("Нужно либо current_page, либо mode")

    return JsonResponse({
        "current_page": progress.current_page,
        "percent":      progress.percent(),
        "mode":         progress.mode,
    })

# ─── ЦИТАТЫ ───────────────────────────────────────────────────────────────────

@login_required
@require_POST
def quote_add(request, pk):
    book = get_object_or_404(Book, pk=pk)
    text = request.POST.get("text", "").strip()
    if not text:
        return HttpResponseBadRequest("Текст цитаты обязателен")
    # Мягкий лимит — чтобы кнопкой «в цитаты» нельзя было выдернуть всю главу
    if len(text) > 2000:
        return HttpResponseBadRequest("Слишком длинная цитата (максимум 2000 символов)")

    page_raw = request.POST.get("page_number", "").strip()
    page = int(page_raw) if page_raw.isdigit() else None

    # Опционально — привязка к главе (из fair-use highlight-а в читалке)
    chapter = None
    ch_raw = request.POST.get("chapter_order", "").strip()
    if ch_raw.isdigit() and hasattr(book, "text") and book.text:
        chapter = BookChapter.objects.filter(book_text=book.text, order=int(ch_raw)).first()

    quote = Quote.objects.create(
        user=request.user, book=book, text=text,
        page_number=page, chapter=chapter,
    )

    # AJAX/JSON вызов (из читалки) — возвращаем короткий JSON
    accept = request.headers.get("Accept", "")
    if "application/json" in accept or request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return JsonResponse({
            "ok": True,
            "id": quote.id,
            "text": quote.text[:120],
        })

    # Обычный HTMX-вызов из таба «Цитаты» — возвращаем HTML
    quotes = Quote.objects.filter(book=book).select_related("user")
    return render(request, "books/_quotes.html", {"book": book, "quotes": quotes})

@login_required
@require_POST
def quote_delete(request, pk, quote_pk):
    book = get_object_or_404(Book, pk=pk)
    quotes_qs = Quote.objects.filter(pk=quote_pk, book=book)
    if not request.user.is_staff:
        quotes_qs = quotes_qs.filter(user=request.user, is_ai_generated=False)
    get_object_or_404(quotes_qs).delete()
    quotes = Quote.objects.filter(book=book).select_related("user")
    return render(request, "books/_quotes.html", {"book": book, "quotes": quotes})

@require_GET
def quotes_partial(request, pk):
    book = get_object_or_404(Book, pk=pk)
    quotes = Quote.objects.filter(book=book).select_related("user")
    return render(request, "books/_quotes.html", {"book": book, "quotes": quotes})


# ─── ПРИВАТНЫЕ ЗАМЕТКИ (BookNote) ─────────────────────────────────────────────
# В отличие от Quote — заметка приватная (видит только автор), хранит и фрагмент,
# и комментарий пользователя «для себя». UI — расширение fair-use highlight bubble
# в читалке (книга/глава, фрагмент, опциональный комментарий).
@login_required
@require_POST
def note_add(request, pk):
    book = get_object_or_404(Book, pk=pk)
    excerpt = request.POST.get("excerpt", "").strip()
    note_text = request.POST.get("note", "").strip()
    if not excerpt:
        return HttpResponseBadRequest("Фрагмент обязателен")
    if len(excerpt) > 4000:
        return HttpResponseBadRequest("Слишком длинный фрагмент (максимум 4000 символов)")
    if len(note_text) > 4000:
        return HttpResponseBadRequest("Слишком длинная заметка (максимум 4000 символов)")

    chapter = None
    ch_raw = request.POST.get("chapter_order", "").strip()
    if ch_raw.isdigit() and hasattr(book, "text") and book.text:
        chapter = BookChapter.objects.filter(book_text=book.text, order=int(ch_raw)).first()

    try:
        note = BookNote.objects.create(
            user=request.user, book=book, chapter=chapter,
            excerpt=excerpt, note=note_text,
        )
    except Exception as exc:
        # Чаще всего сюда попадают, если в продовой БД не накатили миграцию
        # 0012_booknote — таблица books_booknote отсутствует. Логируем и отдаём
        # человекочитаемый JSON, чтобы фронт показал внятное сообщение.
        logger.exception("BookNote.create failed for user=%s book=%s: %s",
                         request.user.id, book.id, exc)
        return JsonResponse(
            {"ok": False, "error": "Не удалось сохранить заметку. Попробуйте позже."},
            status=500,
        )
    return JsonResponse({
        "ok": True,
        "id": note.id,
        "excerpt": note.excerpt[:120],
        "note": note.note[:120],
    })


@login_required
@require_GET
def note_list_for_book(request, pk):
    """
    JSON-список заметок текущего юзера к этой книге. Используется drawer-ом
    в читалке («Мои заметки»), чтобы можно было видеть всё сохранённое не
    выходя из главы. Сортировка — последние сверху.
    """
    book = get_object_or_404(Book, pk=pk)
    notes = (
        BookNote.objects.filter(user=request.user, book=book)
        .select_related("chapter")
        .order_by("-created_at")[:100]
    )
    return JsonResponse({
        "ok": True,
        "items": [
            {
                "id": n.id,
                "excerpt": n.excerpt,
                "note": n.note,
                "chapter_order": n.chapter.order if n.chapter else None,
                "chapter_title": n.chapter.title if n.chapter else "",
                "created_at": n.created_at.strftime("%d.%m.%Y %H:%M"),
            }
            for n in notes
        ],
    })


@login_required
@require_POST
def note_delete(request, note_id):
    """Удаление приватной заметки. Только автор может удалить."""
    note = get_object_or_404(BookNote, pk=note_id, user=request.user)
    note.delete()
    return JsonResponse({"ok": True, "id": note_id})


# ─── АЛЕРТ ЦЕНЫ ───────────────────────────────────────────────────────────────

@login_required
@require_POST
def price_alert_save(request, pk):
    book = get_object_or_404(Book, pk=pk)
    threshold = request.POST.get("threshold", "").strip().replace(",", ".")
    try:
        threshold = float(threshold)
    except ValueError:
        return HttpResponseBadRequest("Некорректное значение порога")
    PriceAlert.objects.update_or_create(
        user=request.user, book=book,
        defaults={"threshold": threshold, "triggered_at": None},
    )
    alert = PriceAlert.objects.get(user=request.user, book=book)
    return render(request, "books/_price_alert.html", {"book": book, "alert": alert})

@login_required
@require_POST
def price_alert_delete(request, pk):
    book = get_object_or_404(Book, pk=pk)
    PriceAlert.objects.filter(user=request.user, book=book).delete()
    return render(request, "books/_price_alert.html", {"book": book, "alert": None})

# ─── MOOD TAGS ───────────────────────────────────────────────────────────────

@login_required
@require_POST
def vote_mood(request, pk, mood_id):
    """Голосование за mood-тег книги. HTMX partial."""
    book = get_object_or_404(Book, pk=pk)
    mood_tag = get_object_or_404(MoodTag, pk=mood_id)
    bm, created = BookMood.objects.get_or_create(
        book=book, mood=mood_tag,
        defaults={"source": "user_vote", "confidence": 0.7, "vote_count": 1},
    )
    if not created:
        bm.vote_count += 1
        bm.save(update_fields=["vote_count"])
    moods = BookMood.objects.filter(book=book).select_related("mood").order_by("-confidence", "-vote_count")
    return render(request, "books/_mood_tags.html", {"book": book, "moods": moods})

# ─── СТРАНИЦА СЕРИИ ──────────────────────────────────────────────────────────

@require_GET
def series_detail(request, pk):
    """Страница серии книг с таймлайном."""
    series = get_object_or_404(Series, pk=pk)
    books = (
        series.books
        .prefetch_related("authors", "genres")
        .order_by(
            F("series_order").asc(nulls_last=True),
            "publication_year",
            "pk",
        )
    )

    year_range = books.aggregate(
        min_year=Min("publication_year"),
        max_year=Max("publication_year"),
        avg_rating=Avg("avg_rating"),
    )

    # Определяем основного автора серии (самый частый среди книг)
    from collections import Counter
    author_counter = Counter()
    for book in books:
        for a in book.authors.all():
            author_counter[a] += 1
    main_authors = [a for a, _ in author_counter.most_common(3)]

    total = books.count()

    # Прогресс и статус для авторизованного пользователя
    progress_map = {}
    in_list_set = set()
    user_read_count = 0
    if request.user.is_authenticated:
        progress_qs = ReadingProgress.objects.filter(
            user=request.user,
            book__in=books,
        ).select_related("book")
        for p in progress_qs:
            progress_map[p.book_id] = p

        user_lists = UserList.objects.filter(user=request.user).prefetch_related("books")
        for ul in user_lists:
            for b in ul.books.all():
                in_list_set.add(b.pk)

        for book in books:
            p = progress_map.get(book.pk)
            if p and book.pages and p.current_page >= book.pages:
                user_read_count += 1
            elif book.pk in in_list_set and not p:
                pass  # в списке, но не читает

    # Собираем данные по каждой книге
    books_data = []
    for i, book in enumerate(books, 1):
        p = progress_map.get(book.pk)
        if p and book.pages and p.current_page >= book.pages:
            status = "read"
            status_label = "Прочитано"
        elif p and p.current_page > 0:
            status = "reading"
            status_label = f"стр. {p.current_page}"
        else:
            status = "not_started"
            status_label = "Не начато"

        books_data.append({
            "book": book,
            "number": book.series_order or i,
            "status": status,
            "status_label": status_label,
            "progress": p,
            "percent": p.percent() if p else 0,
        })

    progress_percent = round(user_read_count / total * 100) if total else 0

    return render(request, "books/series_detail.html", {
        "series": series,
        "books_data": books_data,
        "main_authors": main_authors,
        "total": total,
        "user_read_count": user_read_count,
        "progress_percent": progress_percent,
        "min_year": year_range["min_year"],
        "max_year": year_range["max_year"],
        "avg_rating": year_range["avg_rating"],
    })


# ─── AI-ФИЧИ ПОЛНОГО ТЕКСТА (STAFF-ENDPOINTS) ────────────────────────────────

def _ensure_book_has_text(request, book) -> bool:
    """Проверяет, что у книги загружен текст. Иначе ставит error-сообщение и
    возвращает False."""
    text = getattr(book, "text", None)
    if text is None or not getattr(text, "is_ready", False):
        messages.error(
            request,
            "Для этой фичи нужен загруженный полный текст (EPUB/FB2).",
        )
        return False
    return True


@login_required
@require_GET
def book_chapter_search(request, pk):
    """Поиск по главам книги: FTS + опциональный LLM-rerank.

    GET params:
      q       — поисковый запрос (обязательно, >= 3 chars)
      rerank  — "1" чтобы включить LLM-rerank (тратит токены)

    Возвращает JSON: {"query": "...", "results": [{...}]}
    """
    book = get_object_or_404(Book, pk=pk)
    if not _user_can_read(request, book):
        return JsonResponse({"error": "forbidden"}, status=403)

    q = request.GET.get("q", "").strip()
    rerank = request.GET.get("rerank") == "1"
    if len(q) < 3:
        return JsonResponse({"query": q, "results": []})

    from .chapter_search import search_chapters
    results = search_chapters(book, q, limit=8, rerank=rerank)
    return JsonResponse({"query": q, "results": results, "rerank": rerank})


@staff_required
@require_POST
def book_ai_summaries(request, pk):
    """Запустить Celery-таск, который делает краткое содержание каждой главы."""
    book = get_object_or_404(Book, pk=pk)
    if not _ensure_book_has_text(request, book):
        return redirect("book_detail", pk=pk)

    from .ai_tasks import summarize_all_chapters
    summarize_all_chapters.delay(book.pk)

    n_chapters = book.text.chapters.count()
    messages.success(
        request,
        f"Запущено саммари для {n_chapters} глав книги «{book.title}». "
        f"Результат появится через 1–3 минуты.",
    )
    return redirect("book_detail", pk=pk)


@staff_required
@require_POST
def book_ai_quotes_extract(request, pk):
    """Извлечь 5–10 литературных цитат из реального текста (Quote, is_ai=True)."""
    book = get_object_or_404(Book, pk=pk)
    if not _ensure_book_has_text(request, book):
        return redirect("book_detail", pk=pk)

    from .ai_tasks import extract_book_quotes
    extract_book_quotes.delay(book.pk, replace_ai=True)

    messages.success(
        request,
        f"Извлечение AI-цитат из «{book.title}» запущено. "
        f"Старые AI-цитаты будут заменены.",
    )
    return redirect("book_detail", pk=pk)


@staff_required
@require_POST
def book_ai_themes(request, pk):
    """Извлечь темы и мотивы книги (Book.ai_themes)."""
    book = get_object_or_404(Book, pk=pk)
    if not _ensure_book_has_text(request, book):
        return redirect("book_detail", pk=pk)

    from .ai_tasks import extract_book_themes
    extract_book_themes.delay(book.pk)

    messages.success(
        request,
        f"Анализ тем и мотивов «{book.title}» запущен.",
    )
    return redirect("book_detail", pk=pk)


@staff_required
@require_POST
def book_ai_style(request, pk):
    """Построить профиль стиля книги по первым главам (Book.ai_style_profile)."""
    book = get_object_or_404(Book, pk=pk)
    if not _ensure_book_has_text(request, book):
        return redirect("book_detail", pk=pk)

    from .ai_tasks import build_style_profile
    build_style_profile.delay(book.pk)

    messages.success(
        request,
        f"Построение профиля стиля «{book.title}» запущено "
        f"(spoiler-safe, только первые главы).",
    )
    return redirect("book_detail", pk=pk)

from datetime import timedelta

from django.contrib.admin.views.decorators import staff_member_required
from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from books.models import Author, Book
from .auth import api_key_required
from .models import ApiKey, ApiRequestLog


def _absolute(request, path):
    return request.build_absolute_uri(path)


def _author_payload(request, author):
    return {
        "id": author.pk,
        "name": author.name,
        "birth_year": author.birth_year,
        "url": _absolute(request, reverse("author_detail", args=[author.pk])),
    }


def _book_payload(request, book, *, detail=False):
    data = {
        "id": book.pk,
        "title": book.title,
        "authors": [_author_payload(request, author) for author in book.authors.all()],
        "genres": [genre.name for genre in book.genres.all()],
        "publication_year": book.publication_year,
        "avg_rating": book.avg_rating,
        "rating_count": book.rating_count,
        "cover_url": _absolute(request, book.cover_image.url) if book.cover_image else "",
        "url": _absolute(request, reverse("book_detail", args=[book.pk])),
    }
    if detail:
        data.update({
            "isbn": book.isbn,
            "description": book.description,
            "pages": book.pages,
            "publisher": book.publisher.name if book.publisher else "",
            "language": book.language.name if book.language else "",
        })
    return data


def _paginate(request, qs, default_page_size=20, max_page_size=100):
    try:
        page_size = min(max(int(request.GET.get("page_size", default_page_size)), 1), max_page_size)
    except ValueError:
        page_size = default_page_size
    paginator = Paginator(qs, page_size)
    page_obj = paginator.get_page(request.GET.get("page") or 1)
    return paginator, page_obj


@require_GET
@api_key_required
def api_root(request):
    return JsonResponse({
        "name": "Stroka API",
        "version": "v1",
        "endpoints": {
            "docs": _absolute(request, reverse("api_docs")),
            "books": _absolute(request, reverse("api_books_list")),
            "authors": _absolute(request, reverse("api_authors_list")),
        },
    })


@require_GET
def docs(request):
    return JsonResponse({
        "name": "Stroka API",
        "version": "v1",
        "auth": {
            "headers": [
                "Authorization: Bearer sk_stroka_...",
                "X-API-Key: sk_stroka_...",
            ],
        },
        "pagination": {
            "params": {"page": "integer, default 1", "page_size": "integer, max 100"},
            "response": ["count", "page", "pages", "results"],
        },
        "endpoints": [
            {
                "method": "GET",
                "path": "/api/v1/books/",
                "description": "Поиск и список книг.",
                "query": {
                    "q": "поиск по названию или автору",
                    "ordering": "title, -title, avg_rating, -avg_rating, created_at, -created_at, publication_year, -publication_year",
                    "page": "номер страницы",
                    "page_size": "размер страницы",
                },
            },
            {
                "method": "GET",
                "path": "/api/v1/books/{id}/",
                "description": "Детальная карточка книги.",
            },
            {
                "method": "GET",
                "path": "/api/v1/authors/",
                "description": "Поиск и список авторов.",
                "query": {"q": "поиск по имени", "page": "номер страницы", "page_size": "размер страницы"},
            },
            {
                "method": "GET",
                "path": "/api/v1/authors/{id}/",
                "description": "Автор и его книги.",
            },
        ],
    }, json_dumps_params={"ensure_ascii": False, "indent": 2})


@require_GET
@api_key_required
def books_list(request):
    qs = (
        Book.objects
        .select_related("publisher", "language")
        .prefetch_related("authors", "genres")
        .all()
    )
    q = (request.GET.get("q") or "").strip()
    if q:
        qs = qs.filter(Q(title__icontains=q) | Q(authors__name__icontains=q)).distinct()
    ordering = request.GET.get("ordering") or "-avg_rating"
    allowed = {"title", "-title", "created_at", "-created_at", "avg_rating", "-avg_rating", "publication_year", "-publication_year"}
    if ordering not in allowed:
        ordering = "-avg_rating"
    qs = qs.order_by(ordering, "pk")
    paginator, page_obj = _paginate(request, qs)
    return JsonResponse({
        "count": paginator.count,
        "page": page_obj.number,
        "pages": paginator.num_pages,
        "results": [_book_payload(request, book) for book in page_obj.object_list],
    })


@require_GET
@api_key_required
def book_detail(request, pk):
    book = get_object_or_404(
        Book.objects.select_related("publisher", "language").prefetch_related("authors", "genres"),
        pk=pk,
    )
    return JsonResponse(_book_payload(request, book, detail=True))


@require_GET
@api_key_required
def authors_list(request):
    qs = Author.objects.all()
    q = (request.GET.get("q") or "").strip()
    if q:
        qs = qs.filter(name__icontains=q)
    qs = qs.order_by("name", "pk")
    paginator, page_obj = _paginate(request, qs)
    return JsonResponse({
        "count": paginator.count,
        "page": page_obj.number,
        "pages": paginator.num_pages,
        "results": [_author_payload(request, author) for author in page_obj.object_list],
    })


@require_GET
@api_key_required
def author_detail(request, pk):
    author = get_object_or_404(Author, pk=pk)
    data = _author_payload(request, author)
    data["bio"] = author.bio
    data["books"] = [
        _book_payload(request, book)
        for book in author.books.prefetch_related("authors", "genres").order_by("title")[:50]
    ]
    return JsonResponse(data)


@staff_member_required
def dashboard(request):
    now = timezone.now()
    day_ago = now - timedelta(days=1)
    week_ago = now - timedelta(days=7)
    logs = ApiRequestLog.objects.select_related("api_key", "api_key__owner")
    active_keys = ApiKey.objects.filter(is_active=True).count()
    week_logs = logs.filter(created_at__gte=week_ago)
    stats = {
        "keys": active_keys,
        "day_requests": logs.filter(created_at__gte=day_ago).count(),
        "week_requests": week_logs.count(),
        "week_errors": week_logs.filter(status_code__gte=400).count(),
    }
    keys = (
        ApiKey.objects
        .select_related("owner")
        .annotate(request_count=Count("request_logs"))
        .order_by("-created_at")
    )
    recent_logs = logs[:50]
    top_paths = (
        week_logs.values("path")
        .annotate(count=Count("id"))
        .order_by("-count")[:10]
    )
    return render(request, "public_api/dashboard.html", {
        "stats": stats,
        "keys": keys,
        "recent_logs": recent_logs,
        "top_paths": top_paths,
        "new_key": request.session.pop("new_api_key", ""),
    })


@staff_member_required
@require_POST
def create_key(request):
    name = (request.POST.get("name") or "").strip() or "Новый ключ"
    key, raw_key = ApiKey.create_key(owner=request.user, name=name)
    request.session["new_api_key"] = raw_key
    messages.success(request, f"API-ключ «{key.name}» создан. Скопируйте его сейчас.")
    return redirect("api_dashboard")


@staff_member_required
@require_POST
def revoke_key(request, key_id):
    key = get_object_or_404(ApiKey, pk=key_id)
    key.revoke()
    messages.success(request, f"API-ключ «{key.name}» отключён.")
    return redirect("api_dashboard")

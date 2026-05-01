from datetime import timedelta

from django.contrib.admin.views.decorators import staff_member_required
from django.contrib import messages
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST
from drf_spectacular.utils import extend_schema, OpenApiParameter
from rest_framework import viewsets, filters
from rest_framework.decorators import action
from rest_framework.response import Response

from books.models import Author, Book
from .auth import api_key_required
from .models import ApiKey, ApiRequestLog
from .serializers import (
    AuthorSerializer,
    AuthorDetailSerializer,
    BookSerializer,
    BookDetailSerializer,
)


# ============================================================================
# DRF ViewSets (REST API)
# ============================================================================


class BookViewSet(viewsets.ReadOnlyModelViewSet):
    """ViewSet for Book model with search and filtering."""

    queryset = Book.objects.select_related("publisher", "language").prefetch_related("authors", "genres")
    serializer_class = BookSerializer
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["title", "authors__name"]
    ordering_fields = ["title", "created_at", "avg_rating", "publication_year"]
    ordering = ["-avg_rating"]

    def get_serializer_class(self):
        """Return detailed serializer for retrieve action."""
        if self.action == "retrieve":
            return BookDetailSerializer
        return BookSerializer

    @extend_schema(
        operation_id="api_books_list",
        description="Поиск и список книг.",
        parameters=[
            OpenApiParameter(name="q", description="поиск по названию или автору", required=False),
            OpenApiParameter(name="ordering", description="title, -title, avg_rating, -avg_rating, created_at, -created_at, publication_year, -publication_year", required=False),
        ],
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @extend_schema(
        operation_id="api_book_detail",
        description="Детальная карточка книги.",
    )
    def retrieve(self, request, *args, **kwargs):
        return super().retrieve(request, *args, **kwargs)


class AuthorViewSet(viewsets.ReadOnlyModelViewSet):
    """ViewSet for Author model with search."""

    queryset = Author.objects.all()
    serializer_class = AuthorSerializer
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["name"]
    ordering_fields = ["name"]
    ordering = ["name"]

    def get_serializer_class(self):
        """Return detailed serializer for retrieve action."""
        if self.action == "retrieve":
            return AuthorDetailSerializer
        return AuthorSerializer

    @extend_schema(
        operation_id="api_authors_list",
        description="Поиск и список авторов.",
        parameters=[
            OpenApiParameter(name="q", description="поиск по имени", required=False),
        ],
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @extend_schema(
        operation_id="api_author_detail",
        description="Автор и его книги.",
    )
    def retrieve(self, request, *args, **kwargs):
        return super().retrieve(request, *args, **kwargs)


# ============================================================================
# Legacy views (for backward compatibility and dashboard)
# ============================================================================

def _absolute(request, path):
    return request.build_absolute_uri(path)


def _author_payload(request, author):
    return {
        "id": author.pk,
        "name": author.name,
        "birth_year": author.birth_year,
        "url": _absolute(request, reverse("book_detail", args=[author.pk])),
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

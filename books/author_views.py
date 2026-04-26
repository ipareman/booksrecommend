from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib import messages
from django.http import HttpResponse
from django.db.models import Q, Min, Max
from django.core.paginator import Paginator
from django.conf import settings

from .models import Book, Author, Genre
from users.models import AuthorSubscription
from users.models import AuthorSubscription


def author_detail(request, pk):
    author = get_object_or_404(Author, pk=pk)
    g = request.GET

    qs = (
        Book.objects
        .filter(authors=author)
        .prefetch_related("authors", "genres")
        .select_related("publisher", "language")
    )

    search = g.get("search", "").strip()
    if search:
        qs = qs.filter(
            Q(title__icontains=search) | Q(genres__name__icontains=search)
            | Q(description__icontains=search)
        ).distinct()

    genre_ids = g.getlist("genre")
    if genre_ids:
        for gid in genre_ids:
            qs = qs.filter(genres__id=gid)
        qs = qs.distinct()

    year_from = g.get("year_from", "").strip()
    year_to = g.get("year_to", "").strip()
    if year_from.isdigit(): qs = qs.filter(publication_year__gte=int(year_from))
    if year_to.isdigit():   qs = qs.filter(publication_year__lte=int(year_to))

    pages_from = g.get("pages_from", "").strip()
    pages_to = g.get("pages_to", "").strip()
    if pages_from.isdigit(): qs = qs.filter(pages__gte=int(pages_from))
    if pages_to.isdigit():   qs = qs.filter(pages__lte=int(pages_to))

    rating_min = g.get("rating_min", "").strip()
    if rating_min:
        try:
            qs = qs.filter(avg_rating__gte=float(rating_min))
        except ValueError:
            pass

    ordering = g.get("ordering", "-avg_rating")
    if ordering in {"-avg_rating", "-rating_count", "-publication_year",
                    "publication_year", "avg_price", "-avg_price"}:
        qs = qs.order_by(ordering)

    paginator = Paginator(qs, settings.BOOKS_PER_PAGE)
    page = paginator.get_page(g.get("page", 1))

    params = request.GET.copy()
    params.pop("page", None)

    agg = Book.objects.filter(authors=author).aggregate(
        min_year=Min("publication_year"), max_year=Max("publication_year"),
        min_pages=Min("pages"), max_pages=Max("pages"),
    )

    is_subscribed = False
    if request.user.is_authenticated:
        is_subscribed = AuthorSubscription.objects.filter(
            user=request.user, author=author
        ).exists()

    ctx = {
        "author": author,
        "books": page,
        "total": paginator.count,
        "query_string": params.urlencode(),
        "has_filters": bool(search or genre_ids or year_from or year_to
                            or pages_from or pages_to or rating_min),
        "all_genres": Genre.objects.filter(books__authors=author).distinct(),
        "selected_genres": genre_ids,
        "agg": agg,
        "f": g,
        "is_subscribed": is_subscribed,
    }
    if request.htmx:
        return render(request, "books/_book_list.html", ctx)
    return render(request, "books/author_detail.html", ctx)


@login_required
def toggle_author_subscription(request, pk):
    if request.method != "POST":
        return HttpResponse(status=405)
    author = get_object_or_404(Author, pk=pk)
    sub, created = AuthorSubscription.objects.get_or_create(
        user=request.user, author=author
    )
    if not created:
        sub.delete()
        is_subscribed = False
    else:
        is_subscribed = True
    return render(request, "books/_subscribe_btn.html", {
        "author": author, "is_subscribed": is_subscribed
    })


@user_passes_test(lambda u: u.is_staff)
def author_edit(request, pk):
    """POST — сохранить инлайн-редактирование автора."""
    author = get_object_or_404(Author, pk=pk)

    if request.method != "POST":
        return HttpResponse(status=405)

    name = request.POST.get("name", "").strip()
    if not name:
        messages.error(request, "Имя автора не может быть пустым.")
        return redirect("author_detail", pk=pk)

    bio_val = request.POST.get("bio", "").strip()
    birth_year_raw = request.POST.get("birth_year", "").strip()

    author.name = name
    author.bio = bio_val
    author.birth_year = int(birth_year_raw) if birth_year_raw.isdigit() else None
    author.save()

    messages.success(request, f"Автор «{author.name}» обновлён.")
    return redirect("author_detail", pk=pk)

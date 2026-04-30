from collections import defaultdict

from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib import messages
from django.http import HttpResponse
from django.db.models import Q, Min, Max
from django.core.paginator import Paginator
from django.conf import settings

from .models import Book, Author, Genre, Publisher, Series
from users.models import AuthorSubscription


def _build_bibliography(author: Author) -> list:
    """Возвращает список {'year': int|None, 'books': [...]} отсортированный по году убыв."""
    all_books = (
        Book.objects
        .filter(authors=author)
        .prefetch_related("authors", "genres")
        .select_related("publisher", "series")
        .order_by("-publication_year", "title")
    )
    groups: dict = defaultdict(list)
    for book in all_books:
        groups[book.publication_year].append(book)

    result = []
    for year in sorted(groups.keys(), key=lambda y: (y is None, -(y or 0))):
        result.append({"year": year, "books": groups[year]})
    return result


def _build_by_series(author: Author) -> tuple:
    """Возвращает (series_groups, no_series_books).
    series_groups = list of {'series': Series, 'books': [...]}
    no_series_books = list of Book без серии
    """
    all_books = (
        Book.objects
        .filter(authors=author)
        .prefetch_related("authors", "genres")
        .select_related("series")
        .order_by("series__name", "series_order", "publication_year", "title")
    )
    series_map: dict = defaultdict(list)
    no_series: list = []
    series_objs: dict = {}
    for book in all_books:
        if book.series_id:
            series_map[book.series_id].append(book)
            series_objs[book.series_id] = book.series
        else:
            no_series.append(book)

    series_groups = [
        {"series": series_objs[sid], "books": books}
        for sid, books in series_map.items()
    ]
    series_groups.sort(key=lambda g: g["series"].name)
    return series_groups, no_series


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

    bibliography = _build_bibliography(author)
    series_groups, no_series_books = _build_by_series(author)

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
        "bibliography": bibliography,
        "series_groups": series_groups,
        "no_series_books": no_series_books,
        "has_series": bool(series_groups),
    }
    if request.htmx:
        return render(request, "books/_book_list.html", ctx)
    return render(request, "books/author_detail.html", ctx)


def publisher_detail(request, pk):
    publisher = get_object_or_404(Publisher, pk=pk)
    g = request.GET

    qs = (
        Book.objects
        .filter(publisher=publisher)
        .prefetch_related("authors", "genres")
        .select_related("publisher", "language")
    )

    search = g.get("search", "").strip()
    if search:
        qs = qs.filter(
            Q(title__icontains=search)
            | Q(authors__name__icontains=search)
            | Q(genres__name__icontains=search)
            | Q(description__icontains=search)
            | Q(isbn__icontains=search)
        ).distinct()

    genre_ids = g.getlist("genre")
    if genre_ids:
        for gid in genre_ids:
            qs = qs.filter(genres__id=gid)
        qs = qs.distinct()

    year_from = g.get("year_from", "").strip()
    year_to = g.get("year_to", "").strip()
    if year_from.isdigit():
        qs = qs.filter(publication_year__gte=int(year_from))
    if year_to.isdigit():
        qs = qs.filter(publication_year__lte=int(year_to))

    pages_from = g.get("pages_from", "").strip()
    pages_to = g.get("pages_to", "").strip()
    if pages_from.isdigit():
        qs = qs.filter(pages__gte=int(pages_from))
    if pages_to.isdigit():
        qs = qs.filter(pages__lte=int(pages_to))

    rating_min = g.get("rating_min", "").strip()
    if rating_min:
        try:
            qs = qs.filter(avg_rating__gte=float(rating_min))
        except ValueError:
            pass

    ordering = g.get("ordering", "-avg_rating")
    if ordering in {"-avg_rating", "-rating_count", "-publication_year",
                    "publication_year", "avg_price", "-avg_price", "title"}:
        qs = qs.order_by(ordering)

    paginator = Paginator(qs, settings.BOOKS_PER_PAGE)
    page = paginator.get_page(g.get("page", 1))

    params = request.GET.copy()
    params.pop("page", None)

    base_qs = Book.objects.filter(publisher=publisher)
    agg = base_qs.aggregate(
        min_year=Min("publication_year"), max_year=Max("publication_year"),
        min_pages=Min("pages"), max_pages=Max("pages"),
    )

    ctx = {
        "publisher": publisher,
        "books": page,
        "total": paginator.count,
        "query_string": params.urlencode(),
        "has_filters": bool(search or genre_ids or year_from or year_to
                            or pages_from or pages_to or rating_min),
        "all_genres": Genre.objects.filter(books__publisher=publisher).distinct(),
        "selected_genres": genre_ids,
        "agg": agg,
        "f": g,
    }
    if request.htmx:
        return render(request, "books/_book_list.html", ctx)
    return render(request, "books/publisher_detail.html", ctx)


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


@user_passes_test(lambda u: u.is_staff)
def publisher_edit(request, pk):
    publisher = get_object_or_404(Publisher, pk=pk)

    if request.method != "POST":
        return HttpResponse(status=405)

    name = request.POST.get("name", "").strip()
    if not name:
        messages.error(request, "Название издательства не может быть пустым.")
        return redirect("publisher_detail", pk=pk)

    if Publisher.objects.filter(name__iexact=name).exclude(pk=pk).exists():
        messages.error(request, f"Издательство «{name}» уже существует.")
        return redirect("publisher_detail", pk=pk)

    founded_year_raw = request.POST.get("founded_year", "").strip()
    website = request.POST.get("website", "").strip()
    if website and not website.startswith(("http://", "https://")):
        website = "https://" + website

    publisher.name = name
    publisher.description = request.POST.get("description", "").strip()
    publisher.founded_year = int(founded_year_raw) if founded_year_raw.isdigit() else None
    publisher.country = request.POST.get("country", "").strip()
    publisher.city = request.POST.get("city", "").strip()
    publisher.website = website
    publisher.save()

    messages.success(request, f"Издательство «{publisher.name}» обновлено.")
    return redirect("publisher_detail", pk=pk)

from django.shortcuts import render, redirect, get_object_or_404
from django.http import HttpResponse, JsonResponse
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST, require_GET
from django.core.exceptions import PermissionDenied
from django.db.models import Q, Count
from django.template.loader import render_to_string

from .models import Collection, CollectionBook, CollectionLike
from books.models import Book, UserList


def _owner_or_staff(view_func):
    """Доступ только у создателя подборки или у staff."""
    def wrapper(request, *args, **kwargs):
        pk = kwargs.get("pk")
        col = get_object_or_404(Collection, pk=pk)
        if col.created_by_id != request.user.id and not request.user.is_staff:
            raise PermissionDenied
        return view_func(request, *args, **kwargs)
    wrapper.__name__ = view_func.__name__
    return wrapper


# ─── ПУБЛИЧНЫЕ ─────────────────────────────────────────────────────────────────

def collections_list(request):
    collections = (
        Collection.objects
        .filter(is_published=True)
        .prefetch_related("items__book")
        .annotate(num_books=Count("items"), num_likes=Count("likes", distinct=True))
    )
    liked_ids = set()
    if request.user.is_authenticated:
        liked_ids = set(
            CollectionLike.objects
            .filter(user=request.user, collection__in=collections)
            .values_list("collection_id", flat=True)
        )
    return render(request, "curated/collection_list.html", {
        "collections": collections,
        "liked_ids": liked_ids,
    })


def collection_detail(request, pk):
    col = get_object_or_404(Collection, pk=pk)
    if not col.is_published:
        if not request.user.is_authenticated or (
            col.created_by_id != request.user.id and not request.user.is_staff
        ):
            from django.http import Http404
            raise Http404
    items = (
        col.items
        .select_related("book")
        .prefetch_related("book__authors", "book__genres")
        .order_by("order")
    )
    likes_count = col.likes.count()
    is_liked = (
        request.user.is_authenticated
        and col.likes.filter(user=request.user).exists()
    )
    return render(request, "curated/collection_detail.html", {
        "collection": col,
        "items": items,
        "likes_count": likes_count,
        "is_liked": is_liked,
    })


@login_required
@require_POST
def collection_like_toggle(request, pk):
    """Поставить / снять лайк подборке. Возвращает партиал кнопки для htmx."""
    col = get_object_or_404(Collection, pk=pk)
    like, created = CollectionLike.objects.get_or_create(
        collection=col, user=request.user,
    )
    if not created:
        like.delete()
    likes_count = col.likes.count()
    is_liked = created
    return render(request, "curated/_like_button.html", {
        "collection": col,
        "likes_count": likes_count,
        "is_liked": is_liked,
    })


# ─── СОЗДАНИЕ / РЕДАКТИРОВАНИЕ ─────────────────────────────────────────────────

@login_required
def collection_create(request):
    from_list_id = request.GET.get("from_list") or request.POST.get("from_list")
    source_list = None
    if from_list_id:
        source_list = UserList.objects.filter(
            pk=from_list_id, user=request.user
        ).prefetch_related("books").first()

    if request.method == "POST":
        title = request.POST.get("title", "").strip()
        description = request.POST.get("description", "").strip()
        if title:
            col = Collection.objects.create(
                title=title,
                description=description,
                created_by=request.user,
                cover_image=request.FILES.get("cover_image"),
            )
            if source_list:
                for order, book in enumerate(source_list.books.all()):
                    CollectionBook.objects.create(
                        collection=col, book=book, order=order
                    )
            return redirect("collection_edit", pk=col.pk)

    default_title = ""
    if source_list:
        default_title = f'Подборка из списка «{source_list.name}»'
    return render(request, "curated/collection_create.html", {
        "source_list": source_list,
        "default_title": default_title,
    })


@login_required
@_owner_or_staff
def collection_edit(request, pk):
    col = get_object_or_404(Collection, pk=pk)
    selected = (
        col.items
        .select_related("book")
        .prefetch_related("book__authors")
        .order_by("order")
    )
    return render(request, "curated/collection_editor.html", {
        "collection": col,
        "selected_items": selected,
    })


@login_required
@_owner_or_staff
@require_POST
def collection_delete(request, pk):
    col = get_object_or_404(Collection, pk=pk)
    col.delete()
    return redirect("collections_list")


@login_required
@_owner_or_staff
@require_POST
def collection_toggle_publish(request, pk):
    col = get_object_or_404(Collection, pk=pk)
    col.is_published = not col.is_published
    col.save(update_fields=["is_published"])
    return render(request, "curated/_editor_header.html", {"collection": col})


@login_required
@_owner_or_staff
@require_POST
def collection_add_book(request, pk):
    col = get_object_or_404(Collection, pk=pk)
    book_id = request.POST.get("book_id")
    book = get_object_or_404(Book, pk=book_id)
    max_order = col.items.count()
    CollectionBook.objects.get_or_create(
        collection=col, book=book,
        defaults={"order": max_order},
    )
    selected = col.items.select_related("book").prefetch_related("book__authors").order_by("order")
    ctx = {"collection": col, "selected_items": selected}

    html = render_to_string("curated/_selected_books.html", ctx, request=request)
    # OOB: убрать книгу из поиска + обновить мобильную панель
    oob_delete = f'<div id="book-option-{book.pk}" hx-swap-oob="delete"></div>'
    oob_mobile = (
        f'<div id="selected-books-mobile" hx-swap-oob="innerHTML">'
        + render_to_string("curated/_selected_books.html", ctx, request=request)
        + '</div>'
    )
    return HttpResponse(html + oob_delete + oob_mobile)


@login_required
@_owner_or_staff
@require_POST
def collection_remove_book(request, pk, book_id):
    col = get_object_or_404(Collection, pk=pk)
    CollectionBook.objects.filter(collection=col, book_id=book_id).delete()
    selected = (
        col.items
        .select_related("book")
        .prefetch_related("book__authors")
        .order_by("order")
    )
    ctx = {"collection": col, "selected_items": selected}
    html = render_to_string("curated/_selected_books.html", ctx, request=request)
    # OOB: обновить мобильную панель
    oob_mobile = (
        f'<div id="selected-books-mobile" hx-swap-oob="innerHTML">'
        + render_to_string("curated/_selected_books.html", ctx, request=request)
        + '</div>'
    )
    resp = HttpResponse(html + oob_mobile)
    # Триггер перезагрузки результатов поиска
    resp["HX-Trigger"] = "refreshSearch"
    return resp


@login_required
@_owner_or_staff
@require_GET
def collection_search_books(request, pk):
    col = get_object_or_404(Collection, pk=pk)
    q = request.GET.get("q", "").strip()
    existing_ids = set(col.items.values_list("book_id", flat=True))

    if q:
        books = (
            Book.objects
            .filter(Q(title__icontains=q) | Q(authors__name__icontains=q))
            .exclude(pk__in=existing_ids)
            .prefetch_related("authors")
            .distinct()[:20]
        )
    else:
        books = (
            Book.objects
            .exclude(pk__in=existing_ids)
            .prefetch_related("authors")
            .order_by("-avg_rating")[:20]
        )

    return render(request, "curated/_search_results.html", {
        "books": books,
        "collection": col,
    })

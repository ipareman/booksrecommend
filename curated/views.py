from django.shortcuts import render, redirect, get_object_or_404
from django.http import Http404, HttpResponse, JsonResponse
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST, require_GET
from django.core.exceptions import PermissionDenied
from django.db.models import Q, Count, Prefetch, Sum, Value
from django.db.models.functions import Coalesce
from django.template.loader import render_to_string

from .models import Collection, CollectionBook, CollectionComment, CollectionCommentVote, CollectionLike
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
    sort = request.GET.get("sort", "fresh").strip()
    q = request.GET.get("q", "").strip()

    collections = (
        Collection.objects
        .filter(is_published=True)
        .prefetch_related("items__book", "items__book__genres")
        .annotate(num_books=Count("items", distinct=True), num_likes=Count("likes", distinct=True))
    )
    if q:
        collections = collections.filter(
            Q(title__icontains=q)
            | Q(description__icontains=q)
            | Q(created_by__username__icontains=q)
            | Q(items__book__title__icontains=q)
        )

    collections = collections.distinct()
    if sort == "likes":
        collections = collections.order_by("-num_likes", "-created_at")
    elif sort == "old":
        collections = collections.order_by("created_at")
    else:
        sort = "fresh"
        collections = collections.order_by("-created_at")

    liked_ids = set()
    if request.user.is_authenticated:
        liked_ids = set(
            CollectionLike.objects
            .filter(user=request.user, collection__in=collections)
            .values_list("collection_id", flat=True)
        )
    context = {
        "collections": collections,
        "liked_ids": liked_ids,
        "sort": sort,
        "q": q,
    }
    if getattr(request, "htmx", False):
        return render(request, "curated/_collection_grid.html", context)
    return render(request, "curated/collection_list.html", context)


def collection_detail(request, pk):
    col = get_object_or_404(Collection, pk=pk)
    if not col.is_published:
        if not request.user.is_authenticated or (
            col.created_by_id != request.user.id and not request.user.is_staff
        ):
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
    comments = (
        col.comments
        .filter(parent__isnull=True)
        .select_related("user", "user__profile")
        .prefetch_related(Prefetch(
            "replies",
            queryset=CollectionComment.objects
            .select_related("user", "user__profile")
            .annotate(vote_score=Coalesce(Sum("votes__value"), Value(0)))
            .order_by("created_at"),
        ))
        .annotate(vote_score=Coalesce(Sum("votes__value"), Value(0)))
        .order_by("created_at")
    )
    user_votes = {}
    if request.user.is_authenticated:
        comment_ids = list(comments.values_list("pk", flat=True))
        reply_ids = list(
            CollectionComment.objects
            .filter(parent_id__in=comment_ids)
            .values_list("pk", flat=True)
        )
        all_ids = comment_ids + reply_ids
        user_votes = dict(
            CollectionCommentVote.objects
            .filter(user=request.user, comment_id__in=all_ids)
            .values_list("comment_id", "value")
        )
    return render(request, "curated/collection_detail.html", {
        "collection": col,
        "items": items,
        "likes_count": likes_count,
        "is_liked": is_liked,
        "comments": comments,
        "user_votes": user_votes,
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


@login_required
@require_POST
def collection_clone(request, pk):
    source = get_object_or_404(
        Collection.objects.prefetch_related("items__book"),
        pk=pk,
        is_published=True,
    )
    if source.created_by_id == request.user.id:
        return redirect("collection_edit", pk=source.pk)

    title = f"Копия: {source.title}"[:200]
    clone = Collection.objects.create(
        title=title,
        description=source.description,
        cover_image=source.cover_image,
        created_by=request.user,
        is_published=False,
    )
    CollectionBook.objects.bulk_create([
        CollectionBook(collection=clone, book=item.book, order=item.order)
        for item in source.items.all()
    ])
    return redirect("collection_edit", pk=clone.pk)


@login_required
@require_POST
def collection_comment_add(request, pk):
    col = get_object_or_404(Collection, pk=pk, is_published=True)
    text = request.POST.get("text", "").strip()
    if not text:
        return HttpResponse(status=400)
    parent = None
    parent_id = request.POST.get("parent_id")
    if parent_id:
        parent = CollectionComment.objects.filter(pk=parent_id, collection=col).first()

    comment = CollectionComment.objects.create(
        collection=col,
        user=request.user,
        parent=parent,
        text=text,
    )
    html = render_to_string("curated/_comment.html", {
        "comment": comment,
        "collection": col,
        "user_votes": {},
    }, request=request)
    return HttpResponse(html + '<div id="collection-comments-empty" hx-swap-oob="delete"></div>')


@login_required
@require_POST
def collection_comment_edit(request, pk):
    comment = get_object_or_404(CollectionComment, pk=pk)
    if comment.user_id != request.user.id:
        raise PermissionDenied
    text = request.POST.get("text", "").strip()
    if not text:
        return HttpResponse(status=400)
    comment.text = text
    comment.save(update_fields=["text", "updated_at"])
    return render(request, "curated/_comment.html", {
        "comment": comment,
        "collection": comment.collection,
        "user_votes": {},
    })


@login_required
@require_POST
def collection_comment_delete(request, pk):
    comment = get_object_or_404(CollectionComment, pk=pk)
    if comment.user_id != request.user.id and not request.user.is_staff:
        raise PermissionDenied
    comment.delete()
    return HttpResponse("")


@login_required
@require_POST
def collection_comment_vote(request, pk):
    comment = get_object_or_404(CollectionComment, pk=pk)
    value_raw = request.POST.get("value", "")
    try:
        value = int(value_raw)
        if value not in (1, -1):
            return HttpResponse(status=400)
    except (TypeError, ValueError):
        return HttpResponse(status=400)

    existing = CollectionCommentVote.objects.filter(user=request.user, comment=comment).first()
    if existing:
        if existing.value == value:
            existing.delete()
            user_vote = 0
        else:
            existing.value = value
            existing.save(update_fields=["value"])
            user_vote = value
    else:
        CollectionCommentVote.objects.create(user=request.user, comment=comment, value=value)
        user_vote = value

    score = CollectionCommentVote.objects.filter(comment=comment).aggregate(
        s=Coalesce(Sum("value"), Value(0))
    )["s"]
    return render(request, "curated/_comment_votes.html", {
        "comment": comment,
        "score": score,
        "user_vote": user_vote,
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
    if request.method == "POST":
        title = request.POST.get("title", col.title).strip()
        description = request.POST.get("description", "").strip()
        if title:
            col.title = title
        col.description = description
        col.save()
        if request.headers.get("HX-Request"):
            return render(request, "curated/_editor_header.html", {"collection": col})
        return redirect("collection_edit", pk=col.pk)

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

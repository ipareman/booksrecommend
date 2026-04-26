from django.db.models import Q, Count
from django.shortcuts import render, get_object_or_404
from django.http import JsonResponse
from django.views.decorators.http import require_POST, require_GET
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied

from books.models import Book
from .models import BookRelation
from .builder import build_graph_data, generate_auto_relations


def book_graph(request, pk):
    book = get_object_or_404(Book.objects.prefetch_related("authors", "genres"), pk=pk)
    return render(request, "graph/book_graph.html", {"book": book})



@require_GET
def book_graph_data(request, pk):
    book = get_object_or_404(Book.objects.prefetch_related("authors"), pk=pk)
    data = build_graph_data(book, depth=2, max_nodes=40)
    return JsonResponse(data)


@login_required
@require_POST
def admin_add_relation(request):
    if not request.user.is_staff:
        raise PermissionDenied
    book_from_id = request.POST.get("book_from_id")
    book_to_id = request.POST.get("book_to_id")
    relation_type = request.POST.get("relation_type")

    book_from = get_object_or_404(Book, pk=book_from_id)
    book_to = get_object_or_404(Book, pk=book_to_id)

    BookRelation.objects.get_or_create(
        book_from=book_from,
        book_to=book_to,
        relation_type=relation_type,
        defaults={"is_auto": False, "weight": 1.5},
    )
    return render(request, "graph/_relations_list.html", {
        "book": book_from,
        "relations": BookRelation.objects.filter(book_from=book_from).select_related("book_to"),
    })


@login_required
def graph_admin(request):
    if not request.user.is_staff:
        raise PermissionDenied

    q = request.GET.get("q", "").strip()
    selected_id = request.GET.get("book_id")
    selected_book = None
    relations = []
    search_books = []

    if selected_id:
        selected_book = Book.objects.filter(pk=selected_id).prefetch_related("authors").first()
        if selected_book:
            relations = (
                BookRelation.objects
                .filter(Q(book_from=selected_book) | Q(book_to=selected_book))
                .select_related("book_from", "book_to")
                .order_by("-weight")
            )

    if q:
        search_books = (
            Book.objects
            .filter(Q(title__icontains=q) | Q(authors__name__icontains=q))
            .prefetch_related("authors")
            .distinct()[:20]
        )

    return render(request, "graph/admin.html", {
        "selected_book": selected_book,
        "book": selected_book,
        "relations": relations,
        "search_books": search_books,
        "q": q,
        "relation_types": BookRelation.RELATION_TYPES,
    })


@login_required
@require_POST
def graph_admin_add_relation(request):
    if not request.user.is_staff:
        raise PermissionDenied

    book_from_id = request.POST.get("book_from_id")
    book_to_id = request.POST.get("book_to_id")
    relation_type = request.POST.get("relation_type")

    book_from = get_object_or_404(Book, pk=book_from_id)
    book_to = get_object_or_404(Book, pk=book_to_id)

    BookRelation.objects.get_or_create(
        book_from=book_from, book_to=book_to, relation_type=relation_type,
        defaults={"is_auto": False, "weight": 1.5},
    )
    relations = (
        BookRelation.objects
        .filter(Q(book_from=book_from) | Q(book_to=book_from))
        .select_related("book_from", "book_to")
        .order_by("-weight")
    )
    return render(request, "graph/_relations_list.html", {
        "book": book_from, "relations": relations,
        "relation_types": BookRelation.RELATION_TYPES,
    })


@login_required
@require_POST
def graph_generate_auto(request):
    """Запустить автогенерацию для всех книг."""
    if not request.user.is_staff:
        raise PermissionDenied
    count = 0
    for book in Book.objects.prefetch_related("authors", "genres"):
        try:
            generate_auto_relations(book)
            count += 1
        except Exception:
            pass
    from django.contrib import messages
    messages.success(request, f"Автосвязи обновлены для {count} книг")
    from django.shortcuts import redirect
    return redirect("graph_admin")


@login_required
@require_GET
def graph_search_books(request):
    """JSON-like partial for book-to search dropdown in graph admin."""
    if not request.user.is_staff:
        raise PermissionDenied
    q = request.GET.get("q", "").strip()
    if len(q) >= 2:
        books = (
            Book.objects
            .filter(Q(title__icontains=q) | Q(authors__name__icontains=q))
            .prefetch_related("authors")
            .distinct()[:15]
        )
    else:
        # Книги с наибольшим количеством связей
        books = (
            Book.objects
            .annotate(rel_count=Count("relations_from") + Count("relations_to"))
            .prefetch_related("authors")
            .order_by("-rel_count")[:15]
        )
    return render(request, "graph/_book_search_dropdown.html", {"books": books, "q": q})


@login_required
@require_POST
def admin_remove_relation(request, relation_id):
    if not request.user.is_staff:
        raise PermissionDenied
    rel = get_object_or_404(BookRelation, pk=relation_id)
    book = rel.book_from
    rel.delete()
    relations = (
        BookRelation.objects
        .filter(Q(book_from=book) | Q(book_to=book))
        .select_related("book_from", "book_to")
        .order_by("-weight")
    )
    return render(request, "graph/_relations_list.html", {
        "book": book,
        "relations": relations,
    })

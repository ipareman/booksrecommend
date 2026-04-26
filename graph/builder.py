from django.db import models
from django.db.models import Q, Count
from .models import BookRelation


RELATION_COLORS = {
    "same_author": "#6366f1",
    "same_genre": "#10b981",
    "same_series": "#f59e0b",
    "also_read": "#8b5cf6",
    "influenced_by": "#ef4444",
    "response_to": "#ec4899",
    "similar_theme": "#06b6d4",
    "sequel": "#f97316",
    "prequel": "#84cc16",
}

RELATION_LABELS = dict(BookRelation.RELATION_TYPES)


def build_graph_data(book, depth=2, max_nodes=40):
    """Строит JSON для D3.js force-directed graph."""
    visited = {book.pk}
    nodes = [_book_node(book, is_center=True)]
    links = []

    current_layer = [book.pk]
    for _ in range(depth):
        if len(nodes) >= max_nodes:
            break
        next_layer = []
        relations = BookRelation.objects.filter(
            Q(book_from_id__in=current_layer) | Q(book_to_id__in=current_layer)
        ).select_related("book_from", "book_to").prefetch_related("book_from__authors", "book_to__authors")

        # prefetch авторов
        relations = list(relations)

        for rel in relations:
            neighbor = rel.book_to if rel.book_from_id in current_layer else rel.book_from
            source_id = rel.book_from_id
            target_id = rel.book_to_id

            if neighbor.pk not in visited:
                visited.add(neighbor.pk)
                nodes.append(_book_node(neighbor, is_center=False))
                next_layer.append(neighbor.pk)

            link_key = (source_id, target_id, rel.relation_type)
            links.append({
                "source": source_id,
                "target": target_id,
                "type": rel.relation_type,
                "label": RELATION_LABELS.get(rel.relation_type, rel.relation_type),
                "color": RELATION_COLORS.get(rel.relation_type, "#999"),
                "weight": rel.weight,
            })

            if len(nodes) >= max_nodes:
                break

        current_layer = next_layer

    return {"nodes": nodes, "links": links}


def _book_node(book, is_center=False):
    cover = book.cover_image.url if book.cover_image else None
    authors = ", ".join(a.name for a in book.authors.all())
    desc = book.description or ""
    if len(desc) > 200:
        desc = desc[:197] + "..."
    return {
        "id": book.pk,
        "title": book.title,
        "cover": cover,
        "authors": authors,
        "rating": float(book.avg_rating) if book.avg_rating else None,
        "description": desc,
        "is_center": is_center,
    }


def generate_auto_relations(book):
    """Генерирует автоматические связи для книги."""
    from books.models import Book

    book_author_ids = set(book.authors.values_list("pk", flat=True))
    book_genre_ids = set(book.genres.values_list("pk", flat=True))

    # same_author
    if book_author_ids:
        related = (
            Book.objects
            .filter(authors__pk__in=book_author_ids)
            .exclude(pk=book.pk)
            .distinct()
        )
        for other in related:
            common = len(book_author_ids & set(other.authors.values_list("pk", flat=True)))
            BookRelation.objects.update_or_create(
                book_from=book, book_to=other, relation_type="same_author",
                defaults={"weight": float(common), "is_auto": True},
            )

    # same_genre (>= 2 общих жанра)
    if len(book_genre_ids) >= 2:
        related = (
            Book.objects
            .filter(genres__pk__in=book_genre_ids)
            .exclude(pk=book.pk)
            .annotate(common_count=Count("genres", filter=Q(genres__pk__in=book_genre_ids)))
            .filter(common_count__gte=2)
        )
        for other in related:
            weight = other.common_count / max(len(book_genre_ids), 1)
            BookRelation.objects.update_or_create(
                book_from=book, book_to=other, relation_type="same_genre",
                defaults={"weight": weight, "is_auto": True},
            )

    # same_series
    if book.series_id:
        related = Book.objects.filter(series=book.series).exclude(pk=book.pk)
        for other in related:
            BookRelation.objects.update_or_create(
                book_from=book, book_to=other, relation_type="same_series",
                defaults={"weight": 2.0, "is_auto": True},
            )

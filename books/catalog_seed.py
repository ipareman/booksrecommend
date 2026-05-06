from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass, field

from django.db import transaction

from .models import Author, Book, Genre, Language, Publisher, Series


@dataclass
class CatalogSeedStats:
    seen: int = 0
    created: int = 0
    updated: int = 0
    skipped: int = 0
    authors_created: int = 0
    genres_created: int = 0
    languages_created: int = 0
    publishers_created: int = 0
    series_created: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def parse_catalog_seed_jsonl(content: str) -> list[dict]:
    rows: list[dict] = []
    for line_no, raw_line in enumerate(content.splitlines(), 1):
        line = raw_line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"line {line_no}: invalid JSON ({exc.msg})") from exc
        if not isinstance(row, dict):
            raise ValueError(f"line {line_no}: JSON object expected")
        row["_line_no"] = line_no
        rows.append(row)
    return rows


def import_catalog_seed_jsonl(content: str, *, dry_run: bool = False) -> CatalogSeedStats:
    rows = parse_catalog_seed_jsonl(content)
    stats = CatalogSeedStats(seen=len(rows))

    with transaction.atomic():
        for row in rows:
            _import_row(row, stats, dry_run=dry_run)
        if dry_run:
            transaction.set_rollback(True)

    return stats


def _import_row(row: dict, stats: CatalogSeedStats, *, dry_run: bool) -> None:
    line_no = row.get("_line_no", "?")
    title = _clean(row.get("title"))
    authors = _clean_list(row.get("authors"))
    genres = _clean_list(row.get("genres"))
    source_urls = _clean_list(row.get("source_urls"))

    if not title:
        stats.skipped += 1
        stats.errors.append(f"line {line_no}: title is required")
        return
    if not authors:
        stats.skipped += 1
        stats.errors.append(f"line {line_no}: at least one author is required")
        return
    if not source_urls:
        stats.skipped += 1
        stats.errors.append(f"line {line_no}: source_urls is required")
        return

    isbn = _clean(row.get("isbn_13")) or None
    publication_year = _int_or_none(row.get("publication_year"))
    pages = _int_or_none(row.get("pages"))
    description = _clean(row.get("description"))
    first_author = authors[0]

    book = _find_existing_book(title=title, first_author=first_author, isbn=isbn)
    publisher = _get_optional_name(Publisher, row.get("publisher"), stats, "publishers_created")
    series = _get_optional_name(Series, row.get("series"), stats, "series_created")
    language = _get_optional_name(Language, row.get("language"), stats, "languages_created")

    if book is None:
        if dry_run:
            for name in authors:
                _get_required_name(Author, name, stats, "authors_created")
            for name in genres:
                _get_required_name(Genre, name, stats, "genres_created")
            stats.created += 1
            return
        book = Book(
            title=title,
            isbn=isbn,
            description=description,
            publication_year=publication_year,
            pages=pages,
            publisher=publisher,
            series=series,
            series_order=_int_or_none(row.get("series_order")),
            language=language,
        )
        Book.objects.bulk_create([book])
        if book.pk is None:
            book = Book.objects.filter(title__iexact=title).order_by("-pk").first()
        stats.created += 1
    else:
        stats.updated += 1
        if not dry_run:
            updates = {
                "description": description or book.description,
                "publication_year": publication_year if publication_year is not None else book.publication_year,
                "pages": pages if pages is not None else book.pages,
                "publisher": publisher or book.publisher,
                "series": series or book.series,
                "series_order": _int_or_none(row.get("series_order")) or book.series_order,
                "language": language or book.language,
            }
            if isbn and not book.isbn:
                updates["isbn"] = isbn
            Book.objects.filter(pk=book.pk).update(**updates)
            for attr, value in updates.items():
                setattr(book, attr, value)

    if dry_run:
        return

    if book is None:
        stats.skipped += 1
        stats.errors.append(f"line {line_no}: book was not saved")
        return

    author_objs = [_get_required_name(Author, name, stats, "authors_created") for name in authors]
    genre_objs = [_get_required_name(Genre, name, stats, "genres_created") for name in genres]
    book.authors.set(author_objs)
    book.genres.set(genre_objs)


def _find_existing_book(*, title: str, first_author: str, isbn: str | None) -> Book | None:
    if isbn:
        book = Book.objects.filter(isbn=isbn).first()
        if book:
            return book
    return (
        Book.objects
        .filter(title__iexact=title, authors__name__iexact=first_author)
        .distinct()
        .first()
    )


def _get_required_name(model, name: str, stats: CatalogSeedStats, counter_name: str):
    obj, created = model.objects.get_or_create(name=name)
    if created:
        setattr(stats, counter_name, getattr(stats, counter_name) + 1)
    return obj


def _get_optional_name(model, raw, stats: CatalogSeedStats, counter_name: str):
    name = _clean(raw)
    if not name:
        return None
    return _get_required_name(model, name, stats, counter_name)


def _clean(value) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _clean_list(value) -> list[str]:
    if not isinstance(value, Iterable) or isinstance(value, (str, bytes)):
        return []
    result: list[str] = []
    seen: set[str] = set()
    for item in value:
        cleaned = _clean(item)
        key = cleaned.casefold()
        if cleaned and key not in seen:
            result.append(cleaned)
            seen.add(key)
    return result


def _int_or_none(value) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None

"""
Импорт библиотеки из Goodreads CSV.
Матчит книги по ISBN / title+author, создаёт списки и отзывы.
"""

import csv
import io
import logging
import re

from django.contrib.postgres.search import TrigramWordSimilarity
from django.db.models import Q

from .models import Book, Author, Genre, UserList, Publisher
from .isbn_lookup import lookup_by_isbn, _clean_isbn
from reviews.models import Review

logger = logging.getLogger(__name__)

# Маппинг Goodreads shelf → sentiment_tag
SHELF_SENTIMENT = {
    "read": "positive",
    "currently-reading": "neutral",
    "to-read": "wishlist",
}

# Маппинг Goodreads shelf → русское название списка
SHELF_NAMES = {
    "read": "Прочитано (Goodreads)",
    "currently-reading": "Читаю (Goodreads)",
    "to-read": "Хочу прочитать (Goodreads)",
}


def parse_goodreads_csv(file_content: str) -> list[dict]:
    """
    Парсит CSV-контент из Goodreads export.
    Возвращает список dict'ов с ключами:
      title, author, isbn13, isbn, my_rating, exclusive_shelf,
      bookshelves, pages, year, publisher, my_review
    """
    reader = csv.DictReader(io.StringIO(file_content))
    rows = []
    for row in reader:
        isbn13 = _clean_isbn(row.get("ISBN13", ""))
        isbn = _clean_isbn(row.get("ISBN", ""))
        rows.append({
            "title": (row.get("Title") or "").strip(),
            "author": (row.get("Author") or "").strip(),
            "additional_authors": (row.get("Additional Authors") or "").strip(),
            "isbn13": isbn13 if len(isbn13) == 13 else "",
            "isbn": isbn if len(isbn) in (10, 13) else "",
            "my_rating": int(row.get("My Rating") or 0),
            "exclusive_shelf": (row.get("Exclusive Shelf") or "read").strip(),
            "bookshelves": (row.get("Bookshelves") or "").strip(),
            "pages": int(row["Number of Pages"]) if (row.get("Number of Pages") or "").isdigit() else None,
            "year": int(row["Year Published"]) if (row.get("Year Published") or "").isdigit() else None,
            "publisher": (row.get("Publisher") or "").strip(),
            "my_review": (row.get("My Review") or "").strip(),
        })
    return rows


def _match_book(row: dict) -> Book | None:
    """
    Ищет книгу в БД:
    1. По ISBN13 (точное)
    2. По ISBN (точное)
    3. По title + author (trigram similarity)
    """
    isbn13 = row.get("isbn13")
    isbn = row.get("isbn")

    if isbn13:
        book = Book.objects.filter(isbn=isbn13).first()
        if book:
            return book
    if isbn:
        book = Book.objects.filter(isbn=isbn).first()
        if book:
            return book

    # Fuzzy match по названию
    title = row.get("title", "")
    author = row.get("author", "")
    if not title:
        return None

    qs = Book.objects.annotate(
        sim=TrigramWordSimilarity(title, "title")
    ).filter(sim__gte=0.5).order_by("-sim")

    # Фильтруем по автору если указан
    if author:
        qs = qs.filter(
            Q(authors__name__icontains=author.split(",")[0].strip())
        )

    return qs.first()


def _create_book_from_row(row: dict) -> Book | None:
    """Создаёт книгу из данных строки CSV. Пробует ISBN lookup если есть ISBN."""
    isbn = row.get("isbn13") or row.get("isbn")

    # Попробуем через API
    if isbn:
        api_data = lookup_by_isbn(isbn)
        if api_data and api_data.get("title"):
            publisher = None
            if api_data.get("publisher"):
                publisher, _ = Publisher.objects.get_or_create(name=api_data["publisher"])

            book = Book.objects.create(
                title=api_data["title"],
                isbn=isbn,
                description=api_data.get("description", ""),
                publication_year=api_data.get("publication_year"),
                pages=api_data.get("pages"),
                publisher=publisher,
            )
            # Авторы
            for aname in api_data.get("authors", []):
                author, _ = Author.objects.get_or_create(name=aname)
                book.authors.add(author)
            # Жанры
            for gname in api_data.get("genres", []):
                genre, _ = Genre.objects.get_or_create(name=gname)
                book.genres.add(genre)
            return book

    # Минимальное создание из CSV данных
    if not row.get("title"):
        return None

    book = Book.objects.create(
        title=row["title"],
        isbn=isbn or None,
        pages=row.get("pages"),
        publication_year=row.get("year"),
    )
    if row.get("author"):
        author, _ = Author.objects.get_or_create(name=row["author"])
        book.authors.add(author)
    if row.get("publisher"):
        pub, _ = Publisher.objects.get_or_create(name=row["publisher"])
        book.publisher = pub
        book.save(update_fields=["publisher"])

    return book


def import_library(user, file_content: str, create_missing: bool = True) -> dict:
    """
    Основная функция импорта.
    Возвращает: {imported, skipped, created, reviews_created, errors}
    """
    rows = parse_goodreads_csv(file_content)

    stats = {"imported": 0, "skipped": 0, "created": 0, "reviews_created": 0, "errors": []}
    shelf_lists = {}  # shelf_name -> UserList

    for row in rows:
        try:
            book = _match_book(row)
            if not book and create_missing:
                book = _create_book_from_row(row)
                if book:
                    stats["created"] += 1

            if not book:
                stats["skipped"] += 1
                continue

            # Определяем shelf
            shelf = row.get("exclusive_shelf", "read")
            if shelf not in shelf_lists:
                list_name = SHELF_NAMES.get(shelf, f"{shelf} (Goodreads)")
                sentiment = SHELF_SENTIMENT.get(shelf, "neutral")
                user_list, _ = UserList.objects.get_or_create(
                    user=user, name=list_name,
                    defaults={"sentiment_tag": sentiment},
                )
                shelf_lists[shelf] = user_list

            user_list = shelf_lists[shelf]
            if not user_list.books.filter(pk=book.pk).exists():
                user_list.books.add(book)

            # Создаём отзыв если есть рейтинг и отзыва ещё нет
            if row.get("my_rating", 0) > 0:
                if not Review.objects.filter(user=user, book=book).exists():
                    Review.objects.create(
                        user=user,
                        book=book,
                        rating=row["my_rating"],
                        text=row.get("my_review", ""),
                        status=Review.APPROVED,
                    )
                    stats["reviews_created"] += 1

            stats["imported"] += 1

        except Exception as exc:
            logger.warning("Import error for row %s: %s", row.get("title", "?"), exc)
            stats["errors"].append(f"{row.get('title', '?')}: {exc}")
            stats["skipped"] += 1

    return stats

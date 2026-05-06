import json

import pytest

from books.catalog_seed import import_catalog_seed_jsonl
from books.models import Author, Book, Genre, Language


def _jsonl(*rows):
    return "\n".join(json.dumps(row, ensure_ascii=False) for row in rows)


@pytest.mark.django_db
def test_import_catalog_seed_creates_book_reference_data():
    stats = import_catalog_seed_jsonl(_jsonl({
        "title": "Мастер и Маргарита",
        "authors": ["Михаил Булгаков"],
        "genres": ["классика", "магический реализм"],
        "language": "ru",
        "publication_year": 1967,
        "description": "Роман о Москве, свободе и выборе.",
        "source_urls": ["https://www.wikidata.org/wiki/Q?"],
    }))

    book = Book.objects.get(title="Мастер и Маргарита")
    assert stats.created == 1
    assert book.publication_year == 1967
    assert book.language.name == "ru"
    assert list(book.authors.values_list("name", flat=True)) == ["Михаил Булгаков"]
    assert set(book.genres.values_list("name", flat=True)) == {"классика", "магический реализм"}


@pytest.mark.django_db
def test_import_catalog_seed_updates_existing_by_title_and_author():
    author = Author.objects.create(name="Михаил Булгаков")
    book = Book.objects.create(title="Мастер и Маргарита")
    book.authors.add(author)

    stats = import_catalog_seed_jsonl(_jsonl({
        "title": "Мастер и Маргарита",
        "authors": ["Михаил Булгаков"],
        "genres": ["классика"],
        "language": "ru",
        "publication_year": 1967,
        "pages": 480,
        "source_urls": ["https://www.wikidata.org/wiki/Q?"],
    }))

    book.refresh_from_db()
    assert stats.created == 0
    assert stats.updated == 1
    assert Book.objects.count() == 1
    assert book.pages == 480
    assert Genre.objects.filter(name="классика").exists()


@pytest.mark.django_db
def test_import_catalog_seed_dry_run_rolls_back():
    stats = import_catalog_seed_jsonl(_jsonl({
        "title": "Проверочная книга",
        "authors": ["Автор"],
        "genres": ["жанр"],
        "language": "ru",
        "source_urls": ["https://www.wikidata.org/wiki/Q?"],
    }), dry_run=True)

    assert stats.created == 1
    assert Book.objects.count() == 0
    assert Author.objects.count() == 0
    assert Genre.objects.count() == 0
    assert Language.objects.count() == 0

"""
ISBN Lookup — автозаполнение метаданных книги по ISBN через Google Books API / Open Library API.
"""

import logging
import re

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

GOOGLE_BOOKS_URL = "https://www.googleapis.com/books/v1/volumes"
OPEN_LIBRARY_ISBN_URL = "https://openlibrary.org/isbn/{isbn}.json"
OPEN_LIBRARY_AUTHOR_URL = "https://openlibrary.org{key}.json"
OPEN_LIBRARY_COVER_URL = "https://covers.openlibrary.org/b/id/{cover_id}-L.jpg"

TIMEOUT = 10


def _clean_isbn(isbn: str) -> str:
    """Убирает дефисы, пробелы, кавычки из ISBN."""
    return re.sub(r"[^0-9Xx]", "", isbn.strip())


def _extract_year(date_str: str | None) -> int | None:
    """Извлекает год из строки вида '2024', '2024-03-15', 'March 15, 2024'."""
    if not date_str:
        return None
    m = re.search(r"\b(1[89]\d{2}|20\d{2})\b", date_str)
    return int(m.group(1)) if m else None


def _google_books_lookup(isbn: str) -> dict | None:
    """Поиск по Google Books API."""
    params = {"q": f"isbn:{isbn}"}
    api_key = getattr(settings, "GOOGLE_BOOKS_API_KEY", "")
    if api_key:
        params["key"] = api_key

    try:
        resp = requests.get(GOOGLE_BOOKS_URL, params=params, timeout=TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, ValueError) as exc:
        logger.warning("Google Books API error for ISBN %s: %s", isbn, exc)
        return None

    items = data.get("items")
    if not items:
        return None

    info = items[0].get("volumeInfo", {})

    # Обложка — берём самую крупную
    image_links = info.get("imageLinks", {})
    cover_url = (
        image_links.get("extraLarge")
        or image_links.get("large")
        or image_links.get("medium")
        or image_links.get("thumbnail")
    )
    # Убираем edge=curl если есть, и ставим zoom=1 для качества
    if cover_url:
        cover_url = cover_url.replace("&edge=curl", "").replace("zoom=1", "zoom=2")

    return {
        "title": info.get("title", ""),
        "authors": info.get("authors", []),
        "description": info.get("description", ""),
        "publication_year": _extract_year(info.get("publishedDate")),
        "pages": info.get("pageCount"),
        "publisher": info.get("publisher"),
        "language": info.get("language"),
        "cover_url": cover_url,
        "genres": info.get("categories", []),
        "isbn": isbn,
        "source": "google_books",
    }


def _open_library_lookup(isbn: str) -> dict | None:
    """Поиск по Open Library API."""
    try:
        resp = requests.get(
            OPEN_LIBRARY_ISBN_URL.format(isbn=isbn), timeout=TIMEOUT
        )
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, ValueError) as exc:
        logger.warning("Open Library API error for ISBN %s: %s", isbn, exc)
        return None

    # Авторы — нужен дополнительный запрос
    authors = []
    for author_ref in data.get("authors", []):
        author_key = author_ref.get("key")
        if not author_key:
            continue
        try:
            aresp = requests.get(
                OPEN_LIBRARY_AUTHOR_URL.format(key=author_key), timeout=TIMEOUT
            )
            aresp.raise_for_status()
            aname = aresp.json().get("name")
            if aname:
                authors.append(aname)
        except (requests.RequestException, ValueError):
            pass

    # Обложка
    cover_url = None
    covers = data.get("covers", [])
    if covers:
        cover_url = OPEN_LIBRARY_COVER_URL.format(cover_id=covers[0])

    # Описание
    description = ""
    desc_field = data.get("description")
    if isinstance(desc_field, str):
        description = desc_field
    elif isinstance(desc_field, dict):
        description = desc_field.get("value", "")

    return {
        "title": data.get("title", ""),
        "authors": authors,
        "description": description,
        "publication_year": _extract_year(data.get("publish_date")),
        "pages": data.get("number_of_pages"),
        "publisher": (data.get("publishers") or [None])[0],
        "language": None,
        "cover_url": cover_url,
        "genres": data.get("subjects", [])[:5] if data.get("subjects") else [],
        "isbn": isbn,
        "source": "open_library",
    }


def lookup_by_isbn(isbn: str) -> dict | None:
    """
    Ищет книгу по ISBN. Пробует Google Books, затем Open Library.
    Возвращает унифицированный dict с метаданными или None.
    """
    isbn = _clean_isbn(isbn)
    if not isbn:
        return None

    result = _google_books_lookup(isbn)
    if result and result.get("title"):
        return result

    result = _open_library_lookup(isbn)
    if result and result.get("title"):
        return result

    return None

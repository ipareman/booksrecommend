import re
from dataclasses import dataclass
from functools import lru_cache

from django.urls import reverse
from django.utils.html import conditional_escape
from django.utils.safestring import mark_safe


@dataclass(frozen=True)
class EntityLink:
    label: str
    url: str


def _author_aliases(name):
    parts = [p.strip(".,:;!?()[]{}\"'«»") for p in name.split()]
    aliases = {name.strip()}
    if parts:
        surname = parts[-1]
        if len(surname) >= 4:
            aliases.add(surname)
    return aliases


@lru_cache(maxsize=1)
def _entity_links():
    from books.models import Author, Book

    aliases = {}

    for author in Author.objects.only("id", "name").iterator():
        for alias in _author_aliases(author.name):
            if len(alias) >= 4:
                aliases.setdefault(
                    alias.casefold(),
                    EntityLink(alias, reverse("author_detail", args=[author.pk])),
                )

    for book in Book.objects.only("id", "title").iterator():
        title = book.title.strip()
        if len(title) >= 3:
            aliases.setdefault(
                title.casefold(),
                EntityLink(title, reverse("book_detail", args=[book.pk])),
            )

    return tuple(sorted(aliases.values(), key=lambda item: len(item.label), reverse=True))


def clear_entity_link_cache():
    _entity_links.cache_clear()


def linkify_message_text(text):
    if not text:
        return ""

    entities = _entity_links()
    if not entities:
        return conditional_escape(text)

    pattern = re.compile(
        r"(?<![\w])(" + "|".join(re.escape(entity.label) for entity in entities) + r")(?![\w])",
        re.IGNORECASE,
    )
    by_label = {entity.label.casefold(): entity for entity in entities}

    out = []
    last = 0
    for match in pattern.finditer(text):
        entity = by_label.get(match.group(1).casefold())
        if not entity:
            continue
        out.append(conditional_escape(text[last:match.start()]))
        label = conditional_escape(match.group(1))
        url = conditional_escape(entity.url)
        out.append(f'<a href="{url}" class="msg-entity-link">{label}</a>')
        last = match.end()

    out.append(conditional_escape(text[last:]))
    return mark_safe("".join(str(part) for part in out))

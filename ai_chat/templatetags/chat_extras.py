"""Шаблон-фильтры для AI-чата по книге."""

from __future__ import annotations

import html
import re

from django import template
from django.urls import reverse
from django.utils.safestring import mark_safe

register = template.Library()

# Ищем маркер "[Глава N]" или "[Глава N.]" или "[Глава N-M]"
_CHAPTER_MARKER = re.compile(r"\[\s*Глав[ауеы]?\s+(\d+)\s*\]", re.IGNORECASE)


@register.filter(name="link_chapters")
def link_chapters(value, book):
    """Превращает упоминания [Глава N] в тексте в кликабельные ссылки
    на соответствующую главу читалки.

    Использование:
        {{ msg.content|link_chapters:book }}
    """
    if not value or not book:
        return value

    text = html.escape(str(value))

    def repl(m):
        try:
            ch_num = int(m.group(1))
        except (ValueError, TypeError):
            return m.group(0)
        if ch_num < 1:
            return m.group(0)
        try:
            url = reverse("book_read_chapter", args=[book.id, ch_num - 1])
        except Exception:
            return m.group(0)
        return (
            f'<a href="{url}" class="ai-chat-chapter-ref" '
            f'title="Перейти к главе {ch_num}">[Глава {ch_num}]</a>'
        )

    return mark_safe(_CHAPTER_MARKER.sub(repl, text))

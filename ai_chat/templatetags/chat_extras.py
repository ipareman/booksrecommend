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
_BOLD_MARKER = re.compile(r"\*\*(?=\S)(.+?)(?<=\S)\*\*", re.DOTALL)


def _apply_basic_markdown(text: str) -> str:
    """Разрешает минимальную markdown-разметку поверх уже экранированного текста."""
    return _BOLD_MARKER.sub(r"<strong>\1</strong>", text)


@register.filter(name="link_chapters")
def link_chapters(value, book):
    """Превращает упоминания [Глава N] в тексте в кликабельные ссылки
    на соответствующую главу читалки.

    Использование:
        {{ msg.content|link_chapters:book }}
    """
    if not value or not book:
        return value

    text = _apply_basic_markdown(html.escape(str(value)))

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


@register.filter(name="ai_markdown")
def ai_markdown(value):
    """Безопасно рендерит минимальную markdown-разметку AI-ответов.

    Сейчас поддерживается только `**жирный текст**`; остальной HTML
    экранируется, переносы строк сохраняются.
    """
    if not value:
        return ""

    text = _apply_basic_markdown(html.escape(str(value)))
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "<br>")
    return mark_safe(text)

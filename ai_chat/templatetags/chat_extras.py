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
_BOOK_LINK_MARKER = re.compile(r"\[\s*book:(\d+)\|([^\]]+)\s*\]", re.IGNORECASE)


def _apply_basic_markdown(text: str) -> str:
    """Разрешает минимальную markdown-разметку поверх уже экранированного текста."""
    return _BOLD_MARKER.sub(r"<strong>\1</strong>", text)


@register.filter(name="link_chapters")
def link_chapters(value, book):
    """Превращает упоминания [Глава N] в тексте в кликабельные ссылки
    на соответствующую главу читалки, а также ссылки [book:ID|Название]
    в кликабельные ссылки на карточки книги.

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

    def repl_book(m):
        try:
            b_id = int(m.group(1))
            b_title = m.group(2).strip()
            url = reverse("book_detail", args=[b_id])
            return f'<a href="{url}" class="lnk" style="font-weight:600;">{b_title}</a>'
        except Exception:
            return m.group(0)

    # Заменяем главы, затем книги
    text_processed = _CHAPTER_MARKER.sub(repl, text)
    text_processed = _BOOK_LINK_MARKER.sub(repl_book, text_processed)

    return mark_safe(text_processed)


@register.filter(name="ai_markdown")
def ai_markdown(value):
    """Безопасно рендерит минимальную markdown-разметку AI-ответов.
    Также превращает ссылки [book:ID|Название] в кликабельные ссылки,
    и пытается найти в базе книги, упомянутые в кавычках «Название»
    или "Название", делая их кликабельными.
    """
    if not value:
        return ""

    text = html.escape(str(value))
    text = _apply_basic_markdown(text)

    # 1. Обрабатываем ссылки формата [book:ID|Название]
    def repl_book(m):
        try:
            b_id = int(m.group(1))
            b_title = m.group(2).strip()
            url = reverse("book_detail", args=[b_id])
            return f'<a href="{url}" class="lnk" style="font-weight:600;">{b_title}</a>'
        except Exception:
            return m.group(0)

    text = _BOOK_LINK_MARKER.sub(repl_book, text)

    # 2. Находим упоминания книг в кавычках «...», “...” или "..."
    QUOTED_RE = re.compile(r'(?:«([^»]+)»|“([^”]+)”|(?:\b|\s)"([^"]+)"(?:\b|\s))')

    try:
        from books.models import Book
        from django.core.cache import cache

        def repl_quoted(m):
            title = m.group(1) or m.group(2) or m.group(3)
            if not title:
                return m.group(0)
            
            title_stripped = title.strip()
            cache_key = f"book_title_id_{title_stripped.lower()}"
            book_id = cache.get(cache_key)
            
            if book_id is None:
                book = Book.objects.filter(title__iexact=title_stripped).first()
                if not book:
                    # Попробуем убрать знак вопроса или точку на конце
                    clean_title = title_stripped.rstrip("?.! ")
                    if clean_title != title_stripped:
                        book = Book.objects.filter(title__iexact=clean_title).first()
                
                if book:
                    book_id = book.id
                    cache.set(cache_key, book_id, 3600)
                else:
                    cache.set(cache_key, -1, 3600)
            
            if book_id and book_id != -1:
                try:
                    url = reverse("book_detail", args=[book_id])
                    quote_start = "«" if m.group(1) else ("“" if m.group(2) else '"')
                    quote_end = "»" if m.group(1) else ("”" if m.group(2) else '"')
                    # Возвращаем красивую ссылку, сохраняя кавычки
                    return f'<a href="{url}" class="lnk" style="font-weight:600;">{quote_start}{title}{quote_end}</a>'
                except Exception:
                    pass
            return m.group(0)

        text = QUOTED_RE.sub(repl_quoted, text)
    except Exception:
        pass

    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "<br>")
    return mark_safe(text)

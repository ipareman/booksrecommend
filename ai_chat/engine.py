import re

from core.llm import chat_completion
from reviews.models import Review
from books.models import BookTag


# Эвристика «метаданные похожи на заглушку» — нужна, чтобы LLM не принимал
# случайные значения title/description как истину в последней инстанции, если
# у книги при этом загружен полный текст.
_PLACEHOLDER_RE = re.compile(r"^[a-zа-я]{1,3}(\s*\(.*?\))*$", re.IGNORECASE)


def _looks_placeholder(s: str | None) -> bool:
    if not s:
        return True
    s = s.strip()
    if not s:
        return True
    # Отрезаем скобочные суффиксы «(копия)», «(copy)» — они не несут сигнала.
    stripped = re.sub(r"\s*\(.*?\)\s*", "", s).strip()
    if len(stripped) < 4:
        return True
    if _PLACEHOLDER_RE.match(stripped):
        return True
    # Повтор короткого паттерна: «asdasd», «qweqwe», «aaaaa».
    low = stripped.lower()
    for cycle_len in (1, 2, 3):
        if len(low) >= cycle_len * 2:
            chunk = low[:cycle_len]
            if low.startswith(chunk * 2):
                return True
    # Набор без гласных — похоже на случайное нажатие клавиш.
    letters = re.sub(r"[^a-zа-я]", "", low)
    if letters and len(letters) >= 4:
        vowels = sum(1 for c in letters if c in "аеёиоуыэюяaeiouy")
        if vowels / len(letters) < 0.1:
            return True
    return False


def build_book_context(book):
    """Собирает контекст книги для AI. Если есть полный текст, он становится
    основным источником истины — метаданные подаются «возможно-заглушкой»."""
    parts = []

    text = getattr(book, "text", None)
    has_text = bool(text and getattr(text, "is_ready", False))

    # ── Метаданные ─────────────────────────────────────────────────────────
    authors = ", ".join(a.name for a in book.authors.all())
    genres = ", ".join(g.name for g in book.genres.all())
    description = (book.description or "").strip()

    # Маркируем метаданные как возможно-заглушку, если у книги есть реальный
    # текст и при этом description пустой либо title выглядит мусором.
    metadata_is_suspect = has_text and (
        not description or _looks_placeholder(book.title) or _looks_placeholder(authors)
    )

    meta_header = (
        "Метаданные книги (заполнены пользователем, МОГУТ БЫТЬ ЗАГЛУШКОЙ — "
        "если они противоречат содержимому текста ниже, доверяй тексту):"
        if metadata_is_suspect
        else "Метаданные книги:"
    )
    parts.append(meta_header)
    parts.append(f"Название: {book.title}")
    if authors:
        parts.append(f"Авторы: {authors}")
    if genres:
        parts.append(f"Жанры: {genres}")
    if book.publication_year:
        parts.append(f"Год: {book.publication_year}")
    if book.series:
        parts.append(f"Серия: {book.series.name}")
    if book.pages:
        parts.append(f"Страниц: {book.pages}")

    if description:
        parts.append(f"\nОписание:\n{description}")

    # Контент от администратора
    try:
        content = book.ai_content
        if content.content_text:
            parts.append(f"\nДополнительная информация:\n{content.content_text}")
    except Exception:
        pass

    # Теги
    tags = BookTag.objects.filter(book=book).order_by("-count")[:10]
    if tags:
        parts.append(f"\nТеги: {', '.join(t.name for t in tags)}")

    # AI-темы/мотивы (из анализа полного текста)
    ai_themes = getattr(book, "ai_themes", None) or []
    if ai_themes:
        names = [t.get("name") for t in ai_themes if t.get("name")]
        if names:
            parts.append(f"\nТемы и мотивы (по анализу текста): {', '.join(names)}")

    # ── Реальное содержимое: первые абзацы + структура глав ────────────────
    # Это якорь для модели — по ним видно, что за книга на самом деле.
    if has_text:
        chapters = list(text.chapters.order_by("order"))
        if chapters:
            opening = (chapters[0].text or "").strip()
            if opening:
                # Первые ~700 символов первой главы — хватает, чтобы узнать книгу
                excerpt = opening[:700]
                parts.append(
                    "\nПЕРВЫЕ АБЗАЦЫ КНИГИ (реальный текст — основной источник истины):\n"
                    + excerpt
                    + ("…" if len(opening) > 700 else "")
                )

            parts.append("\nСтруктура книги (главы):")
            for ch in chapters[:80]:
                title = ch.title or f"Глава {ch.order + 1}"
                line = f"- [Глава {ch.order + 1}] {title}"
                if getattr(ch, "summary", ""):
                    line += f" — {ch.summary}"
                parts.append(line)

    # Отзывы
    reviews = Review.objects.filter(book=book, status=Review.APPROVED).order_by("-created_at")[:10]
    if reviews:
        parts.append("\nОтзывы читателей:")
        for r in reviews:
            text_preview = r.text[:300] + "..." if len(r.text) > 300 else r.text
            parts.append(f"- ★{r.rating}: {text_preview}")

    return "\n".join(parts)


def find_relevant_chapters(book, query: str, limit: int = 3) -> list[dict]:
    """Для RAG: ищет главы, релевантные вопросу пользователя.

    Возвращает список {chapter_order, title, snippet_text} с plain-text
    сниппетами (без <mark> — это для LLM).
    """
    text = getattr(book, "text", None)
    if text is None:
        return []
    try:
        from books.chapter_search import search_chapters
        results = search_chapters(book, query, limit=limit, rerank=False)
    except Exception:
        return []
    out = []
    for r in results:
        snippet = (r.get("snippet") or "").replace("<mark>", "").replace("</mark>", "")
        out.append({
            "chapter_order": r["chapter_order"],
            "title":   r["title"],
            "snippet_text": snippet,
        })
    return out


def ask_about_book(chat, user_message):
    """Отправляет вопрос AI и возвращает ответ."""
    from .models import BookChatMessage

    book_context = build_book_context(chat.book)

    # RAG: если есть полный текст, ищем 3 самые релевантные главы
    relevant = find_relevant_chapters(chat.book, user_message, limit=3)
    rag_block = ""
    if relevant:
        lines = []
        for r in relevant:
            lines.append(
                f"[Глава {r['chapter_order'] + 1}. {r['title']}]\n{r['snippet_text']}"
            )
        rag_block = (
            "\n\nРелевантные отрывки из книги (используй их как источник "
            "и ссылайся на главы в формате [Глава N]):\n\n"
            + "\n\n".join(lines)
        )

    # История (последние 20 сообщений)
    history = list(
        chat.messages.order_by("-created_at")[:20]
    )
    history.reverse()

    messages = [
        {
            "role": "system",
            "content": (
                f'Ты — AI-рецензент и собеседник по книге. '
                f'ВСЕГДА отвечай ТОЛЬКО на русском языке. '
                f'НЕ показывай свои размышления, давай сразу готовый ответ. '
                f'Пиши кратко и по делу (2–5 предложений), если не просят подробностей. '
                f'Обсуждай сюжет, персонажей, темы, стиль автора и контекст. '
                f'Если ниже есть релевантные отрывки — ссылайся на главы '
                f'в формате [Глава N] (например, «разбирается в [Глава 7]»).\n'
                f'ВАЖНО: приоритет источников — (1) релевантные отрывки и первые абзацы '
                f'текста, (2) отзывы читателей, (3) метаданные (название/описание). '
                f'Если метаданные выглядят как заглушка или противоречат содержимому '
                f'текста — ПОЛНОСТЬЮ ИГНОРИРУЙ их и опирайся на текст; при необходимости '
                f'начни ответ с уточнения («судя по тексту, это…»). '
                f'Не называй книгу «бессмысленной», «хаотичной» и т.п. только на основании '
                f'странного названия — смотри в реальный текст. '
                f'Не выдумывай события, которых нет в тексте. '
                f'Если не знаешь — так и скажи.\n\n'
                f'Информация о книге:\n{book_context}'
                f'{rag_block}'
            ),
        }
    ]

    for msg in history:
        messages.append({"role": msg.role, "content": msg.content})

    messages.append({"role": "user", "content": user_message})

    # Сохраняем сообщение пользователя
    BookChatMessage.objects.create(chat=chat, role="user", content=user_message)

    try:
        response = chat_completion(
            tier="main",
            feature="book_chat",
            user=chat.user,
            messages=messages,
            max_tokens=1024,
        )
        ai_text = response.choices[0].message.content.strip()
    except Exception as e:
        ai_text = f"Извините, произошла ошибка при обращении к AI: {e}"

    # Сохраняем ответ AI
    BookChatMessage.objects.create(chat=chat, role="assistant", content=ai_text)

    return ai_text

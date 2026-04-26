"""
Celery-таски, работающие с полным текстом книги (BookText / BookChapter).

Отдельный модуль, чтобы не раздувать books/tasks.py: здесь живут фичи,
которые требуют загруженного EPUB/FB2 и обращаются к LLM от имени книги:
  - summarize_chapters    (4) краткое содержание каждой главы
  - extract_book_quotes   (1) подборка литературных цитат из реального текста
  - extract_book_themes   (5) темы и мотивы книги
  - build_style_profile   (7) профиль стиля по первым главам
"""

import json
import logging

from celery import shared_task

logger = logging.getLogger(__name__)


# ── Настройки ────────────────────────────────────────────────────────────
# Лимиты, чтобы не выжирать токены на огромных книгах.
CHAPTER_SUMMARY_MAX_CHARS = 8000    # Каждой главе обрезаем контекст
BOOK_QUOTES_SAMPLE_CHARS  = 40000   # Сколько символов шлём в LLM для извлечения цитат
BOOK_THEMES_SAMPLE_CHARS  = 30000
STYLE_PROFILE_MAX_CHARS   = 20000   # Только первые главы (для spoiler-safe)


def _truncate(text: str, max_chars: int) -> str:
    if not text:
        return ""
    text = text.strip()
    if len(text) <= max_chars:
        return text
    # Режем по словам, чтобы не обрывать фразу
    head = text[:max_chars]
    last_space = head.rfind(" ")
    if last_space > max_chars * 0.8:
        head = head[:last_space]
    return head + "…"


def _sample_book_text(book, max_chars: int) -> str:
    """Берёт срез начала + середины + конца книги (чтобы охватить разные места).

    Возвращает склеенный plain text с маркерами глав.
    """
    text = getattr(book, "text", None)
    if text is None:
        return ""
    chapters = list(text.chapters.order_by("order"))
    if not chapters:
        return ""

    # Стратегия: 50% в начале, 30% в середине, 20% в конце
    n = len(chapters)
    idxs = set()
    # Первые главы
    idxs.update(range(0, min(3, n)))
    # Середина
    if n >= 5:
        mid = n // 2
        idxs.update([mid - 1, mid, mid + 1])
    # Последние главы
    if n >= 4:
        idxs.update([n - 2, n - 1])
    idxs = sorted(i for i in idxs if 0 <= i < n)

    budget = max_chars
    parts = []
    # Равномерно делим бюджет между выбранными главами
    per_chapter = max(500, budget // max(1, len(idxs)))
    for i in idxs:
        ch = chapters[i]
        piece = _truncate(ch.text, per_chapter)
        if piece:
            title = ch.title or f"Глава {ch.order + 1}"
            parts.append(f"[{title}]\n{piece}")
    return "\n\n".join(parts)[:max_chars]


# ══════════════════════════════════════════════════════════════════════════
# (4) Chapter summaries
# ══════════════════════════════════════════════════════════════════════════

@shared_task
def summarize_chapter(chapter_id: int) -> str:
    """Генерирует краткое содержание (1-2 предложения) для одной главы.

    Возвращает сам summary (для unit-тестов), побочно — пишет в БД.
    """
    from core.llm import chat_completion
    from books.models import BookChapter

    try:
        ch = BookChapter.objects.select_related("book_text__book").get(pk=chapter_id)
    except BookChapter.DoesNotExist:
        return ""

    body = _truncate(ch.text, CHAPTER_SUMMARY_MAX_CHARS)
    if not body or len(body) < 80:
        ch.summary = ""
        ch.summary_status = BookChapter.SUMMARY_ERROR
        ch.save(update_fields=["summary", "summary_status"])
        return ""

    title = ch.title or f"Глава {ch.order + 1}"
    book = ch.book_text.book

    prompt = (
        f"Книга: «{book.title}»\n"
        f"Сейчас — {title}.\n\n"
        f"Текст главы:\n{body}\n\n"
        f"Напиши 1–2 предложения, что происходит в этой главе. Без спойлеров к развязке. "
        f"Только факты сюжета, без оценок. Ответ на русском, максимум 180 символов."
    )

    try:
        resp = chat_completion(
            tier="light",
            feature="chapter_summary",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=120,
        )
        summary = (resp.choices[0].message.content or "").strip()
        # Обрезаем кавычки и переносы, если LLM их добавит
        summary = summary.strip('"' + "'" + " ").replace("\n", " ")
        if len(summary) > 300:
            summary = summary[:300] + "…"
        ch.summary = summary
        ch.summary_status = BookChapter.SUMMARY_OK
        ch.save(update_fields=["summary", "summary_status"])
        return summary
    except Exception as exc:
        logger.error("summarize_chapter(%d) failed: %s", chapter_id, exc)
        ch.summary_status = BookChapter.SUMMARY_ERROR
        ch.save(update_fields=["summary_status"])
        return ""


@shared_task
def summarize_all_chapters(book_id: int) -> int:
    """Запускает `summarize_chapter` для каждой главы книги.

    Возвращает число запланированных глав (полезно для UI-оповещений).
    """
    from books.models import Book

    try:
        book = Book.objects.get(pk=book_id)
    except Book.DoesNotExist:
        return 0
    text = getattr(book, "text", None)
    if not text:
        return 0

    count = 0
    for ch_id in text.chapters.values_list("id", flat=True):
        # Синхронный вызов — целостная обработка одной книги по очереди
        # (параллель лучше оставить на Celery-worker-ов при .delay на уровень выше).
        summarize_chapter(ch_id)
        count += 1
    logger.info("summarize_all_chapters: book=%d, processed=%d", book_id, count)
    return count


# ══════════════════════════════════════════════════════════════════════════
# (1) Настоящие AI-цитаты из полного текста
# ══════════════════════════════════════════════════════════════════════════

@shared_task
def extract_book_quotes(book_id: int, replace_ai: bool = True) -> int:
    """Выбирает 5–10 литературных цитат из реального текста книги.

    В отличие от `generate_smart_quotes` (который выдумывает цитаты по описанию),
    здесь LLM должна выбирать ТОЛЬКО дословные фрагменты из предоставленного текста.

    `replace_ai=True` — сносит прежние AI-цитаты и заменяет новыми.
    Возвращает число сохранённых цитат.
    """
    from core.llm import chat_completion
    from django.contrib.auth.models import User
    from books.models import Book, BookChapter, Quote, MoodTag

    try:
        book = Book.objects.prefetch_related("authors").get(pk=book_id)
    except Book.DoesNotExist:
        return 0
    text = getattr(book, "text", None)
    if not text:
        return 0

    sample = _sample_book_text(book, BOOK_QUOTES_SAMPLE_CHARS)
    if not sample:
        return 0

    mood_names = list(MoodTag.objects.values_list("name", flat=True))
    mood_hint = f"Подбери для каждой цитаты одно настроение из списка: {', '.join(mood_names)}." if mood_names else ""

    prompt = (
        f"Ниже — отрывки из книги «{book.title}». "
        f"Выбери 5–10 САМЫХ ярких литературных цитат — запоминающихся мыслей, "
        f"метафор, описаний, афоризмов. ВАЖНО: цитаты должны быть ДОСЛОВНО из текста, "
        f"НЕ перефразированные. Не бери спойлеры финала. "
        f"Каждая цитата — 1–5 предложений, не короче 30 символов. "
        f"Также укажи номер главы (номер в квадратных скобках [Глава N]), "
        f"из которой взята цитата, если видно.\n\n"
        f"{mood_hint}\n\n"
        f"Текст:\n{sample}"
    )

    tools = [{
        "type": "function",
        "function": {
            "name": "save_quotes",
            "parameters": {
                "type": "object",
                "properties": {
                    "quotes": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "text":          {"type": "string", "description": "Дословный фрагмент из текста"},
                                "chapter_title": {"type": "string", "description": "Название или номер главы из маркера"},
                                "mood":          {"type": "string", "description": "Одно из настроений из списка"},
                            },
                            "required": ["text"],
                        },
                    },
                },
                "required": ["quotes"],
            },
        },
    }]

    try:
        resp = chat_completion(
            tier="main",
            feature="quotes",
            messages=[{"role": "user", "content": prompt}],
            tools=tools,
            tool_choice={"type": "function", "function": {"name": "save_quotes"}},
            max_tokens=2000,
        )
    except Exception as exc:
        logger.error("extract_book_quotes(%d) failed: %s", book_id, exc)
        return 0

    # Парсим tool-call
    data = {}
    for choice in resp.choices:
        if not choice.message.tool_calls:
            continue
        for tc in choice.message.tool_calls:
            try:
                data = json.loads(tc.function.arguments or "{}")
            except Exception:
                continue
            break
    quotes = (data or {}).get("quotes", [])
    if not quotes:
        logger.warning("extract_book_quotes(%d): LLM returned empty", book_id)
        return 0

    ai_user = User.objects.filter(is_staff=True).first()
    if not ai_user:
        return 0

    # Удаляем прежние AI-цитаты, если просили заменить
    if replace_ai:
        Quote.objects.filter(book=book, is_ai_generated=True).delete()

    # Строим карту глав книги (номер → объект)
    chapters = {c.order: c for c in BookChapter.objects.filter(book_text=text)}

    saved = 0
    for q in quotes[:10]:
        raw = (q.get("text") or "").strip().strip('"' + "'")
        if len(raw) < 30 or len(raw) > 1500:
            continue

        # Мягкая проверка: цитата должна встречаться в сэмпле (борьба с галлюцинациями)
        # Сравнение по префиксу первых 40 символов, без пробелов и пунктуации
        key = "".join(c.lower() for c in raw[:40] if c.isalnum())
        sample_key = "".join(c.lower() for c in sample if c.isalnum())
        if key and key not in sample_key:
            logger.debug("extract_book_quotes: dropping hallucinated quote: %s…", raw[:60])
            continue

        # Пробуем привязать главу по маркеру [Глава N]
        chapter_obj = None
        ch_title = (q.get("chapter_title") or "").strip()
        import re
        m = re.search(r"глав[ауеы]?\s*(\d+)", ch_title.lower())
        if m:
            try:
                ch_num = int(m.group(1)) - 1
                chapter_obj = chapters.get(ch_num)
            except Exception:
                pass

        mood_name = (q.get("mood") or "").lower().strip()
        mood = MoodTag.objects.filter(name=mood_name).first() if mood_name else None

        Quote.objects.create(
            user=ai_user,
            book=book,
            text=raw,
            is_ai_generated=True,
            mood_tag=mood,
            chapter=chapter_obj,
        )
        saved += 1

    logger.info("extract_book_quotes: book=%d, saved=%d", book_id, saved)
    return saved


# ══════════════════════════════════════════════════════════════════════════
# (5) Темы и мотивы из полного текста
# ══════════════════════════════════════════════════════════════════════════

@shared_task
def extract_book_themes(book_id: int) -> list[str]:
    """Извлекает 5–7 центральных тем/мотивов из реального текста книги.

    Записывает результат в `Book.ai_themes` (JSONField).
    """
    from core.llm import chat_completion
    from books.models import Book

    try:
        book = Book.objects.get(pk=book_id)
    except Book.DoesNotExist:
        return []
    text = getattr(book, "text", None)
    if not text:
        return []

    sample = _sample_book_text(book, BOOK_THEMES_SAMPLE_CHARS)
    if not sample:
        return []

    prompt = (
        f"Ниже — отрывки из книги «{book.title}». "
        f"Выдели 5–7 центральных ТЕМ и МОТИВОВ. "
        f"Темы — крупные смысловые категории (любовь и одиночество, война, религия, взросление, власть, память). "
        f"Мотивы — повторяющиеся образы/ситуации (дорога, зеркало, сон, двойничество, возвращение домой). "
        f"Пиши коротко, 1–4 слова на пункт, на русском. НЕ выдумывай — только то, что реально в тексте.\n\n"
        f"Текст:\n{sample}"
    )

    tools = [{
        "type": "function",
        "function": {
            "name": "save_themes",
            "parameters": {
                "type": "object",
                "properties": {
                    "themes": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string"},
                                "kind": {"type": "string", "enum": ["theme", "motif"]},
                            },
                            "required": ["name"],
                        },
                        "maxItems": 7,
                    },
                },
                "required": ["themes"],
            },
        },
    }]

    try:
        resp = chat_completion(
            tier="light",
            feature="book_themes",
            messages=[{"role": "user", "content": prompt}],
            tools=tools,
            tool_choice={"type": "function", "function": {"name": "save_themes"}},
            max_tokens=500,
        )
    except Exception as exc:
        logger.error("extract_book_themes(%d) failed: %s", book_id, exc)
        return []

    themes_out = []
    for choice in resp.choices:
        if not choice.message.tool_calls:
            continue
        for tc in choice.message.tool_calls:
            try:
                data = json.loads(tc.function.arguments or "{}")
            except Exception:
                continue
            for t in (data.get("themes") or [])[:7]:
                name = (t.get("name") or "").strip()
                kind = (t.get("kind") or "theme").strip()
                if len(name) >= 2 and len(name) <= 80:
                    themes_out.append({"name": name, "kind": kind})
    if themes_out:
        book.ai_themes = themes_out
        book.save(update_fields=["ai_themes"])
    logger.info("extract_book_themes: book=%d, themes=%d", book_id, len(themes_out))
    return themes_out


# ══════════════════════════════════════════════════════════════════════════
# (7) Профиль стиля (для spoiler-safe рекомендаций)
# ══════════════════════════════════════════════════════════════════════════

@shared_task
def build_style_profile(book_id: int) -> dict:
    """Строит структурированный профиль стиля по первым главам книги.

    Используется для рекомендаций «похоже по стилю на первые N страниц» —
    пользователь не должен зацепить спойлеры финала.
    """
    from core.llm import chat_completion
    from books.models import Book

    try:
        book = Book.objects.get(pk=book_id)
    except Book.DoesNotExist:
        return {}
    text = getattr(book, "text", None)
    if not text:
        return {}

    # Только первые главы — чтобы не подцепить спойлеры
    first_chapters = list(text.chapters.order_by("order")[:5])
    if not first_chapters:
        return {}

    parts = []
    budget_per = max(500, STYLE_PROFILE_MAX_CHARS // len(first_chapters))
    for ch in first_chapters:
        piece = _truncate(ch.text, budget_per)
        if piece:
            parts.append(piece)
    sample = ("\n\n".join(parts))[:STYLE_PROFILE_MAX_CHARS]
    if not sample:
        return {}

    prompt = (
        f"Ниже — начало книги «{book.title}» (первые главы). "
        f"Определи профиль авторского стиля. Не раскрывай сюжет. Только стиль. "
        f"Опиши структурно:\n"
        f"— тон (light / warm / ironic / dark / detached / lyrical / ...)\n"
        f"— темп (slow / medium / fast)\n"
        f"— плотность (sparse / balanced / dense)\n"
        f"— POV (first / third_close / third_omniscient / epistolary / second)\n"
        f"— словарь (plain / literary / archaic / colloquial / technical)\n"
        f"— длина предложений (short / medium / long)\n"
        f"— 2–4 ключевые черты стиля простыми словами\n\n"
        f"Текст:\n{sample}"
    )

    tools = [{
        "type": "function",
        "function": {
            "name": "save_style",
            "parameters": {
                "type": "object",
                "properties": {
                    "tone":            {"type": "string"},
                    "pace":            {"type": "string"},
                    "density":         {"type": "string"},
                    "pov":             {"type": "string"},
                    "vocabulary":      {"type": "string"},
                    "sentence_length": {"type": "string"},
                    "traits":          {"type": "array", "items": {"type": "string"}, "maxItems": 4},
                },
                "required": ["tone", "pace", "traits"],
            },
        },
    }]

    try:
        resp = chat_completion(
            tier="main",
            feature="book_style",
            messages=[{"role": "user", "content": prompt}],
            tools=tools,
            tool_choice={"type": "function", "function": {"name": "save_style"}},
            max_tokens=500,
        )
    except Exception as exc:
        logger.error("build_style_profile(%d) failed: %s", book_id, exc)
        return {}

    profile = {}
    for choice in resp.choices:
        if not choice.message.tool_calls:
            continue
        for tc in choice.message.tool_calls:
            try:
                profile = json.loads(tc.function.arguments or "{}")
            except Exception:
                profile = {}
            break
    if profile:
        book.ai_style_profile = profile
        book.save(update_fields=["ai_style_profile"])
    logger.info("build_style_profile: book=%d, profile=%s", book_id, bool(profile))
    return profile

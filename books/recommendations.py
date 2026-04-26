"""
Рекомендательный движок на чистом PostgreSQL — без ML, без внешних зависимостей.

Алгоритм скоринга (похожие книги):
  +4 за каждого совпавшего автора
  +3 за каждый совпавший жанр (с TF-IDF весом — редкий жанр ценнее)
  +2 если та же серия
  +1 если год публикации ±5 лет
  +0.5 * avg_rating книги-кандидата (бонус за качество)

Персональные рекомендации:
  Собираем «профиль вкуса» из жанров/авторов книг пользователя,
  взвешиваем по частоте встречаемости и рейтингу оценок и sentiment_tag списка,
  применяем TF-IDF для редких жанров, temporal decay (свежее = важнее),
  штрафуем книги из отрицательных списков,
  MMR-диверсификация: один автор / жанр не заполняет весь топ.
  находим непрочитанные книги с максимальным попаданием.

Коллаборативная фильтрация (also_read):
  Если пользователи A, B, C добавили книгу X и книгу Y в один список —
  значит Y похожа на X. Чистый SQL, без ML.
"""

import math
from django.core.cache import cache
from django.db.models import Q, Count
from django.utils import timezone

from .models import Book, UserList, Genre, ReadingProgress
from reviews.models import Review
# Веса по sentiment_tag списка
_SENTIMENT_WEIGHT = {
    "positive": 1.0,
    "wishlist": 0.6,
    "neutral": 0.4,
    "negative": -0.5,
}

_IDF_CACHE_KEY = "genre_idf_v1"
_IDF_CACHE_TTL = 60 * 60  # 1 час


# ── ПОХОЖИЕ КНИГИ ─────────────────────────────────────────────────────────────

def similar_books(book, limit=6):
    """
    Вернуть список книг, похожих на заданную.

    Похожесть считается по авторам, жанрам (c TF‑IDF весами),
    серии, году издания и среднему рейтингу.
    """

    genre_ids = list(book.genres.values_list("id", flat=True))
    author_ids = list(book.authors.values_list("id", flat=True))

    if not genre_ids and not author_ids:
        return list(
            Book.objects.exclude(pk=book.pk)
            .prefetch_related("authors", "genres")
            .order_by("-avg_rating")[:limit]
        )

    q = Q(genres__id__in=genre_ids) | Q(authors__id__in=author_ids)
    if book.series_id:
        q |= Q(series_id=book.series_id)

    candidates = (
        Book.objects.exclude(pk=book.pk)
        .filter(q)
        .distinct()
        .prefetch_related("authors", "genres")
    )

    idf = _genre_idf()
    scored = _score_books(candidates, genre_ids, author_ids, book, idf)
    scored.sort(key=lambda x: -x[0])

    result = [b for _, b in scored[:limit]]
    if len(result) < limit:
        seen = {b.pk for b in result} | {book.pk}
        extra = list(
            Book.objects.exclude(pk__in=seen)
            .prefetch_related("authors", "genres")
            .order_by("-avg_rating")[: limit - len(result)]
        )
        result += extra

    return result


def _genre_idf():
    """TF-IDF вес жанра — кешируется на 1 час."""
    cached = cache.get(_IDF_CACHE_KEY)
    if cached is not None:
        return cached

    total = max(Book.objects.count(), 1)
    counts = Genre.objects.annotate(book_count=Count("books")).values("id", "book_count")
    idf = {row["id"]: math.log(total / max(row["book_count"], 1)) for row in counts}
    cache.set(_IDF_CACHE_KEY, idf, _IDF_CACHE_TTL)
    return idf


def invalidate_idf_cache():
    """Вызывать при добавлении новой книги."""
    cache.delete(_IDF_CACHE_KEY)


def _score_books(candidates, genre_ids, author_ids, anchor_book=None, idf=None):
    """Скоринг кандидатов. Использует prefetch_related — без N+1."""
    genre_set = set(genre_ids)
    author_set = set(author_ids)
    idf = idf or {}
    scored = []

    # Spoiler-safe: профиль стиля якоря — если у обеих книг есть AI-профиль,
    # схожесть стиля добавляет до +5 к скору (подробности в _style_similarity)
    anchor_style = getattr(anchor_book, "ai_style_profile", None) if anchor_book else None

    for book in candidates:
        score = 0.0
        c_genres = {g.id for g in book.genres.all()}
        c_authors = {a.id for a in book.authors.all()}

        for gid in c_genres & genre_set:
            score += 3 * idf.get(gid, 1.0)

        score += len(c_authors & author_set) * 4

        if anchor_book and anchor_book.series_id and book.series_id == anchor_book.series_id:
            score += 2

        if anchor_book and anchor_book.publication_year and book.publication_year:
            if abs(anchor_book.publication_year - book.publication_year) <= 5:
                score += 1

        score += book.avg_rating * 0.5

        # Spoiler-safe бонус по профилю стиля (первые главы обеих книг)
        if anchor_style:
            candidate_style = getattr(book, "ai_style_profile", None)
            if candidate_style:
                score += _style_similarity(anchor_style, candidate_style)

        if score > 0:
            scored.append((score, book))

    return scored


def _style_similarity(a: dict, b: dict) -> float:
    """Сравнивает два AI-профиля стиля и возвращает бонус к скору в [0..5].

    Структура профиля (см. books/ai_tasks.py::build_style_profile):
      {
        "tone":            str   (напр. "мрачный", "иронический")
        "pace":            str   ("быстрый", "медленный", "размеренный")
        "density":         str   ("плотный", "лёгкий")
        "pov":             str   ("от первого лица", "третье лицо всезнающее", ...)
        "vocabulary":      str   ("архаичный", "современный", "разговорный")
        "sentence_length": str   ("короткие", "длинные", "смешанные")
        "traits":          [str] — свободный список признаков
      }
    """
    if not isinstance(a, dict) or not isinstance(b, dict):
        return 0.0

    bonus = 0.0
    # Точечные совпадения по категориям — каждая даёт +0.7
    for key in ("tone", "pace", "density", "pov", "vocabulary", "sentence_length"):
        va = (a.get(key) or "").strip().lower()
        vb = (b.get(key) or "").strip().lower()
        if va and vb and va == vb:
            bonus += 0.7

    # Пересечение свободных traits — каждое совпадение +0.3, максимум +2
    traits_a = {(t or "").strip().lower() for t in (a.get("traits") or []) if t}
    traits_b = {(t or "").strip().lower() for t in (b.get("traits") or []) if t}
    overlap = traits_a & traits_b
    bonus += min(2.0, len(overlap) * 0.3)

    return min(5.0, bonus)


# ── SPOILER-SAFE: ПОХОЖИЕ ПО СТИЛЮ (первых глав) ─────────────────────────────

def similar_by_style(book, limit: int = 6):
    """Рекомендации «похоже по стилю на первые главы» — без спойлеров.

    Использует `ai_style_profile`, построенный по первым главам книги.
    Возвращает пустой список, если у якоря нет профиля.
    """
    anchor_style = getattr(book, "ai_style_profile", None)
    if not anchor_style:
        return []

    # Кандидаты — книги с непустым style_profile. В проде это небольшое
    # подмножество: сначала отфильтруем жёстко, потом оценим в Python.
    candidates = (
        Book.objects
        .exclude(pk=book.pk)
        .exclude(ai_style_profile={})
        .exclude(ai_style_profile__isnull=True)
        .prefetch_related("authors", "genres")[:400]
    )

    scored = []
    for cand in candidates:
        style = getattr(cand, "ai_style_profile", None) or {}
        sim = _style_similarity(anchor_style, style)
        if sim <= 0:
            continue
        # Лёгкий бонус за рейтинг, чтобы не выдавать откровенный мусор
        score = sim + (cand.avg_rating or 0) * 0.25
        scored.append((score, cand))

    scored.sort(key=lambda x: -x[0])
    return [b for _, b in scored[:limit]]


# ── КОЛЛАБОРАТИВНАЯ ФИЛЬТРАЦИЯ (Также читают) ────────────────────────────────

def also_read(book, limit=6):
    """
    Item-based CF: находим пользователей у которых есть эта книга в любом
    НЕ-отрицательном списке, затем смотрим какие ещё книги они добавляли.
    """

    # Только списки с положительным или нейтральным тегом
    positive_list_ids = UserList.objects.exclude(
        sentiment_tag="negative"
    ).filter(books=book).values_list("id", flat=True)

    user_ids = (
        UserList.objects
        .filter(id__in=positive_list_ids)
        .values_list("user_id", flat=True)
        .distinct()
    )

    cf_books = list(
        Book.objects
        .filter(in_lists__user__in=user_ids)
        .exclude(pk=book.pk)
        .annotate(co_count=Count(
            "in_lists__user",
            filter=Q(in_lists__user__in=user_ids),
            distinct=True,
        ))
        .filter(co_count__gt=0)
        .order_by("-co_count", "-avg_rating")
        .prefetch_related("authors", "genres")
        [:limit]
    )

    result = cf_books

    if len(result) < limit:
        seen = {b.pk for b in result} | {book.pk}
        genre_ids = list(book.genres.values_list("id", flat=True))
        author_ids = list(book.authors.values_list("id", flat=True))
        if genre_ids or author_ids:
            q = Q(genres__id__in=genre_ids) | Q(authors__id__in=author_ids)
            candidates = (
                Book.objects
                .exclude(pk__in=seen)
                .filter(q).distinct()
                .prefetch_related("authors", "genres")
            )
            idf = _genre_idf()
            extra_scored = _score_books(candidates, genre_ids, author_ids, book, idf)
            extra_scored.sort(key=lambda x: -x[0])
            result += [b for _, b in extra_scored[: limit - len(result)]]

    return result


# ── ПЕРСОНАЛЬНЫЕ РЕКОМЕНДАЦИИ ─────────────────────────────────────────────────

def recommended_for_user(user, limit=10):

    # ── 1. Сбор данных из списков пользователя ─────────────────────────────
    user_lists = (
        UserList.objects.filter(user=user)
        .prefetch_related("books__genres", "books__authors")
    )

    user_reviews = Review.objects.filter(user=user).values("book_id", "rating")
    reviewed = {r["book_id"]: r["rating"] for r in user_reviews}
    seen_ids = set(reviewed.keys())

    # Исключаем книги, которые пользователь сейчас читает
    reading_ids = ReadingProgress.objects.filter(
        user=user, current_page__gt=0
    ).values_list("book_id", flat=True)
    seen_ids.update(reading_ids)

    genre_weight = {}
    author_weight = {}
    negative_genres = set()    # жанры из отрицательных списков
    negative_authors = set()   # авторы из отрицательных списков

    now = timezone.now()

    # ── 2. Взвешиваем: sentiment × rating × temporal decay ─────────────────
    for ul in user_lists:
        sw = _SENTIMENT_WEIGHT.get(ul.sentiment_tag or "neutral", 0.4)

        # Temporal decay: 5 % затухание в месяц — свежие списки важнее
        list_age_days = max((now - ul.created_at).days, 0)
        decay = 0.95 ** (list_age_days / 30)

        for book in ul.books.all():
            seen_ids.add(book.pk)
            rating_factor = reviewed.get(book.pk, 5) / 5.0
            weight = sw * rating_factor * decay

            for g in book.genres.all():
                genre_weight[g.id] = genre_weight.get(g.id, 0) + weight
                if ul.sentiment_tag == "negative":
                    negative_genres.add(g.id)
            for a in book.authors.all():
                author_weight[a.id] = author_weight.get(a.id, 0) + weight
                if ul.sentiment_tag == "negative":
                    negative_authors.add(a.id)

    if not genre_weight and not author_weight and not reviewed:
        return _cold_start(user, limit)

    # Учитываем отзывы на книги, которых нет в списках
    orphan_review_ids = set(reviewed.keys()) - seen_ids
    if orphan_review_ids:
        for b in Book.objects.filter(pk__in=orphan_review_ids).prefetch_related("genres", "authors"):
            seen_ids.add(b.pk)
            w = 0.4 * (reviewed[b.pk] / 5.0)
            for g in b.genres.all():
                genre_weight[g.id] = genre_weight.get(g.id, 0) + w
            for a in b.authors.all():
                author_weight[a.id] = author_weight.get(a.id, 0) + w

    # Подписки на авторов — сильный положительный сигнал
    sub_author_ids = user.author_subscriptions.values_list("author_id", flat=True)
    for author_id in sub_author_ids:
        author_weight[author_id] = author_weight.get(author_id, 0) + 1.5

    # TF-IDF: редкий жанр ценнее
    idf = _genre_idf()
    for gid in genre_weight:
        genre_weight[gid] *= idf.get(gid, 1.0)

    if not genre_weight and not author_weight:
        return _cold_start(user, limit)

    # ── 3. Скоринг кандидатов ──────────────────────────────────────────────
    candidates = (
        Book.objects
        .exclude(pk__in=seen_ids)
        .filter(
            Q(genres__id__in=genre_weight.keys()) |
            Q(authors__id__in=author_weight.keys())
        )
        .distinct()
        .prefetch_related("authors", "genres", "tags")
    )

    scored = []
    for book in candidates:
        score = 0.0
        book_genres = {g.id for g in book.genres.all()}
        book_authors = {a.id for a in book.authors.all()}

        for gid in book_genres:
            score += genre_weight.get(gid, 0) * 3
        for aid in book_authors:
            score += author_weight.get(aid, 0) * 4

        # Штраф за пересечение с отрицательными списками
        neg_overlap = len(book_genres & negative_genres) * 2.0
        neg_overlap += len(book_authors & negative_authors) * 3.0
        score -= neg_overlap

        score += book.avg_rating * 0.5

        if score > 0:
            scored.append((score, book))

    # ── 4. MMR-диверсификация: один автор/жанр не заполняет весь топ ───────
    result = [b for _, b in _mmr_rerank(scored, limit)]

    if len(result) < limit:
        seen_ids = seen_ids | {b.pk for b in result}
        extra = list(
            Book.objects.exclude(pk__in=seen_ids)
            .prefetch_related("authors", "genres")
            .order_by("-avg_rating")[: limit - len(result)]
        )
        result += extra

    return result


def _mmr_rerank(scored, limit, lam=0.6):
    """
    Maximal Marginal Relevance — жадный отбор с штрафом
    за похожесть на уже отобранные книги.
    lam=1 → чистая релевантность, lam=0 → максимальное разнообразие.
    """
    if not scored:
        return []
    scored.sort(key=lambda x: -x[0])
    if len(scored) <= limit:
        return scored

    selected = [scored[0]]
    remaining = scored[1:]

    while len(selected) < limit and remaining:
        best_idx, best_mmr = 0, -999.0
        for i, (score, book) in enumerate(remaining):
            b_authors = {a.id for a in book.authors.all()}
            b_genres = {g.id for g in book.genres.all()}

            max_sim = 0.0
            for _, sel in selected:
                s_a = {a.id for a in sel.authors.all()}
                s_g = {g.id for g in sel.genres.all()}
                a_sim = len(b_authors & s_a) / max(len(b_authors | s_a), 1)
                g_sim = len(b_genres & s_g) / max(len(b_genres | s_g), 1)
                max_sim = max(max_sim, 0.5 * a_sim + 0.5 * g_sim)

            mmr = lam * score - (1 - lam) * max_sim * scored[0][0]
            if mmr > best_mmr:
                best_mmr, best_idx = mmr, i

        selected.append(remaining.pop(best_idx))

    return selected


def build_explain_context(user) -> dict:
    """
    Предвычислить данные для `explain_match` — чтобы не дёргать БД на каждую книгу.
    Возвращает:
      {
        "liked_genre_ids": set[int],
        "liked_author_ids": set[int],
        "negative_genre_ids": set[int],
        "negative_author_ids": set[int],
        "fav_genre_ids": set[int],       # из онбординга
        "fav_author_ids": set[int],
        "sub_author_ids": set[int],
        "reviewed_high": {book_id: rating},  # ≥4
      }
    """
    liked_genre_ids: set[int] = set()
    liked_author_ids: set[int] = set()
    neg_genre_ids: set[int] = set()
    neg_author_ids: set[int] = set()

    for ul in (
        UserList.objects
        .filter(user=user)
        .prefetch_related("books__genres", "books__authors")
    ):
        is_pos = ul.sentiment_tag in ("positive", "wishlist", "neutral")
        is_neg = ul.sentiment_tag == "negative"
        for b in ul.books.all():
            for g in b.genres.all():
                if is_pos: liked_genre_ids.add(g.id)
                if is_neg: neg_genre_ids.add(g.id)
            for a in b.authors.all():
                if is_pos: liked_author_ids.add(a.id)
                if is_neg: neg_author_ids.add(a.id)

    profile = getattr(user, "profile", None)
    fav_genre_ids  = set(profile.favorite_genres.values_list("id", flat=True)) if profile else set()
    fav_author_ids = set(profile.favorite_authors.values_list("id", flat=True)) if profile else set()

    sub_author_ids = set(user.author_subscriptions.values_list("author_id", flat=True))

    reviewed_high = {
        r["book_id"]: r["rating"]
        for r in Review.objects.filter(user=user, rating__gte=4).values("book_id", "rating")
    }

    return {
        "liked_genre_ids":    liked_genre_ids,
        "liked_author_ids":   liked_author_ids,
        "negative_genre_ids": neg_genre_ids,
        "negative_author_ids": neg_author_ids,
        "fav_genre_ids":      fav_genre_ids,
        "fav_author_ids":     fav_author_ids,
        "sub_author_ids":     sub_author_ids,
        "reviewed_high":      reviewed_high,
    }


def explain_match(book, ctx: dict) -> list[str]:
    """
    Вернуть список коротких пунктов, объясняющих, почему эта книга
    попала в рекомендации. Использует предвычисленный контекст из
    `build_explain_context`.
    """
    reasons: list[str] = []

    book_author_ids = {a.id for a in book.authors.all()}
    book_genre_ids  = {g.id for g in book.genres.all()}

    # 1. Подписка на автора — самый сильный сигнал
    sub_match = book_author_ids & ctx["sub_author_ids"]
    if sub_match:
        names = [a.name for a in book.authors.all() if a.id in sub_match]
        reasons.append(f"★ Подписка на автора: {', '.join(names)}")

    # 2. Автор в любимых (онбординг) или в положительных списках
    fav_author_match  = book_author_ids & (ctx["fav_author_ids"] | ctx["liked_author_ids"])
    fav_author_match -= sub_match  # чтобы не дублировать
    if fav_author_match:
        names = [a.name for a in book.authors.all() if a.id in fav_author_match]
        reasons.append(f"Автор уже нравится пользователю: {', '.join(names)}")

    # 3. Жанры в любимых / положительных списках
    fav_genre_match = book_genre_ids & (ctx["fav_genre_ids"] | ctx["liked_genre_ids"])
    if fav_genre_match:
        names = [g.name for g in book.genres.all() if g.id in fav_genre_match]
        reasons.append(f"Жанры в интересах: {', '.join(names)}")

    # 4. Пересечение с отрицательными — НЕ должно попадать, но на всякий
    neg_g = book_genre_ids & ctx["negative_genre_ids"]
    neg_a = book_author_ids & ctx["negative_author_ids"]
    if neg_g or neg_a:
        parts = []
        if neg_g:
            parts.append(f"жанры: {', '.join(g.name for g in book.genres.all() if g.id in neg_g)}")
        if neg_a:
            parts.append(f"авторы: {', '.join(a.name for a in book.authors.all() if a.id in neg_a)}")
        reasons.append(f"⚠ Пересечение с отрицательными списками ({'; '.join(parts)})")

    # 5. Высокий рейтинг
    if book.avg_rating and book.avg_rating >= 4.0:
        reasons.append(f"Высокий рейтинг читателей: {book.avg_rating:.1f}")

    if not reasons:
        reasons.append("Похожа на общий профиль интересов (холодный старт)")

    return reasons


def diagnose_recommendations(user, produced_count: int | None = None) -> dict:
    """
    Диагностика: хватает ли данных для генерации качественных рекомендаций.
    Используется в UI когда «ничего не сгенерировано».

    produced_count — сколько книг фактически вернул движок.
    Если данные есть (`has_data=True`), но produced_count == 0 — значит
    проблема не в данных, а в каталоге / фильтрах.

    Возвращает {
      "has_data":  bool,
      "reason":    str,                # человекочитаемое резюме
      "bullets":   list[str],          # пункты — чего не хватает / что есть
      "mode":      "cold" | "onboarding" | "personal" | "personal_empty",
      "catalog_size": int,
    }
    """
    lists_cnt = UserList.objects.filter(user=user).count()
    books_in_lists = Book.objects.filter(in_lists__user=user).distinct().count()
    reviews_cnt = Review.objects.filter(user=user).count()
    catalog_size = Book.objects.count()

    profile = getattr(user, "profile", None)
    fav_g = profile.favorite_genres.count() if profile else 0
    fav_a = profile.favorite_authors.count() if profile else 0
    onboarding_done = bool(profile and profile.onboarding_done)

    has_personal = bool(books_in_lists or reviews_cnt)

    bullets = [
        f"Списков: {lists_cnt} (книг в них: {books_in_lists})",
        f"Отзывов: {reviews_cnt}",
        f"Любимых жанров (онбординг): {fav_g}",
        f"Любимых авторов (онбординг): {fav_a}",
        f"Онбординг пройден: {'да' if onboarding_done else 'нет'}",
        f"Всего книг в каталоге: {catalog_size}",
    ]

    empty = produced_count is not None and produced_count == 0

    if has_personal and empty:
        mode = "personal_empty"
        reason = (
            "Данных о вас достаточно, но движок не смог собрать рекомендации. "
            "Возможные причины:"
        )
        bullets = [
            "Все подходящие по жанру/автору книги уже есть в ваших списках.",
            "Каталог пока слишком мал, чтобы подобрать непрочитанные книги "
            f"({catalog_size} книг всего).",
            "Негативные списки перевесили положительные сигналы.",
            "Произошла ошибка в момент расчёта — проверь логи сервера.",
        ] + bullets
    elif has_personal:
        mode = "personal"
        reason = "Данных достаточно для персональных рекомендаций."
    elif (fav_g or fav_a) and empty:
        mode = "personal_empty"
        reason = (
            "Персональных данных нет. По предпочтениям онбординга "
            "тоже не удалось ничего подобрать — возможно, каталог мал."
        )
    elif fav_g or fav_a:
        mode = "onboarding"
        reason = (
            "Персональных данных (списков/отзывов) нет — используются "
            "предпочтения из онбординга."
        )
    elif empty:
        mode = "cold"
        reason = (
            "Данных о пользователе нет, и каталог пуст — рекомендовать нечего."
        )
    else:
        mode = "cold"
        reason = (
            "Данных о пользователе почти нет — показаны популярные книги "
            "как холодный старт."
        )

    return {
        "has_data":     has_personal,
        "reason":       reason,
        "bullets":      bullets,
        "mode":         mode,
        "catalog_size": catalog_size,
        "empty":        empty,
    }


def build_ai_reason_bullets(user, ai_recs_cached) -> list[str]:
    """
    Причины, почему AI-рекомендаций нет в кеше.
    `ai_recs_cached` — то, что вернула load_from_cache.
    """
    if ai_recs_cached:
        return []
    from django.conf import settings as _conf
    bullets: list[str] = []
    if not getattr(_conf, "ANTHROPIC_API_KEY", ""):
        bullets.append("API-ключ LLM не настроен на сервере.")
    else:
        try:
            from ai_admin.models import AIConfig
            if not AIConfig.get().feature_enabled("recommendations"):
                bullets.append("Фича «recommendations» отключена в админке AI.")
        except Exception:
            pass
        bullets.append(
            "AI-рекомендации ещё не были сгенерированы "
            "(или кеш уже истёк — по умолчанию 24 часа)."
        )
    return bullets


def _cold_start(user, limit):
    """Холодный старт: используем предпочтения из онбординга, иначе популярное."""

    profile = getattr(user, "profile", None)
    fav_genres = list(profile.favorite_genres.values_list("id", flat=True)) if profile else []
    fav_authors = list(profile.favorite_authors.values_list("id", flat=True)) if profile else []

    if fav_genres or fav_authors:
        q = Q()
        if fav_genres:
            q |= Q(genres__id__in=fav_genres)
        if fav_authors:
            q |= Q(authors__id__in=fav_authors)
        return list(
            Book.objects.filter(q).distinct()
            .prefetch_related("authors", "genres")
            .order_by("-avg_rating")[:limit]
        )

    return list(
        Book.objects
        .prefetch_related("authors", "genres")
        .order_by("-avg_rating")[:limit]
    )

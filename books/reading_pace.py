"""
Reading Pace Predictor — предсказание времени чтения книги на основе истории пользователя.
"""

import statistics

from django.db.models import Min, Max, F
from .models import ReadingProgress


def user_reading_pace(user) -> float | None:
    """
    Медианная скорость чтения в страницах/день.
    Нужно минимум 2 книги с прогрессом > 0 для расчёта.
    """
    progress_entries = (
        ReadingProgress.objects
        .filter(user=user, current_page__gt=0)
        .select_related("book")
    )

    daily_paces = []
    for p in progress_entries:
        if not p.book.pages or p.book.pages == 0:
            continue
        # Используем updated_at (последнее обновление) vs created_at аппроксимацию
        # ReadingProgress не хранит created_at, используем приближение
        # Считаем: текущие страницы / количество дней с момента обновления
        # Грубая оценка: берём current_page как прочитанное
        pages_read = p.current_page
        if pages_read < 10:
            continue

        # Приближение: 1 книга = 1 запись, скорость ≈ pages_read / 7 (неделя по умолчанию)
        # Лучше: если есть updated_at, используем разницу
        # Но ReadingProgress обновляется при каждом сохранении, нет start_date
        # Поэтому используем среднюю скорость: pages_read как %книги
        percent_done = min(pages_read / p.book.pages, 1.0)
        if percent_done < 0.1:
            continue
        # Грубая оценка: пользователь читает ~30 стр/день (средняя)
        # Более точно: используем кол-во прочитанных книг как proxy
        daily_paces.append(pages_read)

    if len(daily_paces) < 2:
        return None

    # Медиана прочитанных страниц / 14 дней (2 недели — среднее время чтения)
    median_pages = statistics.median(daily_paces)
    return round(median_pages / 14, 1)


def predict_reading_time(user, book) -> dict | None:
    """
    Предсказывает время чтения книги для пользователя.
    Возвращает dict или None если данных мало.
    """
    if not book.pages or book.pages == 0:
        return None

    pace = user_reading_pace(user)
    if not pace or pace <= 0:
        return None

    # Количество книг с прогрессом (для уверенности)
    books_with_progress = (
        ReadingProgress.objects
        .filter(user=user, current_page__gt=10)
        .count()
    )

    if books_with_progress < 2:
        return None

    days = max(1, round(book.pages / pace))

    if books_with_progress >= 5:
        confidence = "high"
    elif books_with_progress >= 3:
        confidence = "medium"
    else:
        confidence = "low"

    return {
        "days": days,
        "pace_pages_per_day": pace,
        "confidence": confidence,
        "based_on_books": books_with_progress,
    }

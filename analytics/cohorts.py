"""
Retention-когорты пользователей: 8×8 матрица.

- Строка: «когорта регистрации» (те, кто зарегался на неделе W).
- Колонка: «недель с регистрации» (0 = та же неделя, 1 = следующая, ...).
- Ячейка: процент пользователей этой когорты, которые были "активны"
  на соответствующей неделе.

Активность = любое из:
  - SearchHistory.created_at
  - Review.created_at
  - Critique.created_at
  - ReadingProgress.updated_at

Используется TruncWeek (ISO-неделя). Алгоритм:
  1. Берём 8 последних ISO-недель — это наши когорты + окно наблюдения.
  2. Для каждой когорты (регистрация на этой неделе) считаем активных
     в каждой из 8 недель вперёд (но не дальше текущей).
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from django.contrib.auth.models import User
from django.db.models.functions import TruncWeek
from django.utils import timezone


COHORT_COUNT = 8        # сколько последних недель брать как когорты
COHORT_DEPTH = 8        # глубина наблюдения (сколько недель вперёд от регистрации)


def _monday_of(d: date) -> date:
    """Дата понедельника недели, содержащей d (ISO-неделя)."""
    return d - timedelta(days=d.weekday())


def _active_user_ids_in_week(monday: date) -> set[int]:
    """Все user_id, у которых есть активность в неделе (monday .. monday+7)."""
    from search.models import SearchHistory
    from reviews.models import Review, Critique
    from books.models import ReadingProgress

    start = datetime.combine(monday, datetime.min.time())
    end   = start + timedelta(days=7)
    # tz-aware
    tz = timezone.get_current_timezone()
    start = timezone.make_aware(start, tz) if timezone.is_naive(start) else start
    end   = timezone.make_aware(end,   tz) if timezone.is_naive(end)   else end

    ids: set[int] = set()
    ids |= set(SearchHistory.objects.filter(user__isnull=False,
                                            created_at__gte=start,
                                            created_at__lt=end)
                                    .values_list("user_id", flat=True))
    ids |= set(Review.objects.filter(created_at__gte=start, created_at__lt=end)
                             .values_list("user_id", flat=True))
    ids |= set(Critique.objects.filter(created_at__gte=start, created_at__lt=end)
                               .values_list("user_id", flat=True))
    ids |= set(ReadingProgress.objects.filter(updated_at__gte=start, updated_at__lt=end)
                                      .values_list("user_id", flat=True))
    return ids


def compute_retention_cohorts() -> dict[str, Any]:
    """
    Возвращает:
        {
          "weeks": ["10.03", "17.03", ...],     # метки понедельников когорт (8 шт)
          "depth_labels": ["0", "1", ..., "7"],  # недели с регистрации
          "rows": [
            {
              "label":       "10.03",
              "cohort_size": 42,
              "cells": [
                {"pct": 100, "n": 42, "visible": True},   # неделя 0 — сама регистрация
                {"pct": 56,  "n": 24, "visible": True},   # неделя +1
                ...
                {"pct": 0,   "n": 0,  "visible": False},  # будущие недели — серым
              ],
            },
            ...
          ],
        }
    """
    today = timezone.now().date()
    this_monday = _monday_of(today)

    # Когорты: N последних понедельников, от самой ранней к самой свежей
    cohort_mondays = [this_monday - timedelta(weeks=COHORT_COUNT - 1 - i)
                      for i in range(COHORT_COUNT)]

    # Предсчитываем для каждой "наблюдаемой" недели список активных user_id.
    # Нужны недели начиная с cohort_mondays[0] и вперёд до сегодня.
    all_weeks = set()
    for cm in cohort_mondays:
        for k in range(COHORT_DEPTH):
            wk = cm + timedelta(weeks=k)
            if wk <= this_monday:
                all_weeks.add(wk)
    active_cache: dict[date, set[int]] = {
        wk: _active_user_ids_in_week(wk) for wk in all_weeks
    }

    # Когорты: user_id, зарегавшиеся в (cohort_monday .. +7 дней)
    rows = []
    for cm in cohort_mondays:
        cohort_end = cm + timedelta(days=7)
        start_dt = datetime.combine(cm, datetime.min.time())
        end_dt   = datetime.combine(cohort_end, datetime.min.time())
        tz = timezone.get_current_timezone()
        if timezone.is_naive(start_dt):
            start_dt = timezone.make_aware(start_dt, tz)
        if timezone.is_naive(end_dt):
            end_dt = timezone.make_aware(end_dt, tz)

        cohort_ids = set(User.objects
                             .filter(date_joined__gte=start_dt,
                                     date_joined__lt=end_dt)
                             .values_list("id", flat=True))
        size = len(cohort_ids)

        cells = []
        for k in range(COHORT_DEPTH):
            wk = cm + timedelta(weeks=k)
            if wk > this_monday:
                # Будущее: нечего показывать
                cells.append({"pct": 0, "n": 0, "visible": False, "future": True})
                continue
            active = active_cache.get(wk, set())
            n_active = len(cohort_ids & active)
            pct = round(n_active / size * 100, 1) if size else 0
            cells.append({"pct": pct, "n": n_active, "visible": True, "future": False})

        rows.append({
            "label":       cm.strftime("%d.%m"),
            "monday":      cm.isoformat(),
            "cohort_size": size,
            "cells":       cells,
        })

    return {
        "weeks":        [r["label"] for r in rows],
        "depth_labels": [str(i) for i in range(COHORT_DEPTH)],
        "rows":         rows,
    }

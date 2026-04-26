"""
Celery-таски аналитики.

- `refresh_dashboard_cache` — вызывается раз в час celery-beat'ом.
  Тяжёлая функция `build_dashboard()` выполняется в фоне;
  админ-панель читает из кеша мгновенно.
"""
import logging

from celery import shared_task
from django.core.cache import cache

from .compute import DASHBOARD_CACHE_KEY, DASHBOARD_CACHE_TTL, build_dashboard


logger = logging.getLogger(__name__)


@shared_task(name="analytics.refresh_dashboard_cache")
def refresh_dashboard_cache() -> str:
    """
    Пересобирает полный дашборд и кладёт в кеш. Возвращает короткую сводку.
    """
    try:
        data = build_dashboard()
        cache.set(DASHBOARD_CACHE_KEY, data, DASHBOARD_CACHE_TTL)
        summary = (
            f"ok · kpis.users.total={data['kpis']['users']['total']} · "
            f"kpis.clicks.total={data['kpis']['clicks']['total']} · "
            f"cohorts.rows={len(data['cohorts']['rows'])}"
        )
        logger.info("analytics dashboard cache refreshed: %s", summary)
        return summary
    except Exception as exc:
        logger.exception("refresh_dashboard_cache failed: %s", exc)
        # НЕ перезапиcываем кеш при ошибке — пусть остаются прошлые данные
        raise

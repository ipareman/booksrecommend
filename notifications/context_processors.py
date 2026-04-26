"""
Контекст-процессор для всех шаблонов: счётчик непрочитанных + последние 5 событий.

Регистрируется в settings.TEMPLATES[0]["OPTIONS"]["context_processors"].
"""
from __future__ import annotations

from .models import Notification


def notifications_counts(request):
    user = getattr(request, "user", None)
    if not (user and getattr(user, "is_authenticated", False)):
        return {
            "notifications_unread": 0,
            "notifications_recent_5": [],
        }

    try:
        qs = Notification.objects.for_user(user)
        unread = qs.filter(read_at__isnull=True).count()
        recent = list(
            qs.select_related("actor")
              .order_by("-updated_at")[:5]
        )
    except Exception:
        unread = 0
        recent = []

    return {
        "notifications_unread": unread,
        "notifications_recent_5": recent,
    }

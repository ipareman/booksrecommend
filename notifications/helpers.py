"""
Точки входа для создания уведомлений.
Используются из сигналов (`notifications/signals.py`), Celery-тасок
(`notifications/tasks.py`) и ручных вызовов (например, из `reviews.views`).
"""
from __future__ import annotations

import logging
from typing import Optional

from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.utils import timezone

from .models import Notification

logger = logging.getLogger(__name__)


def emit(
    *,
    user,
    kind: str,
    actor=None,
    target=None,
    text: str = "",
    url: str = "",
    extra: Optional[dict] = None,
) -> Optional[Notification]:
    """
    Создать Notification. Возвращает объект или None, если
    пользователь-получатель невалиден / совпадает с actor (не уведомляем себя).

    Безопасно: заворачиваем в try — ошибка записи не ломает родительский сигнал.
    """
    if not user or not getattr(user, "is_authenticated", True):
        return None
    if actor and actor.pk == getattr(user, "pk", None):
        return None  # не шлём уведомление самому себе

    target_ct = None
    target_id = None
    if target is not None:
        try:
            target_ct = ContentType.objects.get_for_model(target.__class__)
            target_id = target.pk
        except Exception:
            target_ct, target_id = None, None

    try:
        return Notification.objects.create(
            user=user,
            kind=kind,
            actor=actor if (actor and getattr(actor, "is_authenticated", True)) else None,
            target_ct=target_ct,
            target_id=target_id,
            text=(text or "")[:300],
            url=(url or "")[:500],
            extra=extra or {},
        )
    except Exception as exc:
        logger.warning("emit(kind=%s) failed: %s", kind, exc)
        return None


def upsert_chat_notification(recipient, room, actor, body_preview: str) -> Optional[Notification]:
    """
    Спец-логика дедупа для `kind=new_message`:
    - одна запись на (user, kind, extra.room_id)
    - при новом сообщении инкрементит счётчик в extra и помечает unread,
      обновляет превью и всплывает наверх (`updated_at`)
    """
    if not recipient or getattr(recipient, "pk", None) is None:
        return None
    if actor and actor.pk == recipient.pk:
        return None

    actor_name = getattr(actor, "username", "кто-то") if actor else "кто-то"
    preview = (body_preview or "").strip().replace("\n", " ")
    if len(preview) > 120:
        preview = preview[:117] + "…"

    url = f"/chat/{room.pk}/"
    kind = Notification.KIND_NEW_MESSAGE

    with transaction.atomic():
        qs = (
            Notification.objects
            .select_for_update()
            .filter(user=recipient, kind=kind, extra__room_id=room.pk)
            .order_by("-updated_at")
        )
        existing = qs.first()
        if existing:
            count = int(existing.extra.get("count", 1)) + 1
            existing.extra = {**existing.extra, "count": count, "room_id": room.pk}
            existing.text = f"{actor_name}: «{preview}»" if preview else f"{actor_name}: новое сообщение"
            existing.actor = actor
            existing.url = url
            existing.read_at = None
            existing.updated_at = timezone.now()
            existing.save(update_fields=["extra", "text", "actor", "url", "read_at", "updated_at"])
            return existing

        return emit(
            user=recipient,
            kind=kind,
            actor=actor,
            target=room,
            text=(f"{actor_name}: «{preview}»" if preview else f"{actor_name}: новое сообщение"),
            url=url,
            extra={"room_id": room.pk, "count": 1},
        )

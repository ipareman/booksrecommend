"""
Подписки на post_save других моделей → запись в Notification.

Подключаются один раз через `NotificationsConfig.ready()`.
Все хендлеры обёрнуты в try/except — ошибка в уведомлении не должна
ломать исходную бизнес-транзакцию (создание сообщения, отзыва и т.д.).
"""
from __future__ import annotations

import logging

from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver

from .helpers import emit, upsert_chat_notification
from .models import Notification

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# CHAT: новое сообщение → уведомление каждому участнику, кроме отправителя
# ─────────────────────────────────────────────────────────────────────────────
@receiver(post_save, sender="chat.ChatMessage")
def on_chat_message_created(sender, instance, created, **kwargs):
    if not created:
        return
    try:
        room = instance.room
        actor = instance.user
        body = (instance.body or "").strip()
        # participants — related name на ChatRoom.participants (ChatParticipant)
        parts = room.participants.select_related("user").exclude(user_id=actor.pk)
        for p in parts:
            upsert_chat_notification(
                recipient=p.user,
                room=room,
                actor=actor,
                body_preview=body,
            )
    except Exception as exc:
        logger.warning("on_chat_message_created failed: %s", exc)


# ─────────────────────────────────────────────────────────────────────────────
# SOCIAL: заявка в друзья / её принятие
# ─────────────────────────────────────────────────────────────────────────────
@receiver(pre_save, sender="social.Friendship")
def on_friendship_presave(sender, instance, **kwargs):
    """Запомнить старый статус, чтобы отличать переход в accepted от простого save."""
    if not instance.pk:
        instance._old_status = None
        return
    try:
        old = sender.objects.only("status").get(pk=instance.pk)
        instance._old_status = old.status
    except sender.DoesNotExist:
        instance._old_status = None


@receiver(post_save, sender="social.Friendship")
def on_friendship_saved(sender, instance, created, **kwargs):
    try:
        if created and instance.status == "pending":
            # Заявка в друзья → получателю
            actor = instance.from_user
            recipient = instance.to_user
            actor_name = getattr(actor, "username", "кто-то")
            emit(
                user=recipient,
                kind=Notification.KIND_FRIEND_REQUEST,
                actor=actor,
                target=instance,
                text=f"{actor_name} отправил(а) заявку в друзья",
                url="/social/friends/",
                extra={"friendship_id": instance.pk},
            )
            return

        old_status = getattr(instance, "_old_status", None)
        if old_status != "accepted" and instance.status == "accepted":
            # Заявка принята → инициатору (from_user), получатель уже знает
            actor = instance.to_user
            recipient = instance.from_user
            actor_name = getattr(actor, "username", "кто-то")
            emit(
                user=recipient,
                kind=Notification.KIND_FRIEND_ACCEPTED,
                actor=actor,
                target=instance,
                text=f"{actor_name} принял(а) вашу заявку в друзья",
                url=f"/users/{actor_name}/",
                extra={"friendship_id": instance.pk},
            )
    except Exception as exc:
        logger.warning("on_friendship_saved failed: %s", exc)


# ─────────────────────────────────────────────────────────────────────────────
# SOCIAL: рекомендация книги от друга
# ─────────────────────────────────────────────────────────────────────────────
@receiver(post_save, sender="social.BookRecommendation")
def on_book_recommendation_created(sender, instance, created, **kwargs):
    if not created:
        return
    try:
        actor = instance.from_user
        recipient = instance.to_user
        book = instance.book
        actor_name = getattr(actor, "username", "кто-то")
        book_title = getattr(book, "title", "книгу")
        emit(
            user=recipient,
            kind=Notification.KIND_BOOK_RECOMMENDED,
            actor=actor,
            target=instance,
            text=f"{actor_name} рекомендует: «{book_title}»",
            url="/social/recommendations/",
            extra={"book_id": getattr(book, "pk", None), "rec_id": instance.pk},
        )
    except Exception as exc:
        logger.warning("on_book_recommendation_created failed: %s", exc)


# ─────────────────────────────────────────────────────────────────────────────
# REVIEWS: комментарий к рецензии + ответ на комментарий
# ─────────────────────────────────────────────────────────────────────────────
@receiver(post_save, sender="reviews.CritiqueComment")
def on_critique_comment_created(sender, instance, created, **kwargs):
    if not created:
        return
    try:
        actor = instance.user
        critique = instance.critique
        actor_name = getattr(actor, "username", "кто-то")
        snippet = (instance.text or "").strip().replace("\n", " ")
        if len(snippet) > 120:
            snippet = snippet[:117] + "…"

        url = f"/reviews/critique/{critique.pk}/#comment-{instance.pk}"

        if instance.parent_id is None:
            # Комментарий верхнего уровня → автору рецензии
            recipient = critique.user
            emit(
                user=recipient,
                kind=Notification.KIND_CRITIQUE_COMMENT,
                actor=actor,
                target=instance,
                text=f"{actor_name} прокомментировал(а) «{critique.title}»: «{snippet}»"
                     if snippet else f"{actor_name} прокомментировал(а) «{critique.title}»",
                url=url,
                extra={"critique_id": critique.pk, "comment_id": instance.pk},
            )
        else:
            # Ответ → автору родительского комментария
            parent_user = getattr(instance.parent, "user", None)
            if parent_user is None:
                return
            emit(
                user=parent_user,
                kind=Notification.KIND_CRITIQUE_REPLY,
                actor=actor,
                target=instance,
                text=f"{actor_name} ответил(а) вам: «{snippet}»"
                     if snippet else f"{actor_name} ответил(а) вам",
                url=url,
                extra={
                    "critique_id": critique.pk,
                    "comment_id": instance.pk,
                    "parent_id": instance.parent_id,
                },
            )
    except Exception as exc:
        logger.warning("on_critique_comment_created failed: %s", exc)

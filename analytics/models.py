"""
Модели аналитики:
- StoreClick: клик по ссылке «Купить» (для воронки trafik→магазин).
- ModerationLog: журнал действий администратора (одобрено/отклонено/блокировка/…).
"""
from django.conf import settings
from django.db import models


class StoreClick(models.Model):
    """Один клик по ссылке «Купить» у книги. Пишется через server-redirect /b/<book>/s/<store>/."""

    book    = models.ForeignKey("books.Book",  on_delete=models.CASCADE, related_name="store_clicks")
    store   = models.ForeignKey("books.Store", on_delete=models.CASCADE, related_name="clicks")
    user    = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                null=True, blank=True, related_name="store_clicks")
    session_key = models.CharField(max_length=40, blank=True, db_index=True,
                                   help_text="Для дедупликации кликов анонимов в пределах сессии.")
    referer = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["-created_at", "store"]),
            models.Index(fields=["-created_at", "book"]),
        ]

    def __str__(self) -> str:
        return f"{self.book_id} → {self.store_id} @ {self.created_at:%Y-%m-%d %H:%M}"


class ModerationLog(models.Model):
    """Запись о модераторском действии: кто, что, с каким объектом, когда."""

    ACTION_CHOICES = [
        ("review_approve",    "Отзыв одобрен"),
        ("review_reject",     "Отзыв отклонён"),
        ("critique_approve",  "Рецензия одобрена"),
        ("critique_reject",   "Рецензия отклонена"),
        ("user_block",        "Пользователь заблокирован"),
        ("user_unblock",      "Пользователь разблокирован"),
        ("user_notify",       "Отправлено уведомление пользователю"),
        ("store_save",        "Магазин сохранён"),
        ("store_delete",      "Магазин удалён"),
        ("book_delete",       "Книга удалена"),
        ("other",             "Иное"),
    ]

    moderator   = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                    null=True, related_name="+")
    action      = models.CharField(max_length=32, choices=ACTION_CHOICES, db_index=True)
    target_type = models.CharField(max_length=32, blank=True,
                                   help_text="Название модели цели (review / critique / user / store / book).")
    target_id   = models.IntegerField(null=True, blank=True)
    target_repr = models.CharField(max_length=250, blank=True,
                                   help_text="Человекочитаемое представление цели на момент действия.")
    note        = models.CharField(max_length=500, blank=True,
                                   help_text="Комментарий (причина отклонения и т.п.).")
    created_at  = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["-created_at", "action"]),
        ]

    def __str__(self) -> str:
        return f"[{self.action}] {self.target_type}#{self.target_id} by {self.moderator_id}"

    @classmethod
    def log(cls, moderator, action: str, target=None, note: str = "") -> "ModerationLog":
        """
        Удобный хелпер. target — Django-объект; из него извлекаем тип и id.
        """
        target_type = ""
        target_id   = None
        target_repr = ""
        if target is not None:
            target_type = target._meta.model_name or ""
            target_id   = getattr(target, "pk", None)
            try:
                target_repr = str(target)[:250]
            except Exception:
                target_repr = ""
        return cls.objects.create(
            moderator=moderator if getattr(moderator, "is_authenticated", False) else None,
            action=action,
            target_type=target_type,
            target_id=target_id,
            target_repr=target_repr,
            note=note[:500],
        )

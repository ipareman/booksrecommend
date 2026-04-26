"""
Модели уведомлений: единая лента входящих событий для пользователя.

Одна таблица `Notification`. `kind` — типизированное событие,
`actor` — инициатор (может быть NULL для системных),
`target_ct`/`target_id` — обобщённая ссылка на сущность
(Book / ChatRoom / Friendship / Critique / Review / etc),
`text`/`url` — пре-рендеренные поля для ленты,
`extra` — место под kind-специфичные данные (room_id, unread_count).
"""
from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.utils import timezone


class NotificationManager(models.Manager):
    def for_user(self, user):
        if not (user and getattr(user, "is_authenticated", False)):
            return self.none()
        return self.filter(user=user)

    def unread(self, user):
        return self.for_user(user).filter(read_at__isnull=True)

    def recent(self, user, limit: int = 10):
        return self.for_user(user).order_by("-updated_at")[:limit]


class Notification(models.Model):
    """Единичная запись ленты уведомлений."""

    # Типы событий v1
    KIND_NEW_MESSAGE        = "new_message"
    KIND_NEW_BOOK_BY_AUTHOR = "new_book_by_author"
    KIND_FRIEND_REQUEST     = "friend_request"
    KIND_FRIEND_ACCEPTED    = "friend_accepted"
    KIND_BOOK_RECOMMENDED   = "book_recommended"
    KIND_REVIEW_MODERATED   = "review_moderated"
    KIND_CRITIQUE_COMMENT   = "critique_comment"
    KIND_CRITIQUE_REPLY     = "critique_reply"
    KIND_ADMIN_NOTICE       = "admin_notice"
    KIND_MENTIONED          = "mentioned"  # @username в чате

    KIND_CHOICES = [
        (KIND_NEW_MESSAGE,        "Новое сообщение"),
        (KIND_NEW_BOOK_BY_AUTHOR, "Новая книга у автора"),
        (KIND_FRIEND_REQUEST,     "Заявка в друзья"),
        (KIND_FRIEND_ACCEPTED,    "Заявка принята"),
        (KIND_BOOK_RECOMMENDED,   "Рекомендация книги"),
        (KIND_REVIEW_MODERATED,   "Отзыв/рецензия: модерация"),
        (KIND_CRITIQUE_COMMENT,   "Комментарий к рецензии"),
        (KIND_CRITIQUE_REPLY,     "Ответ на комментарий"),
        (KIND_ADMIN_NOTICE,       "Уведомление от администрации"),
        (KIND_MENTIONED,          "Упоминание в чате"),
    ]

    # Иконка по типу (для UI)
    KIND_ICON = {
        KIND_NEW_MESSAGE:        "✉",
        KIND_NEW_BOOK_BY_AUTHOR: "📚",
        KIND_FRIEND_REQUEST:     "👤",
        KIND_FRIEND_ACCEPTED:    "🤝",
        KIND_BOOK_RECOMMENDED:   "💡",
        KIND_REVIEW_MODERATED:   "✅",
        KIND_CRITIQUE_COMMENT:   "💬",
        KIND_CRITIQUE_REPLY:     "↩",
        KIND_ADMIN_NOTICE:       "📢",
        KIND_MENTIONED:          "@",
    }

    # Категория (для v2-фильтров; в v1 не обязательна)
    KIND_CATEGORY = {
        KIND_NEW_MESSAGE:        "messages",
        KIND_NEW_BOOK_BY_AUTHOR: "books",
        KIND_FRIEND_REQUEST:     "social",
        KIND_FRIEND_ACCEPTED:    "social",
        KIND_BOOK_RECOMMENDED:   "social",
        KIND_REVIEW_MODERATED:   "system",
        KIND_CRITIQUE_COMMENT:   "social",
        KIND_CRITIQUE_REPLY:     "social",
        KIND_ADMIN_NOTICE:       "system",
        KIND_MENTIONED:          "social",
    }

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notifications",
    )
    kind = models.CharField(max_length=32, choices=KIND_CHOICES, db_index=True)

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="notifications_authored",
    )

    # GenericForeignKey на любой target-объект
    target_ct = models.ForeignKey(
        ContentType, on_delete=models.SET_NULL, null=True, blank=True,
    )
    target_id = models.PositiveIntegerField(null=True, blank=True)
    target    = GenericForeignKey("target_ct", "target_id")

    text  = models.CharField(max_length=300, blank=True)
    url   = models.CharField(max_length=500, blank=True)
    extra = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)
    read_at    = models.DateTimeField(null=True, blank=True)

    objects = NotificationManager()

    class Meta:
        ordering = ["-updated_at"]
        indexes = [
            models.Index(fields=["user", "read_at", "-updated_at"]),
            models.Index(fields=["user", "kind"]),
        ]

    def __str__(self):
        mark = "•" if self.read_at is None else " "
        return f"{mark} [{self.kind}] → {self.user}: {self.text[:60]}"

    @property
    def is_unread(self) -> bool:
        return self.read_at is None

    @property
    def icon(self) -> str:
        return self.KIND_ICON.get(self.kind, "🔔")

    @property
    def category(self) -> str:
        return self.KIND_CATEGORY.get(self.kind, "other")

    def mark_read(self, *, commit: bool = True):
        if self.read_at is None:
            self.read_at = timezone.now()
            if commit:
                self.save(update_fields=["read_at", "updated_at"])


# ═══════════════════════════════════════════════════════════════════════════════
# НАСТРОЙКИ РАССЫЛКИ (админская «матрица»: событие × канал)
# ═══════════════════════════════════════════════════════════════════════════════

class NotificationSetting(models.Model):
    """
    Админская матрица «какие события идут в какие каналы».

    Строка = событие (например «новая книга у подписного автора»).
    Столбцы = каналы: telegram / max / email.

    Inbox (/notifications/) не управляется отсюда — он всегда включён,
    это базовый «входящий» пользователя. Матрица регулирует только внешние
    каналы: сколько шума летит в мессенджеры/почту.
    """

    # События, которые рассылаются вовне.
    EVENT_NEW_BOOK          = "new_book"          # books → подписчикам автора
    EVENT_PRICE_ALERT       = "price_alert"       # снижение цены
    EVENT_REVIEW_APPROVED   = "review_approved"   # модерация отзыва: принят
    EVENT_REVIEW_REJECTED   = "review_rejected"   # модерация отзыва: отклонён
    EVENT_CRITIQUE_APPROVED = "critique_approved"
    EVENT_CRITIQUE_REJECTED = "critique_rejected"
    EVENT_WEEKLY_DIGEST     = "weekly_digest"     # еженедельный дайджест

    EVENT_CHOICES = [
        (EVENT_NEW_BOOK,          "Новая книга у подписного автора"),
        (EVENT_PRICE_ALERT,       "Алерт о снижении цены"),
        (EVENT_REVIEW_APPROVED,   "Отзыв одобрен"),
        (EVENT_REVIEW_REJECTED,   "Отзыв отклонён"),
        (EVENT_CRITIQUE_APPROVED, "Рецензия одобрена"),
        (EVENT_CRITIQUE_REJECTED, "Рецензия отклонена"),
        (EVENT_WEEKLY_DIGEST,     "Еженедельный дайджест"),
    ]

    CHANNELS = ("telegram", "max", "email")
    CHANNEL_LABELS = {
        "telegram": "Telegram",
        "max":      "MAX",
        "email":    "Email",
    }

    event = models.CharField(max_length=32, unique=True, choices=EVENT_CHOICES)
    channel_telegram = models.BooleanField(default=True)
    channel_max      = models.BooleanField(default=True)
    channel_email    = models.BooleanField(default=True)
    updated_at       = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["event"]
        verbose_name = "Настройка рассылки"
        verbose_name_plural = "Настройки рассылок"

    def __str__(self):
        ch = []
        if self.channel_telegram: ch.append("TG")
        if self.channel_max:      ch.append("MAX")
        if self.channel_email:    ch.append("email")
        return f"{self.get_event_display()} → {','.join(ch) or '—'}"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        self._invalidate_cache(self.event)

    def delete(self, *args, **kwargs):
        event = self.event
        super().delete(*args, **kwargs)
        self._invalidate_cache(event)

    @staticmethod
    def _cache_key(event: str) -> str:
        return f"notif_setting:{event}"

    @classmethod
    def _invalidate_cache(cls, event: str):
        try:
            from django.core.cache import cache
            cache.delete(cls._cache_key(event))
        except Exception:
            pass

    @classmethod
    def channels_for(cls, event: str) -> dict:
        """
        Возвращает словарь {"telegram": bool, "max": bool, "email": bool}
        для заданного event. Если строки настройки нет — всё включено (default).
        Кешируется на 60 секунд.
        """
        from django.core.cache import cache
        key = cls._cache_key(event)
        cached = cache.get(key)
        if cached is not None:
            return cached

        setting = cls.objects.filter(event=event).first()
        if setting is None:
            result = {c: True for c in cls.CHANNELS}
        else:
            result = {
                "telegram": bool(setting.channel_telegram),
                "max":      bool(setting.channel_max),
                "email":    bool(setting.channel_email),
            }
        cache.set(key, result, 60)
        return result

    @classmethod
    def is_enabled(cls, event: str, channel: str) -> bool:
        """Короткий хелпер для проверки одного канала."""
        return cls.channels_for(event).get(channel, True)

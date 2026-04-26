from django.conf import settings
from django.db import models


class ChatRoom(models.Model):
    """DM or club chat room."""

    ROOM_DM = "dm"
    ROOM_CLUB = "club"
    ROOM_TYPE_CHOICES = [
        (ROOM_DM, "Личные сообщения"),
        (ROOM_CLUB, "Клубный чат"),
    ]

    room_type = models.CharField(max_length=10, choices=ROOM_TYPE_CHOICES, default=ROOM_DM)
    club = models.OneToOneField(
        "clubs.BookClub", on_delete=models.CASCADE, null=True, blank=True, related_name="chat_room_link",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        if self.room_type == self.ROOM_CLUB and self.club:
            return f"Club chat: {self.club.name}"
        participants = self.participants.values_list("user__username", flat=True)
        return f"DM: {', '.join(participants)}"


class ChatParticipant(models.Model):
    room = models.ForeignKey(ChatRoom, on_delete=models.CASCADE, related_name="participants")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="chat_participations")
    joined_at = models.DateTimeField(auto_now_add=True)
    last_read_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("room", "user")


class ChatMessage(models.Model):
    room = models.ForeignKey(ChatRoom, on_delete=models.CASCADE, related_name="messages")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="chat_messages")
    body = models.TextField(blank=True)
    # Опциональное вложение: книга из каталога. Рендерится карточкой в чате
    # (обложка + название + авторы). Разрешаем пустой body, если книга есть.
    attached_book = models.ForeignKey(
        "books.Book",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return f"{self.user.username}: {self.body[:40]}"


class ChatMessageReaction(models.Model):
    """
    Emoji-реакция на сообщение. Один пользователь может поставить разные emoji
    на одно сообщение, но один и тот же emoji — только однажды (toggle on/off).
    """
    # Whitelist на уровне приложения. Расширяем список — добавляем сюда,
    # а не позволяем произвольный unicode (защита от спама и нагрузки на UI).
    ALLOWED_EMOJI = ["👍", "❤️", "😂", "😮", "🎉", "🙏"]

    message = models.ForeignKey(ChatMessage, on_delete=models.CASCADE, related_name="reactions")
    user    = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    emoji   = models.CharField(max_length=8)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("message", "user", "emoji")
        indexes = [models.Index(fields=["message", "emoji"])]
        ordering = ["created_at"]

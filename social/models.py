from django.db import models
from django.conf import settings


class Friendship(models.Model):
    STATUS_CHOICES = [
        ("pending", "Ожидание"),
        ("accepted", "Принято"),
    ]
    from_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="friendship_requests_sent",
    )
    to_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="friendship_requests_received",
    )
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default="pending")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("from_user", "to_user")

    def __str__(self):
        return f"{self.from_user} → {self.to_user} ({self.status})"


class ActivityEvent(models.Model):
    EVENT_TYPES = [
        ("add_to_list", "Добавление в список"),
        ("review", "Отзыв"),
        ("join_club", "Вступление в клуб"),
        ("new_friendship", "Новая дружба"),
        ("book_recommend", "Рекомендация книги"),
    ]
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="activity_events",
    )
    event_type = models.CharField(max_length=20, choices=EVENT_TYPES)
    book = models.ForeignKey(
        "books.Book", on_delete=models.CASCADE, null=True, blank=True
    )
    target_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="activity_mentions",
    )
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.user} — {self.event_type}"


class BookRecommendation(models.Model):
    from_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="book_recs_sent",
    )
    to_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="book_recs_received",
    )
    book = models.ForeignKey("books.Book", on_delete=models.CASCADE)
    message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    is_read = models.BooleanField(default=False)

    class Meta:
        unique_together = ("from_user", "to_user", "book")
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.from_user} → {self.to_user}: {self.book}"

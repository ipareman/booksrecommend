from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.urls import reverse
from django.utils import timezone


class Ticket(models.Model):
    KIND_REQUEST = "request"
    KIND_REPORT = "report"
    KIND_CHOICES = [
        (KIND_REQUEST, "Обращение"),
        (KIND_REPORT, "Жалоба"),
    ]

    STATUS_OPEN = "open"
    STATUS_IN_PROGRESS = "in_progress"
    STATUS_ANSWERED = "answered"
    STATUS_CLOSED = "closed"
    STATUS_CHOICES = [
        (STATUS_OPEN, "Открыт"),
        (STATUS_IN_PROGRESS, "В работе"),
        (STATUS_ANSWERED, "Есть ответ"),
        (STATUS_CLOSED, "Закрыт"),
    ]

    PRIORITY_NORMAL = "normal"
    PRIORITY_HIGH = "high"
    PRIORITY_CHOICES = [
        (PRIORITY_NORMAL, "Обычный"),
        (PRIORITY_HIGH, "Важный"),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="tickets",
    )
    kind = models.CharField(max_length=16, choices=KIND_CHOICES, db_index=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_OPEN, db_index=True)
    priority = models.CharField(max_length=12, choices=PRIORITY_CHOICES, default=PRIORITY_NORMAL, db_index=True)

    subject = models.CharField(max_length=180)
    body = models.TextField()

    target_ct = models.ForeignKey(ContentType, on_delete=models.SET_NULL, null=True, blank=True)
    target_id = models.PositiveIntegerField(null=True, blank=True)
    target = GenericForeignKey("target_ct", "target_id")
    target_label = models.CharField(max_length=240, blank=True)
    target_url = models.CharField(max_length=500, blank=True)

    admin_response = models.TextField(blank=True)
    responded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ticket_responses",
    )
    responded_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]
        indexes = [
            models.Index(fields=["kind", "status", "-updated_at"]),
            models.Index(fields=["user", "-updated_at"]),
        ]

    def __str__(self):
        return f"#{self.pk} {self.get_kind_display()}: {self.subject}"

    def get_absolute_url(self):
        return reverse("ticket_detail", kwargs={"pk": self.pk})

    @property
    def is_report(self):
        return self.kind == self.KIND_REPORT

    def mark_answered(self, user, text):
        self.admin_response = text
        self.responded_by = user
        self.responded_at = timezone.now()
        self.status = self.STATUS_ANSWERED
        self.save(update_fields=["admin_response", "responded_by", "responded_at", "status", "updated_at"])

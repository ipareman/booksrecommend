import hashlib
import secrets

from django.conf import settings
from django.db import models
from django.utils import timezone


class ApiKey(models.Model):
    name = models.CharField(max_length=120)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="api_keys",
    )
    prefix = models.CharField(max_length=12, unique=True, db_index=True)
    key_hash = models.CharField(max_length=64, unique=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.name} ({self.prefix}...)"

    @staticmethod
    def hash_key(raw_key):
        return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()

    @classmethod
    def create_key(cls, *, owner, name):
        raw_key = f"sk_stroka_{secrets.token_urlsafe(32)}"
        key = cls.objects.create(
            owner=owner,
            name=name,
            prefix=raw_key[:12],
            key_hash=cls.hash_key(raw_key),
        )
        return key, raw_key

    def revoke(self):
        self.is_active = False
        self.revoked_at = timezone.now()
        self.save(update_fields=["is_active", "revoked_at"])


class ApiRequestLog(models.Model):
    api_key = models.ForeignKey(
        ApiKey,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="request_logs",
    )
    path = models.CharField(max_length=255)
    method = models.CharField(max_length=8)
    status_code = models.PositiveSmallIntegerField()
    remote_addr = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=255, blank=True)
    latency_ms = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]

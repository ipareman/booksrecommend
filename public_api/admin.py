from django.contrib import admin

from .models import ApiKey, ApiRequestLog


@admin.register(ApiKey)
class ApiKeyAdmin(admin.ModelAdmin):
    list_display = ("name", "owner", "prefix", "is_active", "created_at", "last_used_at")
    list_filter = ("is_active", "created_at")
    search_fields = ("name", "owner__username", "prefix")
    readonly_fields = ("prefix", "key_hash", "created_at", "last_used_at", "revoked_at")


@admin.register(ApiRequestLog)
class ApiRequestLogAdmin(admin.ModelAdmin):
    list_display = ("path", "method", "status_code", "api_key", "latency_ms", "created_at")
    list_filter = ("status_code", "method", "created_at")
    search_fields = ("path", "api_key__name", "api_key__prefix")
    readonly_fields = ("api_key", "path", "method", "status_code", "remote_addr", "user_agent", "latency_ms", "created_at")

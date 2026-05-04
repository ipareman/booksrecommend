from django.contrib import admin

from .models import Notification, NotificationSetting


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "kind", "actor", "text", "read_at", "updated_at")
    list_filter  = ("kind", "read_at")
    search_fields = ("user__username", "actor__username", "text")
    readonly_fields = ("created_at", "updated_at")
    autocomplete_fields = ("user", "actor")
    ordering = ("-updated_at",)


@admin.register(NotificationSetting)
class NotificationSettingAdmin(admin.ModelAdmin):
    list_display = ("event", "channel_telegram", "channel_max", "channel_vk", "channel_email", "updated_at")
    list_editable = ("channel_telegram", "channel_max", "channel_vk", "channel_email")
    list_filter = ("channel_telegram", "channel_max", "channel_vk", "channel_email")
    readonly_fields = ("updated_at",)
    ordering = ("event",)

from django.contrib import admin

from .models import ModerationLog, StoreClick


@admin.register(StoreClick)
class StoreClickAdmin(admin.ModelAdmin):
    list_display   = ("id", "book", "store", "user", "created_at")
    list_filter    = ("store", "created_at")
    search_fields  = ("book__title", "user__username")
    date_hierarchy = "created_at"
    raw_id_fields  = ("book", "store", "user")


@admin.register(ModerationLog)
class ModerationLogAdmin(admin.ModelAdmin):
    list_display   = ("id", "action", "target_type", "target_id", "target_repr", "moderator", "created_at")
    list_filter    = ("action", "target_type", "created_at")
    search_fields  = ("target_repr", "note", "moderator__username")
    date_hierarchy = "created_at"
    raw_id_fields  = ("moderator",)
    readonly_fields = ("action", "target_type", "target_id", "target_repr",
                       "note", "moderator", "created_at")

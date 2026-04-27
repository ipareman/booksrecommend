from django.contrib import admin

from .models import Ticket


@admin.register(Ticket)
class TicketAdmin(admin.ModelAdmin):
    list_display = ("id", "kind", "status", "priority", "subject", "user", "created_at", "updated_at")
    list_filter = ("kind", "status", "priority", "created_at")
    search_fields = ("subject", "body", "target_label", "user__username")
    readonly_fields = ("created_at", "updated_at", "responded_at")

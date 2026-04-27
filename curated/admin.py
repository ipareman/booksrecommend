from django.contrib import admin

from .models import Collection, CollectionBook, CollectionComment, CollectionCommentVote, CollectionLike


class CollectionBookInline(admin.TabularInline):
    model = CollectionBook
    extra = 0


@admin.register(Collection)
class CollectionAdmin(admin.ModelAdmin):
    list_display = ("id", "title", "created_by", "is_published", "created_at")
    list_filter = ("is_published", "created_at")
    search_fields = ("title", "description", "created_by__username")
    inlines = [CollectionBookInline]


@admin.register(CollectionLike)
class CollectionLikeAdmin(admin.ModelAdmin):
    list_display = ("collection", "user", "created_at")
    search_fields = ("collection__title", "user__username")


@admin.register(CollectionComment)
class CollectionCommentAdmin(admin.ModelAdmin):
    list_display = ("collection", "user", "created_at")
    search_fields = ("collection__title", "user__username", "text")


@admin.register(CollectionCommentVote)
class CollectionCommentVoteAdmin(admin.ModelAdmin):
    list_display = ("comment", "user", "value")
    search_fields = ("comment__text", "user__username")

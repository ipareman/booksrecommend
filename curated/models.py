from django.db import models
from django.conf import settings


class Collection(models.Model):
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    cover_image = models.ImageField(upload_to="collections/", null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="collections_created",
    )
    is_published = models.BooleanField(default=False)
    order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["order", "-created_at"]

    def __str__(self):
        return self.title

    def book_count(self):
        return self.items.count()


class CollectionBook(models.Model):
    collection = models.ForeignKey(
        Collection, on_delete=models.CASCADE, related_name="items"
    )
    book = models.ForeignKey(
        "books.Book", on_delete=models.CASCADE, related_name="in_collections"
    )
    order = models.PositiveIntegerField(default=0)

    class Meta:
        unique_together = ("collection", "book")
        ordering = ["order"]

    def __str__(self):
        return f"{self.collection.title}: {self.book.title}"


class CollectionLike(models.Model):
    """«Лайк» (сохранение в избранное) подборки пользователем."""
    collection = models.ForeignKey(
        Collection, on_delete=models.CASCADE, related_name="likes"
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name="liked_collections",
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["collection", "user"],
                                    name="collection_like_unique"),
        ]
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.user} ♥ {self.collection}"


class CollectionComment(models.Model):
    collection = models.ForeignKey(
        Collection, on_delete=models.CASCADE, related_name="comments"
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name="collection_comments",
    )
    parent = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.CASCADE, related_name="replies",
    )
    text = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["created_at"]
        indexes = [
            models.Index(fields=["collection", "created_at"]),
        ]

    def __str__(self):
        return f"{self.user} → {self.collection}"


class CollectionCommentVote(models.Model):
    UP = 1
    DOWN = -1
    VALUE_CHOICES = [(UP, "+1"), (DOWN, "-1")]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name="collection_comment_votes",
    )
    comment = models.ForeignKey(
        CollectionComment, on_delete=models.CASCADE, related_name="votes",
    )
    value = models.SmallIntegerField(choices=VALUE_CHOICES)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "comment"], name="collection_comment_vote_unique"),
        ]

    def __str__(self):
        return f"{self.user} → collection comment #{self.comment_id}"

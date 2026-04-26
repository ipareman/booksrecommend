from django.contrib.auth.models import User
from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator


class Review(models.Model):
    PENDING  = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    STATUS_CHOICES = [(PENDING,"На модерации"),(APPROVED,"Одобрен"),(REJECTED,"Отклонён")]

    user       = models.ForeignKey(User, on_delete=models.CASCADE, related_name="reviews")
    book       = models.ForeignKey("books.Book", on_delete=models.CASCADE, related_name="reviews")
    rating     = models.IntegerField(validators=[MinValueValidator(1), MaxValueValidator(5)])
    text       = models.TextField(blank=True)
    status     = models.CharField(max_length=10, choices=STATUS_CHOICES, default=PENDING)
    created_at    = models.DateTimeField(auto_now_add=True)
    extracted_tag = models.CharField(max_length=80, blank=True, default="",
                    help_text="Тег, извлечённый Claude из этого отзыва")

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["user", "book"], name="review_unique")
        ]

    @property
    def stars_display(self):
        return "★" * self.rating + "☆" * (5 - self.rating)

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        _recalc(self.book)

    def delete(self, *args, **kwargs):
        book = self.book
        super().delete(*args, **kwargs)
        _recalc(book)


def _recalc(book):
    from django.db.models import Avg, Count
    stats = Review.objects.filter(book=book, status=Review.APPROVED).aggregate(
        avg=Avg("rating"), cnt=Count("id")
    )
    book.avg_rating   = round(stats["avg"] or 0.0, 2)
    book.rating_count = stats["cnt"] or 0
    book.save(update_fields=["avg_rating", "rating_count"])


class ReviewLike(models.Model):
    """Лайк («Полезно») на одобренном отзыве — один пользователь, один отзыв."""
    user   = models.ForeignKey(User, on_delete=models.CASCADE, related_name="review_likes")
    review = models.ForeignKey(Review, on_delete=models.CASCADE, related_name="likes")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "review"], name="review_like_unique")
        ]

    def __str__(self):
        return f"{self.user.username} → review #{self.review_id}"


# ═══════════════════════════════════════════════════════════════════════════════
# РЕЦЕНЗИИ (расширенные обзоры с критериями, комментариями, обложками)
# ═══════════════════════════════════════════════════════════════════════════════

class Critique(models.Model):
    PENDING  = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    STATUS_CHOICES = [(PENDING, "На модерации"), (APPROVED, "Одобрена"), (REJECTED, "Отклонена")]

    user         = models.ForeignKey(User, on_delete=models.CASCADE, related_name="critiques")
    book         = models.ForeignKey("books.Book", on_delete=models.CASCADE, related_name="critiques")
    title        = models.CharField(max_length=300)
    body         = models.TextField(help_text="Отрендеренный HTML (санитайзится перед сохранением)")
    # Для режима markdown — исходник, чтобы редактор мог открыть его обратно.
    # Для режима html (CKEditor) — остаётся пустым.
    body_source  = models.TextField(blank=True, default="",
                                    help_text="Исходник в формате markdown (если формат — markdown)")
    FORMAT_HTML     = "html"
    FORMAT_MARKDOWN = "markdown"
    FORMAT_CHOICES  = [(FORMAT_HTML, "Rich (CKEditor)"),
                       (FORMAT_MARKDOWN, "Markdown")]
    body_format  = models.CharField(
        max_length=10, choices=FORMAT_CHOICES, default=FORMAT_HTML,
        help_text="В каком редакторе автор писал рецензию",
    )
    final_rating = models.IntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(5)],
        help_text="Итоговая оценка (обязательна)",
    )
    cover_image  = models.ImageField(upload_to="critique_covers/", blank=True, null=True)
    status       = models.CharField(max_length=10, choices=STATUS_CHOICES, default=PENDING)
    extracted_tag = models.CharField(max_length=80, blank=True, default="")
    created_at   = models.DateTimeField(auto_now_add=True)
    updated_at   = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.title} — {self.user.username}"

    @property
    def stars_display(self):
        return "★" * self.final_rating + "☆" * (5 - self.final_rating)

    @property
    def criteria_avg(self):
        from django.db.models import Avg
        result = self.criteria.aggregate(avg=Avg("rating"))
        return round(result["avg"] or 0, 1)

    @property
    def body_excerpt(self):
        """Чистый текст без HTML-тегов, обрезанный до ~200 символов."""
        import re
        plain = re.sub(r"<[^>]+>", "", self.body)
        return plain[:200] + "…" if len(plain) > 200 else plain


class CritiqueCriterion(models.Model):
    critique = models.ForeignKey(Critique, on_delete=models.CASCADE, related_name="criteria")
    name     = models.CharField(max_length=100)
    rating   = models.IntegerField(validators=[MinValueValidator(1), MaxValueValidator(5)])

    class Meta:
        ordering = ["pk"]

    def __str__(self):
        return f"{self.name}: {self.rating}/5"

    @property
    def stars_display(self):
        return "★" * self.rating + "☆" * (5 - self.rating)


class CritiqueComment(models.Model):
    critique   = models.ForeignKey(Critique, on_delete=models.CASCADE, related_name="comments")
    user       = models.ForeignKey(User, on_delete=models.CASCADE, related_name="critique_comments")
    parent     = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.CASCADE, related_name="replies",
    )
    text       = models.TextField(max_length=2000)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Comment by {self.user.username} on «{self.critique.title}»"


class CritiqueCommentVote(models.Model):
    UP   = 1
    DOWN = -1
    VALUE_CHOICES = [(UP, "+1"), (DOWN, "-1")]

    user    = models.ForeignKey(User, on_delete=models.CASCADE, related_name="comment_votes")
    comment = models.ForeignKey(CritiqueComment, on_delete=models.CASCADE, related_name="votes")
    value   = models.SmallIntegerField(choices=VALUE_CHOICES)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "comment"], name="comment_vote_unique")
        ]

    def __str__(self):
        return f"{self.user.username} {'↑' if self.value > 0 else '↓'} comment #{self.comment_id}"


class CritiqueLike(models.Model):
    user     = models.ForeignKey(User, on_delete=models.CASCADE, related_name="critique_likes")
    critique = models.ForeignKey(Critique, on_delete=models.CASCADE, related_name="likes")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "critique"], name="critique_like_unique")
        ]

    def __str__(self):
        return f"{self.user.username} → critique #{self.critique_id}"

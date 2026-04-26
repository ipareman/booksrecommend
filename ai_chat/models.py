from django.db import models
from django.conf import settings


class BookChat(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="book_chats",
    )
    book = models.ForeignKey(
        "books.Book", on_delete=models.CASCADE, related_name="ai_chats"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("user", "book")

    def __str__(self):
        return f"{self.user} — {self.book}"


class BookChatMessage(models.Model):
    ROLE_CHOICES = [("user", "Пользователь"), ("assistant", "AI")]

    chat = models.ForeignKey(
        BookChat, on_delete=models.CASCADE, related_name="messages"
    )
    role = models.CharField(max_length=10, choices=ROLE_CHOICES)
    content = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return f"{self.role}: {self.content[:50]}"


class DiscoveryChat(models.Model):
    """AI-чат для поиска книг (не привязан к конкретной книге)."""
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="discovery_chats",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]

    def __str__(self):
        return f"Discovery: {self.user} ({self.created_at})"


class DiscoveryChatMessage(models.Model):
    ROLE_CHOICES = [("user", "Пользователь"), ("assistant", "AI")]

    chat = models.ForeignKey(
        DiscoveryChat, on_delete=models.CASCADE, related_name="messages"
    )
    role = models.CharField(max_length=10, choices=ROLE_CHOICES)
    content = models.TextField()
    recommended_books = models.ManyToManyField("books.Book", blank=True)
    # Метаданные для рендера карточек при перезаходе: [{book_id, reason, detailed_reason?}, ...].
    # Храним отдельно от M2M, потому что M2M не содержит per-book reason,
    # а UI показывает объяснение «почему эта книга подходит» под каждой карточкой.
    books_meta = models.JSONField(default=list, blank=True)
    # Follow-up чипы, когда AI не уверен и просит уточнить: [{"label": str, "prompt": str}, ...]
    followup_options = models.JSONField(default=list, blank=True)
    # «Не то» feedback: [{"book_id": int, "reason": str}] — учитывается при следующем запросе
    disliked_book_ids = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return f"[Discovery] {self.role}: {self.content[:50]}"

    def books_with_reasons(self):
        """
        Отдаёт список {"book": Book, "reason": str} в порядке из books_meta.
        Используется в шаблоне discovery.html при перезаходе в чат, чтобы
        сохранить исходный порядок и тексты «reason».
        """
        if not self.books_meta:
            return []
        meta_by_id = {m.get("book_id"): m.get("reason", "") for m in self.books_meta if isinstance(m, dict)}
        book_ids = [m.get("book_id") for m in self.books_meta if isinstance(m, dict) and m.get("book_id")]
        if not book_ids:
            return []
        from books.models import Book
        books_qs = Book.objects.filter(pk__in=book_ids).prefetch_related("authors")
        by_id = {b.pk: b for b in books_qs}
        out = []
        for bid in book_ids:
            b = by_id.get(bid)
            if b is None:
                continue
            out.append({"book": b, "reason": meta_by_id.get(bid, "")})
        return out


class BookContent(models.Model):
    book = models.OneToOneField(
        "books.Book", on_delete=models.CASCADE, related_name="ai_content"
    )
    content_text = models.TextField(
        help_text="Расширенное описание, краткое содержание, ключевые цитаты"
    )
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Контент: {self.book.title}"

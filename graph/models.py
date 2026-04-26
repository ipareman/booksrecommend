from django.db import models


class BookRelation(models.Model):
    RELATION_TYPES = [
        ("same_author", "Тот же автор"),
        ("same_genre", "Общие жанры"),
        ("same_series", "Одна серия"),
        ("also_read", "Также читали"),
        ("influenced_by", "Повлияла на"),
        ("response_to", "Ответ на"),
        ("similar_theme", "Похожая тема"),
        ("sequel", "Продолжение"),
        ("prequel", "Приквел"),
    ]

    book_from = models.ForeignKey(
        "books.Book", on_delete=models.CASCADE, related_name="relations_from"
    )
    book_to = models.ForeignKey(
        "books.Book", on_delete=models.CASCADE, related_name="relations_to"
    )
    relation_type = models.CharField(max_length=20, choices=RELATION_TYPES)
    is_auto = models.BooleanField(default=True)
    weight = models.FloatField(default=1.0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("book_from", "book_to", "relation_type")

    def __str__(self):
        return f"{self.book_from} → {self.book_to} ({self.relation_type})"

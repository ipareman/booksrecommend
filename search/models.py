from django.contrib.auth.models import User
from django.db import models


class SearchHistory(models.Model):
    user          = models.ForeignKey(User, null=True, blank=True,
                                      on_delete=models.CASCADE, related_name="search_history")
    query         = models.CharField(max_length=500, db_index=True)
    results_count = models.PositiveIntegerField(default=0)
    created_at    = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f'"{self.query}"'

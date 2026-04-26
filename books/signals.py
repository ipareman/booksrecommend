from django.db.models.signals import post_save
from django.dispatch import receiver
from notifications.tasks import notify_book_added
from books.tasks import extract_tags_from_description
from books.recommendations import invalidate_idf_cache


@receiver(post_save, sender="books.Book")
def book_saved(sender, instance, created, update_fields, **kwargs):
    """При добавлении новой книги — уведомить подписчиков авторов + извлечь AI-теги."""
    skip = {"avg_rating", "rating_count", "avg_price", "price_last_requested"}
    if update_fields and set(update_fields) <= skip:
        return

    if created:
        notify_book_added.delay(instance.pk)

        # Извлекаем AI-теги из описания если оно есть
        if instance.description and len(instance.description.strip()) > 30:
            extract_tags_from_description.delay(instance.pk)

    # Инвалидируем кеш IDF при любом изменении книги
    invalidate_idf_cache()

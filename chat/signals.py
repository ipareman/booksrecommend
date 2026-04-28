from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from books.models import Author, Book
from .linkify import clear_entity_link_cache


@receiver([post_save, post_delete], sender=Author)
@receiver([post_save, post_delete], sender=Book)
def clear_chat_entity_links(**kwargs):
    clear_entity_link_cache()

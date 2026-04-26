# notifications/apps.py
from django.apps import AppConfig


class NotificationsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "notifications"

    def ready(self):
        # Подключаем post_save-хендлеры: chat.ChatMessage, social.Friendship,
        # social.BookRecommendation, reviews.CritiqueComment.
        # Импорт внутри ready() — стандартный Django-паттерн, чтобы избежать
        # циклических импортов при загрузке приложений.
        try:
            from . import signals  # noqa: F401
        except Exception:
            # Не роняем старт Django, если что-то пошло не так на импорте —
            # уведомления просто не будут создаваться, приложение работает.
            import logging
            logging.getLogger(__name__).exception("notifications.signals import failed")

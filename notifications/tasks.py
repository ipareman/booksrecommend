import logging
from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task
def notify_book_added(book_id: int):
    """
    Отправить Telegram-уведомления всем подписчикам авторов новой книги.
    Запускается из сигнала post_save на Book.
    """
    from books.models import Book
    from users.models import AuthorSubscription
    from notifications.telegram import send_message
    from notifications.max import send_message as max_send_message
    from notifications.models import NotificationSetting
    from django.conf import settings

    try:
        book = Book.objects.prefetch_related("authors").get(pk=book_id)
    except Book.DoesNotExist:
        return

    author_ids = list(book.authors.values_list("id", flat=True))
    if not author_ids:
        return

    # Матрица «что включено для данного события» (кеш на 60с)
    ch = NotificationSetting.channels_for(NotificationSetting.EVENT_NEW_BOOK)

    # Подписчики с заполненным chat_id
    subs = (
        AuthorSubscription.objects
        .filter(author_id__in=author_ids)
        .select_related("user__profile", "author")
        .distinct()
    )

    site_url = settings.__dict__.get("SITE_URL", "")
    book_url  = f"{site_url}/books/{book.pk}/"

    sent_users = set()  # чтобы не слать дважды если подписан на нескольких авторов книги
    inbox_users = set()  # чтобы не создавать дубли Notification на одну книгу
    sent_max_users = set()  # параллельный трекер для MAX-канала

    # Хелпер для DB-уведомления (импорт локальный — чтобы Celery-worker не падал,
    # если notifications-таблица ещё не мигрирована).
    try:
        from notifications.helpers import emit as _emit_notification
        from notifications.models import Notification as _Notif
    except Exception:
        _emit_notification = None
        _Notif = None

    for sub in subs:
        # DB-уведомление (инбокс) — одно на пользователя на книгу, независимо от Telegram
        if _emit_notification is not None and sub.user_id not in inbox_users:
            try:
                _emit_notification(
                    user=sub.user,
                    kind=_Notif.KIND_NEW_BOOK_BY_AUTHOR,
                    actor=None,
                    target=book,
                    text=f"Новая книга у {sub.author.name}: «{book.title}»",
                    url=f"/books/{book.pk}/",
                    extra={"book_id": book.pk, "author_id": sub.author_id},
                )
                inbox_users.add(sub.user_id)
            except Exception as exc:
                logger.warning("Failed to create inbox notification for user %s: %s",
                               sub.user.username, exc)

        profile = getattr(sub.user, "profile", None)
        if not profile:
            continue

        authors_str = ", ".join(a.name for a in book.authors.all())
        text = (
            f"📚 <b>Новая книга от {sub.author.name}</b>\n\n"
            f"<b>{book.title}</b>\n"
            f"Авторы: {authors_str}\n"
        )
        if book.publication_year:
            text += f"Год: {book.publication_year}\n"
        if site_url:
            text += f"\n<a href='{book_url}'>Открыть в Строка</a>"

        # Telegram
        if ch["telegram"] and profile.telegram_chat_id and sub.user_id not in sent_users:
            ok = send_message(profile.telegram_chat_id, text)
            if ok:
                sent_users.add(sub.user_id)
                logger.info("Notified user %s via TG about book #%d", sub.user.username, book_id)
            else:
                logger.warning("Failed to notify user %s via TG", sub.user.username)

        # MAX
        if ch["max"] and profile.max_user_id and sub.user_id not in sent_max_users:
            ok = max_send_message(profile.max_user_id, text)
            if ok:
                sent_max_users.add(sub.user_id)
                logger.info("Notified user %s via MAX about book #%d", sub.user.username, book_id)
            else:
                logger.warning("Failed to notify user %s via MAX", sub.user.username)

    logger.info("Book #%d: telegram=%d, max=%d, inbox=%d",
                book_id, len(sent_users), len(sent_max_users), len(inbox_users))

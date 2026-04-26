"""
Email-уведомления как альтернатива Telegram.
Отправляются пользователям, у которых заполнен email и нет telegram_chat_id.
"""

import logging
from django.core.mail import send_mail
from django.conf import settings

logger = logging.getLogger(__name__)


def send_price_alert_email(user, book, current_price, threshold):
    """Уведомление о снижении цены книги."""
    if not user.email:
        return False
    site_url = getattr(settings, "SITE_URL", "")
    book_url = f"{site_url}/books/{book.pk}/"
    try:
        send_mail(
            subject=f"Цена снизилась: {book.title}",
            message=(
                f"Книга: {book.title}\n"
                f"Текущая цена: {current_price} руб.\n"
                f"Ваш порог: {threshold} руб.\n\n"
                f"Открыть: {book_url}"
            ),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
            fail_silently=True,
        )
        logger.info("Price alert email sent to %s for book #%d", user.email, book.pk)
        return True
    except Exception as exc:
        logger.error("Email send failed for %s: %s", user.email, exc)
        return False


def send_review_status_email(user, book, approved: bool):
    """Уведомление о результате модерации отзыва."""
    if not user.email:
        return False
    site_url = getattr(settings, "SITE_URL", "")
    book_url = f"{site_url}/books/{book.pk}/"
    status_text = "одобрен" if approved else "отклонён"
    try:
        send_mail(
            subject=f"Отзыв {status_text}: {book.title}",
            message=(
                f"Ваш отзыв на книгу \"{book.title}\" был {status_text}.\n\n"
                f"Открыть: {book_url}"
            ),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
            fail_silently=True,
        )
        return True
    except Exception as exc:
        logger.error("Email send failed for %s: %s", user.email, exc)
        return False


def send_weekly_digest_email(user, recommendations, max_books=3):
    """Еженедельный дайджест рекомендаций по email."""
    if not user.email or not recommendations:
        return False
    site_url = getattr(settings, "SITE_URL", "")
    lines = ["Ваши рекомендации на эту неделю:\n"]
    for i, item in enumerate(recommendations[:max_books], 1):
        book = item["book"]
        book_url = f"{site_url}/books/{book.pk}/"
        lines.append(f"{i}. {book.title} — {book_url}")
        if item.get("reason"):
            lines.append(f"   {item['reason']}")
    lines.append("\nХорошего чтения!")

    try:
        send_mail(
            subject="Рекомендации недели — Строка",
            message="\n".join(lines),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
            fail_silently=True,
        )
        return True
    except Exception as exc:
        logger.error("Weekly digest email failed for %s: %s", user.email, exc)
        return False

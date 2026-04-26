import logging
from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task
def send_weekly_digest():
    """
    Celery Beat: еженедельный дайджест AI-рекомендаций.
    Telegram — приоритетный канал, email — fallback.
    """
    from django.contrib.auth.models import User
    from books.ai_recommendations import load_from_cache
    from notifications.telegram import send_message
    from notifications.max import send_message as max_send_message
    from notifications.email import send_weekly_digest_email
    from notifications.models import NotificationSetting
    from django.conf import settings as conf

    site_url = getattr(conf, "SITE_URL", "")
    users = User.objects.select_related("profile").filter(is_active=True)

    ch = NotificationSetting.channels_for(NotificationSetting.EVENT_WEEKLY_DIGEST)

    sent_tg, sent_max, sent_email = 0, 0, 0
    for user in users:
        recs = load_from_cache(user.pk)
        if not recs:
            continue

        profile = getattr(user, "profile", None)
        if not profile:
            continue

        lines = ["📚 <b>Рекомендации недели</b>\n"]
        for i, item in enumerate(recs[:3], 1):
            book = item["book"]
            url = f"{site_url}/books/{book.pk}/"
            lines.append(f"{i}. <a href='{url}'>{book.title}</a>")
            if item.get("reason"):
                lines.append(f"   <i>{item['reason']}</i>")
        text = "\n".join(lines)

        delivered = False

        # Telegram
        if ch["telegram"] and profile.telegram_chat_id:
            try:
                if send_message(profile.telegram_chat_id, text):
                    sent_tg += 1
                    delivered = True
            except Exception as exc:
                logger.error("weekly_digest tg: failed for %s: %s", user.username, exc)

        # MAX
        if ch["max"] and profile.max_user_id:
            try:
                if max_send_message(profile.max_user_id, text):
                    sent_max += 1
                    delivered = True
            except Exception as exc:
                logger.error("weekly_digest max: failed for %s: %s", user.username, exc)

        # Email fallback, если ни один мессенджер не сработал
        if ch["email"] and not delivered and user.email:
            if send_weekly_digest_email(user, recs):
                sent_email += 1

    logger.info("weekly_digest: tg=%d max=%d email=%d", sent_tg, sent_max, sent_email)


@shared_task(bind=True, max_retries=1, default_retry_delay=10)
def generate_ai_recommendations_task(self, user_id: int):
    """
    Celery-задача: запускает AI-рекомендации для пользователя и кеширует результат.
    Запускается по нажатию кнопки «Обновить рекомендации» в профиле.
    """
    from django.contrib.auth.models import User
    from books.ai_recommendations import generate_ai_recommendations

    try:
        user = User.objects.get(pk=user_id)
    except User.DoesNotExist:
        logger.warning("generate_ai_recommendations_task: user %d not found", user_id)
        return {"status": "error", "message": "Пользователь не найден"}

    try:
        result = generate_ai_recommendations(user)
        logger.info("AI recs for user %d: %d books", user_id, len(result))
        return {"status": "ok", "count": len(result)}
    except Exception as exc:
        logger.error("AI recs task failed for user %d: %s", user_id, exc)
        try:
            raise self.retry(exc=exc)
        except self.MaxRetriesExceededError:
            return {"status": "error", "message": str(exc)}


@shared_task
def classify_list_sentiment(list_id: int):
    """Определить тональность списка через LLM и сохранить sentiment_tag."""
    from django.conf import settings as conf
    if not getattr(conf, "ANTHROPIC_API_KEY", ""):
        return

    from books.models import UserList
    try:
        ul = UserList.objects.get(pk=list_id)
    except UserList.DoesNotExist:
        return

    from core.llm import chat_completion
    prompt = (
        f"Пользователь создал список книг с названием: «{ul.name}»\n\n"
        "Определи тональность этого списка. Ответь ТОЛЬКО одним словом:\n"
        "- positive  (нравится, избранное, лучшее, топ, любимое)\n"
        "- negative  (не нравится, разочарования, плохое, мусор, бросил)\n"
        "- wishlist  (хочу прочитать, буду читать, план, очередь, to-read)\n"
        "- neutral   (всё остальное: прочитано, читаю, архив и т.п.)"
    )

    try:
        resp = chat_completion(
            tier="light",
            feature="sentiment",
            max_tokens=10,
            messages=[{"role": "user", "content": prompt}],
        )
        tag = (resp.choices[0].message.content or "").strip().lower()
        if tag in ("positive", "negative", "wishlist", "neutral"):
            ul.sentiment_tag = tag
            ul.save(update_fields=["sentiment_tag"])
            logger.info("List #%d «%s» → sentiment: %s", list_id, ul.name, tag)
        else:
            logger.warning("Unexpected sentiment tag '%s' for list #%d", tag, list_id)
    except Exception as exc:
        logger.error("classify_list_sentiment error for list #%d: %s", list_id, exc)

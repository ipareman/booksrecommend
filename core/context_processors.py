from django.conf import settings


def globals(request):
    site_key = getattr(settings, "RECAPTCHA_SITE_KEY", "") or getattr(
        settings, "RECAPTCHA_PUBLIC_KEY", ""
    )
    return {
        # Оба имени для обратной совместимости с разными шаблонами.
        "recaptcha_public_key": site_key,
        "recaptcha_site_key": site_key,
        "telegram_bot_username": getattr(settings, "TELEGRAM_BOT_USERNAME", ""),
        "max_bot_username":      getattr(settings, "MAX_BOT_USERNAME", ""),
    }

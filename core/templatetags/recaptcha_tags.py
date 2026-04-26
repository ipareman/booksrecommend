from django import template
from django.conf import settings
from django.utils.safestring import mark_safe

register = template.Library()


@register.simple_tag
def recaptcha_widget():
    site_key = getattr(settings, "RECAPTCHA_SITE_KEY", "")
    if not site_key:
        # reCAPTCHA не настроена — рендерим пустой hidden input
        return mark_safe('<input type="hidden" name="g-recaptcha-response" value="no-captcha">')
    return mark_safe(
        f'<div class="g-recaptcha" data-sitekey="{site_key}" data-theme="light"></div>'
        f'<script src="https://www.google.com/recaptcha/api.js" async defer></script>'
    )

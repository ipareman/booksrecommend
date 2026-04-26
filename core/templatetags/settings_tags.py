from django import template
from django.conf import settings as django_settings

register = template.Library()

@register.simple_tag
def get_setting(name, default=""):
    return getattr(django_settings, name, default)

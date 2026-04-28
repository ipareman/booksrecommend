from django import template

from chat.linkify import linkify_message_text


register = template.Library()


@register.filter
def chat_linkify(value):
    return linkify_message_text(value)

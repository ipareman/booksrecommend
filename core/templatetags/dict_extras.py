from django import template


register = template.Library()


@register.filter
def get_item(mapping, key):
    if not mapping:
        return None
    try:
        return mapping.get(key)
    except AttributeError:
        return None

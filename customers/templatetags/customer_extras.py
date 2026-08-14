from django import template

register = template.Library()


@register.filter
def mask_phone(value):
    text = str(value or '')
    if len(text) >= 7:
        return f'{text[:3]}****{text[-4:]}'
    return text

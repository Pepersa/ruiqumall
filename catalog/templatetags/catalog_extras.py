from decimal import Decimal, InvalidOperation

from django import template


register = template.Library()


@register.filter
def get_item(mapping, key):
    if not isinstance(mapping, dict):
        return ''
    return mapping.get(key, '')


@register.filter
def qty(value):
    if value in (None, ''):
        return ''
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return value
    normalized = number.normalize()
    if normalized == normalized.to_integral_value():
        return str(int(normalized))
    text = format(normalized, 'f')
    return text.rstrip('0').rstrip('.')


@register.filter
def price_or_login(value, user=None):
    """Hide price for unauthenticated users. Accepts (price, user) tuple or just price."""
    if isinstance(value, tuple):
        price, user = value
    else:
        price = value
    if user is not None and user.is_authenticated:
        if price is None:
            return '待确认'
        return f'¥{price}'
    return '登录后查看'


@register.simple_tag
def display_price(price, user=None):
    """Display price with login gate. Returns tuple (text, show_price)."""
    if user is not None and user.is_authenticated:
        if price is None:
            return ('待确认', True)
        return (f'¥{price}', True)
    return ('登录后查看', False)

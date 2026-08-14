from decimal import Decimal, InvalidOperation

CART_SESSION_KEY = 'cart'


def _parse_qty(raw_value, fallback=Decimal('0')):
    try:
        qty = Decimal(str(raw_value))
    except (InvalidOperation, TypeError):
        return fallback
    return qty if qty > 0 else fallback


def cart_item_count(request):
    cart = request.session.get(CART_SESSION_KEY, {})
    total = Decimal('0')
    for qty_text in cart.values():
        total += _parse_qty(qty_text, Decimal('0'))
    if total == total.to_integral_value():
        return int(total)
    return float(total)


def cart_context(request):
    count = cart_item_count(request)
    return {
        'cart_item_count': count,
        'cart_has_items': count > 0,
    }

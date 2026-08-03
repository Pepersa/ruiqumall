"""Cart persistence helpers.

Session-only cart gets flushed on logout, so we mirror the cart into a signed
cookie that survives logout/login cycles on the same browser.
"""
from django.core import signing


CART_PERSIST_COOKIE = 'cart_persist'
SIGNER_SALT = 'cart-persistence-v1'


def save_cart_cookie(response, cart):
    """Attach a signed cookie with the current cart contents."""
    if not cart:
        response.delete_cookie(CART_PERSIST_COOKIE)
        return response
    signed = signing.dumps(cart, salt=SIGNER_SALT)
    response.set_cookie(
        CART_PERSIST_COOKIE,
        signed,
        max_age=60 * 60 * 24 * 30,  # 30 天
        httponly=True,
        samesite='Lax',
    )
    return response


def load_cart_cookie(request):
    """Return the cart dict stored in the persistence cookie, or None."""
    raw = request.COOKIES.get(CART_PERSIST_COOKIE)
    if not raw:
        return None
    try:
        cart = signing.loads(raw, salt=SIGNER_SALT, max_age=60 * 60 * 24 * 30)
    except (signing.BadSignature, signing.SignatureExpired, ValueError):
        return None
    if not isinstance(cart, dict):
        return None
    return cart


def merge_cart(session_cart, cookie_cart):
    """Merge cookie cart into session cart, summing quantities for overlap."""
    for sku_id, qty_text in (cookie_cart or {}).items():
        existing = session_cart.get(sku_id, '0')
        try:
            from decimal import Decimal
            session_cart[sku_id] = str(Decimal(str(existing)) + Decimal(str(qty_text)))
        except Exception:
            session_cart[sku_id] = qty_text
from decimal import Decimal, InvalidOperation
from urllib.parse import urlencode

from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from catalog.models import SKU
from catalog.pricing import resolve_unit_price_simple

from .context_processors import cart_item_count


CART_SESSION_KEY = 'cart'


def _get_cart(request):
    return request.session.setdefault(CART_SESSION_KEY, {})


def _parse_qty(raw_value, fallback=Decimal('1')):
    try:
        qty = Decimal(str(raw_value))
    except (InvalidOperation, TypeError):
        return fallback
    return qty if qty > 0 else fallback


def _normalize_qty(sku, qty):
    qty = max(qty, sku.moq)
    step = sku.order_step or Decimal('1')
    if step > 0:
        steps = ((qty - sku.moq) / step).to_integral_value(rounding='ROUND_CEILING')
        qty = sku.moq + steps * step
    return qty


def _wants_json(request):
    return request.headers.get('X-Requested-With') == 'XMLHttpRequest'


def _cart_redirect(request):
    next_url = request.POST.get('next', '').strip()
    if next_url:
        return redirect(next_url)
    return redirect('cart:detail')


def cart_items(request):
    cart = _get_cart(request)
    sku_ids = [int(sku_id) for sku_id in cart.keys()]
    skus = SKU.objects.filter(pk__in=sku_ids).select_related('product')
    sku_map = {str(sku.pk): sku for sku in skus}
    customer = getattr(request.user, 'customer', None) if request.user.is_authenticated else None
    items = []
    total = Decimal('0')
    for sku_id, qty_text in cart.items():
        sku = sku_map.get(str(sku_id))
        if not sku:
            continue
        qty = _parse_qty(qty_text)
        unit_price = resolve_unit_price_simple(customer, sku, qty) if customer else sku.price
        amount = unit_price * qty if unit_price is not None else None
        if amount is not None:
            total += amount
        items.append({'sku': sku, 'qty': qty, 'amount': amount, 'unit_price': unit_price})
    return items, total


@require_POST
def add_to_cart(request, sku_id):
    sku = get_object_or_404(SKU.objects.select_related('product'), pk=sku_id)
    if not request.user.is_authenticated:
        login_url = f"{reverse('accounts:login')}?{urlencode({'next': sku.product.get_absolute_url()})}"
        if _wants_json(request):
            return JsonResponse({'ok': False, 'redirect': login_url}, status=401)
        messages.info(request, '请先注册或登录后再加入购物车。')
        return redirect(login_url)
    if not sku.can_add_to_cart:
        error = '该 SKU 当前不可加入购物车，请联系销售确认。'
        if _wants_json(request):
            return JsonResponse({'ok': False, 'error': error}, status=400)
        messages.error(request, error)
        return redirect(sku.product.get_absolute_url())
    qty = _normalize_qty(sku, _parse_qty(request.POST.get('qty'), sku.moq))
    cart = _get_cart(request)
    existing = _parse_qty(cart.get(str(sku.pk), ''), Decimal('0'))
    cart[str(sku.pk)] = str(existing + qty)
    request.session.modified = True

    if _wants_json(request):
        return JsonResponse(
            {
                'ok': True,
                'cart_count': cart_item_count(request),
                'image_url': sku.product.display_image_url,
                'product_name': sku.display_name,
            }
        )

    referer = request.META.get('HTTP_REFERER')
    if referer:
        return redirect(referer)
    return redirect(sku.product.get_absolute_url())


def cart_detail(request):
    items, total = cart_items(request)
    return render(request, 'cart/detail.html', {'items': items, 'total': total})


@require_POST
def update_cart_item(request, sku_id):
    sku = get_object_or_404(SKU, pk=sku_id)
    cart = _get_cart(request)
    normalized_qty = None
    if str(sku.pk) in cart:
        normalized_qty = _normalize_qty(sku, _parse_qty(request.POST.get('qty'), sku.moq))
        cart[str(sku.pk)] = str(normalized_qty)
        request.session.modified = True
        if not _wants_json(request):
            messages.success(request, '购物车已更新。')
    if _wants_json(request):
        item_exists = str(sku.pk) in cart
        return JsonResponse(
            {
                'ok': item_exists,
                'qty': str(normalized_qty) if normalized_qty is not None else None,
                'cart_count': cart_item_count(request),
            },
            status=200 if item_exists else 404,
        )
    return _cart_redirect(request)


@require_POST
def remove_cart_item(request, sku_id):
    cart = _get_cart(request)
    cart.pop(str(sku_id), None)
    request.session.modified = True
    messages.success(request, '已删除购物车商品。')
    return _cart_redirect(request)

# Create your views here.

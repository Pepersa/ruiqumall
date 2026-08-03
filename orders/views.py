from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render

from accounts.forms import ShippingAddressForm
from accounts.services import ensure_user_profile, sync_customer_from_profile
from cart.views import CART_SESSION_KEY, cart_items

from .forms import OrderConfirmForm
from .models import Order, OrderItem
from catalog.pricing import resolve_unit_price


def get_default_shipping_address(user):
    address = user.shipping_addresses.filter(is_default=True).first()
    if address is None:
        address = user.shipping_addresses.first()
    return address


def confirm_initial(user, address_id=''):
    initial = {}
    address = None
    if address_id:
        address = user.shipping_addresses.filter(pk=address_id).first()
    if address is None:
        address = get_default_shipping_address(user)
    if address:
        initial['saved_address'] = str(address.pk)
        initial.update(
            {
                'receiver_name': address.receiver_name,
                'receiver_mobile': address.receiver_mobile,
                'receiver_state': address.receiver_state,
                'receiver_city': address.receiver_city,
                'receiver_district': address.receiver_district,
                'receiver_address': address.receiver_address,
            }
        )
    return initial


def enrich_order_data(user, data):
    profile = ensure_user_profile(user)
    payload = data.copy()
    payload.pop('saved_address', None)
    payload['company_name'] = profile.company_name.strip() or user.username
    payload['tax_no'] = profile.tax_no
    payload['email'] = user.email
    payload['contact_name'] = profile.name.strip() or user.username
    payload['mobile'] = profile.phone.strip()
    payload['invoice_info'] = ''
    payload['expected_delivery_date'] = None
    return payload


def resolve_checkout_customer(user, data):
    customer = sync_customer_from_profile(user)
    customer.company_name = data['company_name']
    customer.tax_no = data.get('tax_no', '')
    customer.contact_name = data['contact_name']
    customer.mobile = data['mobile']
    customer.email = data.get('email', '')
    customer.save()
    return customer


@transaction.atomic
def create_order_from_cart(request, data):
    items, _total = cart_items(request)
    if not items:
        return None

    customer = resolve_checkout_customer(request.user, data)
    order = Order.objects.create(
        customer=customer,
        receiver_name=data['receiver_name'],
        receiver_mobile=data['receiver_mobile'],
        receiver_state=data.get('receiver_state', ''),
        receiver_city=data.get('receiver_city', ''),
        receiver_district=data.get('receiver_district', ''),
        receiver_address=data['receiver_address'],
        invoice_info=data.get('invoice_info', ''),
        buyer_message=data.get('buyer_message', ''),
        expected_delivery_date=data.get('expected_delivery_date'),
        total_amount=Decimal('0'),
    )
    for item in items:
        sku = item['sku']
        unit_price, price_source, price_record_id = resolve_unit_price(customer, sku, item['qty'])
        OrderItem.objects.create(
            order=order,
            product=sku.product,
            sku=sku,
            snapshot_product_name=sku.display_name,
            snapshot_sku_code=sku.internal_sku_code,
            snapshot_jst_sku_id=sku.jst_sku_id or sku.internal_sku_code,
            snapshot_shop_sku_id=sku.shop_sku_id or sku.internal_sku_code,
            properties_value=sku.sku_attribute_text,
            unit_price=unit_price,
            qty=item['qty'],
            price_source=price_source,
            snapshot_customer_price_id=price_record_id,
            remark='价格待确认' if unit_price is None else '',
        )
    order.recalculate_total()
    request.session[CART_SESSION_KEY] = {}
    request.session.modified = True
    return order


@login_required
def confirm_order(request):
    items, total = cart_items(request)
    if not items:
        messages.error(request, '购物车为空，请先选择商品。')
        return redirect('cart:detail')

    addresses = list(request.user.shipping_addresses.all())
    selected_address_id = request.GET.get('address', '').strip()
    selected_address = None

    if request.method == 'POST':
        form = OrderConfirmForm(request.user, request.POST)
        if form.is_valid():
            try:
                order = create_order_from_cart(request, enrich_order_data(request.user, form.order_payload()))
            except Exception:
                import logging, traceback
                logging.getLogger('orders').error('create_order_from_cart failed: %s', traceback.format_exc())
                messages.error(request, '订单提交失败，请稍后再试或联系客服。')
                return redirect('cart:detail')
            messages.success(request, '订单已提交，公司将确认库存和交期。')
            return redirect(order.get_absolute_url())
    else:
        if not selected_address_id:
            initial = confirm_initial(request.user)
            selected_address_id = initial.get('saved_address', '')
        else:
            initial = confirm_initial(request.user, selected_address_id)
        form = OrderConfirmForm(request.user, initial=initial)

    if selected_address_id:
        selected_address = request.user.shipping_addresses.filter(pk=selected_address_id).first()
    if selected_address is None:
        selected_address = get_default_shipping_address(request.user)
    if selected_address and not selected_address_id:
        selected_address_id = str(selected_address.pk)

    return render(
        request,
        'orders/confirm.html',
        {
            'form': form,
            'address_form': ShippingAddressForm(),
            'items': items,
            'total': total,
            'addresses': addresses,
            'selected_address': selected_address,
            'selected_address_id': selected_address_id,
        },
    )


def order_detail(request, order_no):
    order = get_object_or_404(Order.objects.select_related('customer').prefetch_related('items'), order_no=order_no)
    mobile = request.GET.get('mobile', '').strip() or request.POST.get('mobile', '').strip()
    verified = request.user.is_staff
    if not verified and request.user.is_authenticated and order.customer.user_id == request.user.id:
        verified = True
    if not verified and mobile and mobile == order.receiver_mobile:
        verified = True
    return render(request, 'orders/detail.html', {'order': order, 'verified': verified, 'mobile': mobile})

# Create your views here.

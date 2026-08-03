from customers.models import Customer

from orders.models import Order

from .models import UserProfile


def ensure_user_profile(user):
    profile, _ = UserProfile.objects.get_or_create(user=user)
    return profile


def sync_customer_from_profile(user):
    profile = ensure_user_profile(user)
    company_name = profile.company_name.strip() or user.username
    contact_name = profile.name.strip() or user.username
    mobile = profile.phone.strip()
    defaults = {
        'company_name': company_name,
        'contact_name': contact_name,
        'mobile': mobile,
        'email': user.email or '',
        'tax_no': profile.tax_no,
    }
    customer, created = Customer.objects.get_or_create(user=user, defaults=defaults)
    if not created:
        for field, value in defaults.items():
            setattr(customer, field, value)
        customer.save(update_fields=list(defaults.keys()))
    return customer


def user_orders(user):
    if not user.is_authenticated:
        return Order.objects.none()
    customer = getattr(user, 'customer', None)
    if customer is None:
        return Order.objects.none()
    return customer.orders.select_related('customer').prefetch_related('items')

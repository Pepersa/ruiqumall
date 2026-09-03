from django.db.models import Count, Sum

from catalog.models import SKU
from orders.models import Order, OrderItem


def purchase_history_data(user, top_n=12, recent_n=20):
    """
    返回历史采购页所需数据：
    - top_skus:  购买频次最高的 N 个 SKU（附统计数据）
    - recent_orders: 最近 N 笔有效订单
    """
    if not user.is_authenticated:
        return None, None

    customer = getattr(user, 'customer', None)
    if not customer:
        return None, None

    # 排除草稿和已取消的订单
    _exclude = {Order.Status.DRAFT, Order.Status.CANCELLED}

    # Top-N 常购 SKU：按独立订单数排序（相同则按总采购量）
    top_items = (
        OrderItem.objects
        .filter(
            order__customer=customer,
            order__status__in=[
                Order.Status.PENDING_COMPANY_CONFIRM,
                Order.Status.PENDING_CUSTOMER_CONFIRM,
                Order.Status.PENDING_JST_EXPORT,
                Order.Status.EXPORTED,
                Order.Status.JST_ERROR,
                Order.Status.ACCEPTED,
                Order.Status.SHIPPED,
                Order.Status.COMPLETED,
            ],
            sku__isnull=False,
        )
        .values('sku')
        .annotate(
            order_count=Count('order', distinct=True),
            total_qty=Sum('qty'),
        )
        .order_by('-order_count', '-total_qty')[:top_n]
    )

    sku_ids = [item['sku'] for item in top_items]
    sku_map = {sku.pk: sku for sku in SKU.objects.filter(pk__in=sku_ids).select_related('product')}

    top_skus = []
    for item in top_items:
        sku = sku_map.get(item['sku'])
        if sku:
            item['sku_obj'] = sku
            top_skus.append(item)

    # 最近 N 笔订单
    recent_orders = (
        customer.orders
        .exclude(status__in=_exclude)
        .prefetch_related('items')
        .order_by('-created_at')[:recent_n]
    )

    return top_skus, recent_orders

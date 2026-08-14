"""客户 × SKU 单价解析服务。

下单与购物车渲染统一调用 `resolve_unit_price`，确保用户在三个页面看到的是同一价格。

优先级：
1. CustomerSKUPrice 命中（is_active + 有效期内 + 数量在阶梯区间内）
2. SKU.price（默认标价）
3. None（表示「价格待确认」）
"""
from datetime import date
from decimal import Decimal

from django.db.models import Q


def resolve_unit_price(customer, sku, qty=None, today=None):
    """返回 (unit_price: Decimal|None, source: str, price_record_id: int|None).

    source 取值：`customer_price` / `sku_default` / `unpriced`.
    """
    if sku is None:
        return None, 'unpriced', None
    today = today or date.today()
    qty = qty if qty is not None else Decimal('0')
    if customer is not None:
        from .models import CustomerSKUPrice

        candidates = CustomerSKUPrice.objects.filter(
            customer=customer,
            sku=sku,
            is_active=True,
        )
        candidates = candidates.filter(
            Q(valid_from__isnull=True) | Q(valid_from__lte=today)
        ).filter(
            Q(valid_to__isnull=True) | Q(valid_to__gte=today)
        ).filter(
            Q(min_qty__isnull=True) | Q(min_qty__lte=qty)
        ).filter(
            Q(max_qty__isnull=True) | Q(max_qty__gte=qty)
        )
        # 同时段多档时：先比阶梯起点大小（更精细的阶梯优先），再比创建时间（最新优先）
        record = candidates.order_by('-min_qty', '-created_at').first()
        if record is not None:
            return record.price, 'customer_price', record.pk
    if sku.price is not None:
        return sku.price, 'sku_default', None
    return None, 'unpriced', None


def resolve_unit_price_simple(customer, sku, qty=None, today=None):
    """只返回价格 Decimal|None，忽略来源 — 用于购物车金额快速合计。"""
    price, _, _ = resolve_unit_price(customer, sku, qty, today)
    return price

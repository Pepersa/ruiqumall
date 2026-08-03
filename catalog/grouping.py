"""产品列表按「款式」聚合 —— 帮助把同款不同色号 SKU 拼到同一张 Product 卡上。

历史数据约定：
- `Product.style_code` 常以色号结尾，例如 `BOTNY-B1088-0825`、`BOTNY-B1088-c3`。
- 列表页希望每张 Product 卡上额外展示「同款所有色号」+ 「115 个同类型产品」标识。

主型号提取（按优先级）：
1. `Product.name` 正则 `([A-Z]{0,3}-?\d{3,4}[A-Z]?)` 命中 → 例如 `B-1088`。
2. 回退 `style_code` 去掉最后一个 `-` 后剩余段 → 例如 `BOTNY-B1088`。
3. 都没则按 Product pk 单独成组。
"""
import re
from collections import defaultdict

from .models import PublishStatus, SKU


_NAME_MODEL_PATTERN = re.compile(r'([A-Z]{0,3}-?\d{3,4}[A-Z]?)')


def _from_name(name):
    if not name:
        return ''
    match = _NAME_MODEL_PATTERN.search(name)
    return match.group(1) if match else ''


def _from_style(style_code):
    if not style_code:
        return ''
    if '-' not in style_code:
        return style_code
    return style_code.rsplit('-', 1)[0]


def _from_manufacturer_model(manufacturer_model):
    """历史数据约定：manufacturer_model 已经是更精细的型号（如「净味120」「专时时丽」）。

    直接用作 group_key，避免被 style_code 大段前缀盖住。
    """
    if not manufacturer_model:
        return ''
    return manufacturer_model.strip()


def _group_key(product):
    # 优先用 manufacturer_model + product.name 组合：
    # 同型号且同产品名才算同一系列（"内墙乳胶漆"≠"内墙面漆"）。
    name_part = product.name.strip() if product.name else ''
    mfr_part = getattr(product, 'manufacturer_model', None) or ''
    if mfr_part and name_part:
        return f'{mfr_part.strip()}||{name_part}'
    if mfr_part:
        return mfr_part.strip()
    name_key = _from_name(product.name)
    if name_key:
        return name_key
    style_key = _from_style(product.style_code)
    if style_key:
        return style_key
    return f'__solo__{product.pk}'


def build_style_peer_map(products):
    """把一组 Product 按款式聚合，返回：

        {
            'B-1088': [sku_for_product_1, sku_for_product_2, ...],  # 所有色号 SKU
            ...
        }

    返回的 SKU 列表已排序，便于卡片色块展示。
    """
    buckets = defaultdict(list)
    for product in products:
        buckets[_group_key(product)].append(product)

    result = {}
    for key, products_in_group in buckets.items():
        sku_qs = SKU.objects.filter(
            product__in=products_in_group,
            status=PublishStatus.PUBLISHED,
        ).order_by('product__style_code', 'attributes', 'internal_sku_code')
        result[key] = list(sku_qs)
    return result


def collapse_products_by_style(products):
    """把按通用字段排序的 Product 列表折叠成「同款代表 Product」列表。

    排序语义：
    - 同款内仅保留当前顺序中最靠前的 Product。
    - 跨款时维持原顺序（继承调用方 `ORDER BY`）。

    返回类型：list[Product]
    """
    seen_keys = set()
    result = []
    for product in products:
        key = _group_key(product)
        if key in seen_keys:
            continue
        seen_keys.add(key)
        result.append(product)
    return result
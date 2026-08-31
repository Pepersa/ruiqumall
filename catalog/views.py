import mimetypes
import re
from pathlib import Path

from django.http import FileResponse, Http404
from django.db.models import Count, Exists, OuterRef, Prefetch, Q, Value, Case, IntegerField, Sum, When
from django.db.models.functions import Coalesce
from django.core.paginator import Paginator
from django.views.generic import DetailView, ListView, TemplateView

from .grouping import _group_key, build_style_peer_map, collapse_products_by_style
from .models import (
    BrandOrder, Category, CategoryAttribute, HomeBrand, HomeCategory, HomeScene, Product, PublishStatus, SKU,
)
from .product_images import (
    IMAGE_EXTENSIONS,
    product_image_gallery,
    product_image_root,
    product_main_image_url,
)


UNCATEGORIZED_SLUG = 'uncategorized'

# 保赐利喷漆色号提取: "保赐利（BOTNY） 自动喷漆 B-1088 0825新五征蓝 200g/400mL" -> "0825"
# 注意：COLOR_CODE_RE 仅适用于名字含色号前缀的产品；其他 group（如立邦内墙面漆）
# 同 group 内不靠 color_code 区分样式，需在调用处判断 name 是否带色号前缀再使用。
COLOR_CODE_RE = re.compile(r'B-1088\s+([A-Za-z0-9]+)')


def _extract_color_code(name):
    m = COLOR_CODE_RE.search(name)
    return m.group(1) if m else None


_HAS_COLOR_CODE = re.compile(r'B-1088\s+[A-Za-z0-9]+')


def _has_color_code_marker(name):
    """名字里是否含 B-1088 XXXX 这种色号前缀；只对这种产品做色号去重，避免误伤其他 group。"""
    return bool(name and _HAS_COLOR_CODE.search(name))

SORT_OPTIONS = {
    'default': ('sort_order', 'name', 'id'),
}


def is_displayable_category(category):
    return bool(category) and category.slug != UNCATEGORIZED_SLUG


def root_categories():
    return (
        Category.objects.filter(is_active=True, parent__isnull=True)
        .exclude(slug=UNCATEGORIZED_SLUG)
        .prefetch_related('children__children')
        .order_by('sort_order', 'name')
    )


def decorate_products_for_card(products):
    """给 product 列表补全 product_card.html 需要的展示属性：

    - `base_sku` / `main_image_url`：价格 / 按钮 / 主图
    - `peer_skus` / `style_model_label`：同款徽标

    内部使用 in-place 写属性，避免新建对象。
    """
    product_list = list(products)
    if not product_list:
        return product_list
    style_peers = build_style_peer_map(product_list)
    for product in product_list:
        # 兜底：没 prefetch_related 时补一次
        if not hasattr(product, 'quick_skus'):
            product.quick_skus = list(
                product.skus.filter(status=PublishStatus.PUBLISHED).order_by('internal_sku_code')
            )
        category_attributes = product.category.effective_attributes() if product.category else []
        product.base_sku = base_sku_for_product(product.quick_skus, category_attributes)
        product.main_image_url = product_main_image_url(product, product.base_sku)
        # 「同类型产品」徽章显示同系列 SKU 总数。
        # 色号变体通常挂在同一 Product 下，把当前产品的色号 SKU 也算入，
        # 否则 pk=522 这类单产品系列永远不显示徽章。
        product.peer_skus = list(style_peers.get(_group_key(product), []))
        product.style_model_label = _group_key(product)
    return product_list


def selected_category_from_slug(slug):
    if not slug:
        return None
    return Category.objects.filter(slug=slug, is_active=True).first()


def attribute_param(code):
    return f'attr_{code}'


def attribute_values(skus, code, limit=80):
    values = []
    seen = set()
    for attributes in skus.exclude(attributes={}).values_list('attributes', flat=True):
        if not isinstance(attributes, dict):
            continue
        value = attributes.get(code)
        if value in (None, '') or value in seen:
            continue
        seen.add(value)
        values.append(value)
        if len(values) >= limit:
            break
    return sorted(values, key=str)


def natural_value_key(value):
    """Sort values in human order (2 before 10), with blanks last."""
    text = str(value or '').strip()
    parts = re.split(r'(\d+(?:\.\d+)?)', text.casefold())
    return (not text, tuple((0, float(part)) if re.fullmatch(r'\d+(?:\.\d+)?', part) else (1, part) for part in parts))


def base_sku_for_product(skus, attributes):
    attribute_codes = [attribute.code for attribute in attributes]

    def sort_key(sku):
        values = sku.attributes if isinstance(sku.attributes, dict) else {}
        return (
            tuple(natural_value_key(values.get(code)) for code in attribute_codes),
            natural_value_key(sku.sku_attribute_text),
            sku.internal_sku_code,
        )

    return min(skus, key=sort_key, default=None)


def _find_hit_sku(product, keywords):
    """根据搜索关键词，从产品的 SKU 中找到最匹配的 SKU。

    优先级：关键词命中 SKU 字段（color/sku_attribute_text/internal_sku_code/
    jst_sku_id/package_spec/attributes）的次数越多越靠前；次数相同时按
    internal_sku_code 排序取第一个。返回 SKU 对象或 None。
    """
    if not keywords:
        return None
    candidates = []
    for sku in getattr(product, 'quick_skus', []):
        if not sku.status == PublishStatus.PUBLISHED:
            continue
        fields = [
            sku.color or '',
            sku.sku_attribute_text or '',
            sku.internal_sku_code or '',
            sku.jst_sku_id or '',
            sku.package_spec or '',
        ]
        attr_text = ''
        if isinstance(sku.attributes, dict):
            attr_text = ' '.join(str(v) for v in sku.attributes.values() if v not in (None, ''))
        fields.append(attr_text)
        haystack = ' '.join(fields).casefold()
        score = sum(1 for kw in keywords if kw.casefold() in haystack)
        if score > 0:
            candidates.append((score, sku.internal_sku_code or '', sku))
    if not candidates:
        return None
    candidates.sort(key=lambda c: (-c[0], c[1]))
    return candidates[0][2]


def pagination_items(current, total):
    if total <= 7:
        return list(range(1, total + 1))
    if current <= 4:
        return [1, 2, 3, 4, 5, 'ellipsis', total]
    if current >= total - 3:
        return [1, 'ellipsis', total - 4, total - 3, total - 2, total - 1, total]
    return [1, 'ellipsis-left', current - 1, current, current + 1, 'ellipsis-right', total]


class HomeView(TemplateView):
    template_name = 'catalog/home.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['category_tree'] = root_categories()
        context['home_categories'] = list(
            HomeCategory.objects.filter(is_active=True)
            .select_related('category')
            .order_by('sort_order', 'id')
        )
        context['home_scenes'] = list(
            HomeScene.objects.filter(is_active=True)
            .order_by('sort_order', 'id')
        )
        context['home_brands'] = list(
            HomeBrand.objects.filter(is_active=True).order_by('sort_order', 'id')
        )
        return context


class HomeSceneView(DetailView):
    model = HomeScene
    template_name = 'catalog/home_scene.html'
    context_object_name = 'scene'
    slug_field = 'slug'
    slug_url_kwarg = 'slug'

    def get_queryset(self):
        return HomeScene.objects.filter(is_active=True)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['scene_products'] = decorate_products_for_card(self.object.active_products)
        context['category_tree'] = root_categories()
        return context


class ProductListView(ListView):
    template_name = 'catalog/product_list.html'
    context_object_name = 'products'
    paginate_by = 20
    page_size_options = (10, 20, 50)

    def get_paginate_by(self, queryset):
        try:
            page_size = int(self.request.GET.get('page_size', self.paginate_by))
        except (TypeError, ValueError):
            return self.paginate_by
        return page_size if page_size in self.page_size_options else self.paginate_by

    def get_queryset(self):
        queryset = Product.objects.filter(status=PublishStatus.PUBLISHED).select_related('category')
        q = self.request.GET.get('q', '').strip()
        category_slug = self.request.GET.get('category', '').strip()
        brand = self.request.GET.get('brand', '').strip()
        color = self.request.GET.get('color', '').strip()
        package_spec = self.request.GET.get('package_spec', '').strip()
        stock_status = self.request.GET.get('stock_status', '').strip()
        self.selected_category = selected_category_from_slug(category_slug)

        if q:
            # 多关键词以空格分隔。多关键词同时出现时，按「匹配关键词数」过滤 + 排序，
            # 避免单关键词命中把无关产品拉入（例如「三和 手摇自动喷漆 国标色」
            # 只保留同时命中 ≥2 个关键词的产品，「三和」单关键词命中的整条产品线会被剔除）。
            self.search_keywords = [w for w in q.split() if w]
            n_keywords = len(self.search_keywords)
            combined = Q()
            for kw in self.search_keywords:
                kw_q = (
                    Q(name__icontains=kw)
                    | Q(alias__icontains=kw)
                    | Q(cas_no__icontains=kw)
                    | Q(style_code__icontains=kw)
                    | Q(brand__icontains=kw)
                    | Q(manufacturer_model__icontains=kw)
                    | Q(skus__internal_sku_code__icontains=kw)
                    | Q(skus__jst_sku_id__icontains=kw)
                    | Q(skus__sku_attribute_text__icontains=kw)
                    | Q(skus__color__icontains=kw)
                    | Q(skus__capacity__icontains=kw)
                    | Q(skus__package_spec__icontains=kw)
                    | Q(skus__attributes__icontains=kw)
                )
                combined |= kw_q
            queryset = queryset.filter(combined)
            # 兜底过滤：至少一个关键词命中产品身份字段（name/alias/brand/
            # manufacturer_model），避免纯 SKU 编码/色号把无关产品拉入。
            identity_field_q = Q()
            for kw in self.search_keywords:
                identity_field_q |= (
                    Q(name__icontains=kw)
                    | Q(alias__icontains=kw)
                    | Q(brand__icontains=kw)
                    | Q(manufacturer_model__icontains=kw)
                    | Q(style_code__icontains=kw)
                    | Q(cas_no__icontains=kw)
                )
            queryset = queryset.filter(identity_field_q)

            # 统计每个产品**实际匹配了几个不同关键词**。
            # 每个关键词构造一个 Case：产品级字段命中 或 任一 SKU 命中 → 1，否则 0；
            # 用 Exists 子查询做 SKU 命中检测，避免 JOIN 翻倍。最后把这些 Case 直接相加，
            # 得到 0..N 的「命中关键词数」。
            per_keyword_cases = []
            for kw in self.search_keywords:
                sku_match_subq = SKU.objects.filter(product_id=OuterRef('pk')).filter(
                    Q(internal_sku_code__icontains=kw)
                    | Q(jst_sku_id__icontains=kw)
                    | Q(sku_attribute_text__icontains=kw)
                    | Q(color__icontains=kw)
                    | Q(capacity__icontains=kw)
                    | Q(package_spec__icontains=kw)
                    | Q(attributes__icontains=kw)
                )
                product_match_q = (
                    Q(name__icontains=kw)
                    | Q(alias__icontains=kw)
                    | Q(brand__icontains=kw)
                    | Q(manufacturer_model__icontains=kw)
                    | Q(cas_no__icontains=kw)
                    | Q(style_code__icontains=kw)
                )
                per_keyword_cases.append(
                    Case(
                        When(product_match_q | Exists(sku_match_subq), then=Value(1)),
                        default=Value(0),
                        output_field=IntegerField(),
                    )
                )
            matched_keyword_count_expr = Value(0)
            for case_expr in per_keyword_cases:
                matched_keyword_count_expr = matched_keyword_count_expr + case_expr
            queryset = queryset.annotate(matched_keyword_count=matched_keyword_count_expr)

            # 多关键词严格过滤：
            # - 1 个关键词：保留任一字段命中（与原行为一致）
            # - ≥2 个关键词：要求**全部命中**（避免「三和 手摇自动喷漆 国标色」
            #   这种查询被「三和」单关键词命中整条产品线，也避免属性里恰好含
            #   「国标色」字样的产品被混入）。
            #   如果查询词超过 4 个，则放宽到 N-1（容忍 1 个错字/弱关键词）。
            if n_keywords <= 1:
                min_match = 1
            elif n_keywords == 2:
                min_match = 2
            elif n_keywords == 3:
                min_match = 3
            else:
                min_match = n_keywords - 1
            queryset = queryset.filter(matched_keyword_count__gte=min_match)

            # 多层级相关性打分：
            # - SKU 编码精确匹配 / 开头匹配：最高分（用户多半在搜具体型号）
            # - 产品名 / 品牌 / 制造商型号开头匹配：高
            # - 包含匹配：中
            # - 颜色 / 容量 / 包规命中：低
            when_clauses = []
            for kw in self.search_keywords:
                # SKU 内部编码开头匹配（最常见：用户拷贝一段 SKU 前缀）
                when_clauses.append(When(skus__internal_sku_code__istartswith=kw, then=80))
                # SKU 内部编码精确包含
                when_clauses.append(When(skus__internal_sku_code__iexact=kw, then=100))
                when_clauses.append(When(skus__internal_sku_code__icontains=kw, then=40))
                # 产品名 / 别名开头匹配
                when_clauses.append(When(Q(name__istartswith=kw) | Q(alias__istartswith=kw), then=70))
                # 产品名 / 别名包含
                when_clauses.append(When(Q(name__icontains=kw) | Q(alias__icontains=kw), then=30))
                # 品牌精确 / 开头 / 包含
                when_clauses.append(When(brand__iexact=kw, then=90))
                when_clauses.append(When(brand__istartswith=kw, then=60))
                when_clauses.append(When(brand__icontains=kw, then=25))
                # 制造商型号
                when_clauses.append(When(manufacturer_model__istartswith=kw, then=55))
                when_clauses.append(When(manufacturer_model__icontains=kw, then=25))
                # CAS / style_code
                when_clauses.append(When(cas_no__icontains=kw, then=50))
                when_clauses.append(When(style_code__icontains=kw, then=45))
                # SKU 其他属性
                when_clauses.append(When(skus__color__icontains=kw, then=15))
                when_clauses.append(When(skus__capacity__icontains=kw, then=15))
                when_clauses.append(When(skus__package_spec__icontains=kw, then=10))
                when_clauses.append(When(skus__sku_attribute_text__icontains=kw, then=10))
                when_clauses.append(When(skus__attributes__icontains=kw, then=10))

            score = Coalesce(Sum(
                Case(*when_clauses, default=0, output_field=IntegerField()),
            ), 0)
            queryset = queryset.annotate(relevance_score=score)
        self.search_keywords = getattr(self, 'search_keywords', [])
        if self.selected_category:
            queryset = queryset.filter(category_id__in=self.selected_category.descendant_ids())
        if brand:
            queryset = queryset.filter(brand=brand)
        if color:
            queryset = queryset.filter(skus__color=color)
        if package_spec:
            queryset = queryset.filter(skus__package_spec=package_spec)
        if stock_status:
            queryset = queryset.filter(skus__stock_status=stock_status)

        if self.selected_category:
            for attribute in self.selected_category.effective_attributes():
                value = self.request.GET.get(attribute_param(attribute.code), '').strip()
                if value:
                    queryset = queryset.filter(**{f'skus__attributes__{attribute.code}': value})

        self.sort = self.request.GET.get('sort', 'default')
        if self.sort not in SORT_OPTIONS:
            self.sort = 'default'

        order_clauses = list(SORT_OPTIONS[self.sort])
        if getattr(self, 'search_keywords', []):
            # 搜索时按「命中关键词数 → 相关性 → 默认排序」排，命中关键词数最多的产品排在最前。
            order_clauses = ['-matched_keyword_count', '-relevance_score'] + order_clauses

        queryset = (
            queryset.annotate(sku_count=Count('skus', distinct=True))
            .distinct()
            .order_by(*order_clauses)
            .prefetch_related(
                Prefetch(
                    'skus',
                    queryset=SKU.objects.filter(status=PublishStatus.PUBLISHED).order_by('internal_sku_code'),
                    to_attr='quick_skus',
                )
            )
        )
        # 折叠到「款式」粒度：每个款式只展示一个代表 Product，分页基于款式数
        collapsed = collapse_products_by_style(queryset)
        # 过滤掉没有上架SKU的产品
        collapsed = [p for p in collapsed if p.active_sku_count > 0]
        self.filtered_queryset = queryset
        self.collapsed_queryset = collapsed
        return collapsed

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        filtered_products = getattr(self, 'filtered_queryset', self.get_queryset())
        base_skus = SKU.objects.filter(
            product__status=PublishStatus.PUBLISHED,
            status=PublishStatus.PUBLISHED,
            product_id__in=filtered_products.values('pk'),
        )
        selected_category = getattr(self, 'selected_category', None)
        if selected_category:
            base_skus = base_skus.filter(product__category_id__in=selected_category.descendant_ids())
        dynamic_attributes = selected_category.effective_attributes() if selected_category else []
        dynamic_attribute_filters = []
        for attribute in dynamic_attributes:
            if not attribute.is_filterable:
                continue
            dynamic_attribute_filters.append(
                {
                    'attribute': attribute,
                    'param': attribute_param(attribute.code),
                    'selected': self.request.GET.get(attribute_param(attribute.code), '').strip(),
                    'values': attribute_values(base_skus, attribute.code),
                }
            )

        context['categories'] = Category.objects.filter(is_active=True)
        context['category_tree'] = root_categories()
        context['selected_category'] = selected_category
        context['breadcrumbs'] = selected_category.breadcrumb() if is_displayable_category(selected_category) else []
        panel_subcategories = []
        if selected_category:
            panel_subcategories = [
                subcategory
                for subcategory in selected_category.children.filter(is_active=True).order_by('sort_order', 'name')
                if filtered_products.filter(category_id__in=subcategory.descendant_ids()).exists()
            ]
        context['panel_subcategories'] = panel_subcategories
        # 第 1 行 chip：永远展示当前层级的同级分类（未选时即根分类）
        if selected_category:
            hierarchy_level = selected_category.children.filter(is_active=True).order_by('sort_order', 'name')
            hierarchy_parent_slug = selected_category.slug
        else:
            hierarchy_level = root_categories()
            hierarchy_parent_slug = ''
        context['hierarchy_level'] = hierarchy_level
        context['hierarchy_parent_slug'] = hierarchy_parent_slug
        context['hierarchy_level_label'] = (
            f'{selected_category.name} 之子分类' if selected_category else '全部分类'
        )

        # 第 2 行 chip：品牌（支持后台自定义排序）
        brand_qs = filtered_products.exclude(brand='')
        if selected_category:
            brand_qs = brand_qs.filter(category_id__in=selected_category.descendant_ids())
        # 获取所有品牌并关联 BrandOrder 排序配置
        from django.db.models.functions import Concat
        from django.db.models import F, OuterRef, Subquery
        brand_list = list(
            brand_qs.order_by('brand').values_list('brand', flat=True).distinct()
        )
        # 按 BrandOrder.sort_order 排序，未配置的按字母顺序排后面
        ordered_brands = list(
            BrandOrder.objects.filter(
                brand__in=brand_list,
                is_active=True,
            ).values_list('brand', flat=True).order_by('sort_order')
        )
        # 未配置 BrandOrder 的品牌按字母顺序排在后面
        unordered_brands = sorted([b for b in brand_list if b not in ordered_brands])
        context['brands'] = ordered_brands + unordered_brands

        context['colors'] = base_skus.exclude(color='').values_list('color', flat=True).distinct().order_by('color')[:80]
        context['package_specs'] = (
            base_skus.exclude(package_spec='').values_list('package_spec', flat=True).distinct().order_by('package_spec')[:80]
        )
        context['stock_statuses'] = SKU._meta.get_field('stock_status').choices
        context['dynamic_attribute_filters'] = dynamic_attribute_filters
        context['filters'] = self.request.GET
        context['page_size'] = self.get_paginate_by(self.object_list)
        context['page_size_options'] = self.page_size_options

        # 同类型色号聚合：每个 Product 找同款主型号的所有色号 SKU
        all_filtered_products = list(self.filtered_queryset)
        scoped_peers = build_style_peer_map(all_filtered_products)
        keywords = getattr(self, 'search_keywords', [])
        hit_sku_by_product = {}
        if keywords:
            for product in context['products']:
                hit_sku = _find_hit_sku(product, keywords)
                if hit_sku:
                    hit_sku_by_product[product.pk] = hit_sku
        for product in context['products']:
            category_attributes = product.category.effective_attributes() if product.category else []
            product.base_sku = base_sku_for_product(product.quick_skus, category_attributes)
            product.main_image_url = product_main_image_url(product, product.base_sku)
            # 列表页跨页：peer 用所有命中 SKU（不只是当前页）。
            # 色号变体通常挂在同一 Product 下，把当前产品的色号 SKU 也算入，
            # 否则 pk=522 这类单产品系列永远不显示徽章。
            product.peer_skus = list(scoped_peers.get(_group_key(product), []))
            product.style_model_label = _group_key(product)
            product.hit_sku = hit_sku_by_product.get(product.pk)
        context['hit_sku_by_product'] = hit_sku_by_product

        query = self.request.GET.copy()
        query.pop('page', None)
        context['page_querystring'] = query.urlencode()

        brand_query = query.copy()
        brand_query.pop('brand', None)
        context['brand_querystring'] = brand_query.urlencode()

        category_query = query.copy()
        category_query.pop('category', None)
        category_query.pop('brand', None)
        context['category_querystring'] = category_query.urlencode()

        paginator = context.get('paginator')
        page_obj = context.get('page_obj')
        if paginator and page_obj:
            context['page_items'] = pagination_items(page_obj.number, paginator.num_pages)
        return context


class ProductDetailView(DetailView):
    model = Product
    template_name = 'catalog/product_detail.html'

    @staticmethod
    def _variant_row_attribute_keys(variant_skus, detail_attributes):
        """返回每行 attrs 区域应当显示的字段集合。

        每行都展示完整的型号信息（销售单位、包规等），便于用户在「其他所有型号」区
        一眼区分每个 SKU；CategoryAttribute（如颜色、规格）始终显示。
        """
        keys = {key for key, _ in (
            ('manufacturer_model', lambda sku: sku.product.manufacturer_model),
            ('capacity', lambda sku: sku.capacity),
            ('unit', lambda sku: sku.unit),
            ('package_spec', lambda sku: sku.package_spec),
            ('mpq', lambda sku: sku.mpq),
        )}
        # CategoryAttribute（颜色、规格等）始终显示
        for attr in detail_attributes:
            keys.add(attr.code)
        return keys
    context_object_name = 'product'
    queryset = Product.objects.filter(status=PublishStatus.PUBLISHED).select_related('category')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        skus = list(self.object.skus.filter(status=PublishStatus.PUBLISHED).order_by('internal_sku_code'))
        category = self.object.category
        detail_attributes = category.effective_attributes() if category else []
        base_sku = base_sku_for_product(skus, detail_attributes)
        selected_id = self.request.GET.get('sku')
        selected_sku = next((sku for sku in skus if str(sku.pk) == selected_id), None) or base_sku
        selected_name_attributes = []
        selected_attributes = selected_sku.attributes if selected_sku and isinstance(selected_sku.attributes, dict) else {}
        for attribute in detail_attributes:
            value = selected_attributes.get(attribute.code)
            if value not in (None, ''):
                selected_name_attributes.append({'name': attribute.name, 'value': value})
        # 标题追加 SKU 颜色 + 制造商型号（如「内墙乳胶漆 哑光白 净味120」）。
        # SKU 的颜色一般存在 attributes['color']，但部分 SKU 没填，
        # 因此回退到 sku.color 字段。
        title_extras = []
        color_value = selected_attributes.get('color') or (selected_sku.color if selected_sku else '')
        if color_value:
            title_extras.append(color_value)
        if self.object.manufacturer_model:
            title_extras.append(self.object.manufacturer_model)
        context['title_extras'] = title_extras

        # 1. 收集所有 SKU：同 group_key 的所有产品（含当前产品自身）。
        # 颜色变体一般挂在同一 Product 下的不同 SKU，单产品系列也能展示完整颜色列表。
        all_skus = []
        current_group_key = _group_key(self.object)
        selected_sku_from_query = self.request.GET.get('sku', '').strip()
        sku_focus_mode = bool(selected_sku_from_query)
        if sku_focus_mode:
            # 搜索来源（列表页带 ?sku= 命中精确 SKU）：只展示该 SKU，避免复合显示。
            for sku_obj in skus:
                if str(sku_obj.pk) == selected_sku_from_query:
                    sku_obj.is_other_product = False
                    if _has_color_code_marker(self.object.name):
                        sku_obj.color_code = _extract_color_code(self.object.name)
                    all_skus.append(sku_obj)
                    break
        elif current_group_key and not current_group_key.startswith('__solo__'):
            # 只有名字含色号前缀（如 B-1088 XXXX）的产品才按色号去重；
            # 其他 group（如立邦内墙面漆按 mfr 区分）的所有 SKU 都并入，避免只显示当前产品 2 个。
            only_one_per_color = _has_color_code_marker(self.object.name)
            seen_codes = {}
            for p in (
                Product.objects.filter(
                    status=PublishStatus.PUBLISHED,
                )
                .prefetch_related('skus')
            ):
                if _group_key(p) != current_group_key:
                    continue
                is_self = p.pk == self.object.pk
                if only_one_per_color and not is_self:
                    code = _extract_color_code(p.name)
                    if code and code not in seen_codes:
                        seen_codes[code] = True
                    elif code and code in seen_codes:
                        continue
                    else:
                        # 同组但没解析出色号：兜底也并入，避免漏掉（如规格变体）
                        pass
                for sku_obj in p.skus.filter(status=PublishStatus.PUBLISHED):
                    sku_obj.is_other_product = not is_self
                    if only_one_per_color:
                        sku_obj.color_code = _extract_color_code(p.name)
                    all_skus.append(sku_obj)

        # 2. 构建筛选条件（从全部 SKU 取值）
        # 精确 SKU 模式下 all_skus 仅有 1 个，筛选会塌缩为单条；改用 skus 作为筛选值域。
        filter_value_source = skus if sku_focus_mode else all_skus
        variant_query = self.request.GET.get('variant_q', '').strip().casefold()
        variant_filters = {}
        variant_filter_groups = []

        # SKU 模型字段（capacity / color）也作为筛选维度，无论分类属性是否配置都显示
        for field_code, field_name, label in [
            ('capacity', 'capacity', '容量'),
            ('color', 'color', '颜色'),
        ]:
            values = sorted(
                {str(getattr(sku, field_code, '') or '').strip()
                 for sku in filter_value_source} - {''},
                key=natural_value_key,
            )
            param = f'variant_{field_code}'
            selected_values = [v for v in self.request.GET.getlist(param) if v]
            if selected_values:
                variant_filters[field_code] = set(selected_values)
            if values:
                variant_filter_groups.append({
                    'attribute': type('Obj', (), {'code': field_code, 'name': label})(),
                    'param': param,
                    'values': values,
                    'selected_values': selected_values,
                })

        # CategoryAttribute.code 与 SKU/Product 模型字段名的映射（因历史命名差异）
        SKU_FIELD_MAP = {
            'volume': 'capacity',
            'factory_model': 'manufacturer_model',
            'product_name': 'name',
        }

        def _sku_attr_value(sku, code):
            """从 SKU.attributes JSON 取值，fallback 到 SKU/product 模型字段。"""
            if isinstance(sku.attributes, dict):
                v = sku.attributes.get(code, None)
                if v not in (None, ''):
                    return str(v).strip()
            # fallback 到 SKU 模型字段（含字段名映射）
            model_code = SKU_FIELD_MAP.get(code, code)
            v = getattr(sku, model_code, None)
            if v not in (None, ''):
                return str(v).strip()
            # fallback 到 product 字段（含字段名映射）
            v = getattr(sku.product, model_code, None)
            if v not in (None, ''):
                return str(v).strip()
            return ''

        for attribute in detail_attributes:
            if not attribute.is_filterable:
                continue
            if attribute.code == 'color_code':
                continue
            # 避免与上方 SKU 字段重复（如分类属性也定义了 capacity / color）
            if attribute.code in ('capacity', 'color'):
                continue
            param = f'variant_{attribute.code}'
            selected_values = [value for value in self.request.GET.getlist(param) if value]

            values = sorted(
                {
                    _sku_attr_value(sku, attribute.code)
                    for sku in filter_value_source
                } - {''},
                key=natural_value_key,
            )
            if selected_values:
                variant_filters[attribute.code] = set(selected_values)
            if values:
                variant_filter_groups.append(
                    {'attribute': attribute, 'param': param, 'values': values, 'selected_values': selected_values}
                )

        # 3. 过滤 & 排序
        variant_skus = []
        # 多关键词：OR 语义，任一关键词命中即包含；按命中质量打分用于排序
        query_terms = [t.casefold() for t in variant_query.split() if t] if variant_query else []
        search_pool = skus if sku_focus_mode else all_skus

        def _sku_search_score(sku):
            """返回相关性总分：精确匹配 > 开头匹配 > 包含匹配，无匹配返回 0。"""
            if not query_terms:
                return 1  # 无搜索词保留在原排序位置
            score = 0
            code = sku.internal_sku_code.casefold()
            jst = (sku.jst_sku_id or '').casefold()
            attr_text = (sku.sku_attribute_text or '').casefold()
            display = sku.display_name.casefold()
            color = (sku.color or '').casefold()
            capacity = (sku.capacity or '').casefold()
            product_name = (sku.product.name or '').casefold()
            manufacturer_model = (sku.product.manufacturer_model or '').casefold()
            # 从 attributes JSON 中也收集文本
            extra_attrs = []
            if isinstance(sku.attributes, dict):
                for v in sku.attributes.values():
                    if v and str(v).strip():
                        extra_attrs.append(str(v).casefold())
            extra_text = ' '.join(extra_attrs)
            for term in query_terms:
                # 精确 == 最高分
                if term == code or term == jst or term == attr_text:
                    score += 100
                # 开头匹配
                elif code.startswith(term) or jst.startswith(term) or attr_text.startswith(term):
                    score += 70
                elif display.startswith(term) or product_name.startswith(term) or manufacturer_model.startswith(term):
                    score += 60
                # 包含匹配
                elif term in code or term in jst or term in attr_text:
                    score += 40
                elif term in display or term in product_name or term in manufacturer_model:
                    score += 30
                elif term in color or term in capacity or term in extra_text:
                    score += 20
                else:
                    # 其他属性字段（名称、code 等）
                    found = any(term in _sku_attr_value(sku, attr.code).casefold()
                                for attr in detail_attributes)
                    if found:
                        score += 10
            return score

        for sku in search_pool:
            if query_terms and _sku_search_score(sku) == 0:
                continue
            if any(_sku_attr_value(sku, code) not in values for code, values in variant_filters.items()):
                continue
            variant_skus.append(sku)

        # 精确 SKU 模式（搜索来源）：「其他所有型号」展示同 product 下其他 SKU（排除当前选中），
        # 否则这里只显示当前 SKU 1 条，模块毫无意义。
        # 默认模式（非 sku_focus_mode）也排除当前主 SKU，避免列表首位显示自己造成"重复"错觉。
        # 注意：sku_focus_mode 下 all_skus 仅 1 条，必须用 skus（product 全部 SKU）作为筛选+排除的源。
        # 排除必须在"步骤 3 过滤"之后做，否则筛选失效。
        # 「其他所有型号」区需排除当前显示 SKU（无论 sku_focus_mode 还是默认模式）。
        # 上一步搜索/筛选已经完成；这里只做排除。
        current_pk = None
        if sku_focus_mode:
            current_pk = selected_sku_from_query
        elif selected_sku is not None:
            current_pk = str(selected_sku.pk)
        elif base_sku is not None:
            current_pk = str(base_sku.pk)
        if current_pk:
            variant_skus = [sku for sku in variant_skus if str(sku.pk) != current_pk]

        # 有搜索词时按相关性降序 + 订货编码升序；无搜索词时保持自然排序
        if query_terms:
            variant_skus.sort(
                key=lambda sku: (
                    -_sku_search_score(sku),
                    sku.internal_sku_code,
                )
            )
        else:
            variant_skus.sort(
                key=lambda sku: (
                    tuple(
                        natural_value_key(_sku_attr_value(sku, attribute.code))
                        for attribute in detail_attributes
                    ),
                    sku.internal_sku_code,
                )
            )

        variant_paginator = Paginator(variant_skus, 5)
        variant_page_obj = variant_paginator.get_page(self.request.GET.get('variant_page', 1))
        variant_query_params = self.request.GET.copy()
        variant_query_params.pop('variant_page', None)

        context['skus'] = skus
        context['selected_sku'] = selected_sku
        context['selected_name_attributes'] = selected_name_attributes
        context['base_sku'] = base_sku
        context['breadcrumbs'] = category.breadcrumb() if is_displayable_category(category) else []
        context['detail_attributes'] = detail_attributes
        context['variant_skus'] = list(variant_page_obj.object_list)
        context['variant_paginator'] = variant_paginator
        context['variant_page_obj'] = variant_page_obj
        context['variant_page_items'] = pagination_items(variant_page_obj.number, variant_paginator.num_pages)
        context['variant_page_querystring'] = variant_query_params.urlencode()
        context['variant_filter_groups'] = variant_filter_groups
        context['variant_query'] = self.request.GET.get('variant_q', '').strip()
        # 同款式下多个 SKU 时，若某字段全部相同则隐藏（避免每行重复）
        context['variant_row_attribute_keys'] = self._variant_row_attribute_keys(variant_skus, detail_attributes)
        gallery = product_image_gallery(self.object, selected_sku)
        context['product_main_image_url'] = gallery['main_url']
        context['product_detail_images'] = gallery['detail_images']

        # 聚合图片列表：主图 + 主图细节(最多12张) + 详情图(最多10张)
        from catalog.product_images import product_attachments_gallery, product_documents
        context['product_gallery_images'] = product_attachments_gallery(self.object)
        context['product_documents'] = product_documents(self.object)

        return context


def _search_suggest_queryset(q):
    """构造搜索建议的候选集（按相关性排序的产品 + 命中 SKU 的样品）。

    返回的是 (suggestions, products)，suggestions 是给前端下拉的扁平结构。
    """
    q = (q or '').strip()
    if not q:
        return [], []
    keywords = [w for w in q.split() if w]
    if not keywords:
        return [], []
    # 1) 产品候选：name / alias / brand / manufacturer_model / style_code / cas_no 命中
    product_q = Q()
    for kw in keywords:
        product_q |= (
            Q(name__icontains=kw)
            | Q(alias__icontains=kw)
            | Q(brand__icontains=kw)
            | Q(manufacturer_model__icontains=kw)
            | Q(style_code__icontains=kw)
            | Q(cas_no__icontains=kw)
        )
    products = list(
        Product.objects.filter(status=PublishStatus.PUBLISHED)
        .filter(product_q)
        .select_related('category')
        .only('pk', 'name', 'alias', 'brand', 'manufacturer_model', 'style_code')
        .order_by('name')[:60]
    )
    # 2) SKU 候选：用于在建议里附带「内部 SKU 编码」
    sku_q = Q()
    for kw in keywords:
        sku_q |= (
            Q(internal_sku_code__icontains=kw)
            | Q(jst_sku_id__icontains=kw)
            | Q(sku_attribute_text__icontains=kw)
            | Q(product__name__icontains=kw)
            | Q(product__alias__icontains=kw)
            | Q(product__brand__icontains=kw)
            | Q(product__manufacturer_model__icontains=kw)
        )
    skus = list(
        SKU.objects.filter(status=PublishStatus.PUBLISHED, product__status=PublishStatus.PUBLISHED)
        .filter(sku_q)
        .select_related('product')
        .only('pk', 'internal_sku_code', 'product__pk', 'product__name', 'product__alias', 'product__brand')
        .order_by('internal_sku_code')[:60]
    )
    return products, skus


def search_suggest(request):
    """搜索建议 API：返回 JSON 列表，前端用于 autocomplete。"""
    from django.http import JsonResponse
    q = request.GET.get('q', '').strip()
    if not q:
        return JsonResponse({'products': [], 'skus': []})
    products, skus = _search_suggest_queryset(q)
    payload = {
        'products': [
            {
                'pk': p.pk,
                'name': p.name,
                'alias': p.alias or '',
                'brand': p.brand or '',
                'manufacturer_model': p.manufacturer_model or '',
                'style_code': p.style_code or '',
                'url': p.get_absolute_url(),
            }
            for p in products
        ],
        'skus': [
            {
                'pk': s.pk,
                'internal_sku_code': s.internal_sku_code,
                'product_pk': s.product_id,
                'product_name': s.product.name,
                'url': s.product.get_absolute_url() + f'?sku={s.pk}',
            }
            for s in skus
        ],
    }
    return JsonResponse(payload)


def product_media(request, asset_path):
    root = product_image_root().resolve()
    requested = (root / Path(asset_path)).resolve()
    try:
        requested.relative_to(root)
    except ValueError as error:
        raise Http404 from error

    # 允许的目录结构：
    #   1) <style_code>/<sku_code>/<image>          ← 新上架模板格式
    #   2) <style_code>/主图透图/<image>            ← 旧主图
    #   3) <style_code>/详情页/<image> 或 详情图/<image>  ← 旧详情图
    if not requested.is_file() or requested.suffix.casefold() not in IMAGE_EXTENSIONS:
        raise Http404

    relative_parts = requested.relative_to(root).parts
    if len(relative_parts) != 3 or relative_parts[1] == '..' or requested.is_symlink():
        raise Http404
    middle = relative_parts[1]
    allowed_middle = {'主图透图', '详情页', '详情图'}
    if middle not in allowed_middle:
        # 新格式：第二段需匹配系统中存在的 SKU 编码；这里采用“同 style_code 下任意子目录”策略：
        # 因为 product_image_root 之外的目录无法被构造路径进来，所以只要第二段是字符串就直接放行。
        if not middle:
            raise Http404

    content_type, _ = mimetypes.guess_type(requested.name)
    response = FileResponse(requested.open('rb'), content_type=content_type or 'application/octet-stream')
    response['Cache-Control'] = 'public, max-age=86400'
    return response

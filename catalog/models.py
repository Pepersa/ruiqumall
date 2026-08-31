from decimal import Decimal

from django.conf import settings
from django.db import models
from django.templatetags.static import static
from django.urls import reverse


class PublishStatus(models.TextChoices):
    DRAFT = 'draft', '草稿'
    PUBLISHED = 'published', '上架'
    ARCHIVED = 'archived', '下架'


class Category(models.Model):
    name = models.CharField('分类名称', max_length=120)
    slug = models.SlugField('URL 标识', max_length=140, unique=True)
    parent = models.ForeignKey(
        'self',
        verbose_name='上级分类',
        null=True,
        blank=True,
        related_name='children',
        on_delete=models.CASCADE,
    )
    description = models.TextField('说明', blank=True)
    icon = models.ImageField('分类图标', upload_to='category_icons/', blank=True)
    sort_order = models.PositiveIntegerField('排序', default=0)
    is_active = models.BooleanField('启用', default=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        verbose_name = '产品分类'
        verbose_name_plural = '产品分类'
        ordering = ['sort_order', 'name']
        indexes = [models.Index(fields=['slug']), models.Index(fields=['parent', 'is_active'])]

    def __str__(self):
        return self.name

    @property
    def level(self):
        level = 1
        parent = self.parent
        while parent:
            level += 1
            parent = parent.parent
        return level

    def ancestors(self):
        items = []
        parent = self.parent
        while parent:
            items.append(parent)
            parent = parent.parent
        return list(reversed(items))

    def breadcrumb(self):
        return [*self.ancestors(), self]

    def descendants(self):
        items = []
        children = list(self.children.filter(is_active=True))
        for child in children:
            items.append(child)
            items.extend(child.descendants())
        return items

    def descendant_ids(self, include_self=True):
        ids = [self.pk] if include_self else []
        ids.extend(category.pk for category in self.descendants())
        return ids

    def effective_attributes(self):
        for category in reversed(self.breadcrumb()):
            attributes = list(category.attributes.filter(is_active=True).order_by('sort_order', 'name'))
            if attributes:
                return attributes
        return []


class AttributeDataType(models.TextChoices):
    TEXT = 'text', '文本'
    NUMBER = 'number', '数字'
    PRICE = 'price', '价格'
    OPTION = 'option', '枚举'
    RANGE = 'range', '范围'


class CategoryAttribute(models.Model):
    category = models.ForeignKey(Category, verbose_name='所属分类', related_name='attributes', on_delete=models.CASCADE)
    name = models.CharField('属性名称', max_length=80)
    code = models.SlugField('属性编码', max_length=100)
    data_type = models.CharField('数据类型', max_length=20, choices=AttributeDataType.choices, default=AttributeDataType.TEXT)
    is_required = models.BooleanField('必填', default=False)
    is_filterable = models.BooleanField('用于筛选', default=True)
    is_list_visible = models.BooleanField('列表显示', default=False)
    is_detail_visible = models.BooleanField('详情显示', default=True)
    sort_order = models.PositiveIntegerField('排序', default=0)
    is_active = models.BooleanField('启用', default=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        verbose_name = '分类属性'
        verbose_name_plural = '分类属性'
        ordering = ['category', 'sort_order', 'name']
        unique_together = [('category', 'code')]
        indexes = [
            models.Index(fields=['category', 'is_active']),
            models.Index(fields=['code']),
        ]

    def __str__(self):
        return f'{self.category} - {self.name}'


class Product(models.Model):
    name = models.CharField('产品名称', max_length=255)
    alias = models.CharField('别名/简称', max_length=255, blank=True)
    style_code = models.CharField('款式编码', max_length=80, unique=True)
    cas_no = models.CharField('CAS 号', max_length=80, blank=True)
    category = models.ForeignKey(
        Category,
        verbose_name='分类',
        null=True,
        blank=True,
        related_name='products',
        on_delete=models.SET_NULL,
    )
    brand = models.CharField('品牌', max_length=120, blank=True)
    manufacturer_model = models.CharField('制造商型号', max_length=120, blank=True)
    capacity = models.CharField('容量', max_length=80, blank=True)
    image = models.ImageField('产品图片', upload_to='products/', blank=True)
    remote_image_url = models.URLField('在线图片 URL', max_length=1000, blank=True)
    image_source_url = models.URLField('图片来源 URL', max_length=1000, blank=True)
    description = models.TextField('简介', blank=True)
    spec_summary = models.TextField('关键规格', blank=True)
    storage_info = models.TextField('储存条件', blank=True)
    safety_info = models.TextField('安全说明', blank=True)
    shipping_info = models.TextField('运输说明', blank=True)
    source_file_name = models.CharField('来源文件', max_length=255, blank=True)
    source_created_by = models.CharField('来源创建人', max_length=120, blank=True)
    status = models.CharField('状态', max_length=20, choices=PublishStatus.choices, default=PublishStatus.PUBLISHED)
    sort_order = models.PositiveIntegerField('目录排序', default=0, help_text='商品目录列表的展示顺序，值小的靠前；相同值时按名称排序')
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        verbose_name = '产品'
        verbose_name_plural = '产品'
        ordering = ['sort_order', 'name']
        indexes = [
            models.Index(fields=['style_code']),
            models.Index(fields=['brand']),
            models.Index(fields=['manufacturer_model']),
            models.Index(fields=['status']),
            models.Index(fields=['category', 'status']),
            models.Index(fields=['brand', 'name', 'manufacturer_model'], name='catalog_pro_brand_n_d61f24_idx'),
            models.Index(fields=['sort_order'], name='catalog_pro_sort_or_8c1a23_idx'),
        ]

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse('catalog:product_detail', kwargs={'pk': self.pk})

    @property
    def active_sku_count(self):
        return self.skus.filter(status=PublishStatus.PUBLISHED).count()

    @property
    def display_image_url(self):
        if self.image:
            return self.image.url
        if self.remote_image_url:
            return self.remote_image_url
        return static('img/product-placeholder.jpg')


class StockStatus(models.TextChoices):
    IN_STOCK = 'in_stock', '有货'
    CONFIRM = 'confirm', '需确认'
    PRESALE = 'presale', '预售'
    OUT_OF_STOCK = 'out_of_stock', '缺货'
    DISCONTINUED = 'discontinued', '停售'


class SKU(models.Model):
    product = models.ForeignKey(Product, verbose_name='所属产品', related_name='skus', on_delete=models.CASCADE)
    internal_sku_code = models.CharField('内部 SKU 编码', max_length=80, unique=True)
    jst_sku_id = models.CharField('聚水潭商品编码', max_length=80, blank=True)
    shop_sku_id = models.CharField('店铺商品编码', max_length=80, blank=True)
    source_goods_code = models.CharField('来源商品编码', max_length=80, blank=True)
    source_style_code = models.CharField('来源款式编码', max_length=80, blank=True)
    source_goods_name = models.CharField('来源商品名称', max_length=255, blank=True)
    sku_attribute_text = models.CharField('颜色及规格', max_length=255, blank=True)
    color = models.CharField('颜色/型号', max_length=120, blank=True)
    package_spec = models.CharField('包规', max_length=120, blank=True)
    capacity = models.CharField('容量', max_length=80, blank=True)
    grade = models.CharField('等级', max_length=120, blank=True)
    unit = models.CharField('单位', max_length=40, blank=True)
    price = models.DecimalField('单价', max_digits=12, decimal_places=2, null=True, blank=True)
    cost_price = models.DecimalField('成本价', max_digits=12, decimal_places=2, null=True, blank=True)
    purchase_price = models.DecimalField('采购价', max_digits=12, decimal_places=2, null=True, blank=True)
    list_price = models.DecimalField('市场价', max_digits=12, decimal_places=2, null=True, blank=True)
    moq = models.DecimalField('起订量', max_digits=12, decimal_places=2, default=Decimal('1'))
    mpq = models.DecimalField('每包数量(MPQ)', max_digits=12, decimal_places=2, null=True, blank=True)
    order_step = models.DecimalField('销售步进', max_digits=12, decimal_places=2, default=Decimal('1'))
    stock_status = models.CharField('库存状态', max_length=20, choices=StockStatus.choices, default=StockStatus.CONFIRM)
    inventory_sync_enabled = models.BooleanField('库存同步', default=True)
    attributes = models.JSONField('特殊属性', default=dict, blank=True)
    source_raw_row = models.JSONField('原始导入行', default=dict, blank=True)
    status = models.CharField('状态', max_length=20, choices=PublishStatus.choices, default=PublishStatus.PUBLISHED)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        verbose_name = 'SKU'
        verbose_name_plural = 'SKU'
        ordering = ['internal_sku_code']
        indexes = [
            models.Index(fields=['internal_sku_code']),
            models.Index(fields=['jst_sku_id']),
            models.Index(fields=['source_style_code']),
            models.Index(fields=['stock_status']),
            models.Index(fields=['status']),
        ]

    def __str__(self):
        return f'{self.internal_sku_code} {self.source_goods_name or self.product.name}'

    @property
    def display_name(self):
        return self.source_goods_name or self.product.name

    @property
    def can_add_to_cart(self):
        return self.status == PublishStatus.PUBLISHED and self.stock_status not in {
            StockStatus.OUT_OF_STOCK,
            StockStatus.DISCONTINUED,
        }


class ProductAttachment(models.Model):
    class AttachmentType(models.TextChoices):
        SDS = 'sds', 'SDS/MSDS'
        COA = 'coa', 'COA'
        TDS = 'tds', 'TDS'
        MANUAL = 'manual', '产品说明书'
        CERT = 'cert', '资质证书'
        OTHER = 'other', '其他'

    product = models.ForeignKey(Product, verbose_name='产品', related_name='attachments', on_delete=models.CASCADE)
    sku = models.ForeignKey(SKU, verbose_name='SKU', null=True, blank=True, related_name='attachments', on_delete=models.CASCADE)
    title = models.CharField('标题', max_length=180)
    attachment_type = models.CharField('资料类型', max_length=20, choices=AttachmentType.choices, default=AttachmentType.OTHER)
    file = models.FileField('文件', upload_to='attachments/')
    version = models.CharField('版本', max_length=60, blank=True)
    is_public = models.BooleanField('前台可见', default=True)
    uploaded_at = models.DateTimeField('上传时间', auto_now_add=True)

    class Meta:
        verbose_name = '产品资料'
        verbose_name_plural = '产品资料'
        ordering = ['product', 'attachment_type', 'title']

    def __str__(self):
        return self.title


class HomeCategory(models.Model):
    class ImageDisplayMode(models.TextChoices):
        COVER = 'cover', '覆盖（填充并裁剪）'
        CONTAIN = 'contain', '包含（完整显示）'
        FILL = 'fill', '拉伸（填满）'
        AUTO = 'auto', '自适应（保持比例）'

    category = models.ForeignKey(
        Category,
        verbose_name='关联分类',
        related_name='home_entries',
        on_delete=models.CASCADE,
        limit_choices_to={'parent__isnull': False, 'parent__parent__isnull': True},
        help_text='仅可选择二级分类（其上级为顶级分类）',
    )
    title = models.CharField('显示标题', max_length=120, blank=True, help_text='留空则使用分类名称')
    image = models.ImageField('分类图标', upload_to='home_categories/', blank=True)
    image_display = models.CharField(
        '图片显示模式',
        max_length=20,
        choices=ImageDisplayMode.choices,
        default=ImageDisplayMode.COVER,
        help_text='cover: 填充并裁剪（推荐）, contain: 完整显示, fill: 拉伸变形, auto: 浏览器默认',
    )
    link_url = models.CharField('跳转链接', max_length=255, blank=True, help_text='留空则跳到该分类的产品列表')
    sort_order = models.PositiveIntegerField('排序', default=0)
    is_active = models.BooleanField('启用', default=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        verbose_name = '主页分类'
        verbose_name_plural = '主页分类'
        ordering = ['sort_order', 'id']

    def __str__(self):
        return self.display_title

    @property
    def display_title(self):
        return self.title or self.category.name

    @property
    def resolved_url(self):
        if self.link_url:
            return self.link_url
        from django.urls import reverse
        return reverse('catalog:product_list') + f'?category={self.category.slug}'


class HomeScene(models.Model):
    title = models.CharField('场景标题', max_length=80)
    subtitle = models.CharField('副标题', max_length=200, blank=True)
    description = models.TextField('场景描述', blank=True)
    slug = models.SlugField('URL 标识', max_length=120, unique=True)
    banner_image = models.ImageField(
        '场景横幅图', upload_to='home_scenes/', blank=True,
    )
    icon = models.ImageField(
        '小图标', upload_to='home_scenes/icons/', blank=True,
    )
    sort_order = models.PositiveIntegerField('排序', default=0)
    is_active = models.BooleanField('启用', default=True)
    products = models.ManyToManyField(
        'Product',
        through='HomeSceneProduct',
        related_name='featured_in_scenes',
        verbose_name='精选商品',
        blank=True,
    )
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        verbose_name = '主页场景'
        verbose_name_plural = '主页场景'
        ordering = ['sort_order', 'id']

    def __str__(self):
        return self.title

    def get_absolute_url(self):
        from django.urls import reverse
        return reverse('catalog:home_scene', kwargs={'slug': self.slug})

    @property
    def active_products(self):
        from .models import HomeSceneProduct
        ids = list(
            HomeSceneProduct.objects
            .filter(scene=self, product__status=PublishStatus.PUBLISHED)
            .order_by('sort_order', 'id')
            .values_list('product_id', flat=True)
        )
        if not ids:
            return Product.objects.none()
        preserved = {pk: idx for idx, pk in enumerate(ids)}
        return Product.objects.filter(id__in=ids).order_by(models.Case(
            *[models.When(pk=pk, then=models.Value(idx)) for pk, idx in preserved.items()],
            default=models.Value(len(ids)),
        ))


class HomeBrand(models.Model):
    """主页「品牌馆」精选：管理员可挑选要展示的品牌并上传 logo。

    - `brand_key` 必须与 Product.brand 字段完全一致（用于 ?brand= 过滤）。
      留空时回退到 `name`（仅当 name 与 Product.brand 文本相同时才会生效）。
    - `logo` 为空时品牌卡片只显示品牌名。
    """

    name = models.CharField('品牌名称', max_length=120)
    brand_key = models.CharField(
        '品牌 Key',
        max_length=120,
        blank=True,
        help_text='用于在 Product.brand 中精确匹配；留空则使用上方名称',
    )
    logo = models.ImageField(
        '品牌 Logo',
        upload_to='home_brands/',
        blank=True,
    )
    description = models.CharField('一句话简介', max_length=160, blank=True)
    link_url = models.CharField(
        '跳转链接',
        max_length=255,
        blank=True,
        help_text='留空则按品牌 Key 过滤产品列表',
    )
    sort_order = models.PositiveIntegerField('排序', default=0)
    is_active = models.BooleanField('启用', default=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        verbose_name = '主页品牌'
        verbose_name_plural = '主页品牌'
        ordering = ['sort_order', 'id']
        indexes = [
            models.Index(fields=['is_active', 'sort_order']),
            models.Index(fields=['brand_key']),
        ]

    def __str__(self):
        return self.name

    @property
    def display_name(self):
        return self.name

    @property
    def filter_key(self):
        """用于 ProductListView ?brand= 过滤的精确字符串（直接取 name）。"""
        return self.name.strip()

    @property
    def resolved_url(self):
        from django.urls import reverse
        return reverse('catalog:product_list') + f'?brand={self.filter_key}'


class BrandOrder(models.Model):
    """商品目录品牌筛选的自定义排序。管理员可在后台配置各品牌的显示顺序。

    - `brand` 必须与 Product.brand 字段完全一致。
    - 未在本表配置的品牌将按字母顺序排在已配置品牌之后。
    - `is_active=True` 时该品牌才会在筛选中显示。
    """

    brand = models.CharField('品牌名称', max_length=120, unique=True)
    sort_order = models.PositiveIntegerField('排序', default=0)
    is_active = models.BooleanField('启用', default=True, help_text='关闭后该品牌不在筛选中显示')
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        verbose_name = '品牌排序'
        verbose_name_plural = '品牌排序'
        ordering = ['sort_order', 'brand']

    def __str__(self):
        return self.brand


class HomeSceneProduct(models.Model):
    scene = models.ForeignKey(
        HomeScene, on_delete=models.CASCADE,
        related_name='scene_products', verbose_name='场景',
    )
    product = models.ForeignKey(
        'Product', on_delete=models.CASCADE,
        related_name='scene_links', verbose_name='商品',
    )
    sort_order = models.PositiveIntegerField('排序', default=0)

    class Meta:
        verbose_name = '场景商品'
        verbose_name_plural = '场景商品'
        ordering = ['sort_order', 'id']
        unique_together = [('scene', 'product')]

    def __str__(self):
        return f'{self.scene.title} - {self.product.name}'


class CustomerSKUPrice(models.Model):
    """客户 × SKU 协议价。下单/购物车解析单价时优先使用本表记录。"""

    customer = models.ForeignKey(
        'customers.Customer',
        verbose_name='客户',
        related_name='sku_prices',
        on_delete=models.CASCADE,
    )
    sku = models.ForeignKey(
        SKU,
        verbose_name='SKU',
        related_name='customer_prices',
        on_delete=models.CASCADE,
    )
    price = models.DecimalField('协议价', max_digits=12, decimal_places=2)
    min_qty = models.DecimalField(
        '起订量',
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        help_text='数量 ≥ 该值时生效，留空表示不限制下限',
    )
    max_qty = models.DecimalField(
        '封顶量',
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        help_text='数量 ≤ 该值时生效，留空表示不限制上限',
    )
    valid_from = models.DateField('生效开始', null=True, blank=True)
    valid_to = models.DateField('生效结束', null=True, blank=True)
    is_active = models.BooleanField('启用', default=True)
    remark = models.CharField('备注', max_length=255, blank=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        verbose_name = '客户协议价'
        verbose_name_plural = '客户协议价'
        ordering = ['customer', 'sku', 'min_qty']
        indexes = [
            models.Index(fields=['customer', 'sku']),
            models.Index(fields=['sku', 'is_active']),
        ]

    def __str__(self):
        return f'{self.customer.company_name} / {self.sku.internal_sku_code} = {self.price}'

    def is_effective(self, today=None):
        from datetime import date
        today = today or date.today()
        if not self.is_active:
            return False
        if self.valid_from and self.valid_from > today:
            return False
        if self.valid_to and self.valid_to < today:
            return False
        return True


class PriceHistory(models.Model):
    """协议价变更审计：保存旧值 + 操作人 + 原因，方便追溯。"""

    class ChangeType(models.TextChoices):
        CREATE = 'create', '新建'
        UPDATE = 'update', '调整'
        DISABLE = 'disable', '停用'

    customer = models.ForeignKey(
        'customers.Customer',
        verbose_name='客户',
        related_name='price_histories',
        on_delete=models.CASCADE,
    )
    sku = models.ForeignKey(
        SKU,
        verbose_name='SKU',
        related_name='price_histories',
        on_delete=models.CASCADE,
    )
    price_record = models.ForeignKey(
        CustomerSKUPrice,
        verbose_name='协议价记录',
        related_name='histories',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    change_type = models.CharField('变更类型', max_length=20, choices=ChangeType.choices)
    old_price = models.DecimalField('调整前价', max_digits=12, decimal_places=2, null=True, blank=True)
    new_price = models.DecimalField('调整后价', max_digits=12, decimal_places=2, null=True, blank=True)
    reason = models.CharField('原因', max_length=255, blank=True)
    operator = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name='操作人',
        null=True, blank=True,
        on_delete=models.SET_NULL,
    )
    created_at = models.DateTimeField('变更时间', auto_now_add=True)

    class Meta:
        verbose_name = '协议价变更记录'
        verbose_name_plural = '协议价变更记录'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['customer', 'sku']),
            models.Index(fields=['created_at']),
        ]

    def __str__(self):
        return f'{self.get_change_type_display()} {self.sku_id} {self.old_price}→{self.new_price}'


# Create your models here.

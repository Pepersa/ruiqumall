import json
from pathlib import Path
from uuid import uuid4

from django.contrib import admin, messages
from django import forms
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.uploadedfile import UploadedFile
from django.db.models import Case, Q, When
from django.db import models
from django.http import Http404
from django.shortcuts import redirect, render
from django.urls import path, reverse
from django.utils.text import get_valid_filename
from django.utils.html import format_html, format_html_join
from django.utils.safestring import mark_safe

from .category_io import expand_category_queryset, export_categories_response, import_categories_file
from .models import (
    BrandOrder,
    Category,
    CategoryAttribute,
    CustomerSKUPrice,
    HomeBrand,
    HomeCategory,
    HomeScene,
    HomeSceneProduct,
    PriceHistory,
    Product,
    ProductAttachment,
    SKU,
)
from .pricing_io import export_customer_prices_response, import_customer_prices_file
from .product_image_archive import (
    ProductImageArchiveError,
    import_product_image_archive,
)
from .product_images import (
    IMAGE_EXTENSIONS,
    detail_images_from_directory,
    image_url,
    main_image_from_directory,
    product_style_directory,
)
from .product_io import expand_product_queryset, export_products_response, import_products_file
from .listing_template import import_listing_workbook
from .listing_image_archive import (
    ListingImageImportError,
    ListingImageImportResult,
    import_listing_image_archive,
)


PRODUCT_IMAGE_DIRECTORY_NAMES = {
    'main': '主图透图',
    'detail': '详情页',
}
MAX_PRODUCT_IMAGE_BYTES = 30 * 1024 * 1024


def unique_image_path(directory, filename):
    path = directory / filename
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    index = 2
    while True:
        candidate = directory / f'{stem}-{index}{suffix}'
        if not candidate.exists():
            return candidate
        index += 1


def validate_product_image_upload(uploaded_file):
    if not isinstance(uploaded_file, UploadedFile):
        raise ValidationError('上传文件无效。')
    filename = get_valid_filename(Path(uploaded_file.name).name)
    suffix = Path(filename).suffix.casefold()
    if not filename or suffix not in IMAGE_EXTENSIONS:
        allowed = '、'.join(sorted(extension.removeprefix('.').upper() for extension in IMAGE_EXTENSIONS))
        raise ValidationError(f'仅支持 {allowed} 图片。')
    if uploaded_file.size > MAX_PRODUCT_IMAGE_BYTES:
        raise ValidationError('单张图片不能超过 30 MB。')
    if uploaded_file.content_type and not uploaded_file.content_type.startswith('image/'):
        raise ValidationError('文件内容类型不是图片。')
    return filename


def save_product_image(uploaded_file, directory):
    filename = validate_product_image_upload(uploaded_file)
    directory.mkdir(parents=True, exist_ok=True)
    destination = unique_image_path(directory, filename)
    temporary = directory / f'.upload-{uuid4().hex}.tmp'
    try:
        with temporary.open('xb') as output:
            for chunk in uploaded_file.chunks():
                output.write(chunk)
        temporary.replace(destination)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return destination


def named_main_image(asset_directory):
    main_directory = asset_directory / PRODUCT_IMAGE_DIRECTORY_NAMES['main']
    if not main_directory.is_dir():
        return None
    return next(
        (
            path
            for path in main_directory.iterdir()
            if path.is_file()
            and path.suffix.casefold() in IMAGE_EXTENSIONS
            and path.name.casefold().startswith('主图.')
        ),
        None,
    )


def promote_product_main_image(asset_directory, selected):
    main_directory = asset_directory / PRODUCT_IMAGE_DIRECTORY_NAMES['main']
    if selected.parent != main_directory or not selected.is_file():
        raise ValidationError('只能把主图透图目录中的图片设为主图。')

    destination = main_directory / f'主图{selected.suffix.casefold()}'
    if selected == destination:
        return selected

    temporary = main_directory / f'.primary-{uuid4().hex}{selected.suffix.casefold()}'
    selected.replace(temporary)
    current = named_main_image(asset_directory)
    if current and current != temporary:
        preserved = unique_image_path(
            main_directory,
            f'原主图{current.suffix.casefold()}',
        )
        current.replace(preserved)
    temporary.replace(destination)
    return destination


def managed_product_image_path(product, relative_path):
    asset_directory = product_style_directory(product)
    if not asset_directory:
        raise Http404
    requested = (asset_directory / Path(relative_path)).resolve()
    try:
        relative = requested.relative_to(asset_directory)
    except ValueError as error:
        raise Http404 from error
    if (
        len(relative.parts) != 2
        or relative.parts[0] not in PRODUCT_IMAGE_DIRECTORY_NAMES.values()
        or requested.suffix.casefold() not in IMAGE_EXTENSIONS
    ):
        raise Http404
    return requested


def product_admin_image_items(product):
    asset_directory = product_style_directory(product)
    if not asset_directory or not asset_directory.is_dir():
        return {'main': [], 'detail': []}
    primary = main_image_from_directory(asset_directory)

    def serialize(path):
        return {
            'name': path.name,
            'url': image_url(path),
            'relative_path': path.relative_to(asset_directory).as_posix(),
            'is_primary': path == primary,
        }

    main_directory = asset_directory / PRODUCT_IMAGE_DIRECTORY_NAMES['main']
    main_images = []
    if main_directory.is_dir():
        main_images = sorted(
            (
                path
                for path in main_directory.iterdir()
                if path.is_file() and path.suffix.casefold() in IMAGE_EXTENSIONS
            ),
            key=lambda path: path.name.casefold(),
        )
    return {
        'main': [serialize(path) for path in main_images],
        'detail': [serialize(path) for path in detail_images_from_directory(asset_directory)],
    }


def category_tree_choices(queryset):
    categories = list(queryset.select_related('parent', 'parent__parent', 'parent__parent__parent'))
    by_parent = {}
    for category in categories:
        by_parent.setdefault(category.parent_id, []).append(category)
    for siblings in by_parent.values():
        siblings.sort(key=lambda item: (item.sort_order, item.name))

    ordered = []

    def walk(parent_id):
        for category in by_parent.get(parent_id, []):
            ordered.append(category)
            walk(category.pk)

    walk(None)
    return ordered


def category_choice_label(category):
    indent = "\u3000" * (category.level - 1)
    return f"{indent}{category.name}"


def ordered_category_queryset(queryset):
    ordered = category_tree_choices(queryset)
    if not ordered:
        return Category.objects.none()
    ordering = Case(*[When(pk=category.pk, then=index) for index, category in enumerate(ordered)])
    return Category.objects.filter(pk__in=[category.pk for category in ordered]).order_by(ordering)


class SpecialAttributesWidget(forms.Widget):
    def __init__(self, definitions=(), attrs=None):
        super().__init__(attrs)
        self.definitions = list(definitions)

    def _value_dict(self, value):
        if isinstance(value, dict):
            return value
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
                return parsed if isinstance(parsed, dict) else {}
            except (TypeError, ValueError):
                return {}
        return {}

    def render(self, name, value, attrs=None, renderer=None):
        values = self._value_dict(value)
        if not self.definitions:
            return format_html(
                '<div style="min-width:220px;color:#666">请先选择产品并保存，系统将按产品分类显示特殊属性。</div>'
                '<input type="hidden" name="{}" value="{}">',
                name,
                json.dumps(values, ensure_ascii=False),
            )

        base_id = (attrs or {}).get('id', f'id_{name}')
        rows = []
        for definition in self.definitions:
            code = definition['code']
            input_id = f'{base_id}__{code}'
            required = mark_safe(' required') if definition.get('required') else ''
            required_mark = mark_safe(' <span style="color:#ba2121">*</span>') if definition.get('required') else ''
            current_value = str(values.get(code, ''))
            choices = list(definition.get('choices', []))
            if current_value and current_value not in choices:
                choices.append(current_value)
            options = [format_html('<option value="">请选择</option>')]
            options.extend(
                format_html(
                    '<option value="{}"{}>{}</option>',
                    choice,
                    mark_safe(' selected') if choice == current_value else '',
                    choice,
                )
                for choice in choices
            )
            options.append(format_html('<option value="__new__">＋ 新增值…</option>'))
            rows.append(
                format_html(
                    '<div style="display:grid;grid-template-columns:minmax(72px,auto) minmax(120px,1fr);gap:8px;align-items:center">'
                    '<label for="{}" style="margin:0;white-space:nowrap">{}{}</label>'
                    '<div style="display:flex;gap:6px;min-width:180px">'
                    '<select id="{}" name="{}__{}"{} style="flex:1;min-width:120px" '
                    'onchange="var n=this.nextElementSibling;n.hidden=this.value!==\'__new__\';if(!n.hidden){{n.focus()}}">{}</select>'
                    '<input class="vTextField" type="text" name="{}__{}__new" placeholder="输入新值" hidden style="flex:1;min-width:110px">'
                    '</div>'
                    '</div>',
                    input_id,
                    definition['name'],
                    required_mark,
                    input_id,
                    name,
                    code,
                    required,
                    mark_safe(''.join(str(option) for option in options)),
                    name,
                    code,
                )
            )
        return format_html(
            '<div class="special-attributes-editor" style="display:grid;gap:8px;min-width:260px">{}</div>',
            mark_safe(''.join(str(row) for row in rows)),
        )

    def value_from_datadict(self, data, files, name):
        if not self.definitions:
            return self._value_dict(data.get(name, '{}'))
        values = {}
        for definition in self.definitions:
            code = definition['code']
            value = str(data.get(f'{name}__{code}', '')).strip()
            if value == '__new__':
                value = str(data.get(f'{name}__{code}__new', '')).strip()
            if value:
                values[code] = value
        return values

    def value_omitted_from_data(self, data, files, name):
        if name in data:
            return False
        return not any(f"{name}__{definition['code']}" in data for definition in self.definitions)


class SKUAdminForm(forms.ModelForm):
    class Meta:
        model = SKU
        fields = '__all__'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        field = self.fields.get('attributes')
        if not field:
            return
        field.label = '特殊属性'
        product = self.instance.product if self.instance and self.instance.product_id else None
        if not product and self.data.get('product'):
            product = Product.objects.filter(pk=self.data.get('product')).select_related('category').first()
        attributes = product.category.effective_attributes() if product and product.category else []
        category = product.category if product else None
        actual_values = {}
        if category:
            actual_values = getattr(category, '_admin_special_attribute_values', None)
            if actual_values is None:
                actual_values = {}
                for values in SKU.objects.filter(product__category=category).exclude(attributes={}).values_list('attributes', flat=True):
                    if not isinstance(values, dict):
                        continue
                    for code, value in values.items():
                        text = str(value).strip()
                        if text:
                            actual_values.setdefault(code, set()).add(text)
                category._admin_special_attribute_values = actual_values
        definitions = [
            {
                'name': attribute.name,
                'code': attribute.code,
                'required': attribute.is_required,
                'choices': sorted(actual_values.get(attribute.code, set()), key=str.casefold),
            }
            for attribute in attributes
        ]
        known_codes = {definition['code'] for definition in definitions}
        existing_values = self.instance.attributes if self.instance and isinstance(self.instance.attributes, dict) else {}
        definitions.extend(
            {
                'name': code,
                'code': code,
                'required': False,
                'choices': sorted(actual_values.get(code, set()), key=str.casefold),
            }
            for code in existing_values
            if code not in known_codes
        )
        field.widget = SpecialAttributesWidget(definitions)
        if attributes:
            field.help_text = format_html_join(
                '',
                '<span style="display:inline-block;margin-right:14px"><strong>{}</strong>（编码：{}）</span>',
                ((attribute.name, attribute.code) for attribute in attributes),
            )
        else:
            field.help_text = '特殊属性由产品所属分类的属性模板决定。'

    def clean_attributes(self):
        attributes = self.cleaned_data.get('attributes')
        if not isinstance(attributes, dict):
            raise forms.ValidationError('特殊属性格式不正确。')
        missing = [
            definition['name']
            for definition in self.fields['attributes'].widget.definitions
            if definition.get('required') and not str(attributes.get(definition['code'], '')).strip()
        ]
        if missing:
            raise forms.ValidationError(f"必填特殊属性不能为空：{'、'.join(missing)}")
        return attributes


class ProductAdminForm(forms.ModelForm):
    single_sku_code = forms.CharField(label='内部 SKU 编码', required=False)
    single_sku_price = forms.DecimalField(label='单价', required=False, max_digits=12, decimal_places=2)
    single_sku_stock_status = forms.ChoiceField(label='库存状态', required=False, choices=SKU._meta.get_field('stock_status').choices)
    single_sku_attributes = forms.JSONField(label='特殊属性', required=False)
    single_sku_status = forms.ChoiceField(label='SKU 状态', required=False, choices=SKU._meta.get_field('status').choices)
    category_l1 = forms.ChoiceField(label='一级分类', required=False, choices=[('', '— 选择一级分类 —')])
    category_l2 = forms.ChoiceField(label='二级分类', required=False, choices=[('', '— 先选一级分类 —')])
    category_l3 = forms.ChoiceField(label='三级分类', required=False, choices=[('', '— 先选二级分类 —')])

    class Meta:
        model = Product
        fields = '__all__'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.single_sku = None
        if self.instance and self.instance.pk:
            skus = list(self.instance.skus.all()[:2])
            if len(skus) == 1:
                self.single_sku = skus[0]
        if self.single_sku:
            sku_form = SKUAdminForm(instance=self.single_sku)
            self.fields['single_sku_code'].initial = self.single_sku.internal_sku_code
            self.fields['single_sku_price'].initial = self.single_sku.price
            self.fields['single_sku_stock_status'].initial = self.single_sku.stock_status
            self.fields['single_sku_attributes'].initial = self.single_sku.attributes
            self.fields['single_sku_attributes'].widget = sku_form.fields['attributes'].widget
            self.fields['single_sku_attributes'].help_text = sku_form.fields['attributes'].help_text
            self.fields['single_sku_status'].initial = self.single_sku.status

        # Build basic L1/L2/L3 choices; JS handles cascading pre-selection
        all_cats = list(
            Category.objects.filter(is_active=True)
            .select_related('parent', 'parent__parent')
            .order_by('sort_order', 'name')
        )
        by_parent = {}
        for cat in all_cats:
            by_parent.setdefault(cat.parent_id, []).append(cat)

        l1_choices, l2_choices, l3_choices = [('', '— 选择一级分类 —')], [('', '— 选择二级分类 —')], [('', '— 选择三级分类 —')]
        for l1 in sorted(by_parent.get(None, []), key=lambda c: (c.sort_order, c.name)):
            l1_choices.append((l1.pk, l1.name))
            for l2 in sorted(by_parent.get(l1.pk, []), key=lambda c: (c.sort_order, c.name)):
                l2_choices.append((l2.pk, l2.name))
                for l3 in sorted(by_parent.get(l2.pk, []), key=lambda c: (c.sort_order, c.name)):
                    l3_choices.append((l3.pk, l3.name))

        self.fields['category_l1'].choices = l1_choices
        self.fields['category_l2'].choices = l2_choices
        self.fields['category_l3'].choices = l3_choices

        cat = getattr(self.instance, 'category', None)
        if cat:
            if cat.level == 3:
                self.fields['category_l3'].initial = cat.pk
                if cat.parent:
                    self.fields['category_l2'].initial = cat.parent.pk
                    if cat.parent.parent:
                        self.fields['category_l1'].initial = cat.parent.parent.pk
            elif cat.level == 2:
                self.fields['category_l2'].initial = cat.pk
                if cat.parent:
                    self.fields['category_l1'].initial = cat.parent.pk
            elif cat.level == 1:
                self.fields['category_l1'].initial = cat.pk

    def clean_category_l1(self):
        return self.cleaned_data.get('category_l1') or None

    def clean_category_l3(self):
        return self.cleaned_data.get('category_l3') or None

    def clean(self):
        cleaned = super().clean()
        brand = cleaned.get('brand', '').strip()
        if not brand:
            self.add_error('brand', '品牌不能为空，请填写产品品牌。')
        return cleaned

    def clean_single_sku_code(self):
        code = self.cleaned_data.get('single_sku_code', '').strip()
        if not self.single_sku:
            return code
        if not code:
            raise forms.ValidationError('内部 SKU 编码不能为空。')
        if SKU.objects.exclude(pk=self.single_sku.pk).filter(internal_sku_code=code).exists():
            raise forms.ValidationError('该内部 SKU 编码已存在。')
        return code

    def clean_single_sku_attributes(self):
        attributes = self.cleaned_data.get('single_sku_attributes') or {}
        if not self.single_sku:
            return attributes
        missing = [
            definition['name']
            for definition in self.fields['single_sku_attributes'].widget.definitions
            if definition.get('required') and not str(attributes.get(definition['code'], '')).strip()
        ]
        if missing:
            raise forms.ValidationError(f"必填特殊属性不能为空：{'、'.join(missing)}")
        return attributes

    def save_single_sku(self):
        if not self.single_sku or not self.is_valid():
            return
        self.single_sku.internal_sku_code = self.cleaned_data['single_sku_code']
        self.single_sku.price = self.cleaned_data['single_sku_price']
        self.single_sku.stock_status = self.cleaned_data['single_sku_stock_status']
        self.single_sku.attributes = self.cleaned_data['single_sku_attributes']
        self.single_sku.status = self.cleaned_data['single_sku_status']
        self.single_sku.save(
            update_fields=['internal_sku_code', 'price', 'stock_status', 'attributes', 'status', 'updated_at']
        )


class SKUInline(admin.TabularInline):
    model = SKU
    form = SKUAdminForm
    extra = 0
    fields = (
        'internal_sku_code',
        'price',
        'stock_status',
        'attributes',
        'status',
    )
    readonly_fields = ()


class CustomerSKUPriceForSKUInline(admin.TabularInline):
    """SKU 详情页内联：所有客户对这个 SKU 的协议价。"""
    model = CustomerSKUPrice
    extra = 0
    fields = ('customer', 'price', 'min_qty', 'max_qty', 'valid_from', 'valid_to', 'is_active', 'remark')
    autocomplete_fields = ('customer',)


class ProductAttachmentInline(admin.TabularInline):
    model = ProductAttachment
    extra = 0


class CategoryAttributeInline(admin.TabularInline):
    model = CategoryAttribute
    extra = 0
    fields = (
        'name',
        'code',
        'data_type',
        'is_required',
        'is_filterable',
        'is_list_visible',
        'is_detail_visible',
        'sort_order',
        'is_active',
    )


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'parent', 'level', 'slug', 'is_active', 'sort_order')
    list_filter = ('is_active', 'parent')
    search_fields = ('name', 'slug')
    prepopulated_fields = {'slug': ('name',)}
    inlines = (CategoryAttributeInline,)
    actions = ('export_selected_categories',)
    change_list_template = 'admin/catalog/category/change_list.html'

    def get_urls(self):
        custom_urls = [
            path(
                'import/',
                self.admin_site.admin_view(self.import_categories_view),
                name='catalog_category_import',
            ),
            path(
                'export-all/',
                self.admin_site.admin_view(self.export_all_categories_view),
                name='catalog_category_export_all',
            ),
        ]
        return custom_urls + super().get_urls()

    @admin.action(description='导出所选分类')
    def export_selected_categories(self, request, queryset):
        categories = expand_category_queryset(queryset)
        if not categories.exists():
            self.message_user(request, '没有可导出的分类。', level=messages.WARNING)
            return None
        return export_categories_response(categories, filename_prefix='selected-categories')

    def export_all_categories_view(self, request):
        return export_categories_response(Category.objects.all())

    def import_categories_view(self, request):
        if request.method == 'POST':
            uploaded_file = request.FILES.get('import_file')
            dry_run = request.POST.get('dry_run') == 'on'
            if not uploaded_file:
                self.message_user(request, '请选择 Excel 文件。', level=messages.ERROR)
            else:
                try:
                    result = import_categories_file(uploaded_file, dry_run=dry_run)
                except Exception as exc:
                    self.message_user(request, f'导入失败：{exc}', level=messages.ERROR)
                else:
                    summary = (
                        f'分类新增 {result.created_categories}，更新 {result.updated_categories}；'
                        f'属性新增 {result.created_attributes}，更新 {result.updated_attributes}；'
                        f'失败 {len(result.failures)}'
                    )
                    if result.failures:
                        preview = '；'.join(result.failures[:5])
                        if len(result.failures) > 5:
                            preview += f'；还有 {len(result.failures) - 5} 条未显示'
                        self.message_user(request, f'{summary}。{preview}', level=messages.WARNING)
                    elif dry_run:
                        self.message_user(request, f'校验通过。{summary}', level=messages.SUCCESS)
                    else:
                        self.message_user(request, f'导入完成。{summary}', level=messages.SUCCESS)
                        return redirect('admin:catalog_category_changelist')
        context = {
            **self.admin_site.each_context(request),
            'opts': self.model._meta,
            'title': '导入分类',
        }
        return render(request, 'admin/catalog/category/import_form.html', context)


@admin.register(CategoryAttribute)
class CategoryAttributeAdmin(admin.ModelAdmin):
    list_display = (
        'name',
        'category',
        'code',
        'data_type',
        'is_required',
        'is_filterable',
        'is_list_visible',
        'is_detail_visible',
        'sort_order',
        'is_active',
    )
    list_filter = ('category', 'data_type', 'is_required', 'is_filterable', 'is_active')
    search_fields = ('name', 'code', 'category__name')
    autocomplete_fields = ('category',)


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    form = ProductAdminForm
    list_display = ('name', 'style_code', 'brand', 'category', 'status', 'sort_order', 'has_product_image', 'active_sku_count', 'updated_at')
    list_filter = ('status', 'category', 'brand')
    search_fields = ('name', 'alias', 'style_code', 'cas_no', 'brand', 'skus__internal_sku_code')
    inlines = (ProductAttachmentInline,)
    readonly_fields = ('manage_product_images_link', 'manage_skus_link')
    actions = ('export_selected_products',)
    list_editable = ('sort_order',)
    change_list_template = 'admin/catalog/product/change_list.html'
    fieldsets = (
        (
            '基础信息',
            {
                'fields': (
                    'name',
                    'alias',
                    'style_code',
                    'cas_no',
                    'category_l1',
                    'category_l2',
                    'category_l3',
                    'brand',
                    'status',
                    'sort_order',
                )
            },
        ),
        ('产品图片资源', {'fields': ('manage_product_images_link',)}),
        ('具体型号', {'fields': ('manage_skus_link',)}),
        ('展示说明', {'fields': ('description', 'spec_summary', 'storage_info', 'safety_info', 'shipping_info')}),
        ('来源信息', {'fields': ('source_file_name', 'source_created_by')}),
    )

    def get_fieldsets(self, request, obj=None):
        base_fieldsets = (
            (
                '基础信息',
                {
                    'fields': (
                        'name',
                        'alias',
                        'style_code',
                        'cas_no',
                        'category_l1',
                        'category_l2',
                        'category_l3',
                        'brand',
                        'status',
                        'sort_order',
                    )
                },
            ),
            ('产品图片资源', {'fields': ('manage_product_images_link',)}),
            ('具体型号', {'fields': ('manage_skus_link',)}),
            ('展示说明', {'fields': ('description', 'spec_summary', 'storage_info', 'safety_info', 'shipping_info')}),
            ('来源信息', {'fields': ('source_file_name', 'source_created_by')}),
        )
        if obj and obj.skus.count() == 1:
            return [
                (
                    '具体型号',
                    {
                        'fields': (
                            'single_sku_code',
                            'single_sku_price',
                            'single_sku_stock_status',
                            'single_sku_attributes',
                            'single_sku_status',
                        )
                    },
                ),
                (
                    '基础信息',
                    {
                        'fields': (
                            'name',
                            'alias',
                            'style_code',
                            'cas_no',
                            'category_l1',
                            'category_l2',
                            'category_l3',
                            'brand',
                            'status',
                            'sort_order',
                        )
                    },
                ),
                ('产品图片资源', {'fields': ('manage_product_images_link',)}),
                ('展示说明', {'fields': ('description', 'spec_summary', 'storage_info', 'safety_info', 'shipping_info')}),
                ('来源信息', {'fields': ('source_file_name', 'source_created_by')}),
            ]
        return base_fieldsets

    def save_model(self, request, obj, form, change):
        cat_l3 = form.cleaned_data.get('category_l3')
        cat_l2 = form.cleaned_data.get('category_l2')
        if cat_l3:
            obj.category_id = cat_l3
        elif cat_l2:
            obj.category_id = cat_l2
        super().save_model(request, obj, form, change)
        form.save_single_sku()

    def _build_category_hierarchy(self):
        cats = list(
            Category.objects.filter(is_active=True)
            .select_related('parent', 'parent__parent')
            .order_by('sort_order', 'name')
        )
        by_parent = {}
        for cat in cats:
            by_parent.setdefault(cat.parent_id, []).append(cat)
        result = []
        for root in sorted(by_parent.get(None, []), key=lambda c: (c.sort_order, c.name)):
            node = {'pk': root.pk, 'name': root.name, 'children': []}
            for l2 in sorted(by_parent.get(root.pk, []), key=lambda c: (c.sort_order, c.name)):
                l2_node = {'pk': l2.pk, 'name': l2.name, 'children': []}
                for l3 in sorted(by_parent.get(l2.pk, []), key=lambda c: (c.sort_order, c.name)):
                    l2_node['children'].append({'pk': l3.pk, 'name': l3.name})
                node['children'].append(l2_node)
            result.append(node)
        return result

    def changeform_view(self, request, object_id=None, form_url='', extra_context=None):
        extra_context = extra_context or {}
        extra_context['category_hierarchy_json'] = json.dumps(self._build_category_hierarchy())
        return super().changeform_view(request, object_id, form_url, extra_context)

    class Media:
        css = {'all': ('admin/css/catalog-category-cascade.css',)}

    def get_urls(self):
        custom_urls = [
            path(
                'import/',
                self.admin_site.admin_view(self.import_products_view),
                name='catalog_product_import',
            ),
            path(
                'export-all/',
                self.admin_site.admin_view(self.export_all_products_view),
                name='catalog_product_export_all',
            ),
            path(
                'bulk-images/',
                self.admin_site.admin_view(self.bulk_product_images_view),
                name='catalog_product_bulk_images',
            ),
            path(
                'listing-import/',
                self.admin_site.admin_view(self.listing_import_view),
                name='catalog_product_listing_import',
            ),
            path(
                'listing-images/',
                self.admin_site.admin_view(self.listing_images_view),
                name='catalog_product_listing_images',
            ),
            path(
                'brand-sort/',
                self.admin_site.admin_view(self.brand_sort_view),
                name='catalog_product_brand_sort',
            ),
            path(
                '<path:object_id>/images/',
                self.admin_site.admin_view(self.product_images_view),
                name='catalog_product_images',
            ),
        ]
        return custom_urls + super().get_urls()

    def listing_import_view(self, request):
        if not self.has_change_permission(request):
            raise PermissionDenied
        if request.method == 'POST':
            uploaded_file = request.FILES.get('import_file')
            dry_run = request.POST.get('dry_run') == 'on'
            if not uploaded_file:
                self.message_user(request, '请选择 Excel 文件。', level=messages.ERROR)
            else:
                source_name = getattr(uploaded_file, 'name', '') or ''
                try:
                    result = import_listing_workbook(
                        uploaded_file,
                        dry_run=dry_run,
                        source_file_name=source_name,
                    )
                except Exception as exc:
                    self.message_user(request, f'导入失败：{exc}', level=messages.ERROR)
                else:
                    summary = (
                        f'产品新增 {result.created_products}、更新 {result.updated_products}；'
                        f'SKU 新增 {result.created_skus}、更新 {result.updated_skus}；'
                        f'失败 {len(result.failures)}'
                    )
                    if result.failures:
                        preview = '；'.join(result.failures[:5])
                        if len(result.failures) > 5:
                            preview += f'；还有 {len(result.failures) - 5} 条未显示'
                        self.message_user(
                            request,
                            f'{summary}。{preview}',
                            level=messages.WARNING,
                        )
                    elif dry_run:
                        self.message_user(request, f'校验通过。{summary}', level=messages.SUCCESS)
                    else:
                        self.message_user(request, f'导入完成。{summary}', level=messages.SUCCESS)
                        return redirect('admin:catalog_product_changelist')
        context = {
            **self.admin_site.each_context(request),
            'opts': self.model._meta,
            'title': '上架模板导入',
        }
        return render(request, 'admin/catalog/product/listing_import.html', context)

    def listing_images_view(self, request):
        if not self.has_change_permission(request):
            raise PermissionDenied
        if request.method == 'POST':
            archive = request.FILES.get('archive')
            if not archive:
                self.message_user(request, '请选择 ZIP 压缩包。', level=messages.ERROR)
            elif Path(archive.name).suffix.casefold() != '.zip':
                self.message_user(request, '请上传 ZIP 格式的压缩包。', level=messages.ERROR)
            else:
                try:
                    result: ListingImageImportResult = import_listing_image_archive(archive)
                except (OSError, ListingImageImportError) as error:
                    self.message_user(request, f'图片导入失败：{error}', level=messages.ERROR)
                else:
                    size_mb = result.uncompressed_bytes / (1024 * 1024)
                    note_parts = [
                        f'入库 {result.image_count} 张图片',
                        f'覆盖 {len(result.style_codes)} 个款式目录',
                        f'涉及 {len(result.sku_codes)} 个 SKU',
                    ]
                    if result.missing_skus:
                        sample = '、'.join(result.missing_skus[:5])
                        more = f'（还有 {len(result.missing_skus) - 5} 个）' if len(result.missing_skus) > 5 else ''
                        note_parts.append(
                            f'商品编码未在数据库中、已跳过 {len(result.missing_skus)} 个：{sample}{more}'
                        )
                    note_parts.append(f'解压后 {size_mb:.1f} MB')
                    self.message_user(request, '，'.join(note_parts), level=messages.SUCCESS)
                    return redirect('admin:catalog_product_changelist')
        context = {
            **self.admin_site.each_context(request),
            'opts': self.model._meta,
            'title': '上架模板图片上传',
        }
        return render(request, 'admin/catalog/product/listing_images.html', context)

    def bulk_product_images_view(self, request):
        if not self.has_change_permission(request):
            raise PermissionDenied

        if request.method == 'POST':
            archive = request.FILES.get('archive')
            confirmed = request.POST.get('confirm_replace') == 'on'
            if not archive:
                self.message_user(request, '请选择 ZIP 压缩包。', level=messages.ERROR)
            elif Path(archive.name).suffix.casefold() != '.zip':
                self.message_user(request, '请上传 ZIP 格式的压缩包。', level=messages.ERROR)
            elif not confirmed:
                self.message_user(
                    request,
                    '请确认同款式编码目录将被完全覆盖。',
                    level=messages.ERROR,
                )
            else:
                try:
                    result = import_product_image_archive(
                        archive,
                        known_style_codes=Product.objects.values_list('style_code', flat=True),
                    )
                except (OSError, ProductImageArchiveError) as error:
                    self.message_user(request, f'批量上传失败：{error}', level=messages.ERROR)
                else:
                    size_mb = result.uncompressed_bytes / (1024 * 1024)
                    self.message_user(
                        request,
                        f'批量上传完成：已完全覆盖 {len(result.style_codes)} 个款式目录，'
                        f'共 {result.image_count} 张图片，解压后 {size_mb:.1f} MB。',
                        level=messages.SUCCESS,
                    )
                    return redirect('admin:catalog_product_changelist')

        context = {
            **self.admin_site.each_context(request),
            'opts': self.model._meta,
            'title': '批量上传产品图片',
        }
        return render(request, 'admin/catalog/product/bulk_images.html', context)

    def product_images_view(self, request, object_id):
        product = self.get_object(request, object_id)
        if product is None:
            raise Http404
        if not self.has_change_permission(request, product):
            raise PermissionDenied

        asset_directory = product_style_directory(product)
        if not asset_directory:
            raise Http404

        if request.method == 'POST':
            action = request.POST.get('action')
            try:
                if action == 'upload':
                    image_type = request.POST.get('image_type')
                    directory_name = PRODUCT_IMAGE_DIRECTORY_NAMES.get(image_type)
                    if not directory_name:
                        raise ValidationError('图片类型无效。')
                    uploaded_files = request.FILES.getlist('images')
                    if not uploaded_files:
                        raise ValidationError('请选择要上传的图片。')
                    saved = [
                        save_product_image(uploaded_file, asset_directory / directory_name)
                        for uploaded_file in uploaded_files
                    ]
                    if image_type == 'main':
                        # 删除旧主图（主图透图目录下名为 主图.* 的文件）
                        main_dir = asset_directory / directory_name
                        if main_dir.is_dir():
                            for old_file in main_dir.iterdir():
                                if old_file.is_file() and old_file.name.startswith('主图.'):
                                    old_file.unlink()
                        # 将第一张新图片设为主图
                        promote_product_main_image(asset_directory, saved[0])
                    self.message_user(
                        request,
                        f'已上传 {len(saved)} 张{"主图" if image_type == "main" else "详情图"}。',
                        level=messages.SUCCESS,
                    )
                elif action == 'delete':
                    image_path = managed_product_image_path(product, request.POST.get('image_path', ''))
                    if not image_path.is_file():
                        raise ValidationError('图片不存在或已经删除。')
                    image_path.unlink()
                    self.message_user(request, f'已删除图片：{image_path.name}', level=messages.SUCCESS)
                elif action == 'set_main':
                    image_path = managed_product_image_path(product, request.POST.get('image_path', ''))
                    promoted = promote_product_main_image(asset_directory, image_path)
                    self.message_user(request, f'已设为产品主图：{promoted.name}', level=messages.SUCCESS)
                elif action == 'upload_document':
                    uploaded_files = request.FILES.getlist('files')
                    if not uploaded_files:
                        raise ValidationError('请选择要上传的文件。')
                    for uploaded_file in uploaded_files:
                        att = ProductAttachment(
                            product=product,
                            title=get_valid_filename(Path(uploaded_file.name).name),
                            is_public=True,
                        )
                        att.file.save(get_valid_filename(uploaded_file.name), uploaded_file)
                    self.message_user(
                        request,
                        f'已上传 {len(uploaded_files)} 个文档。',
                        level=messages.SUCCESS,
                    )
                elif action == 'delete_document':
                    doc_id = request.POST.get('document_id')
                    if not doc_id:
                        raise ValidationError('文档 ID 无效。')
                    try:
                        att = ProductAttachment.objects.get(pk=int(doc_id), product=product)
                        att.delete()
                        self.message_user(request, '已删除文档。', level=messages.SUCCESS)
                    except ProductAttachment.DoesNotExist:
                        raise ValidationError('文档不存在。')
                elif action == 'upload_carousel':
                    uploaded_files = request.FILES.getlist('carousel_images')
                    if not uploaded_files:
                        raise ValidationError('请选择要上传的图片。')
                    existing_carousel = product.attachments.filter(
                        title__startswith='轮播图'
                    ).count()
                    saved = []
                    for i, uploaded_file in enumerate(uploaded_files):
                        suffix = Path(uploaded_file.name).suffix.lower()
                        if suffix not in IMAGE_EXTENSIONS:
                            continue
                        idx = existing_carousel + i + 1
                        safe_name = f'轮播图{idx}{suffix}'
                        att = ProductAttachment(
                            product=product,
                            title=safe_name,
                            is_public=True,
                        )
                        att.file.save(safe_name, uploaded_file)
                        saved.append(safe_name)
                    if saved:
                        self.message_user(
                            request,
                            f'已上传 {len(saved)} 张轮播图。',
                            level=messages.SUCCESS,
                        )
                elif action == 'delete_carousel':
                    doc_id = request.POST.get('document_id')
                    if not doc_id:
                        raise ValidationError('文档 ID 无效。')
                    try:
                        att = ProductAttachment.objects.get(pk=int(doc_id), product=product, title__startswith='轮播图')
                        att.delete()
                        self.message_user(request, '已删除轮播图。', level=messages.SUCCESS)
                    except ProductAttachment.DoesNotExist:
                        raise ValidationError('轮播图不存在。')
                else:
                    raise ValidationError('无法识别的图片操作。')
            except (OSError, ValidationError) as error:
                message = error.messages[0] if isinstance(error, ValidationError) else str(error)
                self.message_user(request, f'操作失败：{message}', level=messages.ERROR)
            return redirect('admin:catalog_product_images', object_id=product.pk)

        images = product_admin_image_items(product)
        documents = [d for d in product.attachments.filter(is_public=True).order_by('-uploaded_at') if not d.title.startswith('轮播图')]
        carousel_images = product.attachments.filter(is_public=True, title__startswith='轮播图').order_by('title')
        context = {
            **self.admin_site.each_context(request),
            'opts': self.model._meta,
            'product': product,
            'title': f'管理产品图片：{product.name}',
            'main_images': images['main'],
            'detail_images': images['detail'],
            'documents': documents,
            'carousel_images': list(carousel_images),
            'max_upload_mb': MAX_PRODUCT_IMAGE_BYTES // (1024 * 1024),
        }
        return render(request, 'admin/catalog/product/images.html', context)

    @admin.action(description='导出所选产品')
    def export_selected_products(self, request, queryset):
        products = expand_product_queryset(queryset)
        if not products.exists():
            self.message_user(request, '没有可导出的产品。', level=messages.WARNING)
            return None
        return export_products_response(products, filename_prefix='selected-products')

    def export_all_products_view(self, request):
        return export_products_response(Product.objects.all())

    def import_products_view(self, request):
        if request.method == 'POST':
            uploaded_file = request.FILES.get('import_file')
            dry_run = request.POST.get('dry_run') == 'on'
            allow_missing_price = request.POST.get('allow_missing_price') == 'on'
            if not uploaded_file:
                self.message_user(request, '请选择 Excel 文件。', level=messages.ERROR)
            else:
                try:
                    result = import_products_file(
                        uploaded_file,
                        dry_run=dry_run,
                        allow_missing_price=allow_missing_price,
                        allow_missing_category=allow_missing_price,
                    )
                except Exception as exc:
                    self.message_user(request, f'导入失败：{exc}', level=messages.ERROR)
                else:
                    summary = (
                        f'产品新增 {result.created_products}，更新 {result.updated_products}；'
                        f'SKU 新增 {result.created_skus}，更新 {result.updated_skus}；'
                        f'失败 {len(result.failures)}'
                    )
                    if result.failures:
                        preview = '；'.join(result.failures[:5])
                        if len(result.failures) > 5:
                            preview += f'；还有 {len(result.failures) - 5} 条未显示'
                        self.message_user(request, f'{summary}。{preview}', level=messages.WARNING)
                    elif dry_run:
                        self.message_user(request, f'校验通过。{summary}', level=messages.SUCCESS)
                    else:
                        self.message_user(request, f'导入完成。{summary}', level=messages.SUCCESS)
                        return redirect('admin:catalog_product_changelist')
        context = {
            **self.admin_site.each_context(request),
            'opts': self.model._meta,
            'title': '导入产品',
        }
        return render(request, 'admin/catalog/product/import_form.html', context)

    def brand_sort_view(self, request):
        """按品牌批量调整产品排序号。

        GET: 选择品牌后展示该品牌下所有上架产品，可逐项填写排序号。
        POST: 把每行的 sort_order 写回数据库；其他字段不受影响。
        """
        if not self.has_change_permission(request):
            raise PermissionDenied

        # 收集所有出现过产品的品牌，按字母序展示；带 BrandOrder 优先。
        ordered_brands = list(
            BrandOrder.objects.filter(is_active=True)
            .values_list('brand', flat=True)
            .order_by('sort_order')
        )
        all_brands = list(
            Product.objects.exclude(brand='')
            .values_list('brand', flat=True)
            .distinct()
        )
        unordered_brands = sorted(b for b in all_brands if b not in ordered_brands)
        brands = ordered_brands + unordered_brands

        selected_brand = request.GET.get('brand') or request.POST.get('brand', '').strip()
        saved = False
        if request.method == 'POST':
            if not selected_brand:
                self.message_user(request, '请先选择品牌。', level=messages.ERROR)
            else:
                updates = 0
                for key, raw_value in request.POST.items():
                    if not key.startswith('order_'):
                        continue
                    try:
                        pk = int(key[len('order_'):])
                    except ValueError:
                        continue
                    try:
                        new_sort = int(str(raw_value).strip() or '0')
                    except ValueError:
                        new_sort = 0
                    new_sort = max(0, new_sort)
                    updated = Product.objects.filter(pk=pk, brand=selected_brand).update(
                        sort_order=new_sort,
                    )
                    updates += updated
                self.message_user(
                    request,
                    f'品牌「{selected_brand}」已更新 {updates} 个产品的排序号。',
                    level=messages.SUCCESS,
                )
                saved = True

        products = []
        if selected_brand:
            products = list(
                Product.objects.filter(brand=selected_brand)
                .select_related('category')
                .order_by('sort_order', 'name', 'id')
            )

        context = {
            **self.admin_site.each_context(request),
            'opts': self.model._meta,
            'title': '按品牌调整排序号',
            'brands': brands,
            'selected_brand': selected_brand,
            'products': products,
            'saved': saved,
        }
        return render(request, 'admin/catalog/product/brand_sort.html', context)

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == 'category':
            queryset = Category.objects.filter(is_active=True)
            object_id = request.resolver_match.kwargs.get('object_id')
            if object_id:
                product = Product.objects.filter(pk=object_id).only('category_id').first()
                if product and product.category_id:
                    queryset = Category.objects.filter(Q(is_active=True) | Q(pk=product.category_id))
            kwargs['queryset'] = ordered_category_queryset(queryset)
            formfield = super().formfield_for_foreignkey(db_field, request, **kwargs)
            formfield.label_from_instance = category_choice_label
            return formfield
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    @admin.display(boolean=True, description='有图片')
    def has_product_image(self, obj):
        asset_directory = product_style_directory(obj)
        return bool(
            obj.image
            or obj.remote_image_url
            or (asset_directory and asset_directory.is_dir() and main_image_from_directory(asset_directory))
        )

    @admin.display(description='产品图片')
    def manage_product_images_link(self, obj):
        if not obj or not obj.pk:
            return '请先保存产品，再上传产品图片。'
        url = reverse('admin:catalog_product_images', args=[obj.pk])
        images = product_admin_image_items(obj)
        return format_html(
            '<a class="button" href="{}">上传和管理产品图片</a>'
            '<p style="margin:8px 0 0;color:#666">当前主图区 {} 张，详情图区 {} 张；目录：product_catalog/{}</p>',
            url,
            len(images['main']),
            len(images['detail']),
            obj.style_code,
        )

    @admin.display(description='SKU / 特殊属性')
    def manage_skus_link(self, obj):
        if not obj or not obj.pk:
            return '请先保存产品系列，再管理具体型号。'
        url = reverse('admin:catalog_sku_changelist')
        sku_count = obj.skus.count()
        return format_html(
            '<a class="button" href="{}?product__id__exact={}">管理该系列的 {} 个具体型号</a>'
            '<p style="margin:8px 0 0;color:#666">价格、库存状态和特殊属性均在具体型号页面中编辑。</p>',
            url,
            obj.pk,
            sku_count,
        )


@admin.register(SKU)
class SKUAdmin(admin.ModelAdmin):
    form = SKUAdminForm
    list_display = (
        'internal_sku_code',
        'product',
        'jst_sku_id',
        'shop_sku_id',
        'price',
        'stock_status',
        'inventory_sync_enabled',
        'status',
        'customer_price_count',
        'has_sku_image',
    )
    list_filter = ('status', 'stock_status', 'inventory_sync_enabled', 'product__category', 'product__brand')
    search_fields = (
        'internal_sku_code',
        'jst_sku_id',
        'shop_sku_id',
        'source_style_code',
        'source_goods_name',
        'sku_attribute_text',
        'product__name',
        'product__brand',
    )
    autocomplete_fields = ('product',)
    readonly_fields = ('product_series_link', 'source_raw_row', 'customer_price_count')
    fieldsets = (
        ('基础信息', {'fields': ('product_series_link', 'product', 'internal_sku_code', 'jst_sku_id', 'shop_sku_id', 'status')}),
        ('来源信息', {'fields': ('source_goods_code', 'source_style_code', 'source_goods_name', 'source_raw_row')}),
        ('规格属性', {'fields': ('sku_attribute_text', 'color', 'package_spec', 'grade', 'unit', 'attributes')}),
        ('价格库存', {'fields': ('price', 'cost_price', 'purchase_price', 'list_price', 'moq', 'order_step', 'stock_status', 'inventory_sync_enabled')}),
        ('客户协议价', {'fields': ('customer_price_count',)}),
    )

    @admin.display(description='有图片', boolean=True)
    def has_sku_image(self, obj):
        from catalog.product_images import product_style_directory
        asset_directory = product_style_directory(obj.product)
        if not asset_directory or not asset_directory.is_dir():
            return False
        sku_dir = asset_directory / obj.internal_sku_code
        if sku_dir.is_dir():
            return any(path.is_file() and path.suffix.lower() in {'.jpg', '.jpeg', '.png', '.webp', '.avif'} for path in sku_dir.iterdir())
        return False

    @admin.display(description='所属产品系列')
    def product_series_link(self, obj):
        if not obj or not obj.product_id:
            return '请先选择所属产品。'
        url = reverse('admin:catalog_product_change', args=[obj.product_id])
        return format_html('<a class="button" href="{}">返回产品系列：{}</a>', url, obj.product)

    @admin.display(description='协议客户数')
    def customer_price_count(self, obj):
        if not obj or not obj.pk:
            return 0
        return obj.customer_prices.filter(is_active=True).count()


@admin.register(CustomerSKUPrice)
class CustomerSKUPriceAdmin(admin.ModelAdmin):
    list_display = (
        'customer',
        'sku',
        'price',
        'min_qty',
        'max_qty',
        'valid_from',
        'valid_to',
        'is_active',
        'updated_at',
    )
    list_filter = ('is_active', 'customer', 'sku__product__category')
    search_fields = ('customer__company_name', 'sku__internal_sku_code', 'sku__product__name', 'remark')
    autocomplete_fields = ('customer', 'sku')
    list_editable = ('price', 'is_active')
    date_hierarchy = 'updated_at'
    actions = ('disable_selected', 'enable_selected', 'export_selected_prices')
    change_list_template = 'admin/catalog/customerskuprice/change_list.html'

    def get_urls(self):
        custom_urls = [
            path(
                'import/',
                self.admin_site.admin_view(self.import_prices_view),
                name='catalog_customerskuprice_import',
            ),
            path(
                'export-all/',
                self.admin_site.admin_view(self.export_all_prices_view),
                name='catalog_customerskuprice_export_all',
            ),
        ]
        return custom_urls + super().get_urls()

    @admin.action(description='停用所选协议价')
    def disable_selected(self, request, queryset):
        updated = 0
        for record in queryset.select_related('customer', 'sku'):
            old_price = record.price
            record.is_active = False
            record.save(update_fields=['is_active', 'updated_at'])
            PriceHistory.objects.create(
                customer=record.customer,
                sku=record.sku,
                price_record=record,
                change_type=PriceHistory.ChangeType.DISABLE,
                old_price=old_price,
                new_price=old_price,
                operator=request.user,
            )
            updated += 1
        self.message_user(request, f'已停用 {updated} 条协议价。', level=messages.SUCCESS)

    @admin.action(description='启用所选协议价')
    def enable_selected(self, request, queryset):
        queryset.update(is_active=True)
        self.message_user(request, f'已启用 {queryset.count()} 条协议价。', level=messages.SUCCESS)

    @admin.action(description='导出所选协议价')
    def export_selected_prices(self, request, queryset):
        return export_customer_prices_response(queryset, filename_prefix='selected-customer-prices')

    def export_all_prices_view(self, request):
        return export_customer_prices_response(CustomerSKUPrice.objects.all(), filename_prefix='all-customer-prices')

    def import_prices_view(self, request):
        if request.method == 'POST':
            uploaded_file = request.FILES.get('import_file')
            dry_run = request.POST.get('dry_run') == 'on'
            if not uploaded_file:
                self.message_user(request, '请选择 Excel 文件。', level=messages.ERROR)
            else:
                try:
                    result = import_customer_prices_file(uploaded_file, operator=request.user, dry_run=dry_run)
                except Exception as exc:
                    self.message_user(request, f'导入失败：{exc}', level=messages.ERROR)
                else:
                    summary = (
                        f'新增 {result.created}，更新 {result.updated}，'
                        f'停用 {result.disabled}，失败 {len(result.failures)}'
                    )
                    if result.failures:
                        preview = '；'.join(result.failures[:5])
                        if len(result.failures) > 5:
                            preview += f'；还有 {len(result.failures) - 5} 条未显示'
                        self.message_user(request, f'{summary}。{preview}', level=messages.WARNING)
                    elif dry_run:
                        self.message_user(request, f'校验通过。{summary}', level=messages.SUCCESS)
                    else:
                        self.message_user(request, f'导入完成。{summary}', level=messages.SUCCESS)
                        return redirect('admin:catalog_customerskuprice_changelist')
        context = {
            **self.admin_site.each_context(request),
            'opts': CustomerSKUPrice._meta,
            'title': '导入客户协议价',
        }
        return render(request, 'admin/catalog/customerskuprice/import_form.html', context)

    def save_model(self, request, obj, form, change):
        old_price = None
        if change:
            old_price = form.initial.get('price')
        super().save_model(request, obj, form, change)
        PriceHistory.objects.create(
            customer=obj.customer,
            sku=obj.sku,
            price_record=obj,
            change_type=PriceHistory.ChangeType.UPDATE if change else PriceHistory.ChangeType.CREATE,
            old_price=old_price,
            new_price=obj.price,
            operator=request.user,
        )


@admin.register(PriceHistory)
class PriceHistoryAdmin(admin.ModelAdmin):
    list_display = ('created_at', 'change_type', 'customer', 'sku', 'old_price', 'new_price', 'operator')
    list_filter = ('change_type', 'customer')
    search_fields = ('customer__company_name', 'sku__internal_sku_code', 'reason')
    readonly_fields = (
        'customer',
        'sku',
        'price_record',
        'change_type',
        'old_price',
        'new_price',
        'reason',
        'operator',
        'created_at',
    )
    date_hierarchy = 'created_at'

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(ProductAttachment)
class ProductAttachmentAdmin(admin.ModelAdmin):
    list_display = ('title', 'product', 'sku', 'attachment_type', 'version', 'is_public', 'uploaded_at')
    list_filter = ('attachment_type', 'is_public', 'uploaded_at')
    search_fields = ('title', 'product__name', 'sku__internal_sku_code', 'version')
    autocomplete_fields = ('product', 'sku')


@admin.register(HomeCategory)
class HomeCategoryAdmin(admin.ModelAdmin):
    list_display = ('display_title', 'category', 'sort_order', 'is_active', 'updated_at')
    list_filter = ('is_active',)
    list_editable = ('sort_order', 'is_active')
    search_fields = ('title', 'category__name', 'category__slug')
    autocomplete_fields = ('category',)
    readonly_fields = ('preview_image', 'created_at', 'updated_at')

    fieldsets = (
        (None, {
            'fields': ('category', 'title', 'image', 'preview_image', 'link_url'),
        }),
        ('图片显示', {
            'fields': ('image_display',),
            'description': '控制图片在分类卡片中的显示方式',
        }),
        ('显示控制', {
            'fields': ('sort_order', 'is_active'),
        }),
        ('时间', {
            'fields': ('created_at', 'updated_at'),
        }),
    )

    def preview_image(self, obj):
        if obj.image:
            return format_html('<img src="{}" style="max-height:80px;border-radius:6px;">', obj.image.url)
        return '（未上传图片）'

    preview_image.short_description = '图片预览'


class HomeSceneProductInline(admin.TabularInline):
    model = HomeSceneProduct
    extra = 0
    autocomplete_fields = ('product',)
    fields = ('product', 'sort_order')
    verbose_name = '场景商品'
    verbose_name_plural = '场景商品'


@admin.register(HomeScene)
class HomeSceneAdmin(admin.ModelAdmin):
    list_display = ('title', 'slug', 'sort_order', 'is_active', 'preview_banner', 'product_count', 'updated_at')
    list_filter = ('is_active',)
    list_editable = ('sort_order', 'is_active')
    search_fields = ('title', 'slug', 'subtitle', 'description')
    prepopulated_fields = {'slug': ('title',)}
    readonly_fields = ('preview_banner', 'created_at', 'updated_at')
    inlines = (HomeSceneProductInline,)
    fieldsets = (
        (None, {
            'fields': ('title', 'subtitle', 'description', 'slug', 'banner_image', 'icon', 'preview_banner'),
        }),
        ('显示控制', {
            'fields': ('sort_order', 'is_active'),
        }),
        ('时间', {
            'fields': ('created_at', 'updated_at'),
        }),
    )

    def preview_banner(self, obj):
        if obj.banner_image:
            return format_html(
                '<img src="{}" style="max-height:90px;border-radius:6px;">',
                obj.banner_image.url,
            )
        return '（未上传横幅）'

    preview_banner.short_description = '横幅预览'

    @admin.display(description='商品数')
    def product_count(self, obj):
        return obj.scene_products.count()

    formfield_overrides = {
        models.TextField: {'widget': forms.Textarea(attrs={'rows': 4, 'style': 'width: 95%; max-width: 760px;'})},
    }


class HomeBrandForm(forms.ModelForm):
    name = forms.ChoiceField(label='品牌名称', required=True, choices=[('', '— 选择已有品牌 —')])

    class Meta:
        model = HomeBrand
        # 品牌 Key / 跳转链接 后台不再使用，从表单中移除
        fields = ('name', 'logo', 'description', 'sort_order', 'is_active')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # 预填当前值
        current = self.initial.get('name') or (self.instance.name if self.instance and self.instance.pk else '')
        choices = [('', '— 选择已有品牌 —')]
        existing = (
            Product.objects.exclude(brand='')
            .values_list('brand', flat=True)
            .distinct()
            .order_by('brand')
        )
        for brand in existing:
            choices.append((brand, brand))
        if current and not any(c[0] == current for c in choices):
            choices.append((current, current))
        self.fields['name'].choices = choices

    class Media:
        js = ('admin/js/catalog-homebrand.js',)


@admin.register(HomeBrand)
class HomeBrandAdmin(admin.ModelAdmin):
    form = HomeBrandForm
    list_display = ('display_name', 'preview_logo', 'sort_order', 'is_active', 'updated_at')
    list_filter = ('is_active',)
    list_editable = ('sort_order', 'is_active')
    search_fields = ('name', 'description')
    readonly_fields = ('preview_logo', 'created_at', 'updated_at')

    def get_urls(self):
        custom_urls = [
            path(
                'api-brands/',
                self.admin_site.admin_view(self.api_brands_view),
                name='catalog_homebrand_api_brands',
            ),
        ]
        return custom_urls + super().get_urls()

    def api_brands_view(self, request):
        from django.http import JsonResponse
        brands = list(
            Product.objects.exclude(brand='')
            .values_list('brand', flat=True)
            .distinct()
            .order_by('brand')
        )
        return JsonResponse(brands, safe=False)

    fieldsets = (
        (None, {
            'fields': ('name', 'logo', 'preview_logo', 'description'),
        }),
        ('显示控制', {
            'fields': ('sort_order', 'is_active'),
            'description': '调整品牌卡片的展示顺序与启用状态；排序值小的靠前。',
        }),
        ('时间', {
            'fields': ('created_at', 'updated_at'),
        }),
    )

    def preview_logo(self, obj):
        if obj.logo:
            return format_html(
                '<img src="{}" style="max-height:60px;max-width:160px;background:#f8fafc;padding:6px;border-radius:6px;">',
                obj.logo.url,
            )
        return '（未上传 Logo）'

    preview_logo.short_description = 'Logo 预览'


@admin.register(BrandOrder)
class BrandOrderAdmin(admin.ModelAdmin):
    """商品目录品牌筛选的自定义排序管理"""
    list_display = ('brand', 'sort_order', 'is_active', 'updated_at')
    list_filter = ('is_active',)
    list_editable = ('sort_order', 'is_active')
    search_fields = ('brand',)
    list_per_page = 100

    def get_form(self, request, obj=None, **kwargs):
        """动态构建品牌下拉框，仅显示产品中已存在的品牌。"""
        class BrandOrderDynamicForm(forms.ModelForm):
            class Meta:
                model = BrandOrder
                fields = ('brand', 'sort_order', 'is_active')

            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                current = (
                    self.initial.get('brand')
                    or (self.instance.brand if self.instance and self.instance.pk else '')
                )
                existing = list(
                    Product.objects.exclude(brand='')
                    .order_by('brand')
                    .values_list('brand', flat=True)
                    .distinct()
                )
                # 已下架或已被删除但当前记录仍引用的品牌，也保留在下拉中
                if current and current not in existing:
                    existing.append(current)
                self.fields['brand'] = forms.ChoiceField(
                    label='品牌名称',
                    required=True,
                    choices=[('', '— 选择已有品牌 —')] + [(b, b) for b in existing],
                )

        kwargs['form'] = BrandOrderDynamicForm
        return super().get_form(request, obj, **kwargs)

    fieldsets = (
        (None, {
            'fields': ('brand',),
            'description': '从下拉框中选择产品中已存在的品牌；如选项为空，请先在产品管理中录入品牌。',
        }),
        ('显示控制', {
            'fields': ('sort_order', 'is_active'),
            'description': '排序值小的靠前；关闭启用后该品牌不在商品目录筛选中显示。',
        }),
    )

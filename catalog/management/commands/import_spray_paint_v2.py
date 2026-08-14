"""
Management command to import spray paint (自喷漆) products from Excel + image folders.
Each model (e.g. B-1088) = one Product; each color = one SKU.
Sales unit is the color name, not the full title.

Usage:
  PYTHONPATH=/tmp/xlrd_pkg .venv/bin/python manage.py import_spray_paint_v2 \\
    "docs/自喷漆-非盖亚发品模板保赐利B-1088和镀铬.xls" \\
    "docs/202601140000247_自喷漆_图片模板【以此文件夹打包】" \\
    --dry-run
"""
import os
import shutil
from collections import defaultdict
from pathlib import Path

from django.core.files import File
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils.text import slugify

try:
    import xlrd
except ImportError:
    import sys
    sys.path.insert(0, '/tmp/xlrd_pkg')
    import xlrd

from catalog.models import (
    Category,
    CategoryAttribute,
    Product,
    ProductAttachment,
    PublishStatus,
    SKU,
    StockStatus,
)


def clean(v):
    if v is None:
        return ''
    if isinstance(v, float):
        if v == int(v):
            return str(int(v))
        return f'{v:.4g}'
    return str(v).strip()


def parse_decimal(v):
    try:
        s = clean(v).replace(',', '').replace('，', '')
        return __import__('decimal').Decimal(s) if s else None
    except Exception:
        return None


def parse_int(v):
    try:
        return int(float(clean(v).replace(',', '').replace('，', '')))
    except Exception:
        return None


def parse_spray_title(title):
    """解析'保赐利（BOTNY） 自动喷漆 B-1088 C3时风绿 200g/400mL'返回各字段。"""
    parts = [p.strip() for p in title.split() if p.strip()]
    brand = parts[0] if len(parts) > 0 else ''
    # 产品名称: 前3段 "品牌 自动喷漆 型号"
    product_name = ' '.join(parts[:3]) if len(parts) >= 3 else title
    model = parts[2] if len(parts) > 2 else ''
    # 颜色色号: 最后一段 "C3时风绿"（第一个含汉字的段）
    color_name = ''
    for p in parts[3:]:
        color_name = p
        break  # 取紧跟型号后的那段
    # 包装规格: "200g/400mL"
    spec = parts[-1] if parts else ''
    return brand, product_name, model, color_name, spec


class Command(BaseCommand):
    help = '从京东自喷漆发品模板 Excel + 图片文件夹导入商品（按型号聚合）和图片'

    def add_arguments(self, parser):
        parser.add_argument('excel_file', help='Excel 文件路径 (.xls)')
        parser.add_argument('image_folder', help='图片文件夹路径')
        parser.add_argument('--dry-run', action='store_true', help='只校验不写入')

    def handle(self, *args, **options):
        excel_path = Path(options['excel_file'])
        image_folder = Path(options['image_folder'])
        dry_run = options['dry_run']

        if not excel_path.exists():
            self.stderr.write(self.style.ERROR(f'文件不存在：{excel_path}'))
            return
        if not image_folder.exists():
            self.stderr.write(self.style.ERROR(f'图片文件夹不存在：{image_folder}'))
            return

        wb = xlrd.open_workbook(str(excel_path))
        if '发品模板' not in wb.sheet_names():
            self.stderr.write(self.style.ERROR('缺少"发品模板"工作表'))
            return
        ws = wb.sheet_by_name('发品模板')

        headers = [clean(ws.cell_value(7, c)) for c in range(ws.ncols)]
        col = {h.split('\n')[0].replace('(必填)', '').strip(): c for c, h in enumerate(headers) if h}

        spray_cat = Category.objects.filter(name='自喷漆', is_active=True).first()
        if not spray_cat:
            self.stderr.write(self.style.ERROR('找不到"自喷漆"分类'))
            return
        self.stdout.write(f'分类：{spray_cat.name} (pk={spray_cat.pk})')

        # 扫描图片文件夹
        image_dirs = {}
        for d in image_folder.iterdir():
            if d.is_dir():
                image_dirs[d.name] = d
        self.stdout.write(f'图片文件夹数: {len(image_dirs)} 个')

        self._ensure_attributes(spray_cat)

        # 第一步：读取所有行，按型号分组
        # model_key -> {brand, product_name, model, specs: [{img_id, color, color_code, net_weight, capacity, price, ...}]}
        model_groups = defaultdict(lambda: {
            'brand': '', 'product_name': '', 'model': '',
            'specs': [],
        })

        for row_idx in range(8, ws.nrows):
            row = [ws.cell_value(row_idx, c) for c in range(ws.ncols)]

            img_id = clean(row[col.get('图片文件夹唯一标识', 0)])
            title = clean(row[col.get('商品标题', 1)])
            unit = clean(row[col.get('销售单位-下拉选择', 5)])
            pkg_list = clean(row[col.get('包装清单', 9)])
            color = clean(row[col.get('类目属性2-颜色', col.get('类目属性2-颜色(必填)', 34))])
            color_code = clean(row[col.get('类目属性2-色号', col.get('类目属性2-色号(必填)', 35))])
            net_weight = clean(row[col.get('类目属性2-净含量', col.get('类目属性2-净含量(必填)', 36))])
            temp_use = clean(row[col.get('类目属性2-使用温度', 37)])
            capacity = clean(row[col.get('类目属性45-容量(L)', 38)])
            dry_time = clean(row[col.get('类目属性45-干燥时间', 39)])
            scope = clean(row[col.get('类目属性46-适用范围', 40)])
            market_price = parse_decimal(row[col.get('市场价(必填)\n市场价>京东价，京东价≥采购价', 41)])
            cost_price = parse_decimal(row[col.get('采购价(必填)\n市场价>京东价，京东价≥采购价', 42)])
            jd_price = parse_decimal(row[col.get('京东价(必填)\n市场价>京东价，京东价≥采购价', 43)])
            barcode = clean(row[col.get('商品条形码', 48)])
            item_no = clean(row[col.get('货号', 49)])
            origin = clean(row[col.get('产地', 3)])

            if not img_id or not title:
                continue

            brand, product_name, model, color_name, spec = parse_spray_title(title)
            if not model:
                model = 'UNKNOWN'
            key = f'{brand}-{model}'

            group = model_groups[key]
            group['brand'] = brand
            group['product_name'] = product_name
            group['model'] = model
            group['specs'].append({
                'img_id': img_id,
                'title': title,
                'color': color or color_name,
                'color_code': color_code,
                'net_weight': net_weight,
                'temp_use': temp_use,
                'capacity': capacity,
                'dry_time': dry_time,
                'scope': scope,
                'market_price': market_price,
                'cost_price': cost_price,
                'jd_price': jd_price,
                'barcode': barcode,
                'item_no': item_no,
                'origin': origin,
                'pkg_list': pkg_list,
                'spec': spec,
                'unit': unit,
            })

        self.stdout.write(f'解析到 {len(model_groups)} 个型号组')

        products_created = 0
        skus_created = 0
        images_copied = 0

        with transaction.atomic():
            for model_key, group in sorted(model_groups.items()):
                brand = group['brand']
                product_name = group['product_name']
                model = group['model']
                specs = group['specs']

                # 一个 Product = 一个型号
                safe_model = slugify(model)[:30] or model[:30]
                style_code = f'BOTNY-{safe_model}'

                product, prod_created = Product.objects.get_or_create(
                    style_code=style_code,
                    defaults={
                        'name': product_name,
                        'alias': '',
                        'brand': brand,
                        'category': spray_cat,
                        'description': f'品牌：{brand} | 型号：{model}\n（多色可选，规格见下方型号列表）',
                        'spec_summary': '',
                        'source_file_name': excel_path.name,
                        'status': PublishStatus.PUBLISHED,
                    },
                )
                products_created += int(prod_created)
                main_image_imported = False

                for i, spec in enumerate(specs):
                    img_dir = image_dirs.get(spec['img_id'])
                    sku_suffix = f'{i+1:02d}'

                    # 第一个有图片的颜色设主图，其他只复制附件
                    do_set_main = (img_dir and not main_image_imported)
                    if img_dir:
                        self._import_images(product, img_dir, dry_run, set_main=do_set_main)
                        if do_set_main:
                            main_image_imported = True
                        images_copied += 1

                    # source_goods_name = 颜色名（销售单位），用于 display_name
                    source_goods_name = spec['color']

                    sku_code = f'{style_code}-{sku_suffix}'
                    sku, sku_created = SKU.objects.get_or_create(
                        internal_sku_code=sku_code,
                        defaults={
                            'product': product,
                            'source_goods_name': source_goods_name,
                            'source_style_code': style_code,
                            'color': spec['color'],
                            'sku_attribute_text': f'{spec["color"]} {spec["net_weight"]}',
                            'package_spec': spec['spec'],
                            'unit': spec['unit'] or '个',
                            'price': spec['jd_price'],
                            'purchase_price': spec['cost_price'],
                            'list_price': spec['market_price'],
                            'source_raw_row': {
                                'img_id': spec['img_id'],
                                'color_code': spec['color_code'],
                                'net_weight': spec['net_weight'],
                                'temp_use': spec['temp_use'],
                                'capacity': spec['capacity'],
                                'dry_time': spec['dry_time'],
                                'scope': spec['scope'],
                                'barcode': spec['barcode'],
                                'item_no': spec['item_no'],
                                'pkg_list': spec['pkg_list'],
                                'origin': spec['origin'],
                                'model': model,
                                'title': spec['title'],
                            },
                            'attributes': {
                                'color': spec['color'],
                                'color_code': spec['color_code'],
                                'net_weight': spec['net_weight'],
                                'capacity': spec['capacity'],
                            },
                            'stock_status': StockStatus.IN_STOCK,
                            'status': PublishStatus.PUBLISHED,
                        },
                    )
                    skus_created += int(sku_created)

            if dry_run:
                transaction.set_rollback(True)

        self.stdout.write(self.style.SUCCESS(
            f'导入完成' if not dry_run else '校验完成，未写入'
        ))
        self.stdout.write(f'型号组: {len(model_groups)}，Product: {products_created}，SKU: {skus_created}，主图: {images_copied}')

    def _ensure_attributes(self, category):
        attrs = {
            'color': ('颜色', 'text'),
            'color_code': ('色号', 'text'),
            'net_weight': ('净含量', 'number'),
            'capacity': ('容量(L)', 'number'),
            'dry_time': ('干燥时间', 'text'),
            'scope': ('适用范围', 'text'),
        }
        from catalog.models import AttributeDataType
        dt_map = {'text': AttributeDataType.TEXT, 'number': AttributeDataType.NUMBER}
        for code, (name, dtype) in attrs.items():
            CategoryAttribute.objects.get_or_create(
                category=category,
                code=code,
                defaults={
                    'name': name,
                    'data_type': dt_map.get(dtype, AttributeDataType.TEXT),
                    'is_filterable': True,
                    'is_list_visible': True,
                    'is_detail_visible': True,
                    'is_active': True,
                },
            )

    def _import_images(self, product, img_dir, dry_run, set_main=True):
        """
        Copy images for one color folder.
        Returns number of images copied.
        """
        import django.conf
        media_root = Path(django.conf.settings.MEDIA_ROOT)

        main_folder = img_dir / '主图和透图'
        detail_folder = img_dir / '详情图'

        main_file = None
        transparent_file = None
        main_detail_files = []
        detail_files = []

        if main_folder.is_dir():
            for f in sorted(main_folder.iterdir()):
                if not f.is_file():
                    continue
                fname = f.name
                if fname == f'{img_dir.name}.jpg':
                    main_file = f
                elif fname.startswith('TMT') and fname.endswith('.png'):
                    transparent_file = f
                elif fname.endswith('.jpg') and not fname.startswith('TMT'):
                    main_detail_files.append(f)

        if detail_folder.is_dir():
            for f in sorted(detail_folder.iterdir()):
                if f.is_file() and f.suffix.lower() in ('.jpg', '.jpeg', '.png'):
                    detail_files.append(f)

        if dry_run:
            self.stdout.write(
                f'  [dry] {product.style_code}: '
                f'main={main_file.name if main_file else None}, '
                f'main_detail={len(main_detail_files)}, detail={len(detail_files)}'
            )
            return

        product_dir = Path(media_root) / 'products' / product.style_code
        product_dir.mkdir(parents=True, exist_ok=True)

        # 主图
        if set_main and main_file:
            dest = product_dir / f'0_main{main_file.suffix}'
            shutil.copy2(main_file, dest)
            with open(dest, 'rb') as fh:
                product.image.save(dest.name, File(fh), save=True)

        # 透图
        if transparent_file:
            dest = product_dir / f'0_transparent{transparent_file.suffix}'
            shutil.copy2(transparent_file, dest)
            rel_path = f'products/{product.style_code}/{dest.name}'
            with open(dest, 'rb') as fh:
                att = ProductAttachment(
                    product=product,
                    title=f'{product.name} 透明图',
                    is_public=True,
                )
                att.file.save(rel_path, File(fh), save=True)

        # 主图细节图
        for idx, src_file in enumerate(main_detail_files):
            dest = product_dir / f'{idx+1}_{src_file.name}'
            shutil.copy2(src_file, dest)
            rel_path = f'products/{product.style_code}/{dest.name}'
            with open(dest, 'rb') as fh:
                att = ProductAttachment(
                    product=product,
                    title=f'{product.name} 主图细节 {idx+1}',
                    is_public=True,
                )
                att.file.save(rel_path, File(fh), save=True)

        # 详情图（d+数字前缀）
        for idx, src_file in enumerate(detail_files):
            dest = product_dir / f'd{idx+1}_{src_file.name}'
            shutil.copy2(src_file, dest)
            rel_path = f'products/{product.style_code}/{dest.name}'
            with open(dest, 'rb') as fh:
                att = ProductAttachment(
                    product=product,
                    title=f'{product.name} 详情图 {idx+1}',
                    is_public=True,
                )
                att.file.save(rel_path, File(fh), save=True)

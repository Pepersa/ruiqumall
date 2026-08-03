"""
Management command to import spray paint (自喷漆) products from Excel + image folders.

Usage:
  python manage.py import_spray_paint <excel_file> <image_folder> [--dry-run]

Excel: "自喷漆-非盖亚发品模板保赐利B-1088和镀铬.xls"
Image folder: "202601140000247_自喷漆_图片模板【以此文件夹打包】/"
"""
import os
import shutil
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


class Command(BaseCommand):
    help = '从京东自喷漆发品模板 Excel + 图片文件夹导入商品和图片'

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

        # 表头在第8行（索引7）
        headers = [clean(ws.cell_value(7, c)) for c in range(ws.ncols)]
        col = {h.split('\n')[0].replace('(必填)', '').strip(): c for c, h in enumerate(headers) if h}

        # 找到自喷漆分类
        spray_cat = Category.objects.filter(name='自喷漆', is_active=True).first()
        if not spray_cat:
            self.stderr.write(self.style.ERROR('找不到"自喷漆"分类'))
            return
        self.stdout.write(f'分类：{spray_cat.name} (pk={spray_cat.pk})')

        # 扫描图片文件夹（按颜色 ID 索引）
        image_dirs = {}
        for d in image_folder.iterdir():
            if d.is_dir():
                image_dirs[d.name] = d

        self.stdout.write(f'图片文件夹数: {len(image_dirs)} 个')

        # 确保分类属性存在
        attr_map = self._ensure_attributes(spray_cat)

        products_created = 0
        skus_created = 0
        images_copied = 0
        failures = []

        with transaction.atomic():
            for row_idx in range(8, ws.nrows):
                row = [ws.cell_value(row_idx, c) for c in range(ws.ncols)]

                img_id = clean(row[col.get('图片文件夹唯一标识', 0)])
                title = clean(row[col.get('商品标题', 1)])
                brand = clean(row[col.get('品牌名称-下拉选择', 2)])
                origin = clean(row[col.get('产地', 3)])
                model = clean(row[col.get('型号', 4)])
                unit = clean(row[col.get('销售单位-下拉选择', 5)])
                spec = clean(row[col.get('包装规格', 8)])
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
                weight = parse_decimal(row[col.get('商品重量(必填，单位：kg 含包装)', 44)])
                length = parse_int(row[col.get('长(正整数 必填，单位：毫米 含包装)', 45)])
                wide = parse_int(row[col.get('宽(正整数 必填，单位：毫米 含包装)', 46)])
                height = parse_int(row[col.get('高(正整数 必填，单位：毫米 含包装)', 47)])
                barcode = clean(row[col.get('商品条形码', 48)])
                item_no = clean(row[col.get('货号', 49)])

                if not img_id or not title:
                    continue

                # 查找图片目录
                img_dir = image_dirs.get(img_id)

                # 生成 style_code
                safe_id = slugify(img_id.replace(' ', '-'))[:30] or img_id[:30]
                style_code = f'BOTNY-B1088-{safe_id}'

                # 创建/获取 Product
                product, prod_created = Product.objects.get_or_create(
                    style_code=style_code,
                    defaults={
                        'name': title,
                        'alias': f'{brand} {color}',
                        'brand': brand,
                        'category': spray_cat,
                        'description': f'品牌：{brand} | 型号：{model} | 产地：{origin}\n包装清单：{pkg_list}',
                        'spec_summary': f'{color} {net_weight} | {capacity}',
                        'source_file_name': excel_path.name,
                        'status': PublishStatus.PUBLISHED,
                    },
                )

                products_created += int(prod_created)

                # 创建 SKU
                sku_code = f'{style_code}-01'
                sku, sku_created = SKU.objects.get_or_create(
                    internal_sku_code=sku_code,
                    defaults={
                        'product': product,
                        'color': color,
                        'sku_attribute_text': f'{color} {net_weight}',
                        'package_spec': f'{spec}{"/" + unit if unit else ""}',
                        'unit': unit,
                        'price': jd_price,
                        'purchase_price': cost_price,
                        'list_price': market_price,
                        'source_raw_row': {
                            'img_id': img_id,
                            'color_code': color_code,
                            'net_weight': net_weight,
                            'temp_use': temp_use,
                            'capacity': capacity,
                            'dry_time': dry_time,
                            'scope': scope,
                            'barcode': barcode,
                            'item_no': item_no,
                            'pkg_list': pkg_list,
                            'origin': origin,
                            'model': model,
                            'weight': str(weight) if weight else None,
                            'length': length,
                            'width': wide,
                            'height': height,
                        },
                        'attributes': {
                            'color': color,
                            'color_code': color_code,
                            'net_weight': net_weight,
                            'capacity': capacity,
                        },
                        'stock_status': StockStatus.IN_STOCK,
                        'status': PublishStatus.PUBLISHED,
                    },
                )
                skus_created += int(sku_created)

                # 处理图片
                if img_dir:
                    self._import_images(product, img_dir, dry_run)
                    images_copied += 1

            if dry_run:
                transaction.set_rollback(True)

        self.stdout.write(self.style.SUCCESS(
            f'导入完成' if not dry_run else '校验完成，未写入'
        ))
        self.stdout.write(f'商品: {products_created}，SKU: {skus_created}，图片: {images_copied}')
        if failures:
            self.stdout.write(f'失败: {len(failures)}')
            for f in failures[:20]:
                self.stdout.write(f'  {f}')

    def _ensure_attributes(self, category):
        attrs = {
            'color': ('颜色', 'color', 'text'),
            'color_code': ('色号', 'color_code', 'text'),
            'net_weight': ('净含量', 'net_weight', 'number'),
            'capacity': ('容量(L)', 'capacity', 'number'),
            'dry_time': ('干燥时间', 'dry_time', 'text'),
            'scope': ('适用范围', 'scope', 'text'),
        }
        from catalog.models import AttributeDataType
        dt_map = {'text': AttributeDataType.TEXT, 'number': AttributeDataType.NUMBER}
        result = {}
        for code, (name, slug, dtype) in attrs.items():
            obj, _ = CategoryAttribute.objects.get_or_create(
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
            result[code] = obj
        return result

    def _import_images(self, product, img_dir, dry_run):
        from catalog.models import ProductAttachment
        import django.conf
        media_root = Path(django.conf.settings.MEDIA_ROOT)

        # 主图：找 {id}.jpg
        main_candidates = []
        detail_images = []

        for f in img_dir.iterdir():
            if not f.is_file():
                continue
            fname = f.name
            if fname == f'{img_dir.name}.jpg' or fname == f'{img_dir.name}.png':
                # 主图
                pass
            elif fname.startswith('TMT') and fname.endswith('.png'):
                # 透图
                pass
            elif fname.startswith('主图') and fname.endswith('.jpg'):
                pass
            elif img_dir.name in ['主图和透图', '详情图']:
                pass

        # 遍历子目录
        main_folder = img_dir / '主图和透图'
        detail_folder = img_dir / '详情图'

        files_to_copy = []
        main_file = None
        transparent_file = None

        if main_folder.is_dir():
            for f in sorted(main_folder.iterdir()):
                if not f.is_file():
                    continue
                fname = f.name
                # 主图：颜色ID.jpg
                if fname == f'{img_dir.name}.jpg':
                    main_file = f
                # 透明图：TMT开头 .png
                elif fname.startswith('TMT') and fname.endswith('.png'):
                    transparent_file = f
                # 其他主图细节图
                elif fname.endswith('.jpg'):
                    files_to_copy.append(('main_detail', f))

        if detail_folder.is_dir():
            for f in sorted(detail_folder.iterdir()):
                if f.is_file() and f.suffix.lower() in ('.jpg', '.jpeg', '.png'):
                    files_to_copy.append(('detail', f))

        if dry_run:
            self.stdout.write(f'  [dry] {product.style_code}: main={main_file.name if main_file else None}')
            return

        product_dir = Path(media_root) / 'products' / product.style_code
        product_dir.mkdir(parents=True, exist_ok=True)

        # 复制主图到 media/products/ 下
        if main_file:
            dest = product_dir / f'0_main{main_file.suffix}'
            shutil.copy2(main_file, dest)
            with open(dest, 'rb') as fh:
                product.image.save(dest.name, File(fh), save=True)

        # 复制透图到附件
        if transparent_file:
            dest = product_dir / f'0_transparent{transparent_file.suffix}'
            shutil.copy2(transparent_file, dest)
            rel_path = str(dest.relative_to(media_root))
            with open(dest, 'rb') as fh:
                att = ProductAttachment(
                    product=product,
                    title=f'{product.name} 透明图',
                    is_public=True,
                )
                att.file.save(rel_path, File(fh), save=True)

        # 复制其他主图细节图和详情图
        for idx, (kind, src_file) in enumerate(files_to_copy):
            dest = product_dir / f'{idx+1}_{src_file.name}'
            shutil.copy2(src_file, dest)
            kind_label = '主图细节' if kind == 'main_detail' else '详情图'
            rel_path = str(dest.relative_to(media_root))
            with open(dest, 'rb') as fh:
                att = ProductAttachment(
                    product=product,
                    title=f'{product.name} {kind_label} {idx+1}',
                    is_public=True,
                )
                att.file.save(rel_path, File(fh), save=True)

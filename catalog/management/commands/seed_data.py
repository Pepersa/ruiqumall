"""
Management command to seed the database with sample product data
for demonstration and testing purposes.
"""
import random
from decimal import Decimal

from django.core.management.base import BaseCommand

from catalog.models import (
    AttributeDataType,
    Category,
    CategoryAttribute,
    Product,
    PublishStatus,
    SKU,
    StockStatus,
)


# ===== Product reference data =====
BRANDS = [
    '壳牌', '美孚', '嘉实多', '道达尔', '长城',
    '科慕', '杜邦', '赢创', '索尔维', '万华',
    '汉高', '3M', '陶氏', '巴斯夫', '西卡',
]

PACKAGE_SPECS = [
    '1L/桶', '4L/桶', '18L/桶', '200L/桶',
    '1kg/桶', '5kg/桶', '20kg/桶',
    '250ml/瓶', '500ml/瓶', '1L/瓶',
    '15kg/桶', '25kg/桶',
]

UNITS = ['桶', '瓶', 'kg', 'L', '箱', '个', '支']


def _make_slug(name):
    """Generate a URL-safe slug, preserving Chinese characters."""
    import re
    s = name.lower().strip()
    # Replace spaces and special chars with hyphens
    s = re.sub(r'[\s/\\]+', '-', s)
    # Keep Chinese chars and alphanumeric
    s = re.sub(r'[^a-z0-9\u4e00-\u9fff-]', '', s)
    s = re.sub(r'-+', '-', s)
    s = s.strip('-')
    return s


class Command(BaseCommand):
    help = 'Seed database with sample product data (categories, products, SKUs)'

    def add_arguments(self, parser):
        parser.add_argument(
            '--products-per-category',
            type=int,
            default=3,
            help='Number of products per leaf category (default: 3)',
        )
        parser.add_argument(
            '--skus-per-product',
            type=int,
            default=5,
            help='Number of SKUs per product (default: 5)',
        )
        parser.add_argument(
            '--clear',
            action='store_true',
            help='Delete all existing catalog data before seeding',
        )

    def handle(self, *args, **options):
        if options['clear']:
            self.stdout.write('Clearing existing catalog data...')
            SKU.objects.all().delete()
            Product.objects.all().delete()
            CategoryAttribute.objects.all().delete()
            Category.objects.all().delete()
            self.stdout.write(self.style.SUCCESS('Cleared.'))

        self.stdout.write('Seeding categories...')
        categories = self._seed_categories()
        self.stdout.write(f'  Created {len(categories)} categories')

        self.stdout.write('Seeding category attributes...')
        self._seed_attributes(categories)

        self.stdout.write('Seeding products...')
        products = self._seed_products(categories, options['products_per_category'])
        self.stdout.write(f'  Created {len(products)} products')

        self.stdout.write('Seeding SKUs...')
        sku_count = self._seed_skus(products, options['skus_per_product'])
        self.stdout.write(f'  Created {sku_count} SKUs')

        self.stdout.write(self.style.SUCCESS(
            f'Seeding complete! '
            f'Categories: {len(categories)}, Products: {len(products)}, SKUs: {sku_count}'
        ))

    def _seed_categories(self):
        """Create the full 3-level category tree."""
        cat_data = [
            {
                'name': '润滑',
                'children': [
                    {'name': '车用润滑油', 'children': ['车用齿轮油', '车用发动机油', '车用液压油', '刹车油']},
                    {'name': '工业润滑油', 'children': ['液压油', '齿轮油', '压缩机油', '涡轮机油']},
                    {'name': '金属加工液', 'children': ['切削液', '磨削液', '冲压油', '轧制油']},
                    {'name': '润滑脂', 'children': ['锂基脂', '聚脲脂', '复合磺酸钙脂', '高温脂']},
                ],
            },
            {
                'name': '油漆涂料',
                'children': [
                    {'name': '工业涂料', 'children': ['环氧涂料', '聚氨酯涂料', '丙烯酸涂料', '氟碳涂料']},
                    {'name': '建筑涂料', 'children': ['内墙漆', '外墙漆', '地坪漆', '防水涂料']},
                    {'name': '自喷漆', 'children': ['金属自喷漆', '塑料自喷漆', '防锈自喷漆', '荧光自喷漆']},
                ],
            },
            {
                'name': '胶粘剂',
                'children': [
                    {'name': '灌封材料', 'children': ['有机硅灌封胶', '环氧树脂灌封胶', '聚氨酯灌封胶']},
                    {'name': '建筑胶', 'children': ['瓷砖胶', '结构胶', '密封胶', '玻璃胶']},
                    {'name': '厌氧胶', 'children': ['螺纹锁固胶', '管路密封胶', '平面密封胶', '固持胶']},
                    {'name': '非金属修补剂', 'children': ['耐磨修补剂', '防腐修补剂', '陶瓷修补剂', '橡胶修补剂']},
                    {'name': '其他胶', 'children': ['瞬干胶', '改性硅烷胶', '热熔胶', 'UV胶']},
                ],
            },
            {
                'name': '车间化学品',
                'children': [
                    {'name': '干燥剂', 'children': ['硅胶干燥剂', '分子筛干燥剂', '蒙脱石干燥剂', '纤维干燥剂']},
                    {'name': '活性炭', 'children': ['柱状活性炭', '颗粒活性炭', '粉末活性炭', '蜂窝活性炭']},
                    {'name': '模具养护产品', 'children': ['模具清洗剂', '模具防锈剂', '模具脱模剂', '模具保养油']},
                    {'name': '探伤化学品', 'children': ['渗透探伤剂', '磁粉探伤剂', '超声波耦合剂']},
                    {'name': '气雾剂', 'children': ['万能防锈剂', '电气设备干燥剂', '脱模气雾剂', '清洗气雾剂']},
                    {'name': '清洗剂', 'children': ['工业清洗剂', '金属清洗剂', '光学清洗剂', '电子清洗剂']},
                ],
            },
        ]

        categories = []
        sort_order = [0]

        def next_sort():
            sort_order[0] += 1
            return sort_order[0]

        for l1_data in cat_data:
            l1, _ = Category.objects.get_or_create(
                slug=_make_slug(l1_data['name']),
                defaults={
                    'name': l1_data['name'],
                    'parent': None,
                    'sort_order': next_sort(),
                    'is_active': True,
                },
            )
            categories.append(l1)
            for l2_data in l1_data['children']:
                l2, _ = Category.objects.get_or_create(
                    slug=_make_slug(l2_data['name']),
                    defaults={
                        'name': l2_data['name'],
                        'parent': l1,
                        'sort_order': next_sort(),
                        'is_active': True,
                    },
                )
                categories.append(l2)
                for l3_name in l2_data.get('children', []):
                    l3, _ = Category.objects.get_or_create(
                        slug=_make_slug(l3_name),
                        defaults={
                            'name': l3_name,
                            'parent': l2,
                            'sort_order': next_sort(),
                            'is_active': True,
                        },
                    )
                    categories.append(l3)
        return categories

    def _seed_attributes(self, categories):
        """Create category-specific attribute templates."""
        attr_defs = {
            '润滑': [
                {'name': '粘度等级', 'code': 'viscosity', 'data_type': AttributeDataType.OPTION},
                {'name': '认证标准', 'code': 'standard', 'data_type': AttributeDataType.OPTION},
            ],
            '油漆涂料': [
                {'name': '颜色', 'code': 'color', 'data_type': AttributeDataType.TEXT},
                {'name': '光泽度', 'code': 'gloss', 'data_type': AttributeDataType.OPTION},
            ],
            '胶粘剂': [
                {'name': '颜色', 'code': 'color', 'data_type': AttributeDataType.TEXT},
                {'name': '固化方式', 'code': 'cure', 'data_type': AttributeDataType.OPTION},
            ],
            '干燥剂': [
                {'name': '包材', 'code': 'package_material', 'data_type': AttributeDataType.OPTION},
                {'name': '克重', 'code': 'weight_g', 'data_type': AttributeDataType.NUMBER},
                {'name': '箱规', 'code': 'box_spec', 'data_type': AttributeDataType.TEXT},
            ],
            '活性炭': [
                {'name': '碘值', 'code': 'iodine_value', 'data_type': AttributeDataType.NUMBER},
                {'name': '尺寸', 'code': 'size', 'data_type': AttributeDataType.TEXT},
                {'name': '孔径', 'code': 'pore_size', 'data_type': AttributeDataType.OPTION},
            ],
        }
        for cat in categories:
            key = cat.name
            for defn in attr_defs.get(key, []):
                CategoryAttribute.objects.get_or_create(
                    category=cat,
                    code=defn['code'],
                    defaults={
                        'name': defn['name'],
                        'data_type': defn['data_type'],
                        'is_filterable': True,
                        'is_list_visible': True,
                        'is_detail_visible': True,
                        'sort_order': 0,
                        'is_active': True,
                    },
                )

    def _seed_products(self, categories, per_leaf):
        """Create sample products under leaf categories."""
        leaf_cats = [c for c in categories if c.parent and c.parent.parent]
        products = []

        for cat in leaf_cats:
            for i in range(per_leaf):
                brand = random.choice(BRANDS)
                style_code = f'SC{cat.slug[:6].upper()}{i+1:03d}'
                name = f'{brand}{cat.parent.name}'
                price = Decimal(str(random.randint(50, 3000) / 10)).quantize(Decimal('0.01'))
                product, created = Product.objects.get_or_create(
                    style_code=style_code,
                    defaults={
                        'name': name,
                        'alias': f'{name}（{cat.name}）',
                        'brand': brand,
                        'category': cat,
                        'description': f'高品质{cat.name}，{brand}品牌，适用于工业生产场景。',
                        'spec_summary': f'品牌：{brand} | 分类：{cat.name}',
                        'status': PublishStatus.PUBLISHED,
                    },
                )
                if created:
                    products.append(product)

        return products

    def _seed_skus(self, products, skus_per_product):
        """Create sample SKUs for each product."""
        colors = ['透明', '白色', '黑色', '黄色', '灰色', '本色', '红色', '蓝色', '绿色']
        gloss_levels = ['哑光', '半光', '高光', '亮光']
        cure_methods = ['室温固化', '加热固化', 'UV固化', '双组分固化']
        standards = ['ISO VG 46', 'ISO VG 68', 'SAE 5W-30', 'SAE 10W-40', 'DIN 51524-2']
        viscosity_grades = ['ISO VG 32', 'ISO VG 46', 'ISO VG 68', 'ISO VG 100']

        sku_count = 0
        for product in products:
            category = product.category
            cat_name = category.name if category else ''
            attrs = {}

            for i in range(skus_per_product):
                sku_code = f'{product.style_code}-{i+1:03d}'
                price = Decimal(str(random.randint(50, 5000) / 10)).quantize(Decimal('0.01'))
                package = random.choice(PACKAGE_SPECS)

                if '润滑' in cat_name or '油' in cat_name:
                    attrs = {
                        'viscosity': random.choice(viscosity_grades),
                        'standard': random.choice(standards),
                    }
                elif '涂料' in cat_name or '漆' in cat_name:
                    attrs = {
                        'color': random.choice(colors),
                        'gloss': random.choice(gloss_levels),
                    }
                elif '胶' in cat_name:
                    attrs = {
                        'color': random.choice(colors),
                        'cure': random.choice(cure_methods),
                    }
                elif '干燥' in cat_name:
                    attrs = {
                        'package_material': random.choice(['无纺布', '纸盒', '塑料', '复合包装']),
                        'weight_g': random.choice([1, 2, 5, 10, 20, 50, 100, 200, 500]),
                    }

                sku, created = SKU.objects.get_or_create(
                    internal_sku_code=sku_code,
                    defaults={
                        'product': product,
                        'price': price,
                        'package_spec': package,
                        'unit': random.choice(UNITS),
                        'stock_status': random.choice([
                            StockStatus.IN_STOCK,
                            StockStatus.IN_STOCK,
                            StockStatus.IN_STOCK,
                            StockStatus.CONFIRM,
                        ]),
                        'moq': Decimal('1'),
                        'order_step': Decimal('1'),
                        'attributes': attrs,
                        'status': PublishStatus.PUBLISHED,
                    },
                )
                if created:
                    sku_count += 1

        return sku_count

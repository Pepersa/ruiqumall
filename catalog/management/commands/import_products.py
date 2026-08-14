from pathlib import Path

from django.core.management.base import BaseCommand

from catalog.product_io import import_products_workbook
from openpyxl import load_workbook


class Command(BaseCommand):
    help = '从聚水潭/商品资料 Excel 导入产品和 SKU'

    def add_arguments(self, parser):
        parser.add_argument('file', help='Excel 文件路径')
        parser.add_argument('--sheet', default='Sheet1', help='工作表名称（仅当文件中没有“产品”工作表时使用）')
        parser.add_argument(
            '--dev-allow-missing-price-category',
            action='store_true',
            help='开发模式：允许价格或分类为空，用于临时样例数据',
        )
        parser.add_argument('--dry-run', action='store_true', help='只校验不写入数据库')

    def handle(self, *args, **options):
        file_path = Path(options['file'])
        if not file_path.exists():
            self.stderr.write(self.style.ERROR(f'文件不存在：{file_path}'))
            return

        workbook = load_workbook(file_path, data_only=True)
        result = import_products_workbook(
            workbook,
            dry_run=options['dry_run'],
            allow_missing_price=options['dev_allow_missing_price_category'],
            allow_missing_category=options['dev_allow_missing_price_category'],
            source_file_name=file_path.name,
        )

        self.stdout.write(self.style.SUCCESS('导入完成' if not options['dry_run'] else '校验完成，未写入数据库'))
        self.stdout.write(f'产品新增 {result.created_products}，更新 {result.updated_products}')
        self.stdout.write(f'SKU 新增 {result.created_skus}，更新 {result.updated_skus}')
        self.stdout.write(f'失败 {len(result.failures)}')
        for reason in result.failures[:50]:
            self.stdout.write(reason)
        if len(result.failures) > 50:
            self.stdout.write(f'还有 {len(result.failures) - 50} 条失败未显示')

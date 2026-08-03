from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.core.files import File
from django.db import transaction
from django.utils import timezone
from openpyxl import Workbook

from core.models import AuditLog, SiteConfig
from orders.models import Order


class JstExportValidationError(ValueError):
    pass


JST_EXPORT_HEADERS = [
    '线上单号',
    '店铺编码',
    '订单日期',
    '买家账号',
    '收件人',
    '手机/电话',
    '省',
    '市',
    '区',
    '详细地址',
    '买家留言',
    '卖家备注',
    '应付金额',
    '运费',
    'SKU编码',
    '店铺商品编码',
    '商品名称',
    '商品属性',
    '单价',
    '数量',
    '明细金额',
    '明细备注',
]


def get_config_value(key, default=''):
    config = SiteConfig.objects.filter(key=key).first()
    return config.value if config else default


def validate_order_for_jst(order):
    errors = []
    if order.status in {Order.Status.DRAFT, Order.Status.CANCELLED}:
        errors.append('订单状态不可导出')
    if not order.receiver_name or not order.receiver_mobile or not order.receiver_address:
        errors.append('收货人、电话和详细地址不能为空')
    items = list(order.items.all())
    if not items:
        errors.append('订单明细不能为空')
    for item in items:
        prefix = f'{item.snapshot_sku_code or "未命名 SKU"}：'
        if not item.snapshot_jst_sku_id:
            errors.append(prefix + '聚水潭商品编码不能为空')
        if item.qty <= 0:
            errors.append(prefix + '数量必须大于 0')
        if item.unit_price is None:
            errors.append(prefix + '导出前必须确认单价')
    if errors:
        raise JstExportValidationError(f'{order.order_no} 导出校验失败：' + '；'.join(errors))


def _decimal_value(value):
    if value is None:
        return None
    return float(Decimal(value).quantize(Decimal('0.01')))


@transaction.atomic
def export_orders_to_jst(orders, exported_by=None):
    from .models import JstExportBatch

    orders = list(orders.prefetch_related('items', 'customer'))
    if not orders:
        raise JstExportValidationError('请选择至少一个订单')
    for order in orders:
        validate_order_for_jst(order)

    now = timezone.localtime()
    batch_no = f'JST{now.strftime("%Y%m%d%H%M%S")}'
    file_name = f'{batch_no}.xlsx'
    export_dir = Path(settings.MEDIA_ROOT) / '_tmp_exports'
    export_dir.mkdir(parents=True, exist_ok=True)
    absolute_path = export_dir / file_name

    wb = Workbook()
    ws = wb.active
    ws.title = '聚水潭订单导入'
    ws.append(JST_EXPORT_HEADERS)

    shop_code = get_config_value('jst.default_shop_code', 'B2B')
    for order in orders:
        for item in order.items.all():
            ws.append([
                order.order_no,
                shop_code,
                timezone.localtime(order.created_at).strftime('%Y-%m-%d %H:%M:%S'),
                order.customer.company_name,
                order.receiver_name,
                order.receiver_mobile,
                order.receiver_state,
                order.receiver_city,
                order.receiver_district,
                order.receiver_address,
                order.buyer_message,
                order.internal_remark,
                _decimal_value(order.total_amount),
                _decimal_value(order.freight),
                item.snapshot_jst_sku_id,
                item.snapshot_shop_sku_id,
                item.snapshot_product_name,
                item.properties_value,
                _decimal_value(item.unit_price),
                float(item.qty),
                _decimal_value(item.amount),
                item.remark,
            ])

    for column_cells in ws.columns:
        max_length = max(len(str(cell.value or '')) for cell in column_cells)
        ws.column_dimensions[column_cells[0].column_letter].width = min(max(max_length + 2, 12), 36)
    wb.save(absolute_path)

    batch = JstExportBatch.objects.create(
        batch_no=batch_no,
        file_name=file_name,
        order_count=len(orders),
        exported_by=exported_by if getattr(exported_by, 'is_authenticated', False) else None,
    )
    with absolute_path.open('rb') as fh:
        batch.file.save(file_name, File(fh), save=True)
    absolute_path.unlink(missing_ok=True)
    batch.orders.set(orders)

    for order in orders:
        order.status = Order.Status.EXPORTED
        order.exported_at = timezone.now()
        order.save(update_fields=['status', 'exported_at'])
        AuditLog.objects.create(
            actor=batch.exported_by,
            action='jst_export',
            target_type='Order',
            target_id=order.order_no,
            message=f'导出批次 {batch.batch_no}',
        )

    return batch

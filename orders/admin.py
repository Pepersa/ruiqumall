from django.contrib import admin, messages
from django.utils import timezone

from core.models import AuditLog
from integrations.services import JstExportValidationError, export_orders_to_jst

from .models import Order, OrderItem


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    fields = (
        'snapshot_product_name',
        'snapshot_sku_code',
        'snapshot_jst_sku_id',
        'properties_value',
        'unit_price',
        'qty',
        'amount',
        'confirmed_stock_status',
        'expected_ship_date',
        'remark',
    )
    readonly_fields = ('amount',)
    autocomplete_fields = ('product', 'sku')


@admin.action(description='导出选中订单为聚水潭模板')
def export_to_jst(modeladmin, request, queryset):
    try:
        batch = export_orders_to_jst(queryset, exported_by=request.user)
    except JstExportValidationError as exc:
        modeladmin.message_user(request, str(exc), level=messages.ERROR)
        return
    modeladmin.message_user(request, f'已生成聚水潭导出批次 {batch.batch_no}：{batch.file.url}', level=messages.SUCCESS)


@admin.action(description='确认所选订单（标记为可导出）')
def confirm_orders(modeladmin, request, queryset):
    count = queryset.filter(
        status=Order.Status.PENDING_COMPANY_CONFIRM
    ).update(
        status=Order.Status.PENDING_JST_EXPORT,
        confirmed_at=timezone.now(),
    )
    for order in queryset.filter(status=Order.Status.PENDING_JST_EXPORT):
        AuditLog.objects.create(
            actor=request.user,
            action='order_confirmed',
            target_type='Order',
            target_id=order.order_no,
            message=f'管理员 {request.user.username} 确认订单',
        )
    modeladmin.message_user(request, f'已确认 {count} 个订单，状态更新为待导入聚水潭。', level=messages.SUCCESS)


@admin.action(description='拒绝所选订单')
def reject_orders(modeladmin, request, queryset):
    count = queryset.filter(
        status__in={Order.Status.PENDING_COMPANY_CONFIRM, Order.Status.PENDING_CUSTOMER_CONFIRM}
    ).update(status=Order.Status.CANCELLED)
    for order in queryset.filter(status=Order.Status.CANCELLED):
        AuditLog.objects.create(
            actor=request.user,
            action='order_rejected',
            target_type='Order',
            target_id=order.order_no,
            message=f'管理员 {request.user.username} 拒绝订单',
        )
    modeladmin.message_user(request, f'已拒绝 {count} 个订单。', level=messages.SUCCESS)


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ('order_no', 'customer', 'status', 'total_amount', 'created_at', 'exported_at')
    list_filter = ('status', 'created_at', 'exported_at')
    search_fields = (
        'order_no',
        'customer__company_name',
        'customer__contact_name',
        'receiver_name',
        'receiver_mobile',
        'items__snapshot_sku_code',
    )
    readonly_fields = ('order_no', 'created_at', 'exported_at')
    autocomplete_fields = ('customer',)
    inlines = (OrderItemInline,)
    actions = (confirm_orders, reject_orders, export_to_jst)
    fieldsets = (
        ('订单状态', {'fields': ('order_no', 'status', 'customer', 'total_amount', 'freight', 'expected_delivery_date')}),
        ('收货信息', {'fields': ('receiver_name', 'receiver_mobile', 'receiver_state', 'receiver_city', 'receiver_district', 'receiver_address')}),
        ('备注与开票', {'fields': ('invoice_info', 'buyer_message', 'internal_remark')}),
        ('时间', {'fields': ('created_at', 'confirmed_at', 'exported_at')}),
    )

    def save_formset(self, request, form, formset, change):
        super().save_formset(request, form, formset, change)
        if isinstance(form.instance, Order):
            form.instance.recalculate_total()


@admin.register(OrderItem)
class OrderItemAdmin(admin.ModelAdmin):
    list_display = ('order', 'snapshot_sku_code', 'snapshot_product_name', 'unit_price', 'qty', 'amount')
    list_filter = ('order__status',)
    search_fields = ('order__order_no', 'snapshot_sku_code', 'snapshot_jst_sku_id', 'snapshot_product_name')
    autocomplete_fields = ('order', 'product', 'sku')

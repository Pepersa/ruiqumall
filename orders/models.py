from decimal import Decimal

from django.db import models
from django.urls import reverse
from django.utils import timezone

from catalog.models import Product, SKU
from customers.models import Customer


class Order(models.Model):
    class Status(models.TextChoices):
        DRAFT = 'draft', '待提交'
        PENDING_COMPANY_CONFIRM = 'pending_company_confirm', '待公司确认'
        PENDING_CUSTOMER_CONFIRM = 'pending_customer_confirm', '待客户确认'
        PENDING_JST_EXPORT = 'pending_jst_export', '待导入聚水潭'
        EXPORTED = 'exported', '已导出聚水潭'
        JST_ERROR = 'jst_error', '聚水潭处理异常'
        ACCEPTED = 'accepted', '已受理'
        SHIPPED = 'shipped', '已发货'
        COMPLETED = 'completed', '已完成'
        CANCELLED = 'cancelled', '已取消'

    order_no = models.CharField('网站订单号', max_length=40, unique=True, blank=True)
    customer = models.ForeignKey(Customer, verbose_name='客户', related_name='orders', on_delete=models.PROTECT)
    status = models.CharField(
        '状态',
        max_length=40,
        choices=Status.choices,
        default=Status.PENDING_COMPANY_CONFIRM,
    )
    receiver_name = models.CharField('收件人', max_length=80)
    receiver_mobile = models.CharField('手机/电话', max_length=80)
    receiver_state = models.CharField('省', max_length=80, blank=True)
    receiver_city = models.CharField('市', max_length=80, blank=True)
    receiver_district = models.CharField('区', max_length=80, blank=True)
    receiver_address = models.CharField('详细地址', max_length=255)
    invoice_info = models.TextField('开票信息', blank=True)
    buyer_message = models.TextField('买家留言', blank=True)
    internal_remark = models.TextField('内部备注', blank=True)
    total_amount = models.DecimalField('订单总额', max_digits=12, decimal_places=2, default=Decimal('0'))
    freight = models.DecimalField('运费', max_digits=12, decimal_places=2, default=Decimal('0'))
    expected_delivery_date = models.DateField('期望交期', null=True, blank=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    confirmed_at = models.DateTimeField('确认时间', null=True, blank=True)
    exported_at = models.DateTimeField('最近导出时间', null=True, blank=True)

    class Meta:
        verbose_name = '订单'
        verbose_name_plural = '订单'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['order_no']),
            models.Index(fields=['status']),
            models.Index(fields=['created_at']),
        ]

    def __str__(self):
        return self.order_no or f'订单 {self.pk}'

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if not self.order_no:
            self.order_no = f'RQ{timezone.localtime(self.created_at).strftime("%Y%m%d")}{self.pk:06d}'
            super().save(update_fields=['order_no'])

    def get_absolute_url(self):
        return reverse('orders:detail', kwargs={'order_no': self.order_no})

    def recalculate_total(self):
        total = sum(
            (item.amount or Decimal('0') for item in self.items.all()),
            Decimal('0'),
        )
        self.total_amount = total + (self.freight or Decimal('0'))
        self.save(update_fields=['total_amount'])


class OrderItem(models.Model):
    order = models.ForeignKey(Order, verbose_name='订单', related_name='items', on_delete=models.CASCADE)
    product = models.ForeignKey(Product, verbose_name='产品', null=True, blank=True, on_delete=models.SET_NULL)
    sku = models.ForeignKey(SKU, verbose_name='SKU', null=True, blank=True, on_delete=models.SET_NULL)
    snapshot_product_name = models.CharField('产品名称快照', max_length=255)
    snapshot_sku_code = models.CharField('SKU 编码快照', max_length=80)
    snapshot_jst_sku_id = models.CharField('聚水潭编码快照', max_length=80, blank=True)
    snapshot_shop_sku_id = models.CharField('店铺编码快照', max_length=80, blank=True)
    properties_value = models.CharField('商品属性快照', max_length=255, blank=True)
    unit_price = models.DecimalField('单价', max_digits=12, decimal_places=2, null=True, blank=True)
    qty = models.DecimalField('数量', max_digits=12, decimal_places=2)
    amount = models.DecimalField('明细金额', max_digits=12, decimal_places=2, default=Decimal('0'))
    price_source = models.CharField('价格来源', max_length=20, blank=True,
                                    help_text='sku_default=默认标价 / customer_price=客户协议价')
    snapshot_customer_price_id = models.BigIntegerField('协议价记录 ID', null=True, blank=True)
    confirmed_stock_status = models.CharField('库存确认', max_length=80, blank=True)
    expected_ship_date = models.DateField('预计发货日期', null=True, blank=True)
    remark = models.CharField('明细备注', max_length=255, blank=True)

    class Meta:
        verbose_name = '订单明细'
        verbose_name_plural = '订单明细'
        ordering = ['id']
        indexes = [models.Index(fields=['snapshot_sku_code']), models.Index(fields=['snapshot_jst_sku_id'])]

    def __str__(self):
        return f'{self.snapshot_sku_code} x {self.qty}'

    def save(self, *args, **kwargs):
        if self.unit_price is None:
            self.amount = Decimal('0')
        else:
            self.amount = self.unit_price * self.qty
        super().save(*args, **kwargs)

# Create your models here.

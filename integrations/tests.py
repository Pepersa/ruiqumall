from decimal import Decimal
from tempfile import TemporaryDirectory

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from catalog.models import Product, SKU
from customers.models import Customer
from orders.models import Order, OrderItem

from .services import JstExportValidationError, export_orders_to_jst


class JstExportTests(TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.user = get_user_model().objects.create_user('admin', password='x', is_staff=True)
        product = Product.objects.create(name='测试助剂', style_code='A-1')
        sku = SKU.objects.create(product=product, internal_sku_code='S-1', jst_sku_id='J-1', shop_sku_id='SHOP-1')
        customer = Customer.objects.create(company_name='测试企业', contact_name='李工', mobile='13900000000')
        self.order = Order.objects.create(
            customer=customer,
            receiver_name='李工',
            receiver_mobile='13900000000',
            receiver_address='测试路 2 号',
        )
        OrderItem.objects.create(
            order=self.order,
            product=product,
            sku=sku,
            snapshot_product_name='测试助剂 25kg',
            snapshot_sku_code='S-1',
            snapshot_jst_sku_id='J-1',
            snapshot_shop_sku_id='SHOP-1',
            properties_value='25kg/桶',
            unit_price=Decimal('20.00'),
            qty=Decimal('2'),
        )
        self.order.recalculate_total()

    def test_export_creates_batch_and_marks_order(self):
        with override_settings(MEDIA_ROOT=self.tmp.name):
            batch = export_orders_to_jst(Order.objects.filter(pk=self.order.pk), exported_by=self.user)
        self.order.refresh_from_db()
        self.assertEqual(batch.order_count, 1)
        self.assertEqual(self.order.status, Order.Status.EXPORTED)
        self.assertTrue(batch.file.name.endswith('.xlsx'))

    def test_export_requires_price(self):
        item = self.order.items.get()
        item.unit_price = None
        item.save()
        with self.assertRaises(JstExportValidationError):
            export_orders_to_jst(Order.objects.filter(pk=self.order.pk), exported_by=self.user)

# Create your tests here.

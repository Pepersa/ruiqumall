from decimal import Decimal
from urllib.parse import quote

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from accounts.models import UserProfile
from catalog.models import Product, SKU
from customers.models import Customer, ShippingAddress

from .models import Order


class ConfirmOrderTests(TestCase):
    def setUp(self):
        self.product = Product.objects.create(name='测试树脂', style_code='P-1', brand='Ruiqu')
        self.sku = SKU.objects.create(
            product=self.product,
            internal_sku_code='SKU-100',
            jst_sku_id='JST-100',
            shop_sku_id='SHOP-100',
            source_goods_name='测试树脂 1kg',
            sku_attribute_text='1kg/桶',
            price=Decimal('12.50'),
            moq=Decimal('2'),
            order_step=Decimal('1'),
        )
        self.user = get_user_model().objects.create_user('buyer', password='pw38421844', email='buyer@example.com')
        UserProfile.objects.create(
            user=self.user,
            name='王工',
            phone='13800000000',
            company_name='测试企业',
        )
        Customer.objects.create(
            user=self.user,
            company_name='测试企业',
            contact_name='王工',
            mobile='13800000000',
            email='buyer@example.com',
        )
        self.address = ShippingAddress.objects.create(
            user=self.user,
            receiver_name='王工',
            receiver_mobile='13800000000',
            receiver_address='测试地址 1 号',
            is_default=True,
        )

    def test_confirm_page_prefills_saved_address(self):
        client = Client()
        client.force_login(self.user)
        client.post(f'/cart/add/{self.sku.id}/', {'qty': '3'})
        response = client.get(reverse('orders:confirm'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '确认订单')
        self.assertContains(response, '测试地址 1 号')
        self.assertContains(response, 'value="王工"', html=False)
        self.assertNotContains(response, '采购企业')
        self.assertNotContains(response, '开票信息')
        self.assertNotContains(response, '期望交期')
        self.assertNotContains(response, '联系人')
        self.assertNotContains(response, '手机/电话')

    def test_confirm_order_creates_pending_order_with_snapshots(self):
        client = Client()
        client.force_login(self.user)
        client.post(f'/cart/add/{self.sku.id}/', {'qty': '3'})
        response = client.post(reverse('orders:confirm'), {
            'saved_address': str(self.address.pk),
            'receiver_name': '王工',
            'receiver_mobile': '13800000000',
            'receiver_address': '测试地址 1 号',
        })
        self.assertEqual(response.status_code, 302)
        order = Order.objects.get()
        self.assertEqual(order.status, Order.Status.PENDING_COMPANY_CONFIRM)
        self.assertEqual(order.customer.contact_name, '王工')
        self.assertEqual(order.customer.mobile, '13800000000')
        self.assertEqual(order.items.get().snapshot_sku_code, 'SKU-100')
        self.assertEqual(order.total_amount, Decimal('37.50'))
        self.assertEqual(order.buyer_message, '')

    def test_confirm_page_marks_message_optional_and_address_required(self):
        client = Client()
        client.force_login(self.user)
        client.post(f'/cart/add/{self.sku.id}/', {'qty': '3'})

        response = client.get(reverse('orders:confirm'))

        self.assertContains(response, '买家留言')
        self.assertContains(response, '<span class="optional-mark">（选填）</span>', html=True)
        self.assertContains(response, '收货地址')
        self.assertContains(response, '<span class="required-mark">*</span>', html=True)

    def test_confirm_order_rejects_missing_shipping_address(self):
        client = Client()
        client.force_login(self.user)
        client.post(f'/cart/add/{self.sku.id}/', {'qty': '3'})

        response = client.post(reverse('orders:confirm'), {'buyer_message': '请尽快处理'})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '请选择或新增完整的收货地址后再提交订单。')
        self.assertFalse(Order.objects.exists())

    def test_confirm_order_allows_manual_shipping_info(self):
        client = Client()
        client.force_login(self.user)
        client.post(f'/cart/add/{self.sku.id}/', {'qty': '3'})
        response = client.post(reverse('orders:confirm'), {
            'receiver_name': '李工',
            'receiver_mobile': '13900000000',
            'receiver_address': '手动填写地址 2 号',
        })
        self.assertEqual(response.status_code, 302)
        order = Order.objects.get()
        self.assertEqual(order.receiver_address, '手动填写地址 2 号')

    def test_anonymous_user_is_redirected_before_add_to_cart(self):
        client = Client()
        response = client.post(f'/cart/add/{self.sku.id}/', {'qty': '3'})
        self.assertEqual(response.status_code, 302)
        self.assertIn('/accounts/login/', response['Location'])
        self.assertIn(quote(self.product.get_absolute_url(), safe=''), response['Location'])

# Create your tests here.

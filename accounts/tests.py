from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from customers.models import Customer, ShippingAddress
from orders.models import Order

from .models import UserProfile


class RegisterTests(TestCase):
    def test_register_creates_and_logs_in_user(self):
        client = Client()
        response = client.post('/accounts/register/', {
            'username': 'newbuyer',
            'email': 'buyer@example.com',
            'company_name': '测试采购企业',
            'password1': 'pw38421844!',
            'password2': 'pw38421844!',
        })
        self.assertEqual(response.status_code, 302)
        user = get_user_model().objects.get(username='newbuyer')
        self.assertEqual(int(client.session['_auth_user_id']), user.pk)
        profile = UserProfile.objects.get(user=user)
        self.assertEqual(profile.name, '')
        self.assertEqual(profile.phone, '')
        self.assertEqual(profile.company_name, '测试采购企业')
        self.assertEqual(user.customer.company_name, '测试采购企业')

    def test_register_saves_optional_name_and_phone(self):
        client = Client()
        response = client.post('/accounts/register/', {
            'username': 'namedbuyer',
            'name': '张三',
            'phone': '13800138000',
            'password1': 'pw38421844!',
            'password2': 'pw38421844!',
        })
        self.assertEqual(response.status_code, 302)
        profile = UserProfile.objects.get(user__username='namedbuyer')
        self.assertEqual(profile.name, '张三')
        self.assertEqual(profile.phone, '13800138000')


class ProfileTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user('buyer', password='pw38421844', email='buyer@example.com')
        self.client = Client()
        self.client.force_login(self.user)
        self.profile = UserProfile.objects.create(
            user=self.user,
            name='王工',
            phone='13800000000',
            company_name='测试企业',
        )
        self.customer = Customer.objects.create(
            user=self.user,
            company_name='测试企业',
            contact_name='王工',
            mobile='13800000000',
            email='buyer@example.com',
        )

    def test_profile_home_requires_login(self):
        client = Client()
        response = client.get(reverse('accounts:profile'))
        self.assertEqual(response.status_code, 302)

    def test_profile_edit_updates_user_and_customer(self):
        response = self.client.post(reverse('accounts:profile_edit'), {
            'email': 'new@example.com',
            'name': '李工',
            'phone': '13900000000',
            'company_name': '新企业',
        })
        self.assertEqual(response.status_code, 302)
        self.user.refresh_from_db()
        self.profile.refresh_from_db()
        self.customer.refresh_from_db()
        self.assertEqual(self.user.email, 'new@example.com')
        self.assertEqual(self.profile.name, '李工')
        self.assertEqual(self.customer.company_name, '新企业')

    def test_profile_orders_lists_user_orders(self):
        order = Order.objects.create(
            customer=self.customer,
            receiver_name='王工',
            receiver_mobile='13800000000',
            receiver_address='测试地址',
        )
        response = self.client.get(reverse('accounts:profile_orders'))
        self.assertContains(response, order.order_no)

    def test_shipping_address_crud(self):
        response = self.client.post(reverse('accounts:profile_address_add'), {
            'label': '公司仓库',
            'receiver_name': '王工',
            'receiver_mobile': '13800000000',
            'receiver_state': '上海市',
            'receiver_city': '上海市',
            'receiver_district': '浦东新区',
            'receiver_address': '测试路 1 号',
            'is_default': True,
        })
        self.assertEqual(response.status_code, 302)
        address = ShippingAddress.objects.get(user=self.user)
        self.assertTrue(address.is_default)
        response = self.client.post(reverse('accounts:profile_address_delete', args=[address.pk]))
        self.assertEqual(response.status_code, 302)
        self.assertFalse(ShippingAddress.objects.filter(user=self.user).exists())

    def test_logged_in_user_can_view_own_order_without_phone_verification(self):
        order = Order.objects.create(
            customer=self.customer,
            receiver_name='王工',
            receiver_mobile='13800000000',
            receiver_address='测试地址',
        )
        response = self.client.get(order.get_absolute_url())
        self.assertContains(response, order.order_no)
        self.assertNotContains(response, '输入收件电话查看订单详情')

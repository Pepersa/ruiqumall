from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from catalog.models import Product, SKU


class AddToCartTests(TestCase):
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
        self.user = get_user_model().objects.create_user('buyer', password='pw38421844')

    def test_ajax_add_returns_json_without_redirecting_to_cart(self):
        client = Client()
        client.force_login(self.user)
        response = client.post(
            reverse('cart:add', args=[self.sku.id]),
            {'qty': '3'},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['ok'])
        self.assertEqual(data['cart_count'], 3)
        self.assertIn('image_url', data)

    def test_add_redirects_back_to_referer_instead_of_cart(self):
        client = Client()
        client.force_login(self.user)
        response = client.post(
            reverse('cart:add', args=[self.sku.id]),
            {'qty': '2'},
            HTTP_REFERER='http://testserver/products/1/',
        )
        self.assertRedirects(response, 'http://testserver/products/1/', fetch_redirect_response=False)

    def test_cart_context_processor_exposes_item_count(self):
        client = Client()
        client.force_login(self.user)
        client.post(reverse('cart:add', args=[self.sku.id]), {'qty': '2'}, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        response = client.get(reverse('home'))
        self.assertContains(response, 'cart-badge')
        self.assertContains(response, '>2</span>')

    def test_cart_uses_quantity_stepper(self):
        client = Client()
        client.force_login(self.user)
        client.post(reverse('cart:add', args=[self.sku.id]), {'qty': '2'})

        response = client.get(reverse('cart:detail'))

        self.assertContains(response, 'quantity-stepper--compact')
        self.assertContains(response, 'data-quantity-change="-1"')
        self.assertContains(response, 'data-quantity-change="1"')
        self.assertContains(response, 'aria-label="购物车数量"')
        self.assertNotContains(response, '>更新</button>')

    def test_ajax_quantity_update_hides_price_totals(self):
        client = Client()
        client.force_login(self.user)
        client.post(reverse('cart:add', args=[self.sku.id]), {'qty': '2'})

        response = client.post(
            reverse('cart:update', args=[self.sku.id]),
            {'qty': '4'},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['qty'], '4.00')
        self.assertEqual(response.json()['cart_count'], 4)
        self.assertNotIn('amount', response.json())
        self.assertNotIn('total', response.json())

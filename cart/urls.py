from django.urls import path

from . import views

app_name = 'cart'

urlpatterns = [
    path('', views.cart_detail, name='detail'),
    path('add/<int:sku_id>/', views.add_to_cart, name='add'),
    path('update/<int:sku_id>/', views.update_cart_item, name='update'),
    path('remove/<int:sku_id>/', views.remove_cart_item, name='remove'),
]

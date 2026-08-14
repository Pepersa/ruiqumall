from django.urls import path

from . import views

app_name = 'orders'

urlpatterns = [
    path('confirm/', views.confirm_order, name='confirm'),
    path('<str:order_no>/', views.order_detail, name='detail'),
]

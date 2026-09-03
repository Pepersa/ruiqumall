from django.urls import path

from . import views

app_name = 'orders'

urlpatterns = [
    path('confirm/', views.confirm_order, name='confirm'),
    path('history/', views.purchase_history, name='history'),
    path('reorder/<str:order_no>/', views.reorder, name='reorder'),
    path('<str:order_no>/', views.order_detail, name='detail'),
]

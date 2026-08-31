from django.urls import path

from . import views

app_name = 'catalog'

urlpatterns = [
    path('media/<path:asset_path>', views.product_media, name='product_media'),
    path('search/suggest/', views.search_suggest, name='search_suggest'),
    path('', views.ProductListView.as_view(), name='product_list'),
    path('scenes/<slug:slug>/', views.HomeSceneView.as_view(), name='home_scene'),
    path('<int:pk>/', views.ProductDetailView.as_view(), name='product_detail'),
]

from django.contrib.auth import views as auth_views
from django.urls import path

from cart.persistence import (
    CART_PERSIST_COOKIE,
    load_cart_cookie,
    merge_cart,
    save_cart_cookie,
)

from .views import (
    ProfileAddressesView,
    ProfileCartView,
    ProfileEditView,
    ProfileHomeView,
    ProfileOrdersView,
    RegisterSuccessView,
    RegistrationRequestView,
    ShippingAddressCreateView,
    ShippingAddressUpdateView,
    delete_shipping_address,
    set_default_shipping_address,
)

CART_SESSION_KEY = 'cart'


class PersistentCartLoginView(auth_views.LoginView):
    """登录成功时，如果有持久化 cookie 里的 cart，合并到 session cart。"""

    def get(self, request, *args, **kwargs):
        response = super().get(request, *args, **kwargs)
        if request.user.is_authenticated and not request.session.get(CART_SESSION_KEY):
            cookie_cart = load_cart_cookie(request)
            if cookie_cart:
                session_cart = request.session.setdefault(CART_SESSION_KEY, {})
                merge_cart(session_cart, cookie_cart)
                request.session.modified = True
                response.delete_cookie(CART_PERSIST_COOKIE)
        return response

    def form_valid(self, form):
        response = super().form_valid(form)
        cookie_cart = load_cart_cookie(self.request)
        if cookie_cart:
            session_cart = self.request.session.setdefault(CART_SESSION_KEY, {})
            merge_cart(session_cart, cookie_cart)
            self.request.session.modified = True
            response.delete_cookie(CART_PERSIST_COOKIE)
        return response


class PersistentCartLogoutView(auth_views.LogoutView):
    """登出前把 cart 写入持久化 cookie，避免 flush 后丢失。"""

    def dispatch(self, request, *args, **kwargs):
        cart = request.session.get(CART_SESSION_KEY)
        response = super().dispatch(request, *args, **kwargs)
        # super().dispatch 内部调用 auth.logout() -> session.flush()，session_cart 已清空，
        # 但 flush 不会影响我们在 dispatch 前面拿到的 cart 字典（dict 是引用，但 flush 后 session 内的 dict
        # 已被换成新对象，所以这里必须用提前捕获的引用）。
        if cart:
            save_cart_cookie(response, cart)
        return response


app_name = 'accounts'

urlpatterns = [
    path('register/', RegistrationRequestView.as_view(), name='register'),
    path('register/success/', RegisterSuccessView.as_view(), name='register_success'),
    path(
        'login/',
        PersistentCartLoginView.as_view(template_name='registration/login.html'),
        name='login',
    ),
    path('logout/', PersistentCartLogoutView.as_view(), name='logout'),
    path('profile/', ProfileHomeView.as_view(), name='profile'),
    path('profile/cart/', ProfileCartView.as_view(), name='profile_cart'),
    path('profile/orders/', ProfileOrdersView.as_view(), name='profile_orders'),
    path('profile/edit/', ProfileEditView.as_view(), name='profile_edit'),
    path('profile/addresses/', ProfileAddressesView.as_view(), name='profile_addresses'),
    path('profile/addresses/add/', ShippingAddressCreateView.as_view(), name='profile_address_add'),
    path('profile/addresses/<int:pk>/edit/', ShippingAddressUpdateView.as_view(), name='profile_address_edit'),
    path('profile/addresses/<int:pk>/default/', set_default_shipping_address, name='profile_address_default'),
    path('profile/addresses/<int:pk>/delete/', delete_shipping_address, name='profile_address_delete'),
]

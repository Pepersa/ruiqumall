from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.messages.views import SuccessMessageMixin
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.views.decorators.http import require_POST
from django.views.generic import CreateView, TemplateView, UpdateView

from cart.views import cart_items
from customers.models import ShippingAddress

from .forms import ProfileForm, RegistrationRequestForm, ShippingAddressForm
from .services import ensure_user_profile, user_orders


class RegistrationRequestView(SuccessMessageMixin, CreateView):
    """内部客户注册申请页 - 提交后需管理员审核"""
    form_class = RegistrationRequestForm
    template_name = 'accounts/register.html'
    success_url = reverse_lazy('accounts:register_success')
    success_message = '注册申请已提交，请等待管理员审核。审核通过后即可登录。'

    def form_valid(self, form):
        response = super().form_valid(form)
        return response


class RegisterSuccessView(TemplateView):
    template_name = 'accounts/register_success.html'


class LoginRequiredMessageMixin(LoginRequiredMixin):
    login_url = reverse_lazy('accounts:login')

    def handle_no_permission(self):
        messages.info(self.request, '请先登录后访问。')
        return super().handle_no_permission()


class ProfileMixin(LoginRequiredMessageMixin):
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['profile_section'] = getattr(self, 'profile_section', 'home')
        context['profile_user'] = self.request.user
        ensure_user_profile(self.request.user)
        return context


class ProfileHomeView(ProfileMixin, TemplateView):
    template_name = 'accounts/profile/home.html'
    profile_section = 'home'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        items, total = cart_items(self.request)
        orders_qs = user_orders(self.request.user)
        context.update(
            {
                'cart_count': len(items),
                'cart_total': total,
                'recent_orders': orders_qs[:5],
                'order_count': orders_qs.count(),
                'address_count': self.request.user.shipping_addresses.count(),
            }
        )
        return context


class ProfileCartView(ProfileMixin, TemplateView):
    template_name = 'accounts/profile/cart.html'
    profile_section = 'cart'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        items, total = cart_items(self.request)
        context['items'] = items
        context['total'] = total
        context['cart_return_url'] = reverse('accounts:profile_cart')
        return context


class ProfileOrdersView(ProfileMixin, TemplateView):
    template_name = 'accounts/profile/orders.html'
    profile_section = 'orders'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['orders'] = user_orders(self.request.user)
        return context


class ProfileEditView(ProfileMixin, TemplateView):
    template_name = 'accounts/profile/edit.html'
    profile_section = 'edit'

    def get(self, request, *args, **kwargs):
        return render(request, self.template_name, self.get_context_data(form=ProfileForm(request.user)))

    def post(self, request, *args, **kwargs):
        form = ProfileForm(request.user, request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, '个人信息已更新。')
            return redirect('accounts:profile_edit')
        return render(request, self.template_name, self.get_context_data(form=form))


class ProfileAddressesView(ProfileMixin, TemplateView):
    template_name = 'accounts/profile/addresses.html'
    profile_section = 'addresses'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['addresses'] = self.request.user.shipping_addresses.all()
        context['address_form'] = ShippingAddressForm()
        return context


class ShippingAddressCreateView(ProfileMixin, SuccessMessageMixin, CreateView):
    model = ShippingAddress
    form_class = ShippingAddressForm
    template_name = 'accounts/profile/address_form.html'
    profile_section = 'addresses'
    success_message = '收货地址已保存。'

    def get_success_url(self):
        next_url = self.request.POST.get('next') or self.request.GET.get('next')
        if next_url:
            return next_url
        return reverse('accounts:profile_addresses')

    def form_valid(self, form):
        form.instance.user = self.request.user
        return super().form_valid(form)


class ShippingAddressUpdateView(ProfileMixin, SuccessMessageMixin, UpdateView):
    model = ShippingAddress
    form_class = ShippingAddressForm
    template_name = 'accounts/profile/address_form.html'
    profile_section = 'addresses'
    success_message = '收货地址已更新。'

    def get_queryset(self):
        return ShippingAddress.objects.filter(user=self.request.user)

    def get_success_url(self):
        next_url = self.request.POST.get('next') or self.request.GET.get('next')
        if next_url:
            return next_url
        return reverse('accounts:profile_addresses')


@login_required
@require_POST
def set_default_shipping_address(request, pk):
    address = get_object_or_404(ShippingAddress, pk=pk, user=request.user)
    address.is_default = True
    address.save()
    next_url = request.POST.get('next') or reverse('accounts:profile_addresses')
    return redirect(next_url)


@login_required
@require_POST
def delete_shipping_address(request, pk):
    address = get_object_or_404(ShippingAddress, pk=pk, user=request.user)
    address.delete()
    next_url = request.POST.get('next') or reverse('accounts:profile_addresses')
    return redirect(next_url)

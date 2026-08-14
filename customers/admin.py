from django.contrib import admin

from .models import Customer, ShippingAddress


class CustomerSKUPriceInline(admin.TabularInline):
    """客户详情页内联：直接维护该客户 × SKU 的协议价。"""
    from catalog.models import CustomerSKUPrice
    model = CustomerSKUPrice
    extra = 0
    fields = ('sku', 'price', 'min_qty', 'max_qty', 'valid_from', 'valid_to', 'is_active', 'remark')
    autocomplete_fields = ('sku',)


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ('company_name', 'contact_name', 'mobile', 'email', 'user', 'status', 'updated_at')
    list_filter = ('status',)
    search_fields = ('company_name', 'tax_no', 'contact_name', 'mobile', 'email', 'remark', 'user__username')
    inlines = (CustomerSKUPriceInline,)


@admin.register(ShippingAddress)
class ShippingAddressAdmin(admin.ModelAdmin):
    list_display = ('user', 'label', 'receiver_name', 'receiver_mobile', 'receiver_address', 'is_default', 'updated_at')
    list_filter = ('is_default',)
    search_fields = ('user__username', 'label', 'receiver_name', 'receiver_mobile', 'receiver_address')

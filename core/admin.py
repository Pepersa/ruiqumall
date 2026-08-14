from django.contrib import admin

from .models import AuditLog, SiteConfig, SiteSettings


@admin.register(SiteSettings)
class SiteSettingsAdmin(admin.ModelAdmin):
    """网站联系方式管理"""
    list_display = ('phone', 'email', 'updated_at')
    fieldsets = [
        (None, {'fields': ['phone', 'email']}),
    ]


@admin.register(SiteConfig)
class SiteConfigAdmin(admin.ModelAdmin):
    list_display = ('key', 'value', 'description', 'updated_at')
    search_fields = ('key', 'value', 'description')


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ('created_at', 'actor', 'action', 'target_type', 'target_id')
    list_filter = ('action', 'target_type', 'created_at')
    search_fields = ('action', 'target_type', 'target_id', 'message')
    readonly_fields = ('actor', 'action', 'target_type', 'target_id', 'message', 'created_at')

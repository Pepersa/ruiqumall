from django.contrib import admin, messages
from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone
from django.utils.html import format_html

from .models import RegistrationRequest, UserProfile


User = get_user_model()


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'name', 'phone', 'company_name', 'tax_no')
    search_fields = ('user__username', 'name', 'phone', 'company_name', 'tax_no')


@admin.register(RegistrationRequest)
class RegistrationRequestAdmin(admin.ModelAdmin):
    list_display = ('company_name', 'contact_name', 'phone', 'username', 'status', 'created_at', 'reviewed_by', 'reviewed_at')
    list_filter = ('status', 'created_at')
    search_fields = ('company_name', 'contact_name', 'phone', 'username', 'email')
    readonly_fields = ('created_at', 'updated_at', 'reviewed_by', 'reviewed_at', 'reject_reason')
    actions = ('approve_selected', 'reject_selected')

    fieldsets = (
        ('申请信息', {
            'fields': ('company_name', 'contact_name', 'phone', 'purpose')
        }),
        ('账号信息', {
            'fields': ('username', 'email', 'password', 'status')
        }),
        ('审核结果', {
            'fields': ('reviewed_by', 'reviewed_at', 'reject_reason')
        }),
        ('时间记录', {
            'fields': ('created_at', 'updated_at')
        }),
    )
    readonly_fields = ('password', 'created_at', 'updated_at', 'reviewed_at')

    def has_add_permission(self, request):
        return False

    def approve_selected(self, request, queryset):
        queryset = queryset.filter(status=RegistrationRequest.Status.PENDING)
        if not queryset.exists():
            self.message_user(request, '没有待审核的申请。', level=messages.WARNING)
            return
        approved, rejected = 0, 0
        for reg_req in queryset:
            try:
                with transaction.atomic():
                    if User.objects.filter(username=reg_req.username).exists():
                        reg_req.status = RegistrationRequest.Status.REJECTED
                        reg_req.reject_reason = '用户名已存在'
                        reg_req.save(update_fields=['status', 'reject_reason'])
                        rejected += 1
                        continue
                    user = User.objects.create_user(
                        username=reg_req.username,
                        email=reg_req.email,
                    )
                    if reg_req.password:
                        user.password = reg_req.password
                        user.save(update_fields=['password'])
                    UserProfile.objects.create(
                        user=user,
                        name=reg_req.contact_name,
                        phone=reg_req.phone,
                        company_name=reg_req.company_name,
                    )
                    reg_req.status = RegistrationRequest.Status.APPROVED
                    reg_req.reviewed_by = request.user
                    reg_req.reviewed_at = timezone.now()
                    reg_req.save(update_fields=['status', 'reviewed_by', 'reviewed_at'])
                    approved += 1
            except Exception as e:
                reg_req.status = RegistrationRequest.Status.REJECTED
                reg_req.reject_reason = f'系统错误：{str(e)[:200]}'
                reg_req.reviewed_by = request.user
                reg_req.reviewed_at = timezone.now()
                reg_req.save(update_fields=['status', 'reject_reason', 'reviewed_by', 'reviewed_at'])
                rejected += 1
        self.message_user(
            request,
            f'已通过 {approved} 个申请，'
            f'已拒绝 {rejected} 个（用户名重复或系统错误）',
            level=messages.SUCCESS if approved else messages.WARNING,
        )

    approve_selected.short_description = '通过所选申请（自动创建账号）'

    def reject_selected(self, request, queryset):
        count = queryset.filter(status=RegistrationRequest.Status.PENDING).update(
            status=RegistrationRequest.Status.REJECTED,
            reviewed_by=request.user,
            reviewed_at=timezone.now(),
        )
        self.message_user(request, f'已拒绝 {count} 个申请。', level=messages.SUCCESS)

    reject_selected.short_description = '拒绝所选申请'


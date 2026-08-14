from django.conf import settings
from django.db import models


class UserProfile(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='profile',
        verbose_name='用户',
    )
    name = models.CharField('姓名', max_length=80, blank=True)
    phone = models.CharField('电话号码', max_length=80, blank=True)
    company_name = models.CharField('公司名称', max_length=180, blank=True)
    tax_no = models.CharField('税号', max_length=80, blank=True)

    class Meta:
        verbose_name = '用户资料'
        verbose_name_plural = '用户资料'

    def __str__(self):
        return self.name or self.user.username


class RegistrationRequest(models.Model):
    class Status(models.TextChoices):
        PENDING = 'pending', '待审核'
        APPROVED = 'approved', '已通过'
        REJECTED = 'rejected', '已拒绝'

    username = models.CharField('用户名', max_length=150, unique=True)
    email = models.EmailField('邮箱', blank=True)
    company_name = models.CharField('公司名称', max_length=180)
    contact_name = models.CharField('联系人', max_length=80)
    phone = models.CharField('手机/电话', max_length=80)
    purpose = models.TextField('申请说明', blank=True, help_text='如采购品类、用途等')
    password = models.CharField('密码哈希', max_length=256, blank=True,
                                help_text='保存用户设置的登录密码（哈希值），审核通过时回填')
    status = models.CharField('状态', max_length=20, choices=Status.choices, default=Status.PENDING)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name='审核人',
        null=True, blank=True,
        related_name='reviewed_registration_requests',
        on_delete=models.SET_NULL,
    )
    reviewed_at = models.DateTimeField('审核时间', null=True, blank=True)
    reject_reason = models.TextField('拒绝原因', blank=True)
    created_at = models.DateTimeField('申请时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        verbose_name = '注册申请'
        verbose_name_plural = '注册申请'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status']),
            models.Index(fields=['company_name']),
        ]

    def __str__(self):
        return f'{self.company_name} - {self.username}（{self.get_status_display()}）'

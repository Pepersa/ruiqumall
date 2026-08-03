from django.conf import settings
from django.db import models


class Customer(models.Model):
    class Status(models.TextChoices):
        ACTIVE = 'active', '正常'
        INACTIVE = 'inactive', '停用'

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        verbose_name='关联用户',
        related_name='customer',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    company_name = models.CharField('采购企业', max_length=180)
    tax_no = models.CharField('税号', max_length=80, blank=True)
    contact_name = models.CharField('联系人', max_length=80)
    mobile = models.CharField('手机/电话', max_length=80)
    email = models.EmailField('邮箱', blank=True)
    remark = models.TextField('客户备注', blank=True)
    status = models.CharField('状态', max_length=20, choices=Status.choices, default=Status.ACTIVE)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        verbose_name = '客户'
        verbose_name_plural = '客户'
        ordering = ['company_name']
        indexes = [models.Index(fields=['company_name']), models.Index(fields=['mobile'])]

    def __str__(self):
        return f'{self.company_name} - {self.contact_name}'


class ShippingAddress(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name='用户',
        related_name='shipping_addresses',
        on_delete=models.CASCADE,
    )
    label = models.CharField('地址标签', max_length=40, blank=True)
    receiver_name = models.CharField('收件人', max_length=80)
    receiver_mobile = models.CharField('手机/电话', max_length=80)
    receiver_state = models.CharField('省', max_length=80, blank=True)
    receiver_city = models.CharField('市', max_length=80, blank=True)
    receiver_district = models.CharField('区', max_length=80, blank=True)
    receiver_address = models.CharField('详细地址', max_length=255)
    is_default = models.BooleanField('默认地址', default=False)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        verbose_name = '收货地址'
        verbose_name_plural = '收货地址'
        ordering = ['-is_default', '-updated_at']
        indexes = [models.Index(fields=['user', 'is_default'])]

    def __str__(self):
        return self.label or self.receiver_address

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if self.is_default:
            ShippingAddress.objects.filter(user_id=self.user_id).exclude(pk=self.pk).update(is_default=False)

# Create your models here.

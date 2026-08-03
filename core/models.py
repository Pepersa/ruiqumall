from django.conf import settings
from django.db import models


class SiteConfig(models.Model):
    key = models.CharField('配置键', max_length=80, unique=True)
    value = models.TextField('配置值', blank=True)
    description = models.CharField('说明', max_length=255, blank=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        verbose_name = '系统配置'
        verbose_name_plural = '系统配置'
        ordering = ['key']

    def __str__(self):
        return self.key


class AuditLog(models.Model):
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name='操作人',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    action = models.CharField('操作', max_length=80)
    target_type = models.CharField('对象类型', max_length=80, blank=True)
    target_id = models.CharField('对象 ID', max_length=80, blank=True)
    message = models.TextField('说明', blank=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)

    class Meta:
        verbose_name = '审计日志'
        verbose_name_plural = '审计日志'
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.action} {self.target_type} {self.target_id}'.strip()

# Create your models here.

from django.conf import settings
from django.db import models


class JstExportBatch(models.Model):
    class Status(models.TextChoices):
        CREATED = 'created', '已生成'
        IMPORTED = 'imported', '导入成功'
        FAILED = 'failed', '导入失败'

    batch_no = models.CharField('批次号', max_length=40, unique=True)
    file_name = models.CharField('文件名', max_length=255)
    file = models.FileField('导出文件', upload_to='jst_exports/', blank=True)
    orders = models.ManyToManyField('orders.Order', verbose_name='订单', related_name='export_batches', blank=True)
    order_count = models.PositiveIntegerField('订单数', default=0)
    status = models.CharField('状态', max_length=20, choices=Status.choices, default=Status.CREATED)
    exported_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name='导出人',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    exported_at = models.DateTimeField('导出时间', auto_now_add=True)
    error_message = models.TextField('异常信息', blank=True)

    class Meta:
        verbose_name = '聚水潭导出批次'
        verbose_name_plural = '聚水潭导出批次'
        ordering = ['-exported_at']
        indexes = [models.Index(fields=['batch_no']), models.Index(fields=['status'])]

    def __str__(self):
        return self.batch_no

# Create your models here.

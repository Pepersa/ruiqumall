from django.contrib import admin

from .models import JstExportBatch


@admin.register(JstExportBatch)
class JstExportBatchAdmin(admin.ModelAdmin):
    list_display = ('batch_no', 'file_name', 'order_count', 'status', 'exported_by', 'exported_at')
    list_filter = ('status', 'exported_at')
    search_fields = ('batch_no', 'file_name', 'orders__order_no', 'error_message')
    readonly_fields = ('batch_no', 'file_name', 'file', 'order_count', 'exported_by', 'exported_at')
    filter_horizontal = ('orders',)

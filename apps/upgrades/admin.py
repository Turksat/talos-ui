from django.contrib import admin
from .models import UpgradeJob


@admin.register(UpgradeJob)
class UpgradeJobAdmin(admin.ModelAdmin):
    list_display = ('id', 'cluster', 'job_type', 'status', 'initiated_by', 'created_at', 'completed_at')
    list_filter = ('job_type', 'status', 'cluster')
    readonly_fields = ('created_at', 'started_at', 'completed_at', 'celery_task_id', 'logs')
    filter_horizontal = ('target_nodes',)

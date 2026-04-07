from django.contrib import admin
from .models import PatchTemplate, PatchJob


@admin.register(PatchTemplate)
class PatchTemplateAdmin(admin.ModelAdmin):
    list_display = ['name', 'target_role', 'created_by', 'created_at', 'updated_at']
    search_fields = ['name', 'description']
    list_filter = ['target_role']


@admin.register(PatchJob)
class PatchJobAdmin(admin.ModelAdmin):
    list_display = ['id', 'patch_template', 'cluster', 'target_role', 'status', 'initiated_by', 'created_at']
    list_filter = ['status', 'target_role']
    readonly_fields = ['celery_task_id', 'logs', 'created_at', 'started_at', 'completed_at']

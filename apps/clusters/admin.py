from django.contrib import admin
from .models import Cluster, Node, NodeOperation


class NodeInline(admin.TabularInline):
    model = Node
    extra = 0
    readonly_fields = ('last_seen', 'status', 'talos_version', 'k8s_version')


@admin.register(Cluster)
class ClusterAdmin(admin.ModelAdmin):
    list_display = ('name', 'endpoint', 'is_active', 'created_at', 'created_by')
    list_filter = ('is_active',)
    search_fields = ('name', 'endpoint')
    inlines = [NodeInline]
    readonly_fields = ('created_at', 'created_by')

    def save_model(self, request, obj, form, change):
        if not change:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)


@admin.register(Node)
class NodeAdmin(admin.ModelAdmin):
    list_display = ('ip_address', 'hostname', 'cluster', 'role', 'status', 'talos_version', 'k8s_version', 'last_seen')
    list_filter = ('role', 'status', 'cluster')
    search_fields = ('ip_address', 'hostname')


@admin.register(NodeOperation)
class NodeOperationAdmin(admin.ModelAdmin):
    list_display = ('node', 'operation', 'status', 'initiated_by', 'started_at', 'completed_at')
    list_filter = ('operation', 'status')
    readonly_fields = ('started_at', 'completed_at', 'output')

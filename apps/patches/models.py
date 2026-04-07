from django.db import models
from django.db.models import F
from django.db.models.functions import Concat
from django.db.models import Value
from django.contrib.auth.models import User
from apps.clusters.models import Cluster, Node


class PatchTemplate(models.Model):
    ROLE_ALL = 'all'
    ROLE_CONTROLPLANE = 'controlplane'
    ROLE_WORKER = 'worker'

    ROLE_CHOICES = [
        (ROLE_ALL, 'All Nodes'),
        (ROLE_CONTROLPLANE, 'Control Plane'),
        (ROLE_WORKER, 'Worker'),
    ]

    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)
    patch_content = models.TextField(help_text='JSON patch content (array of patch operations)')
    target_role = models.CharField(max_length=20, choices=ROLE_CHOICES, default=ROLE_ALL)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='patch_templates')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class PatchJob(models.Model):
    STATUS_PENDING = 'pending'
    STATUS_RUNNING = 'running'
    STATUS_SUCCESS = 'success'
    STATUS_FAILED = 'failed'
    STATUS_PARTIAL = 'partial'

    STATUS_CHOICES = [
        (STATUS_PENDING, 'Pending'),
        (STATUS_RUNNING, 'Running'),
        (STATUS_SUCCESS, 'Success'),
        (STATUS_FAILED, 'Failed'),
        (STATUS_PARTIAL, 'Partial Success'),
    ]

    patch_template = models.ForeignKey(
        PatchTemplate, on_delete=models.SET_NULL, null=True, blank=True, related_name='jobs'
    )
    cluster = models.ForeignKey(Cluster, on_delete=models.CASCADE, related_name='patch_jobs')
    patch_content = models.TextField(help_text='Snapshot of patch content at time of application')
    target_role = models.CharField(max_length=20)
    target_nodes = models.ManyToManyField(Node, blank=True, related_name='patch_jobs')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING, db_index=True)
    celery_task_id = models.CharField(max_length=200, blank=True)
    initiated_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    logs = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        tmpl = self.patch_template.name if self.patch_template else 'Ad-hoc'
        return f'{tmpl} on {self.cluster.name} ({self.status})'

    def append_log(self, line: str):
        PatchJob.objects.filter(pk=self.pk).update(
            logs=Concat(F('logs'), Value(line + '\n'))
        )
        self.logs = self.logs + line + '\n'

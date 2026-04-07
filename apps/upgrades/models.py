from django.db import models
from django.db.models import F
from django.db.models.functions import Concat
from django.db.models import Value
from django.contrib.auth.models import User
from apps.clusters.models import Cluster, Node


class UpgradeJob(models.Model):
    TYPE_IMAGE = 'image'
    TYPE_K8S = 'k8s'

    JOB_TYPE_CHOICES = [
        (TYPE_IMAGE, 'Image Upgrade'),
        (TYPE_K8S, 'K8s Upgrade'),
    ]

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

    cluster = models.ForeignKey(Cluster, on_delete=models.CASCADE, related_name='upgrade_jobs')
    job_type = models.CharField(max_length=10, choices=JOB_TYPE_CHOICES)
    image_url = models.CharField(max_length=500, blank=True, help_text='For image upgrade: full image URL')
    target_version = models.CharField(max_length=50, blank=True, help_text='For k8s upgrade: target version e.g. 1.32.0')
    target_nodes = models.ManyToManyField(Node, blank=True, related_name='upgrade_jobs')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING, db_index=True)
    celery_task_id = models.CharField(max_length=200, blank=True)
    initiated_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    logs = models.TextField(blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.get_job_type_display()} on {self.cluster.name} ({self.status})'

    def append_log(self, line: str):
        UpgradeJob.objects.filter(pk=self.pk).update(
            logs=Concat(F('logs'), Value(line + '\n'))
        )
        self.logs = self.logs + line + '\n'

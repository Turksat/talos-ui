from django.db import models
from django.contrib.auth.models import User


class Cluster(models.Model):
    name = models.CharField(max_length=200)
    endpoint = models.CharField(max_length=500, help_text='Talos API endpoint: IP or IP:port (e.g. 192.168.1.10 or 192.168.1.10:50000)')
    talosconfig_content = models.TextField(help_text='Paste your talosconfig YAML here')
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='clusters')
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return self.name


class Node(models.Model):
    ROLE_CONTROLPLANE = 'controlplane'
    ROLE_WORKER = 'worker'

    ROLE_CHOICES = [
        (ROLE_CONTROLPLANE, 'Control Plane'),
        (ROLE_WORKER, 'Worker'),
    ]

    cluster = models.ForeignKey(Cluster, on_delete=models.CASCADE, related_name='nodes')
    ip_address = models.GenericIPAddressField()
    hostname = models.CharField(max_length=200, blank=True)
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default=ROLE_WORKER)
    status = models.CharField(max_length=50, default='unknown')
    talos_version = models.CharField(max_length=50, blank=True)
    k8s_version = models.CharField(max_length=50, blank=True)
    last_seen = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = ('cluster', 'ip_address')
        ordering = ['role', 'ip_address']

    def __str__(self):
        return f'{self.hostname or self.ip_address} ({self.cluster.name})'


class NodeOperation(models.Model):
    OP_REBOOT = 'reboot'
    OP_SHUTDOWN = 'shutdown'
    OP_RESET = 'reset'
    OP_RESTART_SERVICE = 'restart_service'

    OPERATION_CHOICES = [
        (OP_REBOOT, 'Reboot'),
        (OP_SHUTDOWN, 'Shutdown'),
        (OP_RESET, 'Reset'),
        (OP_RESTART_SERVICE, 'Restart Service'),
    ]

    STATUS_PENDING = 'pending'
    STATUS_RUNNING = 'running'
    STATUS_SUCCESS = 'success'
    STATUS_FAILED = 'failed'

    STATUS_CHOICES = [
        (STATUS_PENDING, 'Pending'),
        (STATUS_RUNNING, 'Running'),
        (STATUS_SUCCESS, 'Success'),
        (STATUS_FAILED, 'Failed'),
    ]

    node = models.ForeignKey(Node, on_delete=models.CASCADE, related_name='operations')
    operation = models.CharField(max_length=30, choices=OPERATION_CHOICES)
    service_name = models.CharField(max_length=100, blank=True, help_text='For restart_service only')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    initiated_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    started_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    output = models.TextField(blank=True)

    class Meta:
        ordering = ['-started_at']

    def __str__(self):
        return f'{self.get_operation_display()} on {self.node} ({self.status})'

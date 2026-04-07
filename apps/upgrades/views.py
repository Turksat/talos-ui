from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse

from apps.clusters.models import Node
from apps.clusters.mixins import operator_required
from .models import UpgradeJob
from .forms import ImageUpgradeForm, K8sUpgradeForm
from .tasks import run_image_upgrade, run_k8s_upgrade


@login_required
@operator_required
def image_upgrade(request):
    form = ImageUpgradeForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        cluster = form.cleaned_data['cluster']
        image_url = form.cleaned_data['image_url']
        target_nodes = form.cleaned_data.get('target_nodes', [])

        job = UpgradeJob.objects.create(
            cluster=cluster,
            job_type=UpgradeJob.TYPE_IMAGE,
            image_url=image_url,
            initiated_by=request.user,
        )
        if target_nodes:
            job.target_nodes.set(target_nodes)
        job.save()

        task = run_image_upgrade.delay(job.pk)
        job.celery_task_id = task.id
        job.save(update_fields=['celery_task_id'])

        messages.success(request, f'Image upgrade job #{job.pk} started.')
        return redirect('upgrades:job_detail', pk=job.pk)

    return render(request, 'upgrades/image_upgrade.html', {'form': form})


@login_required
@operator_required
def k8s_upgrade(request):
    form = K8sUpgradeForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        cluster = form.cleaned_data['cluster']
        target_version = form.cleaned_data['target_version']

        job = UpgradeJob.objects.create(
            cluster=cluster,
            job_type=UpgradeJob.TYPE_K8S,
            target_version=target_version,
            initiated_by=request.user,
        )

        task = run_k8s_upgrade.delay(job.pk)
        job.celery_task_id = task.id
        job.save(update_fields=['celery_task_id'])

        messages.success(request, f'K8s upgrade job #{job.pk} started.')
        return redirect('upgrades:job_detail', pk=job.pk)

    return render(request, 'upgrades/k8s_upgrade.html', {'form': form})


@login_required
def job_list(request):
    jobs = UpgradeJob.objects.select_related('cluster', 'initiated_by').all()
    return render(request, 'upgrades/job_list.html', {'jobs': jobs})


@login_required
def job_detail(request, pk):
    job = get_object_or_404(UpgradeJob, pk=pk)
    return render(request, 'upgrades/job_detail.html', {'job': job})


@login_required
def job_status_api(request, pk):
    """JSON API for polling job status."""
    job = get_object_or_404(UpgradeJob, pk=pk)
    return JsonResponse({
        'status': job.status,
        'logs': job.logs,
        'completed_at': job.completed_at.isoformat() if job.completed_at else None,
    })


@login_required
def get_cluster_nodes(request, cluster_pk):
    """AJAX: return nodes for a cluster (used by upgrade forms)."""
    nodes = Node.objects.filter(cluster_id=cluster_pk).values('id', 'ip_address', 'hostname', 'role')
    return JsonResponse({'nodes': list(nodes)})

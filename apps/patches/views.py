from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse

from apps.clusters.models import Node
from apps.clusters.mixins import operator_required, admin_required
from .models import PatchTemplate, PatchJob
from .forms import PatchTemplateForm, PatchApplyForm
from .tasks import run_patch_job


@login_required
def patch_list(request):
    templates = PatchTemplate.objects.select_related('created_by').all()
    return render(request, 'patches/patch_list.html', {'templates': templates})


@login_required
@operator_required
def patch_create(request):
    form = PatchTemplateForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        patch = form.save(commit=False)
        patch.created_by = request.user
        patch.save()
        messages.success(request, f'Patch "{patch.name}" saved.')
        return redirect('patches:list')
    return render(request, 'patches/patch_form.html', {'form': form, 'title': 'New Patch Template'})


@login_required
@operator_required
def patch_edit(request, pk):
    patch = get_object_or_404(PatchTemplate, pk=pk)
    form = PatchTemplateForm(request.POST or None, instance=patch)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, f'Patch "{patch.name}" updated.')
        return redirect('patches:list')
    return render(request, 'patches/patch_form.html', {'form': form, 'title': f'Edit: {patch.name}', 'patch': patch})


@login_required
@admin_required
def patch_delete(request, pk):
    patch = get_object_or_404(PatchTemplate, pk=pk)
    if request.method == 'POST':
        name = patch.name
        patch.delete()
        messages.success(request, f'Patch "{name}" deleted.')
        return redirect('patches:list')
    return render(request, 'patches/patch_confirm_delete.html', {'patch': patch})


@login_required
@operator_required
def patch_apply(request, pk):
    patch = get_object_or_404(PatchTemplate, pk=pk)
    form = PatchApplyForm(request.POST or None, patch_template=patch)
    if request.method == 'POST' and form.is_valid():
        cluster = form.cleaned_data['cluster']
        target_role = form.cleaned_data['target_role']
        target_nodes = form.cleaned_data.get('target_nodes', [])

        job = PatchJob.objects.create(
            patch_template=patch,
            cluster=cluster,
            patch_content=patch.patch_content,
            target_role=target_role,
            initiated_by=request.user,
        )
        if target_nodes:
            job.target_nodes.set(target_nodes)

        task = run_patch_job.delay(job.pk)
        job.celery_task_id = task.id
        job.save(update_fields=['celery_task_id'])

        messages.success(request, f'Patch job #{job.pk} started.')
        return redirect('patches:job_detail', pk=job.pk)

    return render(request, 'patches/patch_apply.html', {'form': form, 'patch': patch})


@login_required
def job_list(request):
    jobs = PatchJob.objects.select_related('patch_template', 'cluster', 'initiated_by').all()
    return render(request, 'patches/job_list.html', {'jobs': jobs})


@login_required
def job_detail(request, pk):
    job = get_object_or_404(PatchJob, pk=pk)
    return render(request, 'patches/job_detail.html', {'job': job})


@login_required
def job_status_api(request, pk):
    job = get_object_or_404(PatchJob, pk=pk)
    return JsonResponse({
        'status': job.status,
        'logs': job.logs,
        'completed_at': job.completed_at.isoformat() if job.completed_at else None,
    })


@login_required
def get_cluster_nodes(request, cluster_pk):
    """AJAX: return nodes for a cluster filtered by role."""
    role = request.GET.get('role', 'all')
    qs = Node.objects.filter(cluster_id=cluster_pk)
    if role == 'controlplane':
        qs = qs.filter(role='controlplane')
    elif role == 'worker':
        qs = qs.filter(role='worker')
    return JsonResponse({'nodes': list(qs.values('id', 'ip_address', 'hostname', 'role'))})

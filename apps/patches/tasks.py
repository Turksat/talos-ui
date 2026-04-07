import logging
import yaml
from celery import shared_task
from django.utils import timezone
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

logger = logging.getLogger(__name__)


def _send_ws(job_id, data: dict):
    channel_layer = get_channel_layer()
    if channel_layer:
        async_to_sync(channel_layer.group_send)(
            f'patch_{job_id}',
            {'type': 'patch.progress', **data},
        )


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge override into base. Lists are replaced, not appended."""
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _apply_patch_via_fetch(t, node_ip: str, patch_content: str) -> dict:
    """
    Fetch current machine config, deep-merge the YAML patch, then apply
    back with apply-config. This bypasses multi-document limitations of
    talosctl patch machineconfig.
    """
    # 1. Fetch current config
    fetch = t.get_machineconfig(node_ip)
    if not fetch['success']:
        return fetch

    current_yaml = fetch['stdout']

    # 2. Parse patch (YAML only; JSON RFC 6902 not supported for multi-doc)
    try:
        patch_data = yaml.safe_load(patch_content)
    except yaml.YAMLError as e:
        return {
            'stdout': '', 'stderr': f'Invalid patch YAML: {e}',
            'returncode': -1, 'success': False,
        }

    if not isinstance(patch_data, dict):
        return {
            'stdout': '',
            'stderr': 'Patch must be a YAML mapping (not a list). JSON RFC 6902 array patches are not supported for multi-document machine configs.',
            'returncode': -1, 'success': False,
        }

    # 3. Parse all documents from current config
    try:
        docs = list(yaml.safe_load_all(current_yaml))
    except yaml.YAMLError as e:
        return {
            'stdout': '', 'stderr': f'Failed to parse current machine config: {e}',
            'returncode': -1, 'success': False,
        }

    if not docs:
        return {
            'stdout': '', 'stderr': 'No documents found in current machine config.',
            'returncode': -1, 'success': False,
        }

    # 4. Merge patch into the v1alpha1 document (first doc without apiVersion/kind at root,
    #    or the one that has 'machine' key)
    merged = False
    for i, doc in enumerate(docs):
        if not isinstance(doc, dict):
            continue
        # v1alpha1 machine config has 'machine' or 'version' key
        if 'machine' in doc or doc.get('version') == 'v1alpha1':
            docs[i] = _deep_merge(doc, patch_data)
            merged = True
            break

    if not merged:
        # Fall back: merge into first dict document
        for i, doc in enumerate(docs):
            if isinstance(doc, dict):
                docs[i] = _deep_merge(doc, patch_data)
                merged = True
                break

    if not merged:
        return {
            'stdout': '', 'stderr': 'Could not find a v1alpha1 document to patch.',
            'returncode': -1, 'success': False,
        }

    # 5. Serialize back to YAML (all documents)
    try:
        merged_yaml = yaml.dump_all(
            docs,
            default_flow_style=False,
            allow_unicode=True,
            sort_keys=False,
        )
    except yaml.YAMLError as e:
        return {
            'stdout': '', 'stderr': f'Failed to serialize merged config: {e}',
            'returncode': -1, 'success': False,
        }

    # 6. Apply via apply-config
    return t.apply_machineconfig(node_ip, merged_yaml, mode='auto')


@shared_task(bind=True)
def run_patch_job(self, job_id: int):
    from .models import PatchJob
    from apps.clusters.models import Node
    from apps.clusters.talosctl import TalosctlRunner

    try:
        job = PatchJob.objects.select_related('cluster').prefetch_related('target_nodes').get(pk=job_id)
    except PatchJob.DoesNotExist:
        logger.error('run_patch_job: job %s not found', job_id)
        return {'job_id': job_id, 'status': 'not_found'}
    job.status = PatchJob.STATUS_RUNNING
    job.started_at = timezone.now()
    job.celery_task_id = self.request.id
    job.save(update_fields=['status', 'started_at', 'celery_task_id'])

    # Resolve target nodes
    nodes = list(job.target_nodes.all())
    if not nodes:
        qs = job.cluster.nodes.all()
        if job.target_role == 'controlplane':
            qs = qs.filter(role='controlplane')
        elif job.target_role == 'worker':
            qs = qs.filter(role='worker')
        nodes = list(qs)

    success_count = 0
    fail_count = 0

    try:
        with TalosctlRunner(job.cluster) as t:
            for node in nodes:
                msg = f'[{node.ip_address}] Applying patch...'
                logger.info(msg)
                job.append_log(msg)
                _send_ws(job_id, {'node': node.ip_address, 'status': 'patching', 'message': msg})

                result = _apply_patch_via_fetch(t, node.ip_address, job.patch_content)

                output = (result.get('stdout') or '') + (result.get('stderr') or '')
                if output.strip():
                    job.append_log(output.strip())
                    _send_ws(job_id, {'node': node.ip_address, 'status': 'patching', 'message': output.strip()})

                if result['success']:
                    success_count += 1
                    msg = f'[{node.ip_address}] Patch applied successfully.'
                    _send_ws(job_id, {'node': node.ip_address, 'status': 'success', 'message': msg})
                else:
                    fail_count += 1
                    msg = f'[{node.ip_address}] Patch FAILED: {result.get("stderr", "").strip()}'
                    logger.error(msg)
                    _send_ws(job_id, {'node': node.ip_address, 'status': 'failed', 'message': msg})
                job.append_log(msg)

    except Exception as exc:
        logger.exception(f'Patch job {job_id} raised an exception')
        job.append_log(f'EXCEPTION: {exc}')
        job.status = PatchJob.STATUS_FAILED
    else:
        if fail_count == 0:
            job.status = PatchJob.STATUS_SUCCESS
        elif success_count == 0:
            job.status = PatchJob.STATUS_FAILED
        else:
            job.status = PatchJob.STATUS_PARTIAL
    finally:
        job.completed_at = timezone.now()
        job.save(update_fields=['status', 'completed_at'])
        _send_ws(job_id, {
            'status': job.status,
            'message': f'Job finished: {job.status}',
            'done': True,
        })

    return {'job_id': job_id, 'status': job.status}

import logging
from celery import shared_task
from django.utils import timezone
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

logger = logging.getLogger(__name__)


def _send_ws_progress(job_id, data: dict):
    """Push progress update to WebSocket group."""
    channel_layer = get_channel_layer()
    if channel_layer:
        async_to_sync(channel_layer.group_send)(
            f'upgrade_{job_id}',
            {'type': 'upgrade.progress', **data},
        )


@shared_task(bind=True)
def run_image_upgrade(self, job_id: int):
    from .models import UpgradeJob
    from apps.clusters.talosctl import TalosctlRunner

    try:
        job = UpgradeJob.objects.select_related('cluster').prefetch_related('target_nodes').get(pk=job_id)
    except UpgradeJob.DoesNotExist:
        logger.error('run_image_upgrade: job %s not found', job_id)
        return {'job_id': job_id, 'status': 'not_found'}
    job.status = UpgradeJob.STATUS_RUNNING
    job.started_at = timezone.now()
    job.celery_task_id = self.request.id
    job.save(update_fields=['status', 'started_at', 'celery_task_id'])

    nodes = list(job.target_nodes.all())
    if not nodes:
        nodes = list(job.cluster.nodes.all())

    success_count = 0
    fail_count = 0

    try:
        with TalosctlRunner(job.cluster) as t:
            for node in nodes:
                msg = f'[{node.ip_address}] Starting image upgrade to {job.image_url}'
                logger.info(msg)
                job.append_log(msg)
                _send_ws_progress(job_id, {
                    'node': node.ip_address,
                    'status': 'upgrading',
                    'message': msg,
                })

                node_success = False
                for line, is_done, success in t.upgrade_stream(node.ip_address, job.image_url):
                    if is_done:
                        node_success = success
                    elif line:
                        job.append_log(line)
                        _send_ws_progress(job_id, {
                            'node': node.ip_address,
                            'status': 'upgrading',
                            'message': line,
                        })

                if node_success:
                    success_count += 1
                    msg = f'[{node.ip_address}] Upgrade completed successfully.'
                    _send_ws_progress(job_id, {
                        'node': node.ip_address,
                        'status': 'success',
                        'message': msg,
                    })
                else:
                    fail_count += 1
                    msg = f'[{node.ip_address}] Upgrade FAILED.'
                    logger.error(msg)
                    _send_ws_progress(job_id, {
                        'node': node.ip_address,
                        'status': 'failed',
                        'message': msg,
                    })
                job.append_log(msg)

    except Exception as exc:
        logger.exception(f'Image upgrade job {job_id} raised an exception')
        job.append_log(f'EXCEPTION: {exc}')
        job.status = UpgradeJob.STATUS_FAILED
    else:
        if fail_count == 0:
            job.status = UpgradeJob.STATUS_SUCCESS
        elif success_count == 0:
            job.status = UpgradeJob.STATUS_FAILED
        else:
            job.status = UpgradeJob.STATUS_PARTIAL
    finally:
        job.completed_at = timezone.now()
        job.save(update_fields=['status', 'completed_at'])
        _send_ws_progress(job_id, {
            'status': job.status,
            'message': f'Job finished with status: {job.status}',
            'done': True,
        })

    return {'job_id': job_id, 'status': job.status}


@shared_task(bind=True)
def run_k8s_upgrade(self, job_id: int):
    from .models import UpgradeJob
    from apps.clusters.talosctl import TalosctlRunner

    try:
        job = UpgradeJob.objects.select_related('cluster').get(pk=job_id)
    except UpgradeJob.DoesNotExist:
        logger.error('run_k8s_upgrade: job %s not found', job_id)
        return {'job_id': job_id, 'status': 'not_found'}
    job.status = UpgradeJob.STATUS_RUNNING
    job.started_at = timezone.now()
    job.celery_task_id = self.request.id
    job.save(update_fields=['status', 'started_at', 'celery_task_id'])

    msg = f'Starting Kubernetes upgrade to {job.target_version} on cluster {job.cluster.name}'
    logger.info(msg)
    job.append_log(msg)
    _send_ws_progress(job_id, {'status': 'running', 'message': msg})

    try:
        with TalosctlRunner(job.cluster) as t:
            k8s_success = False
            for line, is_done, success in t.upgrade_k8s_stream(job.target_version):
                if is_done:
                    k8s_success = success
                elif line:
                    job.append_log(line)
                    _send_ws_progress(job_id, {'status': 'running', 'message': line})
                    if 'unsupported upgrade path' in line and '->' in line:
                        job.append_log(
                            'HINT: talosctl upgrade-k8s only supports minor version upgrades '
                            '(e.g. 1.34.x → 1.35.0). For patch version upgrades (e.g. 1.35.0 → 1.35.2) '
                            'use Image Upgrade with the appropriate installer image.'
                        )

        if k8s_success:
            job.status = UpgradeJob.STATUS_SUCCESS
            msg = 'Kubernetes upgrade completed successfully.'
        else:
            job.status = UpgradeJob.STATUS_FAILED
            msg = 'Kubernetes upgrade FAILED.'

        logger.info(msg)
        job.append_log(msg)

    except Exception as exc:
        logger.exception(f'K8s upgrade job {job_id} raised an exception')
        job.append_log(f'EXCEPTION: {exc}')
        job.status = UpgradeJob.STATUS_FAILED
        msg = str(exc)
    finally:
        job.completed_at = timezone.now()
        job.save(update_fields=['status', 'completed_at'])
        _send_ws_progress(job_id, {
            'status': job.status,
            'message': msg,
            'done': True,
        })

    return {'job_id': job_id, 'status': job.status}

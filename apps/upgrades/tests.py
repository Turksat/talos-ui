from unittest.mock import patch, MagicMock, call

from django.test import TestCase, Client, override_settings
from django.contrib.auth.models import User
from django.urls import reverse

from apps.accounts.models import UserProfile
from apps.clusters.models import Cluster, Node
from apps.upgrades.models import UpgradeJob
from apps.upgrades.forms import ImageUpgradeForm, K8sUpgradeForm


FAKE_TALOSCONFIG = "context: test\ncontexts:\n  test:\n    endpoints: []\n"


def make_cluster(user):
    return Cluster.objects.create(
        name='upgrade-cluster',
        endpoint='192.168.1.10',
        talosconfig_content=FAKE_TALOSCONFIG,
        created_by=user,
    )


def make_node(cluster, ip='192.168.1.10'):
    return Node.objects.create(
        cluster=cluster,
        ip_address=ip,
        role=Node.ROLE_CONTROLPLANE,
    )


def make_operator(username='operator'):
    u = User.objects.create_user(username, password='pass')
    u.profile.role = UserProfile.ROLE_OPERATOR
    u.profile.save()
    return u


def make_viewer(username='viewer'):
    return User.objects.create_user(username, password='pass')


# ─── Model tests ─────────────────────────────────────────────────────────────

class UpgradeJobModelTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('u', password='p')
        self.cluster = make_cluster(self.user)

    def test_str_image_upgrade(self):
        job = UpgradeJob.objects.create(
            cluster=self.cluster,
            job_type=UpgradeJob.TYPE_IMAGE,
            image_url='ghcr.io/siderolabs/installer:v1.8.0',
            initiated_by=self.user,
        )
        self.assertIn('Image Upgrade', str(job))
        self.assertIn('upgrade-cluster', str(job))

    def test_str_k8s_upgrade(self):
        job = UpgradeJob.objects.create(
            cluster=self.cluster,
            job_type=UpgradeJob.TYPE_K8S,
            target_version='1.32.0',
            initiated_by=self.user,
        )
        self.assertIn('K8s Upgrade', str(job))

    def test_default_status_is_pending(self):
        job = UpgradeJob.objects.create(
            cluster=self.cluster,
            job_type=UpgradeJob.TYPE_IMAGE,
            initiated_by=self.user,
        )
        self.assertEqual(job.status, UpgradeJob.STATUS_PENDING)

    def test_append_log(self):
        job = UpgradeJob.objects.create(
            cluster=self.cluster,
            job_type=UpgradeJob.TYPE_IMAGE,
            initiated_by=self.user,
        )
        job.append_log('line one')
        job.append_log('line two')
        job.refresh_from_db()
        self.assertIn('line one', job.logs)
        self.assertIn('line two', job.logs)

    def test_append_log_accumulates_all_lines(self):
        job = UpgradeJob.objects.create(
            cluster=self.cluster,
            job_type=UpgradeJob.TYPE_IMAGE,
            initiated_by=self.user,
        )
        for i in range(10):
            job.append_log(f'step {i}')
        job.refresh_from_db()
        for i in range(10):
            self.assertIn(f'step {i}', job.logs)

    def test_status_choices_include_partial(self):
        choices = dict(UpgradeJob.STATUS_CHOICES)
        self.assertIn(UpgradeJob.STATUS_PARTIAL, choices)

    def test_target_nodes_many_to_many(self):
        node = make_node(self.cluster)
        job = UpgradeJob.objects.create(
            cluster=self.cluster,
            job_type=UpgradeJob.TYPE_IMAGE,
            initiated_by=self.user,
        )
        job.target_nodes.set([node])
        self.assertEqual(job.target_nodes.count(), 1)

    def test_ordering_most_recent_first(self):
        j1 = UpgradeJob.objects.create(
            cluster=self.cluster, job_type=UpgradeJob.TYPE_IMAGE, initiated_by=self.user
        )
        j2 = UpgradeJob.objects.create(
            cluster=self.cluster, job_type=UpgradeJob.TYPE_K8S, initiated_by=self.user
        )
        jobs = list(UpgradeJob.objects.all())
        self.assertEqual(jobs[0], j2)


# ─── Form tests ───────────────────────────────────────────────────────────────

class ImageUpgradeFormTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('u', password='p')
        self.cluster = make_cluster(self.user)

    def test_valid_image_url(self):
        form = ImageUpgradeForm(data={
            'cluster': self.cluster.pk,
            'image_url': 'ghcr.io/siderolabs/installer:v1.8.0',
        })
        self.assertTrue(form.is_valid(), form.errors)

    def test_invalid_image_url_no_tag(self):
        form = ImageUpgradeForm(data={
            'cluster': self.cluster.pk,
            'image_url': 'ghcr.io/siderolabs/installer',
        })
        self.assertFalse(form.is_valid())
        self.assertIn('image_url', form.errors)

    def test_invalid_image_url_spaces(self):
        form = ImageUpgradeForm(data={
            'cluster': self.cluster.pk,
            'image_url': 'bad url with spaces:tag',
        })
        self.assertFalse(form.is_valid())

    def test_missing_image_url(self):
        form = ImageUpgradeForm(data={'cluster': self.cluster.pk})
        self.assertFalse(form.is_valid())
        self.assertIn('image_url', form.errors)

    def test_missing_cluster(self):
        form = ImageUpgradeForm(data={'image_url': 'ghcr.io/siderolabs/installer:v1.8.0'})
        self.assertFalse(form.is_valid())
        self.assertIn('cluster', form.errors)


class K8sUpgradeFormTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('u', password='p')
        self.cluster = make_cluster(self.user)

    def test_valid_version(self):
        form = K8sUpgradeForm(data={
            'cluster': self.cluster.pk,
            'target_version': '1.32.0',
        })
        self.assertTrue(form.is_valid(), form.errors)

    def test_valid_version_with_v_prefix(self):
        form = K8sUpgradeForm(data={
            'cluster': self.cluster.pk,
            'target_version': 'v1.32.0',
        })
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data['target_version'], '1.32.0')

    def test_invalid_version_format_missing_patch(self):
        form = K8sUpgradeForm(data={
            'cluster': self.cluster.pk,
            'target_version': '1.32',
        })
        self.assertFalse(form.is_valid())
        self.assertIn('target_version', form.errors)

    def test_invalid_version_text(self):
        form = K8sUpgradeForm(data={
            'cluster': self.cluster.pk,
            'target_version': 'latest',
        })
        self.assertFalse(form.is_valid())

    def test_missing_version(self):
        form = K8sUpgradeForm(data={'cluster': self.cluster.pk})
        self.assertFalse(form.is_valid())
        self.assertIn('target_version', form.errors)


# ─── Celery task tests ────────────────────────────────────────────────────────

@override_settings(CHANNEL_LAYERS={'default': {'BACKEND': 'channels.layers.InMemoryChannelLayer'}})
class RunImageUpgradeTaskTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('u', password='p')
        self.cluster = make_cluster(self.user)
        self.node = make_node(self.cluster, ip='192.168.1.10')

    def _make_job(self):
        job = UpgradeJob.objects.create(
            cluster=self.cluster,
            job_type=UpgradeJob.TYPE_IMAGE,
            image_url='ghcr.io/siderolabs/installer:v1.8.0',
            initiated_by=self.user,
        )
        job.target_nodes.set([self.node])
        return job

    @patch('apps.clusters.talosctl.TalosctlRunner')
    def test_success_sets_status_success(self, mock_cls):
        mock_runner = MagicMock()
        mock_runner.upgrade_stream.return_value = iter([
            ('Upgrading...', False, None),
            ('', True, True),
        ])
        mock_cls.return_value.__enter__ = MagicMock(return_value=mock_runner)
        mock_cls.return_value.__exit__ = MagicMock(return_value=False)

        from apps.upgrades.tasks import run_image_upgrade
        job = self._make_job()
        with patch('apps.clusters.talosctl.TalosctlRunner', mock_cls):
            run_image_upgrade.apply(args=[job.pk])

        job.refresh_from_db()
        self.assertEqual(job.status, UpgradeJob.STATUS_SUCCESS)
        self.assertIsNotNone(job.completed_at)
        self.assertIsNotNone(job.started_at)

    def test_failure_sets_status_failed(self):
        mock_runner = MagicMock()
        mock_runner.upgrade_stream.return_value = iter([
            ('Error occurred', False, None),
            ('', True, False),
        ])
        mock_cls = MagicMock()
        mock_cls.return_value.__enter__ = MagicMock(return_value=mock_runner)
        mock_cls.return_value.__exit__ = MagicMock(return_value=False)

        from apps.upgrades.tasks import run_image_upgrade
        job = self._make_job()
        with patch('apps.clusters.talosctl.TalosctlRunner', mock_cls):
            run_image_upgrade.apply(args=[job.pk])

        job.refresh_from_db()
        self.assertEqual(job.status, UpgradeJob.STATUS_FAILED)

    def test_partial_success_with_multiple_nodes(self):
        node2 = Node.objects.create(
            cluster=self.cluster, ip_address='192.168.1.11', role=Node.ROLE_WORKER
        )
        job = UpgradeJob.objects.create(
            cluster=self.cluster,
            job_type=UpgradeJob.TYPE_IMAGE,
            image_url='ghcr.io/siderolabs/installer:v1.8.0',
            initiated_by=self.user,
        )
        job.target_nodes.set([self.node, node2])

        mock_runner = MagicMock()
        mock_runner.upgrade_stream.side_effect = [
            iter([('', True, True)]),
            iter([('', True, False)]),
        ]
        mock_cls = MagicMock()
        mock_cls.return_value.__enter__ = MagicMock(return_value=mock_runner)
        mock_cls.return_value.__exit__ = MagicMock(return_value=False)

        from apps.upgrades.tasks import run_image_upgrade
        with patch('apps.clusters.talosctl.TalosctlRunner', mock_cls):
            run_image_upgrade.apply(args=[job.pk])

        job.refresh_from_db()
        self.assertEqual(job.status, UpgradeJob.STATUS_PARTIAL)

    def test_job_not_found_returns_not_found(self):
        from apps.upgrades.tasks import run_image_upgrade
        result = run_image_upgrade.apply(args=[99999])
        self.assertEqual(result.result['status'], 'not_found')

    def test_uses_cluster_nodes_when_no_target_nodes(self):
        job = UpgradeJob.objects.create(
            cluster=self.cluster,
            job_type=UpgradeJob.TYPE_IMAGE,
            image_url='ghcr.io/siderolabs/installer:v1.8.0',
            initiated_by=self.user,
        )

        mock_runner = MagicMock()
        mock_runner.upgrade_stream.return_value = iter([('', True, True)])
        mock_cls = MagicMock()
        mock_cls.return_value.__enter__ = MagicMock(return_value=mock_runner)
        mock_cls.return_value.__exit__ = MagicMock(return_value=False)

        from apps.upgrades.tasks import run_image_upgrade
        with patch('apps.clusters.talosctl.TalosctlRunner', mock_cls):
            run_image_upgrade.apply(args=[job.pk])

        self.assertEqual(mock_runner.upgrade_stream.call_count, 1)

    def test_exception_sets_failed(self):
        mock_cls = MagicMock()
        mock_cls.return_value.__enter__ = MagicMock(side_effect=RuntimeError('boom'))
        mock_cls.return_value.__exit__ = MagicMock(return_value=False)

        from apps.upgrades.tasks import run_image_upgrade
        job = self._make_job()
        with patch('apps.clusters.talosctl.TalosctlRunner', mock_cls):
            run_image_upgrade.apply(args=[job.pk])

        job.refresh_from_db()
        self.assertEqual(job.status, UpgradeJob.STATUS_FAILED)
        self.assertIn('boom', job.logs)

    def test_output_lines_logged(self):
        mock_runner = MagicMock()
        mock_runner.upgrade_stream.return_value = iter([
            ('upgrading node firmware', False, None),
            ('rebooting node', False, None),
            ('', True, True),
        ])
        mock_cls = MagicMock()
        mock_cls.return_value.__enter__ = MagicMock(return_value=mock_runner)
        mock_cls.return_value.__exit__ = MagicMock(return_value=False)

        from apps.upgrades.tasks import run_image_upgrade
        job = self._make_job()
        with patch('apps.clusters.talosctl.TalosctlRunner', mock_cls):
            run_image_upgrade.apply(args=[job.pk])

        job.refresh_from_db()
        self.assertIn('upgrading node firmware', job.logs)
        self.assertIn('rebooting node', job.logs)


@override_settings(CHANNEL_LAYERS={'default': {'BACKEND': 'channels.layers.InMemoryChannelLayer'}})
class RunK8sUpgradeTaskTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('u', password='p')
        self.cluster = make_cluster(self.user)

    def _make_job(self, version='1.32.0'):
        return UpgradeJob.objects.create(
            cluster=self.cluster,
            job_type=UpgradeJob.TYPE_K8S,
            target_version=version,
            initiated_by=self.user,
        )

    def test_success_sets_status_success(self):
        mock_runner = MagicMock()
        mock_runner.upgrade_k8s_stream.return_value = iter([
            ('updating api-server', False, None),
            ('', True, True),
        ])
        mock_cls = MagicMock()
        mock_cls.return_value.__enter__ = MagicMock(return_value=mock_runner)
        mock_cls.return_value.__exit__ = MagicMock(return_value=False)

        from apps.upgrades.tasks import run_k8s_upgrade
        job = self._make_job()
        with patch('apps.clusters.talosctl.TalosctlRunner', mock_cls):
            run_k8s_upgrade.apply(args=[job.pk])

        job.refresh_from_db()
        self.assertEqual(job.status, UpgradeJob.STATUS_SUCCESS)
        self.assertIsNotNone(job.completed_at)

    def test_failure_sets_status_failed(self):
        mock_runner = MagicMock()
        mock_runner.upgrade_k8s_stream.return_value = iter([
            ('unsupported upgrade path 1.30 -> 1.32', False, None),
            ('', True, False),
        ])
        mock_cls = MagicMock()
        mock_cls.return_value.__enter__ = MagicMock(return_value=mock_runner)
        mock_cls.return_value.__exit__ = MagicMock(return_value=False)

        from apps.upgrades.tasks import run_k8s_upgrade
        job = self._make_job()
        with patch('apps.clusters.talosctl.TalosctlRunner', mock_cls):
            run_k8s_upgrade.apply(args=[job.pk])

        job.refresh_from_db()
        self.assertEqual(job.status, UpgradeJob.STATUS_FAILED)

    def test_unsupported_path_hint_appended(self):
        mock_runner = MagicMock()
        mock_runner.upgrade_k8s_stream.return_value = iter([
            ('unsupported upgrade path 1.30 -> 1.32', False, None),
            ('', True, False),
        ])
        mock_cls = MagicMock()
        mock_cls.return_value.__enter__ = MagicMock(return_value=mock_runner)
        mock_cls.return_value.__exit__ = MagicMock(return_value=False)

        from apps.upgrades.tasks import run_k8s_upgrade
        job = self._make_job()
        with patch('apps.clusters.talosctl.TalosctlRunner', mock_cls):
            run_k8s_upgrade.apply(args=[job.pk])

        job.refresh_from_db()
        self.assertIn('HINT', job.logs)

    def test_job_not_found_returns_not_found(self):
        from apps.upgrades.tasks import run_k8s_upgrade
        result = run_k8s_upgrade.apply(args=[99999])
        self.assertEqual(result.result['status'], 'not_found')

    def test_exception_sets_failed(self):
        mock_cls = MagicMock()
        mock_cls.return_value.__enter__ = MagicMock(side_effect=OSError('network error'))
        mock_cls.return_value.__exit__ = MagicMock(return_value=False)

        from apps.upgrades.tasks import run_k8s_upgrade
        job = self._make_job()
        with patch('apps.clusters.talosctl.TalosctlRunner', mock_cls):
            run_k8s_upgrade.apply(args=[job.pk])

        job.refresh_from_db()
        self.assertEqual(job.status, UpgradeJob.STATUS_FAILED)

    def test_stream_lines_logged(self):
        mock_runner = MagicMock()
        mock_runner.upgrade_k8s_stream.return_value = iter([
            ('patching kube-apiserver', False, None),
            ('', True, True),
        ])
        mock_cls = MagicMock()
        mock_cls.return_value.__enter__ = MagicMock(return_value=mock_runner)
        mock_cls.return_value.__exit__ = MagicMock(return_value=False)

        from apps.upgrades.tasks import run_k8s_upgrade
        job = self._make_job()
        with patch('apps.clusters.talosctl.TalosctlRunner', mock_cls):
            run_k8s_upgrade.apply(args=[job.pk])

        job.refresh_from_db()
        self.assertIn('patching kube-apiserver', job.logs)


# ─── View tests ───────────────────────────────────────────────────────────────

@override_settings(CHANNEL_LAYERS={'default': {'BACKEND': 'channels.layers.InMemoryChannelLayer'}})
class UpgradeViewTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.operator = make_operator('operator_u')
        self.viewer = make_viewer('viewer_u')
        self.cluster = make_cluster(self.operator)

    def test_image_upgrade_requires_login(self):
        response = self.client.get(reverse('upgrades:image'))
        self.assertEqual(response.status_code, 302)

    def test_image_upgrade_viewer_forbidden(self):
        self.client.login(username='viewer_u', password='pass')
        response = self.client.get(reverse('upgrades:image'))
        self.assertIn(response.status_code, [302, 403])

    def test_image_upgrade_get_operator(self):
        self.client.login(username='operator_u', password='pass')
        response = self.client.get(reverse('upgrades:image'))
        self.assertEqual(response.status_code, 200)

    @patch('apps.upgrades.views.run_image_upgrade')
    def test_image_upgrade_post_valid_creates_job(self, mock_task):
        mock_task.delay.return_value = MagicMock(id='celery-task-id')
        self.client.login(username='operator_u', password='pass')
        response = self.client.post(reverse('upgrades:image'), {
            'cluster': self.cluster.pk,
            'image_url': 'ghcr.io/siderolabs/installer:v1.8.0',
        }, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(UpgradeJob.objects.filter(
            cluster=self.cluster, job_type=UpgradeJob.TYPE_IMAGE
        ).exists())

    @patch('apps.upgrades.views.run_image_upgrade')
    def test_image_upgrade_post_invalid_url_no_job(self, mock_task):
        self.client.login(username='operator_u', password='pass')
        response = self.client.post(reverse('upgrades:image'), {
            'cluster': self.cluster.pk,
            'image_url': 'no-tag-here',
        })
        self.assertEqual(response.status_code, 200)
        mock_task.delay.assert_not_called()

    def test_k8s_upgrade_requires_login(self):
        response = self.client.get(reverse('upgrades:k8s'))
        self.assertEqual(response.status_code, 302)

    def test_k8s_upgrade_get_operator(self):
        self.client.login(username='operator_u', password='pass')
        response = self.client.get(reverse('upgrades:k8s'))
        self.assertEqual(response.status_code, 200)

    @patch('apps.upgrades.views.run_k8s_upgrade')
    def test_k8s_upgrade_post_valid_creates_job(self, mock_task):
        mock_task.delay.return_value = MagicMock(id='celery-task-id-2')
        self.client.login(username='operator_u', password='pass')
        response = self.client.post(reverse('upgrades:k8s'), {
            'cluster': self.cluster.pk,
            'target_version': '1.32.0',
        }, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(UpgradeJob.objects.filter(
            cluster=self.cluster, job_type=UpgradeJob.TYPE_K8S
        ).exists())

    def test_upgrade_job_list_authenticated(self):
        self.client.login(username='operator_u', password='pass')
        response = self.client.get(reverse('upgrades:job_list'))
        self.assertEqual(response.status_code, 200)

    def test_upgrade_job_detail_404_unknown(self):
        self.client.login(username='operator_u', password='pass')
        response = self.client.get(reverse('upgrades:job_detail', args=[9999]))
        self.assertEqual(response.status_code, 404)

    def test_upgrade_job_status_api(self):
        job = UpgradeJob.objects.create(
            cluster=self.cluster,
            job_type=UpgradeJob.TYPE_IMAGE,
            image_url='ghcr.io/siderolabs/installer:v1.8.0',
            initiated_by=self.operator,
            status=UpgradeJob.STATUS_RUNNING,
        )
        self.client.login(username='operator_u', password='pass')
        response = self.client.get(reverse('upgrades:job_status_api', args=[job.pk]))
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn('status', data)
        self.assertEqual(data['status'], UpgradeJob.STATUS_RUNNING)

    def test_cluster_nodes_api(self):
        make_node(self.cluster)
        self.client.login(username='operator_u', password='pass')
        response = self.client.get(
            reverse('upgrades:cluster_nodes_api', args=[self.cluster.pk])
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        # API returns either a list or a dict with a 'nodes' key
        nodes = data if isinstance(data, list) else data.get('nodes', data)
        self.assertTrue(len(nodes) > 0)

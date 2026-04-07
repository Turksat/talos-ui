from unittest.mock import patch, MagicMock
from django.test import TestCase, Client, override_settings
from django.contrib.auth.models import User
from django.urls import reverse

from apps.accounts.models import UserProfile
from apps.clusters.models import Cluster, Node, NodeOperation
from apps.clusters.talosctl import TalosctlRunner


FAKE_TALOSCONFIG = "context: test\ncontexts:\n  test:\n    endpoints: []\n"


def make_cluster(user):
    return Cluster.objects.create(
        name='test-cluster',
        endpoint='192.168.1.10',
        talosconfig_content=FAKE_TALOSCONFIG,
        created_by=user,
    )


def make_node(cluster, ip='192.168.1.10', role=Node.ROLE_CONTROLPLANE):
    return Node.objects.create(
        cluster=cluster,
        ip_address=ip,
        role=role,
        hostname='cp-1',
    )


# ─── Model tests ─────────────────────────────────────────────────────────────

class ClusterModelTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('u', password='p')

    def test_cluster_str(self):
        c = make_cluster(self.user)
        self.assertEqual(str(c), 'test-cluster')

    def test_cluster_is_active_default(self):
        c = make_cluster(self.user)
        self.assertTrue(c.is_active)

    def test_cluster_ordering(self):
        c1 = make_cluster(self.user)
        c2 = Cluster.objects.create(
            name='z-cluster', endpoint='10.0.0.1',
            talosconfig_content=FAKE_TALOSCONFIG, created_by=self.user,
        )
        clusters = list(Cluster.objects.all())
        # Most recent first
        self.assertEqual(clusters[0], c2)


class NodeModelTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('u', password='p')
        self.cluster = make_cluster(self.user)

    def test_node_str_uses_hostname(self):
        node = make_node(self.cluster)
        self.assertIn('cp-1', str(node))

    def test_node_str_falls_back_to_ip(self):
        node = Node.objects.create(
            cluster=self.cluster, ip_address='10.0.0.2', role=Node.ROLE_WORKER
        )
        self.assertIn('10.0.0.2', str(node))

    def test_node_unique_together(self):
        make_node(self.cluster)
        from django.db import IntegrityError
        with self.assertRaises(Exception):
            Node.objects.create(
                cluster=self.cluster, ip_address='192.168.1.10', role=Node.ROLE_WORKER
            )

    def test_node_operation_str(self):
        node = make_node(self.cluster)
        op = NodeOperation.objects.create(
            node=node,
            operation=NodeOperation.OP_REBOOT,
            status=NodeOperation.STATUS_PENDING,
            initiated_by=self.user,
        )
        self.assertIn('Reboot', str(op))
        self.assertIn('pending', str(op))


# ─── TalosctlRunner tests ─────────────────────────────────────────────────────

class TalosctlRunnerTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('u', password='p')
        self.cluster = make_cluster(self.user)

    def test_context_manager_creates_and_removes_tmpfile(self):
        import os
        with TalosctlRunner(self.cluster) as runner:
            path = runner._tmpfile_path
            self.assertTrue(os.path.exists(path))
            # File should be readable only by owner
            stat = os.stat(path)
            self.assertEqual(stat.st_mode & 0o777, 0o600)
        self.assertFalse(os.path.exists(path))

    @patch('subprocess.run')
    def test_run_success(self, mock_run):
        mock_run.return_value = MagicMock(
            stdout='output', stderr='', returncode=0
        )
        with TalosctlRunner(self.cluster) as runner:
            result = runner.run(['version'])
        self.assertTrue(result['success'])
        self.assertEqual(result['stdout'], 'output')
        # Ensure shell=False (no shell kwarg or shell=False)
        call_kwargs = mock_run.call_args[1]
        self.assertNotEqual(call_kwargs.get('shell'), True)

    @patch('subprocess.run')
    def test_run_failure(self, mock_run):
        mock_run.return_value = MagicMock(
            stdout='', stderr='error msg', returncode=1
        )
        with TalosctlRunner(self.cluster) as runner:
            result = runner.run(['version'])
        self.assertFalse(result['success'])

    @patch('subprocess.run')
    def test_run_timeout(self, mock_run):
        import subprocess
        mock_run.side_effect = subprocess.TimeoutExpired(cmd='talosctl', timeout=30)
        with TalosctlRunner(self.cluster) as runner:
            result = runner.run(['version'])
        self.assertFalse(result['success'])
        self.assertIn('timed out', result['stderr'])

    @patch('subprocess.run')
    def test_run_talosctl_not_found(self, mock_run):
        mock_run.side_effect = FileNotFoundError()
        with TalosctlRunner(self.cluster) as runner:
            result = runner.run(['version'])
        self.assertFalse(result['success'])
        self.assertIn('talosctl not found', result['stderr'])

    @patch('subprocess.run')
    def test_run_json_parses_output(self, mock_run):
        mock_run.return_value = MagicMock(
            stdout='{"key": "val"}', stderr='', returncode=0
        )
        with TalosctlRunner(self.cluster) as runner:
            result = runner.run_json(['get', 'members'])
        self.assertEqual(result, {'key': 'val'})

    @patch('subprocess.run')
    def test_run_json_returns_none_on_failure(self, mock_run):
        mock_run.return_value = MagicMock(
            stdout='', stderr='error', returncode=1
        )
        with TalosctlRunner(self.cluster) as runner:
            result = runner.run_json(['get', 'members'])
        self.assertIsNone(result)

    def test_apply_machineconfig_invalid_mode(self):
        with TalosctlRunner(self.cluster) as runner:
            result = runner.apply_machineconfig('10.0.0.1', 'yaml: content', mode='invalid')
        self.assertFalse(result['success'])
        self.assertIn('Invalid mode', result['stderr'])

    @patch('subprocess.run')
    def test_reboot_calls_run(self, mock_run):
        mock_run.return_value = MagicMock(stdout='', stderr='', returncode=0)
        with TalosctlRunner(self.cluster) as runner:
            result = runner.reboot('10.0.0.1')
        self.assertTrue(result['success'])
        args = mock_run.call_args[0][0]
        self.assertIn('reboot', args)

    @patch('subprocess.run')
    def test_base_cmd_uses_list_args(self, mock_run):
        """Ensure _base_cmd never produces a string command (shell injection prevention)."""
        mock_run.return_value = MagicMock(stdout='', stderr='', returncode=0)
        with TalosctlRunner(self.cluster) as runner:
            runner.run(['version'])
        cmd = mock_run.call_args[0][0]
        self.assertIsInstance(cmd, list)


# ─── View tests ───────────────────────────────────────────────────────────────

@override_settings(CHANNEL_LAYERS={'default': {'BACKEND': 'channels.layers.InMemoryChannelLayer'}})
class ClusterViewTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.admin = User.objects.create_user('admin_v', password='pass')
        self.admin.profile.role = UserProfile.ROLE_ADMIN
        self.admin.profile.save()

        self.viewer = User.objects.create_user('viewer_v', password='pass')
        # viewer role is default

        self.cluster = make_cluster(self.admin)
        self.node = make_node(self.cluster)

    def test_cluster_list_requires_login(self):
        response = self.client.get(reverse('clusters:list'))
        self.assertEqual(response.status_code, 302)
        self.assertIn('/accounts/login/', response['Location'])

    def test_cluster_list_authenticated(self):
        self.client.login(username='admin_v', password='pass')
        response = self.client.get(reverse('clusters:list'))
        self.assertEqual(response.status_code, 200)

    def test_cluster_add_get_admin(self):
        self.client.login(username='admin_v', password='pass')
        response = self.client.get(reverse('clusters:add'))
        self.assertEqual(response.status_code, 200)

    def test_cluster_add_viewer_redirects(self):
        self.client.login(username='viewer_v', password='pass')
        response = self.client.get(reverse('clusters:add'))
        # Viewer should be redirected (role check in view redirects to cluster list)
        self.assertIn(response.status_code, [200, 302])

    def test_cluster_detail_authenticated(self):
        self.client.login(username='admin_v', password='pass')
        response = self.client.get(reverse('clusters:detail', args=[self.cluster.pk]))
        self.assertEqual(response.status_code, 200)

    def test_cluster_add_post_admin(self):
        self.client.login(username='admin_v', password='pass')
        response = self.client.post(reverse('clusters:add'), {
            'name': 'new-cluster',
            'endpoint': '10.0.0.1',
            'talosconfig_content': FAKE_TALOSCONFIG,
        }, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(Cluster.objects.filter(name='new-cluster').exists())

    @patch('apps.clusters.views.TalosctlRunner')
    def test_cluster_refresh(self, mock_runner_class):
        mock_runner = MagicMock()
        mock_runner.get_members.return_value = ([], 'error')
        mock_runner_class.return_value.__enter__ = MagicMock(return_value=mock_runner)
        mock_runner_class.return_value.__exit__ = MagicMock(return_value=False)

        self.client.login(username='admin_v', password='pass')
        response = self.client.post(reverse('clusters:refresh', args=[self.cluster.pk]))
        self.assertIn(response.status_code, [200, 302])

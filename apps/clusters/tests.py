import json
from unittest.mock import patch, MagicMock, call

from django.test import TestCase, Client, override_settings
from django.contrib.auth.models import User
from django.urls import reverse
from django.core.exceptions import PermissionDenied

from apps.accounts.models import UserProfile
from apps.clusters.models import Cluster, Node, NodeOperation
from apps.clusters.talosctl import TalosctlRunner
from apps.clusters.forms import (
    ClusterForm, NodeForm, RestartServiceForm,
    MachineConfigForm, ClusterBootstrapForm, NodeApplyConfigForm,
)


FAKE_TALOSCONFIG = "context: test\ncontexts:\n  test:\n    endpoints: []\n"


def make_cluster(user, name='test-cluster', endpoint='192.168.1.10'):
    return Cluster.objects.create(
        name=name,
        endpoint=endpoint,
        talosconfig_content=FAKE_TALOSCONFIG,
        created_by=user,
    )


def make_node(cluster, ip='192.168.1.10', role=Node.ROLE_CONTROLPLANE, hostname='cp-1'):
    return Node.objects.create(
        cluster=cluster,
        ip_address=ip,
        role=role,
        hostname=hostname,
    )


def make_admin(username='admin'):
    u = User.objects.create_user(username, password='pass')
    u.profile.role = UserProfile.ROLE_ADMIN
    u.profile.save()
    return u


def make_operator(username='operator'):
    u = User.objects.create_user(username, password='pass')
    u.profile.role = UserProfile.ROLE_OPERATOR
    u.profile.save()
    return u


def make_viewer(username='viewer'):
    return User.objects.create_user(username, password='pass')


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

    def test_cluster_ordering_most_recent_first(self):
        c1 = make_cluster(self.user, name='alpha')
        c2 = make_cluster(self.user, name='beta')
        clusters = list(Cluster.objects.all())
        self.assertEqual(clusters[0], c2)

    def test_cluster_created_by(self):
        c = make_cluster(self.user)
        self.assertEqual(c.created_by, self.user)


class NodeModelTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('u', password='p')
        self.cluster = make_cluster(self.user)

    def test_node_str_uses_hostname(self):
        node = make_node(self.cluster, hostname='cp-1')
        self.assertIn('cp-1', str(node))

    def test_node_str_falls_back_to_ip(self):
        node = Node.objects.create(
            cluster=self.cluster, ip_address='10.0.0.2', role=Node.ROLE_WORKER
        )
        self.assertIn('10.0.0.2', str(node))

    def test_node_unique_together(self):
        make_node(self.cluster)
        with self.assertRaises(Exception):
            Node.objects.create(
                cluster=self.cluster, ip_address='192.168.1.10', role=Node.ROLE_WORKER
            )

    def test_node_role_choices(self):
        roles = dict(Node.ROLE_CHOICES)
        self.assertIn(Node.ROLE_CONTROLPLANE, roles)
        self.assertIn(Node.ROLE_WORKER, roles)

    def test_node_default_status(self):
        node = Node.objects.create(
            cluster=self.cluster, ip_address='10.0.0.5'
        )
        self.assertEqual(node.status, 'unknown')


class NodeOperationModelTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('u', password='p')
        self.cluster = make_cluster(self.user)
        self.node = make_node(self.cluster)

    def test_operation_str(self):
        op = NodeOperation.objects.create(
            node=self.node,
            operation=NodeOperation.OP_REBOOT,
            status=NodeOperation.STATUS_PENDING,
            initiated_by=self.user,
        )
        self.assertIn('Reboot', str(op))
        self.assertIn('pending', str(op))

    def test_operation_choices_complete(self):
        ops = dict(NodeOperation.OPERATION_CHOICES)
        self.assertIn(NodeOperation.OP_REBOOT, ops)
        self.assertIn(NodeOperation.OP_SHUTDOWN, ops)
        self.assertIn(NodeOperation.OP_RESET, ops)
        self.assertIn(NodeOperation.OP_RESTART_SERVICE, ops)

    def test_operation_default_status_is_pending(self):
        op = NodeOperation.objects.create(
            node=self.node,
            operation=NodeOperation.OP_SHUTDOWN,
            initiated_by=self.user,
        )
        self.assertEqual(op.status, NodeOperation.STATUS_PENDING)


# ─── Form tests ───────────────────────────────────────────────────────────────

class ClusterFormTest(TestCase):
    def test_valid_form(self):
        form = ClusterForm(data={
            'name': 'my-cluster',
            'endpoint': '192.168.1.10',
            'talosconfig_content': FAKE_TALOSCONFIG,
        })
        self.assertTrue(form.is_valid(), form.errors)

    def test_endpoint_strips_https_protocol(self):
        form = ClusterForm(data={
            'name': 'x',
            'endpoint': 'https://192.168.1.10:6443/',
            'talosconfig_content': FAKE_TALOSCONFIG,
        })
        self.assertTrue(form.is_valid())
        self.assertEqual(form.cleaned_data['endpoint'], '192.168.1.10:6443')

    def test_endpoint_strips_http_protocol(self):
        form = ClusterForm(data={
            'name': 'x',
            'endpoint': 'http://10.0.0.1',
            'talosconfig_content': FAKE_TALOSCONFIG,
        })
        self.assertTrue(form.is_valid())
        self.assertEqual(form.cleaned_data['endpoint'], '10.0.0.1')

    def test_empty_endpoint_invalid(self):
        form = ClusterForm(data={
            'name': 'x',
            'endpoint': '',
            'talosconfig_content': FAKE_TALOSCONFIG,
        })
        self.assertFalse(form.is_valid())
        self.assertIn('endpoint', form.errors)

    def test_talosconfig_invalid_yaml(self):
        form = ClusterForm(data={
            'name': 'x',
            'endpoint': '10.0.0.1',
            'talosconfig_content': '{{invalid yaml::',
        })
        self.assertFalse(form.is_valid())
        self.assertIn('talosconfig_content', form.errors)

    def test_talosconfig_missing_context_key(self):
        form = ClusterForm(data={
            'name': 'x',
            'endpoint': '10.0.0.1',
            'talosconfig_content': 'foo: bar\nbaz: qux\n',
        })
        self.assertFalse(form.is_valid())
        self.assertIn('talosconfig_content', form.errors)

    def test_talosconfig_with_contexts_key_accepted(self):
        content = "contexts:\n  prod:\n    endpoints: []\n"
        form = ClusterForm(data={
            'name': 'x',
            'endpoint': '10.0.0.1',
            'talosconfig_content': content,
        })
        self.assertTrue(form.is_valid(), form.errors)

    def test_talosconfig_normalizes_crlf(self):
        crlf_config = FAKE_TALOSCONFIG.replace('\n', '\r\n')
        form = ClusterForm(data={
            'name': 'x',
            'endpoint': '10.0.0.1',
            'talosconfig_content': crlf_config,
        })
        self.assertTrue(form.is_valid())
        self.assertNotIn('\r', form.cleaned_data['talosconfig_content'])


class RestartServiceFormTest(TestCase):
    def test_valid_service_name(self):
        form = RestartServiceForm(data={'service_name': 'kubelet'})
        self.assertTrue(form.is_valid())

    def test_valid_service_name_with_hyphen(self):
        form = RestartServiceForm(data={'service_name': 'cri-containerd'})
        self.assertTrue(form.is_valid())

    def test_valid_service_name_with_underscore(self):
        form = RestartServiceForm(data={'service_name': 'kube_proxy'})
        self.assertTrue(form.is_valid())

    def test_invalid_service_name_spaces(self):
        form = RestartServiceForm(data={'service_name': 'kube let'})
        self.assertFalse(form.is_valid())
        self.assertIn('service_name', form.errors)

    def test_invalid_service_name_special_chars(self):
        form = RestartServiceForm(data={'service_name': 'kubelet; rm -rf /'})
        self.assertFalse(form.is_valid())

    def test_empty_service_name_invalid(self):
        form = RestartServiceForm(data={'service_name': ''})
        self.assertFalse(form.is_valid())


class MachineConfigFormTest(TestCase):
    VALID_YAML = "version: v1alpha1\nmachine:\n  type: controlplane\n"

    def test_valid_yaml_and_mode(self):
        form = MachineConfigForm(data={'yaml_content': self.VALID_YAML, 'mode': 'auto'})
        self.assertTrue(form.is_valid(), form.errors)

    def test_all_modes_are_valid(self):
        for mode in ('auto', 'interactive', 'reboot', 'no-reboot', 'staged'):
            form = MachineConfigForm(data={'yaml_content': self.VALID_YAML, 'mode': mode})
            self.assertTrue(form.is_valid(), f"Mode {mode!r} should be valid")

    def test_invalid_mode_rejected(self):
        form = MachineConfigForm(data={'yaml_content': self.VALID_YAML, 'mode': 'nuke'})
        self.assertFalse(form.is_valid())

    def test_invalid_yaml_rejected(self):
        form = MachineConfigForm(data={'yaml_content': '{{broken', 'mode': 'auto'})
        self.assertFalse(form.is_valid())
        self.assertIn('yaml_content', form.errors)

    def test_empty_yaml_rejected(self):
        form = MachineConfigForm(data={'yaml_content': '   ', 'mode': 'auto'})
        self.assertFalse(form.is_valid())

    def test_normalizes_crlf(self):
        crlf = self.VALID_YAML.replace('\n', '\r\n')
        form = MachineConfigForm(data={'yaml_content': crlf, 'mode': 'auto'})
        self.assertTrue(form.is_valid())
        self.assertNotIn('\r', form.cleaned_data['yaml_content'])


class ClusterBootstrapFormTest(TestCase):
    BASE_DATA = {
        'cluster_name': 'new-cluster',
        'endpoint': 'https://192.168.1.10:6443',
        'controlplane_nodes': '[{"ip": "192.168.1.10", "hostname": "cp-1"}]',
        'worker_nodes': '',
        'cp_net_config': '',
        'worker_net_config': '',
    }

    def _form(self, **overrides):
        data = {**self.BASE_DATA, **overrides}
        return ClusterBootstrapForm(data=data)

    def test_valid_minimal_form(self):
        form = self._form()
        self.assertTrue(form.is_valid(), form.errors)

    def test_endpoint_gets_https_prefix(self):
        form = self._form(endpoint='192.168.1.10:6443')
        self.assertTrue(form.is_valid())
        self.assertTrue(form.cleaned_data['endpoint'].startswith('https://'))

    def test_controlplane_nodes_parsed_correctly(self):
        form = self._form()
        self.assertTrue(form.is_valid())
        nodes = form.cleaned_data['controlplane_nodes']
        self.assertEqual(len(nodes), 1)
        self.assertEqual(nodes[0]['ip'], '192.168.1.10')
        self.assertEqual(nodes[0]['hostname'], 'cp-1')

    def test_legacy_node_format_comma_separated(self):
        form = self._form(controlplane_nodes='192.168.1.10:cp-1,192.168.1.11:cp-2')
        self.assertTrue(form.is_valid())
        nodes = form.cleaned_data['controlplane_nodes']
        self.assertEqual(len(nodes), 2)
        self.assertEqual(nodes[1]['ip'], '192.168.1.11')

    def test_invalid_ip_in_controlplane_nodes(self):
        form = self._form(controlplane_nodes='[{"ip": "not-an-ip"}]')
        self.assertFalse(form.is_valid())
        self.assertIn('controlplane_nodes', form.errors)

    def test_empty_controlplane_nodes_invalid(self):
        form = self._form(controlplane_nodes='[]')
        self.assertFalse(form.is_valid())
        self.assertIn('controlplane_nodes', form.errors)

    def test_worker_nodes_optional(self):
        form = self._form(worker_nodes='')
        self.assertTrue(form.is_valid())
        self.assertEqual(form.cleaned_data['worker_nodes'], [])

    def test_worker_nodes_parsed(self):
        form = self._form(worker_nodes='[{"ip": "192.168.1.20", "hostname": "worker-1"}]')
        self.assertTrue(form.is_valid())
        workers = form.cleaned_data['worker_nodes']
        self.assertEqual(len(workers), 1)
        self.assertEqual(workers[0]['ip'], '192.168.1.20')

    def test_net_config_disabled_by_default(self):
        form = self._form(cp_net_config='')
        self.assertTrue(form.is_valid())
        self.assertEqual(form.cleaned_data['cp_net_config'], {'enabled': False})

    def test_net_config_physical_nic_valid(self):
        cfg = json.dumps({'enabled': True, 'type': 'physical', 'interface': 'eth0', 'prefix': 24})
        form = self._form(cp_net_config=cfg)
        self.assertTrue(form.is_valid(), form.errors)

    def test_net_config_bond_requires_name(self):
        cfg = json.dumps({'enabled': True, 'type': 'bond', 'bond_name': '', 'bond_members': ['eth0']})
        form = self._form(cp_net_config=cfg)
        self.assertFalse(form.is_valid())

    def test_net_config_bond_requires_members(self):
        cfg = json.dumps({'enabled': True, 'type': 'bond', 'bond_name': 'bond0', 'bond_members': []})
        form = self._form(cp_net_config=cfg)
        self.assertFalse(form.is_valid())

    def test_net_config_invalid_prefix(self):
        cfg = json.dumps({'enabled': True, 'type': 'physical', 'interface': 'eth0', 'prefix': 99})
        form = self._form(cp_net_config=cfg)
        self.assertFalse(form.is_valid())

    def test_net_config_invalid_json(self):
        form = self._form(cp_net_config='{bad json')
        self.assertFalse(form.is_valid())


class NodeApplyConfigFormTest(TestCase):
    VALID_YAML = "version: v1alpha1\nmachine:\n  type: worker\n"

    def test_valid_form(self):
        form = NodeApplyConfigForm(data={'config_content': self.VALID_YAML, 'insecure': True})
        self.assertTrue(form.is_valid(), form.errors)

    def test_invalid_yaml_rejected(self):
        form = NodeApplyConfigForm(data={'config_content': '{{broken', 'insecure': False})
        self.assertFalse(form.is_valid())
        self.assertIn('config_content', form.errors)

    def test_empty_content_rejected(self):
        form = NodeApplyConfigForm(data={'config_content': '', 'insecure': False})
        self.assertFalse(form.is_valid())

    def test_normalizes_crlf(self):
        crlf = self.VALID_YAML.replace('\n', '\r\n')
        form = NodeApplyConfigForm(data={'config_content': crlf, 'insecure': True})
        self.assertTrue(form.is_valid())
        self.assertNotIn('\r', form.cleaned_data['config_content'])


# ─── TalosctlRunner tests ─────────────────────────────────────────────────────

class TalosctlRunnerTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('u', password='p')
        self.cluster = make_cluster(self.user)

    def test_context_manager_creates_tmpfile_with_correct_perms(self):
        import os
        with TalosctlRunner(self.cluster) as runner:
            path = runner._tmpfile_path
            self.assertTrue(os.path.exists(path))
            self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)
        self.assertFalse(os.path.exists(path))

    def test_context_manager_normalizes_crlf_in_config(self):
        import os
        cluster = Cluster.objects.create(
            name='crlf-cluster',
            endpoint='10.0.0.1',
            talosconfig_content=FAKE_TALOSCONFIG.replace('\n', '\r\n'),
            created_by=self.user,
        )
        with TalosctlRunner(cluster) as runner:
            with open(runner._tmpfile_path) as f:
                content = f.read()
        self.assertNotIn('\r', content)

    @patch('subprocess.run')
    def test_run_success(self, mock_run):
        mock_run.return_value = MagicMock(stdout='output', stderr='', returncode=0)
        with TalosctlRunner(self.cluster) as runner:
            result = runner.run(['version'])
        self.assertTrue(result['success'])
        self.assertEqual(result['stdout'], 'output')

    @patch('subprocess.run')
    def test_run_uses_list_command_not_string(self, mock_run):
        mock_run.return_value = MagicMock(stdout='', stderr='', returncode=0)
        with TalosctlRunner(self.cluster) as runner:
            runner.run(['version'])
        cmd = mock_run.call_args[0][0]
        self.assertIsInstance(cmd, list)
        self.assertNotEqual(mock_run.call_args[1].get('shell'), True)

    @patch('subprocess.run')
    def test_run_failure(self, mock_run):
        mock_run.return_value = MagicMock(stdout='', stderr='error msg', returncode=1)
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
    def test_run_json_success(self, mock_run):
        mock_run.return_value = MagicMock(
            stdout='{"key": "val"}', stderr='', returncode=0
        )
        with TalosctlRunner(self.cluster) as runner:
            result = runner.run_json(['get', 'members'])
        self.assertEqual(result, {'key': 'val'})

    @patch('subprocess.run')
    def test_run_json_returns_none_on_failure(self, mock_run):
        mock_run.return_value = MagicMock(stdout='', stderr='error', returncode=1)
        with TalosctlRunner(self.cluster) as runner:
            result = runner.run_json(['get', 'members'])
        self.assertIsNone(result)

    @patch('subprocess.run')
    def test_run_json_returns_none_on_invalid_json(self, mock_run):
        mock_run.return_value = MagicMock(stdout='not-json', stderr='', returncode=0)
        with TalosctlRunner(self.cluster) as runner:
            result = runner.run_json(['get', 'members'])
        self.assertIsNone(result)

    def test_apply_machineconfig_invalid_mode(self):
        with TalosctlRunner(self.cluster) as runner:
            result = runner.apply_machineconfig('10.0.0.1', 'yaml: content', mode='invalid')
        self.assertFalse(result['success'])
        self.assertIn('Invalid mode', result['stderr'])

    @patch('subprocess.run')
    def test_apply_machineconfig_valid_modes(self, mock_run):
        mock_run.return_value = MagicMock(stdout='ok', stderr='', returncode=0)
        for mode in ('auto', 'interactive', 'reboot', 'no-reboot', 'staged'):
            with TalosctlRunner(self.cluster) as runner:
                result = runner.apply_machineconfig('10.0.0.1', 'version: v1alpha1', mode=mode)
            self.assertTrue(result['success'], f"Mode {mode!r} should succeed")

    @patch('subprocess.run')
    def test_reboot_calls_run_with_reboot(self, mock_run):
        mock_run.return_value = MagicMock(stdout='', stderr='', returncode=0)
        with TalosctlRunner(self.cluster) as runner:
            result = runner.reboot('10.0.0.1')
        self.assertTrue(result['success'])
        args = mock_run.call_args[0][0]
        self.assertIn('reboot', args)

    @patch('subprocess.run')
    def test_shutdown_calls_run_with_shutdown(self, mock_run):
        mock_run.return_value = MagicMock(stdout='', stderr='', returncode=0)
        with TalosctlRunner(self.cluster) as runner:
            runner.shutdown('10.0.0.1')
        args = mock_run.call_args[0][0]
        self.assertIn('shutdown', args)

    @patch('subprocess.run')
    def test_reset_graceful_by_default(self, mock_run):
        mock_run.return_value = MagicMock(stdout='', stderr='', returncode=0)
        with TalosctlRunner(self.cluster) as runner:
            runner.reset('10.0.0.1')
        args = mock_run.call_args[0][0]
        self.assertIn('reset', args)
        self.assertIn('--graceful', args)

    @patch('subprocess.run')
    def test_restart_service(self, mock_run):
        mock_run.return_value = MagicMock(stdout='', stderr='', returncode=0)
        with TalosctlRunner(self.cluster) as runner:
            runner.restart_service('10.0.0.1', 'kubelet')
        args = mock_run.call_args[0][0]
        self.assertIn('kubelet', args)

    @patch('subprocess.run')
    def test_gen_config_success(self, mock_run):
        mock_run.return_value = MagicMock(stdout='', stderr='', returncode=0)
        runner = TalosctlRunner.__new__(TalosctlRunner)
        runner.cluster = None
        runner._tmpfile_path = None
        result = runner.gen_config('mycluster', 'https://10.0.0.1:6443', '/tmp/out')
        self.assertTrue(result['success'])
        args = mock_run.call_args[0][0]
        self.assertIn('gen', args)
        self.assertIn('config', args)

    @patch('subprocess.run')
    def test_gen_config_timeout(self, mock_run):
        import subprocess
        mock_run.side_effect = subprocess.TimeoutExpired(cmd='talosctl', timeout=30)
        runner = TalosctlRunner.__new__(TalosctlRunner)
        runner.cluster = None
        runner._tmpfile_path = None
        result = runner.gen_config('c', 'https://10.0.0.1:6443', '/tmp/out')
        self.assertFalse(result['success'])
        self.assertIn('timed out', result['stderr'])

    @patch('subprocess.run')
    def test_gen_config_not_found(self, mock_run):
        mock_run.side_effect = FileNotFoundError()
        runner = TalosctlRunner.__new__(TalosctlRunner)
        runner.cluster = None
        runner._tmpfile_path = None
        result = runner.gen_config('c', 'https://10.0.0.1:6443', '/tmp/out')
        self.assertFalse(result['success'])
        self.assertIn('talosctl not found', result['stderr'])

    @patch('subprocess.run')
    def test_bootstrap_success(self, mock_run):
        mock_run.return_value = MagicMock(stdout='', stderr='', returncode=0)
        with TalosctlRunner(self.cluster) as runner:
            result = runner.bootstrap('10.0.0.1')
        self.assertTrue(result['success'])
        args = mock_run.call_args[0][0]
        self.assertIn('bootstrap', args)

    @patch('subprocess.run')
    def test_bootstrap_timeout(self, mock_run):
        import subprocess
        mock_run.side_effect = subprocess.TimeoutExpired(cmd='talosctl', timeout=120)
        with TalosctlRunner(self.cluster) as runner:
            result = runner.bootstrap('10.0.0.1')
        self.assertFalse(result['success'])
        self.assertIn('timed out', result['stderr'])

    @patch('subprocess.run')
    def test_get_members_jsonl_format(self, mock_run):
        member_obj = {
            'spec': {
                'address': '192.168.1.10/32',
                'hostname': 'cp-1',
                'machineType': 'controlplane',
                'talosVersion': 'v1.7.0',
                'kubeletVersion': 'v1.30.0',
            }
        }
        mock_run.return_value = MagicMock(
            stdout=json.dumps(member_obj) + '\n',
            stderr='',
            returncode=0,
        )
        with TalosctlRunner(self.cluster) as runner:
            members, err = runner.get_members()
        self.assertIsNone(err)
        self.assertEqual(len(members), 1)
        self.assertEqual(members[0]['ip'], '192.168.1.10')
        self.assertEqual(members[0]['role'], 'controlplane')

    @patch('subprocess.run')
    def test_get_members_v1_11_addresses_list(self, mock_run):
        member_obj = {
            'spec': {
                'addresses': ['10.0.0.5/24'],
                'hostname': 'worker-1',
                'machineType': 'worker',
                'operatingSystem': 'Talos (v1.11.0)',
            }
        }
        mock_run.return_value = MagicMock(
            stdout=json.dumps(member_obj) + '\n',
            stderr='',
            returncode=0,
        )
        with TalosctlRunner(self.cluster) as runner:
            members, err = runner.get_members()
        self.assertIsNone(err)
        self.assertEqual(members[0]['ip'], '10.0.0.5')
        self.assertEqual(members[0]['role'], 'worker')
        self.assertEqual(members[0]['talos_version'], 'v1.11.0')

    @patch('subprocess.run')
    def test_get_members_error(self, mock_run):
        mock_run.return_value = MagicMock(stdout='', stderr='connection refused', returncode=1)
        with TalosctlRunner(self.cluster) as runner:
            members, err = runner.get_members()
        self.assertEqual(members, [])
        self.assertIn('connection refused', err)

    @patch('subprocess.run')
    def test_get_k8s_version_parses_image_tag(self, mock_run):
        obj = {'spec': {'image': 'ghcr.io/siderolabs/kubelet:v1.30.2'}}
        mock_run.return_value = MagicMock(
            stdout=json.dumps(obj), stderr='', returncode=0
        )
        with TalosctlRunner(self.cluster) as runner:
            ver = runner.get_k8s_version()
        self.assertEqual(ver, 'v1.30.2')

    @patch('subprocess.run')
    def test_get_k8s_version_returns_empty_on_failure(self, mock_run):
        mock_run.return_value = MagicMock(stdout='', stderr='err', returncode=1)
        with TalosctlRunner(self.cluster) as runner:
            ver = runner.get_k8s_version()
        self.assertEqual(ver, '')

    @patch('subprocess.run')
    def test_get_machineconfig_extracts_spec_string(self, mock_run):
        import yaml
        doc = {'spec': 'machine:\n  type: controlplane\n'}
        mock_run.return_value = MagicMock(
            stdout=yaml.dump(doc), stderr='', returncode=0
        )
        with TalosctlRunner(self.cluster) as runner:
            result = runner.get_machineconfig('10.0.0.1')
        self.assertTrue(result['success'])
        self.assertIn('machine', result['stdout'])

    @patch('subprocess.run')
    def test_patch_machineconfig_writes_temp_file(self, mock_run):
        mock_run.return_value = MagicMock(stdout='', stderr='', returncode=0)
        patch_content = '[{"op": "add", "path": "/foo", "value": "bar"}]'
        with TalosctlRunner(self.cluster) as runner:
            result = runner.patch_machineconfig('10.0.0.1', patch_content)
        self.assertTrue(result['success'])
        args = mock_run.call_args[0][0]
        self.assertIn('patch', args)
        self.assertIn('machineconfig', args)

    def test_run_stream_yields_lines(self):
        lines_output = b'line1\nline2\nline3\n'

        class FakeProc:
            stdout = lines_output.decode().splitlines(keepends=True)
            returncode = 0

            def __enter__(self): return self
            def __exit__(self, *a): pass
            def wait(self): pass

        with patch('subprocess.Popen', return_value=FakeProc()):
            with TalosctlRunner(self.cluster) as runner:
                lines = list(runner.run_stream(['logs', 'kubelet']))
        self.assertEqual(lines, ['line1', 'line2', 'line3'])

    def test_run_stream_handles_not_found(self):
        with patch('subprocess.Popen', side_effect=FileNotFoundError()):
            with TalosctlRunner(self.cluster) as runner:
                lines = list(runner.run_stream(['logs', 'kubelet']))
        self.assertTrue(any('talosctl not found' in l for l in lines))


# ─── View tests ───────────────────────────────────────────────────────────────

@override_settings(CHANNEL_LAYERS={'default': {'BACKEND': 'channels.layers.InMemoryChannelLayer'}})
class ClusterViewTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.admin = make_admin('admin_v')
        self.operator = make_operator('operator_v')
        self.viewer = make_viewer('viewer_v')
        self.cluster = make_cluster(self.admin)
        self.node = make_node(self.cluster)

    # ── Auth / access ──────────────────────────────────────────────────────────

    def test_cluster_list_requires_login(self):
        response = self.client.get(reverse('clusters:list'))
        self.assertEqual(response.status_code, 302)
        self.assertIn('/accounts/login/', response['Location'])

    def test_cluster_list_authenticated(self):
        self.client.login(username='admin_v', password='pass')
        response = self.client.get(reverse('clusters:list'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.cluster.name)

    def test_cluster_add_get_admin(self):
        self.client.login(username='admin_v', password='pass')
        response = self.client.get(reverse('clusters:add'))
        self.assertEqual(response.status_code, 200)

    def test_cluster_add_viewer_redirected(self):
        self.client.login(username='viewer_v', password='pass')
        response = self.client.post(reverse('clusters:add'), {
            'name': 'hack', 'endpoint': '1.2.3.4',
            'talosconfig_content': FAKE_TALOSCONFIG,
        })
        self.assertIn(response.status_code, [302, 403])

    def test_cluster_detail_authenticated(self):
        self.client.login(username='admin_v', password='pass')
        response = self.client.get(reverse('clusters:detail', args=[self.cluster.pk]))
        self.assertEqual(response.status_code, 200)

    def test_cluster_detail_404_unknown(self):
        self.client.login(username='admin_v', password='pass')
        response = self.client.get(reverse('clusters:detail', args=[9999]))
        self.assertEqual(response.status_code, 404)

    # ── CRUD ──────────────────────────────────────────────────────────────────

    def test_cluster_add_post_admin_creates_cluster(self):
        self.client.login(username='admin_v', password='pass')
        response = self.client.post(reverse('clusters:add'), {
            'name': 'new-cluster',
            'endpoint': '10.0.0.1',
            'talosconfig_content': FAKE_TALOSCONFIG,
        }, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(Cluster.objects.filter(name='new-cluster').exists())

    def test_cluster_edit_get(self):
        self.client.login(username='admin_v', password='pass')
        response = self.client.get(reverse('clusters:edit', args=[self.cluster.pk]))
        self.assertEqual(response.status_code, 200)

    def test_cluster_edit_post_updates_name(self):
        self.client.login(username='admin_v', password='pass')
        response = self.client.post(reverse('clusters:edit', args=[self.cluster.pk]), {
            'name': 'renamed-cluster',
            'endpoint': '192.168.1.10',
            'talosconfig_content': FAKE_TALOSCONFIG,
        }, follow=True)
        self.assertEqual(response.status_code, 200)
        self.cluster.refresh_from_db()
        self.assertEqual(self.cluster.name, 'renamed-cluster')

    def test_cluster_edit_viewer_forbidden(self):
        self.client.login(username='viewer_v', password='pass')
        response = self.client.post(reverse('clusters:edit', args=[self.cluster.pk]), {
            'name': 'hacked', 'endpoint': '1.2.3.4',
            'talosconfig_content': FAKE_TALOSCONFIG,
        })
        self.assertIn(response.status_code, [302, 403])

    def test_cluster_delete_get_confirm_page(self):
        self.client.login(username='admin_v', password='pass')
        response = self.client.get(reverse('clusters:delete', args=[self.cluster.pk]))
        self.assertEqual(response.status_code, 200)

    def test_cluster_delete_post_removes_cluster(self):
        self.client.login(username='admin_v', password='pass')
        pk = self.cluster.pk
        response = self.client.post(reverse('clusters:delete', args=[pk]), follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Cluster.objects.filter(pk=pk).exists())

    def test_cluster_delete_viewer_forbidden(self):
        self.client.login(username='viewer_v', password='pass')
        response = self.client.post(reverse('clusters:delete', args=[self.cluster.pk]))
        self.assertEqual(response.status_code, 403)

    # ── Talosconfig / kubeconfig download ──────────────────────────────────────

    def test_download_talosconfig(self):
        self.client.login(username='admin_v', password='pass')
        response = self.client.get(reverse('clusters:download_talosconfig', args=[self.cluster.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertIn('yaml', response['Content-Type'])
        self.assertIn(b'context', response.content)

    @patch('apps.clusters.views.TalosctlRunner')
    def test_download_kubeconfig_success(self, mock_cls):
        mock_runner = MagicMock()
        mock_runner.get_kubeconfig.return_value = {
            'success': True, 'stdout': 'apiVersion: v1\n', 'stderr': ''
        }
        mock_cls.return_value.__enter__ = MagicMock(return_value=mock_runner)
        mock_cls.return_value.__exit__ = MagicMock(return_value=False)

        self.client.login(username='admin_v', password='pass')
        response = self.client.get(reverse('clusters:download_kubeconfig', args=[self.cluster.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'apiVersion', response.content)

    @patch('apps.clusters.views.TalosctlRunner')
    def test_download_kubeconfig_failure_redirects(self, mock_cls):
        mock_runner = MagicMock()
        mock_runner.get_kubeconfig.return_value = {
            'success': False, 'stdout': '', 'stderr': 'timeout'
        }
        mock_cls.return_value.__enter__ = MagicMock(return_value=mock_runner)
        mock_cls.return_value.__exit__ = MagicMock(return_value=False)

        self.client.login(username='admin_v', password='pass')
        response = self.client.get(reverse('clusters:download_kubeconfig', args=[self.cluster.pk]))
        self.assertEqual(response.status_code, 302)

    # ── Cluster operations ─────────────────────────────────────────────────────

    @patch('apps.clusters.views.TalosctlRunner')
    def test_cluster_refresh_success(self, mock_cls):
        mock_runner = MagicMock()
        mock_runner.get_members.return_value = ([
            {'ip': '192.168.1.10', 'hostname': 'cp-1', 'role': 'controlplane',
             'talos_version': 'v1.7.0', 'k8s_version': 'v1.30.0'},
        ], None)
        mock_runner.get_k8s_version.return_value = 'v1.30.0'
        mock_cls.return_value.__enter__ = MagicMock(return_value=mock_runner)
        mock_cls.return_value.__exit__ = MagicMock(return_value=False)

        self.client.login(username='admin_v', password='pass')
        response = self.client.post(reverse('clusters:refresh', args=[self.cluster.pk]))
        self.assertEqual(response.status_code, 302)

    @patch('apps.clusters.views.TalosctlRunner')
    def test_cluster_refresh_error_shows_message(self, mock_cls):
        mock_runner = MagicMock()
        mock_runner.get_members.return_value = ([], 'connection refused')
        mock_cls.return_value.__enter__ = MagicMock(return_value=mock_runner)
        mock_cls.return_value.__exit__ = MagicMock(return_value=False)

        self.client.login(username='admin_v', password='pass')
        response = self.client.post(
            reverse('clusters:refresh', args=[self.cluster.pk]), follow=True
        )
        self.assertContains(response, 'connection refused')

    @patch('apps.clusters.views.TalosctlRunner')
    def test_cluster_test_connection(self, mock_cls):
        mock_runner = MagicMock()
        mock_runner.run.return_value = {'stdout': 'v1.7.0', 'stderr': '', 'returncode': 0}
        mock_cls.return_value.__enter__ = MagicMock(return_value=mock_runner)
        mock_cls.return_value.__exit__ = MagicMock(return_value=False)

        self.client.login(username='admin_v', password='pass')
        response = self.client.get(reverse('clusters:test', args=[self.cluster.pk]))
        self.assertEqual(response.status_code, 200)

    @patch('apps.clusters.views.TalosctlRunner')
    def test_cluster_bootstrap_etcd_admin_only(self, mock_cls):
        self.client.login(username='viewer_v', password='pass')
        response = self.client.post(reverse('clusters:bootstrap_etcd', args=[self.cluster.pk]))
        self.assertEqual(response.status_code, 403)

    @patch('apps.clusters.views.TalosctlRunner')
    def test_cluster_bootstrap_etcd_success(self, mock_cls):
        mock_runner = MagicMock()
        mock_runner.bootstrap.return_value = {'success': True, 'stdout': '', 'stderr': ''}
        mock_cls.return_value.__enter__ = MagicMock(return_value=mock_runner)
        mock_cls.return_value.__exit__ = MagicMock(return_value=False)

        self.client.login(username='admin_v', password='pass')
        response = self.client.post(
            reverse('clusters:bootstrap_etcd', args=[self.cluster.pk]), follow=True
        )
        self.assertContains(response, 'Bootstrap')


@override_settings(CHANNEL_LAYERS={'default': {'BACKEND': 'channels.layers.InMemoryChannelLayer'}})
class NodeViewTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.admin = make_admin('admin_nv')
        self.operator = make_operator('operator_nv')
        self.viewer = make_viewer('viewer_nv')
        self.cluster = make_cluster(self.admin)
        self.node = make_node(self.cluster, ip='192.168.1.10')

    def test_node_list_authenticated(self):
        self.client.login(username='admin_nv', password='pass')
        response = self.client.get(
            reverse('clusters:node_list', args=[self.cluster.pk])
        )
        self.assertEqual(response.status_code, 200)

    def test_node_detail_authenticated(self):
        self.client.login(username='admin_nv', password='pass')
        response = self.client.get(
            reverse('clusters:node_detail', args=[self.cluster.pk, '192.168.1.10'])
        )
        self.assertEqual(response.status_code, 200)

    def test_node_detail_404_unknown_ip(self):
        self.client.login(username='admin_nv', password='pass')
        response = self.client.get(
            reverse('clusters:node_detail', args=[self.cluster.pk, '1.2.3.4'])
        )
        self.assertEqual(response.status_code, 404)

    def test_node_add_get_operator(self):
        self.client.login(username='operator_nv', password='pass')
        response = self.client.get(
            reverse('clusters:node_add', args=[self.cluster.pk])
        )
        self.assertEqual(response.status_code, 200)

    def test_node_add_viewer_redirected(self):
        self.client.login(username='viewer_nv', password='pass')
        response = self.client.post(
            reverse('clusters:node_add', args=[self.cluster.pk]),
            {'ip_address': '10.0.0.5', 'role': 'worker', 'apply_config': '0'},
        )
        self.assertIn(response.status_code, [302, 403])

    def test_node_add_post_without_config(self):
        self.client.login(username='operator_nv', password='pass')
        response = self.client.post(
            reverse('clusters:node_add', args=[self.cluster.pk]),
            {'ip_address': '10.0.0.99', 'role': 'worker', 'hostname': '', 'apply_config': '0'},
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(Node.objects.filter(ip_address='10.0.0.99').exists())

    def test_node_dashboard_get(self):
        self.client.login(username='admin_nv', password='pass')
        response = self.client.get(
            reverse('clusters:node_dashboard', args=[self.cluster.pk, '192.168.1.10'])
        )
        self.assertEqual(response.status_code, 200)

    @patch('apps.clusters.views.TalosctlRunner')
    def test_node_dashboard_data_htmx(self, mock_cls):
        mock_runner = MagicMock()
        mock_runner.run.return_value = {'success': False, 'stdout': '', 'stderr': ''}
        mock_cls.return_value.__enter__ = MagicMock(return_value=mock_runner)
        mock_cls.return_value.__exit__ = MagicMock(return_value=False)

        self.client.login(username='admin_nv', password='pass')
        response = self.client.get(
            reverse('clusters:node_dashboard_data', args=[self.cluster.pk, '192.168.1.10'])
        )
        self.assertEqual(response.status_code, 200)

    @patch('apps.clusters.views.TalosctlRunner')
    def test_node_reboot_operator(self, mock_cls):
        mock_runner = MagicMock()
        mock_runner.reboot.return_value = {'success': True, 'stdout': '', 'stderr': ''}
        mock_cls.return_value.__enter__ = MagicMock(return_value=mock_runner)
        mock_cls.return_value.__exit__ = MagicMock(return_value=False)

        self.client.login(username='operator_nv', password='pass')
        response = self.client.post(
            reverse('clusters:node_reboot', args=[self.cluster.pk, '192.168.1.10']),
            follow=True,
        )
        self.assertEqual(response.status_code, 200)

    @patch('apps.clusters.views.TalosctlRunner')
    def test_node_reboot_viewer_forbidden(self, mock_cls):
        self.client.login(username='viewer_nv', password='pass')
        response = self.client.post(
            reverse('clusters:node_reboot', args=[self.cluster.pk, '192.168.1.10'])
        )
        self.assertEqual(response.status_code, 403)

    @patch('apps.clusters.views.TalosctlRunner')
    def test_node_shutdown(self, mock_cls):
        mock_runner = MagicMock()
        mock_runner.shutdown.return_value = {'success': True, 'stdout': '', 'stderr': ''}
        mock_cls.return_value.__enter__ = MagicMock(return_value=mock_runner)
        mock_cls.return_value.__exit__ = MagicMock(return_value=False)

        self.client.login(username='operator_nv', password='pass')
        response = self.client.post(
            reverse('clusters:node_shutdown', args=[self.cluster.pk, '192.168.1.10']),
            follow=True,
        )
        self.assertEqual(response.status_code, 200)

    @patch('apps.clusters.views.TalosctlRunner')
    def test_node_reset(self, mock_cls):
        mock_runner = MagicMock()
        mock_runner.reset.return_value = {'success': True, 'stdout': '', 'stderr': ''}
        mock_cls.return_value.__enter__ = MagicMock(return_value=mock_runner)
        mock_cls.return_value.__exit__ = MagicMock(return_value=False)

        self.client.login(username='operator_nv', password='pass')
        response = self.client.post(
            reverse('clusters:node_reset', args=[self.cluster.pk, '192.168.1.10']),
            follow=True,
        )
        self.assertEqual(response.status_code, 200)

    @patch('apps.clusters.views.TalosctlRunner')
    def test_node_restart_service_valid(self, mock_cls):
        mock_runner = MagicMock()
        mock_runner.restart_service.return_value = {'success': True, 'stdout': '', 'stderr': ''}
        mock_cls.return_value.__enter__ = MagicMock(return_value=mock_runner)
        mock_cls.return_value.__exit__ = MagicMock(return_value=False)

        self.client.login(username='operator_nv', password='pass')
        response = self.client.post(
            reverse('clusters:node_restart_service', args=[self.cluster.pk, '192.168.1.10']),
            {'service_name': 'kubelet'},
            follow=True,
        )
        self.assertEqual(response.status_code, 200)

    def test_node_restart_service_invalid_name(self):
        self.client.login(username='operator_nv', password='pass')
        response = self.client.post(
            reverse('clusters:node_restart_service', args=[self.cluster.pk, '192.168.1.10']),
            {'service_name': 'kube; rm -rf /'},
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        # Operation should NOT have been recorded on the node
        self.assertEqual(
            NodeOperation.objects.filter(operation=NodeOperation.OP_RESTART_SERVICE).count(), 0
        )

    def test_node_rows_partial(self):
        self.client.login(username='admin_nv', password='pass')
        response = self.client.get(reverse('clusters:node_list', args=[self.cluster.pk]))
        self.assertEqual(response.status_code, 200)


@override_settings(CHANNEL_LAYERS={'default': {'BACKEND': 'channels.layers.InMemoryChannelLayer'}})
class MachineConfigViewTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.operator = make_operator('op_mc')
        self.viewer = make_viewer('vi_mc')
        self.cluster = make_cluster(self.operator)
        self.node = make_node(self.cluster, ip='10.0.0.1')

    def _url(self, name):
        return reverse(f'clusters:{name}', args=[self.cluster.pk, '10.0.0.1'])

    @patch('apps.clusters.views.TalosctlRunner')
    def test_machineconfig_get_fetches_config(self, mock_cls):
        mock_runner = MagicMock()
        mock_runner.get_machineconfig.return_value = {
            'success': True, 'stdout': 'version: v1alpha1\n', 'stderr': ''
        }
        mock_cls.return_value.__enter__ = MagicMock(return_value=mock_runner)
        mock_cls.return_value.__exit__ = MagicMock(return_value=False)

        self.client.login(username='op_mc', password='pass')
        response = self.client.get(self._url('machineconfig_edit'))
        self.assertEqual(response.status_code, 200)

    def test_machineconfig_get_viewer_forbidden(self):
        self.client.login(username='vi_mc', password='pass')
        response = self.client.get(self._url('machineconfig_edit'))
        self.assertEqual(response.status_code, 403)

    @patch('apps.clusters.views.TalosctlRunner')
    def test_machineconfig_post_success_redirects(self, mock_cls):
        mock_runner = MagicMock()
        mock_runner.apply_machineconfig.return_value = {
            'success': True, 'stdout': '', 'stderr': ''
        }
        mock_cls.return_value.__enter__ = MagicMock(return_value=mock_runner)
        mock_cls.return_value.__exit__ = MagicMock(return_value=False)

        self.client.login(username='op_mc', password='pass')
        response = self.client.post(self._url('machineconfig_edit'), {
            'yaml_content': 'version: v1alpha1\nmachine:\n  type: controlplane\n',
            'mode': 'auto',
        }, follow=True)
        self.assertEqual(response.status_code, 200)

    @patch('apps.clusters.views.TalosctlRunner')
    def test_machineconfig_patch_valid_json(self, mock_cls):
        mock_runner = MagicMock()
        mock_runner.patch_machineconfig.return_value = {
            'success': True, 'stdout': '', 'stderr': ''
        }
        mock_cls.return_value.__enter__ = MagicMock(return_value=mock_runner)
        mock_cls.return_value.__exit__ = MagicMock(return_value=False)

        self.client.login(username='op_mc', password='pass')
        patch_data = '[{"op": "add", "path": "/foo", "value": "bar"}]'
        response = self.client.post(
            self._url('machineconfig_patch'),
            data=patch_data,
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])

    def test_machineconfig_patch_invalid_json_returns_400(self):
        self.client.login(username='op_mc', password='pass')
        response = self.client.post(
            self._url('machineconfig_patch'),
            data='not-json!',
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 400)

    def test_machineconfig_patch_empty_body_returns_400(self):
        self.client.login(username='op_mc', password='pass')
        response = self.client.post(
            self._url('machineconfig_patch'),
            data='',
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 400)

    @patch('apps.clusters.views.TalosctlRunner')
    def test_node_apply_config_get(self, mock_cls):
        self.client.login(username='op_mc', password='pass')
        response = self.client.get(
            reverse('clusters:node_apply_config', args=[self.cluster.pk, '10.0.0.1'])
        )
        self.assertEqual(response.status_code, 200)

    @patch('apps.clusters.views.TalosctlRunner')
    def test_node_apply_config_post_success(self, mock_cls):
        mock_runner = MagicMock()
        mock_runner.apply_config.return_value = {'success': True, 'stdout': '', 'stderr': ''}
        mock_cls.return_value.__enter__ = MagicMock(return_value=mock_runner)
        mock_cls.return_value.__exit__ = MagicMock(return_value=False)

        self.client.login(username='op_mc', password='pass')
        response = self.client.post(
            reverse('clusters:node_apply_config', args=[self.cluster.pk, '10.0.0.1']),
            {
                'config_content': 'version: v1alpha1\nmachine:\n  type: worker\n',
                'insecure': True,
            },
            follow=True,
        )
        self.assertEqual(response.status_code, 200)


# ─── Mixins tests ─────────────────────────────────────────────────────────────

class MixinsTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.viewer = make_viewer('vi_mx')
        self.operator = make_operator('op_mx')
        self.admin = make_admin('ad_mx')
        user = self.admin
        self.cluster = make_cluster(user)
        self.node = make_node(self.cluster, ip='10.5.0.1')

    def test_operator_required_blocks_viewer(self):
        self.client.login(username='vi_mx', password='pass')
        response = self.client.get(
            reverse('clusters:machineconfig_edit', args=[self.cluster.pk, '10.5.0.1'])
        )
        self.assertEqual(response.status_code, 403)

    def test_operator_required_allows_operator(self):
        # Just verify the view is reachable for an operator (even if talosctl fails)
        with patch('apps.clusters.views.TalosctlRunner') as mock_cls:
            mock_runner = MagicMock()
            mock_runner.get_machineconfig.return_value = {
                'success': False, 'stdout': '', 'stderr': 'err'
            }
            mock_cls.return_value.__enter__ = MagicMock(return_value=mock_runner)
            mock_cls.return_value.__exit__ = MagicMock(return_value=False)

            self.client.login(username='op_mx', password='pass')
            response = self.client.get(
                reverse('clusters:machineconfig_edit', args=[self.cluster.pk, '10.5.0.1'])
            )
        self.assertEqual(response.status_code, 200)

    def test_admin_required_blocks_operator(self):
        self.client.login(username='op_mx', password='pass')
        response = self.client.post(
            reverse('clusters:delete', args=[self.cluster.pk])
        )
        self.assertEqual(response.status_code, 403)

    def test_admin_required_allows_admin(self):
        self.client.login(username='ad_mx', password='pass')
        response = self.client.get(
            reverse('clusters:delete', args=[self.cluster.pk])
        )
        self.assertEqual(response.status_code, 200)

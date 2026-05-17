from unittest.mock import patch, MagicMock, call

from django.test import TestCase, Client, override_settings
from django.contrib.auth.models import User
from django.urls import reverse

from apps.accounts.models import UserProfile
from apps.clusters.models import Cluster, Node
from apps.patches.models import PatchTemplate, PatchJob
from apps.patches.forms import PatchTemplateForm
from apps.patches.tasks import _deep_merge, _apply_patch_via_fetch


FAKE_TALOSCONFIG = "context: test\ncontexts:\n  test:\n    endpoints: []\n"
VALID_JSON_PATCH = '[{"op": "add", "path": "/machine/network/hostname", "value": "node1"}]'
VALID_YAML_PATCH = "machine:\n  features:\n    hostDNS:\n      enabled: true\n"


def make_cluster(user):
    return Cluster.objects.create(
        name='patch-cluster',
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


def make_patch_template(user, name='test-patch', content=None, role=PatchTemplate.ROLE_ALL):
    return PatchTemplate.objects.create(
        name=name,
        patch_content=content or VALID_JSON_PATCH,
        target_role=role,
        created_by=user,
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

class PatchTemplateModelTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('u', password='p')

    def test_str(self):
        pt = make_patch_template(self.user, name='my-patch')
        self.assertEqual(str(pt), 'my-patch')

    def test_name_unique(self):
        make_patch_template(self.user, name='unique-patch')
        with self.assertRaises(Exception):
            PatchTemplate.objects.create(
                name='unique-patch',
                patch_content=VALID_JSON_PATCH,
                created_by=self.user,
            )

    def test_default_role_is_all(self):
        pt = PatchTemplate.objects.create(
            name='def-role', patch_content=VALID_JSON_PATCH, created_by=self.user
        )
        self.assertEqual(pt.target_role, PatchTemplate.ROLE_ALL)

    def test_ordering_by_name(self):
        make_patch_template(self.user, name='z-patch')
        make_patch_template(self.user, name='a-patch')
        first = PatchTemplate.objects.first()
        self.assertEqual(first.name, 'a-patch')

    def test_role_choices_include_all_controlplane_worker(self):
        roles = dict(PatchTemplate.ROLE_CHOICES)
        self.assertIn(PatchTemplate.ROLE_ALL, roles)
        self.assertIn(PatchTemplate.ROLE_CONTROLPLANE, roles)
        self.assertIn(PatchTemplate.ROLE_WORKER, roles)


class PatchJobModelTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('u', password='p')
        self.cluster = make_cluster(self.user)
        self.template = make_patch_template(self.user)

    def test_str_with_template(self):
        job = PatchJob.objects.create(
            patch_template=self.template,
            cluster=self.cluster,
            patch_content=VALID_JSON_PATCH,
            target_role=PatchTemplate.ROLE_ALL,
            initiated_by=self.user,
        )
        self.assertIn('test-patch', str(job))
        self.assertIn('patch-cluster', str(job))

    def test_str_adhoc(self):
        job = PatchJob.objects.create(
            cluster=self.cluster,
            patch_content=VALID_JSON_PATCH,
            target_role=PatchTemplate.ROLE_ALL,
            initiated_by=self.user,
        )
        self.assertIn('Ad-hoc', str(job))

    def test_default_status_pending(self):
        job = PatchJob.objects.create(
            cluster=self.cluster,
            patch_content=VALID_JSON_PATCH,
            target_role='all',
            initiated_by=self.user,
        )
        self.assertEqual(job.status, PatchJob.STATUS_PENDING)

    def test_append_log(self):
        job = PatchJob.objects.create(
            cluster=self.cluster,
            patch_content=VALID_JSON_PATCH,
            target_role='all',
            initiated_by=self.user,
        )
        job.append_log('applying patch')
        job.append_log('second line')
        job.refresh_from_db()
        self.assertIn('applying patch', job.logs)
        self.assertIn('second line', job.logs)

    def test_append_log_accumulates(self):
        job = PatchJob.objects.create(
            cluster=self.cluster,
            patch_content=VALID_JSON_PATCH,
            target_role='all',
            initiated_by=self.user,
        )
        for i in range(5):
            job.append_log(f'line {i}')
        job.refresh_from_db()
        for i in range(5):
            self.assertIn(f'line {i}', job.logs)

    def test_target_nodes_many_to_many(self):
        node = make_node(self.cluster)
        job = PatchJob.objects.create(
            cluster=self.cluster,
            patch_content=VALID_JSON_PATCH,
            target_role='all',
            initiated_by=self.user,
        )
        job.target_nodes.set([node])
        self.assertEqual(job.target_nodes.count(), 1)

    def test_status_choices_include_partial(self):
        choices = dict(PatchJob.STATUS_CHOICES)
        self.assertIn(PatchJob.STATUS_PARTIAL, choices)


# ─── Form tests ───────────────────────────────────────────────────────────────

class PatchTemplateFormTest(TestCase):
    def test_valid_json_patch(self):
        form = PatchTemplateForm(data={
            'name': 'json-patch',
            'patch_content': VALID_JSON_PATCH,
            'target_role': 'all',
        })
        self.assertTrue(form.is_valid(), form.errors)

    def test_valid_yaml_patch(self):
        form = PatchTemplateForm(data={
            'name': 'yaml-patch',
            'patch_content': VALID_YAML_PATCH,
            'target_role': 'controlplane',
        })
        self.assertTrue(form.is_valid(), form.errors)

    def test_invalid_patch_content(self):
        form = PatchTemplateForm(data={
            'name': 'bad-patch',
            'patch_content': '{invalid json: [unclosed',
            'target_role': 'all',
        })
        self.assertFalse(form.is_valid())
        self.assertIn('patch_content', form.errors)

    def test_missing_required_fields(self):
        form = PatchTemplateForm(data={})
        self.assertFalse(form.is_valid())
        self.assertIn('name', form.errors)
        self.assertIn('patch_content', form.errors)

    def test_target_role_controlplane_valid(self):
        form = PatchTemplateForm(data={
            'name': 'cp-patch',
            'patch_content': VALID_JSON_PATCH,
            'target_role': 'controlplane',
        })
        self.assertTrue(form.is_valid())

    def test_target_role_worker_valid(self):
        form = PatchTemplateForm(data={
            'name': 'w-patch',
            'patch_content': VALID_JSON_PATCH,
            'target_role': 'worker',
        })
        self.assertTrue(form.is_valid())


# ─── Task helper function tests ───────────────────────────────────────────────

class DeepMergeTest(TestCase):
    def test_simple_merge(self):
        result = _deep_merge({'a': 1, 'b': 2}, {'b': 99, 'c': 3})
        self.assertEqual(result, {'a': 1, 'b': 99, 'c': 3})

    def test_recursive_merge(self):
        base = {'machine': {'network': {'hostname': 'old'}}}
        override = {'machine': {'network': {'nameservers': ['8.8.8.8']}}}
        result = _deep_merge(base, override)
        self.assertEqual(result['machine']['network']['hostname'], 'old')
        self.assertEqual(result['machine']['network']['nameservers'], ['8.8.8.8'])

    def test_list_replaced_not_merged(self):
        base = {'items': [1, 2, 3]}
        override = {'items': [4, 5]}
        result = _deep_merge(base, override)
        self.assertEqual(result['items'], [4, 5])

    def test_override_wins_on_scalar(self):
        result = _deep_merge({'key': 'old'}, {'key': 'new'})
        self.assertEqual(result['key'], 'new')

    def test_does_not_mutate_base(self):
        base = {'a': {'b': 1}}
        override = {'a': {'c': 2}}
        _deep_merge(base, override)
        self.assertNotIn('c', base['a'])

    def test_empty_override(self):
        base = {'a': 1}
        result = _deep_merge(base, {})
        self.assertEqual(result, {'a': 1})

    def test_empty_base(self):
        result = _deep_merge({}, {'a': 1})
        self.assertEqual(result, {'a': 1})


class ApplyPatchViaFetchTest(TestCase):
    def _make_runner(self, fetch_result=None, apply_result=None):
        runner = MagicMock()
        runner.get_machineconfig.return_value = fetch_result or {
            'success': True,
            'stdout': 'version: v1alpha1\nmachine:\n  type: controlplane\n',
            'stderr': '',
        }
        runner.apply_machineconfig.return_value = apply_result or {
            'success': True, 'stdout': '', 'stderr': ''
        }
        return runner

    def test_success_merges_and_applies(self):
        runner = self._make_runner()
        result = _apply_patch_via_fetch(runner, '10.0.0.1', VALID_YAML_PATCH)
        self.assertTrue(result['success'])
        runner.apply_machineconfig.assert_called_once()

    def test_fetch_failure_returns_error(self):
        runner = self._make_runner(
            fetch_result={'success': False, 'stdout': '', 'stderr': 'conn refused'}
        )
        result = _apply_patch_via_fetch(runner, '10.0.0.1', VALID_YAML_PATCH)
        self.assertFalse(result['success'])
        runner.apply_machineconfig.assert_not_called()

    def test_invalid_yaml_patch_returns_error(self):
        runner = self._make_runner()
        result = _apply_patch_via_fetch(runner, '10.0.0.1', '{{invalid yaml::')
        self.assertFalse(result['success'])
        self.assertIn('Invalid patch YAML', result['stderr'])
        runner.apply_machineconfig.assert_not_called()

    def test_json_array_patch_rejected(self):
        runner = self._make_runner()
        result = _apply_patch_via_fetch(runner, '10.0.0.1', VALID_JSON_PATCH)
        self.assertFalse(result['success'])
        self.assertIn('YAML mapping', result['stderr'])

    def test_merges_into_v1alpha1_doc(self):
        current_config = (
            "version: v1alpha1\n"
            "machine:\n"
            "  type: controlplane\n"
            "  network:\n"
            "    hostname: old-name\n"
        )
        runner = self._make_runner(
            fetch_result={'success': True, 'stdout': current_config, 'stderr': ''}
        )
        patch_yaml = "machine:\n  network:\n    hostname: new-name\n"
        _apply_patch_via_fetch(runner, '10.0.0.1', patch_yaml)

        _, kwargs = runner.apply_machineconfig.call_args
        applied_yaml = runner.apply_machineconfig.call_args[0][1] if runner.apply_machineconfig.call_args[0] else kwargs.get('config_yaml', '')
        import yaml
        parsed = yaml.safe_load(applied_yaml)
        self.assertEqual(parsed['machine']['network']['hostname'], 'new-name')

    def test_empty_current_config_returns_error(self):
        runner = self._make_runner(
            fetch_result={'success': True, 'stdout': '', 'stderr': ''}
        )
        result = _apply_patch_via_fetch(runner, '10.0.0.1', VALID_YAML_PATCH)
        self.assertFalse(result['success'])


# ─── Celery task tests ────────────────────────────────────────────────────────

@override_settings(CHANNEL_LAYERS={'default': {'BACKEND': 'channels.layers.InMemoryChannelLayer'}})
class RunPatchJobTaskTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('u', password='p')
        self.cluster = make_cluster(self.user)
        self.node = make_node(self.cluster, ip='192.168.1.10')
        self.template = make_patch_template(self.user)

    def _make_job(self, role='all'):
        job = PatchJob.objects.create(
            patch_template=self.template,
            cluster=self.cluster,
            patch_content=VALID_YAML_PATCH,
            target_role=role,
            initiated_by=self.user,
        )
        job.target_nodes.set([self.node])
        return job

    def test_success_sets_status_success(self):
        mock_runner = MagicMock()
        mock_cls = MagicMock()
        mock_cls.return_value.__enter__ = MagicMock(return_value=mock_runner)
        mock_cls.return_value.__exit__ = MagicMock(return_value=False)

        from apps.patches.tasks import run_patch_job
        job = self._make_job()
        with patch('apps.clusters.talosctl.TalosctlRunner', mock_cls):
            with patch('apps.patches.tasks._apply_patch_via_fetch',
                       return_value={'success': True, 'stdout': 'ok', 'stderr': ''}):
                run_patch_job.apply(args=[job.pk])

        job.refresh_from_db()
        self.assertEqual(job.status, PatchJob.STATUS_SUCCESS)
        self.assertIsNotNone(job.completed_at)

    def test_failure_sets_status_failed(self):
        mock_runner = MagicMock()
        mock_cls = MagicMock()
        mock_cls.return_value.__enter__ = MagicMock(return_value=mock_runner)
        mock_cls.return_value.__exit__ = MagicMock(return_value=False)

        from apps.patches.tasks import run_patch_job
        job = self._make_job()
        with patch('apps.clusters.talosctl.TalosctlRunner', mock_cls):
            with patch('apps.patches.tasks._apply_patch_via_fetch',
                       return_value={'success': False, 'stdout': '', 'stderr': 'patch failed'}):
                run_patch_job.apply(args=[job.pk])

        job.refresh_from_db()
        self.assertEqual(job.status, PatchJob.STATUS_FAILED)

    def test_partial_success_with_multiple_nodes(self):
        node2 = Node.objects.create(
            cluster=self.cluster, ip_address='192.168.1.11', role=Node.ROLE_WORKER
        )
        job = PatchJob.objects.create(
            patch_template=self.template,
            cluster=self.cluster,
            patch_content=VALID_YAML_PATCH,
            target_role='all',
            initiated_by=self.user,
        )
        job.target_nodes.set([self.node, node2])

        mock_runner = MagicMock()
        mock_cls = MagicMock()
        mock_cls.return_value.__enter__ = MagicMock(return_value=mock_runner)
        mock_cls.return_value.__exit__ = MagicMock(return_value=False)

        from apps.patches.tasks import run_patch_job
        side_effects = [
            {'success': True, 'stdout': '', 'stderr': ''},
            {'success': False, 'stdout': '', 'stderr': 'err'},
        ]
        with patch('apps.clusters.talosctl.TalosctlRunner', mock_cls):
            with patch('apps.patches.tasks._apply_patch_via_fetch', side_effect=side_effects):
                run_patch_job.apply(args=[job.pk])

        job.refresh_from_db()
        self.assertEqual(job.status, PatchJob.STATUS_PARTIAL)

    def test_job_not_found_returns_not_found(self):
        from apps.patches.tasks import run_patch_job
        result = run_patch_job.apply(args=[99999])
        self.assertEqual(result.result['status'], 'not_found')

    def test_target_nodes_from_role_when_no_explicit_nodes(self):
        job = PatchJob.objects.create(
            patch_template=self.template,
            cluster=self.cluster,
            patch_content=VALID_YAML_PATCH,
            target_role='controlplane',
            initiated_by=self.user,
        )

        mock_runner = MagicMock()
        mock_cls = MagicMock()
        mock_cls.return_value.__enter__ = MagicMock(return_value=mock_runner)
        mock_cls.return_value.__exit__ = MagicMock(return_value=False)

        from apps.patches.tasks import run_patch_job
        with patch('apps.clusters.talosctl.TalosctlRunner', mock_cls):
            with patch('apps.patches.tasks._apply_patch_via_fetch',
                       return_value={'success': True, 'stdout': '', 'stderr': ''}) as mock_apply:
                run_patch_job.apply(args=[job.pk])

        self.assertEqual(mock_apply.call_count, 1)

    def test_exception_sets_failed_status(self):
        mock_cls = MagicMock()
        mock_cls.return_value.__enter__ = MagicMock(side_effect=RuntimeError('boom'))
        mock_cls.return_value.__exit__ = MagicMock(return_value=False)

        from apps.patches.tasks import run_patch_job
        job = self._make_job()
        with patch('apps.clusters.talosctl.TalosctlRunner', mock_cls):
            run_patch_job.apply(args=[job.pk])

        job.refresh_from_db()
        self.assertEqual(job.status, PatchJob.STATUS_FAILED)


# ─── View tests ───────────────────────────────────────────────────────────────

@override_settings(CHANNEL_LAYERS={'default': {'BACKEND': 'channels.layers.InMemoryChannelLayer'}})
class PatchViewTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.admin = make_admin('admin_p')
        self.operator = make_operator('operator_p')
        self.viewer = make_viewer('viewer_p')
        self.cluster = make_cluster(self.admin)
        self.template = make_patch_template(self.admin)

    def test_patch_list_requires_login(self):
        response = self.client.get(reverse('patches:list'))
        self.assertEqual(response.status_code, 302)

    def test_patch_list_authenticated(self):
        self.client.login(username='viewer_p', password='pass')
        response = self.client.get(reverse('patches:list'))
        self.assertEqual(response.status_code, 200)

    def test_patch_list_shows_template(self):
        self.client.login(username='viewer_p', password='pass')
        response = self.client.get(reverse('patches:list'))
        self.assertContains(response, self.template.name)

    def test_patch_create_requires_operator(self):
        self.client.login(username='viewer_p', password='pass')
        response = self.client.get(reverse('patches:create'))
        self.assertIn(response.status_code, [302, 403])

    def test_patch_create_get_operator(self):
        self.client.login(username='operator_p', password='pass')
        response = self.client.get(reverse('patches:create'))
        self.assertEqual(response.status_code, 200)

    def test_patch_create_post_creates_template(self):
        self.client.login(username='operator_p', password='pass')
        response = self.client.post(reverse('patches:create'), {
            'name': 'new-patch',
            'patch_content': VALID_JSON_PATCH,
            'target_role': 'all',
        }, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(PatchTemplate.objects.filter(name='new-patch').exists())

    def test_patch_edit_get_operator(self):
        self.client.login(username='operator_p', password='pass')
        response = self.client.get(reverse('patches:edit', args=[self.template.pk]))
        self.assertEqual(response.status_code, 200)

    def test_patch_edit_post_updates_content(self):
        self.client.login(username='operator_p', password='pass')
        new_content = VALID_YAML_PATCH
        response = self.client.post(reverse('patches:edit', args=[self.template.pk]), {
            'name': self.template.name,
            'patch_content': new_content,
            'target_role': 'all',
        }, follow=True)
        self.assertEqual(response.status_code, 200)
        self.template.refresh_from_db()
        self.assertEqual(self.template.patch_content.strip(), new_content.strip())

    def test_patch_delete_requires_admin(self):
        self.client.login(username='operator_p', password='pass')
        response = self.client.post(reverse('patches:delete', args=[self.template.pk]))
        self.assertIn(response.status_code, [302, 403])

    def test_patch_delete_admin(self):
        self.client.login(username='admin_p', password='pass')
        response = self.client.post(reverse('patches:delete', args=[self.template.pk]), follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(PatchTemplate.objects.filter(pk=self.template.pk).exists())

    def test_patch_apply_get(self):
        self.client.login(username='operator_p', password='pass')
        response = self.client.get(reverse('patches:apply', args=[self.template.pk]))
        self.assertEqual(response.status_code, 200)

    @patch('apps.patches.views.run_patch_job')
    def test_patch_apply_post_creates_job(self, mock_task):
        mock_task.delay.return_value = MagicMock(id='patch-task-id')
        self.client.login(username='operator_p', password='pass')
        response = self.client.post(reverse('patches:apply', args=[self.template.pk]), {
            'cluster': self.cluster.pk,
            'target_role': 'all',
        }, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(PatchJob.objects.filter(
            cluster=self.cluster, patch_template=self.template
        ).exists())

    def test_patch_apply_viewer_forbidden(self):
        self.client.login(username='viewer_p', password='pass')
        response = self.client.post(reverse('patches:apply', args=[self.template.pk]), {
            'cluster': self.cluster.pk,
            'target_role': 'all',
        })
        self.assertIn(response.status_code, [302, 403])

    def test_job_list_authenticated(self):
        self.client.login(username='viewer_p', password='pass')
        response = self.client.get(reverse('patches:job_list'))
        self.assertEqual(response.status_code, 200)

    def test_job_detail_404_unknown(self):
        self.client.login(username='viewer_p', password='pass')
        response = self.client.get(reverse('patches:job_detail', args=[9999]))
        self.assertEqual(response.status_code, 404)

    def test_job_status_api(self):
        job = PatchJob.objects.create(
            cluster=self.cluster,
            patch_content=VALID_JSON_PATCH,
            target_role='all',
            initiated_by=self.admin,
            status=PatchJob.STATUS_SUCCESS,
        )
        self.client.login(username='viewer_p', password='pass')
        response = self.client.get(reverse('patches:job_status_api', args=[job.pk]))
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn('status', data)
        self.assertEqual(data['status'], PatchJob.STATUS_SUCCESS)

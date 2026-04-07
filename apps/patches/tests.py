from unittest.mock import patch, MagicMock
from django.test import TestCase, Client, override_settings
from django.contrib.auth.models import User
from django.urls import reverse

from apps.accounts.models import UserProfile
from apps.clusters.models import Cluster, Node
from apps.patches.models import PatchTemplate, PatchJob
from apps.patches.forms import PatchTemplateForm


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


def make_patch_template(user, name='test-patch', content=None):
    return PatchTemplate.objects.create(
        name=name,
        patch_content=content or VALID_JSON_PATCH,
        target_role=PatchTemplate.ROLE_ALL,
        created_by=user,
    )


# ─── Model tests ─────────────────────────────────────────────────────────────

class PatchTemplateModelTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('u', password='p')

    def test_str(self):
        pt = make_patch_template(self.user, name='my-patch')
        self.assertEqual(str(pt), 'my-patch')

    def test_name_unique(self):
        make_patch_template(self.user, name='unique-patch')
        from django.db import IntegrityError
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
        job.refresh_from_db()
        self.assertIn('applying patch', job.logs)


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


# ─── View tests ───────────────────────────────────────────────────────────────

@override_settings(CHANNEL_LAYERS={'default': {'BACKEND': 'channels.layers.InMemoryChannelLayer'}})
class PatchViewTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.admin = User.objects.create_user('admin_p', password='pass')
        self.admin.profile.role = UserProfile.ROLE_ADMIN
        self.admin.profile.save()

        self.operator = User.objects.create_user('operator_p', password='pass')
        self.operator.profile.role = UserProfile.ROLE_OPERATOR
        self.operator.profile.save()

        self.viewer = User.objects.create_user('viewer_p', password='pass')

        self.cluster = make_cluster(self.admin)
        self.template = make_patch_template(self.admin)

    def test_patch_list_requires_login(self):
        response = self.client.get(reverse('patches:list'))
        self.assertEqual(response.status_code, 302)

    def test_patch_list_authenticated(self):
        self.client.login(username='viewer_p', password='pass')
        response = self.client.get(reverse('patches:list'))
        self.assertEqual(response.status_code, 200)

    def test_patch_create_requires_operator(self):
        self.client.login(username='viewer_p', password='pass')
        response = self.client.get(reverse('patches:create'))
        self.assertIn(response.status_code, [302, 403])

    def test_patch_create_get_operator(self):
        self.client.login(username='operator_p', password='pass')
        response = self.client.get(reverse('patches:create'))
        self.assertEqual(response.status_code, 200)

    def test_patch_create_post(self):
        self.client.login(username='operator_p', password='pass')
        response = self.client.post(reverse('patches:create'), {
            'name': 'new-patch',
            'patch_content': VALID_JSON_PATCH,
            'target_role': 'all',
        }, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(PatchTemplate.objects.filter(name='new-patch').exists())

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
    def test_patch_apply_post(self, mock_task):
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

    def test_job_list(self):
        self.client.login(username='viewer_p', password='pass')
        response = self.client.get(reverse('patches:job_list'))
        self.assertEqual(response.status_code, 200)

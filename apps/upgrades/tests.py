from unittest.mock import patch, MagicMock
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
        # v prefix stripped in clean
        self.assertEqual(form.cleaned_data['target_version'], '1.32.0')

    def test_invalid_version_format(self):
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


# ─── View tests ───────────────────────────────────────────────────────────────

@override_settings(CHANNEL_LAYERS={'default': {'BACKEND': 'channels.layers.InMemoryChannelLayer'}})
class UpgradeViewTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.operator = User.objects.create_user('operator_u', password='pass')
        self.operator.profile.role = UserProfile.ROLE_OPERATOR
        self.operator.profile.save()

        self.viewer = User.objects.create_user('viewer_u', password='pass')

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
    def test_image_upgrade_post_valid(self, mock_task):
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

    def test_k8s_upgrade_requires_login(self):
        response = self.client.get(reverse('upgrades:k8s'))
        self.assertEqual(response.status_code, 302)

    @patch('apps.upgrades.views.run_k8s_upgrade')
    def test_k8s_upgrade_post_valid(self, mock_task):
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

    def test_upgrade_job_list(self):
        self.client.login(username='operator_u', password='pass')
        response = self.client.get(reverse('upgrades:job_list'))
        self.assertEqual(response.status_code, 200)

from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.urls import reverse

from apps.accounts.models import UserProfile


class UserProfileModelTest(TestCase):
    def setUp(self):
        self.admin_user = User.objects.create_user('admin_u', password='pass')
        self.admin_user.profile.role = UserProfile.ROLE_ADMIN
        self.admin_user.profile.save()

        self.operator_user = User.objects.create_user('operator_u', password='pass')
        self.operator_user.profile.role = UserProfile.ROLE_OPERATOR
        self.operator_user.profile.save()

        self.viewer_user = User.objects.create_user('viewer_u', password='pass')
        # viewer is the default role

        self.superuser = User.objects.create_superuser('super_u', password='pass')

    def test_profile_auto_created_on_user_save(self):
        user = User.objects.create_user('newuser', password='pass')
        self.assertTrue(hasattr(user, 'profile'))
        self.assertIsInstance(user.profile, UserProfile)

    def test_default_role_is_viewer(self):
        user = User.objects.create_user('plain', password='pass')
        self.assertEqual(user.profile.role, UserProfile.ROLE_VIEWER)

    def test_str_representation(self):
        self.assertIn('admin_u', str(self.admin_user.profile))
        self.assertIn('Admin', str(self.admin_user.profile))

    def test_is_admin_property(self):
        self.assertTrue(self.admin_user.profile.is_admin)
        self.assertFalse(self.operator_user.profile.is_admin)
        self.assertFalse(self.viewer_user.profile.is_admin)

    def test_superuser_is_admin(self):
        self.assertTrue(self.superuser.profile.is_admin)

    def test_is_operator_includes_admin(self):
        self.assertTrue(self.admin_user.profile.is_operator)
        self.assertTrue(self.operator_user.profile.is_operator)
        self.assertFalse(self.viewer_user.profile.is_operator)

    def test_superuser_is_operator(self):
        self.assertTrue(self.superuser.profile.is_operator)

    def test_is_viewer_always_true(self):
        for user in [self.admin_user, self.operator_user, self.viewer_user]:
            self.assertTrue(user.profile.is_viewer)

    def test_role_choices(self):
        choices = dict(UserProfile.ROLE_CHOICES)
        self.assertIn(UserProfile.ROLE_ADMIN, choices)
        self.assertIn(UserProfile.ROLE_OPERATOR, choices)
        self.assertIn(UserProfile.ROLE_VIEWER, choices)


class LoginViewTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user('testuser', password='testpass')

    def test_login_page_get(self):
        response = self.client.get(reverse('accounts:login'))
        self.assertEqual(response.status_code, 200)

    def test_login_success_redirects(self):
        response = self.client.post(reverse('accounts:login'), {
            'username': 'testuser',
            'password': 'testpass',
        }, follow=True)
        self.assertEqual(response.status_code, 200)

    def test_login_failure_stays_on_page(self):
        response = self.client.post(reverse('accounts:login'), {
            'username': 'testuser',
            'password': 'wrongpass',
        })
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.wsgi_request.user.is_authenticated)

    def test_logout_redirects(self):
        self.client.login(username='testuser', password='testpass')
        response = self.client.post(reverse('accounts:logout'), follow=True)
        self.assertEqual(response.status_code, 200)


class ProfileViewTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user('profileuser', password='pass')

    def test_profile_view_requires_login(self):
        response = self.client.get(reverse('accounts:profile'))
        self.assertIn(response.status_code, [302, 403])

    def test_profile_view_authenticated(self):
        self.client.login(username='profileuser', password='pass')
        response = self.client.get(reverse('accounts:profile'))
        self.assertEqual(response.status_code, 200)

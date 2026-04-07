import logging

from django.conf import settings as django_settings
from django.contrib.auth import login, logout, authenticate
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect
from django.contrib import messages
from django.contrib.auth.models import User
from django.utils.http import url_has_allowed_host_and_scheme
from .models import UserProfile

logger = logging.getLogger(__name__)


def login_view(request):
    if request.user.is_authenticated:
        return redirect('dashboard:overview')

    if request.method == 'POST':
        username = request.POST.get('username', '').strip()
        password = request.POST.get('password', '')
        try:
            user = authenticate(request, username=username, password=password)
        except Exception as e:
            logger.exception('Authentication error for user %s', username)
            messages.error(request, f'Authentication service error: {e}')
            user = None

        if user:
            login(request, user)
            next_url = request.GET.get('next', '/')
            if not url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
                next_url = '/'
            return redirect(next_url)
        elif not messages.get_messages(request):
            messages.error(request, 'Invalid username or password.')

    return render(request, 'accounts/login.html', {
        'oidc_enabled': getattr(django_settings, 'OIDC_ENABLED', False),
        'ldap_enabled': getattr(django_settings, 'LDAP_ENABLED', False),
    })


def logout_view(request):
    logout(request)
    return redirect('accounts:login')


@login_required
def profile_view(request):
    profile = request.user.profile
    if request.method == 'POST' and profile.is_admin:
        user_id = request.POST.get('user_id')
        role = request.POST.get('role')
        if user_id and role in dict(UserProfile.ROLE_CHOICES):
            try:
                target = UserProfile.objects.get(user_id=user_id)
                target.role = role
                target.save()
                messages.success(request, 'Role updated.')
            except UserProfile.DoesNotExist:
                messages.error(request, 'User not found.')
        return redirect('accounts:profile')

    users = UserProfile.objects.select_related('user').all() if profile.is_admin else None
    return render(request, 'accounts/profile.html', {'users': users, 'profile': profile})

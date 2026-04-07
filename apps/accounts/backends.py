import logging

from django.conf import settings
from .models import UserProfile

logger = logging.getLogger(__name__)


class LDAPBackend:
    """
    Wraps django_auth_ldap.backend.LDAPBackend.
    After successful LDAP authentication, ensures a UserProfile exists
    and maps LDAP groups to application roles.
    """

    def __init__(self):
        from django_auth_ldap.backend import LDAPBackend as _LDAPBackend
        self._backend = _LDAPBackend()

    def authenticate(self, request, username=None, password=None, **kwargs):
        user = self._backend.authenticate(request, username=username, password=password, **kwargs)
        if user is None:
            return None

        self._sync_profile(user)
        return user

    def get_user(self, user_id):
        return self._backend.get_user(user_id)

    def _sync_profile(self, user):
        """Create or update UserProfile based on LDAP group membership."""
        profile, _ = UserProfile.objects.get_or_create(user=user)

        ldap_groups = set()
        if hasattr(user, 'ldap_user') and user.ldap_user:
            ldap_groups = set(user.ldap_user.group_names)

        admin_group = getattr(settings, 'LDAP_GROUP_ADMIN', '')
        operator_group = getattr(settings, 'LDAP_GROUP_OPERATOR', '')

        if admin_group and admin_group in ldap_groups:
            profile.role = UserProfile.ROLE_ADMIN
        elif operator_group and operator_group in ldap_groups:
            profile.role = UserProfile.ROLE_OPERATOR
        else:
            profile.role = UserProfile.ROLE_VIEWER

        profile.save()
        logger.info('LDAP user %s synced with role %s', user.username, profile.role)

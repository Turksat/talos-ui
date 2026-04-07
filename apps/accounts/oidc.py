import logging

from django.conf import settings
from mozilla_django_oidc.auth import OIDCAuthenticationBackend
from .models import UserProfile

logger = logging.getLogger(__name__)


class CustomOIDCBackend(OIDCAuthenticationBackend):
    """
    Extends mozilla-django-oidc to map Keycloak role claims to UserProfile roles.
    """

    def create_user(self, claims):
        user = super().create_user(claims)
        self._sync_profile(user, claims)
        return user

    def update_user(self, user, claims):
        user = super().update_user(user, claims)
        self._sync_profile(user, claims)
        return user

    def _sync_profile(self, user, claims):
        """Map OIDC role claim to UserProfile role."""
        profile, _ = UserProfile.objects.get_or_create(user=user)

        roles_claim = getattr(settings, 'OIDC_ROLES_CLAIM', 'roles')
        claim_roles = claims.get(roles_claim, [])

        # Support nested claims like "realm_access.roles"
        if '.' in roles_claim:
            parts = roles_claim.split('.')
            value = claims
            for part in parts:
                if isinstance(value, dict):
                    value = value.get(part, [])
                else:
                    value = []
                    break
            claim_roles = value if isinstance(value, list) else []

        if not isinstance(claim_roles, list):
            claim_roles = [claim_roles] if claim_roles else []

        admin_role = getattr(settings, 'OIDC_ROLE_ADMIN', 'admin')
        operator_role = getattr(settings, 'OIDC_ROLE_OPERATOR', 'operator')

        if admin_role in claim_roles:
            profile.role = UserProfile.ROLE_ADMIN
        elif operator_role in claim_roles:
            profile.role = UserProfile.ROLE_OPERATOR
        else:
            profile.role = UserProfile.ROLE_VIEWER

        profile.save()
        logger.info('OIDC user %s synced with role %s', user.username, profile.role)

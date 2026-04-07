from django.db import models
from django.contrib.auth.models import User


class UserProfile(models.Model):
    ROLE_ADMIN = 'admin'
    ROLE_OPERATOR = 'operator'
    ROLE_VIEWER = 'viewer'

    ROLE_CHOICES = [
        (ROLE_ADMIN, 'Admin'),
        (ROLE_OPERATOR, 'Operator'),
        (ROLE_VIEWER, 'Viewer'),
    ]

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default=ROLE_VIEWER)

    def __str__(self):
        return f'{self.user.username} ({self.get_role_display()})'

    @property
    def is_admin(self):
        return self.role == self.ROLE_ADMIN or self.user.is_superuser

    @property
    def is_operator(self):
        return self.role in (self.ROLE_ADMIN, self.ROLE_OPERATOR) or self.user.is_superuser

    @property
    def is_viewer(self):
        return True  # All roles can view

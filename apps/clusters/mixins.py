from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.contrib.auth.decorators import login_required
from functools import wraps


class OperatorRequiredMixin(LoginRequiredMixin):
    """Requires operator or admin role."""

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if not request.user.profile.is_operator:
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)


class AdminRequiredMixin(LoginRequiredMixin):
    """Requires admin role."""

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if not request.user.profile.is_admin:
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)


def operator_required(view_func):
    @wraps(view_func)
    @login_required
    def wrapper(request, *args, **kwargs):
        if not request.user.profile.is_operator:
            raise PermissionDenied
        return view_func(request, *args, **kwargs)
    return wrapper


def admin_required(view_func):
    @wraps(view_func)
    @login_required
    def wrapper(request, *args, **kwargs):
        if not request.user.profile.is_admin:
            raise PermissionDenied
        return view_func(request, *args, **kwargs)
    return wrapper

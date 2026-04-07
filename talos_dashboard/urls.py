from django.conf import settings
from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path('admin/', admin.site.urls),
    path('accounts/', include('apps.accounts.urls')),
    path('clusters/', include('apps.clusters.urls')),
    path('upgrades/', include('apps.upgrades.urls')),
    path('patches/', include('apps.patches.urls')),
    path('', include('apps.clusters.urls_dashboard')),
]

if getattr(settings, 'OIDC_ENABLED', False):
    urlpatterns.append(path('oidc/', include('mozilla_django_oidc.urls')))

from django.urls import re_path
from .consumers import UpgradeProgressConsumer

websocket_urlpatterns = [
    re_path(
        r'ws/upgrades/jobs/(?P<job_id>\d+)/progress/$',
        UpgradeProgressConsumer.as_asgi(),
    ),
]

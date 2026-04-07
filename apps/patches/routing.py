from django.urls import re_path
from .consumers import PatchProgressConsumer

websocket_urlpatterns = [
    re_path(r'ws/patches/jobs/(?P<job_id>\d+)/progress/$', PatchProgressConsumer.as_asgi()),
]

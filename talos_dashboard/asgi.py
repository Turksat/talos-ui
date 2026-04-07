import os
from django.core.asgi import get_asgi_application
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.auth import AuthMiddlewareStack

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'talos_dashboard.settings.development')

django_asgi_app = get_asgi_application()

from apps.clusters.routing import websocket_urlpatterns as cluster_ws
from apps.upgrades.routing import websocket_urlpatterns as upgrade_ws
from apps.patches.routing import websocket_urlpatterns as patch_ws

application = ProtocolTypeRouter({
    'http': django_asgi_app,
    'websocket': AuthMiddlewareStack(
        URLRouter(cluster_ws + upgrade_ws + patch_ws)
    ),
})

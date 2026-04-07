from django.urls import re_path
from . import consumers

websocket_urlpatterns = [
    re_path(
        r'ws/clusters/(?P<cluster_id>\d+)/events/$',
        consumers.ClusterEventsConsumer.as_asgi(),
    ),
    re_path(
        r'ws/clusters/(?P<cluster_id>\d+)/nodes/(?P<node_ip>[^/]+)/logs/$',
        consumers.NodeLogsConsumer.as_asgi(),
    ),
    re_path(
        r'ws/clusters/(?P<cluster_id>\d+)/nodes/(?P<node_ip>[^/]+)/logs/(?P<service>[^/]+)/$',
        consumers.NodeLogsConsumer.as_asgi(),
    ),
]

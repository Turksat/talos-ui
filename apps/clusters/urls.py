from django.urls import path
from . import views

app_name = 'clusters'

urlpatterns = [
    # Clusters
    path('', views.cluster_list, name='list'),
    path('add/', views.cluster_add, name='add'),
    path('bootstrap/', views.cluster_bootstrap, name='bootstrap'),
    path('<int:pk>/', views.cluster_detail, name='detail'),
    path('<int:pk>/edit/', views.cluster_edit, name='edit'),
    path('<int:pk>/delete/', views.cluster_delete, name='delete'),
    path('<int:pk>/refresh/', views.cluster_refresh, name='refresh'),
    path('<int:pk>/test/', views.cluster_test_connection, name='test'),
    path('<int:pk>/bootstrap-etcd/', views.cluster_bootstrap_etcd, name='bootstrap_etcd'),
    path('<int:pk>/download/talosconfig/', views.download_talosconfig, name='download_talosconfig'),
    path('<int:pk>/download/kubeconfig/', views.download_kubeconfig, name='download_kubeconfig'),
    # Nodes
    path('<int:cluster_pk>/nodes/', views.node_list, name='node_list'),
    path('<int:cluster_pk>/nodes/add/', views.node_add, name='node_add'),
    path('<int:cluster_pk>/node-config/', views.cluster_node_config, name='node_config'),
    path('<int:cluster_pk>/nodes/<str:node_ip>/', views.node_detail, name='node_detail'),
    path('<int:cluster_pk>/nodes/<str:node_ip>/dashboard/', views.node_dashboard, name='node_dashboard'),
    path('<int:cluster_pk>/nodes/<str:node_ip>/dashboard/data/', views.node_dashboard_data, name='node_dashboard_data'),
    path('<int:cluster_pk>/nodes/<str:node_ip>/reboot/', views.node_reboot, name='node_reboot'),
    path('<int:cluster_pk>/nodes/<str:node_ip>/shutdown/', views.node_shutdown, name='node_shutdown'),
    path('<int:cluster_pk>/nodes/<str:node_ip>/reset/', views.node_reset, name='node_reset'),
    path('<int:cluster_pk>/nodes/<str:node_ip>/restart-service/', views.node_restart_service, name='node_restart_service'),
    path('<int:cluster_pk>/nodes/<str:node_ip>/machineconfig/', views.machineconfig_view, name='machineconfig_edit'),
    path('<int:cluster_pk>/nodes/<str:node_ip>/machineconfig/patch/', views.machineconfig_patch, name='machineconfig_patch'),
    path('<int:cluster_pk>/nodes/<str:node_ip>/apply-config/', views.node_apply_config, name='node_apply_config'),
]

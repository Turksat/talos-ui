from django.urls import path
from . import views

app_name = 'upgrades'

urlpatterns = [
    path('image/', views.image_upgrade, name='image'),
    path('k8s/', views.k8s_upgrade, name='k8s'),
    path('jobs/', views.job_list, name='job_list'),
    path('jobs/<int:pk>/', views.job_detail, name='job_detail'),
    path('jobs/<int:pk>/status/', views.job_status_api, name='job_status_api'),
    path('cluster/<int:cluster_pk>/nodes/', views.get_cluster_nodes, name='cluster_nodes_api'),
]

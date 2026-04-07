from django.urls import path
from . import views

app_name = 'patches'

urlpatterns = [
    path('', views.patch_list, name='list'),
    path('new/', views.patch_create, name='create'),
    path('<int:pk>/edit/', views.patch_edit, name='edit'),
    path('<int:pk>/delete/', views.patch_delete, name='delete'),
    path('<int:pk>/apply/', views.patch_apply, name='apply'),
    path('jobs/', views.job_list, name='job_list'),
    path('jobs/<int:pk>/', views.job_detail, name='job_detail'),
    path('jobs/<int:pk>/status/', views.job_status_api, name='job_status_api'),
    path('api/clusters/<int:cluster_pk>/nodes/', views.get_cluster_nodes, name='cluster_nodes'),
]

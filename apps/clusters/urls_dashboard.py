from django.urls import path
from .views import overview, node_rows_partial

app_name = 'dashboard'

urlpatterns = [
    path('', overview, name='overview'),
    path('node-rows/', node_rows_partial, name='node_rows'),
]

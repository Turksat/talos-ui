import os
from celery import Celery

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'talos_dashboard.settings.development')

app = Celery('talos_dashboard')
app.config_from_object('django.conf:settings', namespace='CELERY')
app.autodiscover_tasks()

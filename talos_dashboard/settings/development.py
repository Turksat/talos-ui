from .base import *  # noqa

DEBUG = True

INSTALLED_APPS += ['django_extensions'] if False else []  # optional

# In development, allow all hosts
ALLOWED_HOSTS = ['*']

# Email backend for development
EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'

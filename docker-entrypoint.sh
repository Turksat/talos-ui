#!/bin/sh
set -e

# Run migrations
python manage.py migrate --noinput

# Create superuser if env vars are set and user doesn't exist yet
if [ -n "$DJANGO_SUPERUSER_USERNAME" ] && [ -n "$DJANGO_SUPERUSER_PASSWORD" ]; then
    python manage.py shell -c "
from django.contrib.auth.models import User
if not User.objects.filter(username='${DJANGO_SUPERUSER_USERNAME}').exists():
    User.objects.create_superuser(
        username='${DJANGO_SUPERUSER_USERNAME}',
        email='${DJANGO_SUPERUSER_EMAIL:-admin@localhost}',
        password='${DJANGO_SUPERUSER_PASSWORD}',
    )
    print('Superuser created: ${DJANGO_SUPERUSER_USERNAME}')
else:
    print('Superuser already exists: ${DJANGO_SUPERUSER_USERNAME}')
"
fi

# Collect static files
python manage.py collectstatic --noinput

exec "$@"

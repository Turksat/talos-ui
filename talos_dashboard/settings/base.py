import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent.parent

SECRET_KEY = os.environ.get('SECRET_KEY', 'insecure-default-change-in-production')

ALLOWED_HOSTS = os.environ.get('ALLOWED_HOSTS', 'localhost,127.0.0.1').split(',')

INSTALLED_APPS = [
    'daphne',                          # must be first — enables ASGI runserver
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    # Third-party
    'channels',
    'crispy_forms',
    'crispy_bootstrap5',
    # Local
    'apps.accounts',
    'apps.clusters',
    'apps.upgrades',
    'apps.patches',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'talos_dashboard.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'talos_dashboard.wsgi.application'
ASGI_APPLICATION = 'talos_dashboard.asgi.application'

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': os.environ.get('DB_PATH', str(BASE_DIR / 'db.sqlite3')),
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True

STATIC_URL = '/static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
STATIC_ROOT = BASE_DIR / 'staticfiles'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

CRISPY_ALLOWED_TEMPLATE_PACKS = 'bootstrap5'
CRISPY_TEMPLATE_PACK = 'bootstrap5'

LOGIN_URL = '/accounts/login/'
LOGIN_REDIRECT_URL = '/'
LOGOUT_REDIRECT_URL = '/accounts/login/'

REDIS_URL = os.environ.get('REDIS_URL', 'redis://localhost:6379/0')

CHANNEL_LAYERS = {
    'default': {
        'BACKEND': 'channels_redis.core.RedisChannelLayer',
        'CONFIG': {
            'hosts': [REDIS_URL],
        },
    },
}

CELERY_BROKER_URL = REDIS_URL
CELERY_RESULT_BACKEND = REDIS_URL
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_TIMEZONE = TIME_ZONE

# ─── Authentication Backends ─────────────────────────────────────────────────

AUTHENTICATION_BACKENDS = [
    'django.contrib.auth.backends.ModelBackend',
]

# ─── LDAP Authentication ─────────────────────────────────────────────────────

LDAP_ENABLED = bool(os.environ.get('LDAP_SERVER_URI'))

if LDAP_ENABLED:
    import ldap
    from django_auth_ldap.config import LDAPSearch, GroupOfNamesType

    AUTH_LDAP_SERVER_URI = os.environ.get('LDAP_SERVER_URI', '')
    AUTH_LDAP_BIND_DN = os.environ.get('LDAP_BIND_DN', '')
    AUTH_LDAP_BIND_PASSWORD = os.environ.get('LDAP_BIND_PASSWORD', '')

    AUTH_LDAP_USER_SEARCH = LDAPSearch(
        os.environ.get('LDAP_USER_SEARCH', 'ou=users,dc=example,dc=com'),
        ldap.SCOPE_SUBTREE,
        '(uid=%(user)s)',
    )

    AUTH_LDAP_GROUP_SEARCH = LDAPSearch(
        os.environ.get('LDAP_GROUP_SEARCH', 'ou=groups,dc=example,dc=com'),
        ldap.SCOPE_SUBTREE,
        '(objectClass=groupOfNames)',
    )
    AUTH_LDAP_GROUP_TYPE = GroupOfNamesType()

    AUTH_LDAP_REQUIRE_GROUP = os.environ.get('LDAP_REQUIRE_GROUP', '')

    AUTH_LDAP_USER_ATTR_MAP = {
        'first_name': 'givenName',
        'last_name': 'sn',
        'email': 'mail',
    }

    AUTH_LDAP_FIND_GROUP_PERMS = True

    # LDAP group to role mapping
    LDAP_GROUP_ADMIN = os.environ.get('LDAP_GROUP_ADMIN', 'cn=admins,ou=groups,dc=example,dc=com')
    LDAP_GROUP_OPERATOR = os.environ.get('LDAP_GROUP_OPERATOR', 'cn=operators,ou=groups,dc=example,dc=com')

    AUTHENTICATION_BACKENDS.insert(0, 'apps.accounts.backends.LDAPBackend')

# ─── Keycloak OIDC SSO ──────────────────────────────────────────────────────

OIDC_ENABLED = bool(os.environ.get('OIDC_RP_CLIENT_ID'))

if OIDC_ENABLED:
    INSTALLED_APPS.append('mozilla_django_oidc')
    MIDDLEWARE.append('mozilla_django_oidc.middleware.SessionRefresh')

    OIDC_RP_CLIENT_ID = os.environ.get('OIDC_RP_CLIENT_ID', '')
    OIDC_RP_CLIENT_SECRET = os.environ.get('OIDC_RP_CLIENT_SECRET', '')
    OIDC_RP_SIGN_ALGO = os.environ.get('OIDC_RP_SIGN_ALGO', 'RS256')

    OIDC_OP_AUTHORIZATION_ENDPOINT = os.environ.get('OIDC_OP_AUTHORIZATION_ENDPOINT', '')
    OIDC_OP_TOKEN_ENDPOINT = os.environ.get('OIDC_OP_TOKEN_ENDPOINT', '')
    OIDC_OP_USER_ENDPOINT = os.environ.get('OIDC_OP_USER_ENDPOINT', '')
    OIDC_OP_JWKS_ENDPOINT = os.environ.get('OIDC_OP_JWKS_ENDPOINT', '')

    OIDC_ROLES_CLAIM = os.environ.get('OIDC_ROLES_CLAIM', 'realm_access.roles')
    OIDC_ROLE_ADMIN = os.environ.get('OIDC_ROLE_ADMIN', 'admin')
    OIDC_ROLE_OPERATOR = os.environ.get('OIDC_ROLE_OPERATOR', 'operator')

    LOGIN_REDIRECT_URL = '/'
    LOGOUT_REDIRECT_URL = '/accounts/login/'

    AUTHENTICATION_BACKENDS.append('apps.accounts.oidc.CustomOIDCBackend')

# Talos Dashboard

![Python](https://img.shields.io/badge/python-3.11%2B-blue)
![Django](https://img.shields.io/badge/django-5.x-green)
![License](https://img.shields.io/badge/license-MIT-lightgrey)
![Status](https://img.shields.io/badge/status-active-brightgreen)

A web-based management dashboard for [Talos Linux](https://www.talos.dev/) clusters. Built with Django and Django Channels, it provides a real-time interface for managing nodes, applying machine configurations, running upgrades, and bootstrapping new clusters.

## Features

### Cluster Management
- Add, edit, and delete clusters
- Store and manage talosconfig per cluster
- Download talosconfig and kubeconfig directly from the UI
- Test cluster connectivity
- Refresh node status from the cluster

### Node Management
- View all nodes with their roles, Talos version, and Kubernetes version
- Add new worker or control plane nodes to existing clusters
- Auto-fetch existing machine config from the cluster when adding a new node
- Reboot, shutdown, reset, and restart services on nodes
- View live node logs via WebSocket

### Machine Config
- View and edit the full machine configuration (YAML editor with syntax highlighting)
- Apply machine config changes with selectable apply modes (auto, reboot, staged, etc.)
- Apply JSON patch or YAML merge patch to machine configs

### Patch Templates
- Save named patch templates (JSON RFC 6902 or YAML merge patch format)
- Apply patches to all nodes, control plane only, or worker only
- Select specific target nodes per application
- View real-time console output for each patch job via WebSocket

### Upgrades
- Image upgrade: upgrade Talos OS image on selected nodes with real-time streaming output
- Kubernetes upgrade: upgrade the Kubernetes control plane with streaming logs
- View upgrade job history and console output

### Cluster Bootstrap
- 3-step wizard: enter cluster info, review and edit generated configs, apply to nodes
- Generates `controlplane.yaml` and `worker.yaml` via `talosctl gen config`
- Edit generated YAML before applying (CodeMirror editor)
- Automatically runs `talosctl bootstrap` after config apply
- Manual bootstrap trigger from cluster detail page if needed

### Live Events
- Real-time cluster event stream via WebSocket on the cluster detail page

### Access Control
- Three roles: admin, operator, viewer
- Role-based access enforced on all views and operations

## Stack

- **Backend**: Django 5.x, Django Channels 4.x (WebSocket), Celery
- **Database**: SQLite (default), PostgreSQL (production)
- **Message Broker**: Redis (Celery broker + Channels layer)
- **Frontend**: Bootstrap 5, HTMX, CodeMirror 5
- **CLI**: wraps `talosctl` via subprocess (shell=False throughout)

## Requirements

- Python 3.11+
- Redis 5+
- `talosctl` installed and available in `PATH`
- Docker (optional, for Redis via Compose)

## Installation

```bash
git https://github.com/Turksat/talos-ui.git
cd talos-ui
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### Configure environment

Copy the example below to a `.env` file in the project root and adjust as needed:

```dotenv
SECRET_KEY=change-me-in-production
ALLOWED_HOSTS=localhost,127.0.0.1
REDIS_URL=redis://localhost:6379/0

# Optional: PostgreSQL (production)
# DATABASE_URL=postgres://user:pass@localhost/talos_dashboard

# Optional: LDAP
# LDAP_SERVER_URI=ldap://ldap.example.com
# LDAP_BIND_DN=cn=admin,dc=example,dc=com
# LDAP_BIND_PASSWORD=secret
# LDAP_USER_SEARCH=ou=users,dc=example,dc=com
# LDAP_GROUP_SEARCH=ou=groups,dc=example,dc=com
# LDAP_GROUP_ADMIN=cn=admins,ou=groups,dc=example,dc=com
# LDAP_GROUP_OPERATOR=cn=operators,ou=groups,dc=example,dc=com

# Optional: OIDC / Keycloak SSO
# OIDC_RP_CLIENT_ID=talos-ui
# OIDC_RP_CLIENT_SECRET=secret
# OIDC_RP_SIGN_ALGO=RS256
# OIDC_OP_AUTHORIZATION_ENDPOINT=https://keycloak/realms/master/protocol/openid-connect/auth
# OIDC_OP_TOKEN_ENDPOINT=https://keycloak/realms/master/protocol/openid-connect/token
# OIDC_OP_USER_ENDPOINT=https://keycloak/realms/master/protocol/openid-connect/userinfo
# OIDC_OP_JWKS_ENDPOINT=https://keycloak/realms/master/protocol/openid-connect/certs
```

### Start Redis

```bash
docker compose up -d
```

Or if Redis is installed locally:

```bash
systemctl start redis
```

### Run migrations

```bash
python manage.py migrate
python manage.py createsuperuser
```

### Start the development server

```bash
python manage.py runserver
```

### Start the Celery worker

In a separate terminal:

```bash
celery -A talos_dashboard worker -l info
```

## Production Deployment

For production, replace `runserver` with `daphne` (ASGI server) and use PostgreSQL:

```bash
pip install daphne psycopg2-binary

# Run ASGI server
daphne -b 0.0.0.0 -p 8000 talos_dashboard.asgi:application
```

Set `DJANGO_SETTINGS_MODULE=talos_dashboard.settings.production` (or base) and configure a proper database via `DATABASE_URL`. Collect static files:

```bash
python manage.py collectstatic --noinput
```

## Configuration

Settings are in `talos_dashboard/settings/base.py`. The following environment variables are supported:

### Core

| Variable | Default | Description |
|---|---|---|
| `SECRET_KEY` | insecure default | Django secret key — **must** be changed in production |
| `ALLOWED_HOSTS` | `localhost,127.0.0.1` | Comma-separated allowed hosts |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis URL (broker + channel layer) |

### LDAP (optional — enabled when `LDAP_SERVER_URI` is set)

| Variable | Description |
|---|---|
| `LDAP_SERVER_URI` | LDAP server URI, e.g. `ldap://ldap.example.com` |
| `LDAP_BIND_DN` | Bind DN for directory queries |
| `LDAP_BIND_PASSWORD` | Bind password |
| `LDAP_USER_SEARCH` | Base DN for user searches |
| `LDAP_GROUP_SEARCH` | Base DN for group searches |
| `LDAP_REQUIRE_GROUP` | DN of group required for login |
| `LDAP_GROUP_ADMIN` | DN of group mapped to `admin` role |
| `LDAP_GROUP_OPERATOR` | DN of group mapped to `operator` role |

### OIDC / Keycloak SSO (optional — enabled when `OIDC_RP_CLIENT_ID` is set)

| Variable | Description |
|---|---|
| `OIDC_RP_CLIENT_ID` | OIDC client ID |
| `OIDC_RP_CLIENT_SECRET` | OIDC client secret |
| `OIDC_RP_SIGN_ALGO` | Signing algorithm (default: `RS256`) |
| `OIDC_OP_AUTHORIZATION_ENDPOINT` | Authorization endpoint URL |
| `OIDC_OP_TOKEN_ENDPOINT` | Token endpoint URL |
| `OIDC_OP_USER_ENDPOINT` | Userinfo endpoint URL |
| `OIDC_OP_JWKS_ENDPOINT` | JWKS endpoint URL |
| `OIDC_ROLES_CLAIM` | JWT claim path for roles (default: `realm_access.roles`) |
| `OIDC_ROLE_ADMIN` | Role name mapped to `admin` (default: `admin`) |
| `OIDC_ROLE_OPERATOR` | Role name mapped to `operator` (default: `operator`) |

## Security

- All `talosctl` commands use `subprocess` with `shell=False`
- Talosconfig is written to a temporary file (`/tmp`, mode `0o600`) and deleted after use
- CSRF protection is active on all POST endpoints
- Role checks are enforced via decorators on every view

## URL Structure

| Path | Description |
|---|---|
| `/` | Dashboard overview |
| `/clusters/` | Cluster list |
| `/clusters/<pk>/` | Cluster detail with live events |
| `/clusters/<pk>/nodes/<ip>/` | Node detail and operations |
| `/clusters/<pk>/nodes/<ip>/machineconfig/` | Machine config editor |
| `/upgrades/image/` | Image upgrade |
| `/upgrades/k8s/` | Kubernetes upgrade |
| `/upgrades/jobs/` | Upgrade job list |
| `/patches/` | Patch template list |
| `/patches/<pk>/apply/` | Apply patch to cluster |
| `/patches/jobs/` | Patch job history |
| `/accounts/login/` | Login |

## WebSocket Endpoints

| Path | Description |
|---|---|
| `ws/clusters/<id>/events/` | Live cluster events |
| `ws/clusters/<id>/nodes/<ip>/logs/<service>/` | Node service logs |
| `ws/upgrades/jobs/<id>/progress/` | Upgrade job progress |
| `ws/patches/jobs/<id>/progress/` | Patch job progress |

## Development

### Running tests

```bash
python manage.py test apps
```

Or per-app:

```bash
python manage.py test apps.accounts
python manage.py test apps.clusters
python manage.py test apps.upgrades
python manage.py test apps.patches
```

Tests use Django's `TestCase` with mocked `talosctl` subprocess calls — no live cluster required.

### Project structure

```
talos_dashboard/   # Django project config (settings, urls, asgi, celery)
apps/
  accounts/        # User model, roles, LDAP/OIDC backends
  clusters/        # Cluster & Node models, talosctl wrapper, WebSocket consumers
  upgrades/        # UpgradeJob model, Celery tasks
  patches/         # Patch templates & PatchJob model
templates/         # Django HTML templates
static/            # CSS/JS assets
docs/              # Additional documentation
```

## Contributing

1. Fork the repository and create a feature branch.
2. Write or update tests for any changed behaviour.
3. Run `python manage.py check` and `python manage.py test apps` — both must pass.
4. Open a pull request with a clear description of the change.

Bug reports and feature requests are welcome via [GitHub Issues](https://github.com/Turksat/talos-ui/issues).

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# talosctl version — override with: docker compose build --build-arg TALOS_VERSION=v1.9.5
ARG TALOS_VERSION=v1.9.5

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libldap2-dev \
    libsasl2-dev \
    libssl-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Download talosctl binary from GitHub releases
RUN curl -fsSL \
    "https://github.com/siderolabs/talos/releases/download/${TALOS_VERSION}/talosctl-linux-amd64" \
    -o /usr/local/bin/talosctl \
    && chmod +x /usr/local/bin/talosctl

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /app/data

COPY docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod +x /docker-entrypoint.sh

EXPOSE 8000

ENTRYPOINT ["/docker-entrypoint.sh"]

#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"

export DJANGO_DEBUG="${DJANGO_DEBUG:-True}"
export DJANGO_COLLECTSTATIC="${DJANGO_COLLECTSTATIC:-1}"
export DJANGO_SECURE_SSL_REDIRECT="${DJANGO_SECURE_SSL_REDIRECT:-False}"
export DJANGO_SESSION_COOKIE_SECURE="${DJANGO_SESSION_COOKIE_SECURE:-False}"
export DJANGO_CSRF_COOKIE_SECURE="${DJANGO_CSRF_COOKIE_SECURE:-False}"
export DJANGO_ALLOWED_HOSTS="${DJANGO_ALLOWED_HOSTS:-localhost,127.0.0.1,0.0.0.0,testserver,ruiqu168.com,www.ruiqu168.com,*.trycloudflare.com,.trycloudflare.com}"
export DJANGO_CSRF_TRUSTED_ORIGINS="${DJANGO_CSRF_TRUSTED_ORIGINS:-https://localhost,https://127.0.0.1,https://ruiqu168.com,https://www.ruiqu168.com,https://*.trycloudflare.com}"
export CADDY_SITE_ADDRESS="${CADDY_SITE_ADDRESS:-localhost}"
export RUIQU_CADDY_SITE_ADDRESS="${RUIQU_CADDY_SITE_ADDRESS:-$CADDY_SITE_ADDRESS}"
export CADDY_HTTP_PORT="${CADDY_HTTP_PORT:-8080}"
export CADDY_HTTPS_PORT="${CADDY_HTTPS_PORT:-8443}"

echo "==> Starting Ruiqu development server"
echo "==> Django DEBUG: $DJANGO_DEBUG"
echo "==> HTTP:  http://localhost:$CADDY_HTTP_PORT/"
echo "==> HTTPS: https://localhost:$CADDY_HTTPS_PORT/"
echo "==> Stop:  Ctrl+C"
echo

exec docker compose up --build

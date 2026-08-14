#!/usr/bin/env bash
# Shared production environment for Docker Compose scripts.
# Intended to be sourced, not executed directly.

SECRET_FILE=".django_secret_key"
if [[ -z "${DJANGO_SECRET_KEY:-${RUIQU_DJANGO_SECRET_KEY:-}}" ]]; then
  if [[ ! -f "$SECRET_FILE" ]]; then
    umask 077
    python3 - <<'PY' > "$SECRET_FILE"
import secrets
chars = "abcdefghijklmnopqrstuvwxyz0123456789!@#$%^&*(-_=+)"
print("".join(secrets.choice(chars) for _ in range(50)))
PY
  fi
  export DJANGO_SECRET_KEY="$(cat "$SECRET_FILE")"
fi

export RUIQU_DJANGO_SECRET_KEY="${RUIQU_DJANGO_SECRET_KEY:-$DJANGO_SECRET_KEY}"
export DJANGO_DEBUG="${DJANGO_DEBUG:-False}"
export DJANGO_COLLECTSTATIC="${DJANGO_COLLECTSTATIC:-1}"
export DJANGO_ALLOWED_HOSTS="${DJANGO_ALLOWED_HOSTS:-ruiqu168.com,www.ruiqu168.com}"
export DJANGO_CSRF_TRUSTED_ORIGINS="${DJANGO_CSRF_TRUSTED_ORIGINS:-https://ruiqu168.com,https://www.ruiqu168.com}"
export CADDY_SITE_ADDRESS="${CADDY_SITE_ADDRESS:-ruiqu168.com, www.ruiqu168.com}"
export RUIQU_CADDY_SITE_ADDRESS="${RUIQU_CADDY_SITE_ADDRESS:-:80}"
export RUIQU_INTERNAL_CADDY_PORT="${RUIQU_INTERNAL_CADDY_PORT:-8088}"
export CADDY_HTTP_PORT="${CADDY_HTTP_PORT:-80}"
export CADDY_HTTPS_PORT="${CADDY_HTTPS_PORT:-443}"
export DJANGO_SECURE_SSL_REDIRECT="${DJANGO_SECURE_SSL_REDIRECT:-True}"
export DJANGO_SESSION_COOKIE_SECURE="${DJANGO_SESSION_COOKIE_SECURE:-True}"
export DJANGO_CSRF_COOKIE_SECURE="${DJANGO_CSRF_COOKIE_SECURE:-True}"

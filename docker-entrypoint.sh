#!/usr/bin/env bash
set -euo pipefail

python manage.py migrate --noinput

if [[ "${DJANGO_COLLECTSTATIC:-0}" == "1" ]]; then
  python manage.py collectstatic --noinput
fi

exec "$@"

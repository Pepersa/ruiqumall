#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"
# shellcheck source=prod_env.sh
source ./prod_env.sh

echo "==> Starting Ruiqu production server"
echo "==> Django DEBUG: $DJANGO_DEBUG"
echo "==> Domains: $DJANGO_ALLOWED_HOSTS"
echo "==> Internal Caddy site: $RUIQU_CADDY_SITE_ADDRESS"
echo "==> Internal Caddy local port: $RUIQU_INTERNAL_CADDY_PORT"
echo "==> Public HTTP/HTTPS should be handled by the host Caddy container"
echo

docker compose up -d
docker compose ps

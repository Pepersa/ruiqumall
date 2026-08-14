#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"
# shellcheck source=prod_env.sh
source ./prod_env.sh

QUICK=0
for arg in "$@"; do
  case "$arg" in
    --quick|-q)
      QUICK=1
      ;;
    --help|-h)
      cat <<'EOF'
Usage: ./restart_server_prod.sh [OPTIONS]

Restart the production Docker Compose stack on this Linux server.

Options:
  --quick, -q   Restart running containers without rebuild (faster, no code reload)
  --help, -h    Show this help

Default mode rebuilds images and recreates containers — use after git pull or config changes.
EOF
      exit 0
      ;;
    *)
      echo "Unknown option: $arg" >&2
      echo "Run ./restart_server_prod.sh --help for usage." >&2
      exit 1
      ;;
  esac
done

echo "==> Restarting Ruiqu production server"
echo "==> Django DEBUG: $DJANGO_DEBUG"
echo "==> Domains: $DJANGO_ALLOWED_HOSTS"
echo "==> Caddy site: $RUIQU_CADDY_SITE_ADDRESS"
echo "==> HTTP/HTTPS ports: $CADDY_HTTP_PORT/$CADDY_HTTPS_PORT"
echo

if [[ "$QUICK" == "1" ]]; then
  echo "==> Mode: quick restart (no rebuild)"
  docker compose restart
else
  echo "==> Mode: rebuild and restart"
  docker compose up -d --build
fi

docker compose ps

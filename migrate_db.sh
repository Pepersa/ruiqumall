#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"

SERVICE="${RUIQU_DOCKER_SERVICE:-web}"
COMPOSE=(docker compose)

usage() {
  cat <<'EOF'
Usage: ./migrate_db.sh [OPTIONS]

Run Django database migrations inside the Docker Compose web container.

Options:
  --plan        Show pending migrations only, do not apply
  --show        Show migration status for all apps
  --help, -h    Show this help

Examples:
  ./migrate_db.sh
  ./migrate_db.sh --plan
  ./migrate_db.sh --show
EOF
}

run_in_container() {
  if "${COMPOSE[@]}" ps --status running --services 2>/dev/null | grep -qx "$SERVICE"; then
    "${COMPOSE[@]}" exec -T "$SERVICE" "$@"
  else
    echo "==> Container '$SERVICE' is not running; using one-off container"
    "${COMPOSE[@]}" run --rm -T "$SERVICE" "$@"
  fi
}

MODE=migrate
for arg in "$@"; do
  case "$arg" in
    --plan)
      MODE=plan
      ;;
    --show)
      MODE=show
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $arg" >&2
      usage >&2
      exit 1
      ;;
  esac
done

echo "==> Ruiqu database migration (service: $SERVICE)"

case "$MODE" in
  show)
    run_in_container python manage.py showmigrations
    ;;
  plan)
    run_in_container python manage.py migrate --plan
    ;;
  migrate)
    run_in_container python manage.py migrate --noinput
    echo "==> Migration complete"
    ;;
esac

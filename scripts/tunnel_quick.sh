#!/usr/bin/env bash
# 启动 Cloudflare 临时隧道，把本机 8000 端口（数据库 runserver）暴露到公网
# 用法：./scripts/tunnel_quick.sh
set -euo pipefail

BIN="/tmp/cloudflared"
if [[ ! -x "$BIN" ]]; then
  echo "cloudflared 不在 $BIN。"
  echo "先跑：cd /tmp && curl -fL -o cloudflared.tgz https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-darwin-arm64.tgz && tar -xzf cloudflared.tgz"
  exit 1
fi

# Django 进程如果在跑，但 DJANGO_ALLOWED_HOSTS 不含 trycloudflare.com，Django 会返回 DisallowedHost (400)。
# 启动前先确认 Django 跑在 8000，且 ALLOWED_HOSTS 已包含 *.trycloudflare.com
HEALTH=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/ 2>/dev/null || echo "000")
echo "==> 本机 8000 健康检查: HTTP $HEALTH"

if [[ "$HEALTH" == "400" ]]; then
  echo "⚠️  HTTP 400 — 大概率是 ALLOWED_HOSTS 没放 trycloudflare.com。"
  echo "    请用 ./start_server_dev.sh（已更新）重启 Django 进程，或临时设置："
  echo "      DJANGO_ALLOWED_HOSTS='localhost,127.0.0.1,*.trycloudflare.com' python manage.py runserver 0.0.0.0:8000"
  exit 1
fi

echo "==> 启动 quick tunnel（Ctrl+C 关闭）"
echo "    启动后把 URL 发给外网用户即可。"
echo
exec "$BIN" tunnel --no-autoupdate --url http://localhost:8000

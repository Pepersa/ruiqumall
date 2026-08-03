#!/usr/bin/env bash
# 局域网访问诊断 - 找出为什么 192.168.1.6:8000 同网不通
set -u

LOCAL_IP="192.168.1.6"
PORT="8000"

echo "============ 1. 本机 IP ============"
ifconfig 2>/dev/null | grep -E "inet " | grep -v "127.0.0.1" | awk '{print "  "$2}' | head -5 || \
ipconfig getifaddr en0 2>/dev/null | awk '{print "  en0: "$0}'
echo "  路由器网关: $(ipconfig getrouter 2>/dev/null | head -1 || echo 未知)"

echo
echo "============ 2. 8000 端口监听情况 ============"
lsof -nP -iTCP:$PORT -sTCP:LISTEN 2>/dev/null | tail -n +2 || \
  netstat -an | grep "\.$PORT " | grep LISTEN
echo

echo "============ 3. macOS 防火墙状态 ============"
FW_STATE=$(/usr/libexec/ApplicationFirewall/socketfilterfw --getglobalstate 2>/dev/null | tr -d '\n')
echo "  $FW_STATE"
echo "  （如显示 enabled + block all incoming，8000 一定被挡）"

echo
echo "============ 4. 是否在 docker 容器里跑 ============"
# 已知 .venv 直接跑
PY_PATHS=$(ps -eo command | grep -E "manage\.py runserver|wsgi|asgi" | grep -v grep | head -3)
if [[ -n "$PY_PATHS" ]]; then
  echo "  Python 进程："
  echo "$PY_PATHS" | sed 's/^/    /'
else
  echo "  未发现 manage.py runserver 进程"
fi

echo
echo "============ 5. Django runserver 启动方式 ============"
# 同一个 process 里的监听地址
ps -eo command | grep -E "runserver" | grep -v grep | head -3 | while read line; do
  echo "  命令: $line"
  # 提取 --host 或 runserver 后的地址
  echo "$line" | grep -oE "runserver[^[:space:]]* [^[:space:]]+" | head -1 | sed 's/^/    实际监听: /'
done

echo
echo "============ 6. 局域网探测 ============"
GW=$(ipconfig getrouter 2>/dev/null | head -1 || echo "")
if [[ -n "$GW" ]]; then
  echo "  ping 网关 $GW ..."
  ping -c 1 -W 1 "$GW" 2>&1 | tail -1 | sed 's/^/    /'
fi
echo "  本机能否访问自己 127.0.0.1:$PORT? "
curl -s -o /dev/null -w "    HTTP=%{http_code}\n" "http://127.0.0.1:$PORT/" --max-time 2 || echo "    无法连接"
echo "  本机通过 $LOCAL_IP 访问自己?"
curl -s -o /dev/null -w "    HTTP=%{http_code}\n" "http://$LOCAL_IP:$PORT/" --max-time 2 || echo "    无法连接"

echo
echo "============ 结论对照 ============"
echo "  步骤 2 显示 *:8000  → runserver 绑了 0.0.0.0  ✅"
echo "  步骤 2 显示 127.0.0.1:8000 → 只绑本机，需要 --host 0.0.0.0 启动"
echo "  步骤 6 自己访问自己 192.168.1.6:8000 返回 200 但 ping 不通另一台 → 防火墙"
echo "  步骤 6 自己都连不上 192.168.1.6:8000 → runserver 绑了 127.0.0.1"

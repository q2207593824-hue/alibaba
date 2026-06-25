#!/bin/bash
# 云端一键恢复：清 8000 占用 + 可选清 sqlite 锁文件 + 前台试跑 health
set -e
ROOT="${1:-/www/wwwroot/ali-auto-publish-fullstack}"
BACKEND="$ROOT/backend"
DATA="${ALI_APP_DATA_DIR:-$ROOT/data}"
PORT="${BACKEND_PORT:-8000}"

echo "[cloud_restart] stop old processes on :$PORT"
pkill -f "run_cloud.py" 2>/dev/null || true
pkill -f "run.py" 2>/dev/null || true
pkill -f "uvicorn" 2>/dev/null || true
sleep 2
if command -v fuser >/dev/null 2>&1; then
  fuser -k "${PORT}/tcp" 2>/dev/null || true
  sleep 1
fi

if ss -lntp 2>/dev/null | grep -q ":${PORT} "; then
  echo "[cloud_restart] ERROR: port $PORT still in use:"
  ss -lntp | grep ":${PORT} " || true
  exit 1
fi

echo "[cloud_restart] remove sqlite wal/shm if present"
rm -f "$DATA/membership.db-wal" "$DATA/membership.db-shm" 2>/dev/null || true

cd "$BACKEND"
export MEMBERSHIP_IS_CLOUD_HOST=1
export MEMBERSHIP_POINTS_SOURCE=local
export ALI_BACKEND_WORKERS=1
export ALI_CLOUD_APP=app.cloud_app:app
export BACKEND_PORT="$PORT"
export ALI_APP_DATA_DIR="$DATA"

PY=""
for c in ./*_venv/bin/python3 ./venv/bin/python3; do
  if [ -x "$c" ]; then PY="$c"; break; fi
done
PY="${PY:-python3}"

echo "[cloud_restart] test run (Ctrl+C after health ok)"
echo "[cloud_restart] curl http://127.0.0.1:$PORT/api/health in another terminal"
exec "$PY" -u run_cloud.py

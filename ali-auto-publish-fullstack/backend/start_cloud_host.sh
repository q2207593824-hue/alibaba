#!/bin/bash
# 云端服务器专用：本机为会员/积分权威，禁止再请求公网 membership API。
# 宝塔「Python 项目」请用启动文件 run_cloud.py（不要用本 bash 脚本，面板会当 Python 执行 bash 报错）
# 重要：请先在宝塔面板点「停止」本项目，勿与面板守护进程同时抢 8000 端口。

set -e
cd "$(dirname "$0")"

export MEMBERSHIP_POINTS_SOURCE=local
export MEMBERSHIP_IS_CLOUD_HOST=1
export ALI_BACKEND_WORKERS=1

PORT="${BACKEND_PORT:-8000}"

if command -v ss >/dev/null 2>&1; then
  if ss -lntp 2>/dev/null | grep -q ":${PORT} "; then
    echo "[start_cloud_host] 错误: 端口 ${PORT} 已被占用。请先在宝塔 Python 项目里点「停止」，再执行本脚本。"
    echo "[start_cloud_host] 占用详情:"
    ss -lntp | grep ":${PORT} " || true
    exit 1
  fi
fi

echo "[start_cloud_host] MEMBERSHIP_POINTS_SOURCE=${MEMBERSHIP_POINTS_SOURCE}"
echo "[start_cloud_host] MEMBERSHIP_IS_CLOUD_HOST=${MEMBERSHIP_IS_CLOUD_HOST}"
echo "[start_cloud_host] ALI_BACKEND_WORKERS=${ALI_BACKEND_WORKERS}"

if [ -f "./abf6e215d777327786333f8c0d4b2a62_venv/bin/python3" ]; then
  exec ./abf6e215d777327786333f8c0d4b2a62_venv/bin/python3 -u run_cloud.py
fi
if [ -f "./venv/bin/python3" ]; then
  exec ./venv/bin/python3 -u run_cloud.py
fi
exec python3 -u run_cloud.py

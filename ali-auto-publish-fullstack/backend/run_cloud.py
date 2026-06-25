# -*- coding: utf-8 -*-
"""
宝塔「Python 项目管理」专用入口（必须用本文件，不要用 /bin/bash）。

在面板里：
  项目路径 = .../backend
  启动文件 = run_cloud.py
  启动方式 = python
  端口 = 8000
"""
from __future__ import annotations

import os
import sys

_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _ROOT)

# 必须在 import app / uvicorn 之前设置（membership_service 在导入时读取环境变量）
os.environ.setdefault("MEMBERSHIP_POINTS_SOURCE", "local")
os.environ.setdefault("MEMBERSHIP_IS_CLOUD_HOST", "1")
os.environ.setdefault("ALI_BACKEND_WORKERS", "1")
os.environ.setdefault("ALI_BACKEND_RELOAD", "0")
os.environ.setdefault("ALI_DISABLE_BROWSER_OPEN", "1")
os.environ.setdefault(
    "ALI_APP_DATA_DIR",
    os.environ.get("ALI_APP_DATA_DIR", "").strip()
    or os.path.join(os.path.dirname(_ROOT), "data"),
)
os.environ.setdefault(
    "CLOUD_MEMBERSHIP_API_BASE",
    "https://echo-yiwu.cloud/api/membership",
)

if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("BACKEND_PORT", "8000").strip() or "8000")
    # 云端会员 API 固定单进程（宝塔误配 workers=4 会导致 4 个进程抢 8000、登录异常）
    workers = 1
    os.environ["ALI_BACKEND_WORKERS"] = "1"

    print("[run_cloud] MEMBERSHIP_POINTS_SOURCE=", os.environ.get("MEMBERSHIP_POINTS_SOURCE"))
    print("[run_cloud] MEMBERSHIP_IS_CLOUD_HOST=", os.environ.get("MEMBERSHIP_IS_CLOUD_HOST"))
    print("[run_cloud] ALI_BACKEND_WORKERS=", workers)
    print("[run_cloud] ALI_APP_DATA_DIR=", os.environ.get("ALI_APP_DATA_DIR"))
    app_target = os.getenv("ALI_CLOUD_APP", "app.cloud_app:app").strip() or "app.cloud_app:app"
    print(f"[run_cloud] app={app_target}")
    print(f"[run_cloud] listening 0.0.0.0:{port}")

    uvicorn.run(
        app_target,
        host="0.0.0.0",
        port=port,
        reload=False,
        workers=workers,
        timeout_keep_alive=5,
    )

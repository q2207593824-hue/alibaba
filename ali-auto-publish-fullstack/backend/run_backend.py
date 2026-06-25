# -*- coding: utf-8 -*-
"""Desktop backend entrypoint.
打包后由 Electron 直接启动，无需用户安装 Python。
"""
import os
import sys
from pathlib import Path


def _ensure_single_desktop_instance() -> None:
    """避免 Electron 监控超时重复拉起第二个 ali-backend.exe。"""
    if os.getenv("ALI_DESKTOP", "").strip() != "1":
        return
    if sys.platform != "win32":
        return
    import ctypes

    port = os.getenv("BACKEND_PORT", "8000").strip() or "8000"
    mutex_name = f"Global\\AliAutoPublishBackend_{port}"
    handle = ctypes.windll.kernel32.CreateMutexW(None, True, mutex_name)
    if ctypes.windll.kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
        print(f"[backend] duplicate instance blocked ({mutex_name})")
        sys.exit(0)
    globals()["_DESKTOP_BACKEND_MUTEX"] = handle


# 确保能导入 app 包
BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

# 桌面/打包态默认写到用户目录，避免 Program Files 等安装目录无写权限
_frozen = getattr(sys, "frozen", False)
_desktop = os.getenv("ALI_DESKTOP", "").strip() == "1"
if _frozen or _desktop:
    _appdata = os.environ.get("APPDATA", "").strip()
    default_data_dir = (
        Path(_appdata) / "AliAutoPublish" / "data"
        if _appdata
        else Path.home() / "AliAutoPublish" / "data"
    )
else:
    default_data_dir = BASE_DIR.parent / "data"
os.environ.setdefault("ALI_APP_DATA_DIR", str(default_data_dir))

_ensure_single_desktop_instance()

import uvicorn  # noqa: E402

from app.core.desktop_bootstrap import ensure_desktop_admin_api_key  # noqa: E402
from app.main import app  # noqa: E402

ensure_desktop_admin_api_key()

if __name__ == "__main__":
    host = os.getenv("BACKEND_HOST", "127.0.0.1")
    port = int(os.getenv("BACKEND_PORT", "8000"))
    uvicorn.run(app, host=host, port=port, log_level="info")

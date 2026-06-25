# -*- coding: utf-8 -*-
"""检查管理员运行时配置（API Key / 模型）同步状态。"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

os.environ.setdefault("ALI_APP_DATA_DIR", str(Path(os.environ.get("APPDATA", "")) / "AliAutoPublish" / "data"))


def main() -> int:
    from app.core.desktop_bootstrap import ensure_desktop_admin_api_key

    ensure_desktop_admin_api_key()
    from app.services.membership_service import _get_admin_api_key
    from app.core.admin_runtime_config import is_masked_secret, resolve_runtime_secret
    from app.services.admin_runtime_cloud_sync import ensure_runtime_secrets_ready, pull_cloud_admin_runtime_to_local
    from app.services.membership_service import _get_admin_api_key, _membership_cloud_sync_enabled

    cfg_path = Path(os.environ["ALI_APP_DATA_DIR"]) / "config.json"
    backup_path = Path(os.environ["ALI_APP_DATA_DIR"]) / "admin_runtime_config.json"

    print("=== 管理员配置同步检查 ===\n")
    print(f"云端同步: {'启用' if _membership_cloud_sync_enabled() else '禁用'}")
    print(f"本机 admin_key: {'有' if _get_admin_api_key() else '无'}")

    if cfg_path.is_file():
        cfg = json.loads(cfg_path.read_text(encoding="utf-8-sig"))
        k = str((cfg.get("data_analysis") or {}).get("doubao_api_key") or "")
        print(f"config.json doubao_api_key: {'有效' if k and not is_masked_secret(k) else '无效/脱敏'} ({repr(k[:12])}...)")
    else:
        print("config.json: 不存在")

    print(f"admin_runtime_config.json: {'存在' if backup_path.is_file() else '不存在（管理员保存后会生成）'}")

    ready = ensure_runtime_secrets_ready()
    print(f"\nensure_runtime_secrets_ready: {'PASS' if ready else 'FAIL'}")

    resolved = resolve_runtime_secret("data_analysis", "doubao_api_key")
    print(f"resolve doubao_api_key: {'PASS' if resolved and not is_masked_secret(resolved) else 'FAIL'}")

    try:
        pulled = pull_cloud_admin_runtime_to_local()
        print(f"pull_cloud: revision={pulled.get('revision')} secrets_ready={pulled.get('secrets_ready')}")
    except Exception as e:
        print(f"pull_cloud: FAIL — {e}")

    return 0 if ready else 1


if __name__ == "__main__":
    raise SystemExit(main())

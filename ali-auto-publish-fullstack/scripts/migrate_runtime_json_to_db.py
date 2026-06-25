# -*- coding: utf-8 -*-
"""一次性迁移：admin_runtime_config.json + config.json points_pricing → app_runtime_settings 表。"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

# 云端主机执行时设置 MEMBERSHIP_IS_CLOUD_HOST=1 与 ALI_APP_DATA_DIR
os.environ.setdefault("MEMBERSHIP_IS_CLOUD_HOST", "1")


def main() -> int:
    from app.services.app_runtime_settings_service import load_app_runtime_settings, migrate_legacy_runtime_to_db_if_needed
    from app.services.membership_service import init_db

    init_db()
    migrated = migrate_legacy_runtime_to_db_if_needed()
    row = load_app_runtime_settings()
    print("migrated:", migrated)
    print("revision:", row.get("revision"))
    print("points_pricing:", row.get("points_pricing"))
    print("data_analysis keys:", list((row.get("data_analysis") or {}).keys()))
    print("ai_image_gen keys:", len((row.get("ai_image_gen") or {}).keys()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

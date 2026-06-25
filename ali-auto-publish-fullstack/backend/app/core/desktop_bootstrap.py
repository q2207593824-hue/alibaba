# -*- coding: utf-8 -*-
"""桌面端首次启动：同步管理员 API Key 等与云端一致的部署参数。"""
from __future__ import annotations

import json
import os
import sys

from app.core.logger import setup_logger

logger = setup_logger("desktop_bootstrap")

_PLACEHOLDER_ADMIN_KEYS = frozenset({"", "change-me-admin", "change-me"})


def _is_desktop() -> bool:
    return os.getenv("ALI_DESKTOP", "").strip().lower() in {"1", "true", "yes"}


def _resolve_deploy_admin_key() -> str:
    env_key = os.getenv("ALI_ADMIN_API_KEY", "").strip()
    if env_key and env_key not in _PLACEHOLDER_ADMIN_KEYS:
        return env_key

    from pathlib import Path

    candidates = []
    data_dir = os.getenv("ALI_APP_DATA_DIR", "").strip()
    if data_dir:
        data_path = Path(data_dir)
        candidates.append(data_path / "desktop.deploy.json")
        candidates.append(data_path.parent / "desktop.deploy.json")
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        candidates.extend(
            [
                exe_dir / "desktop.deploy.json",
                exe_dir.parent / "desktop.deploy.json",
                # Electron: resources/backend-dist/ali-backend/ali-backend.exe → resources/desktop.deploy.json
                exe_dir.parent.parent.parent / "desktop.deploy.json",
            ]
        )
    try:
        project_root = Path(__file__).resolve().parents[3]
        candidates.append(project_root / "frontend" / "electron" / "desktop.deploy.json")
    except Exception:
        pass

    for path in candidates:
        try:
            if not path.is_file():
                continue
            with open(path, "r", encoding="utf-8-sig") as f:
                data = json.load(f)
            key = str((data or {}).get("admin_api_key") or "").strip()
            if key and key not in _PLACEHOLDER_ADMIN_KEYS:
                logger.info("desktop bootstrap: deploy admin key from %s", path)
                return key
        except Exception:
            continue
    return ""


def _seed_user_deploy_json(deploy_key: str) -> None:
    """与 Electron seedDesktopDeployFile 一致：写入用户目录 desktop.deploy.json 供后续启动读取。"""
    data_dir = os.getenv("ALI_APP_DATA_DIR", "").strip()
    if not data_dir or not deploy_key:
        return
    try:
        from pathlib import Path

        target = Path(data_dir).parent / "desktop.deploy.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.is_file():
            try:
                cur = json.loads(target.read_text(encoding="utf-8-sig"))
                if str((cur or {}).get("admin_api_key") or "").strip() == deploy_key:
                    return
            except Exception:
                pass
        target.write_text(
            json.dumps({"admin_api_key": deploy_key}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        logger.info("desktop bootstrap: seeded %s", target)
    except Exception as e:
        logger.warning("desktop bootstrap: seed desktop.deploy.json failed: %s", e)


def _read_payment_admin_key_on_disk() -> str:
    """读 config.json 文件中的原始值（不受 ALI_ADMIN_API_KEY 运行时覆盖）。"""
    try:
        from pathlib import Path

        from app.core.settings import CONFIG_FILE

        path = Path(CONFIG_FILE)
        if not path.is_file():
            return ""
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        return str((data.get("payment") or {}).get("admin_api_key") or "").strip()
    except Exception:
        return ""


def ensure_desktop_admin_api_key() -> None:
    """
    将安装包/环境变量中的 admin_api_key 写入 config.json，避免仍为 change-me-admin 占位符。
    桌面端（ALI_DESKTOP 或 PyInstaller）以 deploy/env 为权威来源；开发机仅覆盖占位符以免误改手工配置。
    """
    deploy_key = _resolve_deploy_admin_key()
    env_key = os.getenv("ALI_ADMIN_API_KEY", "").strip()
    if env_key and env_key not in _PLACEHOLDER_ADMIN_KEYS:
        deploy_key = env_key
    elif deploy_key:
        os.environ.setdefault("ALI_ADMIN_API_KEY", deploy_key)

    if not deploy_key:
        logger.warning("desktop bootstrap: no deploy admin key, skip config sync")
        return

    desktop_mode = _is_desktop() or getattr(sys, "frozen", False)
    if desktop_mode:
        _seed_user_deploy_json(deploy_key)

    try:
        from app.core.settings import config_manager

        on_disk = _read_payment_admin_key_on_disk()
        if on_disk == deploy_key:
            return

        if on_disk in _PLACEHOLDER_ADMIN_KEYS or not on_disk:
            should_sync = True
        elif desktop_mode:
            should_sync = True
        else:
            should_sync = False

        if not should_sync:
            logger.info(
                "desktop bootstrap: keep custom payment.admin_api_key on disk (dev, non-placeholder)"
            )
            return

        config_manager.update("payment", {"admin_api_key": deploy_key})
        reason = "placeholder" if on_disk in _PLACEHOLDER_ADMIN_KEYS or not on_disk else "desktop_deploy_mismatch"
        logger.info("desktop bootstrap: synced payment.admin_api_key (%s)", reason)
    except Exception as e:
        logger.warning("desktop bootstrap admin_api_key sync failed: %s", e)

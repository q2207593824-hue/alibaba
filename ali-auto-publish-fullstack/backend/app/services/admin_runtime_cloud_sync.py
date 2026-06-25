# -*- coding: utf-8 -*-
"""桌面端：管理员运行时配置与云端同步。"""
from __future__ import annotations

import threading
from typing import Any, Dict, Optional

_CONFIG_IO_LOCK = threading.Lock()

from app.core.admin_runtime_config import (
    AI_IMAGE_GEN_ADMIN_KEYS,
    DATA_ANALYSIS_ADMIN_KEYS,
    build_admin_runtime_payload,
    get_config_revision,
    should_skip_runtime_secret_merge,
)
from app.core.logger import setup_logger
from app.core.settings import config_manager, get_config
from app.services.app_runtime_settings_service import POINTS_PRICING_KEYS
from app.services.membership_service import (
    CLOUD_MEMBERSHIP_API_BASE,
    _cloud_http_request,
    _membership_cloud_sync_enabled,
    _parse_cloud_http_error,
)

logger = setup_logger("admin_runtime_cloud_sync")

_CLOUD_RUNTIME_PATH = "/admin/runtime-config"

# 会员可见：不暴露 Key，仅说明总部配置/网络问题
MSG_CLOUD_KEY_MASKED = (
    "总部云端豆包 API Key 仍为脱敏占位或未配置，请管理员登录后在【流量分析】或【产品优化建议】"
    "页面重新输入并保存完整 API Key（会员无需配置 Key）"
)
MSG_PULL_FAILED = (
    "无法从总部云端同步 API 配置，请检查网络能否访问 echo-yiwu.cloud 后重试"
)
MSG_NO_DEPLOY_ADMIN = (
    "本机未找到总部同步密钥（desktop.deploy.json），请重新安装官方客户端或联系技术支持"
)
MSG_GENERIC = (
    "豆包 API Key 未就绪，请管理员在总部保存完整 Key 后，会员重新登录客户端再试"
)


def runtime_secrets_unavailable_message(reason: str = "") -> str:
    r = str(reason or "").strip().lower()
    if r in ("cloud_key_masked", "cloud_empty"):
        return MSG_CLOUD_KEY_MASKED
    if r in ("pull_failed", "network"):
        return MSG_PULL_FAILED
    if r in ("no_deploy_admin", "no_admin_key"):
        return MSG_NO_DEPLOY_ADMIN
    return MSG_GENERIC


def _runtime_url() -> str:
    return f"{CLOUD_MEMBERSHIP_API_BASE.rstrip('/')}{_CLOUD_RUNTIME_PATH}"


def _auth_headers(*, bearer: str = "", admin_key: str = "", desktop_backend_sync: bool = False) -> Dict[str, str]:
    headers: Dict[str, str] = {"Accept": "application/json", "Content-Type": "application/json"}
    if bearer:
        headers["Authorization"] = f"Bearer {bearer.strip()}"
    if admin_key:
        headers["X-Admin-Key"] = admin_key.strip()
    if desktop_backend_sync:
        headers["X-Desktop-Backend-Sync"] = "1"
    return headers


def build_push_body_from_local() -> Dict[str, Any]:
    payload = build_admin_runtime_payload(full_access=True)
    cfg = get_config()
    return {
        "data_analysis": payload.get("data_analysis") or {},
        "ai_image_gen": payload.get("ai_image_gen") or {},
        "points_pricing": cfg.points_pricing.model_dump(),
    }


def apply_cloud_payload_to_local(cloud: Dict[str, Any]) -> int:
    """将云端管理员配置合并进本机 config.json，返回本机 revision。"""
    cfg = config_manager.reload_from_disk()
    data = cfg.model_dump()
    changed = False

    da_in = cloud.get("data_analysis") if isinstance(cloud.get("data_analysis"), dict) else {}
    ai_in = cloud.get("ai_image_gen") if isinstance(cloud.get("ai_image_gen"), dict) else {}

    if da_in:
        da = dict(data.get("data_analysis") or {})
        da_changed = False
        for k in DATA_ANALYSIS_ADMIN_KEYS:
            if k not in da_in or da_in[k] is None:
                continue
            if should_skip_runtime_secret_merge(k, da_in[k], da.get(k)):
                continue
            if da.get(k) != da_in[k]:
                da[k] = da_in[k]
                da_changed = True
        if da_changed:
            data["data_analysis"] = da
            changed = True

    if ai_in:
        ai = dict(data.get("ai_image_gen") or {})
        ai_changed = False
        for k in AI_IMAGE_GEN_ADMIN_KEYS:
            if k not in ai_in or ai_in[k] is None:
                continue
            if should_skip_runtime_secret_merge(k, ai_in[k], ai.get(k)):
                continue
            if ai.get(k) != ai_in[k]:
                ai[k] = ai_in[k]
                ai_changed = True
        if ai_changed:
            data["ai_image_gen"] = ai
            changed = True

    pp_in = cloud.get("points_pricing") if isinstance(cloud.get("points_pricing"), dict) else {}
    if pp_in:
        pp = dict(data.get("points_pricing") or {})
        pp_changed = False
        for k in POINTS_PRICING_KEYS:
            if k not in pp_in or pp_in[k] is None:
                continue
            try:
                val = float(pp_in[k])
            except (TypeError, ValueError):
                continue
            if pp.get(k) != val:
                pp[k] = val
                pp_changed = True
        if pp_changed:
            data["points_pricing"] = pp
            changed = True

    if changed:
        with _CONFIG_IO_LOCK:
            config_manager.update_full(data)
            try:
                from app.services.cloud_admin_runtime_service import save_cloud_admin_runtime

                save_cloud_admin_runtime(
                    data_analysis=data.get("data_analysis") if isinstance(data.get("data_analysis"), dict) else None,
                    ai_image_gen=data.get("ai_image_gen") if isinstance(data.get("ai_image_gen"), dict) else None,
                    points_pricing=data.get("points_pricing") if isinstance(data.get("points_pricing"), dict) else None,
                    merge=True,
                )
            except Exception as e:
                logger.warning("sync admin_runtime_config.json after pull failed: %s", e)
    return get_config_revision()


def _clear_stale_analysis_failures_if_ready(secrets_ready: bool) -> int:
    if not secrets_ready:
        return 0
    try:
        from app.core.task_manager import task_manager

        n = task_manager.clear_stale_failed_tasks()
        if n:
            logger.info("cleared %s stale failed analysis task(s) after runtime secrets ready", n)
        return n
    except Exception as e:
        logger.warning("clear stale analysis tasks failed: %s", e)
        return 0


def fetch_cloud_admin_runtime_revision(*, bearer: str = "", admin_key: str = "") -> int:
    if not _membership_cloud_sync_enabled():
        return get_config_revision()
    from app.services.membership_service import _get_admin_api_key

    key = str(admin_key or "").strip()
    if not key or key in ("change-me-admin", "change-me"):
        key = _get_admin_api_key()
    if key and key not in ("change-me-admin", "change-me"):
        headers = _auth_headers(admin_key=key)
    else:
        headers = _auth_headers(bearer=bearer, desktop_backend_sync=True)
    resp = _cloud_http_request(
        "GET",
        _runtime_url(),
        headers=headers,
        timeout=(5, 20),
    )
    if not resp.ok:
        raise ValueError(_parse_cloud_http_error(resp))
    payload = resp.json() if resp.content else {}
    data = payload.get("data") if isinstance(payload, dict) else payload
    if not isinstance(data, dict):
        return 0
    return int(data.get("revision") or 0)


def _fetch_cloud_runtime_payload(*, bearer: str = "", admin_key: str = "") -> Dict[str, Any]:
    """用安装包内置 admin key（或会员 bearer+desktop sync）从云端拉完整运行时配置。"""
    from app.services.membership_service import _get_admin_api_key

    key = str(admin_key or "").strip()
    if not key or key in ("change-me-admin", "change-me"):
        key = _get_admin_api_key()

    if key and key not in ("change-me-admin", "change-me"):
        headers = _auth_headers(admin_key=key)
    else:
        headers = _auth_headers(bearer=bearer, desktop_backend_sync=True)

    resp = _cloud_http_request(
        "GET",
        _runtime_url(),
        headers=headers,
        timeout=(8, 45),
    )
    if not resp.ok and bearer and key:
        resp = _cloud_http_request(
            "GET",
            _runtime_url(),
            headers=_auth_headers(bearer=bearer, desktop_backend_sync=True),
            timeout=(8, 45),
        )
    if not resp.ok:
        raise ValueError(_parse_cloud_http_error(resp))
    payload = resp.json() if resp.content else {}
    data = payload.get("data") if isinstance(payload, dict) else payload
    if not isinstance(data, dict):
        raise ValueError("云端未返回有效配置")
    return data


def _cloud_doubao_key_status(cloud: Dict[str, Any]) -> str:
    """返回 cloud_empty | cloud_key_masked | ok"""
    from app.core.admin_runtime_config import is_masked_secret

    da = cloud.get("data_analysis") if isinstance(cloud.get("data_analysis"), dict) else {}
    raw = str(da.get("doubao_api_key") or "").strip()
    if not raw:
        return "cloud_empty"
    if is_masked_secret(raw):
        return "cloud_key_masked"
    return "ok"


def pull_cloud_admin_runtime_to_local(
    *,
    bearer: str = "",
    admin_key: str = "",
    run_ensure: bool = True,
) -> Dict[str, Any]:
    if not _membership_cloud_sync_enabled():
        return {"revision": get_config_revision(), "source": "local", "skipped": True}

    from app.services.membership_service import _get_admin_api_key

    key = str(admin_key or "").strip()
    if not key or key in ("change-me-admin", "change-me"):
        key = _get_admin_api_key()

    data = _fetch_cloud_runtime_payload(bearer=bearer, admin_key=key)
    cloud_key_status = _cloud_doubao_key_status(data)
    local_rev = apply_cloud_payload_to_local(data)
    secrets_ready = None
    if run_ensure:
        secrets_ready = ensure_runtime_secrets_ready(
            bearer=bearer, admin_key=key, skip_pull=True
        )
    else:
        from app.core.admin_runtime_config import is_masked_secret, resolve_runtime_secret

        resolved = resolve_runtime_secret("data_analysis", "doubao_api_key")
        secrets_ready = bool(resolved and not is_masked_secret(resolved))
    if secrets_ready:
        _clear_stale_analysis_failures_if_ready(True)
    logger.info(
        "pulled cloud admin runtime config revision=%s local_revision=%s secrets_ready=%s",
        data.get("revision"),
        local_rev,
        secrets_ready,
    )
    return {
        "revision": int(data.get("revision") or 0),
        "local_revision": local_rev,
        "source": "cloud",
        "secrets_ready": secrets_ready,
        "cloud_key_status": cloud_key_status,
    }


def _put_runtime_config_to_remote(*, admin_key: str = "") -> Dict[str, Any]:
    from app.services.membership_service import _get_admin_api_key

    key = str(admin_key or "").strip()
    if not key or key in ("change-me-admin", "change-me"):
        key = _get_admin_api_key()
    if not key:
        raise ValueError("管理员 API Key 未配置，无法同步到云端")

    body = build_push_body_from_local()
    resp = _cloud_http_request(
        "PUT",
        _runtime_url(),
        headers=_auth_headers(admin_key=key),
        json=body,
        timeout=(8, 45),
    )
    if not resp.ok:
        raise ValueError(_parse_cloud_http_error(resp))
    payload = resp.json() if resp.content else {}
    data = payload.get("data") if isinstance(payload, dict) else payload
    logger.info("pushed admin runtime config to cloud revision=%s", (data or {}).get("revision"))
    return data if isinstance(data, dict) else {"success": True}


def push_remote_admin_runtime_to_cloud(*, admin_key: str = "") -> Dict[str, Any]:
    """桌面开发机强制推送到远程 echo-yiwu.cloud（不受 MEMBERSHIP_IS_CLOUD_HOST 影响）。"""
    return _put_runtime_config_to_remote(admin_key=admin_key)


def push_local_admin_runtime_to_cloud(*, admin_key: str = "") -> Dict[str, Any]:
    if not _membership_cloud_sync_enabled():
        return {"skipped": True, "reason": "cloud_sync_disabled"}
    return _put_runtime_config_to_remote(admin_key=admin_key)


def ensure_runtime_secrets_ready(
    *,
    bearer: str = "",
    admin_key: str = "",
    skip_pull: bool = False,
) -> bool:
    """兼容旧调用：仅返回是否就绪。"""
    ready, _ = ensure_runtime_secrets_ready_detail(
        bearer=bearer, admin_key=admin_key, skip_pull=skip_pull
    )
    return ready


def ensure_runtime_secrets_ready_detail(
    *,
    bearer: str = "",
    admin_key: str = "",
    skip_pull: bool = False,
) -> tuple[bool, str]:
    """
    会员执行 AI 分析/生图前，确保本机 config 含完整豆包密钥。
    使用安装包内置 admin key 向云端拉取，Key 只落本机后端文件，不返回浏览器。
    返回 (是否就绪, 失败原因码)。
    """
    from app.core.admin_runtime_config import (
        is_masked_secret,
        purge_masked_runtime_secrets_from_local,
        resolve_runtime_secret,
    )
    from app.services.membership_service import _get_admin_api_key, _membership_cloud_sync_enabled

    try:
        from app.core.desktop_bootstrap import ensure_desktop_admin_api_key

        ensure_desktop_admin_api_key()
    except Exception as e:
        logger.warning("ensure_runtime_secrets_ready bootstrap skipped: %s", e)

    purge_masked_runtime_secrets_from_local()

    cfg = config_manager.reload_from_disk()
    cur = str(getattr(cfg.data_analysis, "doubao_api_key", "") or "").strip()
    if cur and not is_masked_secret(cur):
        return True, "ok"

    deploy_key = str(admin_key or "").strip() or _get_admin_api_key()
    if not deploy_key or deploy_key in ("change-me-admin", "change-me"):
        if not _membership_cloud_sync_enabled():
            resolved = resolve_runtime_secret("data_analysis", "doubao_api_key")
            if resolved and not is_masked_secret(resolved):
                return True, "ok"
            return False, "no_deploy_admin"

    last_cloud_status = ""
    if not skip_pull and _membership_cloud_sync_enabled():
        for attempt in range(2):
            try:
                data = _fetch_cloud_runtime_payload(bearer=bearer, admin_key=deploy_key)
                last_cloud_status = _cloud_doubao_key_status(data)
                apply_cloud_payload_to_local(data)
                if last_cloud_status == "ok":
                    break
            except Exception as e:
                logger.warning(
                    "ensure_runtime_secrets_ready pull attempt %s failed: %s",
                    attempt + 1,
                    e,
                )
                if attempt == 1:
                    resolved = resolve_runtime_secret("data_analysis", "doubao_api_key")
                    if resolved and not is_masked_secret(resolved):
                        return True, "ok"
                    return False, "pull_failed"

    resolved = resolve_runtime_secret("data_analysis", "doubao_api_key")
    if resolved and not is_masked_secret(resolved):
        return True, "ok"

    if last_cloud_status in ("cloud_key_masked", "cloud_empty"):
        return False, last_cloud_status
    if not deploy_key or deploy_key in ("change-me-admin", "change-me"):
        return False, "no_deploy_admin"
    return False, "generic"

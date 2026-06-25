# -*- coding: utf-8 -*-
"""云端管理员运行时配置（API Key / 模型 / 积分单价）— 云端 DB 权威，桌面端 JSON 镜像。"""
from __future__ import annotations

import json
import os
import time
from typing import Any, Dict, Optional

from app.core.admin_runtime_config import (
    AI_IMAGE_GEN_ADMIN_KEYS,
    DATA_ANALYSIS_ADMIN_KEYS,
    should_skip_runtime_secret_merge,
)
from app.core.settings import DATA_DIR
from app.services.app_runtime_settings_service import (
    POINTS_PRICING_KEYS,
    _default_points_pricing_dict,
    _pick_points_pricing,
    _pick_section,
    get_app_runtime_revision,
    load_app_runtime_settings,
    save_app_runtime_settings,
)

RUNTIME_CONFIG_FILE = os.path.join(DATA_DIR, "admin_runtime_config.json")


def _is_cloud_host() -> bool:
    from app.services.membership_service import _is_cloud_membership_host

    return _is_cloud_membership_host()


def _empty_payload() -> Dict[str, Any]:
    return {
        "revision": 0,
        "updated_at": "",
        "updated_by": "",
        "data_analysis": {},
        "ai_image_gen": {},
        "points_pricing": _default_points_pricing_dict(),
    }


def _load_local_json_runtime() -> Dict[str, Any]:
    if not os.path.isfile(RUNTIME_CONFIG_FILE):
        return _empty_payload()
    try:
        with open(RUNTIME_CONFIG_FILE, "r", encoding="utf-8-sig") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return _empty_payload()
        out = _empty_payload()
        out["revision"] = int(data.get("revision") or 0)
        out["updated_at"] = str(data.get("updated_at") or "")
        out["updated_by"] = str(data.get("updated_by") or "")
        out["data_analysis"] = _pick_section(data.get("data_analysis"), DATA_ANALYSIS_ADMIN_KEYS)
        out["ai_image_gen"] = _pick_section(data.get("ai_image_gen"), AI_IMAGE_GEN_ADMIN_KEYS)
        pp = _pick_points_pricing(data.get("points_pricing"))
        if pp:
            out["points_pricing"] = {**out["points_pricing"], **pp}
        return out
    except Exception:
        return _empty_payload()


def _save_local_json_runtime(payload: Dict[str, Any]) -> Dict[str, Any]:
    os.makedirs(DATA_DIR, exist_ok=True)
    body = {
        "revision": int(payload.get("revision") or int(time.time())),
        "updated_at": str(payload.get("updated_at") or time.strftime("%Y-%m-%d %H:%M:%S")),
        "updated_by": str(payload.get("updated_by") or ""),
        "data_analysis": dict(payload.get("data_analysis") or {}),
        "ai_image_gen": dict(payload.get("ai_image_gen") or {}),
        "points_pricing": dict(payload.get("points_pricing") or _default_points_pricing_dict()),
    }
    with open(RUNTIME_CONFIG_FILE, "w", encoding="utf-8", newline="\n") as f:
        json.dump(body, f, ensure_ascii=False, indent=2)
        f.write("\n")
    return body


def load_cloud_admin_runtime() -> Dict[str, Any]:
    if _is_cloud_host():
        return load_app_runtime_settings()
    return _load_local_json_runtime()


def save_cloud_admin_runtime(
    data_analysis: Optional[Dict[str, Any]] = None,
    ai_image_gen: Optional[Dict[str, Any]] = None,
    points_pricing: Optional[Dict[str, Any]] = None,
    *,
    merge: bool = True,
    updated_by: str = "",
) -> Dict[str, Any]:
    if _is_cloud_host():
        return save_app_runtime_settings(
            data_analysis=data_analysis,
            ai_image_gen=ai_image_gen,
            points_pricing=points_pricing,
            merge=merge,
            updated_by=updated_by,
        )

    current = _load_local_json_runtime() if merge else _empty_payload()
    if isinstance(data_analysis, dict):
        da = dict(current.get("data_analysis") or {})
        for k, v in _pick_section(data_analysis, DATA_ANALYSIS_ADMIN_KEYS).items():
            if should_skip_runtime_secret_merge(k, v, da.get(k)):
                continue
            da[k] = v
        current["data_analysis"] = da
    if isinstance(ai_image_gen, dict):
        ai = dict(current.get("ai_image_gen") or {})
        for k, v in _pick_section(ai_image_gen, AI_IMAGE_GEN_ADMIN_KEYS).items():
            if should_skip_runtime_secret_merge(k, v, ai.get(k)):
                continue
            ai[k] = v
        current["ai_image_gen"] = ai
    if isinstance(points_pricing, dict):
        pp = dict(current.get("points_pricing") or _default_points_pricing_dict())
        pp.update(_pick_points_pricing(points_pricing))
        current["points_pricing"] = pp
    current["revision"] = int(time.time())
    current["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    if updated_by:
        current["updated_by"] = updated_by
    return _save_local_json_runtime(current)


def get_cloud_admin_runtime_revision() -> int:
    if _is_cloud_host():
        return get_app_runtime_revision()
    return int(_load_local_json_runtime().get("revision") or 0)

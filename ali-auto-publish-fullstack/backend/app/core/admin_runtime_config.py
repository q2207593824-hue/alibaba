# -*- coding: utf-8 -*-
"""管理员运行时配置（API Key / 模型等）— 供多客户端同步。"""
from __future__ import annotations

import os
from typing import Any, Dict, Optional

from app.core.settings import CONFIG_FILE, get_config

_MASK = "***"

# 流量分析 / 产品优化建议 共用的豆包配置
DATA_ANALYSIS_ADMIN_KEYS = ("doubao_api_key", "doubao_model_name")

# 写入本机 config 时需跳过的脱敏/占位密钥
RUNTIME_SECRET_FIELDS: dict[str, tuple[str, ...]] = {
    "data_analysis": ("doubao_api_key",),
    "ai_image_gen": ("gemini_api_key", "doubao_api_key"),
}

# AI 生图：除普通用户可改字段外的全部管理员配置
AI_IMAGE_GEN_ADMIN_KEYS = (
    "gemini_api_key",
    "gemini_base_url",
    "gemini_model",
    "concurrent_workers",
    "prompt_workers",
    "resize_max_edge",
    "jpeg_quality",
    "global_gemini_pool",
    "use_stream",
    "max_retries",
    "retry_delay",
    "request_interval",
    "skip_existing",
    "prompt_source_priority",
    "prompt_templates",
    "doubao_planner_prompt",
    "doubao_enabled",
    "doubao_api_key",
    "doubao_model",
    "doubao_base_url",
    "doubao_use_official_sdk",
    "doubao_ep_file",
    "doubao_probe_on_startup",
    "doubao_probe_strict",
    "doubao_output_language",
    "cache_prompts",
    "use_cached_prompts",
    "force_refresh",
    "doubao_max_retries",
    "doubao_retry_delay",
)


def get_config_revision() -> int:
    """配置文件 revision（mtime 秒级时间戳）。"""
    try:
        return int(os.path.getmtime(CONFIG_FILE))
    except Exception:
        return 0


def _mask_key(value: Any) -> str:
    raw = str(value or "").strip()
    return _MASK if raw else ""


def is_masked_secret(value: Any) -> bool:
    """判断是否为脱敏占位（不可用于 API 调用或写入本机 config）。"""
    s = str(value or "").strip()
    if not s:
        return False
    if s == _MASK or s.startswith("***"):
        return True
    # 前端 maskSecret 形态：前2 + 全* + 后2
    if len(s) > 4 and s[2:-2] and not s[2:-2].replace("*", ""):
        return True
    return False


def should_skip_runtime_secret_merge(key: str, incoming: Any, current: Any) -> bool:
    """云端/浏览器同步时，禁止用脱敏或空值覆盖本机已有密钥。"""
    if key not in sum(RUNTIME_SECRET_FIELDS.values(), ()):
        return False
    inc = str(incoming or "").strip()
    cur = str(current or "").strip()
    if not inc:
        return bool(cur)
    if is_masked_secret(inc):
        return True
    return False


def resolve_runtime_secret(section: str, field: str) -> str:
    """
    解析管理员运行时密钥：优先本机 config.json，脱敏时回退 admin_runtime_config.json。
    若回退成功且 config 中为脱敏占位，则自动修复本机 config。
    """
    from app.core.settings import config_manager

    cfg = config_manager.reload_from_disk()
    sec = getattr(cfg, section, None)
    val = str(getattr(sec, field, "") or "").strip()
    if val and not is_masked_secret(val):
        return val

    try:
        from app.services.cloud_admin_runtime_service import load_cloud_admin_runtime

        backup = load_cloud_admin_runtime()
        sec_backup = backup.get(section) if isinstance(backup.get(section), dict) else {}
        fallback = str(sec_backup.get(field) or "").strip()
    except Exception:
        fallback = ""

    if fallback and not is_masked_secret(fallback):
        try:
            data = cfg.model_dump()
            sec_data = dict(data.get(section) or {})
            if str(sec_data.get(field) or "").strip() != fallback:
                sec_data[field] = fallback
                data[section] = sec_data
                config_manager.update_full(data)
        except Exception:
            pass
        return fallback
    return ""


def _pick(section: Dict[str, Any], keys: tuple[str, ...]) -> Dict[str, Any]:
    return {k: section.get(k) for k in keys if k in section}


def build_admin_runtime_payload(*, full_access: bool = False) -> Dict[str, Any]:
    """返回运行时配置；暂不对 API Key 脱敏，便于桌面端/会员同步完整密钥。"""
    cfg = get_config()
    da = cfg.data_analysis.model_dump()
    ai = cfg.ai_image_gen.model_dump()

    da_out = _pick(da, DATA_ANALYSIS_ADMIN_KEYS)
    ai_out = _pick(ai, AI_IMAGE_GEN_ADMIN_KEYS)

    return {
        "revision": get_config_revision(),
        "data_analysis": da_out,
        "ai_image_gen": ai_out,
    }


def merge_runtime_secrets_on_save(
    incoming: Dict[str, Any],
    *,
    section: str,
) -> Dict[str, Any]:
    """保存时禁止用脱敏占位（*** / sk**xx）覆盖真实密钥。"""
    sec_in = incoming.get(section)
    secret_fields = RUNTIME_SECRET_FIELDS.get(section)
    if not secret_fields or not isinstance(sec_in, dict):
        return incoming

    cfg = get_config()
    current = getattr(cfg, section).model_dump()
    merged = {**current, **sec_in}

    for field in secret_fields:
        if field not in sec_in:
            continue
        inc = str(sec_in.get(field) or "").strip()
        cur = str(current.get(field) or "").strip()
        if is_masked_secret(inc):
            merged[field] = cur if cur and not is_masked_secret(cur) else ""
        elif not inc and cur and not is_masked_secret(cur):
            merged[field] = cur

    incoming = {**incoming, section: merged}
    return incoming


def purge_masked_runtime_secrets_from_local() -> bool:
    """清除本机 config / admin_runtime 镜像中的脱敏占位，便于后续云端 pull 写入真实 Key。"""
    from app.core.settings import config_manager

    changed = False
    cfg = config_manager.reload_from_disk()
    data = cfg.model_dump()

    for section, fields in RUNTIME_SECRET_FIELDS.items():
        sec = dict(data.get(section) or {})
        sec_changed = False
        for field in fields:
            if is_masked_secret(sec.get(field)):
                sec[field] = ""
                sec_changed = True
        if sec_changed:
            data[section] = sec
            changed = True

    if changed:
        config_manager.update_full(data)

    try:
        from app.services.cloud_admin_runtime_service import load_cloud_admin_runtime, save_cloud_admin_runtime

        backup = load_cloud_admin_runtime()
        backup_changed = False
        for section, fields in RUNTIME_SECRET_FIELDS.items():
            sec = dict(backup.get(section) or {})
            sec_changed = False
            for field in fields:
                if is_masked_secret(sec.get(field)):
                    sec[field] = ""
                    sec_changed = True
            if sec_changed:
                backup[section] = sec
                backup_changed = True
        if backup_changed:
            save_cloud_admin_runtime(
                data_analysis=backup.get("data_analysis") if isinstance(backup.get("data_analysis"), dict) else None,
                ai_image_gen=backup.get("ai_image_gen") if isinstance(backup.get("ai_image_gen"), dict) else None,
                merge=True,
            )
            changed = True
    except Exception:
        pass

    return changed


def merge_admin_runtime_on_save(
    incoming: Dict[str, Any],
    *,
    full_access: bool,
    section: str,
) -> Dict[str, Any]:
    incoming = merge_runtime_secrets_on_save(incoming, section=section)

    if full_access or section not in incoming or not isinstance(incoming.get(section), dict):
        return incoming

    cfg = get_config()
    current = getattr(cfg, section).model_dump()
    patch = dict(incoming[section])

    if section == "data_analysis":
        admin_keys = DATA_ANALYSIS_ADMIN_KEYS
    elif section == "ai_image_gen":
        admin_keys = AI_IMAGE_GEN_ADMIN_KEYS
    else:
        return incoming

    for k in admin_keys:
        patch.pop(k, None)

    incoming = {**incoming, section: {**current, **patch}}
    return incoming


_PAYMENT_SECRET_KEYS = (
    "admin_api_key",
    "admin_console_password",
    "admin_console_username",
    "wechat_secret",
    "alipay_secret",
)

_PAYMENT_PLACEHOLDERS = {
    "admin_api_key": "change-me-admin",
    "admin_console_password": "change-me-owner-pass",
    "wechat_secret": "change-me-wechat",
    "alipay_secret": "change-me-alipay",
}


def mask_full_config_dump(data: Dict[str, Any], *, full_access: bool) -> Dict[str, Any]:
    """暂不对 data_analysis / ai_image_gen 的 API Key 脱敏，保证会员端能同步并跑通任务。"""
    if not isinstance(data, dict):
        return data
    return dict(data)


def merge_payment_on_save(incoming: Dict[str, Any], *, full_access: bool) -> Dict[str, Any]:
    """全量保存时，禁止用浏览器旧缓存里的占位符覆盖已配置的真实 payment 密钥。"""
    payment_in = incoming.get("payment")
    if not isinstance(payment_in, dict):
        return incoming

    cfg = get_config()
    current = cfg.payment.model_dump()
    merged = {**current, **payment_in}

    if full_access:
        incoming = {**incoming, "payment": merged}
        return incoming

    for key in _PAYMENT_SECRET_KEYS:
        placeholder = _PAYMENT_PLACEHOLDERS.get(key, "")
        incoming_val = str(payment_in.get(key) or "").strip()
        current_val = str(current.get(key) or "").strip()
        if (
            placeholder
            and incoming_val == placeholder
            and current_val
            and current_val != placeholder
        ):
            merged[key] = current_val

    incoming = {**incoming, "payment": merged}
    return incoming

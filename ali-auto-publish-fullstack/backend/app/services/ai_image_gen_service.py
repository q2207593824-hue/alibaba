# -*- coding: utf-8 -*-
"""AI 批量生图服务 — 使用内嵌 ai_image_batch_engine（完整原脚本逻辑）。"""
from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

from app.core.admin_runtime_config import is_masked_secret, resolve_runtime_secret
from app.core.logger import setup_logger
from app.core.settings import config_manager, get_config
from app.core.task_manager import TaskInfo
from app.services import ai_image_batch_engine as engine
from app.services.membership_service import (
    check_ai_image_points_sufficient,
    deduct_ai_image_generation_points,
    get_ai_image_points_cost,
    get_points_pricing_snapshot,
)

logger = setup_logger("ai_image_gen")

BASIC_AI_GEN_KEYS = frozenset({
    "input_root_dir",
    "generations_per_image",
    "aspect_ratio",
    "image_size",
    "user_requirement",
    "sku_generations_count",
    "sku_names",
})

engine.set_external_log_fn(lambda msg: logger.info(msg))

_MASK_KEYS = ("gemini_api_key", "doubao_api_key")


def _cfg():
    return get_config().ai_image_gen


def _mask_config(data: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(data)
    for k in _MASK_KEYS:
        if out.get(k):
            out[k] = "***"
    return out


def get_ai_image_gen_config() -> Dict[str, Any]:
    config_manager.reload_from_disk()
    data = _cfg().model_dump()
    if not (data.get("doubao_planner_prompt") or "").strip():
        data["doubao_planner_prompt"] = engine.DOUBAO_PLANNER_PROMPT
    return data


def save_ai_image_gen_config(payload: Dict[str, Any], *, full_access: bool = True) -> Dict[str, Any]:
    config_manager.reload_from_disk()
    cfg = config_manager.config
    current = cfg.ai_image_gen.model_dump()
    incoming = payload or {}
    if not full_access:
        incoming = {k: v for k, v in incoming.items() if k in BASIC_AI_GEN_KEYS}
    for k, v in incoming.items():
        if k not in current:
            continue
        if k in _MASK_KEYS and (not str(v or "").strip() or is_masked_secret(v)):
            continue
        current[k] = v
    cfg.ai_image_gen = cfg.ai_image_gen.__class__(**current)
    config_manager.save()
    if full_access:
        try:
            from app.services.admin_runtime_cloud_sync import push_local_admin_runtime_to_cloud
            from app.services.membership_service import _get_cloud_admin_key

            push_local_admin_runtime_to_cloud(admin_key=_get_cloud_admin_key())
        except Exception as e:
            logger.warning("push ai_image_gen admin config to cloud failed: %s", e)
    return get_ai_image_gen_config()


def _resolve_ep_file(cfg) -> str:
    ep_file = (cfg.doubao_ep_file or "").strip()
    if ep_file and os.path.isfile(ep_file):
        return ep_file
    engine_dir = os.path.dirname(os.path.abspath(engine.__file__))
    for name in ("doubao_ep.txt", "doubao_ep.txt.example"):
        candidate = os.path.join(engine_dir, name)
        if os.path.isfile(candidate):
            return candidate
    legacy = r"D:\桌面\工厂图片调用API\doubao_ep.txt"
    if os.path.isfile(legacy):
        return legacy
    return ep_file


def apply_engine_config() -> None:
    cfg = _cfg()
    da = get_config().data_analysis
    gemini_key = resolve_runtime_secret("ai_image_gen", "gemini_api_key") or (cfg.gemini_api_key or os.getenv("GEMINI_API_KEY", "")).strip()
    doubao_key = (
        resolve_runtime_secret("ai_image_gen", "doubao_api_key")
        or resolve_runtime_secret("data_analysis", "doubao_api_key")
        or cfg.doubao_api_key
        or da.doubao_api_key
        or os.getenv("ARK_API_KEY", "")
    ).strip()
    ep_file = _resolve_ep_file(cfg)

    planner = (cfg.doubao_planner_prompt or "").strip() or engine.DOUBAO_PLANNER_PROMPT
    engine.DOUBAO_PLANNER_PROMPT = planner
    engine.PROMPT_TEMPLATES = list(cfg.prompt_templates or [])

    engine.CONFIG.update({
        "API_KEY": gemini_key,
        "MODEL": cfg.gemini_model,
        "BASE_URL": cfg.gemini_base_url.rstrip("/"),
        "INPUT_ROOT_DIR": cfg.input_root_dir,
        "OUTPUT_ROOT_DIR": cfg.output_root_dir,
        "GENERATIONS_PER_IMAGE": int(cfg.generations_per_image),
        "ASPECT_RATIO": cfg.aspect_ratio,
        "IMAGE_SIZE": cfg.image_size,
        "CONCURRENT_WORKERS": int(cfg.concurrent_workers),
        "PROMPT_WORKERS": int(cfg.prompt_workers),
        "RESIZE_MAX_EDGE": int(cfg.resize_max_edge),
        "JPEG_QUALITY": int(cfg.jpeg_quality),
        "GLOBAL_GEMINI_POOL": bool(cfg.global_gemini_pool),
        "USE_STREAM": bool(cfg.use_stream),
        "MAX_RETRIES": int(cfg.max_retries),
        "RETRY_DELAY": int(cfg.retry_delay),
        "REQUEST_INTERVAL": int(cfg.request_interval),
        "SKIP_EXISTING": bool(cfg.skip_existing),
        "PROMPT_SOURCE_PRIORITY": list(cfg.prompt_source_priority or ["cache", "doubao", "txt"]),
        "SKU_GENERATIONS_COUNT": max(0, int(cfg.sku_generations_count or 0)),
        "SKU_NAMES": [str(n).strip() for n in (cfg.sku_names or []) if str(n).strip()],
    })
    engine.CONFIG["DOUBAO"] = {
        **engine.CONFIG.get("DOUBAO", {}),
        "ENABLED": bool(cfg.doubao_enabled),
        "API_KEY": doubao_key,
        "BASE_URL": cfg.doubao_base_url.rstrip("/"),
        "MODEL": cfg.doubao_model,
        "USE_OFFICIAL_SDK": bool(cfg.doubao_use_official_sdk),
        "EP_FILE": os.path.basename(ep_file) if ep_file else "doubao_ep.txt",
        "PROBE_ON_STARTUP": bool(cfg.doubao_probe_on_startup),
        "PROBE_STRICT": bool(cfg.doubao_probe_strict),
        "OUTPUT_LANGUAGE": cfg.doubao_output_language or "English",
        "USER_REQUIREMENT": cfg.user_requirement or "",
        "CACHE_PROMPTS": bool(cfg.cache_prompts),
        "USE_CACHED_PROMPTS": bool(cfg.use_cached_prompts),
        "FORCE_REFRESH": bool(cfg.force_refresh),
        "MAX_RETRIES": int(cfg.doubao_max_retries),
        "RETRY_DELAY": int(cfg.doubao_retry_delay),
    }
    if ep_file and os.path.isfile(ep_file):
        engine.CONFIG["DOUBAO"]["_EP_FILE_ABSPATH"] = ep_file

    paths = get_config().paths
    engine.CONFIG["DELIVERY"] = {
        "primary_image_dir": (paths.primary_image_dir or "").strip(),
        "main_image_dir": (paths.main_image_dir or "").strip(),
        "title_excel_path": (paths.title_excel_path or "").strip(),
    }


def scan_input_products() -> List[Dict[str, Any]]:
    root = (_cfg().input_root_dir or "").strip()
    if not root or not os.path.isdir(root):
        return []

    items: List[Dict[str, Any]] = []
    for dirpath, _, files in os.walk(root):
        images = [f for f in files if f.lower().endswith((".png", ".jpg", ".jpeg"))]
        if not images:
            continue
        rel = os.path.relpath(dirpath, root)
        folder_label = root if rel == "." else os.path.join(root, rel)
        txt_files = [f for f in files if f.lower().endswith(".txt")]
        for img in sorted(images):
            base = os.path.splitext(img)[0]
            cache = f"{base}_prompts.json"
            cache_path = os.path.join(dirpath, cache)
            items.append({
                "folder": folder_label,
                "folder_rel": rel if rel != "." else "",
                "image": img,
                "image_path": os.path.join(dirpath, img),
                "has_txt": bool(txt_files),
                "has_prompt_cache": os.path.isfile(cache_path),
                "prompt_cache_path": cache_path if os.path.isfile(cache_path) else "",
            })
    return items


def get_prompt_cache(image_path: str) -> Dict[str, Any]:
    if not image_path or not os.path.isfile(image_path):
        raise FileNotFoundError("原图不存在")
    root = os.path.dirname(image_path)
    base = os.path.splitext(os.path.basename(image_path))[0]
    cache_path = os.path.join(root, f"{base}_prompts.json")
    if not os.path.isfile(cache_path):
        return {"path": cache_path, "exists": False, "data": None}
    with open(cache_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return {"path": cache_path, "exists": True, "data": data}


def get_ai_image_points_pricing() -> Dict[str, Any]:
    snap = get_points_pricing_snapshot()
    return {
        "cost_per_size": snap.get("ai_image_cost_per_size") or {},
        "title_optimize_per_item": snap.get("title_optimize_per_item"),
        "traffic_ai_per_run": snap.get("traffic_ai_per_run"),
        "note": "每张成功生成的图片按所选画质扣费；跳过已存在文件不扣费",
    }


def estimate_ai_image_gen_points(
    image_count: int, image_size: str, user_id: int, *, token: str = ""
) -> Dict[str, Any]:
    return check_ai_image_points_sufficient(
        user_id, max(0, int(image_count)), image_size, token=token
    )


def count_planned_ai_gen_images() -> int:
    """预估将尝试生成的张数（不含 SKIP_EXISTING 已存在文件）。"""
    root = (_cfg().input_root_dir or "").strip()
    if not root or not os.path.isdir(root):
        return 0
    gen_per = max(1, int(_cfg().generations_per_image or 1))
    sku_per = max(0, int(_cfg().sku_generations_count or 0))
    per_product = gen_per + sku_per
    total = 0
    for _, _, files in os.walk(root):
        images = [f for f in files if f.lower().endswith((".png", ".jpg", ".jpeg"))]
        if images:
            total += len(images) * per_product
    return total


def configure_points_billing(user_id: int, *, skip: bool = False, token: str = "") -> None:
    if skip or not user_id:
        engine.set_points_charge_fn(None)
        return
    image_size = (_cfg().image_size or "1K").strip()
    billing_token = str(token or "").strip()

    def _charge(label: str) -> None:
        deduct_ai_image_generation_points(
            user_id, image_size, biz_id=label or None, token=billing_token
        )

    engine.set_points_charge_fn(_charge)


def publish_dirs_ready() -> bool:
    paths = get_config().paths
    return bool((paths.primary_image_dir or "").strip() and (paths.main_image_dir or "").strip())


def get_ai_gen_gallery_source_label() -> str:
    """生成结果列表实际扫描的目录说明（供前端展示）。"""
    paths = get_config().paths
    primary = (paths.primary_image_dir or "").strip()
    main = (paths.main_image_dir or "").strip()
    if primary and main:
        return f"发品目录：首图 {primary}；主图 {main}"
    missing = []
    if not primary:
        missing.append("首图文件夹")
    if not main:
        missing.append("主图文件夹")
    return f"未配置发品目录（请在配置管理 → 路径配置中设置：{'、'.join(missing)}）"


def scan_output_gallery(product: Optional[str] = None) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    seen: set[str] = set()

    def _append(product_name: str, path: str) -> None:
        norm = os.path.normcase(os.path.abspath(path))
        if norm in seen or not os.path.isfile(path):
            return
        seen.add(norm)
        out.append({
            "product": product_name,
            "filename": os.path.basename(path),
            "path": path,
            "size": os.path.getsize(path),
        })

    paths = get_config().paths
    primary_dir = (paths.primary_image_dir or "").strip()
    main_dir = (paths.main_image_dir or "").strip()

    if primary_dir and os.path.isdir(primary_dir):
        for name in sorted(os.listdir(primary_dir)):
            if name.lower().endswith((".png", ".jpg", ".jpeg")):
                _append("首图", os.path.join(primary_dir, name))

    if main_dir and os.path.isdir(main_dir):
        for folder in sorted(os.listdir(main_dir)):
            sub = os.path.join(main_dir, folder)
            if not os.path.isdir(sub):
                continue
            if product and folder != product:
                continue
            for name in sorted(os.listdir(sub)):
                if name.lower().endswith((".png", ".jpg", ".jpeg")):
                    _append(folder, os.path.join(sub, name))
            sku_dir = os.path.join(sub, "SKU")
            if os.path.isdir(sku_dir):
                for name in sorted(os.listdir(sku_dir)):
                    if name.lower().endswith((".png", ".jpg", ".jpeg")):
                        _append(f"{folder}/SKU", os.path.join(sku_dir, name))

    return out


def run_ai_image_gen_task(task: TaskInfo, user_id: int = 0, skip_points: bool = False, token: str = ""):
    def _task_log(msg: str) -> None:
        text = str(msg or "").strip()
        if not text:
            return
        logger.info(text)
        task.current_step = text[:240]
        if "[阶段1]" in text:
            task.progress = max(task.progress, 15)
        elif "[阶段2]" in text or "[出图]" in text:
            task.progress = max(task.progress, 30)
        elif "[生成]" in text:
            task.progress = max(task.progress, 40)
        elif "[成功]" in text:
            task.progress = min(95, max(task.progress, 40) + 2)
        elif "[总计]" in text or "[完成]" in text:
            task.progress = 100

    engine.set_external_log_fn(_task_log)
    task.current_step = "加载 AI 生图引擎..."
    task.total = 100
    task.progress = 0

    try:
        apply_engine_config()
        configure_points_billing(int(user_id or 0), skip=bool(skip_points), token=token)

        input_root = (_cfg().input_root_dir or "").strip()
        if not input_root or not os.path.isdir(input_root):
            raise ValueError(f"原图目录不存在: {input_root}")
        if not publish_dirs_ready():
            raise ValueError(
                "请先在「配置管理 → 路径配置」中设置首图文件夹与主图文件夹；"
                "生成图将直接保存到发品目录，不再使用单独的输出目录。"
            )

        if not (_cfg().gemini_api_key or os.getenv("GEMINI_API_KEY", "")).strip():
            raise ValueError("未配置 API Key，请在页面配置或设置环境变量 GEMINI_API_KEY")

        task.current_step = "校验豆包配置..."
        task.progress = 5
        if task.should_stop():
            return

        if _cfg().doubao_enabled:
            engine.validate_doubao_config()

        task.current_step = "扫描原图并批量生成..."
        task.progress = 10
        if task.should_stop():
            return

        if not skip_points and user_id:
            planned = count_planned_ai_gen_images()
            image_size = (_cfg().image_size or "1K").strip()
            check = check_ai_image_points_sufficient(int(user_id), planned, image_size, token=token)
            per = check.get("per_image_cost", get_ai_image_points_cost(image_size))
            if not check.get("sufficient"):
                raise ValueError(
                    f"积分不足：当前余额 {check.get('balance', 0)}，"
                    f"预计需 {check.get('whole_points_required', 0)} 积分（约 {planned} 张 × {per}/张）"
                )
            logger.info(
                f"积分预检通过：余额={check.get('balance')} 预计张数={planned} "
                f"画质={image_size} 单价={per}/张"
            )

        task.current_step = "执行批量生图"
        task.progress = 20
        gen_n = max(1, int(_cfg().generations_per_image or 1))
        sku_n = max(0, int(_cfg().sku_generations_count or 0))
        logger.info(
            f"AI 生图: 每张原图生成 {gen_n} 张主图"
            + (f" + {sku_n} 张 SKU 图" if sku_n > 0 else "")
            + f"（generations_per_image={gen_n}, sku_generations_count={sku_n}）"
        )
        engine.process_batch()
        task.progress = 100
        task.current_step = "AI 生图任务完成"
    finally:
        engine.set_external_log_fn(lambda msg: logger.info(msg))

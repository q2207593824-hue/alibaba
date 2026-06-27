# -*- coding: utf-8 -*-
"""
图片管理 API
对应前端: ImageManager 页面
对应原脚本: cs_图片命名规范化.py
"""
import os
from typing import Dict, List, Optional
from fastapi import APIRouter, HTTPException, UploadFile, File, Depends, Header
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.core.settings import get_config
from app.core.task_manager import task_manager, TaskStatus
from app.core.logger import logger
from app.core.logger import log_buffer
from app.core.membership_guard import require_membership_or_trial, extract_bearer
from app.services.membership_service import resolve_user_id_by_token

router = APIRouter(dependencies=[Depends(require_membership_or_trial)])

IMAGE_NORM_TASK_ID = "image_normalize"
AI_IMAGE_GEN_TASK_ID = "ai_image_gen"


def _ai_gen_full_config_access(x_admin_key: Optional[str] = None) -> bool:
    cfg = get_config()
    expected = (cfg.payment.admin_api_key or "").strip()
    return bool(expected and (x_admin_key or "").strip() == expected)


class ImageNormRequest(BaseModel):
    """图片规范化请求"""
    source_dirs: Optional[List[str]] = None


class AiImageGenConfigUpdate(BaseModel):
    gemini_api_key: Optional[str] = None
    gemini_base_url: Optional[str] = None
    gemini_model: Optional[str] = None
    input_root_dir: Optional[str] = None
    output_root_dir: Optional[str] = None
    generations_per_image: Optional[int] = None
    aspect_ratio: Optional[str] = None
    image_size: Optional[str] = None
    concurrent_workers: Optional[int] = None
    prompt_workers: Optional[int] = None
    resize_max_edge: Optional[int] = None
    jpeg_quality: Optional[int] = None
    global_gemini_pool: Optional[bool] = None
    use_stream: Optional[bool] = None
    max_retries: Optional[int] = None
    retry_delay: Optional[int] = None
    request_interval: Optional[int] = None
    skip_existing: Optional[bool] = None
    prompt_source_priority: Optional[List[str]] = None
    prompt_templates: Optional[List[str]] = None
    doubao_planner_prompt: Optional[str] = None
    user_requirement: Optional[str] = None
    doubao_enabled: Optional[bool] = None
    doubao_api_key: Optional[str] = None
    doubao_model: Optional[str] = None
    doubao_base_url: Optional[str] = None
    doubao_use_official_sdk: Optional[bool] = None
    doubao_ep_file: Optional[str] = None
    doubao_probe_on_startup: Optional[bool] = None
    doubao_probe_strict: Optional[bool] = None
    doubao_output_language: Optional[str] = None
    cache_prompts: Optional[bool] = None
    use_cached_prompts: Optional[bool] = None
    force_refresh: Optional[bool] = None
    doubao_max_retries: Optional[int] = None
    doubao_retry_delay: Optional[int] = None
    sku_generations_count: Optional[int] = None
    sku_names: Optional[List[str]] = None


@router.get("/groups")
async def list_image_groups():
    """获取所有图片分组"""
    from app.services.image_service import scan_image_groups
    try:
        groups = scan_image_groups()
        return {"success": True, "data": groups}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/group/{group_id}")
async def get_group_detail(group_id: str):
    """获取指定分组的图片详情"""
    from app.services.image_service import get_group_images
    try:
        images = get_group_images(group_id)
        return {"success": True, "data": images}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/file")
async def get_image_file(path: str):
    """读取单张图片（二进制）"""
    try:
        if not path:
            raise HTTPException(status_code=400, detail="path 不能为空")
        if not os.path.exists(path) or not os.path.isfile(path):
            raise HTTPException(status_code=404, detail="文件不存在")
        return FileResponse(path)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/config")
async def get_image_norm_config():
    """获取图片规范化配置"""
    from app.services.image_service import get_image_norm_config
    try:
        data = get_image_norm_config()
        return {"success": True, "data": data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/config")
async def update_image_norm_config(payload: Dict):
    """更新图片规范化配置"""
    from app.services.image_service import save_image_norm_config
    try:
        data = save_image_norm_config(payload)
        return {"success": True, "data": data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/normalize/start")
async def start_normalize(req: ImageNormRequest, _=Depends(require_membership_or_trial)):
    """启动图片命名规范化任务"""
    from app.services.image_service import run_normalize_task

    existing = task_manager.get_task(IMAGE_NORM_TASK_ID)
    if existing and existing.status == TaskStatus.RUNNING:
        raise HTTPException(status_code=409, detail="图片规范化任务正在运行中")

    task = task_manager.create_task(IMAGE_NORM_TASK_ID, "图片命名规范化")
    task_manager.start_task(IMAGE_NORM_TASK_ID, run_normalize_task, (req.source_dirs,))

    return {"success": True, "message": "图片规范化任务已启动", "task": task.to_dict()}


@router.get("/normalize/status")
async def get_normalize_status():
    """获取规范化任务状态"""
    task = task_manager.get_task(IMAGE_NORM_TASK_ID)
    if task:
        return {"success": True, "data": task.to_dict()}
    return {"success": True, "data": {"status": "idle"}}


@router.post("/normalize/stop")
async def stop_normalize():
    """停止图片规范化任务"""
    ok = task_manager.stop_task(IMAGE_NORM_TASK_ID)
    if not ok:
        task = task_manager.get_task(IMAGE_NORM_TASK_ID)
        if not task or task.status in (TaskStatus.IDLE, TaskStatus.COMPLETED, TaskStatus.FAILED):
            return {"success": True, "message": "任务未运行"}
        raise HTTPException(status_code=409, detail="任务当前状态不支持停止")
    return {"success": True, "message": "停止指令已发送"}


@router.get("/stats")
async def get_image_stats():
    """获取图片统计信息"""
    from app.services.image_service import get_image_statistics
    try:
        stats = get_image_statistics()
        return {"success": True, "data": stats}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/logs/recent")
async def get_recent_image_logs(limit: int = 500):
    """获取最近图片规范化相关日志（来自 WebSocket 日志缓冲区）。"""
    try:
        n = int(limit or 500)
        n = max(10, min(n, 2000))
        entries = log_buffer.get_recent(n)
        # 仅返回 image_service 的日志，避免弹窗被其他模块刷屏
        out = [e for e in entries if isinstance(e, dict) and str(e.get("module") or "") == "image_service"]
        return {"success": True, "data": {"items": out, "total": len(out)}}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/ai-gen/logs/recent")
async def get_ai_image_gen_recent_logs(limit: int = 200):
    """获取 AI 生图最近日志（WebSocket 不可用时的轮询兜底）。"""
    try:
        n = max(10, min(int(limit or 200), 500))
        entries = log_buffer.get_recent(n)
        out = [e for e in entries if isinstance(e, dict) and str(e.get("module") or "") == "ai_image_gen"]
        return {"success": True, "data": {"items": out, "total": len(out)}}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/ai-gen/config")
async def get_ai_image_gen_config(
    x_admin_key: Optional[str] = Header(default=None, alias="X-Admin-Key"),
):
    from app.services.ai_image_gen_service import get_ai_image_gen_config as _get, BASIC_AI_GEN_KEYS
    try:
        data = _get()
        if not _ai_gen_full_config_access(x_admin_key):
            data = {k: data.get(k) for k in BASIC_AI_GEN_KEYS}
        return {"success": True, "data": data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/ai-gen/config")
async def update_ai_image_gen_config(
    payload: AiImageGenConfigUpdate,
    x_admin_key: Optional[str] = Header(default=None, alias="X-Admin-Key"),
):
    from app.services.ai_image_gen_service import save_ai_image_gen_config
    try:
        body = payload.model_dump(exclude_none=True)
        for k in ("gemini_api_key", "doubao_api_key"):
            if body.get(k) == "***":
                body.pop(k, None)
        data = save_ai_image_gen_config(body, full_access=_ai_gen_full_config_access(x_admin_key))
        return {"success": True, "data": data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/ai-gen/inputs")
async def list_ai_gen_inputs():
    from app.services.ai_image_gen_service import scan_input_products
    try:
        return {"success": True, "data": scan_input_products()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/ai-gen/input-scenes")
async def get_ai_gen_input_scenes():
    """从原图目录的图片文件名中解析场景，统计每个场景的数量"""
    from app.services.ai_image_gen_service import scan_input_products
    from app.services.ai_image_batch_engine import _parse_filename_scene_price
    import os
    from collections import Counter
    try:
        items = scan_input_products()
        scene_counter = Counter()
        for item in items:
            base = os.path.splitext(item["image"])[0]
            _, scene, _ = _parse_filename_scene_price(base)
            if scene:
                scene_counter[scene] += 1
        if not scene_counter:
            return {"success": True, "data": {"scenes": [], "max_count": 1}}
        scenes = list(scene_counter.keys())
        max_count = max(scene_counter.values())
        return {
            "success": True,
            "data": {
                "scenes": scenes,
                "max_count": max_count,
                "scene_counts": dict(scene_counter),
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/ai-gen/outputs")
async def list_ai_gen_outputs(product: Optional[str] = None):
    from app.services.ai_image_gen_service import get_ai_gen_gallery_source_label, scan_output_gallery
    try:
        return {
            "success": True,
            "data": scan_output_gallery(product),
            "gallery_source": get_ai_gen_gallery_source_label(),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/ai-gen/prompts")
async def get_ai_gen_prompts(image_path: str):
    from app.services.ai_image_gen_service import get_prompt_cache
    try:
        return {"success": True, "data": get_prompt_cache(image_path)}
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/ai-gen/points-pricing")
async def get_ai_image_points_pricing():
    from app.services.ai_image_gen_service import get_ai_image_points_pricing

    return {"success": True, "data": get_ai_image_points_pricing()}


@router.get("/ai-gen/points-estimate")
async def estimate_ai_image_points(
    authorization: Optional[str] = Header(default=None),
    x_admin_key: Optional[str] = Header(default=None, alias="X-Admin-Key"),
):
    from app.services.ai_image_gen_service import count_planned_ai_gen_images, estimate_ai_image_gen_points
    from app.core.settings import get_config

    skip_points = _ai_gen_full_config_access(x_admin_key)
    if skip_points:
        return {
            "success": True,
            "data": {
                "skip_points": True,
                "planned_images": count_planned_ai_gen_images(),
                "image_size": (get_config().ai_image_gen.image_size or "1K"),
            },
        }

    token = extract_bearer(authorization)
    try:
        user_id = int(resolve_user_id_by_token(token))
    except Exception as e:
        raise HTTPException(status_code=401, detail=str(e) or "登录已失效，请重新登录")

    image_size = (get_config().ai_image_gen.image_size or "1K").strip()
    planned = count_planned_ai_gen_images()
    data = estimate_ai_image_gen_points(planned, image_size, user_id, token=token)
    data["skip_points"] = False
    data["planned_images"] = planned
    return {"success": True, "data": data}


@router.post("/ai-gen/start")
async def start_ai_image_gen(
    authorization: Optional[str] = Header(default=None),
    x_admin_key: Optional[str] = Header(default=None, alias="X-Admin-Key"),
    _=Depends(require_membership_or_trial),
):
    from app.services.ai_image_gen_service import run_ai_image_gen_task

    existing = task_manager.get_task(AI_IMAGE_GEN_TASK_ID)
    if existing and existing.status == TaskStatus.RUNNING:
        raise HTTPException(status_code=409, detail="AI 生图任务正在运行中")

    skip_points = _ai_gen_full_config_access(x_admin_key)
    user_id = 0
    token = ""
    if not skip_points:
        token = extract_bearer(authorization)
        try:
            user_id = int(resolve_user_id_by_token(token))
        except Exception as e:
            raise HTTPException(status_code=401, detail=str(e) or "登录已失效，请重新登录")

        from app.services.admin_runtime_cloud_sync import (
            ensure_runtime_secrets_ready_detail,
            runtime_secrets_unavailable_message,
        )

        ready, reason = ensure_runtime_secrets_ready_detail(
            bearer=token, admin_key=str(x_admin_key or "")
        )
        if not ready:
            raise HTTPException(
                status_code=400,
                detail=runtime_secrets_unavailable_message(reason),
            )

    task = task_manager.create_task(AI_IMAGE_GEN_TASK_ID, "AI 批量生图")
    task_manager.start_task(AI_IMAGE_GEN_TASK_ID, run_ai_image_gen_task, (user_id, skip_points, token))
    return {"success": True, "message": "AI 生图任务已启动", "task": task.to_dict()}


@router.get("/ai-gen/status")
async def get_ai_image_gen_status():
    task = task_manager.get_task(AI_IMAGE_GEN_TASK_ID)
    if task:
        return {"success": True, "data": task.to_dict()}
    return {"success": True, "data": {"status": "idle"}}


@router.post("/ai-gen/stop")
async def stop_ai_image_gen():
    ok = task_manager.stop_task(AI_IMAGE_GEN_TASK_ID)
    if not ok:
        task = task_manager.get_task(AI_IMAGE_GEN_TASK_ID)
        if not task or task.status in (TaskStatus.IDLE, TaskStatus.COMPLETED, TaskStatus.FAILED):
            return {"success": True, "message": "任务未运行"}
        raise HTTPException(status_code=409, detail="任务当前状态不支持停止")
    return {"success": True, "message": "停止指令已发送"}

# -*- coding: utf-8 -*-
"""
产品上传 API
对应前端: ProductUpload 页面
对应原脚本: main_属性融合.py
"""
from typing import Dict, Optional
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel

from app.core.task_manager import task_manager, TaskStatus
from app.core.logger import logger
from app.core.membership_guard import require_membership_or_trial

router = APIRouter(dependencies=[Depends(require_membership_or_trial)])

UPLOAD_TASK_ID = "product_upload"
OPTIMIZE_TASK_ID = "product_optimize_upload"


class UploadStartRequest(BaseModel):
    """启动上传请求"""
    mode: str = "batch"  # batch / single / scheduled
    max_products: Optional[int] = None
    scheduled_time: Optional[str] = None  # HH:MM，仅 mode=scheduled 时生效


class UploadResponse(BaseModel):
    success: bool
    message: str
    task: Optional[Dict] = None


class OptimizeStartRequest(BaseModel):
    manual_product_ids: Optional[str] = None  # 逗号分隔，可空


class OptimizeDeleteRequest(BaseModel):
    product_id: str
    optimize_date: Optional[str] = None


@router.post("/start")
async def start_upload(req: UploadStartRequest, _=Depends(require_membership_or_trial)):
    """启动自动发品任务"""
    from app.services.upload_service import run_upload_task

    existing = task_manager.get_task(UPLOAD_TASK_ID)
    if existing and existing.status == TaskStatus.RUNNING:
        raise HTTPException(status_code=409, detail="上传任务正在运行中")

    task = task_manager.create_task(UPLOAD_TASK_ID, "自动发品")
    task_manager.start_task(UPLOAD_TASK_ID, run_upload_task, (req.mode, req.max_products, req.scheduled_time))

    logger.info(f"自动发品任务已启动 - 模式: {req.mode}, 定时时间: {req.scheduled_time}")
    return UploadResponse(
        success=True,
        message="自动发品任务已启动",
        task=task.to_dict()
    )


@router.post("/stop")
async def stop_upload():
    """停止自动发品任务"""
    success = task_manager.stop_task(UPLOAD_TASK_ID)
    if success:
        logger.info("自动发品任务已停止")
        return UploadResponse(success=True, message="任务已停止")
    raise HTTPException(status_code=400, detail="没有正在运行的任务")


@router.post("/pause")
async def pause_upload():
    """暂停自动发品任务"""
    success = task_manager.pause_task(UPLOAD_TASK_ID)
    if success:
        return UploadResponse(success=True, message="任务已暂停")
    raise HTTPException(status_code=400, detail="任务无法暂停")


@router.post("/resume")
async def resume_upload():
    """恢复自动发品任务"""
    success = task_manager.resume_task(UPLOAD_TASK_ID)
    if success:
        return UploadResponse(success=True, message="任务已恢复")
    raise HTTPException(status_code=400, detail="任务无法恢复")


@router.get("/status")
async def get_upload_status():
    """获取上传任务状态"""
    from app.services.upload_service import get_title_excel_health

    title_health = get_title_excel_health()
    if task := task_manager.get_task(UPLOAD_TASK_ID):
        data = task.to_dict()
        data["title_excel_health"] = title_health
        return {"success": True, "data": data}
    return {"success": True, "data": {"status": "idle", "title_excel_health": title_health}}


@router.get("/products/available")
async def get_available_products():
    """获取可发布的产品列表"""
    from app.services.upload_service import get_available_products_list
    try:
        products = get_available_products_list()
        return {"success": True, "data": products}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/products/published")
async def get_published_products():
    """获取已发布的产品列表"""
    from app.services.upload_service import get_published_products_list
    try:
        products = get_published_products_list()
        return {"success": True, "data": products}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/optimize/start")
async def start_optimize_upload(req: OptimizeStartRequest, _=Depends(require_membership_or_trial)):
    """启动“优化产品”任务（独立功能，不影响自动发品）"""
    from app.services.optimize_product_service import run_optimize_product_task

    existing = task_manager.get_task(OPTIMIZE_TASK_ID)
    if existing and existing.status == TaskStatus.RUNNING:
        raise HTTPException(status_code=409, detail="优化产品任务正在运行中")

    manual_ids = []
    raw = str(req.manual_product_ids or "").strip()
    if raw:
        manual_ids = [x.strip() for x in raw.split(",") if x.strip()]

    task = task_manager.create_task(OPTIMIZE_TASK_ID, "优化产品")
    # 提前写一步，避免前端看起来“无反应”
    task.current_step = "任务已创建，等待执行"
    task_manager.start_task(OPTIMIZE_TASK_ID, run_optimize_product_task, (manual_ids,))

    return UploadResponse(success=True, message="优化产品任务已启动", task=task.to_dict())


@router.get("/optimize/list")
async def get_optimize_list(limit: int = 300):
    from app.services.optimize_product_service import get_optimize_list as _get_optimize_list
    try:
        data = _get_optimize_list(limit=limit)
        return {"success": True, "data": data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/optimize/failed-today")
async def get_optimize_failed_today():
    from app.services.optimize_product_service import get_today_failed_optimize_ids
    try:
        data = get_today_failed_optimize_ids()
        return {"success": True, "data": data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/optimize/delete")
async def delete_optimize_record(req: OptimizeDeleteRequest, _=Depends(require_membership_or_trial)):
    from app.services.optimize_product_service import delete_optimize_product_record
    try:
        data = delete_optimize_product_record(req.product_id, req.optimize_date)
        return {"success": True, "data": data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/optimize/stop")
async def stop_optimize_upload():
    success = task_manager.stop_task(OPTIMIZE_TASK_ID)
    if success:
        return UploadResponse(success=True, message="优化产品任务已停止")
    raise HTTPException(status_code=400, detail="没有正在运行的优化产品任务")


@router.get("/optimize/status")
async def get_optimize_upload_status():
    task = task_manager.get_task(OPTIMIZE_TASK_ID)
    if task:
        return {"success": True, "data": task.to_dict()}
    return {"success": True, "data": {"status": "idle"}}

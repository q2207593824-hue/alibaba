# -*- coding: utf-8 -*-
"""
新品绑定视频 API
对应前端: VideoBind 页面
"""
from typing import Dict, Optional
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel

from app.core.task_manager import task_manager, TaskStatus
from app.core.logger import logger
from app.core.membership_guard import require_membership_or_trial

router = APIRouter(dependencies=[Depends(require_membership_or_trial)])

VIDEO_BIND_TASK_ID = "video_bind"


class VideoBindStartRequest(BaseModel):
    """启动新品绑定视频请求"""
    video_per_product_limit: int = 10
    max_linked_count: int = 18


class VideoBindResponse(BaseModel):
    success: bool
    message: str
    task: Optional[Dict] = None


@router.post("/start")
async def start_video_bind(req: VideoBindStartRequest, _=Depends(require_membership_or_trial)):
    """启动新品绑定视频任务"""
    from app.services.video_bind_service import run_video_bind_task

    existing = task_manager.get_task(VIDEO_BIND_TASK_ID)
    if existing and existing.status == TaskStatus.RUNNING:
        raise HTTPException(status_code=409, detail="新品绑定视频任务正在运行中")

    task = task_manager.create_task(VIDEO_BIND_TASK_ID, "新品绑定视频")
    task_manager.start_task(
        VIDEO_BIND_TASK_ID,
        run_video_bind_task,
        (req.video_per_product_limit, req.max_linked_count),
    )

    logger.info(
        f"新品绑定视频任务已启动 - video_per_product_limit={req.video_per_product_limit}, max_linked_count={req.max_linked_count}"
    )
    return VideoBindResponse(success=True, message="新品绑定视频任务已启动", task=task.to_dict())


@router.post("/stop")
async def stop_video_bind():
    """停止新品绑定视频任务"""
    success = task_manager.stop_task(VIDEO_BIND_TASK_ID)
    if success:
        logger.info("新品绑定视频任务已停止")
        return VideoBindResponse(success=True, message="任务已停止")
    raise HTTPException(status_code=400, detail="没有正在运行的任务")


@router.post("/pause")
async def pause_video_bind():
    """暂停新品绑定视频任务"""
    success = task_manager.pause_task(VIDEO_BIND_TASK_ID)
    if success:
        return VideoBindResponse(success=True, message="任务已暂停")
    raise HTTPException(status_code=400, detail="任务无法暂停")


@router.post("/resume")
async def resume_video_bind():
    """恢复新品绑定视频任务"""
    success = task_manager.resume_task(VIDEO_BIND_TASK_ID)
    if success:
        return VideoBindResponse(success=True, message="任务已恢复")
    raise HTTPException(status_code=400, detail="任务无法恢复")


@router.get("/status")
async def get_video_bind_status():
    """获取新品绑定视频任务状态"""
    task = task_manager.get_task(VIDEO_BIND_TASK_ID)
    if task:
        return {"success": True, "data": task.to_dict()}
    return {"success": True, "data": {"status": "idle"}}


@router.get("/new-links-preview")
async def get_video_bind_new_links_preview(_=Depends(require_membership_or_trial)):
    """读取新品绑定视频将要处理的新发链接预览数据。"""
    from app.services.video_bind_service import load_new_links_for_video_bind
    try:
        data = load_new_links_for_video_bind()
        df = data.get("df")
        if df is None:
            return {"success": True, "data": {"rows": [], "source": "", "sheet_name": "", "id_col": "新发链接", "type_col": "类型", "bind_col": "绑定视频"}}

        rows = df.fillna("").to_dict(orient="records")
        return {
            "success": True,
            "data": {
                "rows": rows,
                "source": data.get("excel_path", ""),
                "sheet_name": data.get("sheet_name", ""),
                "id_col": (data.get("id_col") or "新发链接"),
                "type_col": "类型",
                "bind_col": (data.get("bind_col") or "绑定视频"),
            },
        }
    except FileNotFoundError:
        return {"success": True, "data": {"rows": [], "source": "", "sheet_name": "", "id_col": "新发链接", "type_col": "类型", "bind_col": "绑定视频"}}
    except ValueError as e:
        msg = str(e)
        if "不存在" in msg or "未配置" in msg:
            return {"success": True, "data": {"rows": [], "source": "", "sheet_name": "", "id_col": "新发链接", "type_col": "类型", "bind_col": "绑定视频", "warning": msg}}
        raise HTTPException(status_code=400, detail=msg)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

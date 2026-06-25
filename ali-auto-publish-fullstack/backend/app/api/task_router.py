# -*- coding: utf-8 -*-
"""
任务管理 API - 统一查看/管理所有后台任务
"""
from fastapi import APIRouter, HTTPException, Depends
from app.core.membership_guard import require_membership_or_trial

from app.core.task_manager import task_manager

router = APIRouter()


@router.get("/list")
async def list_all_tasks(_=Depends(require_membership_or_trial)):
    """获取所有任务状态"""
    tasks = task_manager.get_all_tasks()
    return {"success": True, "data": tasks}


@router.get("/{task_id}")
async def get_task_detail(task_id: str, _=Depends(require_membership_or_trial)):
    """获取指定任务详情"""
    task = task_manager.get_task(task_id)
    if task:
        return {"success": True, "data": task.to_dict()}
    raise HTTPException(status_code=404, detail=f"任务 '{task_id}' 不存在")


@router.post("/{task_id}/stop")
async def stop_task(task_id: str, _=Depends(require_membership_or_trial)):
    """停止指定任务"""
    success = task_manager.stop_task(task_id)
    if success:
        return {"success": True, "message": f"任务 '{task_id}' 已停止"}
    raise HTTPException(status_code=400, detail="任务无法停止")


@router.post("/{task_id}/pause")
async def pause_task(task_id: str, _=Depends(require_membership_or_trial)):
    """暂停指定任务"""
    success = task_manager.pause_task(task_id)
    if success:
        return {"success": True, "message": f"任务 '{task_id}' 已暂停"}
    raise HTTPException(status_code=400, detail="任务无法暂停")


@router.post("/{task_id}/resume")
async def resume_task(task_id: str, _=Depends(require_membership_or_trial)):
    """恢复指定任务"""
    success = task_manager.resume_task(task_id)
    if success:
        return {"success": True, "message": f"任务 '{task_id}' 已恢复"}
    raise HTTPException(status_code=400, detail="任务无法恢复")


@router.delete("/{task_id}")
async def remove_task(task_id: str, _=Depends(require_membership_or_trial)):
    """移除任务记录"""
    task_manager.remove_task(task_id)
    return {"success": True, "message": f"任务 '{task_id}' 已移除"}

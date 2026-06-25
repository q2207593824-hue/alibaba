# -*- coding: utf-8 -*-
"""发品页面元素扫描 API（独立工具，不影响自动发品流程）。"""
import asyncio
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.core.logger import logger
from app.core.membership_guard import require_membership_or_trial

router = APIRouter(dependencies=[Depends(require_membership_or_trial)])


class PageScanRequest(BaseModel):
    url: str = Field(..., description="要扫描的发品页面 URL")
    probe_buttons: bool = Field(True, description="是否探测式点击按钮以发现动态内容")
    wait_seconds: float = Field(30.0, ge=5.0, le=120.0, description="页面加载等待秒数")


class PageScanTarget(BaseModel):
    name: Optional[str] = Field(None, description="页面名称/标签")
    url: str = Field(..., description="发品页面 URL")


class PageScanBatchRequest(BaseModel):
    pages: List[PageScanTarget] = Field(..., min_length=1, max_length=20)
    probe_buttons: bool = Field(True, description="是否探测式点击按钮以发现动态内容")
    wait_seconds: float = Field(30.0, ge=5.0, le=120.0, description="每页加载等待秒数")


class ApplyScanToConfigRequest(BaseModel):
    group_name: str = Field(..., description="产品组别名（与首图文件名组别段一致）")
    url: str = Field(..., description="发品页 URL")
    workflows: List[dict] = Field(default_factory=list, description="功能地图 workflows")
    page_type: str = Field("", description="页面类型")
    page_type_label: str = Field("", description="页面类型中文")
    element_count: int = Field(0, description="元素数量")
    workflow_count: int = Field(0, description="功能地图项数")
    sync_platform: bool = Field(True, description="是否从平台同步属性/规格到 config")


@router.post("/scan")
async def scan_publish_page_endpoint(body: PageScanRequest):
    url = (body.url or "").strip()
    if not url.startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="请提供有效的 http(s) URL")

    from app.services.page_scanner import scan_publish_page

    logger.info(f"开始扫描发品页面: {url}")
    result = await asyncio.to_thread(
        scan_publish_page,
        url,
        probe_buttons=body.probe_buttons,
        wait_seconds=body.wait_seconds,
    )
    if not result.get("success"):
        status = 401 if result.get("needs_login") else 500
        raise HTTPException(status_code=status, detail=result.get("error") or "扫描失败")
    return {"success": True, "data": result}


@router.post("/scan-batch")
async def scan_publish_pages_batch_endpoint(body: PageScanBatchRequest):
    pages: List[dict] = []
    for item in body.pages:
        url = (item.url or "").strip()
        if not url.startswith(("http://", "https://")):
            raise HTTPException(status_code=400, detail=f"无效 URL: {url or '(空)'}")
        pages.append({"name": (item.name or "").strip(), "url": url})

    from app.services.page_scanner import scan_publish_pages_batch

    logger.info(f"开始批量扫描发品页面: {len(pages)} 个")
    result = await asyncio.to_thread(
        scan_publish_pages_batch,
        pages,
        probe_buttons=body.probe_buttons,
        wait_seconds=body.wait_seconds,
    )
    if not result.get("success"):
        if result.get("succeeded", 0) == 0 and any(p.get("needs_login") for p in result.get("pages", [])):
            raise HTTPException(status_code=401, detail=result.get("error") or "需要登录")
        if result.get("succeeded", 0) == 0:
            raise HTTPException(status_code=500, detail=result.get("error") or "批量扫描失败")
    return {"success": True, "data": result}


@router.post("/apply-to-config")
async def apply_scan_to_config_endpoint(body: ApplyScanToConfigRequest):
    """将扫描结果写入产品配置，对接自动发品。"""
    from app.services.page_scanner.config_bridge import apply_scan_to_config

    group = (body.group_name or "").strip()
    url = (body.url or "").strip()
    if not group:
        raise HTTPException(status_code=400, detail="请提供组别名称")
    if not url.startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="请提供有效的发品页 URL")

    logger.info(f"应用扫描到配置: group={group}")
    try:
        result = await asyncio.to_thread(
            apply_scan_to_config,
            group_name=group,
            url=url,
            workflows=body.workflows or [],
            page_type=body.page_type or "",
            page_type_label=body.page_type_label or "",
            element_count=body.element_count or 0,
            workflow_count=body.workflow_count or len(body.workflows or []),
            sync_platform=body.sync_platform,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("apply scan to config failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return {"success": True, "data": result}


@router.get("/validate-group/{group_name}")
async def validate_group_endpoint(group_name: str):
    """验收：检查组别是否已对接并可自动发品。"""
    from app.services.page_scanner.config_bridge import validate_group_for_publish

    result = validate_group_for_publish(group_name)
    return {"success": True, "data": result}

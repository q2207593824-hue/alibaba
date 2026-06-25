# -*- coding: utf-8 -*-
"""
数据下载 API
对应前端: DataDownload / KeywordDownload / StoreDataDownload 页面
对应原脚本: 后台数据下载/*.py
"""
import os
from typing import Optional
from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.core.task_manager import task_manager, TaskStatus
from app.core.logger import logger
from app.core.membership_guard import require_membership_or_trial

router = APIRouter(dependencies=[Depends(require_membership_or_trial)])


class DownloadStartRequest(BaseModel):
    """下载任务启动请求"""
    task_type: str  # product_ranking / daily_data / store_overview / keyword / product360 / product_operate
    date_range: Optional[str] = None
    period_type: Optional[str] = "week"
    # 行业关键词：允许前端直接传入本次要执行的关键词，避免仅依赖配置快照
    big_keywords: Optional[str] = None
    dropdown_keywords: Optional[str] = None


class Product360TrafficChannelsRequest(BaseModel):
    output_dir: Optional[str] = None
    product_ids: list[str] = []


class IndustryKeywordDeleteRequest(BaseModel):
    output_file: Optional[str] = None
    keywords: list[str] = []


class IndustryKeywordDropdownDeleteRequest(BaseModel):
    output_file: Optional[str] = None
    rows: list[dict] = []


class IndustryKeywordTitleGenerateRequest(BaseModel):
    mode: str  # industry_hot / dropdown
    scenes: str
    material: Optional[str] = None
    titles_per_scene: int = 10
    keywords: list[str] = []
    output_file: Optional[str] = None
    dropdown_output_file: Optional[str] = None


@router.post("/download/start")
async def start_download(req: DownloadStartRequest, _=Depends(require_membership_or_trial)):
    """启动数据下载任务"""
    from app.services.data_download_service import run_download_task

    task_id = f"download_{req.task_type}"
    existing = task_manager.get_task(task_id)
    if existing and existing.status == TaskStatus.RUNNING:
        raise HTTPException(status_code=409, detail=f"下载任务 {req.task_type} 正在运行中")

    task_name_map = {
        "product360": "产品360数据下载",
        "product360_crawler": "产品360-数据采集",
        "product360_parser": "产品360-数据解析",
        "product_ranking": "产品参谋-排名/访客/渠道下载",
        "daily_data": "产品参谋-日数据下载",
        "store_overview": "数据概览-店铺数据接口下载",
        "traffic_channel": "流量渠道下载",
        "product_operate": "产品运营下载",
        "store_image_collect": "店铺图片采集",
        "keyword": "选词参谋-关键词下载",
        "keyword_crawler": "选词参谋-关键词下载并分析",
        "keyword_parser": "选词参谋-关键词下载并分析",
        "industry_keyword": "行业关键词下载与整合",
        "industry_keyword_dropdown": "行业关键词-下拉词下载",
    }
    task_name = task_name_map.get(req.task_type, req.task_type)
    task = task_manager.create_task(task_id, task_name)
    download_options = {
        k: v
        for k, v in {
            "big_keywords": req.big_keywords,
            "dropdown_keywords": req.dropdown_keywords,
        }.items()
        if v is not None and str(v).strip()
    }
    task_manager.start_task(
        task_id,
        run_download_task,
        (req.task_type, req.date_range, req.period_type, download_options),
    )

    return {"success": True, "message": f"{task_name} 任务已启动", "task": task.to_dict()}


@router.post("/download/stop/{task_type}")
async def stop_download(task_type: str):
    """停止下载任务"""
    task_id = f"download_{task_type}"
    success = task_manager.stop_task(task_id)
    if success:
        return {"success": True, "message": "任务已停止"}
    raise HTTPException(status_code=400, detail="没有正在运行的任务")


@router.get("/download/status/{task_type}")
async def get_download_status(task_type: str):
    """获取下载任务状态"""
    task_id = f"download_{task_type}"
    task = task_manager.get_task(task_id)
    if task:
        return {"success": True, "data": task.to_dict()}
    return {"success": True, "data": {"status": "idle"}}


@router.get("/download/status")
async def get_all_download_status():
    """获取所有下载任务状态"""
    all_tasks = task_manager.get_all_tasks()
    download_tasks = {k: v for k, v in all_tasks.items() if k.startswith("download_")}
    return {"success": True, "data": download_tasks}


@router.get("/files")
async def list_downloaded_files(dir_path: Optional[str] = None):
    """列出已下载的数据文件"""
    from app.services.data_download_service import list_data_files
    try:
        files = list_data_files(dir_path)
        return {"success": True, "data": files}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/keyword/anomaly/latest")
async def get_keyword_latest_anomaly(dir_path: Optional[str] = None):
    """获取关键词最新异动数据（曝光/点击/关键词指数）"""
    from app.services.data_download_service import get_keyword_latest_anomaly
    try:
        data = get_keyword_latest_anomaly(dir_path)
        return {"success": True, "data": data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/keyword/summary/latest")
async def get_keyword_latest_summary(dir_path: Optional[str] = None):
    """获取关键词汇总最新数据（曝光量/点击量）"""
    from app.services.data_download_service import get_keyword_latest_summary
    try:
        data = get_keyword_latest_summary(dir_path)
        return {"success": True, "data": data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/industry-keyword/latest")
async def get_industry_keyword_latest(output_file: Optional[str] = None):
    """获取行业关键词整合结果（按最新日期列降序）"""
    from app.services.data_download_service import get_industry_keyword_latest
    try:
        data = get_industry_keyword_latest(output_file)
        return {"success": True, "data": data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/industry-keyword/dropdown/latest")
async def get_industry_keyword_dropdown_latest(output_file: Optional[str] = None):
    """获取行业关键词下拉词结果表。"""
    from app.services.data_download_service import get_industry_keyword_dropdown_latest
    try:
        data = get_industry_keyword_dropdown_latest(output_file)
        return {"success": True, "data": data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/industry-keyword/delete")
async def delete_industry_keyword_rows(req: IndustryKeywordDeleteRequest):
    """删除行业关键词整合表中的关键词行（按“关键词”精确匹配）。"""
    from app.services.data_download_service import delete_industry_keyword_rows
    try:
        data = delete_industry_keyword_rows(req.output_file, req.keywords or [])
        return {"success": True, "data": data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/industry-keyword/dropdown/delete")
async def delete_industry_keyword_dropdown_rows(req: IndustryKeywordDropdownDeleteRequest):
    """删除行业关键词下拉词表中的行（按“原词+下拉词”精确匹配）。"""
    from app.services.data_download_service import delete_industry_keyword_dropdown_rows
    try:
        data = delete_industry_keyword_dropdown_rows(req.output_file, req.rows or [])
        return {"success": True, "data": data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


INDUSTRY_KEYWORD_TITLE_TASK_ID = "ai_industry_keyword_title"


@router.post("/industry-keyword/title/generate/start")
async def start_generate_industry_keyword_titles(req: IndustryKeywordTitleGenerateRequest):
    """启动行业关键词标题生成任务（异步，返回任务状态）。"""
    from app.services.data_download_service import run_industry_keyword_title_task

    existing = task_manager.get_task(INDUSTRY_KEYWORD_TITLE_TASK_ID)
    if existing and existing.status == TaskStatus.RUNNING:
        raise HTTPException(status_code=409, detail="标题生成任务正在运行中")

    task = task_manager.create_task(INDUSTRY_KEYWORD_TITLE_TASK_ID, "行业关键词-生成标题")
    payload = {
        "mode": req.mode,
        "scenes": req.scenes,
        "material": req.material,
        "titles_per_scene": req.titles_per_scene,
        "keywords": req.keywords or [],
        "output_file": req.output_file,
        "dropdown_output_file": req.dropdown_output_file,
    }
    task_manager.start_task(INDUSTRY_KEYWORD_TITLE_TASK_ID, run_industry_keyword_title_task, (payload,))
    return {"success": True, "message": "标题生成任务已启动", "task": task.to_dict()}


@router.get("/industry-keyword/title/generate/status")
async def get_generate_industry_keyword_titles_status():
    task = task_manager.get_task(INDUSTRY_KEYWORD_TITLE_TASK_ID)
    if task:
        return {"success": True, "data": task.to_dict()}
    return {"success": True, "data": {"status": "idle"}}


@router.post("/industry-keyword/title/generate/stop")
async def stop_generate_industry_keyword_titles():
    success = task_manager.stop_task(INDUSTRY_KEYWORD_TITLE_TASK_ID)
    if success:
        return {"success": True, "message": "已请求停止标题生成任务"}
    raise HTTPException(status_code=400, detail="没有正在运行的标题生成任务")


@router.get("/industry-keyword/title/generate/result")
async def get_generate_industry_keyword_titles_result():
    """获取最近一次标题生成结果（任务完成后前端拉取）。"""
    from app.services.data_download_service import get_industry_keyword_title_generate_result
    task = task_manager.get_task(INDUSTRY_KEYWORD_TITLE_TASK_ID)
    if task and task.result:
        return {"success": True, "data": {"generated_at": task.finished_at or "", "result": task.result}}
    data = get_industry_keyword_title_generate_result()
    return {"success": True, "data": data}


@router.get("/store/overview/latest")
async def get_store_overview_latest(save_path: Optional[str] = None, include_details: bool = True):
    """获取店铺运营最新指标与周期数据"""
    from app.services.data_download_service import get_store_overview_latest
    try:
        data = get_store_overview_latest(save_path, include_details)
        return {"success": True, "data": data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/store/summary/table")
async def get_store_summary_table(file_path: Optional[str] = None, sheet_name: Optional[str] = None):
    """读取店铺周汇总Excel指定sheet表格"""
    from app.services.data_download_service import get_store_summary_table
    try:
        data = get_store_summary_table(file_path, sheet_name)
        return {"success": True, "data": data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/traffic-channel/overview")
async def get_traffic_channel_overview(file_path: Optional[str] = None, sheet_name: Optional[str] = None):
    """读取流量渠道分析结果（当天/本周/本月/分析结果）"""
    from app.services.data_download_service import get_traffic_channel_overview
    try:
        data = get_traffic_channel_overview(file_path, sheet_name)
        return {"success": True, "data": data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/store-image/list")
async def get_store_image_list(save_dir: Optional[str] = None, keyword: Optional[str] = None):
    """读取店铺图片采集目录的图片列表"""
    from app.services.data_download_service import get_store_image_list
    try:
        data = get_store_image_list(save_dir, keyword)
        return {"success": True, "data": data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/store-image/file")
async def get_store_image_file(path: str):
    """读取单张店铺采集图片（二进制）"""
    try:
        if not path:
            raise HTTPException(status_code=400, detail="path 不能为空")

        # URL 参数中的路径在部分场景会出现 + 被解析为空格，先做一次纠偏
        raw_path = str(path or "").strip()
        candidates = [raw_path]
        if " " in raw_path and "+" not in raw_path:
            candidates.append(raw_path.replace(" ", "+"))

        selected = ""
        for p in candidates:
            if os.path.exists(p) and os.path.isfile(p):
                selected = p
                break

        if not selected:
            raise HTTPException(status_code=404, detail="文件不存在")

        return FileResponse(selected)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/product360/table")
async def get_product360_table(output_dir: Optional[str] = None, sheet_name: Optional[str] = None):
    """读取产品360输出目录下Excel结果总报告表格"""
    from app.services.data_download_service import get_product360_table
    try:
        data = get_product360_table(output_dir, sheet_name)
        return {"success": True, "data": data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/product360/traffic-channels")
async def get_product360_traffic_channels(req: Product360TrafficChannelsRequest):
    """按产品ID读取流量来源sheet的最新日期渠道访问人数（用于P4P渠道表快速展示）。"""
    from app.services.data_download_service import get_product360_traffic_channels
    try:
        data = get_product360_traffic_channels(req.output_dir, req.product_ids)
        return {"success": True, "data": data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/product-operate/table")
async def get_product_operate_table(file_path: Optional[str] = None):
    """读取产品运营下载结果表格"""
    from app.services.data_download_service import get_product_operate_table
    try:
        data = get_product_operate_table(file_path)
        return {"success": True, "data": data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# -*- coding: utf-8 -*-
"""
数据分析 API
对应前端: DataAnalysis / TrafficAnalysis / ProductDiagnosis 页面
对应原脚本: 下载数据的处理/main.py
"""
from typing import Dict, Optional
from fastapi import APIRouter, HTTPException, Depends, Header
from app.core.membership_guard import require_membership_or_trial, extract_bearer
from pydantic import BaseModel

from app.core.task_manager import task_manager, TaskStatus
from app.core.logger import logger
from app.core.settings import get_config
from app.services.membership_service import (
    resolve_user_id_by_token,
    check_title_optimize_points_sufficient,
    check_traffic_ai_points_sufficient,
    get_points_pricing_snapshot,
)

router = APIRouter(dependencies=[Depends(require_membership_or_trial)])


def _analysis_admin_skip(x_admin_key: Optional[str] = None) -> bool:
    cfg = get_config()
    expected = (cfg.payment.admin_api_key or "").strip()
    return bool(expected and (x_admin_key or "").strip() == expected)


def _raise_points_value_error(e: ValueError) -> None:
    msg = str(e)
    if (
        "登录会话在云端失效" in msg
        or "重新登录会员账号" in msg
        or "本地登录会话" in msg
    ):
        raise HTTPException(status_code=401, detail=msg)
    if "云端积分" in msg:
        raise HTTPException(status_code=503, detail=msg)
    raise HTTPException(status_code=400, detail=msg)


class AnalysisStartRequest(BaseModel):
    """分析任务启动请求"""
    task_type: str  # comprehensive / statistics / trend / new_links / p4p / diagnosis / volatility
    source_file: Optional[str] = None


@router.get("/points-pricing")
async def get_analysis_points_pricing():
    return {"success": True, "data": get_points_pricing_snapshot()}


@router.get("/title-optimize/points-estimate")
async def estimate_title_optimize_points(
    source_file: Optional[str] = None,
    authorization: Optional[str] = Header(default=None),
    x_admin_key: Optional[str] = Header(default=None, alias="X-Admin-Key"),
):
    from app.services.title_optimize_service import count_title_optimize_targets

    skip_points = _analysis_admin_skip(x_admin_key)
    manual_ids = [x.strip() for x in str(source_file or "").split(",") if x.strip()]
    planned = count_title_optimize_targets(manual_ids)
    if skip_points:
        return {"success": True, "data": {"skip_points": True, "planned_items": planned}}

    token = extract_bearer(authorization)
    try:
        user_id = int(resolve_user_id_by_token(token))
    except Exception as e:
        raise HTTPException(status_code=401, detail=str(e) or "登录已失效，请重新登录")

    try:
        data = check_title_optimize_points_sufficient(user_id, planned, token=token)
    except ValueError as e:
        _raise_points_value_error(e)
    data["skip_points"] = False
    data["planned_items"] = planned
    return {"success": True, "data": data}


@router.get("/traffic-ai/points-estimate")
async def estimate_traffic_ai_points(
    authorization: Optional[str] = Header(default=None),
    x_admin_key: Optional[str] = Header(default=None, alias="X-Admin-Key"),
):
    skip_points = _analysis_admin_skip(x_admin_key)
    if skip_points:
        return {"success": True, "data": {"skip_points": True, "planned_runs": 1}}

    token = extract_bearer(authorization)
    try:
        user_id = int(resolve_user_id_by_token(token))
    except Exception as e:
        raise HTTPException(status_code=401, detail=str(e) or "登录已失效，请重新登录")

    try:
        data = check_traffic_ai_points_sufficient(user_id, token=token)
    except ValueError as e:
        _raise_points_value_error(e)
    data["skip_points"] = False
    return {"success": True, "data": data}


@router.post("/start")
async def start_analysis(
    req: AnalysisStartRequest,
    authorization: Optional[str] = Header(default=None),
    x_admin_key: Optional[str] = Header(default=None, alias="X-Admin-Key"),
    _=Depends(require_membership_or_trial),
):
    """启动数据分析任务"""
    from app.services.analysis_service import run_analysis_task
    from app.services.title_optimize_service import count_title_optimize_targets

    task_id = f"analysis_{req.task_type}"
    existing = task_manager.get_task(task_id)
    if existing and existing.status == TaskStatus.RUNNING:
        raise HTTPException(status_code=409, detail=f"分析任务 {req.task_type} 正在运行中")

    task_name_map = {
        "comprehensive": "综合分析",
        "single_analysis": "单品分析",
        "title_optimize": "产品优化建议",
        "traffic_ai": "店铺整体数据AI分析",
        "statistics": "产品数据统计",
        "trend": "趋势回归分析",
        "new_links": "新发链接监控",
        "p4p": "P4P数据统计",
        "diagnosis": "产品诊断与优化建议",
        "volatility": "流量波动分析",
    }
    task_name = task_name_map.get(req.task_type, req.task_type)

    skip_points = _analysis_admin_skip(x_admin_key)
    user_id = 0
    billing_token = ""
    if req.task_type in ("title_optimize", "traffic_ai") and not skip_points:
        billing_token = extract_bearer(authorization)
        try:
            user_id = int(resolve_user_id_by_token(billing_token))
        except Exception as e:
            raise HTTPException(status_code=401, detail=str(e) or "登录已失效，请重新登录")

        from app.services.admin_runtime_cloud_sync import (
            ensure_runtime_secrets_ready_detail,
            runtime_secrets_unavailable_message,
        )

        ready, reason = ensure_runtime_secrets_ready_detail(
            bearer=billing_token,
            admin_key=str(x_admin_key or ""),
        )
        if not ready:
            raise HTTPException(
                status_code=400,
                detail=runtime_secrets_unavailable_message(reason),
            )

        if req.task_type == "title_optimize":
            manual_ids = [x.strip() for x in str(req.source_file or "").split(",") if x.strip()]
            planned = count_title_optimize_targets(manual_ids)
            if planned <= 0:
                raise HTTPException(status_code=400, detail="未找到待分析产品")
            try:
                estimate = check_title_optimize_points_sufficient(user_id, planned, token=billing_token)
            except ValueError as e:
                _raise_points_value_error(e)
            if not estimate.get("sufficient"):
                raise HTTPException(
                    status_code=402,
                    detail=(
                        f"积分不足：余额 {estimate.get('balance', 0)}，"
                        f"预计至少需 {estimate.get('estimated_total_cost', estimate.get('whole_points_required', 0))} 积分"
                        f"（{planned} 条 × {estimate.get('per_item_cost', 0)} 积分/条）"
                    ),
                )
        elif req.task_type == "traffic_ai":
            try:
                estimate = check_traffic_ai_points_sufficient(user_id, token=billing_token)
            except ValueError as e:
                _raise_points_value_error(e)
            if not estimate.get("sufficient"):
                raise HTTPException(
                    status_code=402,
                    detail=(
                        f"积分不足：余额 {estimate.get('balance', 0)}，"
                        f"预计至少需 {estimate.get('estimated_total_cost', estimate.get('whole_points_required', 0))} 积分"
                        f"（每次 {estimate.get('per_run_cost', 0)} 积分）"
                    ),
                )

    task = task_manager.create_task(task_id, task_name)
    task_manager.start_task(
        task_id,
        run_analysis_task,
        (req.task_type, req.source_file, user_id, skip_points, billing_token),
    )

    return {"success": True, "message": f"{task_name} 任务已启动", "task": task.to_dict()}


@router.post("/inspect/title-optimize-inputs")
async def inspect_title_optimize_inputs(req: AnalysisStartRequest, _=Depends(require_membership_or_trial)):
    """开始分析前检查标题优化所需输入是否齐全"""
    from app.services.title_optimize_service import inspect_title_optimize_inputs

    raw_ids = [x.strip() for x in str(req.source_file or "").split(",") if x.strip()]
    data = inspect_title_optimize_inputs(raw_ids)
    return {"success": True, "data": data}


@router.post("/stop/{task_type}")
async def stop_analysis(task_type: str, _=Depends(require_membership_or_trial)):
    """停止分析任务"""
    task_id = f"analysis_{task_type}"
    success = task_manager.stop_task(task_id)
    if success:
        return {"success": True, "message": "任务已停止"}
    raise HTTPException(status_code=400, detail="没有正在运行的任务")


@router.get("/status/{task_type}")
async def get_analysis_status(task_type: str, _=Depends(require_membership_or_trial)):
    """获取分析任务状态"""
    task_id = f"analysis_{task_type}"
    task = task_manager.get_task(task_id)
    if task:
        return {"success": True, "data": task.to_dict()}
    return {"success": True, "data": {"status": "idle"}}


@router.get("/results/{task_type}")
async def get_analysis_results(task_type: str, _=Depends(require_membership_or_trial)):
    """获取分析结果"""
    from app.services.analysis_service import get_analysis_result
    try:
        result = get_analysis_result(task_type)
        return {"success": True, "data": result}
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="分析结果不存在，请先运行分析任务")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/overview")
async def get_data_overview(_=Depends(require_membership_or_trial)):
    """获取数据概览（Dashboard 用）"""
    from app.services.analysis_service import get_overview_data
    try:
        data = get_overview_data()
        return {"success": True, "data": data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/volatility/anomaly")
async def get_volatility_anomaly(file_path: Optional[str] = None, _=Depends(require_membership_or_trial)):
    """读取流量波动.xlsx 异动sheet数据（正负分组）"""
    from app.services.analysis_service import get_volatility_anomaly_data
    try:
        data = get_volatility_anomaly_data(file_path)
        return {"success": True, "data": data}
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="流量波动结果不存在，请先执行综合分析")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/new-links/monitor")
async def get_new_links_monitor(file_path: Optional[str] = None, sheet_name: Optional[str] = None, _=Depends(require_membership_or_trial)):
    """读取新发链接数据监控.xlsx（按最新列绝对值降序）"""
    from app.services.analysis_service import get_new_links_monitor_data
    try:
        data = get_new_links_monitor_data(file_path, sheet_name)
        return {"success": True, "data": data}
    except FileNotFoundError:
        # 文件尚未生成时返回空表，避免前端轮询产生大量 404
        target_sheet = (sheet_name or "全店曝光次数").strip()
        return {"success": True, "data": {"sheet": target_sheet, "columns": [], "rows": [], "latest_col": None}}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/diagnosis/table")
async def get_diagnosis_table(file_path: Optional[str] = None, _=Depends(require_membership_or_trial)):
    """读取产品诊断与优化建议.xlsx"""
    from app.services.analysis_service import get_diagnosis_table_data
    try:
        data = get_diagnosis_table_data(file_path)
        return {"success": True, "data": data}
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="诊断结果不存在，请先执行综合分析")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/statistics/table")
async def get_statistics_table(file_path: Optional[str] = None, sheet_name: Optional[str] = None, _=Depends(require_membership_or_trial)):
    """读取统计输出文件（统计csss.xlsx）"""
    from app.services.analysis_service import get_statistics_table_data
    try:
        data = get_statistics_table_data(file_path, sheet_name)
        return {"success": True, "data": data}
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="统计结果不存在，请先执行综合分析")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/p4p/table")
async def get_p4p_table(file_path: Optional[str] = None, sheet_name: Optional[str] = None, _=Depends(require_membership_or_trial)):
    """读取P4P输出文件（P4P数据统计.xlsx）"""
    from app.services.analysis_service import get_p4p_table_data
    try:
        data = get_p4p_table_data(file_path, sheet_name)
        return {"success": True, "data": data}
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="P4P结果不存在，请先执行综合分析")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/title-optimize/results")
async def get_title_optimize_results(_=Depends(require_membership_or_trial)):
    from app.services.title_optimize_service import get_title_optimize_results
    try:
        data = get_title_optimize_results()
        return {"success": True, "data": data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/title-optimize/detail")
async def get_title_optimize_detail(product_id: str, _=Depends(require_membership_or_trial)):
    from app.services.title_optimize_service import get_title_optimize_detail
    try:
        data = get_title_optimize_detail(product_id)
        return {"success": True, "data": data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/traffic-ai/result")
async def get_traffic_ai_result(_=Depends(require_membership_or_trial)):
    from app.services.analysis_service import get_traffic_ai_result
    try:
        data = get_traffic_ai_result()
        return {"success": True, "data": data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

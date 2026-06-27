# -*- coding: utf-8 -*-
"""
会员体系 API（V1）
"""
import asyncio
import os

from typing import Optional, Dict, Any
from fastapi import APIRouter, HTTPException, Header, Body, Depends, Request
from pydantic import BaseModel

from app.core.membership_guard import require_membership_or_trial
from app.core.admin_guard import require_admin_api_key
from app.core.settings import get_config, CONFIG_FILE, config_manager
from app.services.membership_service import (
    init_db,
    register,
    admin_create_user,
    admin_delete_user,
    login,
    unified_login,
    me,
    admin_login_guard_check,
    admin_login_guard_failed,
    admin_login_guard_success,
    verify_admin_account,
    change_admin_password,
    deactivate_all_member_accounts,
    create_recharge,
    mark_recharge_paid,
    redeem_vip,
    apply_withdraw,
    list_ledger,
    list_invite_rewards,
    list_recharge_orders,
    list_recharge_orders_paged,
    get_admin_dashboard_stats,
    get_recharge_order,
    handle_wechat_callback,
    handle_alipay_callback,
    list_withdraw_orders,
    approve_withdraw,
    reject_withdraw,
    batch_review_withdraws,
    upsert_user_access_control,
    list_users_admin,
    register_agent_node,
    heartbeat_agent_node,
    list_agents_admin,
    ingest_keyword_report,
    list_keyword_reports_admin,
    upsert_agent_policy,
    get_agent_policy,
    get_keyword_report_detail,
    delete_keyword_reports_admin,
    admin_update_user,
    admin_upsert_profile_by_username,
    fetch_cloud_me_cached,
    _ensure_local_session_for_cloud_login,
    issue_admin_runtime_session,
    verify_admin_api_key,
)

router = APIRouter()


class RegisterReq(BaseModel):
    username: str
    password: str
    shop_url: Optional[str] = None
    invite_code: Optional[str] = None


class LoginReq(BaseModel):
    username: str
    password: str


class AdminLoginReq(BaseModel):
    username: str
    password: str


class RechargeReq(BaseModel):
    channel: str  # wechat / alipay
    amount_yuan: float


class RechargeMockPaidReq(BaseModel):
    order_no: str


class RedeemReq(BaseModel):
    months: int = 1


class PointsConsumeReq(BaseModel):
    amount: float
    biz_type: str
    biz_id: Optional[str] = None
    remark: str = ""


class WithdrawReq(BaseModel):
    points: int
    channel: str
    account: str


class WithdrawReviewReq(BaseModel):
    withdraw_no: str
    reason: Optional[str] = ""


class WithdrawBatchReviewReq(BaseModel):
    withdraw_nos: list[str]
    action: str  # approve / reject
    reason: Optional[str] = ""


class AdminUserControlReq(BaseModel):
    user_id: int
    mode: str  # normal / force_allow / force_block
    note: Optional[str] = ""


class AdminUserUpdateReq(BaseModel):
    user_id: int
    password: Optional[str] = None
    points_balance: Optional[float] = None
    trial_start_at: Optional[str] = None
    trial_end_at: Optional[str] = None
    vip_expire_at: Optional[str] = None


class AdminUserCreateReq(BaseModel):
    username: str
    password: str
    real_name: str = ""
    phone: str = ""
    invite_code: Optional[str] = None
    points_balance: float = 0
    trial_days: int = 15


class AdminUserDeleteReq(BaseModel):
    user_id: int


class AdminProfileUpsertReq(BaseModel):
    username: str
    company_name: str = ""
    main_category: str = ""
    is_verified: str = ""
    service_years: str = ""
    page_level_star: str = ""
    force: bool = False


class AdminCleanupMembersReq(BaseModel):
    reset_password: bool = True


class AdminChangePasswordReq(BaseModel):
    username: str
    old_password: str
    new_password: str


class AgentRegisterReq(BaseModel):
    agent_id: str
    client_name: Optional[str] = ""
    machine_id: Optional[str] = ""
    app_version: Optional[str] = ""
    license_key: Optional[str] = ""


class AgentHeartbeatReq(BaseModel):
    agent_id: str
    status: Optional[str] = "active"


class AgentPolicyReq(BaseModel):
    agent_id: str
    policy: Dict[str, Any] = {}


class KeywordItemReq(BaseModel):
    keyword: str
    exposure: Optional[float] = 0
    click: Optional[float] = 0
    ctr: Optional[float] = 0
    keyword_index: Optional[float] = 0
    product_id: Optional[str] = ""


class KeywordReportReq(BaseModel):
    agent_id: str
    report_date: str
    batch_no: str
    source: Optional[str] = "keyword_summary"
    items: list[KeywordItemReq] = []


class KeywordReportDeleteReq(BaseModel):
    report_ids: list[int] = []


def _extract_keyword_report_ids(req: Optional[KeywordReportDeleteReq], request: Request) -> list[int]:
    ids: list[int] = []
    if req and isinstance(req.report_ids, list):
        ids.extend(req.report_ids)

    # 兼容 query 参数：?report_ids=1,2,3 或 ?report_ids=1&report_ids=2
    try:
        raw_multi = request.query_params.getlist("report_ids")
    except Exception:
        raw_multi = []
    for raw in raw_multi:
        for part in str(raw or "").split(","):
            s = part.strip()
            if not s:
                continue
            try:
                ids.append(int(s))
            except Exception:
                continue

    return [x for x in sorted(set(ids)) if int(x) > 0]


def _token(authorization: Optional[str]) -> str:
    if not authorization:
        raise HTTPException(status_code=401, detail="缺少Authorization")
    v = authorization.strip()
    if v.lower().startswith("bearer "):
        return v[7:].strip()
    return v


@router.on_event("startup")
async def _startup_init_membership_db():
    # 云端主机：启动阶段不跑 init_db，避免阻塞 /api/health（nginx 504、curl 超时）
    if os.getenv("MEMBERSHIP_IS_CLOUD_HOST", "").strip().lower() in {"1", "true", "yes"}:
        return
    await asyncio.to_thread(init_db)


@router.post("/auth/register")
async def api_register(req: RegisterReq):
    try:
        data = register(req.username.strip(), req.password, req.invite_code)
        return {"success": True, "data": data}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/connectivity")
async def api_connectivity():
    """桌面端诊断：云端是否可达、是否命中 Clash 假 DNS。"""
    from app.services.membership_service import check_cloud_connectivity

    return {"success": True, "data": check_cloud_connectivity()}


class AdminRuntimeConfigBody(BaseModel):
    data_analysis: Optional[Dict[str, Any]] = None
    ai_image_gen: Optional[Dict[str, Any]] = None
    points_pricing: Optional[Dict[str, Any]] = None


def _extract_bearer_token(authorization: Optional[str]) -> str:
    v = str(authorization or "").strip()
    if v.lower().startswith("bearer "):
        return v[7:].strip()
    return v


def _can_read_admin_runtime_config(
    authorization: Optional[str],
    x_admin_key: Optional[str],
) -> bool:
    if verify_admin_api_key(x_admin_key):
        return True
    token = _extract_bearer_token(authorization)
    if not token:
        return False
    try:
        me(token)
        return True
    except Exception:
        return False


@router.get("/admin/runtime-config")
async def api_get_admin_runtime_config(
    request: Request,
    authorization: Optional[str] = Header(default=None),
    x_admin_key: Optional[str] = Header(default=None, alias="X-Admin-Key"),
):
    """全客户端统一下发的管理员配置（API Key / 模型）。已登录会员可读（用于本机执行任务）。"""
    if not _can_read_admin_runtime_config(authorization, x_admin_key):
        raise HTTPException(status_code=401, detail="请先登录会员中心")
    from app.services.cloud_admin_runtime_service import load_cloud_admin_runtime

    cloud = load_cloud_admin_runtime()
    if int(cloud.get("revision") or 0) > 0:
        out = {
            "revision": int(cloud.get("revision") or 0),
            "updated_at": cloud.get("updated_at") or "",
            "data_analysis": dict(cloud.get("data_analysis") or {}),
            "ai_image_gen": dict(cloud.get("ai_image_gen") or {}),
            "points_pricing": dict(cloud.get("points_pricing") or {}),
        }
    else:
        out = {
            "revision": 0,
            "updated_at": "",
            "data_analysis": {},
            "ai_image_gen": {},
            "points_pricing": {},
        }

    return {"success": True, "data": out}


@router.put("/admin/runtime-config")
async def api_put_admin_runtime_config(
    body: AdminRuntimeConfigBody,
    x_admin_key: Optional[str] = Header(default=None, alias="X-Admin-Key"),
):
    """管理员保存运行时配置，所有桌面客户端将自动拉取。"""
    if not verify_admin_api_key(x_admin_key):
        raise HTTPException(status_code=401, detail="管理员密钥无效或未配置")
    from app.services.cloud_admin_runtime_service import save_cloud_admin_runtime

    saved = save_cloud_admin_runtime(
        data_analysis=body.data_analysis,
        ai_image_gen=body.ai_image_gen,
        points_pricing=body.points_pricing,
        merge=True,
    )
    return {
        "success": True,
        "data": {
            "revision": int(saved.get("revision") or 0),
            "updated_at": saved.get("updated_at") or "",
        },
    }


@router.post("/auth/login")
async def api_login(req: LoginReq, request: Request):
    try:
        ip = (request.client.host if request.client else "") or ""
        ua = request.headers.get("user-agent", "")
        # 使用 asyncio.to_thread 将同步函数放入线程池执行
        # 事件循环不再被阻塞，其他请求可以正常处理
        data = await asyncio.to_thread(
            unified_login,
            req.username.strip(),
            str(req.password or "").strip(),
            ip=ip,
            user_agent=ua
        )
        return {"success": True, "data": data}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/auth/sync-admin-session")
async def api_sync_admin_session(x_admin_key: Optional[str] = Header(default=None, alias="X-Admin-Key")):
    """管理员仅有 admin_key、无 Bearer 时，向本机申请运行时 token（产品优化等接口需要 Authorization）。"""
    try:
        if not verify_admin_api_key(x_admin_key):
            raise ValueError("管理员密钥无效或未配置")
        data = issue_admin_runtime_session()
        return {"success": True, "data": {"role": "admin", **data}}
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/auth/admin-session-key")
async def api_admin_session_key(authorization: Optional[str] = Header(default=None)):
    """管理员 Bearer 会话刷新本机有效的 admin_key（修复 localStorage 缓存了占位符密钥）。"""
    from app.services.membership_service import _get_admin_api_key, is_admin_bearer_token

    try:
        token = _token(authorization)
        if not is_admin_bearer_token(token):
            raise ValueError("需要管理员登录态")
        admin_key = _get_admin_api_key()
        if not admin_key:
            raise ValueError("管理员 API Key 未配置，请检查 desktop.deploy.json 或 ALI_ADMIN_API_KEY")
        return {"success": True, "data": {"admin_key": admin_key}}
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/auth/sync-local-session")
async def api_sync_local_session(authorization: Optional[str] = Header(default=None)):
    """浏览器直连云端登录后，把 token 写入本地 user_sessions，供 /api/config 等鉴权。"""
    try:
        token = _token(authorization)
        cloud = await asyncio.to_thread(fetch_cloud_me_cached, token, allow_stale=False)
        if not isinstance(cloud, dict):
            raise ValueError("无法从云端校验登录态")
        uname = str(cloud.get("username") or "").strip()
        if not uname:
            raise ValueError("云端未返回用户名")
        from app.services.membership_service import _sync_user_id_from_cloud_token

        _sync_user_id_from_cloud_token(token)
        return {"success": True, "data": {"username": uname}}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/auth/admin-login")
async def api_admin_login(req: AdminLoginReq, request: Request):
    """兼容旧客户端；新逻辑请用 /auth/login（自动识别管理员/会员）。"""
    try:
        ip = (request.client.host if request.client else "") or ""
        ua = request.headers.get("user-agent", "")
        data = unified_login(req.username.strip(), req.password, ip=ip, user_agent=ua)
        if str(data.get("role") or "") != "admin":
            raise ValueError("管理员账号或密码错误")
        return {
            "success": True,
            "data": {
                "admin_key": data.get("admin_key"),
                "admin_user": data.get("admin_user"),
            },
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/me")
async def api_me(authorization: Optional[str] = Header(default=None)):
    try:
        data = me(_token(authorization))
        return {"success": True, "data": data}
    except Exception as e:
        raise HTTPException(status_code=401, detail=str(e))


@router.get("/points/ledger")
async def api_ledger(limit: int = 50, authorization: Optional[str] = Header(default=None)):
    try:
        rows = list_ledger(_token(authorization), limit)
        return {"success": True, "data": rows}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/points/consume")
async def api_points_consume(req: PointsConsumeReq, authorization: Optional[str] = Header(default=None)):
    """云端扣积分（运行在云端时写云端库；桌面端远程调用此接口）。"""
    from app.services.membership_service import resolve_user_id_by_token, _deduct_points_amount, _points_ai_image_lock

    try:
        token = _token(authorization)
        uid = resolve_user_id_by_token(token)
        biz_type = str(req.biz_type or "consume")
        lock = _points_ai_image_lock if biz_type == "ai_image_gen" else None
        data = _deduct_points_amount(
            uid,
            float(req.amount),
            biz_type,
            req.biz_id,
            str(req.remark or ""),
            lock=lock,
        )
        return {"success": True, "data": data}
    except ValueError as e:
        msg = str(e)
        if "积分不足" in msg:
            raise HTTPException(status_code=402, detail=msg)
        raise HTTPException(status_code=400, detail=msg)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/recharge/list")
async def api_recharge_list(status: Optional[str] = None, limit: int = 100, authorization: Optional[str] = Header(default=None)):
    try:
        rows = list_recharge_orders(_token(authorization), status=status, limit=limit)
        return {"success": True, "data": rows}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/recharge/list-paged")
async def api_recharge_list_paged(
    status: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
    authorization: Optional[str] = Header(default=None),
):
    try:
        data = list_recharge_orders_paged(_token(authorization), status=status, page=page, page_size=page_size)
        return {"success": True, "data": data}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/invite/rewards")
async def api_invite_rewards(limit: int = 100, authorization: Optional[str] = Header(default=None)):
    try:
        rows = list_invite_rewards(_token(authorization), limit)
        return {"success": True, "data": rows}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/recharge/create")
async def api_recharge_create(req: RechargeReq, authorization: Optional[str] = Header(default=None)):
    try:
        data = create_recharge(_token(authorization), req.channel, req.amount_yuan)
        return {"success": True, "data": data}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/recharge/order/{order_no}")
async def api_recharge_order(order_no: str, authorization: Optional[str] = Header(default=None)):
    try:
        data = get_recharge_order(_token(authorization), order_no)
        return {"success": True, "data": data}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/recharge/mock-paid")
async def api_recharge_mock_paid(req: RechargeMockPaidReq, _=Depends(require_membership_or_trial)):
    """V1 演示：模拟支付回调成功。后续替换为微信/支付宝正式回调。"""
    try:
        data = mark_recharge_paid(req.order_no.strip())
        return {"success": True, "data": data}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/pay/callback/wechat")
async def api_wechat_callback(request: Request, payload: Dict[str, Any] = Body(default_factory=dict)):
    """微信支付回调。"""
    try:
        client_ip = (request.client.host if request and request.client else "") or ""
        data = handle_wechat_callback(payload or {}, client_ip=client_ip)
        return {"success": True, "data": data}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/pay/callback/alipay")
async def api_alipay_callback(request: Request, payload: Dict[str, Any] = Body(default_factory=dict)):
    """支付宝支付回调。"""
    try:
        client_ip = (request.client.host if request and request.client else "") or ""
        data = handle_alipay_callback(payload or {}, client_ip=client_ip)
        return {"success": True, "data": data}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/vip/redeem")
async def api_vip_redeem(req: RedeemReq, authorization: Optional[str] = Header(default=None)):
    try:
        data = redeem_vip(_token(authorization), req.months)
        return {"success": True, "data": data}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/withdraw/apply")
async def api_withdraw_apply(req: WithdrawReq, authorization: Optional[str] = Header(default=None)):
    try:
        data = apply_withdraw(_token(authorization), req.points, req.channel, req.account)
        return {"success": True, "data": data}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/admin/withdraw/list")
async def api_admin_withdraw_list(status: Optional[str] = None, limit: int = 50, _=Depends(require_admin_api_key)):
    try:
        data = list_withdraw_orders(status=status, limit=limit)
        return {"success": True, "data": data}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/admin/dashboard")
async def api_admin_dashboard(days: int = 30, _=Depends(require_admin_api_key)):
    try:
        data = get_admin_dashboard_stats(days=days)
        return {"success": True, "data": data}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/admin/withdraw/approve")
async def api_admin_withdraw_approve(req: WithdrawReviewReq, _=Depends(require_admin_api_key)):
    try:
        data = approve_withdraw(req.withdraw_no.strip())
        return {"success": True, "data": data}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/admin/withdraw/reject")
async def api_admin_withdraw_reject(req: WithdrawReviewReq, _=Depends(require_admin_api_key)):
    try:
        data = reject_withdraw(req.withdraw_no.strip(), req.reason or "")
        return {"success": True, "data": data}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/admin/withdraw/batch-review")
async def api_admin_withdraw_batch_review(req: WithdrawBatchReviewReq, _=Depends(require_admin_api_key)):
    try:
        data = batch_review_withdraws(req.withdraw_nos, req.action.strip().lower(), req.reason or "")
        return {"success": True, "data": data}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/admin/users")
async def api_admin_users(limit: int = 200, _=Depends(require_admin_api_key)):
    try:
        data = list_users_admin(limit=limit)
        return {"success": True, "data": data}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/admin/users/create")
async def api_admin_users_create(req: AdminUserCreateReq, _=Depends(require_admin_api_key)):
    try:
        data = admin_create_user(
            username=req.username.strip(),
            password=req.password,
            real_name=req.real_name,
            phone=req.phone,
            invite_code=req.invite_code,
            points_balance=req.points_balance,
            trial_days=req.trial_days,
        )
        return {"success": True, "data": data}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/admin/users/delete")
async def api_admin_users_delete(req: AdminUserDeleteReq, _=Depends(require_admin_api_key)):
    try:
        data = admin_delete_user(req.user_id)
        return {"success": True, "data": data}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/admin/users/profile-upsert")
async def api_admin_users_profile_upsert(req: AdminProfileUpsertReq, authorization: Optional[str] = Header(default=None), _=Depends(require_admin_api_key)):
    try:
        # 安全校验：默认仅允许更新当前登录会员自己的资料，防止越权污染
        if not bool(req.force):
            token = (authorization or "").strip()
            if token.lower().startswith("bearer "):
                token = token[7:].strip()
            if not token:
                raise ValueError("缺少Authorization")
            me_data = me(token)
            me_username = str(me_data.get("username") or "").strip()
            if me_username != req.username.strip():
                raise ValueError("仅允许更新当前登录会员自己的店铺资料")

        data = admin_upsert_profile_by_username(
            username=req.username.strip(),
            company_name=req.company_name,
            main_category=req.main_category,
            is_verified=req.is_verified,
            service_years=req.service_years,
            page_level_star=req.page_level_star,
        )
        return {"success": True, "data": data}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/admin/users/cleanup")
async def api_admin_users_cleanup(req: AdminCleanupMembersReq = Body(default=AdminCleanupMembersReq()), _=Depends(require_admin_api_key)):
    try:
        data = deactivate_all_member_accounts(reset_password=bool(req.reset_password))
        return {"success": True, "data": data}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/admin/account/change-password")
async def api_admin_account_change_password(req: AdminChangePasswordReq, _=Depends(require_admin_api_key)):
    try:
        data = change_admin_password(
            username=req.username.strip(),
            old_password=req.old_password,
            new_password=req.new_password,
        )
        return {"success": True, "data": data}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/admin/users/control")
async def api_admin_user_control(req: AdminUserControlReq, _=Depends(require_admin_api_key)):
    try:
        data = upsert_user_access_control(req.user_id, req.mode, req.note or "")
        return {"success": True, "data": data}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/admin/users/update")
async def api_admin_user_update(req: AdminUserUpdateReq, _=Depends(require_admin_api_key)):
    try:
        data = admin_update_user(
            user_id=req.user_id,
            new_password=req.password,
            points_balance=req.points_balance,
            trial_start_at=req.trial_start_at,
            trial_end_at=req.trial_end_at,
            vip_expire_at=req.vip_expire_at,
        )
        return {"success": True, "data": data}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/agent/register")
async def api_agent_register(req: AgentRegisterReq, _=Depends(require_admin_api_key)):
    try:
        data = register_agent_node(
            req.agent_id,
            req.client_name or "",
            req.machine_id or "",
            req.app_version or "",
            req.license_key or "",
        )
        return {"success": True, "data": data}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/agent/heartbeat")
async def api_agent_heartbeat(req: AgentHeartbeatReq, _=Depends(require_admin_api_key)):
    try:
        data = heartbeat_agent_node(req.agent_id, req.status or "active")
        return {"success": True, "data": data}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/admin/agents")
async def api_admin_agents(limit: int = 300, _=Depends(require_admin_api_key)):
    try:
        data = list_agents_admin(limit=limit)
        return {"success": True, "data": data}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/admin/agents/policy")
async def api_admin_agents_policy(req: AgentPolicyReq, _=Depends(require_admin_api_key)):
    try:
        data = upsert_agent_policy(req.agent_id, req.policy or {})
        return {"success": True, "data": data}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/agent/policy")
async def api_agent_policy(agent_id: str, _=Depends(require_admin_api_key)):
    try:
        data = get_agent_policy(agent_id)
        return {"success": True, "data": data}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/telemetry/keywords")
async def api_telemetry_keywords(req: KeywordReportReq, _=Depends(require_membership_or_trial)):
    try:
        data = ingest_keyword_report(
            agent_id=req.agent_id,
            report_date=req.report_date,
            batch_no=req.batch_no,
            source=req.source or "keyword_summary",
            items=[x.model_dump() for x in (req.items or [])],
        )
        return {"success": True, "data": data}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/admin/telemetry/keywords")
async def api_admin_telemetry_keywords(agent_id: Optional[str] = None, limit: int = 100, _=Depends(require_admin_api_key)):
    try:
        data = list_keyword_reports_admin(agent_id=agent_id, limit=limit)
        return {"success": True, "data": data}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/admin/telemetry/keywords/{report_id:int}")
async def api_admin_telemetry_keywords_detail(report_id: int, limit: int = 200, _=Depends(require_admin_api_key)):
    try:
        data = get_keyword_report_detail(report_id=report_id, limit=limit)
        return {"success": True, "data": data}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.api_route("/admin/telemetry/keywords/delete", methods=["POST", "DELETE"])
async def api_admin_telemetry_keywords_delete_legacy(
    request: Request,
    req: Optional[KeywordReportDeleteReq] = Body(default=None),
    _=Depends(require_admin_api_key),
):
    try:
        report_ids = _extract_keyword_report_ids(req, request)
        data = delete_keyword_reports_admin(report_ids=report_ids)
        return {"success": True, "data": data}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.api_route("/admin/telemetry/keywords/batch/delete", methods=["POST", "DELETE"])
async def api_admin_telemetry_keywords_delete(
    request: Request,
    req: Optional[KeywordReportDeleteReq] = Body(default=None),
    _=Depends(require_admin_api_key),
):
    try:
        report_ids = _extract_keyword_report_ids(req, request)
        data = delete_keyword_reports_admin(report_ids=report_ids)
        return {"success": True, "data": data}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


class MeProfileUpdateReq(BaseModel):
    company_name: str = ""
    main_category: str = ""
    is_verified: str = ""
    service_years: str = ""
    page_level_star: str = ""

@router.post("/me/profile")
async def api_me_profile_update(
    req: MeProfileUpdateReq,
    authorization: Optional[str] = Header(default=None),
):
    """会员自助更新自己的店铺资料，只需 Bearer Token，无需 admin_key。"""
    try:
        token = (authorization or "").strip()
        if token.lower().startswith("bearer "):
            token = token[7:].strip()
        if not token:
            raise ValueError("缺少 Authorization")
        me_data = me(token)
        username = str(me_data.get("username") or "").strip()
        if not username:
            raise ValueError("无法识别当前用户")
        data = admin_upsert_profile_by_username(
            username=username,
            company_name=req.company_name,
            main_category=req.main_category,
            is_verified=req.is_verified,
            service_years=req.service_years,
            page_level_star=req.page_level_star,
        )
        return {"success": True, "data": data}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))





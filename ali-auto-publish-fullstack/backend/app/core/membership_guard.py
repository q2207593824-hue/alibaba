# -*- coding: utf-8 -*-
from typing import Optional, Dict, Any
from fastapi import Header, HTTPException, Request
import hashlib
import asyncio
import os
import time

from app.services.membership_service import (
    evaluate_access_by_token,
    fetch_cloud_me_cached,
    _sync_user_id_from_cloud_token,
    is_admin_access,
    is_admin_username,
    _conn,
    _now_str,
)
from app.core.settings import get_config
from app.core.logger import logger

_DEBUG_AUTH = os.getenv("AUTH_GUARD_DEBUG", "").strip().lower() in {"1", "true", "yes"}

_CLOUD_GUARD_SYNC_LAST: Dict[str, float] = {}
_CLOUD_OVERRIDE_LAST: Dict[str, float] = {}
_GUARD_SYNC_MIN_INTERVAL_SEC = 120.0
_CLOUD_OVERRIDE_MIN_INTERVAL_SEC = 60.0


def _dbg(msg: str) -> None:
    if _DEBUG_AUTH:
        try:
            print(f"[auth-guard] {msg}", flush=True)
        except Exception:
            pass


def _raise_auth_http(status_code: int, detail: str, reason: str):
    # 兼容部分运行环境可能丢失自定义响应头：在 body 内也携带 reason
    _dbg(f"raise_http status={status_code} reason={reason} detail={detail}")
    raise HTTPException(
        status_code=status_code,
        detail={"message": detail, "reason": reason},
        headers={"X-Auth-Reason": reason},
    )


def extract_bearer(authorization: Optional[str]) -> str:
    if not authorization:
        _raise_auth_http(401, "缺少Authorization，请先登录会员中心", "missing_authorization")
    v = authorization.strip()
    if v.lower().startswith("bearer "):
        return v[7:].strip()
    return v


def _to_dt(value: str):
    from datetime import datetime

    s = str(value or "").strip()
    if not s:
        return None
    for fmt in ["%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"]:
        try:
            return datetime.strptime(s, fmt)
        except Exception:
            pass
    try:
        # 兼容 2026-04-22T16:10:41.123 之类
        return datetime.fromisoformat(s.replace("Z", ""))
    except Exception:
        return None


def _get_local_company_by_username(username: str) -> str:
    try:
        uname = str(username or "").strip()
        if not uname:
            return ""
        conn = _conn()
        cur = conn.cursor()
        row = cur.execute("SELECT company_name FROM users WHERE username=? LIMIT 1", (uname,)).fetchone()
        conn.close()
        return str((row or {}).get("company_name") or "").strip() if row else ""
    except Exception:
        return ""


def _upsert_local_membership_snapshot(info: Dict[str, Any]) -> None:
    """将云端会员快照落到本地 users，避免本地功能继续按旧状态拦截。"""
    try:
        username = str(info.get("username") or "").strip()
        if not username:
            return

        company_name = str(info.get("company_name") or "").strip()
        main_category = str(info.get("main_category") or "").strip()
        is_verified = str(info.get("is_verified") or "").strip()
        service_years = str(info.get("service_years") or "").strip()
        page_level_star = str(info.get("page_level_star") or "").strip()
        trial_end_at = str(info.get("trial_end_at") or "").strip()
        vip_expire_at = str(info.get("vip_expire_at") or "").strip() or None

        conn = _conn()
        cur = conn.cursor()
        row = cur.execute("SELECT id FROM users WHERE username=? LIMIT 1", (username,)).fetchone()
        if row:
            cur.execute(
                """
                UPDATE users
                SET company_name=?, main_category=?, is_verified=?, service_years=?, page_level_star=?,
                    trial_end_at=?, vip_expire_at=?
                WHERE username=?
                """,
                (
                    company_name,
                    main_category,
                    is_verified,
                    service_years,
                    page_level_star,
                    trial_end_at,
                    vip_expire_at,
                    username,
                ),
            )
            conn.commit()
        conn.close()
    except Exception:
        pass


def _cloud_override_enabled() -> bool:
    if os.getenv("ALI_DESKTOP", "").strip() == "1":
        return True
    return os.getenv("MEMBERSHIP_GUARD_CLOUD_OVERRIDE", "").strip().lower() in {"1", "true", "yes"}


def _maybe_sync_cloud_snapshot(token: str, info: Dict[str, Any]) -> None:
    """限流：避免每个 API 请求都写 membership.db。"""
    t = str(token or "").strip()
    if not t or not isinstance(info, dict):
        return
    now = time.time()
    if now - float(_CLOUD_GUARD_SYNC_LAST.get(t) or 0) < _GUARD_SYNC_MIN_INTERVAL_SEC:
        return
    _CLOUD_GUARD_SYNC_LAST[t] = now
    _upsert_local_membership_snapshot(info)
    try:
        _sync_user_id_from_cloud_token(t)
    except Exception as e:
        logger.warning(f"membership_guard: sync local session from cloud token failed: {e}")


def _evaluate_access_by_cloud_token(token: str) -> Optional[Dict[str, Any]]:
    """
    当本地 membership.db 无此 token 时，回退到云端会员状态判断。
    并把 token 映射写回本地 users + user_sessions，后续本地接口不再 401。
    """
    try:
        info = fetch_cloud_me_cached(token, allow_stale=True)
        if not isinstance(info, dict):
            logger.warning("membership_guard: cloud /me unavailable")
            return None

        _maybe_sync_cloud_snapshot(token, info)

        company_name = str(info.get("company_name") or "").strip()
        if not company_name:
            # 云端 me 可能暂时未回写公司名，回退读取本地绑定快照，避免误判已绑定账号
            local_company = _get_local_company_by_username(str(info.get("username") or ""))
            company_name = str(local_company or "").strip()
        role = str(info.get("role") or "").strip().lower()
        uname = str(info.get("username") or "").strip()
        if role == "admin" or (uname and is_admin_username(uname)):
            return {"allowed": True, "reason": "admin", "info": info}
        if not company_name:
            return {"allowed": False, "reason": "store_not_bound", "info": info}

        from datetime import datetime
        now = datetime.now()
        vip_expire = _to_dt(str(info.get("vip_expire_at") or ""))
        trial_end = _to_dt(str(info.get("trial_end_at") or ""))

        is_vip = bool(vip_expire and vip_expire > now)
        can_trial = bool(trial_end and trial_end > now)
        allowed = bool(info.get("can_use")) or is_vip or can_trial

        return {"allowed": allowed, "reason": "ok" if allowed else "not_member", "info": info}
    except Exception as e:
        logger.warning(f"membership_guard: unexpected cloud eval error: {e}")
        return None


def _token_hash(token: str) -> str:
    return hashlib.sha256(str(token or "").encode("utf-8")).hexdigest()


def _extract_device_id(request: Request) -> str:
    try:
        return str(request.headers.get("X-Client-Device-Id") or "").strip()
    except Exception:
        return ""


def require_membership_or_trial(
    request: Request,
    authorization: Optional[str] = Header(default=None),
    x_admin_key: Optional[str] = Header(default=None, alias="X-Admin-Key"),
):
    # 放行“绑定店铺”接口：未绑定/未校验通过时也允许执行绑定动作本身
    try:
        p = str(getattr(request, "url", None).path or "")
        if p.endswith("/api/config/cookie/login-by-browser-manager"):
            return
        # 配置 revision 仅用于检测变更，不暴露敏感数据
        if p.endswith("/api/config/revision"):
            return
        # 本地 AI 生图状态/日志轮询：桌面版未登录会员时仍可读进度（仅 127.0.0.1）
        if p.endswith(("/api/images/ai-gen/status", "/api/images/ai-gen/logs/recent")):
            host = (request.client.host if request.client else "") or ""
            if host in ("127.0.0.1", "::1") and not authorization and not str(x_admin_key or "").strip():
                return
    except Exception:
        pass

    # 管理员总钥匙直通：用于管理员操作全站功能（与云端 verify 同源：env/config/deploy）
    try:
        from app.services.membership_service import verify_admin_api_key

        if verify_admin_api_key(x_admin_key):
            return
    except Exception:
        pass

    token = extract_bearer(authorization)
    if is_admin_access(token, x_admin_key):
        _dbg(f"admin access allow path={request.url.path}")
        return

    device_id = _extract_device_id(request)
    _dbg(f"incoming path={request.url.path} token_prefix={token[:8] if token else ''} device_id={device_id}")

    # token_hash/device_id 强校验：防止 token 切换越权
    try:
        conn = _conn()
        cur = conn.cursor()
        row = cur.execute("SELECT token_hash, device_id FROM user_sessions WHERE token=? LIMIT 1", (token,)).fetchone()
        if row:
            saved_hash = str(row["token_hash"] or "").strip()
            saved_device = str(row["device_id"] or "").strip()
            if saved_hash and saved_hash != _token_hash(token):
                conn.close()
                _raise_auth_http(401, "会话校验失败，请重新登录", "session_hash_mismatch")
            if saved_device and device_id and saved_device != device_id:
                conn.close()
                _raise_auth_http(401, "设备校验失败，请重新登录", "device_mismatch")
            # 首次记录设备ID
            if (not saved_device) and device_id:
                cur.execute("UPDATE user_sessions SET device_id=?, last_seen_at=? WHERE token=?", (device_id, _now_str(), token))
                conn.commit()
        conn.close()
    except HTTPException:
        raise
    except Exception:
        pass

    state: Optional[Dict[str, Any]] = None
    local_eval_error = ""
    try:
        state = await asyncio.to_thread(evaluate_access_by_token, token)
        _dbg(f"local_eval ok allowed={bool((state or {}).get('allowed'))} reason={str((state or {}).get('reason') or '')}")
    except Exception as e:
        local_eval_error = str(e)
        _dbg(f"local_eval failed err={local_eval_error}")
        logger.info(f"membership_guard: local evaluate failed, fallback to cloud. path={request.url.path}, err={local_eval_error}")

        # 本地 token 无效时，回退到云端校验
        state = _evaluate_access_by_cloud_token(token)
        _dbg(f"cloud_eval after local_fail state={state}")
        if state is None:
            msg = "登录已失效，请重新登录会员中心"
            reason = "auth_invalid"
            if local_eval_error and ("过期" in local_eval_error or "失效" in local_eval_error):
                msg = "会员登录已过期，请重新登录会员中心"
                reason = "auth_expired"
            logger.warning(f"membership_guard: auth rejected after local+cloud checks. path={request.url.path}, device_id={device_id}, local_err={local_eval_error}")
            _raise_auth_http(401, msg, reason)

    # 关键修复：本地判定非会员/未绑定时，也尝试云端复核，避免本地快照陈旧误伤
    reason = str((state or {}).get("reason") or "")
    if state and (not bool(state.get("allowed"))) and reason in {"store_not_bound", "not_member"}:
        cloud_state = None
        if _cloud_override_enabled():
            t = str(token or "").strip()
            now = time.time()
            last = float(_CLOUD_OVERRIDE_LAST.get(t) or 0)
            if now - last >= _CLOUD_OVERRIDE_MIN_INTERVAL_SEC:
                _CLOUD_OVERRIDE_LAST[t] = now
                cloud_state = _evaluate_access_by_cloud_token(token)
        if cloud_state and bool(cloud_state.get("allowed")):
            logger.info(
                f"membership_guard: cloud override allow. path={request.url.path}, local_reason={reason}, cloud_reason={cloud_state.get('reason')}"
            )
            state = cloud_state
            reason = str(cloud_state.get("reason") or "")
        elif cloud_state:
            # 云端明确拒绝时，以云端结果为准（原因更接近真实状态）
            logger.info(
                f"membership_guard: cloud override deny. path={request.url.path}, local_reason={reason}, cloud_reason={cloud_state.get('reason')}"
            )
            state = cloud_state
            reason = str(cloud_state.get("reason") or "")

    if bool((state or {}).get("allowed")):
        _dbg(f"final allow path={request.url.path} reason={(state or {}).get('reason')}")
        logger.info(f"membership_guard: access granted. path={request.url.path}, reason={(state or {}).get('reason')}")
        return

    _dbg(f"final deny path={request.url.path} reason={reason} local_err={local_eval_error}")
    logger.info(f"membership_guard: access denied. path={request.url.path}, reason={reason}")
    if reason == "store_not_bound":
        if is_admin_access(token, x_admin_key):
            _dbg(f"admin bypass store_not_bound path={request.url.path}")
            return
        _raise_auth_http(403, "当前账户未绑定店铺，请先绑定店铺", "store_not_bound")

    if reason == "not_member":
        _raise_auth_http(403, "试用期已过且非会员，请先充值或兑换会员", "not_member")

    _raise_auth_http(403, "当前账户无访问权限，请联系管理员", reason or "forbidden")

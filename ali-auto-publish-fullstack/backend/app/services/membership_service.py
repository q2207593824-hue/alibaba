# -*- coding: utf-8 -*-
"""
会员/积分/邀请/充值（V1）
说明：当前为可运行的第一版（SQLite + Mock支付回调），后续可替换为正式微信/支付宝网关。
"""
import http.client
import os
import socket
import sqlite3
import ssl
import threading
import time
import urllib.request
from urllib.parse import urlparse

import requests
import urllib3
from requests import Response
from requests.structures import CaseInsensitiveDict

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
import uuid
import hashlib
import hmac
import json
import secrets
from datetime import datetime, timedelta
from typing import Any, Dict, Optional, List, Tuple

from app.core.settings import DATA_DIR, get_config

DB_PATH = os.path.join(DATA_DIR, "membership.db")
CLOUD_MEMBERSHIP_API_BASE = os.getenv(
    "CLOUD_MEMBERSHIP_API_BASE", "https://echo-yiwu.cloud/api/membership"
).rstrip("/")
CLOUD_MEMBERSHIP_ME_URL = f"{CLOUD_MEMBERSHIP_API_BASE}/me"

_CLOUD_ME_CACHE: Dict[str, Dict[str, Any]] = {}
_CLOUD_ME_LOCK = threading.Lock()
_CLOUD_ME_TTL_SECONDS = 30
# /me：积分预检等场景；略高于旧 (1,2)s，减轻偶发误判「云端不可用」
_CLOUD_ME_HTTP_TIMEOUT = (float(os.getenv("CLOUD_ME_CONNECT_TIMEOUT_SEC", "3")), float(os.getenv("CLOUD_ME_READ_TIMEOUT_SEC", "8")))
# /auth/login：缩短超时以加快降级，避免云端不可达时阻塞用户登录
_CLOUD_LOGIN_HTTP_TIMEOUT = (
    float(os.getenv("CLOUD_LOGIN_CONNECT_TIMEOUT_SEC", "3")),
    float(os.getenv("CLOUD_LOGIN_READ_TIMEOUT_SEC", "8")),
)

_CLOUD_MEMBERSHIP_IP_FALLBACK = os.getenv("CLOUD_MEMBERSHIP_API_IP", "43.164.196.172").strip()
_CLOUD_PUBLIC_HOST = os.getenv("CLOUD_MEMBERSHIP_PUBLIC_HOST", "echo-yiwu.cloud").strip() or "echo-yiwu.cloud"
_DOH_CACHE: Dict[str, Tuple[float, List[str]]] = {}
_DOH_TTL_SECONDS = int(os.getenv("CLOUD_DOH_CACHE_SEC", "300"))


def apply_cloud_network_bypass() -> None:
    host = _CLOUD_PUBLIC_HOST
    for key in ("NO_PROXY", "no_proxy"):
        parts = [p.strip() for p in os.environ.get(key, "").split(",") if p.strip()]
        for item in ("127.0.0.1", "localhost", host, f".{host}"):
            if item not in parts:
                parts.append(item)
        os.environ[key] = ",".join(parts)
    if os.getenv("ALI_CLOUD_BYPASS_PROXY", "1").strip().lower() not in {"1", "true", "yes"}:
        return
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
        os.environ.pop(key, None)


apply_cloud_network_bypass()


def _is_fake_clash_ip(ip: str) -> bool:
    s = str(ip or "").strip()
    return s.startswith("198.18.") or s.startswith("198.19.") or s.startswith("28.0.0.")


def _host_resolves_to_fake_dns(host: str) -> bool:
    h = str(host or "").strip()
    if not h or h.replace(".", "").isdigit():
        return False
    try:
        return _is_fake_clash_ip(socket.gethostbyname(h))
    except Exception:
        return False


def _cloud_ip_candidates() -> List[str]:
    ips: List[str] = []
    multi = os.getenv("CLOUD_MEMBERSHIP_API_IPS", "").strip()
    if multi:
        ips.extend([x.strip() for x in multi.split(",") if x.strip()])
    if _CLOUD_MEMBERSHIP_IP_FALLBACK and _CLOUD_MEMBERSHIP_IP_FALLBACK not in ips:
        ips.insert(0, _CLOUD_MEMBERSHIP_IP_FALLBACK)
    legacy = "43.154.196.172"
    if legacy not in ips:
        ips.append(legacy)
    out: List[str] = []
    for ip in ips:
        if ip and not _is_fake_clash_ip(ip) and ip not in out:
            out.append(ip)
    return out


def _resolve_host_via_doh(host: str) -> List[str]:
    h = str(host or "").strip()
    if not h:
        return []
    now = time.time()
    cached = _DOH_CACHE.get(h)
    if cached and now - cached[0] < _DOH_TTL_SECONDS:
        return list(cached[1])
    ips: List[str] = []
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for doh_url in (
        f"https://dns.google/resolve?name={h}&type=A",
        f"https://cloudflare-dns.com/dns-query?name={h}&type=A",
    ):
        try:
            req = urllib.request.Request(doh_url, headers={"Accept": "application/dns-json"})
            with opener.open(req, timeout=6) as resp:
                data = json.loads(resp.read().decode("utf-8", errors="ignore"))
            for ans in data.get("Answer") or []:
                if int(ans.get("type") or 0) != 1:
                    continue
                ip = str(ans.get("data") or "").strip()
                if ip and not _is_fake_clash_ip(ip) and ip not in ips:
                    ips.append(ip)
            if ips:
                break
        except Exception:
            continue
    _DOH_CACHE[h] = (now, ips)
    return ips


def _collect_cloud_target_ips(public_host: str) -> List[str]:
    ips: List[str] = []
    ips.extend(_resolve_host_via_doh(public_host))
    ips.extend(_cloud_ip_candidates())
    out: List[str] = []
    for ip in ips:
        if ip and ip not in out and not _is_fake_clash_ip(ip):
            out.append(ip)
    return out


def _normalize_cloud_timeout(timeout: Any) -> Tuple[float, float]:
    if timeout is None:
        return _CLOUD_LOGIN_HTTP_TIMEOUT
    if isinstance(timeout, (int, float)):
        t = float(timeout)
        return (t, t)
    if isinstance(timeout, (list, tuple)) and len(timeout) >= 2:
        return (float(timeout[0]), float(timeout[1]))
    return _CLOUD_LOGIN_HTTP_TIMEOUT


def _build_requests_response(http_resp: http.client.HTTPResponse, *, url: str, method: str) -> Response:
    r = Response()
    r.status_code = int(http_resp.status)
    r.reason = str(http_resp.reason)
    r.headers = CaseInsensitiveDict(http_resp.getheaders())
    r._content = http_resp.read()
    r.url = url
    r.request = requests.Request(method=method, url=url).prepare()
    return r


def _cloud_http_request_via_ip_sni(
    method: str,
    url: str,
    ip: str,
    public_host: str,
    *,
    timeout: Any = None,
    **kwargs: Any,
) -> Response:
    parsed = urlparse(url)
    path = parsed.path or "/"
    if parsed.query:
        path = f"{path}?{parsed.query}"
    port = parsed.port or 443
    connect_timeout, read_timeout = _normalize_cloud_timeout(timeout)
    headers = dict(kwargs.get("headers") or {})
    headers["Host"] = public_host
    headers.setdefault("Connection", "close")
    body_bytes: Optional[bytes] = None
    if kwargs.get("json") is not None:
        body_bytes = json.dumps(kwargs["json"], ensure_ascii=False).encode("utf-8")
        headers.setdefault("Content-Type", "application/json")
    elif kwargs.get("data") is not None:
        data = kwargs["data"]
        body_bytes = data.encode("utf-8") if isinstance(data, str) else data
    sock = socket.create_connection((ip, port), timeout=connect_timeout)
    ctx = ssl.create_default_context()
    if kwargs.get("verify") is False:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    sock = ctx.wrap_socket(sock, server_hostname=public_host)
    conn = http.client.HTTPSConnection(public_host, port=port, timeout=read_timeout)
    conn.sock = sock
    try:
        if body_bytes is not None:
            headers["Content-Length"] = str(len(body_bytes))
            conn.request(method.upper(), path, body=body_bytes, headers=headers)
        else:
            conn.request(method.upper(), path, headers=headers)
        return _build_requests_response(conn.getresponse(), url=url, method=method)
    finally:
        try:
            conn.close()
        except Exception:
            pass
        try:
            sock.close()
        except Exception:
            pass


def _cloud_http_request(method: str, url: str, *, timeout=None, **kwargs) -> requests.Response:
    """访问云端会员 API：DoH 真实 IP + HTTPS SNI，绕过 VPN/Clash 假 DNS。"""
    parsed = urlparse(url)
    host = (parsed.hostname or "").strip()
    public_host = _CLOUD_PUBLIC_HOST
    fake_dns = _host_resolves_to_fake_dns(public_host)
    if host and not host.replace(".", "").isdigit():
        fake_dns = fake_dns or _host_resolves_to_fake_dns(host)
    target_ips = _collect_cloud_target_ips(public_host)
    retry_codes = {401, 403, 404, 502, 503, 504}
    last_exc: Optional[Exception] = None
    for ip in target_ips:
        try:
            resp = _cloud_http_request_via_ip_sni(method, url, ip, public_host, timeout=timeout, **kwargs)
            if resp.status_code in retry_codes and ip != target_ips[-1]:
                continue
            return resp
        except Exception as exc:
            last_exc = exc
            continue
    if not fake_dns and host and not host.replace(".", "").isdigit():
        for trust_env in (False, True):
            try:
                sess = requests.Session()
                sess.trust_env = trust_env
                proxies = None if trust_env else {"http": None, "https": None}
                return sess.request(
                    method.upper(),
                    url,
                    proxies=proxies,
                    timeout=timeout or _CLOUD_LOGIN_HTTP_TIMEOUT,
                    **kwargs,
                )
            except requests.RequestException as exc:
                last_exc = exc
    if last_exc:
        raise last_exc
    raise requests.RequestException("云端会员服务不可达")


def cloud_quick_unreachable(timeout: Tuple[float, float] = (1.5, 3.0)) -> bool:
    """快速探测云端是否不可达（供本地 python run.py 开发态自动离线登录）。"""
    health_url = CLOUD_MEMBERSHIP_API_BASE.replace("/api/membership", "/api/health")
    try:
        resp = _cloud_http_request("GET", health_url, timeout=timeout)
        return not resp.ok
    except Exception:
        return True


def check_cloud_connectivity() -> Dict[str, Any]:
    """供桌面端诊断：云端是否可达、是否命中假 DNS。"""
    health_url = CLOUD_MEMBERSHIP_API_BASE.replace("/api/membership", "/api/health")
    fake_dns = _host_resolves_to_fake_dns(_CLOUD_PUBLIC_HOST)
    resolved_ips = _collect_cloud_target_ips(_CLOUD_PUBLIC_HOST)
    base = {
        "fake_dns": fake_dns,
        "cloud_base": CLOUD_MEMBERSHIP_API_BASE,
        "ip_fallback": _CLOUD_MEMBERSHIP_IP_FALLBACK,
        "resolved_ips": resolved_ips,
        "db_path": DB_PATH,
        "cloud_host_mode": _is_cloud_membership_host(),
        "membership_points_source": os.getenv("MEMBERSHIP_POINTS_SOURCE", ""),
        "ali_app_data_dir": os.getenv("ALI_APP_DATA_DIR", ""),
    }
    try:
        resp = _cloud_http_request("GET", health_url, timeout=(4, 12))
        return {**base, "ok": resp.ok, "status_code": resp.status_code}
    except Exception as e:
        return {**base, "ok": False, "error": str(e)}


def _is_cloud_membership_host() -> bool:
    """本机即云端会员主机：积分/登录只读写本机库，禁止再请求公网 membership API。"""
    return os.getenv("MEMBERSHIP_IS_CLOUD_HOST", "").strip().lower() in {"1", "true", "yes"}


def use_cloud_points() -> bool:
    """桌面端默认以云端积分为准；云端主机或 ALI_OFFLINE_DEV 时走本机库。"""
    if _is_cloud_membership_host():
        return False
    return os.getenv("MEMBERSHIP_POINTS_SOURCE", "cloud").strip().lower() != "local"


def _cloud_auth_headers(token: str) -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {(token or '').strip()}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


def _parse_cloud_http_error(resp: requests.Response) -> str:
    try:
        payload = resp.json() or {}
        detail = payload.get("detail") if isinstance(payload, dict) else None
        if isinstance(detail, dict):
            return str(detail.get("message") or detail.get("msg") or detail)
        if isinstance(detail, str) and detail.strip():
            return detail.strip()
        if isinstance(payload, dict) and str(payload.get("message") or "").strip():
            return str(payload.get("message")).strip()
    except Exception:
        pass
    return f"云端请求失败({resp.status_code})"


def _invalidate_cloud_me_cache(token: str) -> None:
    t = (token or "").strip()
    if not t:
        return
    with _CLOUD_ME_LOCK:
        _CLOUD_ME_CACHE.pop(t, None)
    try:
        from app.core import membership_guard as mg

        cache = getattr(mg, "_CLOUD_ME_CACHE", None)
        lock = getattr(mg, "_CLOUD_ME_LOCK", None)
        if cache is not None and lock is not None:
            with lock:
                cache.pop(t, None)
    except Exception:
        pass


def _cloud_me_cache_get(token: str, *, max_age: int = _CLOUD_ME_TTL_SECONDS) -> Optional[Dict[str, Any]]:
    """仅读内存缓存，不发起网络请求（供 /me 快速响应）。"""
    t = (token or "").strip()
    if not t:
        return None
    now = time.time()
    with _CLOUD_ME_LOCK:
        cached = _CLOUD_ME_CACHE.get(t)
        if cached and (now - float(cached.get("ts") or 0) < max_age):
            info = cached.get("info")
            return info if isinstance(info, dict) else None
    return None


def fetch_cloud_me_cached(token: str, *, allow_stale: bool = True) -> Optional[Dict[str, Any]]:
    t = (token or "").strip()
    if not t:
        return None
    cached_info = _cloud_me_cache_get(t)
    if cached_info is not None:
        return cached_info

    now = time.time()
    try:
        resp = _cloud_http_request(
            "GET",
            CLOUD_MEMBERSHIP_ME_URL,
            headers=_cloud_auth_headers(t),
            timeout=_CLOUD_ME_HTTP_TIMEOUT,
        )
        if not resp.ok:
            status = getattr(resp, "status_code", 0) or 0
            if status in (401, 403):
                raise ValueError("登录会话在云端失效，请重新登录会员账号")
            if allow_stale:
                with _CLOUD_ME_LOCK:
                    stale = _CLOUD_ME_CACHE.get(t)
                    info = stale.get("info") if stale else None
                    if isinstance(info, dict):
                        return info
            return None
        payload = resp.json() or {}
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, dict):
            if allow_stale:
                with _CLOUD_ME_LOCK:
                    stale = _CLOUD_ME_CACHE.get(t)
                    info = stale.get("info") if stale else None
                    if isinstance(info, dict):
                        return info
            return None
        with _CLOUD_ME_LOCK:
            _CLOUD_ME_CACHE[t] = {"ts": now, "info": data}
        return data
    except ValueError:
        raise
    except Exception:
        if allow_stale:
            with _CLOUD_ME_LOCK:
                stale = _CLOUD_ME_CACHE.get(t)
                info = stale.get("info") if stale else None
                if isinstance(info, dict):
                    return info
        return None


CLOUD_POINTS_UNAVAILABLE_MSG = "云端积分服务暂不可用，请稍后重试"


def _looks_like_local_only_token(token: str) -> bool:
    """本地 login() 曾签发的 uuid4.hex（32 位十六进制），云端 JWT 通常更长且含 '.'。"""
    t = (token or "").strip()
    return len(t) == 32 and all(c in "0123456789abcdef" for c in t.lower())


def _token_requires_cloud_resolve(token: str) -> bool:
    """仅云端 JWT 形态才在本地无会话时请求云端 /me；随机字符串快速 401。"""
    t = (token or "").strip()
    if not t:
        return False
    if _looks_like_local_only_token(t):
        return False
    return t.count(".") >= 2 and len(t) > 40


def _fetch_cloud_me_or_raise(token: str) -> Dict[str, Any]:
    """云端积分模式下必须拿到云端 /me，失败则抛错（禁止回退本地或当作 0 分）。"""
    t = (token or "").strip()
    if not t:
        raise ValueError("登录已失效，请重新登录")
    data = fetch_cloud_me_cached(t, allow_stale=True)
    if not isinstance(data, dict):
        raise ValueError(CLOUD_POINTS_UNAVAILABLE_MSG)
    return data


def cloud_get_points_balance(token: str) -> float:
    data = _fetch_cloud_me_or_raise(token)
    return round(float(data.get("points_balance") or 0), 4)


def cloud_list_ledger(token: str, limit: int = 50) -> List[Dict[str, Any]]:
    t = (token or "").strip()
    if not t:
        raise ValueError("登录已失效，请重新登录")
    resp = _cloud_http_request(
        "GET",
        f"{CLOUD_MEMBERSHIP_API_BASE}/points/ledger",
        headers=_cloud_auth_headers(t),
        params={"limit": max(1, min(int(limit), 200))},
        timeout=(1, 3),
    )
    if not resp.ok:
        raise ValueError(_parse_cloud_http_error(resp))
    payload = resp.json() or {}
    rows = payload.get("data") if isinstance(payload, dict) else None
    return list(rows) if isinstance(rows, list) else []


def _membership_financial_must_proxy_cloud() -> bool:
    """桌面端：充值/兑换/提现写操作只走云端，禁止静默落本地库。"""
    return use_cloud_points() and _membership_cloud_sync_enabled()


def _proxy_membership_write_to_cloud(
    method: str,
    path: str,
    token: str,
    *,
    json_body: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    t = (token or "").strip()
    if not t:
        raise ValueError("登录已失效，请重新登录")
    p = path if str(path).startswith("/") else f"/{path}"
    url = f"{CLOUD_MEMBERSHIP_API_BASE.rstrip('/')}{p}"
    resp = _cloud_http_request(
        method.upper(),
        url,
        json=json_body or {},
        headers=_cloud_auth_headers(t),
        timeout=(5, 30),
    )
    if not resp.ok:
        raise ValueError(_parse_cloud_http_error(resp))
    payload = resp.json() if resp.content else {}
    if isinstance(payload, dict) and payload.get("data") is not None:
        data = payload.get("data")
        _invalidate_cloud_me_cache(t)
        return data if isinstance(data, dict) else {"result": data}
    _invalidate_cloud_me_cache(t)
    return payload if isinstance(payload, dict) else {}


def cloud_consume_points(
    token: str,
    amount: float,
    biz_type: str,
    biz_id: Optional[str] = None,
    remark: str = "",
) -> Dict[str, Any]:
    """调用云端扣积分（需云端已部署 POST /membership/points/consume）。"""
    t = (token or "").strip()
    if not t:
        raise ValueError("登录已失效，请重新登录")
    amount = round(float(amount), 4)
    if amount <= 0:
        return {"amount": 0, "deducted": 0, "balance": cloud_get_points_balance(t)}

    resp = _cloud_http_request(
        "POST",
        f"{CLOUD_MEMBERSHIP_API_BASE}/points/consume",
        json={
            "amount": amount,
            "biz_type": str(biz_type or "consume"),
            "biz_id": biz_id,
            "remark": str(remark or ""),
        },
        headers=_cloud_auth_headers(t),
        timeout=(5, 20),
    )
    if not resp.ok:
        raise ValueError(_parse_cloud_http_error(resp))

    payload = resp.json() or {}
    data = payload.get("data") if isinstance(payload, dict) else None
    _invalidate_cloud_me_cache(t)
    if isinstance(data, dict):
        balance = data.get("balance")
        if balance is not None:
            try:
                uid = resolve_user_id_by_token(t)
                _write_local_points_balance(uid, float(balance))
            except Exception:
                pass
        _mirror_cloud_consume_to_local_ledger(
            t,
            amount,
            str(biz_type or "consume"),
            biz_id,
            str(remark or ""),
            float(balance) if balance is not None else None,
        )
        return data
    balance = cloud_get_points_balance(t)
    try:
        uid = resolve_user_id_by_token(t)
        _write_local_points_balance(uid, balance)
    except Exception:
        pass
    _mirror_cloud_consume_to_local_ledger(
        t,
        amount,
        str(biz_type or "consume"),
        biz_id,
        str(remark or ""),
        float(balance),
    )
    return {"deducted": amount, "balance": balance}


# 云端扣分成功后，本地也落一条镜像流水，保证会员中心实时可见（云端流水接口偶发慢时也可回退展示）
def _mirror_cloud_consume_to_local_ledger(
    token: str,
    amount: float,
    biz_type: str,
    biz_id: Optional[str],
    remark: str,
    balance_after: Optional[float],
) -> None:
    try:
        uid = resolve_user_id_by_token(token)
    except Exception:
        return

    amt = round(abs(float(amount or 0)), 4)
    if amt <= 0:
        return

    init_db()
    conn = _conn()
    cur = conn.cursor()
    try:
        _create_points_account_if_needed(cur, uid)
        acc = cur.execute("SELECT * FROM user_points_accounts WHERE user_id=?", (uid,)).fetchone()
        local_before = _points_balance_from_row(acc)
        if balance_after is None:
            new_balance = round(max(0.0, local_before - amt), 4)
        else:
            new_balance = round(max(0.0, float(balance_after)), 4)

        cur.execute(
            """
            UPDATE user_points_accounts
            SET balance_real=?, balance=?, points_fractional_debt=0, updated_at=?
            WHERE user_id=?
            """,
            (new_balance, int(new_balance), _now_str(), uid),
        )
        cur.execute(
            """
            INSERT INTO user_points_ledger(
              user_id,change_amount,balance_after,biz_type,biz_id,remark,created_at,
              change_amount_real,balance_after_real
            ) VALUES(?,?,?,?,?,?,?,?,?)
            """,
            (
                uid,
                -int(amt),
                int(new_balance),
                str(biz_type or "consume"),
                biz_id,
                str(remark or ""),
                _now_str(),
                -amt,
                new_balance,
            ),
        )
        conn.commit()
    except Exception:
        conn.rollback()
    finally:
        conn.close()


# ---------- 积分云端双向同步 ----------
_CLOUD_USER_ID_CACHE: Dict[str, int] = {}
_CLOUD_ADMIN_USERS_CACHE: Dict[str, Any] = {"ts": 0.0, "rows": []}
_CLOUD_SYNC_LOCK = threading.Lock()
_CLOUD_ADMIN_USERS_TTL = 8


def _membership_cloud_sync_enabled() -> bool:
    """是否向远程云端同步（本机即云端主机时可关闭）。"""
    if os.getenv("MEMBERSHIP_CLOUD_SYNC", "1").strip().lower() in {"0", "false", "no"}:
        return False
    if os.getenv("MEMBERSHIP_IS_CLOUD_HOST", "").strip().lower() in {"1", "true", "yes"}:
        return False
    base = (CLOUD_MEMBERSHIP_API_BASE or "").strip().lower()
    if not base:
        return False
    if any(h in base for h in ("127.0.0.1", "localhost", "0.0.0.0")):
        return False
    return True


def _get_cloud_admin_key() -> str:
    return (get_config().payment.admin_api_key or "").strip()


def _write_local_points_balance(
    user_id: int,
    balance: float,
    *,
    cur: Optional[sqlite3.Cursor] = None,
) -> None:
    uid = int(user_id or 0)
    if uid <= 0:
        return
    pb = round(max(0.0, float(balance)), 4)
    if cur is not None:
        _create_points_account_if_needed(cur, uid)
        cur.execute(
            """
            UPDATE user_points_accounts
            SET balance_real=?, balance=?, points_fractional_debt=0, updated_at=?
            WHERE user_id=?
            """,
            (pb, int(pb), _now_str(), uid),
        )
        return
    init_db()
    conn = _conn()
    c = conn.cursor()
    _create_points_account_if_needed(c, uid)
    c.execute(
        """
        UPDATE user_points_accounts
        SET balance_real=?, balance=?, points_fractional_debt=0, updated_at=?
        WHERE user_id=?
        """,
        (pb, int(pb), _now_str(), uid),
    )
    conn.commit()
    conn.close()


def _persist_cloud_user_id(
    user_id: int,
    cloud_user_id: int,
    *,
    cur: Optional[sqlite3.Cursor] = None,
    username: str = "",
) -> None:
    cid = int(cloud_user_id or 0)
    if cid <= 0:
        return
    uname = str(username or "").strip()
    if uname:
        with _CLOUD_SYNC_LOCK:
            _CLOUD_USER_ID_CACHE[uname] = cid
    if cur is not None:
        cur.execute("UPDATE users SET cloud_user_id=? WHERE id=?", (cid, int(user_id)))
        return
    init_db()
    conn = _conn()
    c = conn.cursor()
    c.execute("UPDATE users SET cloud_user_id=? WHERE id=?", (cid, int(user_id)))
    conn.commit()
    conn.close()


def _invalidate_cloud_me_cache_for_username(username: str) -> None:
    uname = str(username or "").strip()
    if not uname:
        return
    with _CLOUD_ME_LOCK:
        stale_tokens = []
        for token, cached in list(_CLOUD_ME_CACHE.items()):
            info = cached.get("info") if isinstance(cached, dict) else None
            if isinstance(info, dict) and str(info.get("username") or "").strip() == uname:
                stale_tokens.append(token)
        for token in stale_tokens:
            _CLOUD_ME_CACHE.pop(token, None)
    try:
        from app.core import membership_guard as mg

        with mg._CLOUD_ME_LOCK:
            stale_tokens = []
            for token, cached in list(mg._CLOUD_ME_CACHE.items()):
                info = cached.get("info") if isinstance(cached, dict) else None
                if isinstance(info, dict) and str(info.get("username") or "").strip() == uname:
                    stale_tokens.append(token)
            for token in stale_tokens:
                mg._CLOUD_ME_CACHE.pop(token, None)
    except Exception:
        pass


def _cloud_admin_list_users(*, limit: int = 2000, force_refresh: bool = False) -> List[Dict[str, Any]]:
    if not _membership_cloud_sync_enabled():
        return []
    admin_key = _get_cloud_admin_key()
    if not admin_key:
        return []
    now = time.time()
    with _CLOUD_SYNC_LOCK:
        if (
            not force_refresh
            and _CLOUD_ADMIN_USERS_CACHE.get("rows")
            and (now - float(_CLOUD_ADMIN_USERS_CACHE.get("ts") or 0) < _CLOUD_ADMIN_USERS_TTL)
        ):
            return list(_CLOUD_ADMIN_USERS_CACHE.get("rows") or [])
    try:
        resp = requests.get(
            f"{CLOUD_MEMBERSHIP_API_BASE}/admin/users",
            headers={"X-Admin-Key": admin_key, "Accept": "application/json"},
            params={"limit": max(1, min(int(limit or 2000), 2000))},
            # 管理端用户列表是高频轮询接口，云端不可达时必须快速降级，
            # 否则会拖垮本地 FastAPI worker（并发下表现为全局超时）。
            timeout=(1, 2),
        )
        if not resp.ok:
            return []
        payload = resp.json() or {}
        rows = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(rows, list):
            return []
        with _CLOUD_SYNC_LOCK:
            _CLOUD_ADMIN_USERS_CACHE["ts"] = now
            _CLOUD_ADMIN_USERS_CACHE["rows"] = rows
        return rows
    except Exception:
        with _CLOUD_SYNC_LOCK:
            return list(_CLOUD_ADMIN_USERS_CACHE.get("rows") or [])


def _resolve_cloud_user_id(
    username: str,
    *,
    local_user_id: Optional[int] = None,
    cur: Optional[sqlite3.Cursor] = None,
) -> Optional[int]:
    uname = str(username or "").strip()
    if not uname:
        return None

    close_conn = False
    conn = None
    if cur is None:
        init_db()
        conn = _conn()
        cur = conn.cursor()
        close_conn = True
    try:
        if local_user_id:
            row = cur.execute(
                "SELECT username, cloud_user_id FROM users WHERE id=? LIMIT 1",
                (int(local_user_id),),
            ).fetchone()
        else:
            row = cur.execute(
                "SELECT id, username, cloud_user_id FROM users WHERE username=? LIMIT 1",
                (uname,),
            ).fetchone()
        if row:
            keys = row.keys() if hasattr(row, "keys") else []
            cid = row["cloud_user_id"] if "cloud_user_id" in keys and row["cloud_user_id"] is not None else None
            if cid:
                return int(cid)
            if not local_user_id and "id" in keys:
                local_user_id = int(row["id"])
            if "username" in keys and str(row["username"] or "").strip():
                uname = str(row["username"]).strip()
    finally:
        if close_conn and conn is not None:
            conn.close()

    with _CLOUD_SYNC_LOCK:
        cached = _CLOUD_USER_ID_CACHE.get(uname)
        if cached:
            return int(cached)

    for item in _cloud_admin_list_users():
        if str(item.get("username") or "").strip() == uname:
            cloud_uid = int(item.get("id") or 0)
            if cloud_uid > 0:
                if local_user_id:
                    _persist_cloud_user_id(int(local_user_id), cloud_uid, username=uname)
                with _CLOUD_SYNC_LOCK:
                    _CLOUD_USER_ID_CACHE[uname] = cloud_uid
                return cloud_uid
    return None


def _push_admin_user_update_to_cloud(
    cloud_user_id: int,
    *,
    username: str = "",
    new_password: Optional[str] = None,
    points_balance: Optional[float] = None,
    trial_start_at: Optional[str] = None,
    trial_end_at: Optional[str] = None,
    vip_expire_at: Optional[str] = None,
) -> None:
    """管理员改会员：必须先成功写入云端（权威库），失败则抛错。"""
    if not _membership_cloud_sync_enabled():
        return

    admin_key = _get_cloud_admin_key()
    if not admin_key:
        raise ValueError("未配置云端管理密钥（payment.admin_api_key），无法同步会员信息到云端")

    cloud_uid = int(cloud_user_id or 0)
    if cloud_uid <= 0:
        raise ValueError("云端会员 ID 无效，无法同步")

    payload: Dict[str, Any] = {"user_id": cloud_uid}
    if new_password is not None and str(new_password).strip():
        payload["password"] = str(new_password).strip()
    if points_balance is not None:
        payload["points_balance"] = round(max(0.0, float(points_balance)), 4)
    if trial_start_at is not None and str(trial_start_at).strip():
        payload["trial_start_at"] = str(trial_start_at).strip()
    if trial_end_at is not None and str(trial_end_at).strip():
        payload["trial_end_at"] = str(trial_end_at).strip()
    if vip_expire_at is not None:
        val = str(vip_expire_at).strip()
        payload["vip_expire_at"] = val if val else None

    if len(payload) <= 1:
        return

    try:
        resp = requests.post(
            f"{CLOUD_MEMBERSHIP_API_BASE}/admin/users/update",
            headers={"X-Admin-Key": admin_key, "Content-Type": "application/json"},
            json=payload,
            timeout=(3, 15),
        )
    except requests.RequestException as e:
        raise ValueError(f"云端会员信息同步失败：{e}") from e

    if not resp.ok:
        raise ValueError(f"云端会员信息同步失败：{_parse_cloud_http_error(resp)}")

    uname = str(username or "").strip()
    if uname:
        _invalidate_cloud_me_cache_for_username(uname)
    with _CLOUD_SYNC_LOCK:
        _CLOUD_ADMIN_USERS_CACHE["ts"] = 0.0


def _push_points_balance_to_cloud(
    user_id: int,
    balance: float,
    *,
    username: str = "",
    cur: Optional[sqlite3.Cursor] = None,
) -> bool:
    if not _membership_cloud_sync_enabled():
        return False

    uname = str(username or "").strip()
    if not uname:
        close_conn = False
        conn = None
        if cur is None:
            init_db()
            conn = _conn()
            cur = conn.cursor()
            close_conn = True
        try:
            row = cur.execute("SELECT username FROM users WHERE id=? LIMIT 1", (int(user_id),)).fetchone()
            uname = str(row["username"] or "").strip() if row else ""
        finally:
            if close_conn and conn is not None:
                conn.close()
    if not uname:
        return False

    cloud_uid = _resolve_cloud_user_id(uname, local_user_id=int(user_id), cur=cur)
    if not cloud_uid:
        return False

    try:
        _push_admin_user_update_to_cloud(
            int(cloud_uid),
            username=uname,
            points_balance=round(max(0.0, float(balance)), 4),
        )
        return True
    except ValueError:
        return False


def _pull_points_balance_from_cloud_by_token(token: str) -> Optional[float]:
    t = (token or "").strip()
    if not t or not _membership_cloud_sync_enabled():
        return None
    _invalidate_cloud_me_cache(t)
    data = fetch_cloud_me_cached(t, allow_stale=False)
    if not data:
        return None
    return round(float(data.get("points_balance") or 0), 4)


def sync_points_balance_from_cloud(user_id: int, token: str = "", *, balance: Optional[float] = None) -> None:
    """云端 -> 本地：写入本地积分账户。"""
    uid = int(user_id or 0)
    if uid <= 0:
        return
    pb: Optional[float] = round(float(balance), 4) if balance is not None else None
    if pb is None and token:
        pb = _pull_points_balance_from_cloud_by_token(token)
    if pb is None:
        return
    _write_local_points_balance(uid, pb)


def sync_points_balance_to_cloud(
    user_id: int,
    balance: float,
    *,
    username: str = "",
    cur: Optional[sqlite3.Cursor] = None,
) -> None:
    """本地 -> 云端：管理员改分、本地扣费等后推送。"""
    _push_points_balance_to_cloud(int(user_id), float(balance), username=username, cur=cur)


def sync_points_balance_bidirectional(
    user_id: int,
    balance: float,
    *,
    token: str = "",
    username: str = "",
    cur: Optional[sqlite3.Cursor] = None,
    push_cloud: bool = True,
    pull_cloud: bool = False,
) -> None:
    uid = int(user_id or 0)
    if uid <= 0:
        return
    pb = round(max(0.0, float(balance)), 4)
    _write_local_points_balance(uid, pb, cur=cur)
    if push_cloud:
        sync_points_balance_to_cloud(uid, pb, username=username, cur=cur)
    if pull_cloud and token:
        cloud_pb = _pull_points_balance_from_cloud_by_token(token)
        if cloud_pb is not None:
            _write_local_points_balance(uid, cloud_pb, cur=cur)


def _merge_cloud_points_into_admin_users(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not rows or not _membership_cloud_sync_enabled():
        return rows
    cloud_rows = _cloud_admin_list_users()
    if not cloud_rows:
        return rows
    by_name = {str(r.get("username") or "").strip(): r for r in cloud_rows if str(r.get("username") or "").strip()}
    init_db()
    conn = _conn()
    cur = conn.cursor()
    try:
        for item in rows:
            uname = str(item.get("username") or "").strip()
            cloud_item = by_name.get(uname)
            if not cloud_item:
                continue
            cloud_pb = round(float(cloud_item.get("points_balance") or 0), 4)
            local_uid = int(item.get("id") or 0)
            local_pb = round(float(item.get("points_balance") or 0), 4)
            cloud_uid = int(cloud_item.get("id") or 0)
            if cloud_uid > 0 and local_uid > 0:
                _persist_cloud_user_id(local_uid, cloud_uid, cur=cur, username=uname)
            if abs(cloud_pb - local_pb) > 1e-6:
                _write_local_points_balance(local_uid, cloud_pb, cur=cur)
                item["points_balance"] = cloud_pb
            # 合并云端资料字段：当本地为空而云端有值时，补齐并回写本地 SQLite
            profile_fields = ("company_name", "main_category", "is_verified", "service_years", "page_level_star")
            profile_updates: Dict[str, str] = {}
            for field in profile_fields:
                cloud_val = str(cloud_item.get(field) or "").strip()
                local_val = str(item.get(field) or "").strip()
                if cloud_val and not local_val:
                    item[field] = cloud_val
                    profile_updates[field] = cloud_val
            if profile_updates and local_uid > 0:
                set_clause = ", ".join(f"{f}=?" for f in profile_updates)
                cur.execute(
                    f"UPDATE users SET {set_clause}, created_at=created_at WHERE id=?",
                    (*profile_updates.values(), local_uid),
                )
        conn.commit()
    except Exception:
        conn.rollback()
    finally:
        conn.close()
    return rows


# 简易会话（V1）
_TOKENS: Dict[str, Tuple[int, float]] = {} 
def _clean_stale_tokens():
    now = time.time()
    stale_keys = [k for k, v in _TOKENS.items() if now > v[1]]
    for k in stale_keys:
        _TOKENS.pop(k, None)

def _set_token_cache(token: str, uid: int):
    _clean_stale_tokens()
    # 限制最大长度防 OOM
    if len(_TOKENS) > 10000:
        _TOKENS.clear()
    _TOKENS[token] = (uid, time.time() + SESSION_HOURS * 3600)

def _get_token_cache(token: str) -> Optional[int]:
    val = _TOKENS.get(token)
    if val and time.time() <= val[1]:
        return val[0]
    return None

SESSION_HOURS = 72

# 登录安全基线
LOGIN_FAIL_MAX = 5
LOGIN_FAIL_WINDOW_MINUTES = 15
LOGIN_LOCK_MINUTES = 10


def _now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def _hash_pwd(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _new_invite_code() -> str:
    return uuid.uuid4().hex[:8].upper()


def _new_order_no(prefix: str) -> str:
    return f"{prefix}{datetime.now().strftime('%Y%m%d%H%M%S')}{uuid.uuid4().hex[:6].upper()}"


def _random_password(length: int = 20) -> str:
    length = max(12, int(length or 20))
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789!@#$%^&*"
    return "".join(secrets.choice(alphabet) for _ in range(length))


def _conn() -> sqlite3.Connection:
    os.makedirs(DATA_DIR, exist_ok=True)
    c = sqlite3.connect(DB_PATH, timeout=5.0)
    c.row_factory = sqlite3.Row
    try:
        # 并发读写性能与稳定性优化（管理端列表/心跳等高频接口）
        c.execute("PRAGMA journal_mode=WAL;")
        c.execute("PRAGMA synchronous=NORMAL;")
        c.execute("PRAGMA temp_store=MEMORY;")
        c.execute("PRAGMA cache_size=-8000;")  # ~8MB page cache
    except Exception:
        pass
    return c


def _company_key(company_name: str) -> str:
    return " ".join(str(company_name or "").strip().lower().split())


def _sync_company_membership_by_user(cur: sqlite3.Cursor, user_id: int):
    """公司级会员同步：试用期仅首次绑定生效；后续账号继承公司状态。"""
    u = cur.execute(
        "SELECT id, company_name, trial_start_at, trial_end_at, vip_expire_at FROM users WHERE id=?",
        (int(user_id),),
    ).fetchone()
    if not u:
        return

    company_name = str(u["company_name"] or "").strip()
    key = _company_key(company_name)
    if not key:
        return

    now = _now_str()
    row = cur.execute(
        "SELECT id, trial_start_at, trial_end_at, vip_expire_at FROM company_membership_bindings WHERE company_key=?",
        (key,),
    ).fetchone()

    def _dt(v: Optional[str]):
        s = str(v or "").strip()
        if not s:
            return None
        try:
            return datetime.strptime(s, "%Y-%m-%d %H:%M:%S")
        except Exception:
            return None

    if row:
        # 已绑定公司：试用期不再被新账号重置，统一继承公司绑定值
        bind_trial_start = str(row["trial_start_at"] or "")
        bind_trial_end = str(row["trial_end_at"] or "")

        # VIP 允许叠加：取更晚的过期时间
        bind_vip = str(row["vip_expire_at"] or "").strip()
        user_vip = str(u["vip_expire_at"] or "").strip()
        bind_vip_dt = _dt(bind_vip)
        user_vip_dt = _dt(user_vip)
        chosen_vip = bind_vip
        if user_vip_dt and (not bind_vip_dt or user_vip_dt > bind_vip_dt):
            chosen_vip = user_vip

        cur.execute(
            "UPDATE company_membership_bindings SET company_name=?, vip_expire_at=?, updated_at=? WHERE company_key=?",
            (company_name, chosen_vip or None, now, key),
        )

        cur.execute(
            "UPDATE users SET trial_start_at=?, trial_end_at=?, vip_expire_at=? WHERE lower(trim(company_name))=lower(trim(?))",
            (bind_trial_start, bind_trial_end, chosen_vip or None, company_name),
        )
    else:
        # 首次绑定：沉淀当前账号试用/会员状态到公司绑定
        trial_start = str(u["trial_start_at"] or "")
        trial_end = str(u["trial_end_at"] or "")
        vip_expire = str(u["vip_expire_at"] or "").strip() or None

        cur.execute(
            "INSERT INTO company_membership_bindings(company_key, company_name, first_user_id, trial_start_at, trial_end_at, vip_expire_at, created_at, updated_at) VALUES(?,?,?,?,?,?,?,?)",
            (key, company_name, int(u["id"]), trial_start, trial_end, vip_expire, now, now),
        )

        cur.execute(
            "UPDATE users SET trial_start_at=?, trial_end_at=?, vip_expire_at=? WHERE lower(trim(company_name))=lower(trim(?))",
            (trial_start, trial_end, vip_expire, company_name),
        )


_DB_INIT_DONE = False
_DB_INIT_LOCK = threading.Lock()


def _has_core_membership_schema() -> bool:
    """当前 DATA_DIR 下的 membership.db 是否已有核心会员表（防止仅 agent 表的残缺库）。"""
    try:
        conn = _conn()
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='users' LIMIT 1"
        ).fetchone()
        conn.close()
        return bool(row)
    except Exception:
        return False


def ensure_membership_db_ready() -> None:
    """启动/鉴权前确保本机 membership.db 结构完整。"""
    global _DB_INIT_DONE
    if not _has_core_membership_schema():
        with _DB_INIT_LOCK:
            _DB_INIT_DONE = False
    init_db()


def _ensure_agent_telemetry_schema(cur: sqlite3.Cursor) -> None:
    """增量补齐客户端节点/关键词回传表（兼容旧版 membership.db）。"""
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS agent_nodes (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          agent_id TEXT UNIQUE NOT NULL,
          client_name TEXT NULL,
          machine_id TEXT NULL,
          app_version TEXT NULL,
          license_key TEXT NULL,
          status TEXT NOT NULL DEFAULT 'active',
          last_seen_at TEXT NULL,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS agent_policies (
          agent_id TEXT PRIMARY KEY,
          policy_json TEXT NOT NULL,
          updated_at TEXT NOT NULL
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS keyword_reports (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          agent_id TEXT NOT NULL,
          report_date TEXT NOT NULL,
          source TEXT NULL,
          batch_no TEXT NOT NULL,
          item_count INTEGER NOT NULL DEFAULT 0,
          created_at TEXT NOT NULL,
          UNIQUE(agent_id, report_date, batch_no)
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS keyword_report_items (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          report_id INTEGER NOT NULL,
          keyword TEXT NOT NULL,
          exposure REAL NOT NULL DEFAULT 0,
          click REAL NOT NULL DEFAULT 0,
          ctr REAL NOT NULL DEFAULT 0,
          keyword_index REAL NOT NULL DEFAULT 0,
          product_id TEXT NULL
        )
        """
    )


def _ensure_agent_telemetry_schema_ready() -> None:
    """兼容旧调用：统一走 init_db，禁止单独创建 agent 表而跳过 users。"""
    ensure_membership_db_ready()


def init_db():
    global _DB_INIT_DONE
    with _DB_INIT_LOCK:
        if _DB_INIT_DONE and _has_core_membership_schema():
            return
        # 内存标记已完成但磁盘库残缺（例如切换 DATA_DIR 后仅写了 agent 表）
        _DB_INIT_DONE = False

    conn = _conn()
    cur = conn.cursor()

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          username TEXT UNIQUE NOT NULL,
          password_hash TEXT NOT NULL,
          invite_code TEXT UNIQUE NOT NULL,
          inviter_user_id INTEGER NULL,
          invited_at TEXT NULL,
          trial_start_at TEXT NOT NULL,
          trial_end_at TEXT NOT NULL,
          vip_expire_at TEXT NULL,
          real_name TEXT NULL,
          phone TEXT NULL,
          created_at TEXT NOT NULL
        )
        """
    )

    # users 常用字段索引（用户名/邀请码/公司绑定）
    try:
        cur.execute("CREATE INDEX IF NOT EXISTS idx_users_username ON users(username)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_users_invite_code ON users(invite_code)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_users_company_name ON users(company_name)")
    except Exception:
        pass

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS user_points_accounts (
          user_id INTEGER PRIMARY KEY,
          balance INTEGER NOT NULL DEFAULT 0,
          frozen_balance INTEGER NOT NULL DEFAULT 0,
          total_recharged INTEGER NOT NULL DEFAULT 0,
          total_rewarded INTEGER NOT NULL DEFAULT 0,
          total_spent INTEGER NOT NULL DEFAULT 0,
          points_fractional_debt REAL NOT NULL DEFAULT 0,
          updated_at TEXT NOT NULL
        )
        """
    )
    try:
        cur.execute("CREATE INDEX IF NOT EXISTS idx_points_accounts_user_id ON user_points_accounts(user_id)")
    except Exception:
        pass

    try:
        cols = cur.execute("PRAGMA table_info(user_points_accounts)").fetchall()
        names = {str(r[1]) for r in cols}
        if "points_fractional_debt" not in names:
            cur.execute(
                "ALTER TABLE user_points_accounts ADD COLUMN points_fractional_debt REAL NOT NULL DEFAULT 0"
            )
        if "balance_real" not in names:
            cur.execute("ALTER TABLE user_points_accounts ADD COLUMN balance_real REAL")
        cur.execute(
            """
            UPDATE user_points_accounts
            SET balance_real = ROUND(CAST(balance AS REAL) - COALESCE(points_fractional_debt, 0), 4),
                points_fractional_debt = 0
            WHERE balance_real IS NULL
            """
        )
    except Exception:
        pass

    try:
        ledger_cols = cur.execute("PRAGMA table_info(user_points_ledger)").fetchall()
        ledger_names = {str(r[1]) for r in ledger_cols}
        if "change_amount_real" not in ledger_names:
            cur.execute("ALTER TABLE user_points_ledger ADD COLUMN change_amount_real REAL")
        if "balance_after_real" not in ledger_names:
            cur.execute("ALTER TABLE user_points_ledger ADD COLUMN balance_after_real REAL")
    except Exception:
        pass

    # 兼容历史库：补齐新增字段
    try:
        cur.execute("ALTER TABLE users ADD COLUMN real_name TEXT NULL")
    except Exception:
        pass
    try:
        cur.execute("ALTER TABLE users ADD COLUMN phone TEXT NULL")
    except Exception:
        pass
    try:
        cur.execute("ALTER TABLE users ADD COLUMN company_name TEXT NULL")
    except Exception:
        pass
    try:
        cur.execute("ALTER TABLE users ADD COLUMN main_category TEXT NULL")
    except Exception:
        pass
    try:
        cur.execute("ALTER TABLE users ADD COLUMN is_verified TEXT NULL")
    except Exception:
        pass
    try:
        cur.execute("ALTER TABLE users ADD COLUMN service_years TEXT NULL")
    except Exception:
        pass
    try:
        cur.execute("ALTER TABLE users ADD COLUMN page_level_star TEXT NULL")
    except Exception:
        pass
    try:
        cur.execute("ALTER TABLE users ADD COLUMN cloud_user_id INTEGER NULL")
    except Exception:
        pass

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS user_points_ledger (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          user_id INTEGER NOT NULL,
          change_amount INTEGER NOT NULL,
          balance_after INTEGER NOT NULL,
          biz_type TEXT NOT NULL,
          biz_id TEXT NULL,
          remark TEXT NULL,
          created_at TEXT NOT NULL
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS recharge_orders (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          order_no TEXT UNIQUE NOT NULL,
          user_id INTEGER NOT NULL,
          channel TEXT NOT NULL,
          amount_yuan REAL NOT NULL,
          points INTEGER NOT NULL,
          status TEXT NOT NULL,
          paid_at TEXT NULL,
          transaction_id TEXT NULL,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS invite_rewards (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          inviter_user_id INTEGER NOT NULL,
          invitee_user_id INTEGER UNIQUE NOT NULL,
          trigger_recharge_order_id INTEGER NOT NULL,
          reward_points INTEGER NOT NULL DEFAULT 500,
          status TEXT NOT NULL,
          granted_at TEXT NULL,
          created_at TEXT NOT NULL
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS vip_redeem_orders (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          redeem_no TEXT UNIQUE NOT NULL,
          user_id INTEGER NOT NULL,
          points_cost INTEGER NOT NULL,
          months INTEGER NOT NULL,
          vip_start_at TEXT NOT NULL,
          vip_end_at TEXT NOT NULL,
          status TEXT NOT NULL,
          created_at TEXT NOT NULL
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS withdraw_orders (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          withdraw_no TEXT UNIQUE NOT NULL,
          user_id INTEGER NOT NULL,
          points INTEGER NOT NULL,
          amount_yuan REAL NOT NULL,
          status TEXT NOT NULL,
          pay_channel TEXT NULL,
          pay_account TEXT NULL,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS user_sessions (
          token TEXT PRIMARY KEY,
          user_id INTEGER NOT NULL,
          created_at TEXT NOT NULL,
          expire_at TEXT NOT NULL,
          last_seen_at TEXT NULL,
          token_hash TEXT NULL,
          device_id TEXT NULL
        )
        """
    )

    # 常用查询索引（解决管理端列表/在线状态统计慢、并发下易超时）
    try:
        cur.execute("CREATE INDEX IF NOT EXISTS idx_user_sessions_user_id ON user_sessions(user_id)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_user_sessions_last_seen ON user_sessions(last_seen_at)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_user_sessions_user_last_seen ON user_sessions(user_id, last_seen_at)")
        
        # [性能优化] 为流水和订单表补充索引，解决全表扫描导致的严重卡顿
        cur.execute("CREATE INDEX IF NOT EXISTS idx_points_ledger_user_id ON user_points_ledger(user_id)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_recharge_orders_user_id ON recharge_orders(user_id)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_withdraw_orders_user_id ON withdraw_orders(user_id)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_withdraw_orders_status ON withdraw_orders(status)")
    except Exception:
        pass

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS auth_login_events (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          login_type TEXT NOT NULL,
          username TEXT NOT NULL,
          ip TEXT NULL,
          user_agent TEXT NULL,
          success INTEGER NOT NULL,
          reason TEXT NULL,
          created_at TEXT NOT NULL
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS auth_login_locks (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          login_type TEXT NOT NULL,
          username TEXT NOT NULL,
          fail_count INTEGER NOT NULL DEFAULT 0,
          first_fail_at TEXT NOT NULL,
          last_fail_at TEXT NOT NULL,
          locked_until TEXT NULL,
          updated_at TEXT NOT NULL,
          UNIQUE(login_type, username)
        )
        """
    )

    # 管理员账号表（替代写在配置中的明文账号密码）
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS admin_accounts (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          username TEXT UNIQUE NOT NULL,
          password_hash TEXT NOT NULL,
          is_active INTEGER NOT NULL DEFAULT 1,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        )
        """
    )

    # 兼容旧库：补齐 user_sessions 字段
    try:
        cols = cur.execute("PRAGMA table_info(user_sessions)").fetchall()
        names = {str(r[1]) for r in cols}
        if "last_seen_at" not in names:
            cur.execute("ALTER TABLE user_sessions ADD COLUMN last_seen_at TEXT NULL")
        if "token_hash" not in names:
            cur.execute("ALTER TABLE user_sessions ADD COLUMN token_hash TEXT NULL")
        if "device_id" not in names:
            cur.execute("ALTER TABLE user_sessions ADD COLUMN device_id TEXT NULL")
    except Exception:
        pass

    # 公司级会员绑定：同一公司共享试用/会员到期状态（防止重复注册薅试用）
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS company_membership_bindings (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          company_key TEXT UNIQUE NOT NULL,
          company_name TEXT NOT NULL,
          first_user_id INTEGER NOT NULL,
          trial_start_at TEXT NOT NULL,
          trial_end_at TEXT NOT NULL,
          vip_expire_at TEXT NULL,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        )
        """
    )

    # 会员强制控制（总部可强开/强关）
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS user_access_controls (
          user_id INTEGER PRIMARY KEY,
          mode TEXT NOT NULL DEFAULT 'normal',
          note TEXT NULL,
          updated_at TEXT NOT NULL
        )
        """
    )

    # 客户端节点注册与心跳
    _ensure_agent_telemetry_schema(cur)

    try:
        from app.services.app_runtime_settings_service import ensure_app_runtime_settings_schema

        ensure_app_runtime_settings_schema(cur)
    except Exception:
        pass

    # 管理员账号仅存放在 admin_accounts 表，请用 scripts/create_admin_account.py 创建，勿在代码中内置

    conn.commit()
    conn.close()
    with _DB_INIT_LOCK:
        _DB_INIT_DONE = True


def _create_points_account_if_needed(cur: sqlite3.Cursor, user_id: int):
    row = cur.execute("SELECT user_id FROM user_points_accounts WHERE user_id=?", (user_id,)).fetchone()
    if not row:
        cur.execute(
            """
            INSERT INTO user_points_accounts(
              user_id,balance,balance_real,frozen_balance,total_recharged,total_rewarded,total_spent,
              points_fractional_debt,updated_at
            ) VALUES(?,?,?,?,?,?,?,?,?)
            """,
            (user_id, 0, 0.0, 0, 0, 0, 0, 0, _now_str()),
        )


def _points_balance_from_row(acc: Optional[sqlite3.Row]) -> float:
    if not acc:
        return 0.0
    keys = acc.keys() if hasattr(acc, "keys") else []
    if "balance_real" in keys and acc["balance_real"] is not None:
        return round(max(0.0, float(acc["balance_real"])), 4)
    legacy = float(acc["balance"] or 0) - float(acc["points_fractional_debt"] or 0)
    return round(max(0.0, legacy), 4)


def _apply_points_delta(
    cur: sqlite3.Cursor,
    user_id: int,
    delta: float,
    biz_type: str,
    biz_id: Optional[str] = None,
    remark: str = "",
) -> float:
    """实时增减积分（支持小数）；写入 balance_real 与流水。"""
    delta = round(float(delta), 4)
    _create_points_account_if_needed(cur, user_id)
    acc = cur.execute("SELECT * FROM user_points_accounts WHERE user_id=?", (user_id,)).fetchone()
    balance = _points_balance_from_row(acc)
    new_balance = round(balance + delta, 4)
    if new_balance < -1e-6:
        raise ValueError("积分不足")
    new_balance = max(0.0, new_balance)

    total_recharged = float(acc["total_recharged"] or 0)
    total_rewarded = float(acc["total_rewarded"] or 0)
    total_spent = float(acc["total_spent"] or 0)
    if biz_type == "recharge":
        total_recharged = round(total_recharged + max(0.0, delta), 4)
    elif biz_type == "invite_reward":
        total_rewarded = round(total_rewarded + max(0.0, delta), 4)
    elif delta < 0:
        total_spent = round(total_spent + abs(delta), 4)

    cur.execute(
        """
        UPDATE user_points_accounts
        SET balance_real=?, balance=?, points_fractional_debt=0,
            total_recharged=?, total_rewarded=?, total_spent=?, updated_at=?
        WHERE user_id=?
        """,
        (
            new_balance,
            int(new_balance),
            total_recharged,
            total_rewarded,
            total_spent,
            _now_str(),
            user_id,
        ),
    )
    cur.execute(
        """
        INSERT INTO user_points_ledger(
          user_id,change_amount,balance_after,biz_type,biz_id,remark,created_at,
          change_amount_real,balance_after_real
        ) VALUES(?,?,?,?,?,?,?,?,?)
        """,
        (
            user_id,
            int(round(delta)),
            int(round(new_balance)),
            biz_type,
            biz_id,
            remark,
            _now_str(),
            delta,
            new_balance,
        ),
    )
    return new_balance


def _add_points(cur: sqlite3.Cursor, user_id: int, delta: int, biz_type: str, biz_id: Optional[str] = None, remark: str = ""):
    _apply_points_delta(cur, user_id, float(delta), biz_type, biz_id, remark)


# 默认扣费（config.json 未配置 points_pricing 时使用）
_DEFAULT_AI_IMAGE_POINTS_COST: Dict[str, float] = {
    "1K": 0.6,
    "2K": 0.7,
    "4K": 0.85,
}
_DEFAULT_TITLE_OPTIMIZE_POINTS_COST = 0.2
_DEFAULT_TRAFFIC_AI_POINTS_COST = 0.5
_points_ai_image_lock = threading.Lock()
_points_fractional_lock = threading.Lock()


def _points_pricing_cfg():
    from app.services.app_runtime_settings_service import get_effective_points_pricing_config

    return get_effective_points_pricing_config()


def get_points_pricing_snapshot() -> Dict[str, Any]:
    return {
        "title_optimize_per_item": get_title_optimize_points_cost(),
        "traffic_ai_per_run": get_traffic_ai_points_cost(),
        "ai_image_cost_per_size": {
            "1K": get_ai_image_points_cost("1K"),
            "2K": get_ai_image_points_cost("2K"),
            "4K": get_ai_image_points_cost("4K"),
        },
    }


def get_ai_image_points_cost(image_size: str) -> float:
    pp = _points_pricing_cfg()
    costs = {
        "1K": float(pp.ai_image_1k),
        "2K": float(pp.ai_image_2k),
        "4K": float(pp.ai_image_4k),
    }
    key = str(image_size or "1K").strip().upper()
    if key not in costs:
        if key in ("1", "2", "4"):
            key = f"{key}K"
    return float(costs.get(key, costs["1K"]))


def _read_points_account(cur: sqlite3.Cursor, user_id: int) -> Tuple[float, float]:
    _create_points_account_if_needed(cur, user_id)
    acc = cur.execute("SELECT * FROM user_points_accounts WHERE user_id=?", (user_id,)).fetchone()
    return _points_balance_from_row(acc), 0.0


def estimated_points_cost(unit_count: int, unit_cost: float) -> float:
    if unit_count <= 0:
        return 0.0
    return round(unit_count * float(unit_cost), 4)


def projected_whole_points_needed(balance: float, debt: float, image_count: int, image_size: str) -> float:
    """批量开始前预估需扣积分（实时小数扣费）。"""
    _ = balance, debt
    if image_count <= 0:
        return 0.0
    return estimated_points_cost(image_count, get_ai_image_points_cost(image_size))


def projected_whole_points_needed_by_unit_cost(balance: float, debt: float, unit_count: int, unit_cost: float) -> float:
    _ = balance, debt
    return estimated_points_cost(unit_count, unit_cost)


def get_title_optimize_points_cost() -> float:
    return float(_points_pricing_cfg().title_optimize_per_item)


def get_traffic_ai_points_cost() -> float:
    return float(_points_pricing_cfg().traffic_ai_per_run)


def _deduct_points_amount(
    user_id: int,
    amount: float,
    biz_type: str,
    biz_id: Optional[str] = None,
    remark: str = "",
    *,
    lock: Optional[threading.Lock] = None,
) -> Dict[str, Any]:
    """按实际用量实时扣减积分（支持小数）。"""
    init_db()
    amount = round(float(amount), 4)
    if amount <= 0:
        return {"amount": 0, "deducted": 0, "balance": 0}

    use_lock = lock or _points_fractional_lock
    with use_lock:
        conn = _conn()
        cur = conn.cursor()
        try:
            balance, _ = _read_points_account(cur, user_id)
            if balance + 1e-6 < amount:
                raise ValueError("积分不足，请充值后再继续")
            new_balance = _apply_points_delta(cur, user_id, -amount, biz_type, biz_id, remark)
            row = cur.execute("SELECT username FROM users WHERE id=? LIMIT 1", (user_id,)).fetchone()
            uname = str(row["username"] or "").strip() if row else ""
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    try:
        sync_points_balance_to_cloud(user_id, new_balance, username=uname)
    except Exception as e:
        logger.warning(f"积分扣减后云端同步失败: {e}")
        
    return {"amount": amount, "deducted": amount, "balance": new_balance}

def _require_cloud_billing_token(token: str) -> str:
    """云端积分模式下必须有有效 Bearer，禁止静默回退本地扣费。"""
    t = (token or "").strip()
    if use_cloud_points() and not t:
        raise ValueError("登录已失效，请重新登录会员中心后再使用积分")
    return t


def check_title_optimize_points_sufficient(
    user_id: int, item_count: int, *, token: str = ""
) -> Dict[str, Any]:
    t = _require_cloud_billing_token(token) if use_cloud_points() else (token or "").strip()
    if use_cloud_points() and t:
        balance = cloud_get_points_balance(t)
    else:
        init_db()
        conn = _conn()
        cur = conn.cursor()
        balance, _ = _read_points_account(cur, user_id)
        conn.close()
    per_item = get_title_optimize_points_cost()
    total_cost = estimated_points_cost(item_count, per_item)
    return {
        "sufficient": balance + 1e-6 >= total_cost,
        "balance": balance,
        "per_item_cost": per_item,
        "planned_items": item_count,
        "estimated_total_cost": total_cost,
        "whole_points_required": total_cost,
    }


def check_traffic_ai_points_sufficient(user_id: int, *, token: str = "") -> Dict[str, Any]:
    t = _require_cloud_billing_token(token) if use_cloud_points() else (token or "").strip()
    if use_cloud_points() and t:
        balance = cloud_get_points_balance(t)
    else:
        init_db()
        conn = _conn()
        cur = conn.cursor()
        balance, _ = _read_points_account(cur, user_id)
        conn.close()
    per_run = get_traffic_ai_points_cost()
    total_cost = estimated_points_cost(1, per_run)
    return {
        "sufficient": balance + 1e-6 >= total_cost,
        "balance": balance,
        "per_run_cost": per_run,
        "planned_runs": 1,
        "estimated_total_cost": total_cost,
        "whole_points_required": total_cost,
    }


def deduct_title_optimize_points(
    user_id: int, biz_id: Optional[str] = None, *, token: str = ""
) -> Dict[str, Any]:
    amount = get_title_optimize_points_cost()
    remark = f"产品优化建议 扣{amount:g}积分"
    if use_cloud_points():
        t = _require_cloud_billing_token(token)
        return cloud_consume_points(t, amount, "title_optimize", biz_id, remark)
    return _deduct_points_amount(user_id, amount, "title_optimize", biz_id, remark)


def deduct_traffic_ai_points(
    user_id: int, biz_id: Optional[str] = None, *, token: str = ""
) -> Dict[str, Any]:
    amount = get_traffic_ai_points_cost()
    remark = f"流量分析 扣{amount:g}积分"
    if use_cloud_points():
        t = _require_cloud_billing_token(token)
        return cloud_consume_points(t, amount, "traffic_ai", biz_id, remark)
    return _deduct_points_amount(user_id, amount, "traffic_ai", biz_id, remark)


def sync_local_points_balance_from_cloud(user_id: int, token: str) -> None:
    """将云端积分余额同步到本地账户（双向同步：始终以云端余额覆盖本地）。"""
    try:
        cloud_balance = _pull_points_balance_from_cloud_by_token(token)
        if cloud_balance is None:
            return
        sync_points_balance_from_cloud(int(user_id), token, balance=cloud_balance)
    except Exception:
        pass


def check_ai_image_points_sufficient(
    user_id: int, image_count: int, image_size: str, *, token: str = ""
) -> Dict[str, Any]:
    t = _require_cloud_billing_token(token) if use_cloud_points() else (token or "").strip()
    if use_cloud_points() and t:
        balance = cloud_get_points_balance(t)
    else:
        init_db()
        conn = _conn()
        cur = conn.cursor()
        balance, _ = _read_points_account(cur, user_id)
        conn.close()
    per_image = get_ai_image_points_cost(image_size)
    total_cost = projected_whole_points_needed(balance, 0.0, image_count, image_size)
    sufficient = balance + 1e-6 >= total_cost
    return {
        "sufficient": sufficient,
        "balance": balance,
        "per_image_cost": per_image,
        "image_size": str(image_size or "1K").upper(),
        "planned_images": image_count,
        "estimated_total_cost": total_cost,
        "whole_points_required": total_cost,
    }


def deduct_ai_image_generation_points(
    user_id: int,
    image_size: str,
    biz_id: Optional[str] = None,
    *,
    token: str = "",
) -> Dict[str, Any]:
    """每张成功出图后实时扣费（默认走云端）。"""
    amount = get_ai_image_points_cost(image_size)
    size_label = str(image_size or "1K").upper()
    remark = f"AI生图({size_label}) 扣{amount:g}积分"
    if use_cloud_points():
        t = _require_cloud_billing_token(token)
        return cloud_consume_points(t, amount, "ai_image_gen", biz_id, remark)
    return _deduct_points_amount(
        user_id,
        amount,
        "ai_image_gen",
        biz_id,
        remark,
        lock=_points_ai_image_lock,
    )


def register(username: str, password: str, invite_code: Optional[str] = None) -> Dict[str, Any]:
    init_db()
    conn = _conn()
    cur = conn.cursor()

    exists = cur.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()
    if exists:
        conn.close()
        raise ValueError("账号已存在")

    inviter_id = None
    if invite_code:
        inviter = cur.execute("SELECT id FROM users WHERE invite_code=?", (invite_code.strip().upper(),)).fetchone()
        if inviter:
            inviter_id = int(inviter["id"])

    now = datetime.now()
    trial_end = now + timedelta(days=15)
    my_invite = _new_invite_code()

    cur.execute(
        """
        INSERT INTO users(username,password_hash,invite_code,inviter_user_id,invited_at,trial_start_at,trial_end_at,vip_expire_at,created_at)
        VALUES(?,?,?,?,?,?,?,?,?)
        """,
        (
            username,
            _hash_pwd(password),
            my_invite,
            inviter_id,
            _now_str() if inviter_id else None,
            now.strftime("%Y-%m-%d %H:%M:%S"),
            trial_end.strftime("%Y-%m-%d %H:%M:%S"),
            None,
            _now_str(),
        ),
    )
    uid = int(cur.lastrowid)
    _create_points_account_if_needed(cur, uid)
    conn.commit()
    conn.close()

    return {"user_id": uid, "invite_code": my_invite, "trial_end_at": trial_end.strftime("%Y-%m-%d %H:%M:%S")}


def _cloud_admin_create_user(
    username: str,
    password: str,
    *,
    invite_code: Optional[str] = None,
    points_balance: float = 0,
    trial_days: int = 15,
    real_name: str = "",
    phone: str = "",
) -> int:
    """在云端创建会员账号，返回云端 user_id。"""
    if not _membership_cloud_sync_enabled():
        return 0

    admin_key = _get_cloud_admin_key()
    if not admin_key:
        raise ValueError("未配置云端管理密钥（payment.admin_api_key），无法在云端创建会员")

    uname = str(username or "").strip()
    if not uname:
        raise ValueError("username 不能为空")

    body: Dict[str, Any] = {
        "username": uname,
        "password": str(password or ""),
        "real_name": str(real_name or "").strip(),
        "phone": str(phone or "").strip(),
        "points_balance": round(max(0.0, float(points_balance or 0)), 4),
        "trial_days": max(1, int(trial_days or 15)),
    }
    if invite_code is not None and str(invite_code).strip():
        body["invite_code"] = str(invite_code).strip()

    try:
        resp = requests.post(
            f"{CLOUD_MEMBERSHIP_API_BASE}/admin/users/create",
            headers={"X-Admin-Key": admin_key, "Content-Type": "application/json"},
            json=body,
            timeout=(3, 15),
        )
    except requests.RequestException as e:
        raise ValueError(f"云端创建会员失败：{e}") from e

    if not resp.ok:
        msg = _parse_cloud_http_error(resp)
        if any(x in msg for x in ("已存在", "已注册", "exist", "duplicate")):
            cloud_uid = _resolve_cloud_user_id(uname)
            if cloud_uid:
                return int(cloud_uid)
        raise ValueError(f"云端创建会员失败：{msg}")

    payload = resp.json() or {}
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        data = payload if isinstance(payload, dict) else {}
    cloud_uid = int(data.get("user_id") or data.get("id") or 0)
    if cloud_uid <= 0:
        raise ValueError("云端创建会员成功但未返回 user_id")
    with _CLOUD_SYNC_LOCK:
        _CLOUD_ADMIN_USERS_CACHE["ts"] = 0.0
        _CLOUD_USER_ID_CACHE[uname] = cloud_uid
    return cloud_uid


def admin_create_user(
    username: str,
    password: str,
    invite_code: Optional[str] = None,
    points_balance: float = 0,
    trial_days: int = 15,
    real_name: str = "",
    phone: str = "",
) -> Dict[str, Any]:
    data = register(username=username, password=password, invite_code=invite_code)
    uid = int(data.get("user_id") or 0)
    if uid <= 0:
        raise ValueError("创建用户失败")

    init_db()
    conn = _conn()
    cur = conn.cursor()
    _create_points_account_if_needed(cur, uid)
    pb = round(max(0.0, float(points_balance or 0)), 4)
    cur.execute(
        """
        UPDATE user_points_accounts
        SET balance_real=?, balance=?, points_fractional_debt=0, updated_at=?
        WHERE user_id=?
        """,
        (pb, int(pb), _now_str(), uid),
    )

    days = max(1, int(trial_days or 15))
    now = datetime.now()
    end = now + timedelta(days=days)
    cur.execute(
        "UPDATE users SET trial_start_at=?, trial_end_at=?, real_name=?, phone=? WHERE id=?",
        (
            now.strftime("%Y-%m-%d %H:%M:%S"),
            end.strftime("%Y-%m-%d %H:%M:%S"),
            str(real_name or "").strip(),
            str(phone or "").strip(),
            uid,
        ),
    )
    trial_start = now.strftime("%Y-%m-%d %H:%M:%S")
    trial_end = end.strftime("%Y-%m-%d %H:%M:%S")
    conn.commit()
    conn.close()

    cloud_synced = False
    if _membership_cloud_sync_enabled():
        cloud_uid = _resolve_cloud_user_id(username, local_user_id=uid)
        if not cloud_uid:
            cloud_uid = _cloud_admin_create_user(
                username=username,
                password=password,
                invite_code=invite_code,
                points_balance=pb,
                trial_days=days,
                real_name=real_name,
                phone=phone,
            )
        if not cloud_uid:
            raise ValueError(f"无法在云端创建或定位会员账号（{username}）")
        _persist_cloud_user_id(uid, int(cloud_uid), username=username)
        _push_admin_user_update_to_cloud(
            int(cloud_uid),
            username=username,
            points_balance=pb,
            trial_start_at=trial_start,
            trial_end_at=trial_end,
        )
        cloud_synced = True
    else:
        sync_points_balance_to_cloud(uid, pb, username=username)

    return {
        "user_id": uid,
        "username": username,
        "invite_code": data.get("invite_code"),
        "real_name": str(real_name or "").strip(),
        "phone": str(phone or "").strip(),
        "points_balance": round(max(0.0, float(points_balance or 0)), 4),
        "trial_start_at": trial_start,
        "trial_end_at": trial_end,
        "cloud_synced": cloud_synced,
    }


def admin_delete_user(user_id: int) -> Dict[str, Any]:
    uid = int(user_id or 0)
    if uid <= 0:
        raise ValueError("user_id 非法")
    if uid == 1:
        raise ValueError("管理员主账号不允许删除")

    init_db()
    conn = _conn()
    cur = conn.cursor()

    row = cur.execute("SELECT id, username FROM users WHERE id=?", (uid,)).fetchone()
    if not row:
        conn.close()
        raise ValueError("用户不存在")

    cur.execute("DELETE FROM user_sessions WHERE user_id=?", (uid,))
    cur.execute("DELETE FROM user_points_ledger WHERE user_id=?", (uid,))
    cur.execute("DELETE FROM user_points_accounts WHERE user_id=?", (uid,))
    cur.execute("DELETE FROM recharge_orders WHERE user_id=?", (uid,))
    cur.execute("DELETE FROM invite_rewards WHERE inviter_user_id=? OR invitee_user_id=?", (uid, uid))
    cur.execute("DELETE FROM vip_redeem_orders WHERE user_id=?", (uid,))
    cur.execute("DELETE FROM withdraw_orders WHERE user_id=?", (uid,))
    cur.execute("DELETE FROM user_access_controls WHERE user_id=?", (uid,))
    cur.execute("DELETE FROM users WHERE id=?", (uid,))

    conn.commit()
    conn.close()

    return {"user_id": uid, "username": row["username"], "deleted": True}


def _log_login_event(
    cur: sqlite3.Cursor,
    *,
    login_type: str,
    username: str,
    ip: str = "",
    user_agent: str = "",
    success: bool,
    reason: str = "",
):
    cur.execute(
        "INSERT INTO auth_login_events(login_type, username, ip, user_agent, success, reason, created_at) VALUES(?,?,?,?,?,?,?)",
        (
            str(login_type or "member"),
            str(username or ""),
            str(ip or ""),
            str(user_agent or ""),
            1 if success else 0,
            str(reason or ""),
            _now_str(),
        ),
    )


def _check_login_lock(cur: sqlite3.Cursor, login_type: str, username: str):
    u = str(username or "").strip().lower()
    t = str(login_type or "member").strip().lower()
    row = cur.execute(
        "SELECT fail_count, first_fail_at, last_fail_at, locked_until FROM auth_login_locks WHERE login_type=? AND username=?",
        (t, u),
    ).fetchone()
    if not row:
        return

    locked_until = str(row["locked_until"] or "").strip()
    if not locked_until:
        return
    try:
        lu = datetime.strptime(locked_until, "%Y-%m-%d %H:%M:%S")
        if lu > datetime.now():
            mins = max(1, int((lu - datetime.now()).total_seconds() // 60) + 1)
            raise ValueError(f"登录失败次数过多，请 {mins} 分钟后再试")
        # 锁定已过期，自动解锁并清零计数
        cur.execute(
            "UPDATE auth_login_locks SET fail_count=0, first_fail_at=?, last_fail_at=?, locked_until=NULL, updated_at=? WHERE login_type=? AND username=?",
            (_now_str(), _now_str(), _now_str(), t, u),
        )
    except ValueError:
        raise
    except Exception:
        pass


def _record_login_failed(cur: sqlite3.Cursor, login_type: str, username: str):
    u = str(username or "").strip().lower()
    t = str(login_type or "member").strip().lower()
    now = datetime.now()
    now_str = now.strftime("%Y-%m-%d %H:%M:%S")

    row = cur.execute(
        "SELECT fail_count, first_fail_at, last_fail_at, locked_until FROM auth_login_locks WHERE login_type=? AND username=?",
        (t, u),
    ).fetchone()

    if not row:
        fail_count = 1
        first = now
        locked_until = None
        cur.execute(
            "INSERT INTO auth_login_locks(login_type, username, fail_count, first_fail_at, last_fail_at, locked_until, updated_at) VALUES(?,?,?,?,?,?,?)",
            (t, u, fail_count, now_str, now_str, locked_until, now_str),
        )
        return

    fail_count = int(row["fail_count"] or 0)
    first_txt = str(row["first_fail_at"] or "")
    try:
        first = datetime.strptime(first_txt, "%Y-%m-%d %H:%M:%S") if first_txt else now
    except Exception:
        first = now

    if (now - first) > timedelta(minutes=LOGIN_FAIL_WINDOW_MINUTES):
        fail_count = 0
        first = now

    fail_count += 1
    lock_until = None
    if fail_count >= LOGIN_FAIL_MAX:
        lock_until = (now + timedelta(minutes=LOGIN_LOCK_MINUTES)).strftime("%Y-%m-%d %H:%M:%S")

    cur.execute(
        "UPDATE auth_login_locks SET fail_count=?, first_fail_at=?, last_fail_at=?, locked_until=?, updated_at=? WHERE login_type=? AND username=?",
        (
            fail_count,
            first.strftime("%Y-%m-%d %H:%M:%S"),
            now_str,
            lock_until,
            now_str,
            t,
            u,
        ),
    )


def _record_login_success(cur: sqlite3.Cursor, login_type: str, username: str):
    u = str(username or "").strip().lower()
    t = str(login_type or "member").strip().lower()
    cur.execute(
        "UPDATE auth_login_locks SET fail_count=0, first_fail_at=?, last_fail_at=?, locked_until=NULL, updated_at=? WHERE login_type=? AND username=?",
        (_now_str(), _now_str(), _now_str(), t, u),
    )


def _ensure_local_session_for_cloud_login(token: str, username: str) -> None:
    """云端登录后写入本地 users + user_sessions（本地无账号时自动创建）。"""
    t = str(token or "").strip()
    if not t:
        return
    try:
        _sync_user_id_from_cloud_token(t)
        return
    except Exception:
        pass
    uname = str(username or "").strip()
    if not uname:
        return
    init_db()
    conn = _conn()
    cur = conn.cursor()
    row = cur.execute("SELECT id FROM users WHERE username=? LIMIT 1", (uname,)).fetchone()
    if not row:
        conn.close()
        return
    uid = int(row["id"])
    token_hash = hashlib.sha256(t.encode("utf-8")).hexdigest()
    cur.execute(
        "INSERT OR REPLACE INTO user_sessions(token,user_id,created_at,expire_at,last_seen_at,token_hash) VALUES(?,?,?,?,?,?)",
        (t, uid, _now_str(), "2099-12-31 23:59:59", _now_str(), token_hash),
    )
    conn.commit()
    conn.close()
    _TOKENS[t] = uid


def _try_cloud_login(username: str, password: str) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """
    优先使用云端账号登录。
    返回 (token_data, error_reason)：
    - 成功: (data, None)
    - 账号密码错误: (None, "bad_credentials")
    - 云端不可达: (None, "unreachable")
    """
    uname = str(username or "").strip()
    pwd = str(password or "").strip()
    if not uname:
        return None, "bad_credentials"

    try:
        resp = _cloud_http_request(
            "POST",
            f"{CLOUD_MEMBERSHIP_API_BASE}/auth/login",
            json={"username": uname, "password": pwd},
            timeout=_CLOUD_LOGIN_HTTP_TIMEOUT,
        )
    except Exception:
        return None, "unreachable"

    if resp.status_code in (400, 401, 403):
        msg = _parse_cloud_http_error(resp)
        if "不可用" in msg or "unreachable" in msg.lower() or "timeout" in msg.lower():
            return None, "unreachable"
        if "账号" in msg or "密码" in msg or "credentials" in msg.lower():
            return None, "bad_credentials"
        return None, "bad_credentials"

    if resp.status_code >= 500 or not resp.ok:
        return None, "unreachable"

    payload = resp.json() if resp.content else {}
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        data = payload if isinstance(payload, dict) else {}
    token = str(data.get("token") or "").strip()
    if not token:
        return None, "unreachable"

    try:
        _sync_user_id_from_cloud_token(token)
    except Exception:
        try:
            _ensure_local_session_for_cloud_login(token, uname)
        except Exception:
            pass

    expire_at = str(data.get("expire_at") or "").strip()
    if not expire_at:
        expire_at = (datetime.now() + timedelta(hours=SESSION_HOURS)).strftime("%Y-%m-%d %H:%M:%S")
    out: Dict[str, Any] = {"token": token, "expire_at": expire_at}
    role = str(data.get("role") or "").strip().lower()
    if role == "admin":
        out["role"] = "admin"
        out["admin_user"] = str(data.get("admin_user") or uname).strip() or uname
        ak = str(data.get("admin_key") or "").strip()
        if ak:
            out["admin_key"] = ak
        else:
            local_ak = _get_admin_api_key()
            if local_ak:
                out["admin_key"] = local_ak
    return out, None


def _issue_local_member_session(
    cur: sqlite3.Cursor, uid: int, uname: str, ip: str = "", user_agent: str = ""
) -> Dict[str, Any]:
    """生成本地会员 token 并写入 user_sessions（含 token_hash，供 membership_guard 校验）。"""
    token = uuid.uuid4().hex
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    expire_at = datetime.now() + timedelta(hours=SESSION_HOURS)
    expire_str = expire_at.strftime("%Y-%m-%d %H:%M:%S")
    cur.execute(
        "INSERT OR REPLACE INTO user_sessions(token,user_id,created_at,expire_at,last_seen_at,token_hash) VALUES(?,?,?,?,?,?)",
        (token, uid, _now_str(), expire_str, _now_str(), token_hash),
    )
    _TOKENS[token] = uid
    _record_login_success(cur, "member", uname)
    _log_login_event(cur, login_type="member", username=uname, ip=ip, user_agent=user_agent, success=True, reason="ok_local")
    return {"token": token, "expire_at": expire_str}


def _get_admin_api_key() -> str:
    env_key = os.getenv("ALI_ADMIN_API_KEY", "").strip()
    if env_key and env_key not in ("change-me-admin", "change-me"):
        return env_key
    try:
        cfg = get_config()
        key = str(getattr(cfg.payment, "admin_api_key", "") or "").strip()
        if key and key not in ("change-me-admin", "change-me"):
            return key
    except Exception:
        pass
    try:
        from app.core.desktop_bootstrap import _resolve_deploy_admin_key

        deploy_key = _resolve_deploy_admin_key()
        if deploy_key:
            return deploy_key
    except Exception:
        pass
    return ""


def _admin_username_exists(username: str) -> bool:
    uname = str(username or "").strip()
    if not uname:
        return False
    init_db()
    conn = _conn()
    try:
        row = conn.execute(
            "SELECT 1 FROM admin_accounts WHERE username=? AND is_active=1 LIMIT 1",
            (uname,),
        ).fetchone()
        return bool(row)
    finally:
        conn.close()


def create_admin_account(username: str, password: str) -> Dict[str, Any]:
    """在 admin_accounts 表创建或重置管理员（命令行/运维用）。"""
    uname = str(username or "").strip()
    pwd = str(password or "")
    if not uname:
        raise ValueError("管理员用户名不能为空")
    if not pwd.strip():
        raise ValueError("管理员密码不能为空")

    init_db()
    conn = _conn()
    cur = conn.cursor()
    now = _now_str()
    h = _hash_pwd(pwd)
    row = cur.execute("SELECT id FROM admin_accounts WHERE username=?", (uname,)).fetchone()
    if row:
        cur.execute(
            "UPDATE admin_accounts SET password_hash=?, is_active=1, updated_at=? WHERE username=?",
            (h, now, uname),
        )
        action = "updated"
    else:
        cur.execute(
            "INSERT INTO admin_accounts(username,password_hash,is_active,created_at,updated_at) VALUES(?,?,?,?,?)",
            (uname, h, 1, now, now),
        )
        action = "created"
    conn.commit()
    conn.close()
    return {"username": uname, "action": action}


def reset_member_password(username: str, password: str) -> Dict[str, Any]:
    """云端/本地：在 users 表创建或重置会员密码，并清除登录锁定。"""
    uname = str(username or "").strip()
    pwd = str(password or "")
    if not uname:
        raise ValueError("会员用户名不能为空")
    if not pwd.strip():
        raise ValueError("会员密码不能为空")

    init_db()
    conn = _conn()
    cur = conn.cursor()
    now = _now_str()
    h = _hash_pwd(pwd)
    row = cur.execute("SELECT id FROM users WHERE username=?", (uname,)).fetchone()
    if row:
        uid = int(row["id"])
        cur.execute("UPDATE users SET password_hash=? WHERE id=?", (h, uid))
        action = "updated"
    else:
        trial_end = (datetime.now() + timedelta(days=15)).strftime("%Y-%m-%d %H:%M:%S")
        cur.execute(
            """
            INSERT INTO users(username,password_hash,invite_code,inviter_user_id,invited_at,trial_start_at,trial_end_at,vip_expire_at,created_at)
            VALUES(?,?,?,?,?,?,?,?,?)
            """,
            (
                uname,
                h,
                _new_invite_code(),
                None,
                None,
                now,
                trial_end,
                None,
                now,
            ),
        )
        uid = int(cur.lastrowid)
        _create_points_account_if_needed(cur, uid)
        action = "created"

    cur.execute(
        "DELETE FROM auth_login_locks WHERE login_type=? AND username=?",
        ("member", uname.lower()),
    )
    conn.commit()
    conn.close()
    return {"username": uname, "action": action, "user_id": uid}


def _ensure_admin_runtime_user(cur: sqlite3.Cursor) -> int:
    """确保 users.id=1 存在，供管理员运行时 Bearer 鉴权（evaluate_access_by_token 对 uid=1 放行）。"""
    row = cur.execute("SELECT id FROM users WHERE id=1 LIMIT 1").fetchone()
    if row:
        return 1
    now = _now_str()
    cur.execute(
        """
        INSERT INTO users(
          id, username, password_hash, invite_code, inviter_user_id, invited_at,
          trial_start_at, trial_end_at, vip_expire_at, created_at
        ) VALUES(?,?,?,?,?,?,?,?,?,?)
        """,
        (
            1,
            "__admin_runtime__",
            _hash_pwd(secrets.token_hex(24)),
            _new_invite_code(),
            None,
            None,
            now,
            "2099-12-31 23:59:59",
            "2099-12-31 23:59:59",
            now,
        ),
    )
    _create_points_account_if_needed(cur, 1)
    return 1


def issue_admin_runtime_session(admin_username: str = "") -> Dict[str, str]:
    """为管理员签发本地 Bearer token（user_id=1），业务 API 与会员一样带 Authorization 即可。"""
    init_db()
    conn = _conn()
    cur = conn.cursor()
    uid = _ensure_admin_runtime_user(cur)
    token = uuid.uuid4().hex
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    expire_at = datetime.now() + timedelta(hours=SESSION_HOURS * 24)
    expire_str = expire_at.strftime("%Y-%m-%d %H:%M:%S")
    cur.execute(
        "INSERT OR REPLACE INTO user_sessions(token,user_id,created_at,expire_at,last_seen_at,token_hash) VALUES(?,?,?,?,?,?)",
        (token, uid, _now_str(), expire_str, _now_str(), token_hash),
    )
    uname = str(admin_username or "").strip()
    if uname:
        _log_login_event(
            cur,
            login_type="admin",
            username=uname,
            success=True,
            reason="admin_runtime_token",
        )
    conn.commit()
    conn.close()
    _TOKENS[token] = uid
    return {"token": token, "expire_at": expire_str}


def verify_admin_api_key(x_admin_key: Optional[str]) -> bool:
    expected = _get_admin_api_key()
    if not expected:
        return False
    return str(x_admin_key or "").strip() == expected


def is_admin_username(username: str) -> bool:
    """用户名是否在 admin_accounts 中（活跃管理员）。"""
    uname = str(username or "").strip()
    if not uname:
        return False
    try:
        init_db()
        conn = _conn()
        row = conn.execute(
            "SELECT 1 FROM admin_accounts WHERE username=? AND is_active=1 LIMIT 1",
            (uname,),
        ).fetchone()
        conn.close()
        return bool(row)
    except Exception:
        return False


def is_admin_bearer_token(token: str) -> bool:
    """管理员 Bearer 会话：uid=1 运行时账号、admin_accounts 用户名或云端 role=admin。"""
    t = str(token or "").strip()
    if not t:
        return False
    try:
        uid = int(resolve_user_id_by_token(t))
        if uid == 1:
            return True
        conn = _conn()
        row = conn.execute("SELECT username FROM users WHERE id=? LIMIT 1", (uid,)).fetchone()
        conn.close()
        if row and is_admin_username(str(row["username"] or "")):
            return True
    except Exception:
        pass
    try:
        info = fetch_cloud_me_cached(t, allow_stale=True)
        if isinstance(info, dict):
            if str(info.get("role") or "").strip().lower() == "admin":
                return True
            uname = str(info.get("username") or "").strip()
            if uname and is_admin_username(uname):
                return True
    except Exception:
        pass
    return False


def is_admin_access(token: Optional[str] = None, x_admin_key: Optional[str] = None) -> bool:
    """管理员总钥匙或管理员 Bearer 会话均可跳过店铺绑定等会员限制。"""
    if verify_admin_api_key(x_admin_key):
        return True
    return is_admin_bearer_token(str(token or ""))


def unified_login(username: str, password: str, ip: str = "", user_agent: str = "") -> Dict[str, Any]:
    """
    统一登录：先查 admin_accounts（管理员），再走会员 login（users / 云端）。
    返回 data 含 role: admin | member。
    """
    uname = str(username or "").strip()
    pwd = str(password or "").strip()
    if not uname:
        raise ValueError("账号不能为空")
    if not pwd:
        raise ValueError("密码不能为空")

    try:
        admin_login_guard_check(uname)
    except Exception as e:
        raise

    if verify_admin_account(uname, pwd):
        admin_login_guard_success(uname, ip=ip, user_agent=user_agent)
        admin_key = _get_admin_api_key()
        if not admin_key:
            raise ValueError(
                "管理员 API Key 未配置，请在环境变量 ALI_ADMIN_API_KEY 或配置 payment.admin_api_key 中设置"
            )
        runtime = issue_admin_runtime_session(uname)
        return {
            "role": "admin",
            "admin_user": uname,
            "admin_key": admin_key,
            "token": runtime["token"],
            "expire_at": runtime["expire_at"],
        }

    if _admin_username_exists(uname):
        admin_login_guard_failed(uname, ip=ip, user_agent=user_agent, reason="bad_credentials")
        raise ValueError("管理员账号或密码错误")

    member = login(uname, pwd, ip=ip, user_agent=user_agent)
    if str(member.get("role") or "") == "admin":
        return member
    return {"role": "member", **member}


def login(username: str, password: str, ip: str = "", user_agent: str = "") -> Dict[str, Any]:
    init_db()
    conn = _conn()
    cur = conn.cursor()

    uname = str(username or "").strip()
    pwd_plain = str(password or "").strip()
    if not uname:
        conn.close()
        raise ValueError("账号不能为空")

    try:
        _check_login_lock(cur, "member", uname)
    except Exception as e:
        _log_login_event(cur, login_type="member", username=uname, ip=ip, user_agent=user_agent, success=False, reason=str(e))
        conn.commit()
        conn.close()
        raise

    row = cur.execute("SELECT id,password_hash FROM users WHERE username=?", (uname,)).fetchone()
    pwd_hash = _hash_pwd(pwd_plain)
    pw_ok_locally = bool(row and str(row["password_hash"] or "") == pwd_hash)

    # 云端主机：会员登录仅校验本机 membership.db，不调用 CLOUD_MEMBERSHIP_API_BASE（避免自己请求自己）
    if _is_cloud_membership_host():
        if not row or not pw_ok_locally:
            if row and not pw_ok_locally:
                _record_login_failed(cur, "member", uname)
            _log_login_event(
                cur,
                login_type="member",
                username=uname,
                ip=ip,
                user_agent=user_agent,
                success=False,
                reason="bad_credentials",
            )
            conn.commit()
            conn.close()
            raise ValueError("账号或密码错误")
        data = _issue_local_member_session(cur, int(row["id"]), uname, ip=ip, user_agent=user_agent)
        conn.commit()
        conn.close()
        return data

    # MEMBERSHIP_POINTS_SOURCE=cloud（默认）时，必须使用云端签发的 token，否则云端 /me、扣积分不可用。
    # 先前「本地有账号就先发本地 UUID token」会绕过云端登录，导致会员中心有数据但产品优化一查积分就失败。
    if use_cloud_points():
        cloud_first, cloud_err = _try_cloud_login(uname, pwd_plain)
        if cloud_first:
            conn.commit()
            conn.close()
            if str(cloud_first.get("role") or "") == "admin":
                return cloud_first
            return cloud_first
        if cloud_err == "bad_credentials":
            conn.commit()
            conn.close()
            raise ValueError("账号或密码错误")
        conn.commit()
        conn.close()
        raise ValueError(
            "云端会员服务暂不可用，请检查云端网络与反代配置后重试。"
            "本地开发可在启动 backend 前设置 ALI_OFFLINE_DEV=1 使用本地会员库登录。"
        )

    # 未启用云端积分：本地命中则秒级发证（离线/开发）
    if pw_ok_locally:
        data = _issue_local_member_session(cur, int(row["id"]), uname, ip=ip, user_agent=user_agent)
        conn.commit()
        conn.close()
        return data

    cloud_data, cloud_err = _try_cloud_login(uname, pwd_plain)
    if cloud_data:
        conn.close()
        return cloud_data
    if cloud_err == "bad_credentials":
        conn.close()
        raise ValueError("账号或密码错误")

    cloud_unreachable = cloud_err == "unreachable"

    if row and str(row["password_hash"] or "") != pwd_hash:
        _record_login_failed(cur, "member", uname)
        _log_login_event(cur, login_type="member", username=uname, ip=ip, user_agent=user_agent, success=False, reason="bad_credentials")
        conn.commit()
        conn.close()
        raise ValueError("账号或密码错误")

    conn.commit()
    conn.close()
    if cloud_unreachable:
        raise ValueError("云端会员服务暂不可用，且本地无此账号。请稍后重试，或在会员中心注册本地账号。")
    raise ValueError("账号或密码错误")


def admin_login_guard_check(username: str):
    init_db()
    conn = _conn()
    cur = conn.cursor()
    try:
        _check_login_lock(cur, "admin", str(username or "").strip())
        conn.commit()
    finally:
        conn.close()


def admin_login_guard_failed(username: str, ip: str = "", user_agent: str = "", reason: str = "bad_credentials"):
    init_db()
    conn = _conn()
    cur = conn.cursor()
    try:
        uname = str(username or "").strip()
        _record_login_failed(cur, "admin", uname)
        _log_login_event(cur, login_type="admin", username=uname, ip=ip, user_agent=user_agent, success=False, reason=reason)
        conn.commit()
    finally:
        conn.close()


def admin_login_guard_success(username: str, ip: str = "", user_agent: str = ""):
    init_db()
    conn = _conn()
    cur = conn.cursor()
    try:
        uname = str(username or "").strip()
        _record_login_success(cur, "admin", uname)
        _log_login_event(cur, login_type="admin", username=uname, ip=ip, user_agent=user_agent, success=True, reason="ok")
        conn.commit()
    finally:
        conn.close()


def verify_admin_account(username: str, password: str) -> bool:
    init_db()
    uname = str(username or "").strip()
    if not uname:
        return False

    conn = _conn()
    cur = conn.cursor()
    row = cur.execute(
        "SELECT password_hash FROM admin_accounts WHERE username=? AND is_active=1",
        (uname,),
    ).fetchone()
    conn.close()

    if not row:
        return False
    return str(row["password_hash"] or "") == _hash_pwd(str(password or ""))


def change_admin_password(username: str, old_password: str, new_password: str) -> Dict[str, Any]:
    init_db()
    uname = str(username or "").strip()
    if not uname:
        raise ValueError("管理员账号不能为空")
    if not str(new_password or "").strip():
        raise ValueError("新密码不能为空")

    conn = _conn()
    cur = conn.cursor()
    row = cur.execute(
        "SELECT password_hash, is_active FROM admin_accounts WHERE username=?",
        (uname,),
    ).fetchone()
    if not row or int(row["is_active"] or 0) != 1:
        conn.close()
        raise ValueError("管理员账号不存在或已停用")

    if str(row["password_hash"] or "") != _hash_pwd(str(old_password or "")):
        conn.close()
        raise ValueError("旧密码错误")

    cur.execute(
        "UPDATE admin_accounts SET password_hash=?, updated_at=? WHERE username=?",
        (_hash_pwd(str(new_password)), _now_str(), uname),
    )
    conn.commit()
    conn.close()
    return {"username": uname, "updated": True}


def deactivate_all_member_accounts(reset_password: bool = True) -> Dict[str, Any]:
    """清理会员账号：重置密码并清空会话（管理员账号不受影响）。"""
    init_db()
    conn = _conn()
    cur = conn.cursor()

    rows = cur.execute("SELECT id FROM users").fetchall()
    affected = 0
    if reset_password:
        for r in rows:
            uid = int(r["id"])
            cur.execute("UPDATE users SET password_hash=? WHERE id=?", (_hash_pwd(_random_password()), uid))
            affected += 1

    cur.execute("DELETE FROM user_sessions")
    conn.commit()
    conn.close()
    return {"affected_users": affected, "sessions_cleared": True}


def _fetch_cloud_me_data(token: str) -> Optional[Dict[str, Any]]:
    """拉取云端 /membership/me 快照；失败时返回 None。"""
    return fetch_cloud_me_cached(token)


def _sync_user_id_from_cloud_token(token: str) -> int:
    """云端会员 token 映射到本地 users / user_sessions（与 membership_guard、绑定店铺逻辑一致）。"""
    t = (token or "").strip()
    if not t:
        raise ValueError("登录已失效，请重新登录")

    data = _fetch_cloud_me_data(t)
    if not data:
        raise ValueError("登录已失效，请重新登录")

    username = str(data.get("username") or "").strip()
    if not username:
        raise ValueError("登录已失效，请重新登录")

    trial_end_at = str(data.get("trial_end_at") or "2099-12-31 23:59:59").strip() or "2099-12-31 23:59:59"
    vip_expire_at = str(data.get("vip_expire_at") or "").strip() or None

    init_db()
    conn = _conn()
    cur = conn.cursor()
    row = cur.execute("SELECT id FROM users WHERE username=? LIMIT 1", (username,)).fetchone()
    if not row:
        cur.execute(
            """
            INSERT INTO users(username,password_hash,invite_code,inviter_user_id,invited_at,trial_start_at,trial_end_at,vip_expire_at,created_at)
            VALUES(?,?,?,?,?,?,?,?,?)
            """,
            (
                username,
                _hash_pwd("temp-cloud-sync"),
                _new_invite_code(),
                None,
                None,
                _now_str(),
                trial_end_at,
                vip_expire_at,
                _now_str(),
            ),
        )
        user_id = int(cur.lastrowid)
    else:
        user_id = int(row["id"])
        cur.execute(
            "UPDATE users SET trial_end_at=?, vip_expire_at=? WHERE id=?",
            (trial_end_at, vip_expire_at, user_id),
        )

    _create_points_account_if_needed(cur, user_id)
    cloud_uid = int(data.get("id") or 0)
    if cloud_uid > 0:
        _persist_cloud_user_id(user_id, cloud_uid, cur=cur, username=username)
    cloud_pb = round(float(data.get("points_balance") or 0), 4)
    _write_local_points_balance(user_id, cloud_pb, cur=cur)
    token_hash = hashlib.sha256(t.encode("utf-8")).hexdigest()
    cur.execute(
        "INSERT OR REPLACE INTO user_sessions(token,user_id,created_at,expire_at,last_seen_at,token_hash) VALUES(?,?,?,?,?,?)",
        (t, user_id, _now_str(), "2099-12-31 23:59:59", _now_str(), token_hash),
    )
    conn.commit()
    conn.close()
    _TOKENS[t] = user_id
    _invalidate_cloud_me_cache(t)
    return user_id


def _reject_non_session_token(token: str) -> None:
    """非本地会话且非云端 JWT 的乱码 token 直接拒绝，避免 /me 走云端长超时。"""
    t = (token or "").strip()
    if not t:
        raise ValueError("登录已失效，请重新登录")
    if _looks_like_local_only_token(t) or _token_requires_cloud_resolve(t):
        return
    raise ValueError("登录已失效，请重新登录")


def resolve_user_id_by_token(token: str) -> int:
    """本地会话优先；仅云端 JWT 形态才回退云端 /me 并写入本地映射。"""
    _reject_non_session_token(token)
    try:
        return int(_uid_by_token(token))
    except ValueError:
        if _token_requires_cloud_resolve(token):
            return int(_sync_user_id_from_cloud_token(token))
        raise


def _uid_by_token(token: str) -> int:
    t = (token or "").strip()
    if not t:
        raise ValueError("登录已失效，请重新登录")

    uid = _TOKENS.get(t)
    if uid:
        return uid

    conn = _conn()
    cur = conn.cursor()
    row = cur.execute("SELECT user_id, expire_at FROM user_sessions WHERE token=?", (t,)).fetchone()
    if not row:
        conn.close()
        raise ValueError("登录已失效，请重新登录")

    expire_at = datetime.strptime(row["expire_at"], "%Y-%m-%d %H:%M:%S")
    if expire_at <= datetime.now():
        cur.execute("DELETE FROM user_sessions WHERE token=?", (t,))
        conn.commit()
        conn.close()
        raise ValueError("登录已过期，请重新登录")

    uid = int(row["user_id"])
    _TOKENS[t] = uid
    try:
        cur.execute("UPDATE user_sessions SET last_seen_at=? WHERE token=?", (_now_str(), t))
        conn.commit()
    except Exception:
        pass
    conn.close()
    return uid


def me(token: str) -> Dict[str, Any]:
    """会员资料：VIP/店铺信息优先云端；积分余额以云端为准。"""
    _reject_non_session_token(token)
    uid = resolve_user_id_by_token(token)

    if int(uid) == 1:
        conn = _conn()
        cur = conn.cursor()
        user = cur.execute("SELECT * FROM users WHERE id=1 LIMIT 1").fetchone()
        acc = cur.execute("SELECT * FROM user_points_accounts WHERE user_id=1 LIMIT 1").fetchone()
        conn.close()
        user = dict(user) if user else {"id": 1, "username": "__admin_runtime__", "invite_code": "admin"}
        now = datetime.now()
        trial_end = datetime.strptime(str(user.get("trial_end_at") or "2099-12-31 23:59:59"), "%Y-%m-%d %H:%M:%S")
        vip_raw = user.get("vip_expire_at")
        vip_expire = datetime.strptime(vip_raw, "%Y-%m-%d %H:%M:%S") if vip_raw else None
        is_vip = bool(vip_expire and vip_expire > now) or True
        return {
            "id": 1,
            "username": user.get("username") or "__admin_runtime__",
            "invite_code": user.get("invite_code") or "admin",
            "trial_end_at": str(user.get("trial_end_at") or "2099-12-31 23:59:59"),
            "vip_expire_at": str(vip_raw or "2099-12-31 23:59:59"),
            "is_vip": is_vip,
            "can_use": True,
            "role": "admin",
            "points_balance": _points_balance_from_row(acc),
            "points_unavailable": False,
            "points_error": "",
            "points_frozen": int(acc["frozen_balance"]) if acc else 0,
            "points_fractional_debt": 0,
            "company_name": "",
            "main_category": "",
            "is_verified": "",
            "service_years": "",
            "page_level_star": "",
        }

    conn = _conn()
    cur = conn.cursor()
    user = cur.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    acc = cur.execute("SELECT * FROM user_points_accounts WHERE user_id=?", (uid,)).fetchone()
    if not user:
        conn.close()
        raise ValueError("用户不存在")

    # 公司级到期状态覆盖：同公司只认首次绑定沉淀下来的会员状态
    company_name = user["company_name"] if "company_name" in user.keys() else ""
    key = _company_key(company_name)
    if key:
        b = cur.execute(
            "SELECT trial_start_at, trial_end_at, vip_expire_at FROM company_membership_bindings WHERE company_key=?",
            (key,),
        ).fetchone()
        if b:
            user = dict(user)
            user["trial_start_at"] = b["trial_start_at"]
            user["trial_end_at"] = b["trial_end_at"]
            user["vip_expire_at"] = b["vip_expire_at"]

    conn.close()

    user = dict(user)
    # /me：有云端模式时拉取最新积分并回写本地（缓存未命中时短超时请求云端）
    cloud = _cloud_me_cache_get(token)
    if use_cloud_points() and cloud is None:
        cloud = fetch_cloud_me_cached(token, allow_stale=True)
    if cloud:
        for field in (
            "username",
            "invite_code",
            "trial_end_at",
            "vip_expire_at",
            "company_name",
            "main_category",
            "is_verified",
            "service_years",
            "page_level_star",
        ):
            val = cloud.get(field)
            if val is not None and str(val).strip() != "":
                user[field] = val

    now = datetime.now()
    trial_end = datetime.strptime(user["trial_end_at"], "%Y-%m-%d %H:%M:%S")
    vip_expire = datetime.strptime(user["vip_expire_at"], "%Y-%m-%d %H:%M:%S") if user["vip_expire_at"] else None
    is_vip = bool(vip_expire and vip_expire > now)
    can_use = is_vip or (trial_end > now)

    points_unavailable = False
    points_error = ""
    if use_cloud_points():
        if not cloud:
            # 云端偶发慢响应时回退本地镜像，并标记不可用以免与分析扣费检查矛盾。
            points_balance = _points_balance_from_row(acc)
            points_frozen = int(acc["frozen_balance"]) if acc else 0
            points_unavailable = True
            points_error = CLOUD_POINTS_UNAVAILABLE_MSG
        else:
            points_balance = round(float(cloud.get("points_balance") or 0), 4)
            points_frozen = int(cloud.get("points_frozen") or 0)
            cloud_uid = int(cloud.get("id") or 0)
            if cloud_uid > 0:
                init_db()
                conn = _conn()
                c = conn.cursor()
                _persist_cloud_user_id(uid, cloud_uid, cur=c, username=str(user.get("username") or ""))
                _write_local_points_balance(uid, points_balance, cur=c)
                conn.commit()
                conn.close()
            else:
                _write_local_points_balance(uid, points_balance)
    else:
        points_balance = _points_balance_from_row(acc)
        points_frozen = int(acc["frozen_balance"]) if acc else 0

    return {
        "id": int(user["id"]),
        "username": user["username"],
        "invite_code": user["invite_code"],
        "trial_end_at": user["trial_end_at"],
        "vip_expire_at": user["vip_expire_at"],
        "is_vip": is_vip,
        "can_use": can_use,
        "points_balance": points_balance,
        "points_unavailable": points_unavailable,
        "points_error": points_error,
        "points_frozen": points_frozen,
        "points_fractional_debt": 0,
        "company_name": user["company_name"] if "company_name" in user.keys() else "",
        "main_category": user["main_category"] if "main_category" in user.keys() else "",
        "is_verified": user["is_verified"] if "is_verified" in user.keys() else "",
        "service_years": user["service_years"] if "service_years" in user.keys() else "",
        "page_level_star": user["page_level_star"] if "page_level_star" in user.keys() else "",
    }


def _build_payment_payload(order_no: str, channel: str, amount_yuan: float) -> Dict[str, Any]:
    amount_text = f"{amount_yuan:.2f}"
    cfg = get_config().payment

    if channel == "wechat":
        reasons: List[str] = []

        has_required = bool(cfg.wechat_enabled and cfg.wechat_app_id and cfg.wechat_mch_id)
        if not cfg.wechat_enabled:
            reasons.append("wechat disabled")
        if not cfg.wechat_app_id:
            reasons.append("wechat_app_id missing")
        if not cfg.wechat_mch_id:
            reasons.append("wechat_mch_id missing")
        if cfg.strict_gateway_mode and not has_required:
            raise ValueError("微信支付网关参数不完整（需启用并配置 app_id/mch_id）")

        prod_ready = bool(cfg.wechat_api_v3_key and cfg.wechat_serial_no and cfg.wechat_private_key_pem)
        if not cfg.wechat_api_v3_key:
            reasons.append("wechat_api_v3_key missing")
        if not cfg.wechat_serial_no:
            reasons.append("wechat_serial_no missing")
        if not cfg.wechat_private_key_pem:
            reasons.append("wechat_private_key_pem missing")

        if cfg.production_gateway_mode and not prod_ready:
            raise ValueError("微信生产网关参数不完整（需配置 api_v3_key/serial_no/private_key_pem）")

        wx_nonce = uuid.uuid4().hex[:16]
        wx_timestamp = str(int(datetime.now().timestamp()))
        wx_package = f"prepay_id=mock_prepay_{order_no}"

        wechat_jsapi = {
            "appId": cfg.wechat_app_id,
            "timeStamp": wx_timestamp,
            "nonceStr": wx_nonce,
            "package": wx_package,
            "signType": "HMAC-SHA256",
        }
        wechat_jsapi_sign_raw = _canonical_sign_text(wechat_jsapi)
        wechat_jsapi["paySign"] = _calc_hmac_sha256(wechat_jsapi_sign_raw, (cfg.wechat_secret or "").strip() or "change-me-wechat")

        callback_demo_payload = {
            "out_trade_no": order_no,
            "trade_state": "SUCCESS",
            "timestamp": wx_timestamp,
        }
        callback_demo_payload["sign"] = _calc_hmac_sha256(
            _canonical_sign_text(callback_demo_payload),
            (cfg.wechat_secret or "").strip() or "change-me-wechat",
        )

        return {
            "provider": "wechat",
            "enabled": bool(cfg.wechat_enabled),
            "gateway_ready": has_required,
            "production_ready": prod_ready,
            "ready_reasons": reasons,
            "mode": "native_qr",
            "out_trade_no": order_no,
            "total_fee_yuan": amount_yuan,
            "pay_url": f"weixin://wxpay/bizpayurl?appid={cfg.wechat_app_id}&mch_id={cfg.wechat_mch_id}&out_trade_no={order_no}&total_fee={amount_text}",
            "qr_content": f"weixin://wxpay/mock_native?appid={cfg.wechat_app_id}&mch_id={cfg.wechat_mch_id}&out_trade_no={order_no}&total_fee={amount_text}",
            "notify_url": "/api/membership/pay/callback/wechat",
            "wechat_jsapi": wechat_jsapi,
            "callback_demo_payload": callback_demo_payload,
            "gateway_notice": "当前为网关骨架模式；接入官方统一下单后 qr_content 将替换为真实 code_url",
        }

    reasons: List[str] = []
    has_required = bool(cfg.alipay_enabled and cfg.alipay_app_id)
    if not cfg.alipay_enabled:
        reasons.append("alipay disabled")
    if not cfg.alipay_app_id:
        reasons.append("alipay_app_id missing")
    if cfg.strict_gateway_mode and not has_required:
        raise ValueError("支付宝网关参数不完整（需启用并配置 app_id）")

    prod_ready = bool(cfg.alipay_public_key and cfg.alipay_private_key)
    if not cfg.alipay_public_key:
        reasons.append("alipay_public_key missing")
    if not cfg.alipay_private_key:
        reasons.append("alipay_private_key missing")
    if cfg.production_gateway_mode and not prod_ready:
        raise ValueError("支付宝生产网关参数不完整（需配置 alipay_public_key/alipay_private_key）")

    alipay_biz_content = {
        "out_trade_no": order_no,
        "product_code": "FAST_INSTANT_TRADE_PAY",
        "total_amount": amount_text,
        "subject": f"会员充值 {order_no}",
    }

    alipay_form = {
        "method": "alipay.trade.page.pay",
        "app_id": cfg.alipay_app_id,
        "charset": "utf-8",
        "sign_type": "HMAC-SHA256",
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "version": "1.0",
        "notify_url": "/api/membership/pay/callback/alipay",
        "biz_content": alipay_biz_content,
    }
    alipay_form_raw = _canonical_sign_text(alipay_form)
    alipay_form["sign"] = _calc_hmac_sha256(alipay_form_raw, (cfg.alipay_secret or "").strip() or "change-me-alipay")

    callback_demo_payload = {
        "out_trade_no": order_no,
        "trade_status": "TRADE_SUCCESS",
        "timestamp": str(int(datetime.now().timestamp())),
    }
    callback_demo_payload["sign"] = _calc_hmac_sha256(
        _canonical_sign_text(callback_demo_payload),
        (cfg.alipay_secret or "").strip() or "change-me-alipay",
    )

    return {
        "provider": "alipay",
        "enabled": bool(cfg.alipay_enabled),
        "gateway_ready": has_required,
        "production_ready": prod_ready,
        "ready_reasons": reasons,
        "mode": "pc_page",
        "out_trade_no": order_no,
        "total_fee_yuan": amount_yuan,
        "pay_url": f"https://openapi.alipay.com/gateway.do?method=alipay.trade.page.pay&app_id={cfg.alipay_app_id}&out_trade_no={order_no}&total_amount={amount_text}",
        "qr_content": f"ALIPAY|{order_no}|{amount_text}",
        "notify_url": "/api/membership/pay/callback/alipay",
        "alipay_form": alipay_form,
        "callback_demo_payload": callback_demo_payload,
        "gateway_notice": "当前为网关骨架模式；接入官方SDK后将返回签名后的正式支付链接",
    }


def create_recharge(token: str, channel: str, amount_yuan: float) -> Dict[str, Any]:
    if _membership_financial_must_proxy_cloud():
        try:
            return _proxy_membership_write_to_cloud(
                "POST",
                "/recharge/create",
                token,
                json_body={"channel": channel, "amount_yuan": amount_yuan},
            )
        except Exception as e:
            raise ValueError(f"云端充值服务不可用，请稍后重试：{e}") from e

    uid = _uid_by_token(token)
    if channel not in ["wechat", "alipay"]:
        raise ValueError("仅支持 wechat/alipay")
    if amount_yuan <= 0:
        raise ValueError("充值金额必须大于0")

    points = int(round(amount_yuan))
    if points <= 0:
        raise ValueError("充值金额过小")

    order_no = _new_order_no("RC")

    conn = _conn()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO recharge_orders(order_no,user_id,channel,amount_yuan,points,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
        (order_no, uid, channel, float(points), points, "pending", _now_str(), _now_str()),
    )
    conn.commit()
    conn.close()

    payment_payload = _build_payment_payload(order_no, channel, float(points))
    return {
        "order_no": order_no,
        "channel": channel,
        "amount_yuan": float(points),
        "points": points,
        "payment": payment_payload,
        "pay_hint": "请拉起 pay_url 或展示 qr_content；支付平台异步回调将更新订单状态",
    }


def mark_recharge_paid(order_no: str) -> Dict[str, Any]:
    init_db()
    conn = _conn()
    cur = conn.cursor()

    order = cur.execute("SELECT * FROM recharge_orders WHERE order_no=?", (order_no,)).fetchone()
    if not order:
        conn.close()
        raise ValueError("订单不存在")
    if order["status"] == "paid":
        conn.close()
        return {"order_no": order_no, "status": "paid", "idempotent": True}

    uid = int(order["user_id"])
    points = int(order["points"])

    cur.execute(
        "UPDATE recharge_orders SET status='paid', paid_at=?, transaction_id=?, updated_at=? WHERE order_no=?",
        (_now_str(), "TXN-" + uuid.uuid4().hex[:16].upper(), _now_str(), order_no),
    )

    _add_points(cur, uid, points, "recharge", order_no, "充值到账")

    # 邀请奖励：被邀请人的首充成功后，给邀请人500积分（一次）
    # 但若“邀请人”和“被邀请人”是同一公司（company_name 归一化后相同），则不发放邀请奖励
    user = cur.execute("SELECT inviter_user_id, company_name FROM users WHERE id=?", (uid,)).fetchone()
    inviter_id = int(user["inviter_user_id"]) if user and user["inviter_user_id"] else None

    if inviter_id:
        inviter = cur.execute("SELECT company_name FROM users WHERE id=?", (inviter_id,)).fetchone()
        invitee_company_key = _company_key(user["company_name"] if user else "")
        inviter_company_key = _company_key(inviter["company_name"] if inviter else "")
        same_company = bool(invitee_company_key and inviter_company_key and invitee_company_key == inviter_company_key)

        if not same_company:
            rewarded = cur.execute("SELECT id FROM invite_rewards WHERE invitee_user_id=?", (uid,)).fetchone()
            paid_count = cur.execute("SELECT COUNT(1) AS c FROM recharge_orders WHERE user_id=? AND status='paid'", (uid,)).fetchone()["c"]
            if not rewarded and int(paid_count) == 1:
                _add_points(cur, inviter_id, 500, "invite_reward", order_no, f"邀请奖励（被邀请人{uid}首充）")
                cur.execute(
                    "INSERT INTO invite_rewards(inviter_user_id,invitee_user_id,trigger_recharge_order_id,reward_points,status,granted_at,created_at) VALUES(?,?,?,?,?,?,?)",
                    (inviter_id, uid, int(order["id"]), 500, "granted", _now_str(), _now_str()),
                )

    acc = cur.execute("SELECT * FROM user_points_accounts WHERE user_id=?", (uid,)).fetchone()
    balance = _points_balance_from_row(acc)
    uname_row = cur.execute("SELECT username FROM users WHERE id=? LIMIT 1", (uid,)).fetchone()
    uname = str(uname_row["username"] or "").strip() if uname_row else ""
    inviter_balance: Optional[float] = None
    inviter_name = ""
    if inviter_id:
        inv_acc = cur.execute("SELECT * FROM user_points_accounts WHERE user_id=?", (inviter_id,)).fetchone()
        inviter_balance = _points_balance_from_row(inv_acc)
        inv_row = cur.execute("SELECT username FROM users WHERE id=? LIMIT 1", (inviter_id,)).fetchone()
        inviter_name = str(inv_row["username"] or "").strip() if inv_row else ""
    conn.commit()
    conn.close()
    sync_points_balance_to_cloud(uid, balance, username=uname)
    if inviter_id and inviter_balance is not None:
        sync_points_balance_to_cloud(int(inviter_id), inviter_balance, username=inviter_name)
    return {"order_no": order_no, "status": "paid"}


def redeem_vip(token: str, months: int = 1) -> Dict[str, Any]:
    months = max(1, int(months or 1))
    if _membership_financial_must_proxy_cloud():
        try:
            return _proxy_membership_write_to_cloud(
                "POST",
                "/vip/redeem",
                token,
                json_body={"months": months},
            )
        except Exception as e:
            raise ValueError(f"云端兑换会员不可用，请稍后重试：{e}") from e

    uid = _uid_by_token(token)
    cost = 1500 * months

    conn = _conn()
    cur = conn.cursor()

    acc = cur.execute("SELECT * FROM user_points_accounts WHERE user_id=?", (uid,)).fetchone()
    if not acc or _points_balance_from_row(acc) + 1e-6 < float(cost):
        conn.close()
        raise ValueError("积分不足")

    user = cur.execute("SELECT vip_expire_at FROM users WHERE id=?", (uid,)).fetchone()
    now = datetime.now()
    start = now
    if user and user["vip_expire_at"]:
        old = datetime.strptime(user["vip_expire_at"], "%Y-%m-%d %H:%M:%S")
        if old > now:
            start = old
    end = start + timedelta(days=30 * months)

    redeem_no = _new_order_no("VIP")
    _add_points(cur, uid, -cost, "vip_redeem", redeem_no, f"兑换会员{months}个月")
    cur.execute("UPDATE users SET vip_expire_at=? WHERE id=?", (end.strftime("%Y-%m-%d %H:%M:%S"), uid))
    _sync_company_membership_by_user(cur, uid)
    cur.execute(
        "INSERT INTO vip_redeem_orders(redeem_no,user_id,points_cost,months,vip_start_at,vip_end_at,status,created_at) VALUES(?,?,?,?,?,?,?,?)",
        (redeem_no, uid, cost, months, start.strftime("%Y-%m-%d %H:%M:%S"), end.strftime("%Y-%m-%d %H:%M:%S"), "success", _now_str()),
    )
    acc2 = cur.execute("SELECT * FROM user_points_accounts WHERE user_id=?", (uid,)).fetchone()
    balance = _points_balance_from_row(acc2)
    uname_row = cur.execute("SELECT username FROM users WHERE id=? LIMIT 1", (uid,)).fetchone()
    uname = str(uname_row["username"] or "").strip() if uname_row else ""
    conn.commit()
    conn.close()
    sync_points_balance_to_cloud(uid, balance, username=uname)
    if use_cloud_points() and token:
        sync_points_balance_from_cloud(uid, token)
    return {"redeem_no": redeem_no, "vip_expire_at": end.strftime("%Y-%m-%d %H:%M:%S")}


def apply_withdraw(token: str, points: int, channel: str, account: str) -> Dict[str, Any]:
    if _membership_financial_must_proxy_cloud():
        try:
            return _proxy_membership_write_to_cloud(
                "POST",
                "/withdraw/apply",
                token,
                json_body={"points": points, "channel": channel, "account": account},
            )
        except Exception as e:
            raise ValueError(f"云端提现申请不可用，请稍后重试：{e}") from e

    uid = _uid_by_token(token)
    if points <= 0:
        raise ValueError("提现积分必须大于0")

    conn = _conn()
    cur = conn.cursor()
    _create_points_account_if_needed(cur, uid)
    acc = cur.execute("SELECT * FROM user_points_accounts WHERE user_id=?", (uid,)).fetchone()
    balance = _points_balance_from_row(acc)
    if not acc or balance + 1e-6 < float(points):
        conn.close()
        raise ValueError("积分不足")

    withdraw_no = _new_order_no("WD")
    new_balance = round(balance - float(points), 4)
    new_frozen = int(acc["frozen_balance"]) + int(points)

    cur.execute(
        """
        UPDATE user_points_accounts
        SET balance_real=?, balance=?, frozen_balance=?, points_fractional_debt=0, updated_at=?
        WHERE user_id=?
        """,
        (new_balance, int(new_balance), new_frozen, _now_str(), uid),
    )
    cur.execute(
        """
        INSERT INTO user_points_ledger(
          user_id,change_amount,balance_after,biz_type,biz_id,remark,created_at,
          change_amount_real,balance_after_real
        ) VALUES(?,?,?,?,?,?,?,?,?)
        """,
        (
            uid,
            -int(points),
            int(new_balance),
            "withdraw_freeze",
            withdraw_no,
            "提现申请，积分冻结",
            _now_str(),
            -float(points),
            new_balance,
        ),
    )

    cur.execute(
        "INSERT INTO withdraw_orders(withdraw_no,user_id,points,amount_yuan,status,pay_channel,pay_account,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
        (withdraw_no, uid, points, float(points), "pending", channel, account, _now_str(), _now_str()),
    )
    conn.commit()
    conn.close()
    return {"withdraw_no": withdraw_no, "status": "pending"}


def _ledger_row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
    d = dict(row)
    if d.get("change_amount_real") is not None:
        d["change_amount"] = round(float(d["change_amount_real"]), 4)
    else:
        d["change_amount"] = round(float(d.get("change_amount") or 0), 4)
    if d.get("balance_after_real") is not None:
        d["balance_after"] = round(float(d["balance_after_real"]), 4)
    else:
        d["balance_after"] = round(float(d.get("balance_after") or 0), 4)
    return d


def list_ledger(token: str, limit: int = 50) -> List[Dict[str, Any]]:
    if use_cloud_points():
        try:
            return cloud_list_ledger(token, limit)
        except Exception:
            logger.warning("cloud_list_ledger failed, fallback to local mirror")

    uid = resolve_user_id_by_token(token)
    conn = _conn()
    cur = conn.cursor()
    rows = cur.execute(
        """
        SELECT id,change_amount,balance_after,biz_type,biz_id,remark,created_at,
               change_amount_real,balance_after_real
        FROM user_points_ledger WHERE user_id=? ORDER BY id DESC LIMIT ?
        """,
        (uid, max(1, min(limit, 200))),
    ).fetchall()
    conn.close()
    return [_ledger_row_to_dict(r) for r in rows]


def list_invite_rewards(token: str, limit: int = 100) -> List[Dict[str, Any]]:
    uid = _uid_by_token(token)
    conn = _conn()
    cur = conn.cursor()
    rows = cur.execute(
        """
        SELECT ir.id, ir.invitee_user_id, u.username AS invitee_username, ir.reward_points, ir.status, ir.granted_at, ir.created_at
        FROM invite_rewards ir
        LEFT JOIN users u ON u.id = ir.invitee_user_id
        WHERE ir.inviter_user_id=?
        ORDER BY ir.id DESC
        LIMIT ?
        """,
        (uid, max(1, min(limit, 500))),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def list_recharge_orders(token: str, status: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
    uid = _uid_by_token(token)
    conn = _conn()
    cur = conn.cursor()
    if status:
        rows = cur.execute(
            "SELECT id,order_no,channel,amount_yuan,points,status,paid_at,transaction_id,created_at,updated_at FROM recharge_orders WHERE user_id=? AND status=? ORDER BY id DESC LIMIT ?",
            (uid, status, max(1, min(limit, 500))),
        ).fetchall()
    else:
        rows = cur.execute(
            "SELECT id,order_no,channel,amount_yuan,points,status,paid_at,transaction_id,created_at,updated_at FROM recharge_orders WHERE user_id=? ORDER BY id DESC LIMIT ?",
            (uid, max(1, min(limit, 500))),
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def list_recharge_orders_paged(token: str, status: Optional[str] = None, page: int = 1, page_size: int = 20) -> Dict[str, Any]:
    uid = _uid_by_token(token)
    page = max(1, int(page or 1))
    page_size = max(1, min(int(page_size or 20), 100))
    offset = (page - 1) * page_size

    conn = _conn()
    cur = conn.cursor()
    if status:
        total = int(cur.execute("SELECT COUNT(1) AS c FROM recharge_orders WHERE user_id=? AND status=?", (uid, status)).fetchone()["c"])
        rows = cur.execute(
            "SELECT id,order_no,channel,amount_yuan,points,status,paid_at,transaction_id,created_at,updated_at FROM recharge_orders WHERE user_id=? AND status=? ORDER BY id DESC LIMIT ? OFFSET ?",
            (uid, status, page_size, offset),
        ).fetchall()
    else:
        total = int(cur.execute("SELECT COUNT(1) AS c FROM recharge_orders WHERE user_id=?", (uid,)).fetchone()["c"])
        rows = cur.execute(
            "SELECT id,order_no,channel,amount_yuan,points,status,paid_at,transaction_id,created_at,updated_at FROM recharge_orders WHERE user_id=? ORDER BY id DESC LIMIT ? OFFSET ?",
            (uid, page_size, offset),
        ).fetchall()
    conn.close()

    return {
        "items": [dict(r) for r in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


def get_admin_dashboard_stats(days: int = 30) -> Dict[str, Any]:
    window_days = max(1, min(days, 365))
    conn = _conn()
    cur = conn.cursor()

    total_users = int(cur.execute("SELECT COUNT(1) AS c FROM users").fetchone()["c"])
    total_recharge_orders = int(cur.execute("SELECT COUNT(1) AS c FROM recharge_orders").fetchone()["c"])
    paid_recharge_orders = int(cur.execute("SELECT COUNT(1) AS c FROM recharge_orders WHERE status='paid'").fetchone()["c"])
    total_recharge_amount = float(cur.execute("SELECT COALESCE(SUM(amount_yuan),0) AS s FROM recharge_orders WHERE status='paid'").fetchone()["s"])

    total_withdraw_orders = int(cur.execute("SELECT COUNT(1) AS c FROM withdraw_orders").fetchone()["c"])
    paid_withdraw_amount = float(cur.execute("SELECT COALESCE(SUM(amount_yuan),0) AS s FROM withdraw_orders WHERE status='paid'").fetchone()["s"])
    pending_withdraw_orders = int(cur.execute("SELECT COUNT(1) AS c FROM withdraw_orders WHERE status='pending'").fetchone()["c"])

    active_vip_users = int(cur.execute("SELECT COUNT(1) AS c FROM users WHERE vip_expire_at IS NOT NULL AND vip_expire_at > ?", (_now_str(),)).fetchone()["c"])

    today = datetime.now().strftime("%Y-%m-%d")
    today_new_users = int(cur.execute("SELECT COUNT(1) AS c FROM users WHERE date(created_at)=?", (today,)).fetchone()["c"])
    today_paid_orders = int(cur.execute("SELECT COUNT(1) AS c FROM recharge_orders WHERE status='paid' AND date(paid_at)=?", (today,)).fetchone()["c"])

    trend = []
    # [性能优化] 废弃循环查询，改为单次 GROUP BY 查询
    start_date = (datetime.now() - timedelta(days=window_days)).strftime("%Y-%m-%d")
    
    recharge_rows = cur.execute(
        "SELECT date(paid_at) as day, SUM(amount_yuan) as total FROM recharge_orders WHERE status='paid' AND date(paid_at) > ? GROUP BY date(paid_at)", 
        (start_date,)
    ).fetchall()
    recharge_map = {row["day"]: float(row["total"] or 0) for row in recharge_rows}
    
    withdraw_rows = cur.execute(
        "SELECT date(updated_at) as day, SUM(amount_yuan) as total FROM withdraw_orders WHERE status='paid' AND date(updated_at) > ? GROUP BY date(updated_at)", 
        (start_date,)
    ).fetchall()
    withdraw_map = {row["day"]: float(row["total"] or 0) for row in withdraw_rows}

    for i in range(window_days - 1, -1, -1):
        day = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
        trend.append({
            "date": day, 
            "recharge": recharge_map.get(day, 0.0), 
            "withdraw": withdraw_map.get(day, 0.0)
        })

    conn.close()
    return {
        "summary": {
            "total_users": total_users,
            "active_vip_users": active_vip_users,
            "total_recharge_orders": total_recharge_orders,
            "paid_recharge_orders": paid_recharge_orders,
            "total_recharge_amount": round(total_recharge_amount, 2),
            "total_withdraw_orders": total_withdraw_orders,
            "pending_withdraw_orders": pending_withdraw_orders,
            "paid_withdraw_amount": round(paid_withdraw_amount, 2),
            "today_new_users": today_new_users,
            "today_paid_orders": today_paid_orders,
        },
        "trend": trend,
    }


def get_recharge_order(token: str, order_no: str) -> Dict[str, Any]:
    uid = _uid_by_token(token)
    conn = _conn()
    cur = conn.cursor()
    row = cur.execute(
        "SELECT order_no,user_id,channel,amount_yuan,points,status,paid_at,transaction_id,created_at,updated_at FROM recharge_orders WHERE order_no=?",
        (order_no,),
    ).fetchone()
    conn.close()
    if not row:
        raise ValueError("订单不存在")
    if int(row["user_id"]) != int(uid):
        raise ValueError("无权查看该订单")
    return dict(row)


def list_withdraw_orders(status: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
    conn = _conn()
    cur = conn.cursor()
    if status:
        rows = cur.execute(
            "SELECT id,withdraw_no,user_id,points,amount_yuan,status,pay_channel,pay_account,created_at,updated_at FROM withdraw_orders WHERE status=? ORDER BY id DESC LIMIT ?",
            (status, max(1, min(limit, 200))),
        ).fetchall()
    else:
        rows = cur.execute(
            "SELECT id,withdraw_no,user_id,points,amount_yuan,status,pay_channel,pay_account,created_at,updated_at FROM withdraw_orders ORDER BY id DESC LIMIT ?",
            (max(1, min(limit, 200)),),
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def approve_withdraw(withdraw_no: str) -> Dict[str, Any]:
    conn = _conn()
    cur = conn.cursor()
    row = cur.execute("SELECT * FROM withdraw_orders WHERE withdraw_no=?", (withdraw_no,)).fetchone()
    if not row:
        conn.close()
        raise ValueError("提现单不存在")
    if row["status"] == "paid":
        conn.close()
        return {"withdraw_no": withdraw_no, "status": "paid", "idempotent": True}
    if row["status"] != "pending":
        conn.close()
        raise ValueError(f"当前状态不可打款: {row['status']}")

    uid = int(row["user_id"])
    points = int(row["points"])
    acc = cur.execute("SELECT * FROM user_points_accounts WHERE user_id=?", (uid,)).fetchone()
    if not acc or int(acc["frozen_balance"]) < points:
        conn.close()
        raise ValueError("冻结积分不足，无法打款")

    new_frozen = int(acc["frozen_balance"]) - points
    new_spent = int(acc["total_spent"]) + points

    cur.execute(
        "UPDATE user_points_accounts SET frozen_balance=?, total_spent=?, updated_at=? WHERE user_id=?",
        (new_frozen, new_spent, _now_str(), uid),
    )
    cur.execute(
        "INSERT INTO user_points_ledger(user_id,change_amount,balance_after,biz_type,biz_id,remark,created_at) VALUES(?,?,?,?,?,?,?)",
        (uid, 0, int(acc["balance"]), "withdraw_success", withdraw_no, "提现审核通过并打款", _now_str()),
    )
    cur.execute(
        "UPDATE withdraw_orders SET status='paid', updated_at=? WHERE withdraw_no=?",
        (_now_str(), withdraw_no),
    )
    conn.commit()
    conn.close()
    return {"withdraw_no": withdraw_no, "status": "paid"}


def reject_withdraw(withdraw_no: str, reason: str = "") -> Dict[str, Any]:
    conn = _conn()
    cur = conn.cursor()
    row = cur.execute("SELECT * FROM withdraw_orders WHERE withdraw_no=?", (withdraw_no,)).fetchone()
    if not row:
        conn.close()
        raise ValueError("提现单不存在")
    if row["status"] == "rejected":
        conn.close()
        return {"withdraw_no": withdraw_no, "status": "rejected", "idempotent": True}
    if row["status"] != "pending":
        conn.close()
        raise ValueError(f"当前状态不可拒绝: {row['status']}")

    uid = int(row["user_id"])
    points = int(row["points"])
    acc = cur.execute("SELECT * FROM user_points_accounts WHERE user_id=?", (uid,)).fetchone()
    if not acc or int(acc["frozen_balance"]) < points:
        conn.close()
        raise ValueError("冻结积分不足，无法退回")

    new_balance = int(acc["balance"]) + points
    new_frozen = int(acc["frozen_balance"]) - points
    cur.execute(
        "UPDATE user_points_accounts SET balance=?, frozen_balance=?, updated_at=? WHERE user_id=?",
        (new_balance, new_frozen, _now_str(), uid),
    )
    cur.execute(
        "INSERT INTO user_points_ledger(user_id,change_amount,balance_after,biz_type,biz_id,remark,created_at) VALUES(?,?,?,?,?,?,?)",
        (uid, points, new_balance, "withdraw_reject", withdraw_no, f"提现驳回退回积分 {reason}".strip(), _now_str()),
    )
    cur.execute(
        "UPDATE withdraw_orders SET status='rejected', updated_at=? WHERE withdraw_no=?",
        (_now_str(), withdraw_no),
    )
    conn.commit()
    conn.close()
    return {"withdraw_no": withdraw_no, "status": "rejected"}


def batch_review_withdraws(withdraw_nos: List[str], action: str, reason: str = "") -> Dict[str, Any]:
    items = [str(x).strip() for x in (withdraw_nos or []) if str(x).strip()]
    if not items:
        raise ValueError("withdraw_nos 不能为空")

    success = []
    failed = []
    for no in items:
        try:
            if action == "approve":
                approve_withdraw(no)
            elif action == "reject":
                reject_withdraw(no, reason)
            else:
                raise ValueError("未知操作")
            success.append(no)
        except Exception as e:
            failed.append({"withdraw_no": no, "error": str(e)})

    return {
        "action": action,
        "total": len(items),
        "success_count": len(success),
        "failed_count": len(failed),
        "success": success,
        "failed": failed,
    }


def _local_membership_snapshot_by_uid(uid: int) -> Dict[str, Any]:
    """鉴权用本地快照：不请求云端，避免每个 API 都卡在 cloud /me 超时。"""
    conn = _conn()
    cur = conn.cursor()
    user = cur.execute("SELECT * FROM users WHERE id=?", (int(uid),)).fetchone()
    row = cur.execute("SELECT mode FROM user_access_controls WHERE user_id=?", (int(uid),)).fetchone()
    conn.close()
    if not user:
        raise ValueError("用户不存在")

    user = dict(user)
    company_name = str(user.get("company_name") or "").strip()
    key = _company_key(company_name)
    if key:
        conn = _conn()
        cur = conn.cursor()
        b = cur.execute(
            "SELECT trial_start_at, trial_end_at, vip_expire_at FROM company_membership_bindings WHERE company_key=?",
            (key,),
        ).fetchone()
        conn.close()
        if b:
            user["trial_start_at"] = b["trial_start_at"]
            user["trial_end_at"] = b["trial_end_at"]
            user["vip_expire_at"] = b["vip_expire_at"]

    now = datetime.now()
    trial_end = datetime.strptime(str(user["trial_end_at"]), "%Y-%m-%d %H:%M:%S")
    vip_expire = datetime.strptime(user["vip_expire_at"], "%Y-%m-%d %H:%M:%S") if user.get("vip_expire_at") else None
    is_vip = bool(vip_expire and vip_expire > now)
    can_use = is_vip or (trial_end > now)

    return {
        "id": int(uid),
        "username": user.get("username"),
        "can_use": can_use,
        "is_vip": is_vip,
        "control_mode": str(row["mode"]).strip().lower() if row and row["mode"] else "normal",
        "company_name": company_name,
    }


def _merge_cloud_membership_into_snapshot(snap: Dict[str, Any], token: str) -> Dict[str, Any]:
    """桌面云端会员模式：用云端 trial/VIP 覆盖本地快照，与 /me 口径一致。"""
    if not use_cloud_points():
        return snap
    cloud = fetch_cloud_me_cached(token, allow_stale=True)
    if not isinstance(cloud, dict):
        return snap
    out = dict(snap)
    for field in ("trial_end_at", "vip_expire_at", "company_name", "username"):
        val = cloud.get(field)
        if val is not None and str(val).strip() != "":
            out[field] = val
    now = datetime.now()
    try:
        trial_end = datetime.strptime(str(out.get("trial_end_at") or ""), "%Y-%m-%d %H:%M:%S")
    except Exception:
        trial_end = None
    vip_raw = out.get("vip_expire_at")
    try:
        vip_expire = datetime.strptime(vip_raw, "%Y-%m-%d %H:%M:%S") if vip_raw else None
    except Exception:
        vip_expire = None
    is_vip = bool(vip_expire and vip_expire > now)
    out["is_vip"] = is_vip
    out["can_use"] = is_vip or bool(trial_end and trial_end > now) or bool(cloud.get("can_use"))
    return out


def evaluate_access_by_token(token: str) -> Dict[str, Any]:
    if is_admin_bearer_token(token):
        return {"allowed": True, "reason": "admin", "info": {"can_use": True}}

    uid = resolve_user_id_by_token(token)

    if int(uid) == 1:
        return {"allowed": True, "reason": "admin", "info": {"id": uid, "can_use": True}}

    snap = _local_membership_snapshot_by_uid(uid)
    mode = str(snap.get("control_mode") or "normal")
    if mode == "normal" and use_cloud_points():
        snap = _merge_cloud_membership_into_snapshot(snap, token)
    info = {k: v for k, v in snap.items() if k != "control_mode"}

    if mode == "force_allow":
        return {"allowed": True, "reason": "force_allow", "info": info}
    if mode == "force_block":
        return {"allowed": False, "reason": "not_member", "info": info}

    if not bool(snap.get("can_use")):
        return {"allowed": False, "reason": "not_member", "info": info}

    return {"allowed": True, "reason": "ok", "info": info}


def can_use_by_token(token: str) -> bool:
    state = evaluate_access_by_token(token)
    return bool(state.get("allowed"))


def _extract_callback_timestamp(payload: Dict[str, Any]) -> Optional[int]:
    for key in ["ts", "timestamp", "notify_time", "gmt_payment"]:
        val = payload.get(key)
        if val is None:
            continue
        try:
            if isinstance(val, (int, float)):
                return int(val)
            txt = str(val).strip()
            if txt.isdigit():
                return int(txt)
            try:
                dt = datetime.strptime(txt, "%Y-%m-%d %H:%M:%S")
                return int(dt.timestamp())
            except Exception:
                pass
        except Exception:
            pass
    return None


def upsert_user_access_control(user_id: int, mode: str, note: str = "") -> Dict[str, Any]:
    m = str(mode or "normal").strip().lower()
    if m not in {"normal", "force_allow", "force_block"}:
        raise ValueError("mode 仅支持 normal/force_allow/force_block")

    init_db()
    conn = _conn()
    cur = conn.cursor()
    exists = cur.execute("SELECT id FROM users WHERE id=?", (int(user_id),)).fetchone()
    if not exists:
        conn.close()
        raise ValueError("用户不存在")

    cur.execute(
        "INSERT INTO user_access_controls(user_id, mode, note, updated_at) VALUES(?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET mode=excluded.mode, note=excluded.note, updated_at=excluded.updated_at",
        (int(user_id), m, str(note or ""), _now_str()),
    )
    conn.commit()
    conn.close()
    return {"user_id": int(user_id), "mode": m, "note": str(note or "")}


def list_users_admin(limit: int = 200) -> List[Dict[str, Any]]:
    init_db()
    conn = _conn()
    cur = conn.cursor()
    rows = cur.execute(
        """
        SELECT u.id, u.username, u.invite_code, u.real_name, u.phone, u.trial_start_at, u.trial_end_at, u.vip_expire_at, u.created_at,
               u.company_name, u.main_category, u.is_verified, u.service_years, u.page_level_star,
               COALESCE(a.balance_real, a.balance, 0) AS points_balance,
               COALESCE(c.mode, 'normal') AS control_mode,
               COALESCE(c.note, '') AS control_note,
               c.updated_at AS control_updated_at,
               s.last_seen_at AS online_last_seen_at,
               CASE
                 WHEN s.last_seen_at IS NOT NULL AND s.last_seen_at >= datetime('now', '-5 minutes') THEN 1
                 ELSE 0
               END AS online
        FROM users u
        LEFT JOIN user_access_controls c ON c.user_id = u.id
        LEFT JOIN user_points_accounts a ON a.user_id = u.id
        LEFT JOIN (
          SELECT user_id, MAX(last_seen_at) AS last_seen_at
          FROM user_sessions
          GROUP BY user_id
        ) s ON s.user_id = u.id
        ORDER BY u.id DESC
        LIMIT ?
        """,
        (max(1, min(int(limit or 200), 2000)),),
    ).fetchall()
    conn.close()
    local_rows = [dict(r) for r in rows]
    # 积分以云端为准时，管理端列表默认合并云端余额，避免“本地显示已改、云端仍是旧值”。
    env_merge = os.getenv("MEMBERSHIP_ADMIN_USERS_CLOUD_MERGE", "").strip().lower()
    if env_merge in {"0", "false", "no"}:
        enabled = False
    elif env_merge in {"1", "true", "yes"}:
        enabled = True
    else:
        enabled = use_cloud_points()
    
    # 优化：云端不可达时仍返回本地数据，而不是空列表
    if enabled:
        try:
            return _merge_cloud_points_into_admin_users(local_rows)
        except Exception as e:
            logger.warning(f"云端用户列表合并失败，返回本地数据: {e}")
            return local_rows
    else:
        return local_rows


def admin_upsert_profile_by_username(
    username: str,
    company_name: str = "",
    main_category: str = "",
    is_verified: str = "",
    service_years: str = "",
    page_level_star: str = "",
) -> Dict[str, Any]:
    """按用户名回写/更新会员店铺资料（用于本地绑定店铺后同步云端）。"""
    uname = str(username or "").strip()
    if not uname:
        raise ValueError("username 不能为空")

    init_db()
    conn = _conn()
    cur = conn.cursor()
    row = cur.execute("SELECT id FROM users WHERE username=? LIMIT 1", (uname,)).fetchone()
    if not row:
        conn.close()
        raise ValueError("用户不存在")

    uid = int(row["id"])
    old = cur.execute(
        "SELECT company_name, main_category, is_verified, service_years, page_level_star FROM users WHERE id=?",
        (uid,),
    ).fetchone()

    next_company_name = str(company_name or "").strip() or (str(old["company_name"] or "").strip() if old else "")
    next_main_category = str(main_category or "").strip() or (str(old["main_category"] or "").strip() if old else "")
    next_is_verified = str(is_verified or "").strip() or (str(old["is_verified"] or "").strip() if old else "")
    next_service_years = str(service_years or "").strip() or (str(old["service_years"] or "").strip() if old else "")
    next_page_level_star = str(page_level_star or "").strip() or (str(old["page_level_star"] or "").strip() if old else "")

    cur.execute(
        """
        UPDATE users
        SET company_name=?, main_category=?, is_verified=?, service_years=?, page_level_star=?
        WHERE id=?
        """,
        (
            next_company_name,
            next_main_category,
            next_is_verified,
            next_service_years,
            next_page_level_star,
            uid,
        ),
    )

    # 公司绑定：有公司名则同步公司级会员快照
    if str(company_name or "").strip():
        _sync_company_membership_by_user(cur, uid)

    conn.commit()
    conn.close()

    return {
        "user_id": uid,
        "username": uname,
        "company_name": str(company_name or "").strip(),
        "main_category": str(main_category or "").strip(),
        "updated": True,
    }


def admin_update_user(
    user_id: int,
    new_password: Optional[str] = None,
    points_balance: Optional[float] = None,
    trial_start_at: Optional[str] = None,
    trial_end_at: Optional[str] = None,
    vip_expire_at: Optional[str] = None,
) -> Dict[str, Any]:
    uid = int(user_id or 0)
    if uid <= 0:
        raise ValueError("user_id 非法")

    init_db()
    conn = _conn()
    cur = conn.cursor()
    u = cur.execute("SELECT id, username FROM users WHERE id=?", (uid,)).fetchone()
    if not u:
        conn.close()
        raise ValueError("用户不存在")

    uname = str(u["username"] or "").strip()
    has_cloud_fields = bool(
        (new_password is not None and str(new_password).strip())
        or points_balance is not None
        or (trial_start_at is not None and str(trial_start_at).strip())
        or (trial_end_at is not None and str(trial_end_at).strip())
        or vip_expire_at is not None
    )

    cloud_synced = False
    if _membership_cloud_sync_enabled() and has_cloud_fields:
        cloud_uid = _resolve_cloud_user_id(uname, local_user_id=uid, cur=cur)
        if not cloud_uid:
            cloud_rows = _cloud_admin_list_users(force_refresh=True)
            if not cloud_rows:
                conn.close()
                raise ValueError(
                    "无法读取云端会员列表，请检查 admin_api_key、CLOUD_MEMBERSHIP_API_BASE 和云端网络连通性。"
                )
            conn.close()
            raise ValueError(
                f"云端管理员接口可用，但列表中未找到账号（{uname}）。"
                "请确认本地账号与云端用户名完全一致。"
            )
        _persist_cloud_user_id(uid, int(cloud_uid), cur=cur, username=uname)
        _push_admin_user_update_to_cloud(
            int(cloud_uid),
            username=uname,
            new_password=new_password,
            points_balance=points_balance,
            trial_start_at=trial_start_at,
            trial_end_at=trial_end_at,
            vip_expire_at=vip_expire_at,
        )
        cloud_synced = True

    if new_password is not None and str(new_password).strip():
        cur.execute("UPDATE users SET password_hash=? WHERE id=?", (_hash_pwd(str(new_password).strip()), uid))

    if trial_start_at is not None and str(trial_start_at).strip():
        cur.execute("UPDATE users SET trial_start_at=? WHERE id=?", (str(trial_start_at).strip(), uid))

    if trial_end_at is not None and str(trial_end_at).strip():
        cur.execute("UPDATE users SET trial_end_at=? WHERE id=?", (str(trial_end_at).strip(), uid))

    if vip_expire_at is not None:
        val = str(vip_expire_at).strip()
        cur.execute("UPDATE users SET vip_expire_at=? WHERE id=?", (val if val else None, uid))

    # 管理员拥有最高权限：手动改会员时间后，需同步刷新公司绑定快照，避免被旧绑定值反向覆盖
    changed_membership_window = bool(
        (trial_start_at is not None and str(trial_start_at).strip())
        or (trial_end_at is not None and str(trial_end_at).strip())
        or (vip_expire_at is not None)
    )
    if changed_membership_window:
        current = cur.execute(
            "SELECT company_name, trial_start_at, trial_end_at, vip_expire_at FROM users WHERE id=?",
            (uid,),
        ).fetchone()
        company_name = str(current["company_name"] or "").strip() if current else ""
        key = _company_key(company_name)
        if key and current:
            exists = cur.execute(
                "SELECT id FROM company_membership_bindings WHERE company_key=?",
                (key,),
            ).fetchone()
            if exists:
                cur.execute(
                    "UPDATE company_membership_bindings SET company_name=?, trial_start_at=?, trial_end_at=?, vip_expire_at=?, updated_at=? WHERE company_key=?",
                    (
                        company_name,
                        str(current["trial_start_at"] or ""),
                        str(current["trial_end_at"] or ""),
                        str(current["vip_expire_at"] or "").strip() or None,
                        _now_str(),
                        key,
                    ),
                )

    _sync_company_membership_by_user(cur, uid)

    if points_balance is not None:
        _create_points_account_if_needed(cur, uid)
        synced_pb = round(max(0.0, float(points_balance)), 4)
        cur.execute(
            """
            UPDATE user_points_accounts
            SET balance_real=?, balance=?, points_fractional_debt=0, updated_at=?
            WHERE user_id=?
            """,
            (synced_pb, int(synced_pb), _now_str(), uid),
        )

    conn.commit()
    conn.close()
    return {"user_id": uid, "updated": True, "cloud_synced": cloud_synced}


def register_agent_node(agent_id: str, client_name: str = "", machine_id: str = "", app_version: str = "", license_key: str = "") -> Dict[str, Any]:
    aid = str(agent_id or "").strip()
    if not aid:
        raise ValueError("agent_id 不能为空")

    init_db()
    conn = _conn()
    cur = conn.cursor()
    now = _now_str()
    cur.execute(
        "INSERT INTO agent_nodes(agent_id, client_name, machine_id, app_version, license_key, status, last_seen_at, created_at, updated_at) VALUES(?,?,?,?,?,'active',?,?,?) ON CONFLICT(agent_id) DO UPDATE SET client_name=excluded.client_name, machine_id=excluded.machine_id, app_version=excluded.app_version, license_key=excluded.license_key, status='active', last_seen_at=excluded.last_seen_at, updated_at=excluded.updated_at",
        (aid, str(client_name or ""), str(machine_id or ""), str(app_version or ""), str(license_key or ""), now, now, now),
    )
    conn.commit()
    conn.close()
    return {"agent_id": aid, "status": "active", "last_seen_at": now}


def heartbeat_agent_node(agent_id: str, status: str = "active") -> Dict[str, Any]:
    aid = str(agent_id or "").strip()
    if not aid:
        raise ValueError("agent_id 不能为空")

    st = str(status or "active").strip().lower() or "active"
    init_db()
    conn = _conn()
    cur = conn.cursor()
    now = _now_str()
    cur.execute(
        "UPDATE agent_nodes SET status=?, last_seen_at=?, updated_at=? WHERE agent_id=?",
        (st, now, now, aid),
    )
    if cur.rowcount <= 0:
        cur.execute(
            "INSERT INTO agent_nodes(agent_id, status, last_seen_at, created_at, updated_at) VALUES(?,?,?,?,?)",
            (aid, st, now, now, now),
        )
    conn.commit()
    conn.close()
    return {"agent_id": aid, "status": st, "last_seen_at": now}


def upsert_agent_policy(agent_id: str, policy: Dict[str, Any]) -> Dict[str, Any]:
    aid = str(agent_id or "").strip()
    if not aid:
        raise ValueError("agent_id 不能为空")

    expire_at = str((policy or {}).get("expire_at") or "").strip()
    note = str((policy or {}).get("note") or "").strip()

    p = {
        "allow_download": bool((policy or {}).get("allow_download", True)),
        "allow_analysis": bool((policy or {}).get("allow_analysis", True)),
        "allow_upload": bool((policy or {}).get("allow_upload", True)),
        "allow_image": bool((policy or {}).get("allow_image", True)),
        "allow_video_bind": bool((policy or {}).get("allow_video_bind", True)),
        "max_daily_tasks": int((policy or {}).get("max_daily_tasks", 9999) or 9999),
        "expire_at": expire_at,
        "note": note,
    }

    now = _now_str()
    init_db()
    conn = _conn()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO agent_policies(agent_id, policy_json, updated_at) VALUES(?,?,?) ON CONFLICT(agent_id) DO UPDATE SET policy_json=excluded.policy_json, updated_at=excluded.updated_at",
        (aid, json.dumps(p, ensure_ascii=False), now),
    )
    conn.commit()
    conn.close()
    return {"agent_id": aid, "policy": p, "updated_at": now}


def get_agent_policy(agent_id: str) -> Dict[str, Any]:
    aid = str(agent_id or "").strip()
    if not aid:
        raise ValueError("agent_id 不能为空")

    default_policy = {
        "allow_download": True,
        "allow_analysis": True,
        "allow_upload": True,
        "allow_image": True,
        "allow_video_bind": True,
        "max_daily_tasks": 9999,
        "expire_at": "",
        "note": "",
    }

    init_db()
    conn = _conn()
    cur = conn.cursor()
    row = cur.execute("SELECT policy_json, updated_at FROM agent_policies WHERE agent_id=?", (aid,)).fetchone()
    conn.close()
    if not row:
        return {"agent_id": aid, "policy": default_policy, "updated_at": None}

    try:
        parsed = json.loads(str(row["policy_json"] or "{}"))
    except Exception:
        parsed = {}

    merged = {**default_policy, **(parsed or {})}

    exp = str(merged.get("expire_at") or "").strip()
    if exp:
        try:
            exp_dt = datetime.strptime(exp, "%Y-%m-%d %H:%M:%S")
            if exp_dt <= datetime.now():
                merged["allow_download"] = False
                merged["allow_analysis"] = False
                merged["allow_upload"] = False
                merged["allow_image"] = False
                merged["allow_video_bind"] = False
        except Exception:
            pass

    return {"agent_id": aid, "policy": merged, "updated_at": row["updated_at"]}


def list_agents_admin(limit: int = 300) -> List[Dict[str, Any]]:
    ensure_membership_db_ready()
    conn = _conn()
    cur = conn.cursor()
    rows = cur.execute(
        """
        SELECT
          n.agent_id,
          n.client_name,
          n.machine_id,
          n.app_version,
          n.license_key,
          n.status,
          n.last_seen_at,
          n.created_at,
          n.updated_at,
          p.policy_json,
          u.username,
          u.company_name
        FROM agent_nodes n
        LEFT JOIN agent_policies p ON p.agent_id = n.agent_id
        LEFT JOIN (
          SELECT
            s.device_id,
            s.user_id,
            MAX(s.last_seen_at) AS last_seen_at
          FROM user_sessions s
          WHERE COALESCE(s.device_id, '') <> ''
          GROUP BY s.device_id, s.user_id
        ) us ON us.device_id = n.machine_id
        LEFT JOIN users u ON u.id = us.user_id
        ORDER BY n.id DESC, us.last_seen_at DESC
        LIMIT ?
        """,
        (max(1, min(int(limit or 300), 5000)),),
    ).fetchall()
    conn.close()

    out = []
    seen_agent_ids = set()
    for r in rows:
        item = dict(r)
        aid = str(item.get("agent_id") or "").strip()
        if not aid or aid in seen_agent_ids:
            # 设备可能存在多账号历史会话，保留最新一条用于展示
            continue
        seen_agent_ids.add(aid)
        try:
            item["policy"] = json.loads(str(item.get("policy_json") or "{}")) if item.get("policy_json") else {}
        except Exception:
            item["policy"] = {}
        item.pop("policy_json", None)
        company_name = str(item.get("company_name") or "").strip()
        username = str(item.get("username") or "").strip()
        client_name = str(item.get("client_name") or "").strip()
        item["display_client_name"] = company_name or username or client_name or "-"
        out.append(item)
    return out


def ingest_keyword_report(agent_id: str, report_date: str, batch_no: str, items: List[Dict[str, Any]], source: str = "") -> Dict[str, Any]:
    aid = str(agent_id or "").strip()
    d = str(report_date or "").strip()
    b = str(batch_no or "").strip()
    if not aid or not d or not b:
        raise ValueError("agent_id/report_date/batch_no 不能为空")
    # 统一按“天”做覆盖：兼容上传端传 yyyy-mm-dd 或 yyyy-mm-dd HH:MM:SS
    d = d[:10]

    init_db()
    conn = _conn()
    cur = conn.cursor()

    now = _now_str()
    # 业务约束：同一节点在同一天只保留一条回传，后来的上传覆盖旧数据
    existing_rows = cur.execute(
        "SELECT id FROM keyword_reports WHERE agent_id=? AND report_date=? ORDER BY id DESC",
        (aid, d),
    ).fetchall()

    if existing_rows:
        report_id = int(existing_rows[0]["id"])
        cur.execute(
            "UPDATE keyword_reports SET source=?, batch_no=?, item_count=0, created_at=? WHERE id=?",
            (str(source or ""), b, now, report_id),
        )
        # 历史脏数据清理：若已存在多条同日回传，仅保留最新一条
        for r in existing_rows[1:]:
            dup_id = int(r["id"])
            cur.execute("DELETE FROM keyword_report_items WHERE report_id=?", (dup_id,))
            cur.execute("DELETE FROM keyword_reports WHERE id=?", (dup_id,))
    else:
        cur.execute(
            "INSERT INTO keyword_reports(agent_id, report_date, source, batch_no, item_count, created_at) VALUES(?,?,?,?,?,?)",
            (aid, d, str(source or ""), b, 0, now),
        )
        report_id = int(cur.lastrowid or 0)
        if report_id <= 0:
            conn.close()
            raise ValueError("创建关键词回传批次失败")

    cur.execute("DELETE FROM keyword_report_items WHERE report_id=?", (report_id,))

    def _num(v: Any) -> float:
        try:
            return float(str(v or "0").replace(",", "").strip() or "0")
        except Exception:
            return 0.0

    inserted = 0
    for it in (items or []):
        kw = str((it or {}).get("keyword") or "").strip()
        if not kw:
            continue
        cur.execute(
            "INSERT INTO keyword_report_items(report_id, keyword, exposure, click, ctr, keyword_index, product_id) VALUES(?,?,?,?,?,?,?)",
            (
                report_id,
                kw,
                _num((it or {}).get("exposure")),
                _num((it or {}).get("click")),
                _num((it or {}).get("ctr")),
                _num((it or {}).get("keyword_index")),
                str((it or {}).get("product_id") or ""),
            ),
        )
        inserted += 1

    cur.execute("UPDATE keyword_reports SET item_count=? WHERE id=?", (inserted, report_id))
    conn.commit()
    conn.close()

    return {"agent_id": aid, "report_date": d, "batch_no": b, "item_count": inserted}


def list_keyword_reports_admin(agent_id: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
    ensure_membership_db_ready()
    conn = _conn()
    cur = conn.cursor()
    if agent_id:
        rows = cur.execute(
            "SELECT id, agent_id, report_date, source, batch_no, item_count, created_at FROM keyword_reports WHERE agent_id=? ORDER BY id DESC LIMIT ?",
            (str(agent_id).strip(), max(1, min(int(limit or 100), 2000))),
        ).fetchall()
    else:
        rows = cur.execute(
            "SELECT id, agent_id, report_date, source, batch_no, item_count, created_at FROM keyword_reports ORDER BY id DESC LIMIT ?",
            (max(1, min(int(limit or 100), 2000)),),
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_keyword_report_detail(report_id: int, limit: int = 200) -> Dict[str, Any]:
    rid = int(report_id or 0)
    if rid <= 0:
        raise ValueError("report_id 非法")

    init_db()
    conn = _conn()
    cur = conn.cursor()
    report = cur.execute(
        "SELECT id, agent_id, report_date, source, batch_no, item_count, created_at FROM keyword_reports WHERE id=?",
        (rid,),
    ).fetchone()
    if not report:
        conn.close()
        raise ValueError("回传批次不存在")

    rows = cur.execute(
        "SELECT keyword, exposure, click, ctr, keyword_index, product_id FROM keyword_report_items WHERE report_id=? ORDER BY exposure DESC, click DESC LIMIT ?",
        (rid, max(1, min(int(limit or 200), 5000))),
    ).fetchall()
    conn.close()
    return {"report": dict(report), "items": [dict(r) for r in rows]}


def delete_keyword_reports_admin(report_ids: List[int]) -> Dict[str, Any]:
    ids = sorted({int(x or 0) for x in (report_ids or []) if int(x or 0) > 0})
    if not ids:
        return {"deleted_reports": 0, "deleted_items": 0, "requested": 0}

    init_db()
    conn = _conn()
    cur = conn.cursor()

    placeholders = ",".join(["?"] * len(ids))
    row = cur.execute(f"SELECT COUNT(1) AS c FROM keyword_reports WHERE id IN ({placeholders})", tuple(ids)).fetchone()
    matched = int((row["c"] if row else 0) or 0)

    cur.execute(f"DELETE FROM keyword_report_items WHERE report_id IN ({placeholders})", tuple(ids))
    item_deleted = int(cur.rowcount or 0)
    cur.execute(f"DELETE FROM keyword_reports WHERE id IN ({placeholders})", tuple(ids))
    report_deleted = int(cur.rowcount or 0)

    conn.commit()
    conn.close()
    return {
        "matched_count": matched,
        "deleted_reports": report_deleted,
        "deleted_items": item_deleted,
    }


def _verify_common_callback_security(payload: Dict[str, Any], provider: str, client_ip: str = "") -> Tuple[bool, str]:
    cfg = get_config().payment
    allowed_ips = cfg.wechat_callback_allowed_ips if provider == "wechat" else cfg.alipay_callback_allowed_ips
    if allowed_ips:
        ip = (client_ip or "").strip()
        if ip not in set([str(x).strip() for x in allowed_ips if str(x).strip()]):
            return False, f"{provider} callback ip not allowed: {ip}"

    ts = _extract_callback_timestamp(payload)
    tol = max(30, int(cfg.callback_timestamp_tolerance_sec or 600))
    if ts is not None:
        now_ts = int(datetime.now().timestamp())
        if abs(now_ts - ts) > tol:
            return False, f"{provider} callback timestamp expired"
    return True, "callback-security-ok"


def _canonical_sign_text(payload: Dict[str, Any], excluded_keys: Optional[List[str]] = None) -> str:
    excluded = set(["sign", "signature"] + (excluded_keys or []))
    items = []
    for k in sorted(payload.keys()):
        if k in excluded:
            continue
        v = payload.get(k)
        if v is None:
            continue
        if isinstance(v, (dict, list)):
            vv = json.dumps(v, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        else:
            vv = str(v)
        items.append(f"{k}={vv}")
    return "&".join(items)


def _calc_hmac_sha256(text: str, secret: str) -> str:
    return hmac.new(secret.encode("utf-8"), text.encode("utf-8"), hashlib.sha256).hexdigest().upper()


def _verify_wechat_signature(payload: Dict[str, Any], client_ip: str = "") -> Tuple[bool, str]:
    cfg = get_config().payment
    if not cfg.wechat_enabled:
        return False, "wechat disabled"

    ok, reason = _verify_common_callback_security(payload, "wechat", client_ip)
    if not ok:
        return False, reason

    secret = (cfg.wechat_secret or "").strip()
    got = str(payload.get("sign") or payload.get("signature") or "").strip().upper()
    if not secret:
        return False, "wechat secret empty"
    if not got:
        return False, "wechat signature empty"

    raw = _canonical_sign_text(payload)
    expect = _calc_hmac_sha256(raw, secret)
    if got != expect:
        return False, "wechat signature mismatch"
    return True, "wechat-signature-ok"


def _verify_alipay_signature(payload: Dict[str, Any], client_ip: str = "") -> Tuple[bool, str]:
    cfg = get_config().payment
    if not cfg.alipay_enabled:
        return False, "alipay disabled"

    ok, reason = _verify_common_callback_security(payload, "alipay", client_ip)
    if not ok:
        return False, reason

    secret = (cfg.alipay_secret or "").strip()
    got = str(payload.get("sign") or payload.get("signature") or "").strip().upper()
    if not secret:
        return False, "alipay secret empty"
    if not got:
        return False, "alipay signature empty"

    raw = _canonical_sign_text(payload)
    expect = _calc_hmac_sha256(raw, secret)
    if got != expect:
        return False, "alipay signature mismatch"
    return True, "alipay-signature-ok"


def _extract_paid_order_no(payload: Dict[str, Any], provider: str) -> str:
    if provider == "wechat":
        return str(
            payload.get("out_trade_no")
            or payload.get("order_no")
            or payload.get("attach")
            or payload.get("resource", {}).get("ciphertext", "")
            or ""
        ).strip()
    return str(payload.get("out_trade_no") or payload.get("order_no") or payload.get("trade_no") or "").strip()


def _is_payment_success(payload: Dict[str, Any], provider: str) -> bool:
    if provider == "wechat":
        # 兼容字段：trade_state / event_type
        trade_state = str(payload.get("trade_state") or payload.get("resource", {}).get("trade_state") or "").upper()
        event_type = str(payload.get("event_type") or "").upper()
        if trade_state:
            return trade_state in {"SUCCESS", "TRADE_SUCCESS", "PAY_SUCCESS"}
        if event_type:
            return event_type in {"TRANSACTION.SUCCESS", "PAYMENT.SUCCESS", "TRADE_SUCCESS"}
        return True

    # alipay: trade_status
    trade_status = str(payload.get("trade_status") or "").upper()
    if trade_status:
        return trade_status in {"TRADE_SUCCESS", "TRADE_FINISHED", "SUCCESS"}
    return True


def handle_wechat_callback(payload: Dict[str, Any], client_ip: str = "") -> Dict[str, Any]:
    """微信回调：验签 + IP白名单 + 时间戳防重放 + 幂等入账。"""
    ok, reason = _verify_wechat_signature(payload, client_ip)
    if not ok:
        raise ValueError(f"微信回调验签失败: {reason}")

    if not _is_payment_success(payload, "wechat"):
        return {"provider": "wechat", "status": "ignored", "reason": "trade not success"}

    order_no = _extract_paid_order_no(payload, "wechat")
    if not order_no:
        raise ValueError("回调缺少 order_no/out_trade_no")

    result = mark_recharge_paid(order_no)
    result["provider"] = "wechat"
    result["verify"] = reason
    return result


def handle_alipay_callback(payload: Dict[str, Any], client_ip: str = "") -> Dict[str, Any]:
    """支付宝回调：验签 + IP白名单 + 时间戳防重放 + 幂等入账。"""
    ok, reason = _verify_alipay_signature(payload, client_ip)
    if not ok:
        raise ValueError(f"支付宝回调验签失败: {reason}")

    if not _is_payment_success(payload, "alipay"):
        return {"provider": "alipay", "status": "ignored", "reason": "trade not success"}

    order_no = _extract_paid_order_no(payload, "alipay")
    if not order_no:
        raise ValueError("回调缺少 out_trade_no/order_no")

    result = mark_recharge_paid(order_no)
    result["provider"] = "alipay"
    result["verify"] = reason
    return result

# -*- coding: utf-8 -*-
"""
全系统 API 验收（不含产品上传子菜单：发品/优化上架/视频绑定/发品配置）。
覆盖各页面加载、状态查询、会员中心管理员面板。

Security / regression（需本机 backend 已加载最新代码后重启）：
- security:invalid_me_fast_fail — 无效 token 调 /me 须在 ACCEPTANCE_ME_INVALID_MAX_SEC（默认 5s）内 401
- security:member_*_masked — 会员读全量 config / admin-runtime 须脱敏，即使带残留 X-Admin-Key
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

BASE = os.getenv("ACCEPTANCE_BACKEND", "http://127.0.0.1:8000")
# 凭证仅通过环境变量注入，勿在仓库中写默认账号密码（登录以云端为准）
MEMBER_USER = (os.getenv("ACCEPTANCE_MEMBER_USER") or "").strip()
MEMBER_PASS = (os.getenv("ACCEPTANCE_MEMBER_PASS") or "").strip()
ADMIN_USER = (os.getenv("ACCEPTANCE_ADMIN_USER") or "").strip()
ADMIN_PASS = (os.getenv("ACCEPTANCE_ADMIN_PASS") or "").strip()
TIMEOUT = int(os.getenv("ACCEPTANCE_TIMEOUT", "45"))
ME_INVALID_TOKEN_MAX_SEC = float(os.getenv("ACCEPTANCE_ME_INVALID_MAX_SEC", "5"))
IGNORE_MASK_CHECKS = os.getenv("ACCEPTANCE_IGNORE_MASK_CHECKS", "").strip().lower() in {"1", "true", "yes"}
PLACEHOLDER_KEYS = frozenset({"", "change-me-admin", "change-me"})

# (method, path, name, acceptable_statuses)
# 404 = 无数据文件但接口正常；400 = 参数缺失但路由可达
READ_CHECKS = [
    # 控制台 / 配置
    ("GET", "/api/config/", "dashboard:config", {200}),
    ("GET", "/api/config/revision", "dashboard:config_revision", {200}),
    ("GET", "/api/config/admin-runtime", "config:admin_runtime", {200}),
    ("GET", "/api/config/cloud-admin-revision", "config:cloud_revision", {200}),
    ("GET", "/api/config/template", "config:template", {200}),
    ("GET", "/api/config/attributes/list", "config:attributes", {200}),
    ("GET", "/api/config/group-urls/list", "config:group_urls", {200}),
    # 会员
    ("GET", "/api/membership/connectivity", "membership:connectivity", {200}),
    ("GET", "/api/membership/me", "membership:me", {200}),
    ("GET", "/api/membership/points/ledger", "membership:ledger", {200, 400}),
    ("GET", "/api/membership/recharge/list-paged", "membership:recharge_list", {200, 400}),
    ("GET", "/api/membership/invite/rewards", "membership:invite_rewards", {200, 400}),
    # 分析
    ("GET", "/api/analysis/overview", "analysis:overview", {200}),
    ("GET", "/api/analysis/points-pricing", "analysis:points_pricing", {200}),
    ("GET", "/api/analysis/status/comprehensive", "analysis:status_comprehensive", {200}),
    ("GET", "/api/analysis/status/single_analysis", "analysis:status_single", {200}),
    ("GET", "/api/analysis/status/traffic_ai", "analysis:status_traffic_ai", {200}),
    ("GET", "/api/analysis/status/title_optimize", "analysis:status_title_optimize", {200}),
    ("GET", "/api/analysis/traffic-ai/result", "analysis:traffic_ai_result", {200, 404}),
    ("GET", "/api/analysis/title-optimize/results", "analysis:title_optimize_results", {200, 404}),
    ("GET", "/api/analysis/title-optimize/points-estimate", "analysis:title_points_est", {200}),
    ("GET", "/api/analysis/traffic-ai/points-estimate", "analysis:traffic_points_est", {200}),
    ("GET", "/api/analysis/volatility/anomaly", "analysis:volatility", {200, 404}),
    ("GET", "/api/analysis/new-links/monitor", "analysis:new_links", {200, 404}),
    ("GET", "/api/analysis/diagnosis/table", "analysis:diagnosis_table", {200, 404}),
    ("GET", "/api/analysis/statistics/table", "analysis:statistics_table", {200, 404}),
    ("GET", "/api/analysis/p4p/table", "analysis:p4p_table", {200, 404}),
    # 数据下载
    ("GET", "/api/data/download/status", "download:all_status", {200}),
    ("GET", "/api/data/download/status/keyword_parser", "download:status_keyword", {200}),
    ("GET", "/api/data/download/status/industry_keyword", "download:status_industry", {200}),
    ("GET", "/api/data/download/status/store_data", "download:status_store", {200}),
    ("GET", "/api/data/download/status/store_image", "download:status_store_image", {200}),
    ("GET", "/api/data/download/status/traffic_channel", "download:status_traffic_channel", {200}),
    ("GET", "/api/data/download/status/product_operate", "download:status_product_operate", {200}),
    ("GET", "/api/data/files", "download:files", {200, 404}),
    ("GET", "/api/data/keyword/summary/latest", "download:keyword_summary", {200, 404}),
    ("GET", "/api/data/keyword/anomaly/latest", "download:keyword_anomaly", {200, 404}),
    ("GET", "/api/data/industry-keyword/latest", "download:industry_keyword", {200, 404}),
    ("GET", "/api/data/industry-keyword/dropdown/latest", "download:industry_dropdown", {200, 404}),
    ("GET", "/api/data/store/overview/latest", "download:store_overview", {200, 404}),
    ("GET", "/api/data/store/summary/table", "download:store_summary", {200, 404}),
    ("GET", "/api/data/traffic-channel/overview", "download:traffic_channel", {200, 404}),
    ("GET", "/api/data/store-image/list", "download:store_image_list", {200, 404}),
    ("GET", "/api/data/product-operate/table", "download:product_operate", {200, 404}),
    ("GET", "/api/data/industry-keyword/title/generate/status", "download:title_gen_status", {200}),
    # 图片 / AI 生图
    ("GET", "/api/images/groups", "images:groups", {200}),
    ("GET", "/api/images/stats", "images:stats", {200}),
    ("GET", "/api/images/normalize/status", "images:normalize_status", {200}),
    ("GET", "/api/images/logs/recent", "images:logs", {200}),
    ("GET", "/api/images/ai-gen/config", "ai_gen:config", {200}),
    ("GET", "/api/images/ai-gen/status", "ai_gen:status", {200}),
    ("GET", "/api/images/ai-gen/inputs", "ai_gen:inputs", {200, 404}),
    ("GET", "/api/images/ai-gen/outputs", "ai_gen:outputs", {200, 404}),
    ("GET", "/api/images/ai-gen/points-pricing", "ai_gen:points_pricing", {200}),
    ("GET", "/api/images/ai-gen/points-estimate", "ai_gen:points_estimate", {200}),
    ("GET", "/api/images/ai-gen/logs/recent", "ai_gen:logs", {200}),
    # 任务列表
    ("GET", "/api/tasks/list", "tasks:list", {200}),
]

ADMIN_LOCAL_CHECKS = [
    ("GET", "/api/membership/admin/agents", "admin:local_agents"),
    ("GET", "/api/membership/admin/telemetry/keywords", "admin:local_keywords"),
]

ADMIN_CLOUD_CHECKS = [
    ("GET", "/admin/users", "admin:cloud_users"),
    ("GET", "/admin/dashboard", "admin:cloud_dashboard"),
    ("GET", "/admin/withdraw/list", "admin:cloud_withdraws"),
]

EXCLUDED_NOTE = "发品配置 Cookie/平台抓取 — 需浏览器，未纳入读接口验收；启动类见 acceptance_crud / comprehensive"


def ok(name: str, passed: bool, detail: str = "") -> bool:
    mark = "PASS" if passed else "FAIL"
    line = f"[{mark}] {name}"
    if detail:
        line += f" — {detail}"
    print(line)
    return passed


def load_admin_key() -> str:
    key = os.getenv("ACCEPTANCE_ADMIN_KEY", "").strip()
    deploy = ROOT / "frontend" / "electron" / "desktop.deploy.json"
    deploy_key = ""
    if deploy.is_file():
        try:
            deploy_key = str(json.loads(deploy.read_text(encoding="utf-8-sig")).get("admin_api_key") or "").strip()
        except Exception:
            pass
    if not key:
        for cfg in (
            Path(os.environ.get("APPDATA", "")) / "AliAutoPublish" / "data" / "config.json",
            ROOT / "data" / "config.json",
        ):
            try:
                if cfg.is_file():
                    key = str((json.loads(cfg.read_text(encoding="utf-8-sig")).get("payment") or {}).get("admin_api_key") or "").strip()
                    if key and key not in PLACEHOLDER_KEYS:
                        break
            except Exception:
                pass
    if key in PLACEHOLDER_KEYS and deploy_key:
        key = deploy_key
    return key


def check_db() -> list[bool]:
    out: list[bool] = []
    core = ("users", "user_sessions", "user_points_accounts", "admin_accounts")
    agent = ("agent_nodes", "agent_policies", "keyword_reports", "keyword_report_items")
    app_db = Path(os.environ.get("APPDATA", "")) / "AliAutoPublish" / "data" / "membership.db"
    for label, db in (("AppData", app_db), ("Project", ROOT / "data" / "membership.db")):
        if not db.is_file():
            out.append(ok(f"db:{label}", False, "missing"))
            continue
        tables = {
            r[0]
            for r in sqlite3.connect(db).execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        miss = [t for t in core + agent if t not in tables]
        out.append(ok(f"db:{label}:schema", not miss, f"missing={','.join(miss)}" if miss else f"{len(tables)} tables"))
    return out


def run_reads(session: requests.Session, prefix: str) -> list[bool]:
    out: list[bool] = []
    for method, path, name, codes in READ_CHECKS:
        try:
            t0 = time.perf_counter()
            r = session.request(method, f"{BASE}{path}", timeout=TIMEOUT)
            dt = time.perf_counter() - t0
            passed = r.status_code in codes and r.status_code not in (401, 403, 500, 502, 503)
            slow = " SLOW" if dt > 8 else ""
            out.append(ok(f"{prefix}:{name}", passed, f"HTTP {r.status_code} {dt:.2f}s{slow}"))
        except requests.Timeout:
            out.append(ok(f"{prefix}:{name}", False, "timeout"))
        except Exception as e:
            out.append(ok(f"{prefix}:{name}", False, str(e)[:100]))
    return out


def admin_session_setup() -> tuple[requests.Session, str]:
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    admin_key = load_admin_key()
    token = ""
    if ADMIN_PASS:
        r = s.post(f"{BASE}/api/membership/auth/login", json={"username": ADMIN_USER, "password": ADMIN_PASS}, timeout=TIMEOUT)
        data = (r.json() or {}).get("data") or {}
        token = str(data.get("token") or "")
        admin_key = str(data.get("admin_key") or admin_key)
    elif admin_key:
        r = s.post(f"{BASE}/api/membership/auth/sync-admin-session", headers={"X-Admin-Key": admin_key}, timeout=TIMEOUT)
        data = (r.json() or {}).get("data") or {}
        token = str(data.get("token") or "")
    if admin_key:
        s.headers["X-Admin-Key"] = admin_key
    if token:
        s.headers["Authorization"] = f"Bearer {token}"
    return s, admin_key


def member_session_setup() -> requests.Session:
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    if not MEMBER_USER or not MEMBER_PASS:
        return s
    r = s.post(f"{BASE}/api/membership/auth/login", json={"username": MEMBER_USER, "password": MEMBER_PASS}, timeout=TIMEOUT)
    token = str(((r.json() or {}).get("data") or {}).get("token") or "")
    s.headers["Authorization"] = f"Bearer {token}"
    return s


def _is_masked_secret(value: str) -> bool:
    s = str(value or "").strip()
    if not s:
        return True
    if s == "***" or s.startswith("***"):
        return True
    if len(s) > 4 and not s[2:-2].replace("*", ""):
        return True
    return False


def check_member_config_masking(member_token: str, admin_key: str) -> list[bool]:
    """会员读全量 config 必须脱敏；即使携带残留 X-Admin-Key 也不得返回明文密钥。"""
    out: list[bool] = []
    if IGNORE_MASK_CHECKS:
        out.append(ok("security:member_config_mask", True, "skipped (ACCEPTANCE_IGNORE_MASK_CHECKS=1)"))
        return out
    if not member_token:
        out.append(ok("security:member_config_mask", False, "no member token"))
        return out
    headers = {"Authorization": f"Bearer {member_token}"}
    if admin_key:
        headers["X-Admin-Key"] = admin_key
    try:
        r = requests.get(f"{BASE}/api/config/", headers=headers, timeout=TIMEOUT)
        body = r.json() if r.content else {}
        cfg = (body.get("data") or {}) if isinstance(body, dict) else {}
        da = cfg.get("data_analysis") or {}
        ai = cfg.get("ai_image_gen") or {}
        da_key = str(da.get("doubao_api_key") or "")
        ai_key = str(ai.get("doubao_api_key") or "")
        gem_key = str(ai.get("gemini_api_key") or "")
        out.append(ok("security:member_full_config_masked", r.status_code == 200 and _is_masked_secret(da_key), f"da_key={da_key[:12]}"))
        out.append(
            ok(
                "security:member_ai_keys_masked",
                _is_masked_secret(ai_key) and _is_masked_secret(gem_key),
                f"ai={ai_key[:8]} gem={gem_key[:8]}",
            )
        )
        ar = requests.get(f"{BASE}/api/config/admin-runtime", headers=headers, timeout=TIMEOUT)
        ar_da = ((ar.json() or {}).get("data") or {}).get("data_analysis") or {}
        ar_key = str(ar_da.get("doubao_api_key") or "")
        out.append(ok("security:member_admin_runtime_masked", ar.status_code == 200 and _is_masked_secret(ar_key), f"key={ar_key[:12]}"))
    except Exception as e:
        out.append(ok("security:member_config_mask", False, str(e)[:120]))
    return out


def check_invalid_token_me_fast_fail() -> list[bool]:
    """无效 token 调 /me 应快速 401，不等待云端长超时。"""
    out: list[bool] = []
    try:
        t0 = time.perf_counter()
        r = requests.get(
            f"{BASE}/api/membership/me",
            headers={"Authorization": "Bearer invalid-for-perf-test-token"},
            timeout=TIMEOUT,
        )
        dt = time.perf_counter() - t0
        passed = r.status_code in (401, 403) and dt <= ME_INVALID_TOKEN_MAX_SEC
        out.append(
            ok(
                "security:invalid_me_fast_fail",
                passed,
                f"{dt:.2f}s HTTP {r.status_code} (max {ME_INVALID_TOKEN_MAX_SEC:g}s)",
            )
        )
    except requests.Timeout:
        out.append(ok("security:invalid_me_fast_fail", False, f"timeout>{TIMEOUT}s"))
    except Exception as e:
        out.append(ok("security:invalid_me_fast_fail", False, str(e)[:100]))
    return out


def main() -> int:
    print("=== Full system acceptance (excl. product upload subtree) ===")
    print(EXCLUDED_NOTE)
    print()

    results: list[bool] = []
    try:
        h = requests.get(f"{BASE}/api/health", timeout=10)
        results.append(ok("health", h.ok, h.text[:60]))
    except Exception as e:
        print(f"[FAIL] health — {e}")
        return 1

    results.extend(check_db())
    print()

    admin_s, admin_key = admin_session_setup()
    member_s = member_session_setup()

    member_token = str(member_s.headers.get("Authorization") or "").replace("Bearer ", "").strip()
    results.append(ok("member:login", bool(member_token), ""))
    results.append(ok("admin:session", bool(admin_key) and admin_key not in PLACEHOLDER_KEYS, admin_key[:8] + "..." if admin_key else "empty"))

    print("\n--- Security / regression ---")
    results.extend(check_invalid_token_me_fast_fail())
    results.extend(check_member_config_masking(member_token, admin_key))

    print("\n--- Admin reads ---")
    results.extend(run_reads(admin_s, "admin"))

    if member_token:
        print("\n--- Member reads ---")
        results.extend(run_reads(member_s, "member"))
    else:
        print("\n--- Member reads SKIPPED (set ACCEPTANCE_MEMBER_USER and ACCEPTANCE_MEMBER_PASS) ---")

    print("\n--- Admin local panel ---")
    for method, path, name in ADMIN_LOCAL_CHECKS:
        try:
            r = admin_s.request(method, f"{BASE}{path}", params={"limit": 20}, timeout=TIMEOUT)
            body = r.text.lower()
            passed = r.status_code == 200 and "no such table" not in body
            results.append(ok(f"admin:{name}", passed, f"HTTP {r.status_code}"))
        except Exception as e:
            results.append(ok(f"admin:{name}", False, str(e)[:80]))

    print("\n--- Admin cloud panel ---")
    cloud = os.getenv("CLOUD_MEMBERSHIP_API_BASE", "https://echo-yiwu.cloud/api/membership").rstrip("/")
    for method, path, name in ADMIN_CLOUD_CHECKS:
        try:
            r = requests.request(method, f"{cloud}{path}", headers={"X-Admin-Key": admin_key}, params={"limit": 20, "days": 30}, timeout=TIMEOUT)
            results.append(ok(f"admin:{name}", r.status_code == 200, f"HTTP {r.status_code}"))
        except Exception as e:
            results.append(ok(f"admin:{name}", False, str(e)[:80]))

    print("\n--- Admin session key refresh ---")
    try:
        ak = load_admin_key()
        if ak in PLACEHOLDER_KEYS:
            raise RuntimeError("no admin key for sync-admin-session")
        sr = requests.post(
            f"{BASE}/api/membership/auth/sync-admin-session",
            headers={"X-Admin-Key": ak},
            timeout=TIMEOUT,
        )
        tok = str(((sr.json() or {}).get("data") or {}).get("token") or "")
        r = requests.get(
            f"{BASE}/api/membership/auth/admin-session-key",
            headers={"Authorization": f"Bearer {tok}"},
            timeout=TIMEOUT,
        )
        key = str(((r.json() or {}).get("data") or {}).get("admin_key") or "")
        results.append(ok("admin:session_key_api", r.status_code == 200 and key not in PLACEHOLDER_KEYS, f"HTTP {r.status_code}"))
    except Exception as e:
        results.append(ok("admin:session_key_api", False, str(e)[:100]))

    passed = sum(1 for x in results if x)
    total = len(results)
    print(f"\n=== Summary: {passed}/{total} passed ===")
    if passed < total:
        print("FAILED checks need attention before claiming full system OK.")
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())

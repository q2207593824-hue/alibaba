# -*- coding: utf-8 -*-
"""
全量功能验收：按前端页面/模块映射 API（含产品上传子树只读探测）。
与 acceptance_full_system / acceptance_crud 互补；不启动浏览器/Selenium 任务。
"""
from __future__ import annotations

import json
import os
import subprocess
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
TIMEOUT = int(os.getenv("ACCEPTANCE_TIMEOUT", "45"))
PLACEHOLDER_KEYS = frozenset({"", "change-me-admin", "change-me"})

# (page_id, page_title, method, path, acceptable_statuses)
# 404 = 无数据文件但路由正常；400 = 缺参但可达
PAGE_API_MATRIX: list[tuple[str, str, str, str, set[int]]] = [
    # —— 控制台 ——
    ("dashboard", "控制台", "GET", "/api/config/", {200}),
    ("dashboard", "控制台", "GET", "/api/config/revision", {200}),
    ("dashboard", "控制台", "GET", "/api/analysis/overview", {200}),
    ("dashboard", "控制台", "GET", "/api/tasks/list", {200}),
    # —— 产品上传 ——
    ("product-upload", "自动发品", "GET", "/api/upload/status", {200}),
    ("product-upload", "自动发品", "GET", "/api/upload/products/available", {200}),
    ("product-upload", "自动发品", "GET", "/api/upload/products/published", {200}),
    # —— 优化上架 ——
    ("optimize-product", "优化上架", "GET", "/api/upload/optimize/status", {200}),
    ("optimize-product", "优化上架", "GET", "/api/upload/optimize/list", {200}),
    ("optimize-product", "优化上架", "GET", "/api/upload/optimize/failed-today", {200}),
    # —— 视频绑定 ——
    ("video-bind", "视频绑定", "GET", "/api/video-bind/status", {200}),
    ("video-bind", "视频绑定", "GET", "/api/video-bind/new-links-preview", {200, 404}),
    # —— 发品配置 ——
    ("product-config", "发品配置", "GET", "/api/config/template", {200}),
    ("product-config", "发品配置", "GET", "/api/config/attributes/list", {200}),
    ("product-config", "发品配置", "GET", "/api/config/group-urls/list", {200}),
    ("product-config", "发品配置", "GET", "/api/config/admin-runtime", {200}),
    # —— 图片管理 ——
    ("image-manager", "图片管理", "GET", "/api/images/groups", {200}),
    ("image-manager", "图片管理", "GET", "/api/images/stats", {200}),
    ("image-manager", "图片管理", "GET", "/api/images/config", {200}),
    ("image-manager", "图片管理", "GET", "/api/images/normalize/status", {200}),
    ("image-manager", "图片管理", "GET", "/api/images/logs/recent", {200}),
    # —— AI 生图 ——
    ("ai-image-gen", "AI生图", "GET", "/api/images/ai-gen/config", {200}),
    ("ai-image-gen", "AI生图", "GET", "/api/images/ai-gen/status", {200}),
    ("ai-image-gen", "AI生图", "GET", "/api/images/ai-gen/inputs", {200, 404}),
    ("ai-image-gen", "AI生图", "GET", "/api/images/ai-gen/outputs", {200, 404}),
    ("ai-image-gen", "AI生图", "GET", "/api/images/ai-gen/points-pricing", {200}),
    ("ai-image-gen", "AI生图", "GET", "/api/images/ai-gen/points-estimate", {200}),
    ("ai-image-gen", "AI生图", "GET", "/api/images/ai-gen/logs/recent", {200}),
    # —— 店铺图采集 ——
    ("store-image-collect", "店铺图采集", "GET", "/api/data/download/status/store_image", {200}),
    ("store-image-collect", "店铺图采集", "GET", "/api/data/store-image/list", {200, 404}),
    # —— 数据下载各页 ——
    ("data-download", "数据下载", "GET", "/api/data/download/status", {200}),
    ("keyword-download", "关键词下载", "GET", "/api/data/download/status/keyword_parser", {200}),
    ("keyword-download", "关键词下载", "GET", "/api/data/keyword/summary/latest", {200, 404}),
    ("keyword-download", "关键词下载", "GET", "/api/data/keyword/anomaly/latest", {200, 404}),
    ("industry-keyword", "行业关键词", "GET", "/api/data/download/status/industry_keyword", {200}),
    ("industry-keyword", "行业关键词", "GET", "/api/data/industry-keyword/latest", {200, 404}),
    ("industry-keyword", "行业关键词", "GET", "/api/data/industry-keyword/dropdown/latest", {200, 404}),
    ("industry-keyword", "行业关键词", "GET", "/api/data/industry-keyword/title/generate/status", {200}),
    ("store-data", "店铺数据", "GET", "/api/data/download/status/store_data", {200}),
    ("store-data", "店铺数据", "GET", "/api/data/store/overview/latest", {200, 404}),
    ("store-data", "店铺数据", "GET", "/api/data/store/summary/table", {200, 404}),
    ("traffic-channel-download", "流量渠道下载", "GET", "/api/data/download/status/traffic_channel", {200}),
    ("traffic-channel-download", "流量渠道下载", "GET", "/api/data/traffic-channel/overview", {200, 404}),
    ("product-operate-download", "产品经营下载", "GET", "/api/data/download/status/product_operate", {200}),
    ("product-operate-download", "产品经营下载", "GET", "/api/data/product-operate/table", {200, 404}),
    # —— 数据分析 ——
    ("data-analysis", "数据分析", "GET", "/api/analysis/points-pricing", {200}),
    ("data-analysis", "数据分析", "GET", "/api/analysis/status/comprehensive", {200}),
    ("product-diagnosis", "产品诊断", "GET", "/api/analysis/diagnosis/table", {200, 404}),
    ("single-product-analysis", "单品分析", "GET", "/api/analysis/statistics/table", {200, 404}),
    ("traffic-analysis", "流量分析", "GET", "/api/analysis/status/traffic_ai", {200}),
    ("traffic-analysis", "流量分析", "GET", "/api/analysis/traffic-ai/result", {200, 404}),
    ("single-product-channel", "单品渠道", "GET", "/api/data/product360/table", {200, 404}),
    ("p4p-analysis", "直通车", "GET", "/api/analysis/p4p/table", {200, 404}),
    ("new-links-analysis", "新链接", "GET", "/api/analysis/new-links/monitor", {200, 404}),
    ("title-optimize-analysis", "标题优化", "GET", "/api/analysis/status/title_optimize", {200}),
    ("title-optimize-analysis", "标题优化", "GET", "/api/analysis/title-optimize/results", {200, 404}),
    # —— 会员中心 ——
    ("membership", "会员中心", "GET", "/api/membership/connectivity", {200}),
    ("membership", "会员中心", "GET", "/api/membership/me", {200}),
    ("membership", "会员中心", "GET", "/api/membership/points/ledger", {200, 400}),
    ("membership", "会员中心", "GET", "/api/membership/recharge/list-paged", {200, 400}),
    ("membership", "会员中心", "GET", "/api/membership/invite/rewards", {200, 400}),
]

# 需浏览器/Cookie/真实支付/长时 Selenium — 仅记录为人工项
MANUAL_BUTTON_CHECKS = [
    ("product-config", "Cookie 浏览器登录", "POST /api/config/cookie/login-by-browser-manager"),
    ("product-config", "从平台拉取属性", "POST /api/config/attributes/fetch-from-platform"),
    ("product-config", "从平台拉取规格", "POST /api/config/specifications/fetch-from-platform"),
    ("membership", "绑定店铺", "POST /api/config/cookie/login-by-browser-manager"),
    ("image-manager", "开始规范化", "POST /api/images/normalize/start"),
    ("ai-image-gen", "开始 AI 生图", "POST /api/images/ai-gen/start"),
    ("data-download", "各下载任务启动", "POST /api/data/download/start"),
    ("data-analysis", "各分析任务启动", "POST /api/analysis/start"),
    ("membership", "充值/提现/支付回调", "云端支付链路"),
    ("global", "WebSocket 实时日志", "WS /api/ws/logs"),
    ("global", "WebSocket 任务状态", "WS /api/ws/tasks"),
]


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


def member_session() -> tuple[requests.Session, str]:
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    if not MEMBER_USER or not MEMBER_PASS:
        return s, ""
    r = s.post(f"{BASE}/api/membership/auth/login", json={"username": MEMBER_USER, "password": MEMBER_PASS}, timeout=TIMEOUT)
    token = str(((r.json() or {}).get("data") or {}).get("token") or "")
    if token:
        s.headers["Authorization"] = f"Bearer {token}"
    return s, token


def admin_session() -> tuple[requests.Session, str]:
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    admin_key = load_admin_key()
    token = ""
    if admin_key:
        r = s.post(f"{BASE}/api/membership/auth/sync-admin-session", headers={"X-Admin-Key": admin_key}, timeout=TIMEOUT)
        token = str(((r.json() or {}).get("data") or {}).get("token") or "")
        s.headers["X-Admin-Key"] = admin_key
    if token:
        s.headers["Authorization"] = f"Bearer {token}"
    return s, admin_key


UPLOAD_START_JOBS = (
    ("product-upload", "upload", "/api/upload/start", "/api/upload/stop", {"mode": "batch", "max_products": 1}),
    ("optimize-product", "optimize", "/api/upload/optimize/start", "/api/upload/optimize/stop", {}),
    ("video-bind", "video_bind", "/api/video-bind/start", "/api/video-bind/stop", {}),
)


def run_upload_start_stop(session: requests.Session, role: str) -> list[bool]:
    """发品 / 优化上架 / 视频绑定：启动后立即停止。"""
    results: list[bool] = []
    for page_id, label, start_path, stop_path, body in UPLOAD_START_JOBS:
        name = f"{role}:start_stop:{page_id}:{label}"
        try:
            sr = session.post(f"{BASE}{start_path}", json=body, timeout=TIMEOUT)
            start_ok = sr.status_code in (200, 409)
            results.append(ok(f"{name}:start", start_ok, f"HTTP {sr.status_code}"))
            tr = session.post(f"{BASE}{stop_path}", json={}, timeout=TIMEOUT)
            results.append(ok(f"{name}:stop", tr.status_code in (200, 400), f"HTTP {tr.status_code}"))
        except requests.Timeout:
            results.append(ok(f"{name}:start", False, "timeout"))
            results.append(ok(f"{name}:stop", False, "timeout"))
        except Exception as e:
            results.append(ok(name, False, str(e)[:100]))
    return results


def run_page_matrix(session: requests.Session, role: str) -> list[bool]:
    results: list[bool] = []
    seen_pages: dict[str, list[bool]] = {}
    for page_id, title, method, path, codes in PAGE_API_MATRIX:
        name = f"{role}:page:{page_id}:{path.rstrip('/').split('/')[-1] or 'root'}"
        try:
            t0 = time.perf_counter()
            r = session.request(method, f"{BASE}{path}", timeout=TIMEOUT)
            dt = time.perf_counter() - t0
            passed = r.status_code in codes and r.status_code not in (401, 403, 500, 502, 503)
            slow = " SLOW" if dt > 10 else ""
            results.append(ok(name, passed, f"HTTP {r.status_code} {dt:.2f}s{slow}"))
            seen_pages.setdefault(page_id, []).append(passed)
        except requests.Timeout:
            results.append(ok(name, False, "timeout"))
            seen_pages.setdefault(page_id, []).append(False)
        except Exception as e:
            results.append(ok(name, False, str(e)[:100]))
            seen_pages.setdefault(page_id, []).append(False)

    print(f"\n--- {role} page summary ---")
    for page_id in sorted(seen_pages.keys()):
        flags = seen_pages[page_id]
        title = next((t for pid, t, *_ in PAGE_API_MATRIX if pid == page_id), page_id)
        all_ok = all(flags)
        ok(f"{role}:page_summary:{page_id}({title})", all_ok, f"{sum(flags)}/{len(flags)} apis")
        results.append(all_ok)
    return results


def main() -> int:
    print("=== Comprehensive page/API acceptance ===\n")
    results: list[bool] = []

    try:
        h = requests.get(f"{BASE}/api/health", timeout=10)
        results.append(ok("health", h.ok, h.text[:80]))
    except Exception as e:
        print(f"[FAIL] health — {e}\nStart backend: cd backend && python -m uvicorn app.main:app --host 127.0.0.1 --port 8000")
        return 1

    member_s, member_token = member_session()
    admin_s, admin_key = admin_session()
    member_login_ok = bool(member_token)
    results.append(ok("auth:member_token", member_login_ok, "skipped member pages" if not member_login_ok else ""))
    results.append(ok("auth:admin_key", bool(admin_key) and admin_key not in PLACEHOLDER_KEYS, admin_key[:10] + "..." if admin_key else "empty"))

    if member_login_ok:
        print("\n--- Member: all pages ---")
        results.extend(run_page_matrix(member_s, "member"))
        print("\n--- Member: upload / optimize / video-bind start-stop ---")
        results.extend(run_upload_start_stop(member_s, "member"))
    else:
        print("\n--- Member: SKIPPED (login failed; set ACCEPTANCE_MEMBER_USER/PASS or fix cloud) ---")

    print("\n--- Admin: all pages ---")
    results.extend(run_page_matrix(admin_s, "admin"))
    print("\n--- Admin: upload / optimize / video-bind start-stop ---")
    results.extend(run_upload_start_stop(admin_s, "admin"))

    print("\n--- Manual / browser-only buttons (not auto-tested) ---")
    for page_id, label, api in MANUAL_BUTTON_CHECKS:
        print(f"  [MANUAL] {page_id}: {label} → {api}")

    passed = sum(1 for x in results if x)
    total = len(results)
    print(f"\n=== Comprehensive summary: {passed}/{total} automated checks passed ===")
    print(f"=== Manual items: {len(MANUAL_BUTTON_CHECKS)} (require Chrome/Cookie/payment) ===")
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())

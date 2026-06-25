# -*- coding: utf-8 -*-
"""API 验收（不含产品上传）：会员 + 管理员（无需绑定店铺）。"""
from __future__ import annotations

import json
import os
import sys
import time

import requests

BASE = os.getenv("ACCEPTANCE_BACKEND", "http://127.0.0.1:8000")
# 凭证仅通过环境变量注入，勿在仓库中写默认账号密码（登录以云端为准）
MEMBER_USER = (os.getenv("ACCEPTANCE_MEMBER_USER") or "").strip()
MEMBER_PASS = (os.getenv("ACCEPTANCE_MEMBER_PASS") or "").strip()
ADMIN_USER = (os.getenv("ACCEPTANCE_ADMIN_USER") or "").strip()
ADMIN_PASS = (os.getenv("ACCEPTANCE_ADMIN_PASS") or "").strip()
ADMIN_KEY = os.getenv("ACCEPTANCE_ADMIN_KEY", "")
TIMEOUT = int(os.getenv("ACCEPTANCE_TIMEOUT", "60"))


def ok(name: str, passed: bool, detail: str = "") -> bool:
    mark = "PASS" if passed else "FAIL"
    line = f"[{mark}] {name}"
    if detail:
        line += f" — {detail}"
    print(line)
    return passed


def load_admin_key() -> str:
    if ADMIN_KEY:
        return ADMIN_KEY.strip()
    cfg_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "data",
        "config.json",
    )
    try:
        with open(cfg_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return str((data.get("payment") or {}).get("admin_api_key") or "").strip()
    except Exception:
        return ""


FEATURE_ENDPOINTS = [
    ("GET", "/api/config/", "config"),
    ("GET", "/api/config/revision", "config_revision"),
    ("GET", "/api/config/cloud-admin-revision", "cloud_admin_revision"),
    ("GET", "/api/membership/connectivity", "cloud_connectivity"),
    ("GET", "/api/membership/me", "membership_me"),
    ("GET", "/api/analysis/overview", "analysis_overview"),
    ("GET", "/api/analysis/points-pricing", "points_pricing"),
    ("GET", "/api/analysis/status/title_optimize", "title_optimize_status"),
    ("GET", "/api/analysis/status/traffic_ai", "traffic_ai_status"),
    ("GET", "/api/analysis/title-optimize/results", "title_optimize_results"),
    ("GET", "/api/analysis/traffic-ai/result", "traffic_ai_result"),
    ("GET", "/api/analysis/title-optimize/points-estimate", "title_points_estimate"),
    ("GET", "/api/analysis/traffic-ai/points-estimate", "traffic_points_estimate"),
    ("GET", "/api/analysis/volatility/anomaly", "volatility_anomaly"),
    ("GET", "/api/analysis/new-links/monitor", "new_links_monitor"),
    ("GET", "/api/analysis/diagnosis/table", "diagnosis_table"),
    ("GET", "/api/analysis/statistics/table", "statistics_table"),
    ("GET", "/api/analysis/p4p/table", "p4p_table"),
    ("GET", "/api/data/download/status", "data_download_status"),
    ("GET", "/api/images/ai-gen/status", "ai_image_status"),
    ("GET", "/api/video-bind/status", "video_bind_status"),
    ("GET", "/api/config/attributes/list", "config_attributes_list"),
    ("GET", "/api/config/group-urls/list", "config_group_urls"),
]


def run_feature_checks(session: requests.Session, label: str) -> list[bool]:
    results: list[bool] = []
    for method, path, name in FEATURE_ENDPOINTS:
        check_name = f"{label}:{name}"
        try:
            r = session.request(method, f"{BASE}{path}", timeout=TIMEOUT)
            passed = r.status_code not in (401, 403, 500, 502, 503)
            detail = f"HTTP {r.status_code}"
            if not passed:
                detail += " " + r.text[:120]
            results.append(ok(check_name, passed, detail))
        except requests.Timeout:
            results.append(ok(check_name, False, "timeout"))
        except Exception as e:
            results.append(ok(check_name, False, str(e)[:120]))
    return results


def main() -> int:
    session = requests.Session()
    session.headers.update({"Content-Type": "application/json"})
    results: list[bool] = []

    try:
        r = session.get(f"{BASE}/api/health", timeout=15)
        results.append(ok("health", r.ok and r.json().get("service") == "ali-auto-publish-backend", r.text[:80]))
    except Exception as e:
        results.append(ok("health", False, str(e)))
        print("backend not running, abort.")
        return 1

    admin_key = load_admin_key()

    # --- 管理员：无需绑定店铺 ---
    admin_session = requests.Session()
    admin_session.headers.update({"Content-Type": "application/json"})
    admin_token = ""
    if ADMIN_PASS:
        try:
            r = admin_session.post(
                f"{BASE}/api/membership/auth/login",
                json={"username": ADMIN_USER, "password": ADMIN_PASS},
                timeout=TIMEOUT,
            )
            data = r.json().get("data") or {}
            admin_token = data.get("token") or ""
            role = data.get("role")
            ak = data.get("admin_key") or admin_key
            if ak:
                admin_session.headers["X-Admin-Key"] = ak
            if admin_token:
                admin_session.headers["Authorization"] = f"Bearer {admin_token}"
            results.append(
                ok(
                    "admin_login",
                    r.ok and role == "admin" and bool(admin_token),
                    f"role={role}",
                )
            )
        except Exception as e:
            results.append(ok("admin_login", False, str(e)))
    elif admin_key:
        try:
            admin_session.headers["X-Admin-Key"] = admin_key
            r = admin_session.post(
                f"{BASE}/api/membership/auth/sync-admin-session",
                headers={"X-Admin-Key": admin_key},
                timeout=TIMEOUT,
            )
            data = r.json().get("data") or {}
            admin_token = data.get("token") or ""
            if admin_token:
                admin_session.headers["Authorization"] = f"Bearer {admin_token}"
            results.append(
                ok(
                    "admin_sync_session",
                    r.ok and bool(admin_token),
                    f"token={'yes' if admin_token else 'no'}",
                )
            )
        except Exception as e:
            results.append(ok("admin_sync_session", False, str(e)))
    else:
        results.append(ok("admin_login", False, "set ACCEPTANCE_ADMIN_PASS or admin_api_key in config"))

    if admin_token or admin_key:
        try:
            r = admin_session.get(f"{BASE}/api/config/", timeout=TIMEOUT)
            store_blocked = r.status_code == 403 and "未绑定店铺" in r.text
            results.append(
                ok(
                    "admin_no_store_binding",
                    r.status_code == 200 and not store_blocked,
                    f"HTTP {r.status_code}",
                )
            )
        except Exception as e:
            results.append(ok("admin_no_store_binding", False, str(e)))

        results.extend(run_feature_checks(admin_session, "admin"))

    # --- 会员（凭证仅环境变量，登录走云端）---
    if not MEMBER_USER or not MEMBER_PASS:
        results.append(ok("member_login", False, "set ACCEPTANCE_MEMBER_USER/PASS"))
        passed_n = sum(1 for x in results if x)
        print(f"\n=== Summary: {passed_n}/{len(results)} passed (member skipped) ===")
        return 0 if passed_n == len(results) else 1

    member_session = requests.Session()
    member_session.headers.update({"Content-Type": "application/json"})
    try:
        r = member_session.post(
            f"{BASE}/api/membership/auth/login",
            json={"username": MEMBER_USER, "password": MEMBER_PASS},
            timeout=TIMEOUT,
        )
        data = r.json().get("data") or {}
        token = data.get("token") or ""
        member_session.headers["Authorization"] = f"Bearer {token}"
        results.append(ok("member_login", r.ok and bool(token), f"role={data.get('role')}"))
    except Exception as e:
        results.append(ok("member_login", False, str(e)))
        print("\n=== Summary: member login failed ===")
        passed_n = sum(1 for x in results if x)
        print(f"{passed_n}/{len(results)} passed")
        return 1

    results.extend(run_feature_checks(member_session, "member"))

    elapsed = time.time()
    passed_n = sum(1 for x in results if x)
    total = len(results)
    print(f"\n=== Summary: {passed_n}/{total} passed ===")
    return 0 if passed_n == total else 1


if __name__ == "__main__":
    sys.exit(main())

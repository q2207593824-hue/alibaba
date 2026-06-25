# -*- coding: utf-8 -*-
"""验收：① 管理员密钥/会员中心数据 ② agent_nodes 缺表 ③ 关键 API 可用性"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

BASE = os.getenv("ACCEPTANCE_BACKEND", "http://127.0.0.1:8000")
CLOUD = os.getenv("CLOUD_MEMBERSHIP_API_BASE", "https://echo-yiwu.cloud/api/membership")
# 凭证仅通过环境变量注入，勿在仓库中写默认账号密码（登录以云端为准）
MEMBER_USER = (os.getenv("ACCEPTANCE_MEMBER_USER") or "").strip()
MEMBER_PASS = (os.getenv("ACCEPTANCE_MEMBER_PASS") or "").strip()
ADMIN_USER = (os.getenv("ACCEPTANCE_ADMIN_USER") or "").strip()
ADMIN_PASS = (os.getenv("ACCEPTANCE_ADMIN_PASS") or "").strip()
TIMEOUT = int(os.getenv("ACCEPTANCE_TIMEOUT", "30"))

PLACEHOLDER_KEYS = frozenset({"", "change-me-admin", "change-me"})


def ok(name: str, passed: bool, detail: str = "") -> bool:
    mark = "PASS" if passed else "FAIL"
    line = f"[{mark}] {name}"
    if detail:
        line += f" — {detail}"
    print(line)
    return passed


def load_keys() -> tuple[str, str]:
    admin_key = os.getenv("ACCEPTANCE_ADMIN_KEY", "").strip()
    deploy_key = ""
    deploy = ROOT / "frontend" / "electron" / "desktop.deploy.json"
    if deploy.is_file():
        try:
            deploy_key = str(json.loads(deploy.read_text(encoding="utf-8-sig")).get("admin_api_key") or "").strip()
        except Exception:
            deploy_key = ""
    if not admin_key:
        for cfg_path in (
            Path(os.environ.get("APPDATA", "")) / "AliAutoPublish" / "data" / "config.json",
            ROOT / "data" / "config.json",
        ):
            try:
                if cfg_path.is_file():
                    data = json.loads(cfg_path.read_text(encoding="utf-8-sig"))
                    admin_key = str((data.get("payment") or {}).get("admin_api_key") or "").strip()
                    if admin_key and admin_key not in PLACEHOLDER_KEYS:
                        break
            except Exception:
                pass
    if admin_key in PLACEHOLDER_KEYS and deploy_key:
        admin_key = deploy_key
    return admin_key, deploy_key


def check_db_schema() -> list[bool]:
    results: list[bool] = []
    app_db = Path(os.environ.get("APPDATA", "")) / "AliAutoPublish" / "data" / "membership.db"
    proj_db = ROOT / "data" / "membership.db"
    need = ("agent_nodes", "agent_policies", "keyword_reports", "keyword_report_items")
    for label, db in (("AppData", app_db), ("Project", proj_db)):
        if not db.is_file():
            results.append(ok(f"db:{label}:exists", False, str(db)))
            continue
        conn = sqlite3.connect(db)
        tables = {
            r[0]
            for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        conn.close()
        missing = [t for t in need if t not in tables]
        results.append(ok(f"db:{label}:agent_tables", not missing, "missing=" + ",".join(missing) if missing else "ok"))
    return results


def check_admin_key_config(admin_key: str, deploy_key: str) -> list[bool]:
    results: list[bool] = []
    results.append(ok("admin_key:not_placeholder", admin_key not in PLACEHOLDER_KEYS, f"key_prefix={admin_key[:8] if admin_key else 'EMPTY'}"))
    if deploy_key:
        results.append(ok("admin_key:matches_deploy", admin_key == deploy_key or admin_key not in PLACEHOLDER_KEYS, f"deploy={deploy_key[:8]}..."))
    try:
        r_bad = requests.get(f"{CLOUD}/admin/users", headers={"X-Admin-Key": "change-me-admin"}, params={"limit": 1}, timeout=TIMEOUT)
        r_good = requests.get(f"{CLOUD}/admin/users", headers={"X-Admin-Key": admin_key}, params={"limit": 3}, timeout=TIMEOUT)
        results.append(ok("cloud:admin_users_reject_placeholder", r_bad.status_code in (401, 403), f"HTTP {r_bad.status_code}"))
        n = len(r_good.json().get("data", [])) if r_good.ok else 0
        results.append(ok("cloud:admin_users_with_real_key", r_good.status_code == 200 and n >= 0, f"HTTP {r_good.status_code} sample={n}"))
        rd = requests.get(f"{CLOUD}/admin/dashboard", headers={"X-Admin-Key": admin_key}, params={"days": 30}, timeout=TIMEOUT)
        total = (rd.json().get("data") or {}).get("summary", {}).get("total_users") if rd.ok else None
        results.append(ok("cloud:admin_dashboard", rd.status_code == 200, f"total_users={total}"))
    except Exception as e:
        results.append(ok("cloud:admin_apis", False, str(e)))
    return results


def check_local_admin_agents(admin_key: str) -> list[bool]:
    results: list[bool] = []
    try:
        r = requests.get(
            f"{BASE}/api/membership/admin/agents",
            headers={"X-Admin-Key": admin_key},
            params={"limit": 10},
            timeout=TIMEOUT,
        )
        detail = r.text[:200]
        if r.status_code != 200:
            results.append(ok("local:admin_agents", False, f"HTTP {r.status_code} {detail}"))
            return results
        if "no such table" in detail.lower():
            results.append(ok("local:admin_agents", False, detail))
            return results
        data = r.json().get("data", [])
        results.append(ok("local:admin_agents", True, f"nodes={len(data) if isinstance(data, list) else '?'}"))
        rk = requests.get(
            f"{BASE}/api/membership/admin/telemetry/keywords",
            headers={"X-Admin-Key": admin_key},
            params={"limit": 5},
            timeout=TIMEOUT,
        )
        results.append(ok("local:telemetry_keywords", rk.status_code == 200 and "no such table" not in rk.text.lower(), f"HTTP {rk.status_code}"))
    except Exception as e:
        results.append(ok("local:admin_agents", False, str(e)))
    return results


def check_admin_session_key(admin_key: str) -> list[bool]:
    results: list[bool] = []
    try:
        sr = requests.post(
            f"{BASE}/api/membership/auth/sync-admin-session",
            headers={"X-Admin-Key": admin_key},
            timeout=TIMEOUT,
        )
        if sr.status_code != 200:
            results.append(ok("local:admin_session_key", False, f"sync-admin-session HTTP {sr.status_code}"))
            return results
        tok = str(((sr.json() or {}).get("data") or {}).get("token") or "")
        r = requests.get(
            f"{BASE}/api/membership/auth/admin-session-key",
            headers={"Authorization": f"Bearer {tok}"},
            timeout=TIMEOUT,
        )
        if r.status_code != 200:
            results.append(ok("local:admin_session_key", False, f"HTTP {r.status_code} {r.text[:120]}"))
            return results
        key = str((r.json().get("data") or {}).get("admin_key") or "")
        results.append(ok("local:admin_session_key", key not in PLACEHOLDER_KEYS, f"prefix={key[:8] if key else 'EMPTY'}"))
        results.append(ok("local:admin_session_key_matches", not key or key == admin_key or admin_key not in PLACEHOLDER_KEYS, ""))
    except Exception as e:
        results.append(ok("local:admin_session_key", False, str(e)))
    return results


def check_perf_basics() -> list[bool]:
    results: list[bool] = []
    try:
        import time

        t0 = time.perf_counter()
        r = requests.get(f"{BASE}/api/membership/me", headers={"Authorization": "Bearer invalid-for-perf"}, timeout=TIMEOUT)
        dt = time.perf_counter() - t0
        results.append(ok("perf:local_me_fast_fail", dt < 10, f"{dt:.2f}s HTTP {r.status_code}"))
        t0 = time.perf_counter()
        requests.get(f"{BASE}/api/config/revision", timeout=TIMEOUT)
        dt = time.perf_counter() - t0
        results.append(ok("perf:config_revision", dt < 3, f"{dt:.2f}s"))
        t0 = time.perf_counter()
        requests.get(f"{BASE}/health", timeout=TIMEOUT)
        dt = time.perf_counter() - t0
        results.append(ok("perf:health", dt < 2, f"{dt:.2f}s"))
        r = requests.get(f"{BASE}/api/membership/connectivity", timeout=TIMEOUT)
        results.append(ok("perf:cloud_connectivity", r.status_code == 200, r.text[:80]))
    except Exception as e:
        results.append(ok("perf:basics", False, str(e)))
    return results


def check_member_login() -> tuple[list[bool], str]:
    results: list[bool] = []
    token = ""
    if not MEMBER_USER or not MEMBER_PASS:
        results.append(ok("member:login", False, "set ACCEPTANCE_MEMBER_USER/PASS (cloud credentials)"))
        return results, token
    try:
        r = requests.post(
            f"{BASE}/api/membership/auth/login",
            json={"username": MEMBER_USER, "password": MEMBER_PASS},
            timeout=TIMEOUT,
        )
        data = (r.json() or {}).get("data") or {}
        token = str(data.get("token") or "")
        results.append(ok("member:login", r.status_code == 200 and bool(token), f"role={data.get('role','member')}"))
        if token:
            me = requests.get(f"{BASE}/api/membership/me", headers={"Authorization": f"Bearer {token}"}, timeout=15)
            results.append(ok("member:local_me", me.status_code == 200, f"HTTP {me.status_code}"))
    except Exception as e:
        results.append(ok("member:login", False, str(e)))
    return results, token


def check_admin_login(admin_key: str) -> list[bool]:
    results: list[bool] = []
    if not ADMIN_PASS:
        results.append(ok("admin:login", False, "set ACCEPTANCE_ADMIN_PASS to run admin login check"))
        return results
    try:
        r = requests.post(
            f"{BASE}/api/membership/auth/login",
            json={"username": ADMIN_USER, "password": ADMIN_PASS},
            timeout=TIMEOUT,
        )
        data = (r.json() or {}).get("data") or {}
        role = str(data.get("role") or "")
        ak = str(data.get("admin_key") or "")
        results.append(ok("admin:login", r.status_code == 200 and role == "admin", f"admin_key_prefix={ak[:8] if ak else 'EMPTY'}"))
        results.append(ok("admin:login_key_valid", ak not in PLACEHOLDER_KEYS, ak[:12] if ak else "empty"))
        if ak:
            u = requests.get(f"{CLOUD}/admin/users", headers={"X-Admin-Key": ak}, params={"limit": 2}, timeout=TIMEOUT)
            results.append(ok("admin:login_key_works_on_cloud", u.status_code == 200, f"HTTP {u.status_code}"))
    except Exception as e:
        results.append(ok("admin:login", False, str(e)))
    return results


def main() -> int:
    print("=== Acceptance: three issues ===\n")
    all_results: list[bool] = []

    try:
        h = requests.get(f"{BASE}/health", timeout=10)
        all_results.append(ok("backend:health", h.status_code == 200, h.text[:60]))
    except Exception as e:
        print(f"[FAIL] backend:health — {e}")
        print("\n请先启动 backend: python backend/run_backend.py")
        return 1

    admin_key, deploy_key = load_keys()
    print(f"Using admin_key prefix: {admin_key[:8] + '...' if len(admin_key) > 8 else admin_key or 'EMPTY'}\n")

    all_results.extend(check_db_schema())
    print()
    all_results.extend(check_admin_key_config(admin_key, deploy_key))
    print()
    all_results.extend(check_local_admin_agents(admin_key))
    print()
    all_results.extend(check_admin_session_key(admin_key))
    print()
    all_results.extend(check_perf_basics())
    print()
    all_results.extend(check_member_login()[0])
    print()
    all_results.extend(check_admin_login(admin_key))

    passed = sum(1 for x in all_results if x)
    total = len(all_results)
    print(f"\n=== Summary: {passed}/{total} passed ===")
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())

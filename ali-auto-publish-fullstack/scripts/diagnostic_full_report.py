# -*- coding: utf-8 -*-
"""Full project diagnostic: login, points, admin/member, industry, perf, local."""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
BASE = os.getenv("ACCEPTANCE_BACKEND", "http://127.0.0.1:8000")
MEMBER_USER = (os.getenv("ACCEPTANCE_MEMBER_USER") or "321654").strip()
MEMBER_PASS = (os.getenv("ACCEPTANCE_MEMBER_PASS") or "Aa3456").strip()
ADMIN_USER = (os.getenv("ACCEPTANCE_ADMIN_USER") or "admin11").strip()
ADMIN_PASS = (os.getenv("ACCEPTANCE_ADMIN_PASS") or "yingshengchongadmin").strip()
TIMEOUT = int(os.getenv("ACCEPTANCE_TIMEOUT", "60"))
SLOW_MS = int(os.getenv("DIAG_SLOW_MS", "3000"))
PLACEHOLDER_KEYS = frozenset({"", "change-me-admin", "change-me"})


def ok(area: str, name: str, passed: bool, detail: str = "") -> bool:
    mark = "PASS" if passed else "FAIL"
    line = f"[{mark}] [{area}] {name}"
    if detail:
        line += f" — {detail}"
    print(line)
    return passed


def load_admin_key() -> str:
    key = os.getenv("ACCEPTANCE_ADMIN_KEY", "").strip()
    if key and key not in PLACEHOLDER_KEYS:
        return key
    for p in (
        ROOT / "data" / "config.json",
        Path(os.environ.get("APPDATA", "")) / "AliAutoPublish" / "data" / "config.json",
    ):
        try:
            if p.is_file():
                k = str(
                    (json.loads(p.read_text(encoding="utf-8-sig")).get("payment") or {}).get("admin_api_key") or ""
                ).strip()
                if k and k not in PLACEHOLDER_KEYS:
                    return k
        except Exception:
            pass
    return ""


def timed_get(session: requests.Session, path: str) -> tuple[int, float]:
    t0 = time.perf_counter()
    try:
        r = session.get(f"{BASE}{path}", timeout=TIMEOUT)
        return r.status_code, (time.perf_counter() - t0) * 1000
    except Exception:
        return 0, (time.perf_counter() - t0) * 1000


def login(username: str, password: str) -> tuple[requests.Session, dict]:
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    r = s.post(
        f"{BASE}/api/membership/auth/login",
        json={"username": username, "password": password},
        timeout=TIMEOUT,
    )
    data = (r.json() or {}).get("data") or {}
    tok = data.get("token") or ""
    if tok:
        s.headers["Authorization"] = f"Bearer {tok}"
    ak = data.get("admin_key") or ""
    if ak:
        s.headers["X-Admin-Key"] = ak
    return s, data


def main() -> int:
    results: list[bool] = []
    admin_key = load_admin_key()

    print("=" * 60)
    print("FULL PROJECT DIAGNOSTIC")
    print("=" * 60)

    print("\n## 8 Local service")
    try:
        t0 = time.perf_counter()
        r = requests.get(f"{BASE}/api/health", timeout=15)
        ms = (time.perf_counter() - t0) * 1000
        results.append(ok("local", "backend_health", r.ok, f"{ms:.0f}ms"))
    except Exception as e:
        results.append(ok("local", "backend_health", False, str(e)))
        return 1

    results.append(ok("local", "project_db", (ROOT / "data" / "membership.db").is_file(), "data/membership.db"))
    app_data = Path(os.environ.get("APPDATA", "")) / "AliAutoPublish" / "data"
    results.append(ok("local", "appdata_dir", app_data.is_dir(), str(app_data)))

    print("\n## 2 Login")
    member_sess, member_data = login(MEMBER_USER, MEMBER_PASS)
    results.append(
        ok("login", "member", bool(member_data.get("token")), f"role={member_data.get('role')}")
    )
    admin_sess, admin_data = login(ADMIN_USER, ADMIN_PASS)
    is_admin = bool(admin_data.get("token")) and admin_data.get("role") == "admin"
    results.append(ok("login", "admin", is_admin, f"role={admin_data.get('role')}"))
    if admin_key and "X-Admin-Key" not in admin_sess.headers:
        admin_sess.headers["X-Admin-Key"] = admin_key

    print("\n## 3 Points")
    me_r = member_sess.get(f"{BASE}/api/membership/me", timeout=TIMEOUT)
    me = (me_r.json() or {}).get("data") or {}
    bal_before = float(me.get("points_balance") or 0)
    results.append(ok("points", "balance", me_r.status_code == 200, f"{bal_before:.4f}"))
    cr = member_sess.post(
        f"{BASE}/api/membership/points/consume",
        json={"amount": 0.0001, "reason": "diagnostic", "ref_type": "diagnostic"},
        timeout=TIMEOUT,
    )
    results.append(ok("points", "consume", cr.status_code == 200, f"HTTP {cr.status_code}"))
    me_r2 = member_sess.get(f"{BASE}/api/membership/me", timeout=TIMEOUT)
    bal_after = float(((me_r2.json() or {}).get("data") or {}).get("points_balance") or 0)
    if cr.status_code == 200:
        results.append(ok("points", "balance_delta", bal_after < bal_before, f"{bal_before:.4f}->{bal_after:.4f}"))
    lr = member_sess.get(f"{BASE}/api/membership/ledger", params={"page": 1, "page_size": 5}, timeout=TIMEOUT)
    results.append(ok("points", "ledger", lr.status_code == 200, f"HTTP {lr.status_code}"))

    print("\n## 4 Admin panel")
    for path, name in [
        ("/api/membership/admin/agents", "agents"),
        ("/api/membership/admin/telemetry/keywords", "keywords"),
        ("/api/membership/admin/users", "users"),
        ("/api/membership/admin/dashboard", "dashboard"),
        ("/api/membership/admin/withdraw/list", "withdraws"),
        ("/api/config/admin-runtime", "runtime"),
        ("/api/analysis/status/traffic_ai", "traffic_ai"),
        ("/api/analysis/status/title_optimize", "title_opt"),
        ("/api/images/ai-gen/config", "ai_gen"),
    ]:
        code, ms = timed_get(admin_sess, path)
        results.append(ok("admin", name, code in (200, 400), f"HTTP {code} {ms:.0f}ms"))

    print("\n## 5 Member + config mask")
    cfg_r = member_sess.get(f"{BASE}/api/config/", timeout=TIMEOUT)
    cfg = (cfg_r.json() or {}).get("data") or {}
    da_key = str((cfg.get("data_analysis") or {}).get("doubao_api_key") or "")
    gem_key = str((cfg.get("ai_image_gen") or {}).get("gemini_api_key") or "")
    results.append(ok("member", "config", cfg_r.status_code == 200, ""))
    results.append(ok("member", "doubao_masked", da_key in ("", "***") or da_key.startswith("***"), da_key[:8]))
    results.append(ok("member", "gemini_masked", gem_key in ("", "***") or gem_key.startswith("***"), gem_key[:8]))
    for ep, label in [
        ("/api/analysis/traffic-ai/points-estimate", "traffic_est"),
        ("/api/analysis/title-optimize/points-estimate", "title_est"),
        ("/api/images/ai-gen/points-estimate", "ai_est"),
    ]:
        code, ms = timed_get(member_sess, ep)
        results.append(ok("member", label, code == 200, f"HTTP {code} {ms:.0f}ms"))

    print("\n## 6 Industry / store")
    for path in [
        "/api/data/download/status/industry_keyword",
        "/api/data/industry-keyword/latest",
        "/api/data/industry-keyword/dropdown/latest",
        "/api/data/industry-keyword/title/generate/status",
        "/api/data/download/status/store_image",
        "/api/data/store/overview/latest",
    ]:
        code, ms = timed_get(member_sess, path)
        results.append(ok("industry", path.rsplit("/", 1)[-1], code in (200, 404), f"HTTP {code} {ms:.0f}ms"))

    print("\n## 1 Feature isolation")
    statuses = {}
    for label, path in [
        ("upload", "/api/upload/status"),
        ("optimize", "/api/upload/optimize/status"),
        ("video", "/api/video-bind/status"),
        ("analysis", "/api/analysis/status/comprehensive"),
        ("download", "/api/data/download/status"),
        ("images", "/api/images/normalize/status"),
        ("ai_gen", "/api/images/ai-gen/status"),
    ]:
        code, ms = timed_get(member_sess, path)
        statuses[label] = code
        results.append(ok("isolation", label, code == 200, f"HTTP {code} {ms:.0f}ms"))
    results.append(ok("isolation", "no_500", all(c != 500 for c in statuses.values()), str(statuses)))

    print("\n## 7 Response times")
    slow = 0
    for page, path in [
        ("dashboard", "/api/config/"),
        ("dashboard", "/api/config/section/data_download"),
        ("membership", "/api/membership/me"),
        ("membership", "/api/membership/ledger"),
        ("analysis", "/api/analysis/overview"),
        ("analysis", "/api/analysis/diagnosis/table"),
        ("download", "/api/data/download/status"),
        ("industry", "/api/data/industry-keyword/latest"),
        ("traffic", "/api/analysis/traffic-ai/result"),
        ("title", "/api/analysis/title-optimize/results"),
        ("ai_gen", "/api/images/ai-gen/status"),
        ("config", "/api/config/template"),
        ("cloud", "/api/config/cloud-admin-revision"),
    ]:
        code, ms = timed_get(member_sess, path)
        if ms > SLOW_MS:
            slow += 1
        tag = "SLOW" if ms > SLOW_MS else "OK"
        results.append(ok("perf", f"{page}{path}", code in (200, 400, 404), f"{ms:.0f}ms [{tag}]"))
    results.append(ok("perf", "slow_count", slow <= 3, f"{slow}>{SLOW_MS}ms"))

    passed = sum(results)
    total = len(results)
    print(f"\nSUMMARY: {passed}/{total}")
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())

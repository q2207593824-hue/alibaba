# -*- coding: utf-8 -*-
"""Console dashboard buttons acceptance (API + source order, no full browser pipelines)."""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = ROOT / "frontend" / "client" / "src" / "pages" / "Dashboard.tsx"
BASE = os.getenv("ACCEPTANCE_BACKEND", "http://127.0.0.1:8000")
MEMBER_USER = (os.getenv("ACCEPTANCE_MEMBER_USER") or "321654").strip()
MEMBER_PASS = (os.getenv("ACCEPTANCE_MEMBER_PASS") or "Aa3456").strip()
TIMEOUT = int(os.getenv("ACCEPTANCE_TIMEOUT", "60"))

EXPECTED_DOWNLOAD = [
    "store_overview",
    "traffic_channel",
    "product_operate",
    "keyword_crawler",
    "daily_data",
    "product360",
]
EXPECTED_ANALYZE = [
    "comprehensive",
    "single_analysis",
    "traffic_ai",
    "title_optimize",
]
EXPECTED_PUBLISH_APIS = [
    ("POST", "/api/upload/start", "upload"),
    ("POST", "/api/upload/optimize/start", "optimize"),
    ("POST", "/api/video-bind/start", "video_bind"),
]
EXPECTED_IMAGE_APIS = [
    ("POST", "/api/images/normalize/start", "normalize_start"),
    ("POST", "/api/images/normalize/stop", "normalize_stop"),
    ("POST", "/api/images/ai-gen/start", "ai_gen_start"),
    ("POST", "/api/images/ai-gen/stop", "ai_gen_stop"),
]


def ok(name: str, passed: bool, detail: str = "") -> bool:
    mark = "PASS" if passed else "FAIL"
    line = f"[{mark}] {name}"
    if detail:
        line += f" — {detail}"
    print(line)
    return passed


def login() -> requests.Session:
    s = requests.Session()
    s.headers["Content-Type"] = "application/json"
    r = s.post(
        f"{BASE}/api/membership/auth/login",
        json={"username": MEMBER_USER, "password": MEMBER_PASS},
        timeout=TIMEOUT,
    )
    r.raise_for_status()
    tok = (r.json().get("data") or {}).get("token") or ""
    s.headers["Authorization"] = f"Bearer {tok}"
    return s


def extract_download_order(src: str) -> list[str]:
    block = re.search(r"const handleAutoDownload = async \(\) => \{.*?\n  \};", src, re.S)
    if not block:
        return []
    return re.findall(r'task_type:\s*"([^"]+)"', block.group(0))


def extract_analyze_order(src: str) -> list[str]:
    block = re.search(r"const handleAutoAnalyze = async \(\) => \{.*?\n  \};", src, re.S)
    if not block:
        return []
    return re.findall(r'task_type:\s*"([^"]+)"', block.group(0))


def extract_stop_download_order(src: str) -> list[str]:
    block = re.search(r"activeJob === \"download\".*?\]\)", src, re.S)
    if not block:
        return []
    return re.findall(r'stopDownload\("([^"]+)"\)', block.group(0))


def test_source() -> list[bool]:
    results: list[bool] = []
    src = DASHBOARD.read_text(encoding="utf-8")
    results.append(ok("source:file_exists", DASHBOARD.is_file(), str(DASHBOARD)))

    dl = extract_download_order(src)
    results.append(ok("source:download_order", dl == EXPECTED_DOWNLOAD, f"got={dl}"))

    an = extract_analyze_order(src)
    results.append(ok("source:analyze_order", an == EXPECTED_ANALYZE, f"got={an}"))

    stop_dl = extract_stop_download_order(src)
    results.append(ok("source:download_stop_order", stop_dl == EXPECTED_DOWNLOAD, f"got={stop_dl}"))

    results.append(ok("source:image_dialog", "选择图片任务" in src and "imageJobDialogOpen" in src, ""))
    results.append(ok("source:image_modes", "normalize" in src and "ai_gen" in src and "startImageJob" in src, ""))
    results.append(
        ok(
            "source:publish_chain",
            all(x in src for x in ("uploadApi.start", "uploadApi.startOptimize", "videoBindApi.start")),
            "",
        )
    )
    results.append(ok("source:no_keyword_parser_in_analyze", "keyword_parser" not in extract_analyze_order(src), ""))
    return results


def test_status_endpoints(s: requests.Session) -> list[bool]:
    results: list[bool] = []
    checks = [
        ("GET", "/api/upload/status", "publish_status"),
        ("GET", "/api/upload/optimize/status", "optimize_status"),
        ("GET", "/api/video-bind/status", "video_bind_status"),
        ("GET", "/api/images/normalize/status", "normalize_status"),
        ("GET", "/api/images/ai-gen/status", "ai_gen_status"),
    ]
    for method, path, name in checks:
        try:
            r = s.request(method, f"{BASE}{path}", timeout=TIMEOUT)
            results.append(ok(f"status:{name}", r.status_code == 200, f"HTTP {r.status_code}"))
        except Exception as e:
            results.append(ok(f"status:{name}", False, str(e)[:80]))
    for task in EXPECTED_DOWNLOAD:
        try:
            r = s.get(f"{BASE}/api/data/download/status/{task}", timeout=TIMEOUT)
            results.append(ok(f"status:download:{task}", r.status_code == 200, f"HTTP {r.status_code}"))
        except Exception as e:
            results.append(ok(f"status:download:{task}", False, str(e)[:80]))
    for task in EXPECTED_ANALYZE:
        try:
            r = s.get(f"{BASE}/api/analysis/status/{task}", timeout=TIMEOUT)
            results.append(ok(f"status:analyze:{task}", r.status_code == 200, f"HTTP {r.status_code}"))
        except Exception as e:
            results.append(ok(f"status:analyze:{task}", False, str(e)[:80]))
    return results


def test_stop_idle(s: requests.Session) -> list[bool]:
    results: list[bool] = []
    stops = [
        ("POST", "/api/upload/stop", "upload"),
        ("POST", "/api/upload/optimize/stop", "optimize"),
        ("POST", "/api/video-bind/stop", "video_bind"),
        ("POST", "/api/images/normalize/stop", "normalize"),
        ("POST", "/api/images/ai-gen/stop", "ai_gen"),
    ]
    for method, path, name in stops:
        try:
            r = s.request(method, f"{BASE}{path}", json={}, timeout=TIMEOUT)
            results.append(ok(f"stop_idle:{name}", r.status_code in (200, 400), f"HTTP {r.status_code}"))
        except Exception as e:
            results.append(ok(f"stop_idle:{name}", False, str(e)[:80]))
    for task in EXPECTED_DOWNLOAD:
        try:
            r = s.post(f"{BASE}/api/data/download/stop/{task}", json={}, timeout=TIMEOUT)
            results.append(ok(f"stop_idle:download:{task}", r.status_code in (200, 400), f"HTTP {r.status_code}"))
        except Exception as e:
            results.append(ok(f"stop_idle:download:{task}", False, str(e)[:80]))
    for task in EXPECTED_ANALYZE:
        try:
            r = s.post(f"{BASE}/api/analysis/stop/{task}", json={}, timeout=TIMEOUT)
            results.append(ok(f"stop_idle:analyze:{task}", r.status_code in (200, 400), f"HTTP {r.status_code}"))
        except Exception as e:
            results.append(ok(f"stop_idle:analyze:{task}", False, str(e)[:80]))
    return results


def test_image_start_stop_roundtrip(s: requests.Session) -> list[bool]:
    """Lightweight: start then stop image jobs (does not wait for completion)."""
    results: list[bool] = []
    for label, start_path, stop_path in (
        ("normalize", "/api/images/normalize/start", "/api/images/normalize/stop"),
        ("ai_gen", "/api/images/ai-gen/start", "/api/images/ai-gen/stop"),
    ):
        try:
            sr = s.post(f"{BASE}{start_path}", json={}, timeout=TIMEOUT)
            start_ok = sr.status_code in (200, 409)
            results.append(ok(f"roundtrip:{label}:start", start_ok, f"HTTP {sr.status_code}"))
            tr = s.post(f"{BASE}{stop_path}", json={}, timeout=TIMEOUT)
            results.append(ok(f"roundtrip:{label}:stop", tr.status_code in (200, 400), f"HTTP {tr.status_code}"))
        except Exception as e:
            results.append(ok(f"roundtrip:{label}", False, str(e)[:100]))
    return results


def test_upload_start_stop_roundtrip(s: requests.Session) -> list[bool]:
    """Lightweight: start then stop publish / optimize / video-bind (no wait for Selenium)."""
    results: list[bool] = []
    jobs = (
        ("upload", "/api/upload/start", "/api/upload/stop", {"mode": "batch", "max_products": 1}),
        ("optimize", "/api/upload/optimize/start", "/api/upload/optimize/stop", {}),
        ("video_bind", "/api/video-bind/start", "/api/video-bind/stop", {}),
    )
    for label, start_path, stop_path, body in jobs:
        try:
            sr = s.post(f"{BASE}{start_path}", json=body, timeout=TIMEOUT)
            start_ok = sr.status_code in (200, 409)
            results.append(ok(f"roundtrip:{label}:start", start_ok, f"HTTP {sr.status_code}"))
            tr = s.post(f"{BASE}{stop_path}", json={}, timeout=TIMEOUT)
            results.append(ok(f"roundtrip:{label}:stop", tr.status_code in (200, 400), f"HTTP {tr.status_code}"))
        except Exception as e:
            results.append(ok(f"roundtrip:{label}", False, str(e)[:100]))
    return results


def test_config_for_download(s: requests.Session) -> list[bool]:
    results: list[bool] = []
    try:
        r = s.get(f"{BASE}/api/config/section/store_overview", timeout=TIMEOUT)
        data = (r.json() or {}).get("data") or {}
        period = data.get("period_type") or "week"
        results.append(ok("download:store_overview_config", r.status_code == 200, f"period_type={period}"))
    except Exception as e:
        results.append(ok("download:store_overview_config", False, str(e)[:80]))
    return results


def main() -> int:
    print("=== Dashboard console buttons acceptance ===\n")
    results: list[bool] = []

    print("--- Source / UI wiring ---")
    results.extend(test_source())

    try:
        r = requests.get(f"{BASE}/api/health", timeout=15)
        results.append(ok("backend:health", r.ok, r.text[:60]))
    except Exception as e:
        results.append(ok("backend:health", False, str(e)))
        print(f"\nSUMMARY: backend down — {sum(results)}/{len(results)} pre-checks")
        return 1

    try:
        sess = login()
        results.append(ok("auth:member_login", True, MEMBER_USER))
    except Exception as e:
        results.append(ok("auth:member_login", False, str(e)[:100]))
        passed = sum(results)
        print(f"\nSUMMARY: {passed}/{len(results)} passed")
        return 1

    print("\n--- Status endpoints (buttons poll these) ---")
    results.extend(test_status_endpoints(sess))

    print("\n--- Stop endpoints (idle) ---")
    results.extend(test_stop_idle(sess))

    print("\n--- Download config prerequisite ---")
    results.extend(test_config_for_download(sess))

    print("\n--- Image job start/stop roundtrip ---")
    results.extend(test_image_start_stop_roundtrip(sess))

    print("\n--- Upload / optimize / video-bind start/stop roundtrip ---")
    results.extend(test_upload_start_stop_roundtrip(sess))

    passed = sum(results)
    total = len(results)
    print(f"\n=== Summary: {passed}/{total} passed ===")
    if passed < total:
        print("Note: Full download/analyze/publish pipelines need manual UI test with browser/Cookie.")
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())

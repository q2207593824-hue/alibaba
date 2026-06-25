# -*- coding: utf-8 -*-
"""Acceptance: masked doubao key fix + member cloud pull."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

BASE = os.getenv("ACCEPTANCE_BACKEND", "http://127.0.0.1:8000")
MEMBER_USER = (os.getenv("ACCEPTANCE_MEMBER_USER") or "321654").strip()
MEMBER_PASS = (os.getenv("ACCEPTANCE_MEMBER_PASS") or "Aa3456").strip()
ADMIN_KEY = (os.getenv("ACCEPTANCE_ADMIN_KEY") or "").strip()
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
        return ADMIN_KEY
    deploy = ROOT / "frontend" / "electron" / "desktop.deploy.json"
    if deploy.is_file():
        try:
            return str(json.loads(deploy.read_text(encoding="utf-8-sig")).get("admin_api_key") or "").strip()
        except Exception:
            pass
    return ""


def test_merge_rejects_masked() -> list[bool]:
    results: list[bool] = []
    try:
        from app.core.admin_runtime_config import (
            is_masked_secret,
            merge_runtime_secrets_on_save,
            purge_masked_runtime_secrets_from_local,
        )
        from app.core.settings import config_manager, get_config

        cfg = get_config()
        real = str(getattr(cfg.data_analysis, "doubao_api_key", "") or "").strip()
        if not real or is_masked_secret(real):
            real = "sk-test-real-key-for-acceptance-only"

        data = cfg.model_dump()
        data["data_analysis"] = {**data.get("data_analysis", {}), "doubao_api_key": real}
        config_manager.update_full(data)

        merged = merge_runtime_secrets_on_save(
            {"data_analysis": {"doubao_api_key": "***", "doubao_model_name": "m1"}},
            section="data_analysis",
        )
        kept = str((merged.get("data_analysis") or {}).get("doubao_api_key") or "")
        results.append(ok("merge:reject_star_mask", kept == real, f"got={kept[:8]}"))

        config_manager.update_full(
            {
                **cfg.model_dump(),
                "data_analysis": {**cfg.data_analysis.model_dump(), "doubao_api_key": "***"},
            }
        )
        purge_masked_runtime_secrets_from_local()
        after = str(getattr(config_manager.reload_from_disk().data_analysis, "doubao_api_key", "") or "")
        results.append(ok("purge:clears_mask", after == "", f"after={after!r}"))
    except Exception as e:
        results.append(ok("merge:local", False, str(e)[:120]))
    return results


def test_member_pull_and_start_gate() -> list[bool]:
    results: list[bool] = []
    admin_key = load_admin_key()
    try:
        lr = requests.post(
            f"{BASE}/api/membership/auth/login",
            json={"username": MEMBER_USER, "password": MEMBER_PASS},
            timeout=TIMEOUT,
        )
        tok = str(((lr.json() or {}).get("data") or {}).get("token") or "")
        s = requests.Session()
        s.headers.update({"Authorization": f"Bearer {tok}", "Content-Type": "application/json"})
        if admin_key:
            s.headers["X-Admin-Key"] = admin_key

        pr = s.post(f"{BASE}/api/config/pull-cloud-admin-runtime", timeout=TIMEOUT)
        pdata = (pr.json() or {}).get("data") or {}
        results.append(ok("http:pull", pr.status_code == 200, f"HTTP {pr.status_code}"))
        results.append(
            ok(
                "http:secrets_ready",
                pdata.get("secrets_ready") is True,
                f"secrets_ready={pdata.get('secrets_ready')}",
            )
        )

        ar = s.post(
            f"{BASE}/api/analysis/start",
            json={"task_type": "title_optimize", "source_file": "__nonexistent_acceptance__"},
            timeout=TIMEOUT,
        )
        detail = str((ar.json() or {}).get("detail") or "")
        key_blocked = ar.status_code == 400 and "API Key" in detail
        results.append(
            ok(
                "http:analysis_not_blocked_by_key",
                not key_blocked,
                f"HTTP {ar.status_code} {detail[:80]}",
            )
        )

        ir = s.post(f"{BASE}/api/images/ai-gen/start", json={}, timeout=TIMEOUT)
        idetail = str((ir.json() or {}).get("detail") or "")
        ikey_blocked = ir.status_code == 400 and "API Key" in idetail
        results.append(
            ok(
                "http:ai_gen_not_blocked_by_key",
                not ikey_blocked,
                f"HTTP {ir.status_code} {idetail[:80]}",
            )
        )
    except Exception as e:
        results.append(ok("http:member_flow", False, str(e)[:120]))
    return results


def main() -> int:
    print("=== Runtime secrets fix acceptance ===\n")
    results: list[bool] = []
    results.extend(test_merge_rejects_masked())
    print()
    results.extend(test_member_pull_and_start_gate())
    passed = sum(results)
    total = len(results)
    print(f"\n=== Summary: {passed}/{total} passed ===")
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())

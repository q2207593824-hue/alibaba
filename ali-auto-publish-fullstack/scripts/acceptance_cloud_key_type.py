# -*- coding: utf-8 -*-
"""Acceptance: cloud runtime-config API key type (no full plaintext)."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

ADMIN_KEY = (os.getenv("ACCEPTANCE_ADMIN_KEY") or os.getenv("ALI_ADMIN_API_KEY") or "").strip()
MEMBER_USER = (os.getenv("ACCEPTANCE_MEMBER_USER") or "321654").strip()
MEMBER_PASS = (os.getenv("ACCEPTANCE_MEMBER_PASS") or "Aa3456").strip()


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


def classify_key(raw: str) -> dict:
    from app.core.admin_runtime_config import is_masked_secret

    s = str(raw or "").strip()
    if not s:
        return {"type": "empty", "len": 0, "preview": "(empty)"}
    if s == "***" or s.startswith("***"):
        return {"type": "mask_literal", "len": len(s), "preview": s}
    if is_masked_secret(s):
        prev = s[:4] + "..." + s[-4:] if len(s) > 8 else s
        return {"type": "mask_partial", "len": len(s), "preview": prev}
    prev = s[:6] + "..." + s[-4:] if len(s) > 12 else "len=" + str(len(s))
    return {"type": "real_full", "len": len(s), "preview": prev}


def describe_channel(name: str, data: dict) -> tuple[bool, str]:
    from app.services.admin_runtime_cloud_sync import _cloud_doubao_key_status

    da = data.get("data_analysis") if isinstance(data.get("data_analysis"), dict) else {}
    ai = data.get("ai_image_gen") if isinstance(data.get("ai_image_gen"), dict) else {}
    doubao = classify_key(str(da.get("doubao_api_key") or ""))
    gemini = classify_key(str(ai.get("gemini_api_key") or ""))
    status = _cloud_doubao_key_status(data)

    print(f"\n--- {name} ---")
    rev = data.get("revision")
    print(f"  revision: {rev}")
    print("  doubao_api_key:", json.dumps(doubao, ensure_ascii=False))
    print(f"  cloud_key_status: {status}")
    print("  gemini_api_key:", json.dumps(gemini, ensure_ascii=False))
    model = da.get("doubao_model_name", "")
    print(f"  doubao_model: {model}")

    return status == "ok", status


def main() -> int:
    from app.services.admin_runtime_cloud_sync import (
        _fetch_cloud_runtime_payload,
        apply_cloud_payload_to_local,
        ensure_runtime_secrets_ready_detail,
    )
    from app.core.admin_runtime_config import purge_masked_runtime_secrets_from_local, resolve_runtime_secret
    from app.services.membership_service import CLOUD_MEMBERSHIP_API_BASE, _cloud_http_request

    admin_key = load_admin_key()
    results: list[bool] = []

    print("=== Cloud API Key type acceptance ===\n")
    print("cloud_base:", CLOUD_MEMBERSHIP_API_BASE)
    prefix = (admin_key[:8] + "...") if admin_key else "EMPTY"
    print("admin_key_prefix:", prefix)

    try:
        data = _fetch_cloud_runtime_payload(admin_key=admin_key)
        usable, status = describe_channel("channel:admin_key (desktop.deploy)", data)
        dkey = str((data.get("data_analysis") or {}).get("doubao_api_key") or "")
        results.append(ok("cloud:admin_key_fetch", True, "status=" + status))
        results.append(ok("cloud:admin_key_usable", usable, "type=" + classify_key(dkey)["type"]))
    except Exception as e:
        results.append(ok("cloud:admin_key_fetch", False, str(e)[:120]))

    try:
        r = _cloud_http_request(
            "POST",
            CLOUD_MEMBERSHIP_API_BASE + "/auth/login",
            json={"username": MEMBER_USER, "password": MEMBER_PASS},
            timeout=(8, 45),
        )
        tok = str(((r.json() or {}).get("data") or {}).get("token") or "")
        results.append(ok("cloud:member_login", r.ok and bool(tok), "HTTP " + str(r.status_code) + " token_len=" + str(len(tok))))
        if tok:
            data_m = _fetch_cloud_runtime_payload(bearer=tok, admin_key="")
            usable_m, status_m = describe_channel("channel:member_bearer + desktop_sync", data_m)
            mkey = str((data_m.get("data_analysis") or {}).get("doubao_api_key") or "")
            results.append(ok("cloud:member_sync_fetch", True, "status=" + status_m))
            results.append(ok("cloud:member_sync_usable", usable_m, "type=" + classify_key(mkey)["type"]))
    except Exception as e:
        results.append(ok("cloud:member_channel", False, str(e)[:120]))

    try:
        purge_masked_runtime_secrets_from_local()
        data = _fetch_cloud_runtime_payload(admin_key=admin_key)
        apply_cloud_payload_to_local(data)
        local = resolve_runtime_secret("data_analysis", "doubao_api_key")
        ready, reason = ensure_runtime_secrets_ready_detail(skip_pull=True)
        local_info = classify_key(local)
        print("\n--- local after cloud apply ---")
        print("  resolve_runtime_secret:", json.dumps(local_info, ensure_ascii=False))
        print("  secrets_ready:", ready, "reason=" + reason)
        results.append(ok("local:resolve_after_apply", local_info["type"] == "real_full", local_info["type"]))
        results.append(ok("local:secrets_ready", ready, reason))
    except Exception as e:
        results.append(ok("local:apply_resolve", False, str(e)[:120]))

    passed = sum(results)
    total = len(results)
    print(f"\n=== Summary: {passed}/{total} passed ===")

    if passed < total:
        print("\nKey type legend:")
        print("  empty        = cloud not configured")
        print("  mask_literal = *** placeholder")
        print("  mask_partial = sk**xx masked form")
        print("  real_full    = full key (usable by backend)")

    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())

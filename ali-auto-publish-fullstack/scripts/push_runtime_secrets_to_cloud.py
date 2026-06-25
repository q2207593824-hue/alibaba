# -*- coding: utf-8 -*-
"""Push runtime API keys to cloud. See env vars in docstring at top of main()."""
from __future__ import annotations
import json, os, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

def load_admin_key():
    key = (os.getenv("ACCEPTANCE_ADMIN_KEY") or os.getenv("ALI_ADMIN_API_KEY") or "").strip()
    if key:
        return key
    deploy = ROOT / "frontend" / "electron" / "desktop.deploy.json"
    if deploy.is_file():
        try:
            return str(json.loads(deploy.read_text(encoding="utf-8-sig")).get("admin_api_key") or "").strip()
        except Exception:
            pass
    return ""

def apply_env_keys(da, ai):
    da_key = (os.getenv("DATA_ANALYSIS_DOUBAO_API_KEY") or os.getenv("DOUBAO_API_KEY") or "").strip()
    ai_doubao = (os.getenv("AI_DOUBAO_API_KEY") or os.getenv("ARK_API_KEY") or "").strip()
    gemini = (os.getenv("GEMINI_API_KEY") or "").strip()
    if da_key:
        da["doubao_api_key"] = da_key
    if ai_doubao:
        ai["doubao_api_key"] = ai_doubao
    if gemini:
        ai["gemini_api_key"] = gemini
    return da, ai

def main():
    from app.core.admin_runtime_config import is_masked_secret
    from app.core.settings import get_config, config_manager
    from app.services.admin_runtime_cloud_sync import (
        build_push_body_from_local,
        push_remote_admin_runtime_to_cloud,
    )
    from app.services.cloud_admin_runtime_service import save_cloud_admin_runtime
    from app.services.membership_service import _is_cloud_membership_host, check_cloud_connectivity

    if os.getenv("MEMBERSHIP_IS_CLOUD_HOST", "").strip().lower() in {"1", "true", "yes"}:
        if not _is_cloud_membership_host():
            print("NOTE: MEMBERSHIP_IS_CLOUD_HOST is set but this is not the cloud server process.")
        else:
            print("Cloud host mode: will write app_runtime_settings DB directly.")

    config_manager.reload_from_disk()
    cfg = get_config()
    da = cfg.data_analysis.model_dump()
    ai = cfg.ai_image_gen.model_dump()
    da, ai = apply_env_keys(da, ai)

    doubao_da = str(da.get("doubao_api_key") or "").strip()
    doubao_ai = str(ai.get("doubao_api_key") or "").strip()
    gemini = str(ai.get("gemini_api_key") or "").strip()

    print("=== Push runtime secrets to cloud ===")
    print(f"data_analysis.doubao_api_key: len={len(doubao_da)} masked={is_masked_secret(doubao_da)}")
    print(f"ai_image_gen.doubao_api_key: len={len(doubao_ai)} masked={is_masked_secret(doubao_ai)}")
    print(f"ai_image_gen.gemini_api_key: len={len(gemini)} masked={is_masked_secret(gemini)}")

    if not doubao_da or is_masked_secret(doubao_da):
        print("ERROR: data_analysis.doubao_api_key missing or masked.")
        print("Set DATA_ANALYSIS_DOUBAO_API_KEY=... (traffic/title optimize key, NOT ai_image_gen key).")
        return 1

    data = cfg.model_dump()
    data["data_analysis"] = da
    data["ai_image_gen"] = ai
    config_manager.update_full(data)

    ai_push = {
        k: ai.get(k)
        for k in ("gemini_api_key", "doubao_api_key", "gemini_model", "doubao_model", "gemini_base_url", "doubao_base_url")
        if ai.get(k) and not is_masked_secret(ai.get(k))
    }
    saved = save_cloud_admin_runtime(
        data_analysis={"doubao_api_key": doubao_da, "doubao_model_name": da.get("doubao_model_name")},
        ai_image_gen=ai_push or None,
        merge=True,
        updated_by="push_script",
    )
    print("Local mirror updated, revision=", saved.get("revision"))

    if _is_cloud_membership_host():
        print("Cloud host DB OK (no remote HTTP needed).")
        return 0

    admin_key = load_admin_key()
    if not admin_key:
        print("WARN: No admin key - remote cloud push skipped.")
        return 0

    diag = check_cloud_connectivity()
    if diag.get("fake_dns"):
        print("WARN: fake_dns=true (Clash/VPN). Turn off system proxy then re-run this script.")
    if not diag.get("ok"):
        print("WARN: cloud health check failed:", diag.get("error", "")[:200])

    try:
        result = push_remote_admin_runtime_to_cloud(admin_key=admin_key)
        print("Remote cloud push OK:", json.dumps(result, ensure_ascii=False)[:300])
    except Exception as e:
        print("Remote cloud push FAILED:", str(e)[:300])
        print("Local config is ready. Fix network/proxy, then re-run this script (do NOT set MEMBERSHIP_IS_CLOUD_HOST on desktop).")
        return 1

    print("Done. Members re-login to pull keys.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
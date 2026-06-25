# -*- coding: utf-8 -*-
"""管理员运行时配置同步验收（会员 pull 不破坏 Key、分析前 ensure）。"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

BASE = os.getenv("ACCEPTANCE_BACKEND", "http://127.0.0.1:8000")
# 凭证仅通过环境变量注入，勿在仓库中写默认账号密码（登录以云端为准）
MEMBER_USER = (os.getenv("ACCEPTANCE_MEMBER_USER") or "").strip()
MEMBER_PASS = (os.getenv("ACCEPTANCE_MEMBER_PASS") or "").strip()
TIMEOUT = int(os.getenv("ACCEPTANCE_TIMEOUT", "45"))

os.environ.setdefault("ALI_APP_DATA_DIR", str(Path(os.environ.get("APPDATA", "")) / "AliAutoPublish" / "data"))


def ok(name: str, passed: bool, detail: str = "") -> bool:
    mark = "PASS" if passed else "FAIL"
    line = f"[{mark}] {name}"
    if detail:
        line += f" — {detail}"
    print(line)
    return passed


def main() -> int:
    results: list[bool] = []
    print("=== Admin runtime sync acceptance ===\n")

    # 1) 本地 ensure / resolve
    try:
        from app.core.admin_runtime_config import is_masked_secret, resolve_runtime_secret
        from app.services.admin_runtime_cloud_sync import ensure_runtime_secrets_ready, pull_cloud_admin_runtime_to_local

        results.append(ok("local:ensure_secrets", ensure_runtime_secrets_ready()))
        key = resolve_runtime_secret("data_analysis", "doubao_api_key")
        results.append(ok("local:resolve_doubao_key", bool(key) and not is_masked_secret(key), f"len={len(key)}"))
    except Exception as e:
        results.append(ok("local:ensure_secrets", False, str(e)[:100]))

    # 2) 会员 HTTP pull 不破坏 Key
    cfg_path = Path(os.environ["ALI_APP_DATA_DIR"]) / "config.json"
    before = ""
    if cfg_path.is_file():
        before = str((json.loads(cfg_path.read_text(encoding="utf-8-sig")).get("data_analysis") or {}).get("doubao_api_key") or "")

    try:
        r = requests.post(
            f"{BASE}/api/membership/auth/login",
            json={"username": MEMBER_USER, "password": MEMBER_PASS},
            timeout=TIMEOUT,
        )
        tok = str(((r.json() or {}).get("data") or {}).get("token") or "")
        s = requests.Session()
        s.headers.update({"Authorization": f"Bearer {tok}", "Content-Type": "application/json"})

        pr = s.post(f"{BASE}/api/config/pull-cloud-admin-runtime", timeout=TIMEOUT)
        body = pr.json() if pr.content else {}
        data = (body.get("data") or {}) if isinstance(body, dict) else {}
        secrets_ready = data.get("secrets_ready")
        after = ""
        if cfg_path.is_file():
            after = str((json.loads(cfg_path.read_text(encoding="utf-8-sig")).get("data_analysis") or {}).get("doubao_api_key") or "")

        not_masked = bool(after) and after != "***" and not str(after).startswith("***")
        results.append(ok("member:pull_http", pr.status_code == 200, f"HTTP {pr.status_code}"))
        results.append(ok("member:pull_secrets_ready", secrets_ready is True or not_masked, f"secrets_ready={secrets_ready}"))
        results.append(ok("member:pull_no_mask_overwrite", not_masked, f"before={before[:8]} after={after[:8]}"))
    except Exception as e:
        results.append(ok("member:pull_http", False, str(e)[:100]))

    # 3) 会员读 admin-runtime（UI 用，允许脱敏）
    try:
        ar = s.get(f"{BASE}/api/config/admin-runtime", timeout=TIMEOUT)
        da = ((ar.json() or {}).get("data") or {}).get("data_analysis") or {}
        results.append(ok("member:admin_runtime_read", ar.status_code == 200, f"model={da.get('doubao_model_name','')}"))
    except Exception as e:
        results.append(ok("member:admin_runtime_read", False, str(e)[:80]))

    # 4) 分析启动前 ensure（不真正跑任务，只测 preflight inspect）
    try:
        ins = s.post(
            f"{BASE}/api/analysis/inspect/title-optimize-inputs",
            json={"task_type": "title_optimize", "source_file": ""},
            timeout=TIMEOUT,
        )
        results.append(ok("member:title_optimize_inspect", ins.status_code == 200, f"HTTP {ins.status_code}"))
    except Exception as e:
        results.append(ok("member:title_optimize_inspect", False, str(e)[:80]))

    # 5) 云端 revision 可读
    try:
        rev = s.get(f"{BASE}/api/config/cloud-admin-revision", timeout=TIMEOUT)
        payload = (rev.json() or {}).get("data") or {}
        results.append(ok("member:cloud_revision", rev.status_code == 200, f"source={payload.get('source')} rev={payload.get('revision')}"))
    except Exception as e:
        results.append(ok("member:cloud_revision", False, str(e)[:80]))

    passed = sum(1 for x in results if x)
    total = len(results)
    print(f"\n=== Summary: {passed}/{total} passed ===")
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())

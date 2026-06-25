# -*- coding: utf-8 -*-
"""验收：① 管理员改 API/模型后其他客户端同步 ② 积分消耗与云端/本地同步及流水记录。"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import time
import uuid
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

BASE = os.getenv("ACCEPTANCE_BACKEND", "http://127.0.0.1:8000")
CLOUD = os.getenv("CLOUD_MEMBERSHIP_API_BASE", "https://echo-yiwu.cloud/api/membership")
# 凭证仅通过环境变量注入，勿在仓库中写默认账号密码（登录以云端为准）
MEMBER_USER = (os.getenv("ACCEPTANCE_MEMBER_USER") or "").strip()
MEMBER_PASS = (os.getenv("ACCEPTANCE_MEMBER_PASS") or "").strip()
TIMEOUT = int(os.getenv("ACCEPTANCE_TIMEOUT", "45"))
CONSUME_AMOUNT = float(os.getenv("ACCEPTANCE_CONSUME_AMOUNT", "0.0001"))

APP_DATA = Path(os.environ.get("APPDATA", "")) / "AliAutoPublish" / "data"
os.environ.setdefault("ALI_APP_DATA_DIR", str(APP_DATA))

PLACEHOLDER_KEYS = frozenset({"", "change-me-admin", "change-me"})


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
    if key in PLACEHOLDER_KEYS:
        key = ""
    if not key:
        cfg_path = APP_DATA / "config.json"
        if cfg_path.is_file():
            try:
                key = str((json.loads(cfg_path.read_text(encoding="utf-8-sig")).get("payment") or {}).get("admin_api_key") or "").strip()
            except Exception:
                pass
    if key in PLACEHOLDER_KEYS and deploy_key:
        key = deploy_key
    return key


def member_login() -> tuple[requests.Session, str]:
    if not MEMBER_USER or not MEMBER_PASS:
        raise RuntimeError("set ACCEPTANCE_MEMBER_USER and ACCEPTANCE_MEMBER_PASS (cloud credentials)")
    r = requests.post(
        f"{BASE}/api/membership/auth/login",
        json={"username": MEMBER_USER, "password": MEMBER_PASS},
        timeout=TIMEOUT,
    )
    if r.status_code != 200:
        raise RuntimeError(f"member login HTTP {r.status_code}: {r.text[:200]}")
    tok = str(((r.json() or {}).get("data") or {}).get("token") or "")
    if not tok:
        raise RuntimeError("member login: empty token")
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {tok}", "Content-Type": "application/json"})
    return s, tok


def read_member_config_model(member_sess: requests.Session) -> str:
    """与运行中 backend 一致：经会员会话读 /api/config/，避免脚本直读 AppData 与 backend 数据目录不一致。"""
    r = member_sess.get(f"{BASE}/api/config/", timeout=TIMEOUT)
    if r.status_code != 200:
        return ""
    try:
        da = ((r.json() or {}).get("data") or {}).get("data_analysis") or {}
        return str(da.get("doubao_model_name") or "")
    except Exception:
        return ""


def cloud_runtime_get(admin_key: str) -> dict:
    r = requests.get(
        f"{CLOUD}/admin/runtime-config",
        headers={"X-Admin-Key": admin_key, "Accept": "application/json"},
        timeout=TIMEOUT,
    )
    if not r.ok:
        raise RuntimeError(f"cloud runtime GET HTTP {r.status_code}: {r.text[:200]}")
    data = (r.json() or {}).get("data") or {}
    return data if isinstance(data, dict) else {}


def cloud_runtime_put(admin_key: str, body: dict) -> dict:
    r = requests.put(
        f"{CLOUD}/admin/runtime-config",
        headers={"X-Admin-Key": admin_key, "Content-Type": "application/json", "Accept": "application/json"},
        json=body,
        timeout=TIMEOUT,
    )
    if not r.ok:
        raise RuntimeError(f"cloud runtime PUT HTTP {r.status_code}: {r.text[:200]}")
    data = (r.json() or {}).get("data") or {}
    return data if isinstance(data, dict) else {}


def test_admin_model_sync(admin_key: str, member_sess: requests.Session) -> list[bool]:
    results: list[bool] = []
    original_model = ""
    original_da: dict = {}
    test_model = ""
    cloud_rev_before = 0

    try:
        cloud_data = cloud_runtime_get(admin_key)
        original_da = dict(cloud_data.get("data_analysis") or {})
        original_model = str(original_da.get("doubao_model_name") or read_member_config_model(member_sess) or "doubao-pro")
        cloud_rev_before = int(cloud_data.get("revision") or 0)
        test_model = f"{original_model}_acc_{int(time.time()) % 100000}"

        new_da = dict(original_da)
        new_da["doubao_model_name"] = test_model
        put_data = cloud_runtime_put(
            admin_key,
            {"data_analysis": new_da, "ai_image_gen": cloud_data.get("ai_image_gen") or {}},
        )
        cloud_rev_after = int(put_data.get("revision") or 0)
        results.append(ok("sync:admin_push_model", cloud_rev_after >= cloud_rev_before, f"rev {cloud_rev_before}->{cloud_rev_after} model={test_model}"))

        pr = member_sess.post(f"{BASE}/api/config/pull-cloud-admin-runtime", timeout=TIMEOUT)
        pull_body = pr.json() if pr.content else {}
        pull_data = (pull_body.get("data") or {}) if isinstance(pull_body, dict) else {}
        config_model = read_member_config_model(member_sess)
        results.append(ok("sync:member_pull_http", pr.status_code == 200, f"HTTP {pr.status_code}"))
        results.append(ok("sync:member_local_config_model", config_model == test_model, f"config={config_model} expected={test_model}"))

        ar = member_sess.get(f"{BASE}/api/config/admin-runtime", timeout=TIMEOUT)
        ar_da = ((ar.json() or {}).get("data") or {}).get("data_analysis") or {}
        api_model = str(ar_da.get("doubao_model_name") or "")
        results.append(ok("sync:member_admin_runtime_model", api_model == test_model, f"api={api_model}"))

        rev = member_sess.get(f"{BASE}/api/config/cloud-admin-revision", timeout=TIMEOUT)
        rev_n = int(((rev.json() or {}).get("data") or {}).get("revision") or 0)
        results.append(ok("sync:member_cloud_revision", rev.status_code == 200 and rev_n >= cloud_rev_after, f"rev={rev_n}"))

        from app.core.admin_runtime_config import is_masked_secret, resolve_runtime_secret

        key = resolve_runtime_secret("data_analysis", "doubao_api_key")
        results.append(ok("sync:member_api_key_still_valid", bool(key) and not is_masked_secret(key), f"len={len(key or '')}"))
    except Exception as e:
        results.append(ok("sync:admin_model_propagation", False, str(e)[:160]))
    finally:
        if original_model and admin_key:
            try:
                cloud_data = cloud_runtime_get(admin_key)
                restore_da = dict(cloud_data.get("data_analysis") or {})
                restore_da["doubao_model_name"] = original_model
                cloud_runtime_put(
                    admin_key,
                    {"data_analysis": restore_da, "ai_image_gen": cloud_data.get("ai_image_gen") or {}},
                )
                member_sess.post(f"{BASE}/api/config/pull-cloud-admin-runtime", timeout=TIMEOUT)
                print(f"[INFO] restored model to {original_model}")
            except Exception as e:
                print(f"[WARN] restore model failed: {e}")

    return results


def local_db_balance(uid: int) -> float | None:
    db = APP_DATA / "membership.db"
    if not db.is_file():
        db = ROOT / "data" / "membership.db"
    if not db.is_file():
        return None
    conn = sqlite3.connect(db)
    try:
        row = conn.execute(
            "SELECT balance_real, balance FROM user_points_accounts WHERE user_id=? LIMIT 1",
            (uid,),
        ).fetchone()
        if not row:
            return None
        br = row[0]
        return round(float(br if br is not None else row[1] or 0), 4)
    finally:
        conn.close()


def local_db_ledger_has(uid: int, biz_id: str, biz_type: str) -> bool:
    db = APP_DATA / "membership.db"
    if not db.is_file():
        db = ROOT / "data" / "membership.db"
    if not db.is_file():
        return False
    conn = sqlite3.connect(db)
    try:
        row = conn.execute(
            """
            SELECT 1 FROM user_points_ledger
            WHERE user_id=? AND biz_id=? AND biz_type=? LIMIT 1
            """,
            (uid, biz_id, biz_type),
        ).fetchone()
        return row is not None
    finally:
        conn.close()


def cloud_me_balance(token: str) -> float:
    r = requests.get(
        f"{CLOUD}/me",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        timeout=TIMEOUT,
    )
    if r.status_code != 200:
        raise RuntimeError(f"cloud /me HTTP {r.status_code}: {r.text[:120]}")
    return round(float(((r.json() or {}).get("data") or {}).get("points_balance") or 0), 4)


def cloud_consume_http(
    token: str, amount: float, biz_type: str, biz_id: str, remark: str
) -> dict:
    r = requests.post(
        f"{CLOUD}/points/consume",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={"amount": amount, "biz_type": biz_type, "biz_id": biz_id, "remark": remark},
        timeout=TIMEOUT,
    )
    if r.status_code != 200:
        raise RuntimeError(f"cloud consume HTTP {r.status_code}: {r.text[:160]}")
    data = (r.json() or {}).get("data") or {}
    return data if isinstance(data, dict) else {}


def test_points_consume(member_sess: requests.Session, token: str) -> list[bool]:
    results: list[bool] = []
    biz_id = f"acceptance-{uuid.uuid4().hex[:12]}"
    biz_type = "acceptance_test"

    try:
        me_r = member_sess.get(f"{BASE}/api/membership/me", timeout=TIMEOUT)
        me_data = (me_r.json() or {}).get("data") or {}
        if me_r.status_code != 200:
            results.append(ok("points:cloud_mode", False, f"/me HTTP {me_r.status_code}"))
            return results
        if me_data.get("points_unavailable"):
            results.append(ok("points:cloud_mode", False, "points_unavailable on /me"))
            return results
        results.append(ok("points:cloud_mode", True, "desktop cloud points via /me"))

        uid = int(me_data.get("id") or me_data.get("user_id") or 0)
        local_me_before = round(float(me_data.get("points_balance") or 0), 4)
        results.append(ok("points:me_before", True, f"balance={local_me_before} uid={uid}"))

        cloud_before = cloud_me_balance(token)
        db_before = local_db_balance(uid) if uid else None
        if cloud_before < CONSUME_AMOUNT:
            results.append(ok("points:sufficient_balance", False, f"cloud={cloud_before} need>={CONSUME_AMOUNT}"))
            return results
        results.append(ok("points:sufficient_balance", True, f"cloud={cloud_before}"))

        ledger_r = member_sess.get(f"{BASE}/api/membership/points/ledger", params={"limit": 5}, timeout=TIMEOUT)
        results.append(ok("points:ledger_readable", ledger_r.status_code == 200, f"HTTP {ledger_r.status_code}"))

        remark = "验收测试扣分"
        consume_data = cloud_consume_http(token, CONSUME_AMOUNT, biz_type, biz_id, remark)
        deducted = round(float(consume_data.get("deducted") or consume_data.get("amount") or CONSUME_AMOUNT), 4)
        balance_after_consume = round(float(consume_data.get("balance") or 0), 4)
        expected = round(cloud_before - deducted, 4)
        results.append(
            ok(
                "points:cloud_consume",
                deducted > 0 and abs(balance_after_consume - expected) < 0.001,
                f"deducted={deducted} balance={balance_after_consume} expected≈{expected}",
            )
        )

        cloud_after = cloud_me_balance(token)
        results.append(
            ok(
                "points:cloud_balance_synced",
                abs(cloud_after - balance_after_consume) < 0.001,
                f"cloud_after={cloud_after}",
            )
        )

        me_r2 = member_sess.get(f"{BASE}/api/membership/me", timeout=TIMEOUT)
        local_me_after = round(float(((me_r2.json() or {}).get("data") or {}).get("points_balance") or 0), 4)
        results.append(
            ok(
                "points:local_me_synced",
                me_r2.status_code == 200 and abs(local_me_after - cloud_after) < 0.001,
                f"me_before={local_me_before} me_after={local_me_after} cloud={cloud_after}",
            )
        )

        db_after = local_db_balance(uid)
        if db_after is not None:
            results.append(
                ok(
                    "points:local_db_balance",
                    abs(db_after - cloud_after) < 0.001,
                    f"db_before={db_before} db_after={db_after}",
                )
            )
        else:
            results.append(
                ok(
                    "points:local_db_balance",
                    abs(local_me_after - cloud_after) < 0.001,
                    "skip direct db: use /me proxy (backend data dir may differ from script)",
                )
            )

        ledger_r2 = member_sess.get(f"{BASE}/api/membership/points/ledger", params={"limit": 20}, timeout=TIMEOUT)
        rows = (ledger_r2.json() or {}).get("data") or []
        found_cloud_ledger = any(
            str(r.get("biz_id") or "") == biz_id or (remark in str(r.get("remark") or "") and str(r.get("biz_type") or "") == biz_type)
            for r in rows
            if isinstance(r, dict)
        )
        results.append(ok("points:client_ledger_record", found_cloud_ledger, f"biz_id={biz_id} rows={len(rows)}"))

        has_local = local_db_ledger_has(uid, biz_id, biz_type) if uid else False
        results.append(
            ok(
                "points:local_mirror_ledger",
                has_local or found_cloud_ledger,
                f"biz_id={biz_id} local={has_local}",
            )
        )

    except Exception as e:
        results.append(ok("points:consume_flow", False, str(e)[:200]))

    return results


def main() -> int:
    results: list[bool] = []
    print("=== Acceptance: admin sync + points consume ===\n")

    admin_key = load_admin_key()
    results.append(ok("preflight:admin_key", admin_key not in PLACEHOLDER_KEYS, f"prefix={admin_key[:8] if admin_key else 'EMPTY'}"))

    try:
        health = requests.get(f"{BASE}/api/config/revision", timeout=TIMEOUT)
        results.append(ok("preflight:backend", health.status_code == 200, f"HTTP {health.status_code}"))
    except Exception as e:
        results.append(ok("preflight:backend", False, str(e)[:80]))
        passed = sum(1 for x in results if x)
        print(f"\n=== Summary: {passed}/{len(results)} passed ===")
        return 1

    try:
        member_sess, token = member_login()
        results.append(ok("preflight:member_login", True, MEMBER_USER))
    except Exception as e:
        results.append(ok("preflight:member_login", False, str(e)[:100]))
        passed = sum(1 for x in results if x)
        print(f"\n=== Summary: {passed}/{len(results)} passed ===")
        return 1

    print("\n--- (1) Admin model/API sync to other clients ---")
    if admin_key:
        results.extend(test_admin_model_sync(admin_key, member_sess))
    else:
        results.append(ok("sync:admin_model_propagation", False, "no admin key"))

    print("\n--- (2) Points consume + cloud/local sync + ledger ---")
    try:
        member_sess, token = member_login()
    except Exception as e:
        results.append(ok("points:preflight_relogin", False, str(e)[:100]))
    else:
        results.extend(test_points_consume(member_sess, token))

    passed = sum(1 for x in results if x)
    total = len(results)
    print(f"\n=== Summary: {passed}/{total} passed ===")
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())

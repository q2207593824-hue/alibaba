# -*- coding: utf-8 -*-
"""
全系统增删改查（CRUD）验收。
- 覆盖配置、会员、数据、分析、图片、任务等写操作
- 使用临时数据并在测试后清理
- 不含产品上传子树启动类操作（发品/优化上架/视频绑定/发品配置 start）
- 跳过需浏览器/Cookie/真实支付/批量破坏类接口
"""
from __future__ import annotations

import json
import os
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Callable

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

BASE = os.getenv("ACCEPTANCE_BACKEND", "http://127.0.0.1:8000")
# 凭证仅通过环境变量注入，勿在仓库中写默认账号密码（登录以云端为准）
MEMBER_USER = (os.getenv("ACCEPTANCE_MEMBER_USER") or "").strip()
MEMBER_PASS = (os.getenv("ACCEPTANCE_MEMBER_PASS") or "").strip()
ADMIN_USER = (os.getenv("ACCEPTANCE_ADMIN_USER") or "").strip()
ADMIN_PASS = (os.getenv("ACCEPTANCE_ADMIN_PASS") or "").strip()
TIMEOUT = int(os.getenv("ACCEPTANCE_TIMEOUT", "45"))
PLACEHOLDER_KEYS = frozenset({"", "change-me-admin", "change-me"})

RUN_ID = uuid.uuid4().hex[:8]
TEST_GROUP = f"__crud_group_{RUN_ID}__"
TEST_ATTR = f"__crud_attr_{RUN_ID}__"
TEST_AGENT = f"crud-agent-{RUN_ID}"
TEST_USER = f"crud_user_{RUN_ID}"
TEST_BATCH = f"batch-{RUN_ID}"


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


def admin_session_setup() -> tuple[requests.Session, str]:
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    admin_key = load_admin_key()
    token = ""
    if ADMIN_PASS:
        r = s.post(f"{BASE}/api/membership/auth/login", json={"username": ADMIN_USER, "password": ADMIN_PASS}, timeout=TIMEOUT)
        data = (r.json() or {}).get("data") or {}
        token = str(data.get("token") or "")
        admin_key = str(data.get("admin_key") or admin_key)
    elif admin_key:
        r = s.post(f"{BASE}/api/membership/auth/sync-admin-session", headers={"X-Admin-Key": admin_key}, timeout=TIMEOUT)
        data = (r.json() or {}).get("data") or {}
        token = str(data.get("token") or "")
    if admin_key:
        s.headers["X-Admin-Key"] = admin_key
    if token:
        s.headers["Authorization"] = f"Bearer {token}"
    return s, admin_key


def member_session_setup() -> requests.Session:
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    if not MEMBER_USER or not MEMBER_PASS:
        return s
    r = s.post(f"{BASE}/api/membership/auth/login", json={"username": MEMBER_USER, "password": MEMBER_PASS}, timeout=TIMEOUT)
    token = str(((r.json() or {}).get("data") or {}).get("token") or "")
    s.headers["Authorization"] = f"Bearer {token}"
    return s


def expect_status(r: requests.Response, codes: set[int]) -> tuple[bool, str]:
    passed = r.status_code in codes and r.status_code not in (401, 403, 500, 502, 503)
    body = ""
    try:
        body = json.dumps(r.json(), ensure_ascii=False)[:120]
    except Exception:
        body = r.text[:120]
    return passed, f"HTTP {r.status_code} {body}"


def run_case(name: str, fn: Callable[[], tuple[bool, str]]) -> bool:
    try:
        passed, detail = fn()
        return ok(name, passed, detail)
    except Exception as e:
        return ok(name, False, str(e)[:120])


def test_config_group_url_crud(admin: requests.Session) -> list[bool]:
    results: list[bool] = []
    url = "https://example.com/crud-test"

    def create_update():
        r = admin.put(f"{BASE}/api/config/group-urls/{TEST_GROUP}", json={"url": url}, timeout=TIMEOUT)
        if r.status_code != 200:
            return False, f"PUT HTTP {r.status_code}"
        r2 = admin.get(f"{BASE}/api/config/group-urls/list", timeout=TIMEOUT)
        data = ((r2.json() or {}).get("data") or {}).get("group_url_map") or {}
        return r2.status_code == 200 and data.get(TEST_GROUP) == url, f"read back {TEST_GROUP in data}"

    def delete():
        r = admin.delete(f"{BASE}/api/config/group-urls/{TEST_GROUP}", timeout=TIMEOUT)
        if r.status_code != 200:
            return False, f"DELETE HTTP {r.status_code}"
        r2 = admin.get(f"{BASE}/api/config/group-urls/list", timeout=TIMEOUT)
        data = ((r2.json() or {}).get("data") or {}).get("group_url_map") or {}
        return TEST_GROUP not in data, "removed from list"

    results.append(run_case("config:group_url:create", create_update))
    results.append(run_case("config:group_url:delete", delete))
    return results


def test_config_attribute_crud(admin: requests.Session) -> list[bool]:
    results: list[bool] = []
    body = {
        "container_id": "crud-container",
        "values": ["v1"],
        "type": "optional",
        "select_type": "tag",
    }

    def create():
        r = admin.put(f"{BASE}/api/config/attributes/{TEST_ATTR}", json=body, timeout=TIMEOUT)
        if r.status_code != 200:
            return False, f"PUT HTTP {r.status_code}"
        r2 = admin.get(f"{BASE}/api/config/attributes/list", timeout=TIMEOUT)
        attrs = ((r2.json() or {}).get("data") or {}).get("all_attributes") or {}
        return TEST_ATTR in attrs, "attr in list"

    def delete():
        r = admin.delete(f"{BASE}/api/config/attributes/{TEST_ATTR}", timeout=TIMEOUT)
        return expect_status(r, {200})

    results.append(run_case("config:attribute:create", create))
    results.append(run_case("config:attribute:delete", delete))
    return results


def test_config_section_crud(admin: requests.Session) -> list[bool]:
    results: list[bool] = []
    backup: dict[str, Any] = {}

    def read_backup():
        nonlocal backup
        r = admin.get(f"{BASE}/api/config/section/schedule", timeout=TIMEOUT)
        if r.status_code != 200:
            return False, f"GET HTTP {r.status_code}"
        backup = (r.json() or {}).get("data") or {}
        return bool(backup), "loaded schedule"

    def update_restore():
        orig = int(backup.get("check_interval") or 60)
        new_val = orig + 1 if orig < 999 else orig - 1
        r = admin.put(f"{BASE}/api/config/section/schedule", json={"check_interval": new_val}, timeout=TIMEOUT)
        if r.status_code != 200:
            return False, f"update HTTP {r.status_code}"
        r2 = admin.get(f"{BASE}/api/config/section/schedule", timeout=TIMEOUT)
        got = int(((r2.json() or {}).get("data") or {}).get("check_interval") or 0)
        if got != new_val:
            return False, f"check_interval={got} expected {new_val}"
        r3 = admin.put(f"{BASE}/api/config/section/schedule", json={"check_interval": orig}, timeout=TIMEOUT)
        return r3.status_code == 200, "restored schedule"

    results.append(run_case("config:section:read", read_backup))
    if backup:
        results.append(run_case("config:section:update", update_restore))
    return results


def test_config_reload_pull(admin: requests.Session) -> list[bool]:
    results: list[bool] = []

    def reload_cfg():
        r = admin.post(f"{BASE}/api/config/reload", timeout=TIMEOUT)
        return expect_status(r, {200})

    def pull_cloud():
        r = admin.post(f"{BASE}/api/config/pull-cloud-admin-runtime", timeout=TIMEOUT)
        return expect_status(r, {200, 400})

    results.append(run_case("config:reload", reload_cfg))
    results.append(run_case("config:pull_cloud_admin_runtime", pull_cloud))
    return results


def test_images_config_crud(admin: requests.Session) -> list[bool]:
    results: list[bool] = []
    backup: dict[str, Any] = {}

    def norm_roundtrip():
        nonlocal backup
        r = admin.get(f"{BASE}/api/images/config", timeout=TIMEOUT)
        if r.status_code != 200:
            return False, f"GET HTTP {r.status_code}"
        backup = dict((r.json() or {}).get("data") or {})
        payload = dict(backup)
        payload["_crud_touch"] = RUN_ID
        r2 = admin.put(f"{BASE}/api/images/config", json=payload, timeout=TIMEOUT)
        if r2.status_code != 200:
            return False, f"PUT HTTP {r2.status_code}"
        restore = dict(backup)
        restore.pop("_crud_touch", None)
        r3 = admin.put(f"{BASE}/api/images/config", json=restore, timeout=TIMEOUT)
        return r3.status_code == 200, "restored image norm config"

    def ai_gen_roundtrip():
        r = admin.get(f"{BASE}/api/images/ai-gen/config", timeout=TIMEOUT)
        if r.status_code != 200:
            return False, f"GET HTTP {r.status_code}"
        cfg = dict((r.json() or {}).get("data") or {})
        payload = {"request_interval": int(cfg.get("request_interval") or 3)}
        r2 = admin.put(f"{BASE}/api/images/ai-gen/config", json=payload, timeout=TIMEOUT)
        return expect_status(r2, {200})

    results.append(run_case("images:norm_config:update", norm_roundtrip))
    results.append(run_case("images:ai_gen_config:update", ai_gen_roundtrip))
    return results


def test_agent_crud(admin: requests.Session) -> list[bool]:
    results: list[bool] = []

    def register():
        r = admin.post(
            f"{BASE}/api/membership/agent/register",
            json={"agent_id": TEST_AGENT, "client_name": "CRUD Test", "app_version": "0.0.1"},
            timeout=TIMEOUT,
        )
        return expect_status(r, {200})

    def heartbeat():
        r = admin.post(
            f"{BASE}/api/membership/agent/heartbeat",
            json={"agent_id": TEST_AGENT, "status": "active"},
            timeout=TIMEOUT,
        )
        return expect_status(r, {200})

    def policy_upsert_read():
        policy = {"allow_download": False, "note": f"crud-{RUN_ID}"}
        r = admin.post(
            f"{BASE}/api/membership/admin/agents/policy",
            json={"agent_id": TEST_AGENT, "policy": policy},
            timeout=TIMEOUT,
        )
        if r.status_code != 200:
            return False, f"policy PUT HTTP {r.status_code}"
        r2 = admin.get(f"{BASE}/api/membership/agent/policy", params={"agent_id": TEST_AGENT}, timeout=TIMEOUT)
        got = ((r2.json() or {}).get("data") or {}).get("policy") or {}
        if r2.status_code != 200 or got.get("allow_download") is not False:
            return False, f"policy read back allow_download={got.get('allow_download')}"
        admin.post(
            f"{BASE}/api/membership/admin/agents/policy",
            json={"agent_id": TEST_AGENT, "policy": {"allow_download": True, "note": ""}},
            timeout=TIMEOUT,
        )
        return True, "policy roundtrip ok"

    def list_agents():
        r = admin.get(f"{BASE}/api/membership/admin/agents", params={"limit": 50}, timeout=TIMEOUT)
        if r.status_code != 200:
            return False, f"HTTP {r.status_code}"
        rows = (r.json() or {}).get("data") or []
        ids = {str(x.get("agent_id") or "") for x in rows}
        return TEST_AGENT in ids, f"agent listed ({len(rows)} rows)"

    results.append(run_case("membership:agent:register", register))
    results.append(run_case("membership:agent:heartbeat", heartbeat))
    results.append(run_case("membership:agent:policy", policy_upsert_read))
    results.append(run_case("membership:agent:list", list_agents))
    return results


def test_telemetry_keywords_crud(admin: requests.Session, member: requests.Session) -> list[bool]:
    results: list[bool] = []
    report_id: int | None = None
    today = time.strftime("%Y-%m-%d")

    def create():
        r = member.post(
            f"{BASE}/api/membership/telemetry/keywords",
            json={
                "agent_id": TEST_AGENT,
                "report_date": today,
                "batch_no": TEST_BATCH,
                "items": [{"keyword": f"kw-{RUN_ID}", "exposure": 1, "click": 0.1}],
            },
            timeout=TIMEOUT,
        )
        return expect_status(r, {200})

    def read_list():
        nonlocal report_id
        r = admin.get(
            f"{BASE}/api/membership/admin/telemetry/keywords",
            params={"agent_id": TEST_AGENT, "limit": 20},
            timeout=TIMEOUT,
        )
        if r.status_code != 200:
            return False, f"list HTTP {r.status_code}"
        rows = (r.json() or {}).get("data") or []
        for row in rows:
            if str(row.get("batch_no") or "") == TEST_BATCH:
                report_id = int(row.get("id") or 0)
                break
        return report_id is not None and report_id > 0, f"report_id={report_id}"

    def read_detail():
        if not report_id:
            return False, "no report_id"
        r = admin.get(f"{BASE}/api/membership/admin/telemetry/keywords/{report_id}", timeout=TIMEOUT)
        items = ((r.json() or {}).get("data") or {}).get("items") or []
        return r.status_code == 200 and len(items) >= 1, f"items={len(items)}"

    def delete_batch():
        if not report_id:
            return False, "no report_id"
        r = admin.post(
            f"{BASE}/api/membership/admin/telemetry/keywords/batch/delete",
            json={"report_ids": [report_id]},
            timeout=TIMEOUT,
        )
        return expect_status(r, {200})

    results.append(run_case("telemetry:keywords:create", create))
    results.append(run_case("telemetry:keywords:list", read_list))
    if report_id:
        results.append(run_case("telemetry:keywords:detail", read_detail))
        results.append(run_case("telemetry:keywords:delete", delete_batch))
    return results


def test_admin_user_crud(admin: requests.Session) -> list[bool]:
    results: list[bool] = []
    user_id: int | None = None

    def create():
        nonlocal user_id
        r = admin.post(
            f"{BASE}/api/membership/admin/users/create",
            json={
                "username": TEST_USER,
                "password": "CrudPass123!",
                "real_name": "CRUD",
                "points_balance": 0,
                "trial_days": 1,
            },
            timeout=TIMEOUT,
        )
        if r.status_code != 200:
            return expect_status(r, {200})
        user_id = int(((r.json() or {}).get("data") or {}).get("user_id") or 0)
        return user_id > 0, f"user_id={user_id}"

    def list_users():
        r = admin.get(f"{BASE}/api/membership/admin/users", params={"limit": 200}, timeout=TIMEOUT)
        if r.status_code != 200:
            return False, f"HTTP {r.status_code}"
        rows = (r.json() or {}).get("data") or []
        found = any(str(x.get("username") or "") == TEST_USER for x in rows)
        return found, f"listed ({len(rows)} users)"

    def control_update():
        if not user_id:
            return False, "no user_id"
        r1 = admin.post(
            f"{BASE}/api/membership/admin/users/control",
            json={"user_id": user_id, "mode": "normal", "note": f"crud-{RUN_ID}"},
            timeout=TIMEOUT,
        )
        if r1.status_code != 200:
            return False, f"control HTTP {r1.status_code}"
        r2 = admin.post(
            f"{BASE}/api/membership/admin/users/update",
            json={"user_id": user_id, "points_balance": 0.5},
            timeout=TIMEOUT,
        )
        return expect_status(r2, {200})

    def delete_user():
        if not user_id:
            return False, "no user_id"
        r = admin.post(f"{BASE}/api/membership/admin/users/delete", json={"user_id": user_id}, timeout=TIMEOUT)
        return expect_status(r, {200})

    results.append(run_case("admin:user:create", create))
    results.append(run_case("admin:user:list", list_users))
    if user_id:
        results.append(run_case("admin:user:control+update", control_update))
        results.append(run_case("admin:user:delete", delete_user))
    return results


def test_member_auth_crud(member: requests.Session, admin: requests.Session) -> list[bool]:
    results: list[bool] = []
    reg_user = f"reg_{RUN_ID}"
    reg_pass = "RegPass123!"

    def register():
        r = requests.post(
            f"{BASE}/api/membership/auth/register",
            json={"username": reg_user, "password": reg_pass},
            timeout=TIMEOUT,
        )
        return expect_status(r, {200})

    def sync_local_session():
        # 需云端有效 token；使用已登录会员账号验证 sync-local-session 写操作
        r2 = member.post(
            f"{BASE}/api/membership/auth/sync-local-session",
            timeout=TIMEOUT,
        )
        return expect_status(r2, {200})

    def cleanup_registered():
        r = admin.get(f"{BASE}/api/membership/admin/users", params={"limit": 300}, timeout=TIMEOUT)
        rows = (r.json() or {}).get("data") or []
        uid = 0
        for row in rows:
            if str(row.get("username") or "") == reg_user:
                uid = int(row.get("user_id") or row.get("id") or 0)
                break
        if uid <= 0:
            return True, "already gone"
        r2 = admin.post(f"{BASE}/api/membership/admin/users/delete", json={"user_id": uid}, timeout=TIMEOUT)
        return expect_status(r2, {200})

    results.append(run_case("auth:register", register))
    results.append(run_case("auth:sync_local_session", sync_local_session))
    results.append(run_case("auth:register_cleanup", cleanup_registered))
    return results


def test_recharge_create_read(member: requests.Session) -> list[bool]:
    results: list[bool] = []

    def create_order():
        r = member.post(
            f"{BASE}/api/membership/recharge/create",
            json={"amount_yuan": 0.01, "channel": "wechat"},
            timeout=TIMEOUT,
        )
        return expect_status(r, {200, 400})

    def list_orders():
        r = member.get(f"{BASE}/api/membership/recharge/list-paged", params={"page": 1, "page_size": 5}, timeout=TIMEOUT)
        return expect_status(r, {200, 400})

    results.append(run_case("membership:recharge:create", create_order))
    results.append(run_case("membership:recharge:list", list_orders))
    return results


def test_upload_start_stop_roundtrip(session: requests.Session, prefix: str) -> list[bool]:
    """发品 / 优化上架 / 视频绑定：启动后立即停止（不等待 Selenium 完成）。"""
    results: list[bool] = []
    jobs = (
        ("upload", "/api/upload/start", "/api/upload/stop", {"mode": "batch", "max_products": 1}),
        ("optimize", "/api/upload/optimize/start", "/api/upload/optimize/stop", {}),
        ("video_bind", "/api/video-bind/start", "/api/video-bind/stop", {}),
    )
    for label, start_path, stop_path, body in jobs:
        def _roundtrip(sp=start_path, tp=stop_path, b=body, lb=label):
            sr = session.post(f"{BASE}{sp}", json=b, timeout=TIMEOUT)
            if sr.status_code not in (200, 409):
                return False, f"start HTTP {sr.status_code}"
            tr = session.post(f"{BASE}{tp}", json={}, timeout=TIMEOUT)
            return tr.status_code in (200, 400), f"start={sr.status_code} stop={tr.status_code}"

        results.append(run_case(f"{prefix}:upload_roundtrip:{label}", _roundtrip))
    return results


def test_idle_stop_endpoints(session: requests.Session, prefix: str) -> list[bool]:
    """无运行中任务时 stop/pause/resume/delete 应返回 400/404，证明路由可达。"""
    results: list[bool] = []
    idle_ok = {200, 400, 404}

    checks = [
        ("POST", "/api/data/download/stop/industry_keyword", "download:stop"),
        ("POST", "/api/data/industry-keyword/title/generate/stop", "download:title_gen_stop"),
        ("POST", "/api/analysis/stop/title_optimize", "analysis:stop"),
        ("POST", "/api/images/normalize/stop", "images:normalize_stop"),
        ("POST", "/api/images/ai-gen/stop", "images:ai_gen_stop"),
        ("POST", "/api/upload/stop", "upload:stop"),
        ("POST", "/api/upload/optimize/stop", "upload:optimize_stop"),
        ("POST", "/api/video-bind/stop", "video_bind:stop"),
        ("POST", "/api/tasks/__crud_missing__/stop", "tasks:stop_missing"),
        ("POST", "/api/tasks/__crud_missing__/pause", "tasks:pause_missing"),
        ("DELETE", "/api/tasks/__crud_missing__", "tasks:delete_missing"),
    ]
    for method, path, name in checks:
        def _call(m=method, p=path):
            r = session.request(m, f"{BASE}{p}", timeout=TIMEOUT)
            return expect_status(r, idle_ok)

        results.append(run_case(f"{prefix}:{name}", _call))
    return results


def test_data_mutations(admin: requests.Session) -> list[bool]:
    results: list[bool] = []

    def industry_delete():
        r = admin.post(
            f"{BASE}/api/data/industry-keyword/delete",
            json={"keywords": [f"__no_such_kw_{RUN_ID}__"]},
            timeout=TIMEOUT,
        )
        return expect_status(r, {200, 400, 404, 500})

    def dropdown_delete():
        r = admin.post(
            f"{BASE}/api/data/industry-keyword/dropdown/delete",
            json={"rows": [{"原词": f"__none_{RUN_ID}__", "下拉词": "x"}]},
            timeout=TIMEOUT,
        )
        return expect_status(r, {200, 400, 404, 500})

    def product360_channels():
        r = admin.post(
            f"{BASE}/api/data/product360/traffic-channels",
            json={"product_ids": [], "output_dir": ""},
            timeout=TIMEOUT,
        )
        return expect_status(r, {200, 400})

    def analysis_inspect():
        r = admin.post(
            f"{BASE}/api/analysis/inspect/title-optimize-inputs",
            json={"task_type": "title_optimize", "source_file": ""},
            timeout=TIMEOUT,
        )
        return expect_status(r, {200, 400})

    results.append(run_case("data:industry_keyword:delete", industry_delete))
    results.append(run_case("data:industry_dropdown:delete", dropdown_delete))
    results.append(run_case("data:product360:traffic_channels", product360_channels))
    results.append(run_case("analysis:inspect_title_inputs", analysis_inspect))
    return results


def test_admin_runtime_config(admin: requests.Session) -> list[bool]:
    results: list[bool] = []

    def read():
        r = admin.get(f"{BASE}/api/config/admin-runtime", timeout=TIMEOUT)
        return expect_status(r, {200})

    def merge_put():
        r = admin.put(
            f"{BASE}/api/membership/admin/runtime-config",
            json={"data_analysis": {}, "ai_image_gen": {}},
            timeout=TIMEOUT,
        )
        return expect_status(r, {200, 400})

    results.append(run_case("admin:runtime_config:read", read))
    results.append(run_case("admin:runtime_config:merge_put", merge_put))
    return results


def main() -> int:
    print("=== CRUD acceptance (incl. upload/optimize/video-bind start-stop; excl. browser cookie / payment approve) ===")
    print(f"run_id={RUN_ID}")
    print()

    results: list[bool] = []
    try:
        h = requests.get(f"{BASE}/api/health", timeout=10)
        results.append(ok("health", h.ok, h.text[:60]))
    except Exception as e:
        print(f"[FAIL] health — {e}")
        return 1

    admin, admin_key = admin_session_setup()
    member = member_session_setup()
    member_ok = "Authorization" in member.headers
    results.append(ok("admin:session", bool(admin_key) and admin_key not in PLACEHOLDER_KEYS, admin_key[:8] + "..." if admin_key else "empty"))
    if MEMBER_USER and MEMBER_PASS:
        results.append(ok("member:login", member_ok, ""))
    else:
        results.append(ok("member:login", False, "skipped: set ACCEPTANCE_MEMBER_USER/PASS"))

    print("\n--- Config CRUD ---")
    results.extend(test_config_group_url_crud(admin))
    results.extend(test_config_attribute_crud(admin))
    results.extend(test_config_section_crud(admin))
    results.extend(test_config_reload_pull(admin))

    print("\n--- Images config CRUD ---")
    results.extend(test_images_config_crud(admin))

    print("\n--- Membership / Agent CRUD ---")
    results.extend(test_agent_crud(admin))
    if member_ok:
        results.extend(test_telemetry_keywords_crud(admin, member))
    results.extend(test_admin_user_crud(admin))
    if member_ok:
        results.extend(test_member_auth_crud(member, admin))
        results.extend(test_recharge_create_read(member))
    results.extend(test_admin_runtime_config(admin))

    print("\n--- Data / Analysis mutations ---")
    results.extend(test_data_mutations(admin))

    print("\n--- Upload / optimize / video-bind start-stop roundtrip ---")
    results.extend(test_upload_start_stop_roundtrip(admin, "admin"))
    if member_ok:
        results.extend(test_upload_start_stop_roundtrip(member, "member"))

    print("\n--- Idle stop / task control (route reachability) ---")
    results.extend(test_idle_stop_endpoints(admin, "admin"))
    if member_ok:
        results.extend(test_idle_stop_endpoints(member, "member"))

    passed = sum(1 for x in results if x)
    total = len(results)
    print(f"\n=== CRUD Summary: {passed}/{total} passed ===")
    if passed < total:
        print("Some CRUD checks failed — review output above.")
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())

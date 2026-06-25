# -*- coding: utf-8 -*-
"""Comprehensive API audit script - tests CRUD endpoints without destructive side effects."""
from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

BASE = "http://127.0.0.1:8000"
ADMIN_KEY = "change-me-admin"
DEVICE_ID = "api-audit-device-001"


@dataclass
class Result:
    module: str
    name: str
    method: str
    path: str
    status: int
    ok: bool
    note: str = ""
    detail: Any = None


@dataclass
class AuditReport:
    results: List[Result] = field(default_factory=list)

    def add(self, **kwargs):
        self.results.append(Result(**kwargs))

    def summary(self) -> Dict[str, Any]:
        total = len(self.results)
        passed = sum(1 for r in self.results if r.ok)
        failed = [r for r in self.results if not r.ok]
        by_module: Dict[str, Dict[str, int]] = {}
        for r in self.results:
            by_module.setdefault(r.module, {"pass": 0, "fail": 0})
            by_module[r.module]["pass" if r.ok else "fail"] += 1
        return {
            "total": total,
            "passed": passed,
            "failed": len(failed),
            "by_module": by_module,
            "failures": failed,
        }


report = AuditReport()


def http(
    method: str,
    path: str,
    body: Any = None,
    *,
    admin: bool = True,
    token: str = "",
    timeout: float = 20,
) -> Tuple[int, Any]:
    headers = {
        "Content-Type": "application/json",
        "X-Client-Device-Id": DEVICE_ID,
    }
    if admin:
        headers["X-Admin-Key"] = ADMIN_KEY
    if token:
        headers["Authorization"] = f"Bearer {token}"

    data = None
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")

    # Encode non-ASCII in query (e.g. sheet_name=全店曝光次数)
    if isinstance(path, str) and "?" in path and any(ord(c) > 127 for c in path):
        p, qs = path.split("?", 1)
        path = p + "?" + urllib.parse.urlencode(urllib.parse.parse_qsl(qs, keep_blank_values=True))
    req = urllib.request.Request(BASE + path, data=data, headers=headers, method=method.upper())
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            try:
                return resp.status, json.loads(raw)
            except json.JSONDecodeError:
                return resp.status, raw[:300]
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace")
        try:
            return e.code, json.loads(raw)
        except json.JSONDecodeError:
            return e.code, raw[:300]


def record(
    module: str,
    name: str,
    method: str,
    path: str,
    status: int,
    body: Any,
    *,
    expect: Optional[Callable[[int, Any], bool]] = None,
    note: str = "",
):
    if expect is None:
        ok = 200 <= status < 400
    else:
        ok = expect(status, body)
    detail = ""
    if isinstance(body, dict):
        detail = body.get("detail") or body.get("message") or body.get("success")
    report.add(
        module=module,
        name=name,
        method=method,
        path=path,
        status=status,
        ok=ok,
        note=note,
        detail=detail,
    )


def expect_ok(status: int, body: Any) -> bool:
    return 200 <= status < 400


def expect_404_or_ok(status: int, body: Any) -> bool:
    return status == 404 or (200 <= status < 400)


def expect_400_or_ok(status: int, body: Any) -> bool:
    return status == 400 or (200 <= status < 400)


def audit_config():
    m = "配置管理"
    s, b = http("GET", "/api/config/revision", admin=False)
    record(m, "读取 revision", "GET", "/api/config/revision", s, b, expect=expect_ok)

    s, b = http("GET", "/api/config/")
    record(m, "读取全部配置", "GET", "/api/config/", s, b, expect=expect_ok)

    s, b = http("GET", "/api/config/admin-runtime")
    record(m, "读取管理员运行时配置", "GET", "/api/config/admin-runtime", s, b, expect=expect_ok)

    s, b = http("GET", "/api/config/template")
    record(m, "读取配置模板", "GET", "/api/config/template", s, b, expect=expect_ok)

    s, b = http("GET", "/api/config/section/data_analysis")
    record(m, "读取 data_analysis 分区", "GET", "/api/config/section/data_analysis", s, b, expect=expect_ok)

    s, b = http("GET", "/api/config/attributes/list")
    record(m, "读取属性列表", "GET", "/api/config/attributes/list", s, b, expect=expect_ok)

    s, b = http("GET", "/api/config/group-urls/list")
    record(m, "读取分组链接列表", "GET", "/api/config/group-urls/list", s, b, expect=expect_ok)

    # Update section (non-destructive: write back same value)
    if isinstance(b if False else None, dict):
        pass
    s0, b0 = http("GET", "/api/config/section/data_analysis")
    if s0 == 200 and isinstance(b0, dict) and b0.get("success"):
        section_data = b0.get("data") or {}
        s, b = http("PUT", "/api/config/section/data_analysis", {"data": section_data})
        record(m, "更新 data_analysis 分区", "PUT", "/api/config/section/data_analysis", s, b, expect=expect_ok)

    # Auth without admin key should fail on protected routes
    s, b = http("GET", "/api/config/", admin=False)
    record(
        m,
        "未登录读取配置应拒绝",
        "GET",
        "/api/config/",
        s,
        b,
        expect=lambda st, _: st == 401,
        note="401 为预期",
    )


def audit_upload():
    m = "自动发品"
    for path, name in [
        ("/api/upload/status", "读取任务状态"),
        ("/api/upload/products/available", "读取可发品列表"),
        ("/api/upload/products/published", "读取已发品列表"),
        ("/api/upload/optimize/status", "读取优化任务状态"),
        ("/api/upload/optimize/list", "读取优化列表"),
        ("/api/upload/optimize/failed-today", "读取今日失败优化"),
    ]:
        s, b = http("GET", path)
        record(m, name, "GET", path, s, b, expect=expect_ok)

    # stop when idle -> 400 expected
    s, b = http("POST", "/api/upload/stop", {})
    record(m, "停止空闲发品任务", "POST", "/api/upload/stop", s, b, expect=expect_400_or_ok)

    s, b = http("POST", "/api/upload/optimize/stop", {})
    record(m, "停止空闲优化任务", "POST", "/api/upload/optimize/stop", s, b, expect=expect_400_or_ok)


def audit_analysis():
    m = "数据分析"
    reads = [
        ("/api/analysis/overview", "数据概览"),
        ("/api/analysis/points-pricing", "积分定价"),
        ("/api/analysis/volatility/anomaly", "流量波动异动"),
        ("/api/analysis/diagnosis/table", "诊断表"),
        ("/api/analysis/traffic-ai/result", "流量AI结果"),
        ("/api/analysis/title-optimize/results", "标题优化结果"),
        ("/api/analysis/new-links/monitor?sheet_name=全店曝光次数", "新发链接监控"),
        ("/api/analysis/statistics/table", "统计表"),
        ("/api/analysis/p4p/table", "P4P表"),
    ]
    for path, name in reads:
        s, b = http("GET", path)
        # 404 acceptable when output files missing
        record(m, name, "GET", path, s, b, expect=expect_404_or_ok)

    for task_type in ["comprehensive", "title_optimize", "traffic_ai"]:
        s, b = http("GET", f"/api/analysis/status/{task_type}")
        record(m, f"任务状态 {task_type}", "GET", f"/api/analysis/status/{task_type}", s, b, expect=expect_ok)


def audit_data():
    m = "数据下载"
    reads = [
        ("/api/data/download/status", "全部下载状态"),
        ("/api/data/files", "文件列表"),
        ("/api/data/keyword/anomaly/latest", "关键词异动"),
        ("/api/data/keyword/summary/latest", "关键词汇总"),
        ("/api/data/industry-keyword/latest", "行业关键词"),
        ("/api/data/industry-keyword/dropdown/latest", "行业下拉词"),
        ("/api/data/store/overview/latest?include_details=false", "店铺概览"),
        ("/api/data/store/summary/table", "店铺周汇总"),
        ("/api/data/product360/table", "产品360表"),
        ("/api/data/product-operate/table", "产品运营表"),
        ("/api/data/traffic-channel/overview", "流量渠道概览"),
        ("/api/data/store-image/list", "店铺图片列表"),
    ]
    for path, name in reads:
        s, b = http("GET", path)
        record(m, name, "GET", path, s, b, expect=expect_404_or_ok)

    s, b = http("POST", "/api/data/product360/traffic-channels", {"product_ids": []})
    record(m, "产品360流量渠道", "POST", "/api/data/product360/traffic-channels", s, b, expect=expect_404_or_ok)


def audit_images():
    m = "图片管理"
    reads = [
        ("/api/images/groups", "图片分组"),
        ("/api/images/stats", "图片统计"),
        ("/api/images/config", "规范化配置"),
        ("/api/images/normalize/status", "规范化状态"),
        ("/api/images/logs/recent?limit=10", "规范化日志"),
        ("/api/images/ai-gen/config", "AI生图配置"),
        ("/api/images/ai-gen/inputs", "AI生图输入"),
        ("/api/images/ai-gen/outputs", "AI生图输出"),
        ("/api/images/ai-gen/points-pricing", "AI生图积分定价"),
        ("/api/images/ai-gen/points-estimate", "AI生图积分估算"),
        ("/api/images/ai-gen/status", "AI生图状态"),
        ("/api/images/ai-gen/logs/recent?limit=10", "AI生图日志"),
    ]
    for path, name in reads:
        s, b = http("GET", path)
        record(m, name, "GET", path, s, b, expect=expect_ok)

    s, b = http("POST", "/api/images/normalize/stop", {})
    record(m, "停止空闲规范化", "POST", "/api/images/normalize/stop", s, b, expect=expect_400_or_ok)

    s, b = http("POST", "/api/images/ai-gen/stop", {})
    record(m, "停止空闲AI生图", "POST", "/api/images/ai-gen/stop", s, b, expect=expect_400_or_ok)


def audit_video_bind():
    m = "视频绑定"
    s, b = http("GET", "/api/video-bind/status")
    record(m, "任务状态", "GET", "/api/video-bind/status", s, b, expect=expect_ok)

    s, b = http("GET", "/api/video-bind/new-links-preview")
    record(m, "新发链接预览", "GET", "/api/video-bind/new-links-preview", s, b, expect=expect_404_or_ok)

    for action in ["stop", "pause", "resume"]:
        s, b = http("POST", f"/api/video-bind/{action}", {})
        record(m, f"空闲时{action}", "POST", f"/api/video-bind/{action}", s, b, expect=expect_400_or_ok)


def audit_tasks():
    m = "任务管理"
    s, b = http("GET", "/api/tasks/list")
    record(m, "任务列表", "GET", "/api/tasks/list", s, b, expect=expect_ok)


def audit_membership():
    m = "会员系统"
    # Admin reads
    admin_reads = [
        ("/api/membership/admin/users?limit=20", "用户列表"),
        ("/api/membership/admin/agents?limit=20", "节点列表"),
        ("/api/membership/admin/telemetry/keywords?limit=20", "关键词回传"),
        ("/api/membership/admin/withdraw/list?limit=50", "提现列表"),
        ("/api/membership/admin/dashboard?days=30", "管理仪表盘"),
    ]
    for path, name in admin_reads:
        s, b = http("GET", path)
        record(m, name, "GET", path, s, b, expect=expect_ok)

    # Create test user CRUD
    ts = int(time.time())
    username = f"audit_user_{ts}"
    password = "AuditPass123!"
    s, b = http(
        "POST",
        "/api/membership/admin/users/create",
        {
            "username": username,
            "password": password,
            "real_name": "审计测试",
            "phone": "",
            "points_balance": 100,
            "trial_days": 30,
        },
    )
    record(m, "创建测试用户", "POST", "/api/membership/admin/users/create", s, b, expect=expect_ok)
    user_id = None
    if isinstance(b, dict):
        user_id = (b.get("data") or {}).get("user_id") or (b.get("data") or {}).get("id")

    if not user_id:
        s2, b2 = http("GET", "/api/membership/admin/users?limit=200")
        if isinstance(b2, dict):
            for u in (b2.get("data") or b2.get("users") or []):
                if str(u.get("username")) == username:
                    user_id = u.get("id") or u.get("user_id")
                    break

    if user_id:
        s, b = http(
            "POST",
            "/api/membership/admin/users/update",
            {"user_id": user_id, "points_balance": 150},
        )
        record(m, "更新测试用户积分", "POST", "/api/membership/admin/users/update", s, b, expect=expect_ok)

        s, b = http(
            "POST",
            "/api/membership/admin/users/control",
            {"user_id": user_id, "mode": "force_allow", "note": "audit"},
        )
        record(m, "控制测试用户", "POST", "/api/membership/admin/users/control", s, b, expect=expect_ok)

        s, b = http("POST", "/api/membership/admin/users/delete", {"user_id": user_id})
        record(m, "删除测试用户", "POST", "/api/membership/admin/users/delete", s, b, expect=expect_ok)
    else:
        report.add(
            module=m,
            name="更新/删除测试用户",
            method="POST",
            path="/api/membership/admin/users/*",
            status=0,
            ok=False,
            note="创建用户后未拿到 user_id",
        )

    # Agent register + heartbeat
    agent_id = f"audit-agent-{ts}"
    s, b = http(
        "POST",
        "/api/membership/agent/register",
        {"agent_id": agent_id, "client_name": "audit", "machine_id": "m1", "app_version": "1.0"},
    )
    record(m, "注册节点", "POST", "/api/membership/agent/register", s, b, expect=expect_ok)

    s, b = http("POST", "/api/membership/agent/heartbeat", {"agent_id": agent_id, "status": "online"})
    record(m, "节点心跳", "POST", "/api/membership/agent/heartbeat", s, b, expect=expect_ok)

    s, b = http("GET", f"/api/membership/agent/policy?agent_id={urllib.parse.quote(agent_id)}")
    record(m, "读取节点策略", "GET", "/api/membership/agent/policy", s, b, expect=expect_ok)

    s, b = http(
        "POST",
        "/api/membership/admin/agents/policy",
        {"agent_id": agent_id, "policy": {"enabled": True, "note": "audit"}},
    )
    record(m, "更新节点策略", "POST", "/api/membership/admin/agents/policy", s, b, expect=expect_ok)

    # Telemetry batch delete endpoint exists
    s, b = http("POST", "/api/membership/admin/telemetry/keywords/batch/delete", {"report_ids": []})
    record(m, "批量删除关键词回传(空)", "POST", "/api/membership/admin/telemetry/keywords/batch/delete", s, b, expect=expect_ok)


def audit_auth_flow():
    m = "认证流程"
    ts = int(time.time())
    username = f"auth_audit_{ts}"
    password = "AuthAudit123!"

    s, b = http("POST", "/api/membership/auth/register", {"username": username, "password": password}, admin=False)
    record(m, "用户注册", "POST", "/api/membership/auth/register", s, b, expect=expect_ok)

    s, b = http("POST", "/api/membership/auth/login", {"username": username, "password": password}, admin=False)
    record(m, "用户登录", "POST", "/api/membership/auth/login", s, b, expect=expect_ok)
    token = ""
    if isinstance(b, dict):
        token = (b.get("data") or {}).get("token") or b.get("token") or ""

    if token:
        s, b = http("GET", "/api/membership/me", admin=False, token=token)
        record(m, "读取当前用户", "GET", "/api/membership/me", s, b, expect=expect_ok)

        s, b = http("GET", "/api/membership/points/ledger?limit=5", admin=False, token=token)
        record(m, "积分流水", "GET", "/api/membership/points/ledger", s, b, expect=expect_ok)

        s, b = http("GET", "/api/config/", admin=False, token=token)
        record(m, "会员 token 访问配置", "GET", "/api/config/", s, b, expect=expect_ok)
    else:
        report.add(module=m, name="会员 token 后续测试", method="-", path="-", status=0, ok=False, note="登录未返回 token")


def check_code_issues():
    """Static code checks for known issues."""
    issues = []

    # Duplicate route in upload_router
    upload_path = (
        r"d:\桌面\ali-auto-publish-fullstack (3)\ali-auto-publish-fullstack\backend\app\api\upload_router.py"
    )
    with open(upload_path, "r", encoding="utf-8") as f:
        content = f.read()
    count = content.count('@router.get("/optimize/list")')
    if count > 1:
        issues.append(
            {
                "severity": "medium",
                "module": "自动发品",
                "issue": f"upload_router.py 中 /optimize/list 路由重复定义 {count} 次，后者会覆盖前者",
                "file": "backend/app/api/upload_router.py",
            }
        )

    return issues


def main():
    print("=== API Audit Start ===")
    print(f"Target: {BASE}")

    audit_config()
    audit_upload()
    audit_analysis()
    audit_data()
    audit_images()
    audit_video_bind()
    audit_tasks()
    audit_membership()
    audit_auth_flow()

    static_issues = check_code_issues()
    summary = report.summary()

    print("\n=== Results by Module ===")
    for mod, counts in sorted(summary["by_module"].items()):
        print(f"  {mod}: pass={counts['pass']} fail={counts['fail']}")

    print(f"\n=== Total: {summary['passed']}/{summary['total']} passed ===")

    if summary["failures"]:
        print("\n=== Failures ===")
        for f in summary["failures"]:
            print(f"  [{f.module}] {f.name} -> HTTP {f.status} | {f.note} | {f.detail}")

    if static_issues:
        print("\n=== Static Code Issues ===")
        for i in static_issues:
            print(f"  [{i['severity']}] {i['module']}: {i['issue']}")

    out_path = r"d:\桌面\ali-auto-publish-fullstack (3)\ali-auto-publish-fullstack\backend\scripts\api_audit_report.json"
    with open(out_path, "w", encoding="utf-8") as fp:
        json.dump(
            {
                "summary": {k: v for k, v in summary.items() if k != "failures"},
                "failures": [f.__dict__ for f in summary["failures"]],
                "static_issues": static_issues,
            },
            fp,
            ensure_ascii=False,
            indent=2,
        )
    print(f"\nReport saved: {out_path}")

    return 0 if not summary["failures"] and not static_issues else 1


if __name__ == "__main__":
    sys.exit(main())

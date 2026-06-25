# -*- coding: utf-8 -*-
"""Full acceptance: apply scan with platform sync (requires login)."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

TEST_URL = (
    "https://post.alibaba.com/product/publish.htm?"
    "pubType=similarPost&itemId=1601212500292&behavior=copyNew"
)
TEST_GROUP = "\u590d\u5236\u53d1\u54c1\u9a8c\u6536"


def main() -> int:
    from app.services.page_scanner.scanner import scan_publish_page
    from app.services.page_scanner.config_bridge import apply_scan_to_config, validate_group_for_publish

    print("=" * 60)
    print("Full bridge acceptance (scan + apply + sync)")
    print("=" * 60)

    scan = scan_publish_page(TEST_URL, probe_buttons=False, wait_seconds=45.0)
    if not scan.get("success"):
        print("FAIL scan:", scan.get("error"))
        return 1

    wf = scan.get("workflows") or []
    print(f"scan ok: elements={scan.get('element_count')} workflows={len(wf)}")

    applied = apply_scan_to_config(
        group_name=TEST_GROUP,
        url=TEST_URL,
        workflows=wf,
        page_type=scan.get("page_type", ""),
        page_type_label=scan.get("page_type_label", ""),
        element_count=scan.get("element_count", 0),
        workflow_count=scan.get("workflow_count", len(wf)),
        sync_platform=True,
    )

    val = validate_group_for_publish(TEST_GROUP)
    checks = [
        ("scan workflows>=8", len(wf) >= 8),
        ("apply success", applied.get("success")),
        ("platform sync ok", applied.get("platform_sync", {}).get("success") is not False),
        ("validate ok", val.get("success")),
        ("attrs>=3", (val.get("attribute_count") or 0) >= 3),
    ]

    for name, ok in checks:
        print(f"[{'PASS' if ok else 'FAIL'}] {name}")

    out = ROOT / "scripts" / "accept_bridge_full_last.json"
    out.write_text(
        json.dumps({"scan": {"element_count": scan.get("element_count"), "workflows": len(wf)}, "apply": applied, "validate": val}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print("ready:", applied.get("ready_for_publish"), "issues:", applied.get("readiness_issues"))
    print("written", out)
    return 0 if all(c[1] for c in checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())

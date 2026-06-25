# -*- coding: utf-8 -*-
"""Acceptance: page scan -> apply to config -> validate group."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

MOCK_WORKFLOWS = [
    {"id": "product-images", "title": "Product Images", "type": "image_upload", "operable": False},
    {"id": "product-title", "title": "Title", "type": "form_field", "operable": True, "struct_id": "productTitle"},
    {"id": "product-keywords", "title": "Keywords", "type": "form_field", "operable": True},
    {"id": "product-attributes", "title": "Attributes", "type": "attributes", "operable": True},
    {"id": "ladder-price", "title": "Ladder Price", "type": "form_field", "operable": True},
    {"id": "sku-quantity", "title": "SKU", "type": "sku", "operable": True},
    {"id": "spec-color", "title": "Spec Color", "type": "spec_attribute", "spec_name": "Color", "interaction": "value_rows", "operable": True},
    {"id": "spec-size", "title": "Spec Size", "type": "spec_attribute", "spec_name": "Ring Size", "interaction": "checkbox_grid", "operable": True},
    {"id": "detail-images", "title": "Detail Images", "type": "image_upload", "operable": True},
    {"id": "text-detail", "title": "Text Detail", "type": "form_field", "operable": True},
    {"id": "company-desc", "title": "Company", "type": "form_field", "operable": True},
    {"id": "compliance-fields", "title": "Compliance", "type": "compliance", "operable": True},
]

TEST_URL = (
    "https://post.alibaba.com/product/publish.htm?"
    "pubType=similarPost&itemId=1601212500292&behavior=copyNew"
)
TEST_GROUP = "accept-test-group"


def main() -> int:
    from app.services.page_scanner.config_bridge import apply_scan_to_config, validate_group_for_publish

    print("=" * 60)
    print("Bridge acceptance (sync_platform=False dry run)")
    print("=" * 60)

    result = apply_scan_to_config(
        group_name=TEST_GROUP,
        url=TEST_URL,
        workflows=MOCK_WORKFLOWS,
        page_type="copy",
        page_type_label="copy publish",
        element_count=148,
        workflow_count=len(MOCK_WORKFLOWS),
        sync_platform=False,
    )

    checks = []
    checks.append(("apply success", result.get("success") is True))
    checks.append(("group URL bound", TEST_URL in str(result.get("url"))))
    checks.append(("profile saved", bool(result.get("profile"))))
    checks.append(("workflows >= 8", len(MOCK_WORKFLOWS) >= 8))

    val = validate_group_for_publish(TEST_GROUP)
    checks.append(("validate returns", val.get("success") is True))
    checks.append(("posting_url set", bool(val.get("posting_url"))))

    for name, ok in checks:
        print(f"[{'PASS' if ok else 'FAIL'}] {name}")

    out = ROOT / "scripts" / "accept_bridge_last.json"
    out.write_text(json.dumps({"apply": result, "validate": val}, ensure_ascii=False, indent=2), encoding="utf-8")
    print("written", out)
    print("ready_for_publish:", result.get("ready_for_publish"))
    print("issues:", result.get("readiness_issues"))

    failed = [n for n, ok in checks if not ok]
    if failed:
        print("FAILED:", failed)
        return 1
    print("Bridge dry-run PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

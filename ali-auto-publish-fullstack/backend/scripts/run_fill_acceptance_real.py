# -*- coding: utf-8 -*-
"""Real fill acceptance: browser login + full fill, NO submit. Browser stays open."""
from __future__ import annotations
import json, sys, time
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
KEEP_OPEN_SEC = 180

def main() -> int:
    from app.core.settings import get_config
    from app.services.upload_service import (
        get_available_products_list,
        load_titles_from_excel,
        load_keywords_from_excel,
    )
    from app.services.automation.browser_manager import BrowserManager
    from app.services.automation.product_publisher import publish_single_product
    from app.services.automation.attribute_filler import verify_filled_attributes
    from app.services.automation.spec_selector import verify_filled_specs
    from app.services.automation.detail_filler import verify_detail_uploads

    cfg = get_config()
    avail = get_available_products_list()
    if not avail:
        print("FAIL: no products"); return 1
    product = avail[0]
    pid = product.get("pid")
    titles_by_scene = load_titles_from_excel()
    scene = product.get("title_scene")
    pairs = titles_by_scene.get(scene) or []
    if not pairs:
        print("FAIL: no titles for scene", scene); return 1
    main_title, sub_title = pairs[0]["main"], pairs[0]["sub"]
    keywords = load_keywords_from_excel()
    main_dir = str(Path(cfg.paths.main_image_dir) / str(pid))
    resolved_group = product.get("category") or ""
    cat_norm = "".join(c for c in resolved_group.lower() if c.isalnum())
    for g in (cfg.group_urls.group_url_map or {}):
        if "".join(c for c in g.lower() if c.isalnum()) == cat_norm:
            resolved_group = g
            break

    print("\n>>> 即将打开 Chrome，请在 10 分钟内完成阿里巴巴登录 <<<\n")
    print("REAL FILL ACCEPTANCE (skip submit)")
    print(f"product={pid} group={resolved_group} (file={product.get('category')})")
    print(f"main_dir={main_dir}")
    print("\n>>> 即将打开 Chrome，请在 10 分钟内完成阿里巴巴登录 <<<\n"); print("=" * 60)

    browser = BrowserManager()
    if not browser.setup():
        print("FAIL: browser setup"); return 1
    try:
        logged_in = browser.login(manual_wait_seconds=600)
    except Exception as exc:
        print("FAIL: login error:", exc)
        return 1
    if not logged_in:
        print("FAIL: login timeout - complete Alibaba login in Chrome within 10 min")
        return 1

    started = time.time()
    ok, _ = publish_single_product(
        browser=browser,
        product=product,
        main_title=main_title,
        sub_title=sub_title,
        keywords=keywords,
        cfg=cfg,
        task=None,
        skip_submit=True,
    )
    elapsed = round(time.time() - started, 1)

    planned = {}
    try:
        from app.services.automation.attribute_filler import fill_all_attributes_with_diff
    except Exception:
        pass

    report = {
        "pid": pid,
        "group": resolved_group,
        "main_dir": main_dir,
        "fill_ok": ok,
        "elapsed_s": elapsed,
        "spec_issues": verify_filled_specs(browser.driver, cfg.attributes, resolved_group, main_dir),
        "detail_issues": verify_detail_uploads(browser.driver, cfg.paths, cfg.detail),
    }
    try:
        from app.services.automation.attribute_filler import verify_filled_attributes
        # planned_attrs captured during publish via logs; post-check all filled attrs on page
        report["attr_issues"] = verify_filled_attributes(browser.driver, cfg.attributes, {})
    except Exception as exc:
        report["attr_issues"] = [f"attr verify error: {exc}"]
    out = ROOT / "scripts" / "real_fill_acceptance_last.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nFill step ok={ok} elapsed={elapsed}s")
    print(f"spec_issues={len(report['spec_issues'])} detail_issues={len(report['detail_issues'])} attr_issues={len(report.get('attr_issues') or [])}")
    for line in report.get("attr_issues") or []:
        print("  [attr]", line)
    for line in report["spec_issues"]:
        print("  [spec]", line)
    for line in report["detail_issues"]:
        print("  [detail]", line)
    print(f"\nReport: {out}")
    print(f"Browser stays open {KEEP_OPEN_SEC}s for visual check...")
    time.sleep(KEEP_OPEN_SEC)
    try:
        browser.quit()
    except Exception:
        pass
    print("DONE")
    return 0 if ok else 1

if __name__ == "__main__":
    raise SystemExit(main())


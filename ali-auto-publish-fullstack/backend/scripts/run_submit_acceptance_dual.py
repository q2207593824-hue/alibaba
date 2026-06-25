# -*- coding: utf-8 -*-
"""Dual submit acceptance: blank page + copy page, one product each."""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

BLANK_URL = "https://post.alibaba.com/product/publish.htm?from=common&catId=201650701"
COPY_URL = (
    "https://post.alibaba.com/product/publish.htm?"
    "spm=a2700.micro_product_manager.0.0.5d083e5fuH2w2X&pubType=similarPost&"
    "itemId=1601823011019&behavior=copyNew"
)

RUNS = [
    {"mode": "blank", "url": BLANK_URL, "product_index": 0},
    {"mode": "copy_post", "url": COPY_URL, "product_index": 1},
]


def _resolve_group(product: dict, cfg) -> str:
    resolved = product.get("category") or ""
    cat_norm = "".join(c for c in resolved.lower() if c.isalnum())
    for g in (cfg.group_urls.group_url_map or {}):
        if "".join(c for c in g.lower() if c.isalnum()) == cat_norm:
            return g
    return resolved


def main() -> int:
    from app.core.settings import get_config
    from app.services.upload_service import (
        get_available_products_list,
        load_keywords_from_excel,
        load_titles_from_excel,
        load_used_titles,
        save_published_product,
        save_used_title,
    )
    from app.services.automation.browser_manager import BrowserManager
    from app.services.automation.product_publisher import publish_single_product

    cfg = get_config()
    avail = get_available_products_list()
    if len(avail) < 2:
        print(f"FAIL: need >=2 products, got {len(avail)}")
        return 1

    titles_by_scene = load_titles_from_excel()
    keywords = load_keywords_from_excel()
    used_titles = load_used_titles()

    print("\n>>> SUBMIT ACCEPTANCE: blank + copy (2 products) <<<")
    print(f">>> Login in Chrome within 10 minutes <<<\n")

    browser = BrowserManager()
    if not browser.setup():
        print("FAIL: browser setup")
        return 1
    try:
        if not browser.login(manual_wait_seconds=600):
            print("FAIL: login timeout")
            return 1
    except Exception as exc:
        print("FAIL: login error:", exc)
        return 1

    report = {
        "started_at": datetime.now().isoformat(timespec="seconds"),
        "runs": [],
        "all_ok": True,
    }

    for run in RUNS:
        idx = run["product_index"]
        product = avail[idx]
        pid = product.get("pid")
        scene = product.get("title_scene")
        pairs = [
            p for p in (titles_by_scene.get(scene) or [])
            if p.get("main") not in used_titles
        ]
        if not pairs:
            pairs = titles_by_scene.get(scene) or []
        if not pairs:
            print(f"FAIL: no titles for {pid} scene={scene}")
            report["all_ok"] = False
            report["runs"].append({"mode": run["mode"], "pid": pid, "error": "no titles"})
            continue

        main_title, sub_title = pairs[0]["main"], pairs[0]["sub"]
        resolved_group = _resolve_group(product, cfg)
        group_map = cfg.group_urls.group_url_map or {}
        group_map[resolved_group] = run["url"]

        print("=" * 60)
        print(f"[{run['mode']}] pid={pid} group={resolved_group}")
        print(f"url={run['url']}")
        print(f"title={main_title}")
        print("=" * 60)

        started = time.time()
        ok, primary_id = publish_single_product(
            browser=browser,
            product=product,
            main_title=main_title,
            sub_title=sub_title,
            keywords=keywords,
            cfg=cfg,
            task=None,
            skip_submit=False,
        )
        elapsed = round(time.time() - started, 1)

        entry = {
            "mode": run["mode"],
            "url": run["url"],
            "pid": pid,
            "group": resolved_group,
            "main_title": main_title,
            "submit_ok": bool(ok),
            "primary_id": primary_id,
            "elapsed_s": elapsed,
        }
        report["runs"].append(entry)

        status = "OK" if ok else "FAIL"
        print(f"\n>>> [{run['mode']}] {status} primaryId={primary_id} elapsed={elapsed}s\n")

        if ok:
            save_published_product(pid)
            save_used_title(main_title)
            used_titles.add(main_title)
        else:
            report["all_ok"] = False

        if run != RUNS[-1]:
            print("Waiting 15s before next product...")
            time.sleep(15)

    report["finished_at"] = datetime.now().isoformat(timespec="seconds")
    out = ROOT / "scripts" / "submit_acceptance_dual.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n========== SUBMIT ACCEPTANCE SUMMARY ==========")
    for r in report["runs"]:
        print(
            f"  {r.get('mode')}: pid={r.get('pid')} submit_ok={r.get('submit_ok')} "
            f"primaryId={r.get('primary_id')} elapsed={r.get('elapsed_s')}s"
        )
    print(f"Report: {out}")
    print("Browser stays open 120s for check...")
    time.sleep(120)
    try:
        browser.quit()
    except Exception:
        pass
    print("DONE")
    return 0 if report["all_ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

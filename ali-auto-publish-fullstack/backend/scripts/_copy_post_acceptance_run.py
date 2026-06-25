# -*- coding: utf-8 -*-
"""Copy-post fill acceptance (no submit). URL override in memory only."""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Tuple

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

URL_CASES: List[Tuple[str, str, str]] = [
    (
        "copy_post",
        "复制发品",
        "https://post.alibaba.com/product/publish.htm?"
        "spm=a2747.product_manager.0.0.5a3e71d2fAJ4jx&pubType=similarPost&"
        "itemId=1601823011019&behavior=copyNew",
    ),
    (
        "blank_cat",
        "空白类目发品",
        "https://post.alibaba.com/product/publish.htm?from=common&catId=201650701",
    ),
]
KEEP_OPEN_SEC = int(os.environ.get("ACCEPTANCE_KEEP_OPEN_SEC", "15"))
LOGIN_WAIT_SEC = int(os.environ.get("ACCEPTANCE_LOGIN_WAIT_SEC", "600"))


_SKIP_TIMING_KEYS = {
    "1_打开页面", "2_上传图片", "3_标题关键词", "4_规格选择",
    "5_价格库存", "6_属性填写", "7_详情模块", "8_规格补全",
    "9_最终验收", "9_提交发布", "总计",
    "attr_fill_report", "planned_attrs", "attr_value_audit",
}


def _fmt_vals(values: Any) -> str:
    if not values:
        return "[]"
    s = str(list(values))
    return s if len(s) <= 40 else s[:37] + "..."


def _print_step_timings(label: str, step_timings: dict) -> None:
    print("\n" + "=" * 60)
    print(f"{label} — 各步骤耗时（秒）")
    print("=" * 60)
    for key in (
        "1_打开页面", "2_上传图片", "3_标题关键词", "4_规格选择",
        "5_价格库存", "6_属性填写", "7_详情模块", "8_规格补全",
        "9_最终验收", "9_提交发布", "总计",
    ):
        val = step_timings.get(key)
        if isinstance(val, (int, float)):
            print(f"  {key:16s} {val:>8.2f}s")
    for key, val in step_timings.items():
        if key in _SKIP_TIMING_KEYS:
            continue
        if isinstance(val, (int, float)):
            print(f"  {key:16s} {val:>8.2f}s")
    print("=" * 60)


def _print_attr_fill_report(report: List[Dict[str, Any]]) -> None:
    if not report:
        print("\n(无属性填写明细)")
        return
    print("\n" + "-" * 60)
    print("属性填写明细（逐字段耗时与状态）")
    print("-" * 60)
    print(
        f"{'属性':<22} {'阶段':<12} {'类型':<14} {'耗时s':>7}  "
        f"{'填写':<8} {'验收':<8} 值"
    )
    print("-" * 60)
    first_pass_total = 0.0
    refill_total = 0.0
    for rec in report:
        name = str(rec.get("attr_name") or "")[:20]
        phase = str(rec.get("phase") or "")
        stype = str(rec.get("select_type") or "")[:12]
        dur = float(rec.get("duration_s") or 0)
        status = str(rec.get("status") or "")
        verify = str(rec.get("verify") or "")
        values = rec.get("values") or []
        val_preview = str(values)[:36] + ("..." if len(str(values)) > 36 else "")
        if phase == "first_pass":
            first_pass_total += dur
        elif phase == "refill":
            refill_total += dur
        print(
            f"{name:<22} {phase:<12} {stype:<14} {dur:>7.3f}  "
            f"{status:<8} {verify:<8} {val_preview}"
        )
    print("-" * 60)
    print(
        f"首轮填写合计: {first_pass_total:.3f}s | 重填合计: {refill_total:.3f}s | "
        f"记录条数: {len(report)}"
    )


def _print_attr_value_audit(audit: List[Dict[str, Any]]) -> None:
    if not audit:
        print("\n(无属性值审计)")
        return
    print("\n" + "-" * 60)
    print("属性值审计（原值 → 设定值 → 填后值）")
    print("-" * 60)
    print(f"{'属性':<20} {'原值':<28} {'设定值':<28} {'填后值':<28} 一致")
    print("-" * 60)
    ok_n = 0
    for row in audit:
        name = str(row.get("attr_name") or "")[:18]
        orig = _fmt_vals(row.get("original_values"))
        plan = _fmt_vals(row.get("planned_values"))
        fin = _fmt_vals(row.get("final_values"))
        match = row.get("match")
        if match is True:
            ok_n += 1
        match_s = "Y" if match is True else ("N" if match is False else "-")
        print(f"{name:<20} {orig:<28} {plan:<28} {fin:<28} {match_s}")
    print("-" * 60)
    print(f"审计 {len(audit)} 项，与设定值一致 {ok_n} 项")


def main() -> int:
    from app.core.settings import get_config
    from app.services.upload_service import (
        get_available_products_list,
        load_keywords_from_excel,
        load_titles_from_excel,
    )
    from app.services.automation.browser_manager import BrowserManager
    from app.services.automation.product_publisher import publish_single_product
    from app.services.automation.attribute_filler import verify_filled_attributes
    from app.services.automation.spec_selector import verify_filled_specs
    from app.services.automation.detail_filler import verify_detail_uploads

    cfg = get_config()
    avail = get_available_products_list()
    if not avail:
        print("FAIL: no products")
        return 1

    product = None
    for p in avail:
        cat = str(p.get("category") or "").upper()
        if "CHAMPIONSHIP" in cat or "RING" in cat:
            product = p
            break
    if product is None:
        product = avail[0]
    pid = product.get("pid")
    titles_by_scene = load_titles_from_excel()
    scene = product.get("title_scene")
    pairs = titles_by_scene.get(scene) or []
    if not pairs:
        print("FAIL: no titles for scene", scene)
        return 1

    main_title, sub_title = pairs[0]["main"], pairs[0]["sub"]
    keywords = load_keywords_from_excel()
    main_dir = str(Path(cfg.paths.main_image_dir) / str(pid))
    resolved_group = product.get("category") or ""
    cat_norm = "".join(c for c in resolved_group.lower() if c.isalnum())
    group_map = cfg.group_urls.group_url_map or {}
    for g in group_map:
        if "".join(c for c in g.lower() if c.isalnum()) == cat_norm:
            resolved_group = g
            break

    print("\n>>> 请在 Chrome 中完成阿里巴巴登录（最多 {} 秒）<<<\n".format(LOGIN_WAIT_SEC))
    print(f"product={pid} group={resolved_group}")
    print(f"main_dir={main_dir}")
    print(f"将依次验收 {len(URL_CASES)} 个链接")

    browser = BrowserManager()
    if not browser.setup():
        print("FAIL: browser setup")
        return 1
    try:
        logged_in = browser.login(manual_wait_seconds=LOGIN_WAIT_SEC)
    except Exception as exc:
        print("FAIL: login error:", exc)
        return 1
    if not logged_in:
        print("FAIL: login timeout")
        return 1

    reports: List[Dict[str, Any]] = []
    all_ok = True
    group_map = cfg.group_urls.group_url_map or {}

    for mode, mode_label, post_url in URL_CASES:
        print("\n" + "#" * 60)
        print(f"开始验收: {mode_label}")
        print(f"url={post_url}")
        print("#" * 60)
        group_map[resolved_group] = post_url

        step_timings: dict = {}
        started = time.time()
        try:
            ok, _ = publish_single_product(
                browser=browser,
                product=product,
                main_title=main_title,
                sub_title=sub_title,
                keywords=keywords,
                cfg=cfg,
                task=None,
                skip_submit=True,
                step_timings=step_timings,
            )
        except Exception as exc:
            ok = False
            reports.append({
                "mode": mode, "mode_label": mode_label, "url": post_url,
                "fill_ok": False, "error": str(exc),
            })
            print(f"FAIL [{mode_label}]: {exc}")
            all_ok = False
            continue

        elapsed = round(time.time() - started, 1)
        planned_attrs = step_timings.get("planned_attrs") or {}
        attr_fill_report = step_timings.get("attr_fill_report") or []
        attr_value_audit = step_timings.get("attr_value_audit") or []
        report = {
            "mode": mode,
            "mode_label": mode_label,
            "url": post_url,
            "pid": pid,
            "group": resolved_group,
            "main_dir": main_dir,
            "fill_ok": ok,
            "elapsed_s": elapsed,
            "step_timings_s": {
                k: v for k, v in step_timings.items()
                if k not in ("attr_fill_report", "planned_attrs", "attr_value_audit")
            },
            "attr_fill_report": attr_fill_report,
            "attr_value_audit": attr_value_audit,
            "planned_attrs": planned_attrs,
            "spec_issues": verify_filled_specs(browser.driver, cfg.attributes, resolved_group, main_dir),
            "detail_issues": verify_detail_uploads(browser.driver, cfg.paths, cfg.detail),
            "attr_issues": verify_filled_attributes(
                browser.driver, cfg.attributes, planned_attrs
            ),
        }
        reports.append(report)
        if not ok:
            all_ok = False

        print(f"\nFill step ok={ok} elapsed={elapsed}s")
        _print_step_timings(mode_label, step_timings)
        _print_attr_fill_report(attr_fill_report)
        _print_attr_value_audit(attr_value_audit)
        print(
            f"spec_issues={len(report['spec_issues'])} "
            f"detail_issues={len(report['detail_issues'])} "
            f"attr_issues={len(report.get('attr_issues') or [])}"
        )
        for line in report.get("attr_issues") or []:
            print("  [attr]", line)
        for line in report["spec_issues"]:
            print("  [spec]", line)
        for line in report["detail_issues"]:
            print("  [detail]", line)

    combined = {"pid": pid, "group": resolved_group, "runs": reports, "all_ok": all_ok}
    out = ROOT / "scripts" / "dual_url_acceptance_last.json"
    out.write_text(json.dumps(combined, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n" + "=" * 60)
    print("双链接验收汇总")
    print("=" * 60)
    for rep in reports:
        label = rep.get("mode_label") or rep.get("mode")
        total = (rep.get("step_timings_s") or {}).get("总计", "-")
        print(f"  [{label}] ok={rep.get('fill_ok')} elapsed={rep.get('elapsed_s', '-')}s total={total}s")
    print(f"\nReport: {out}")
    print(f"Browser stays open {KEEP_OPEN_SEC}s ...")
    time.sleep(KEEP_OPEN_SEC)
    try:
        browser.quit()
    except Exception:
        pass
    print("DONE")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

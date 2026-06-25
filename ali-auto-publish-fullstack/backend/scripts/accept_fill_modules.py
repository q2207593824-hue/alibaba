# -*- coding: utf-8 -*-
from __future__ import annotations
import json, os, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
TEST_GROUP = "CHAMPIONSHIP RINGS"

def main():
    from app.core.settings import get_config
    from app.services.automation.spec_selector import resolve_specs_for_group, _list_spec_image_values, _is_sale_attribute_enabled, _spec_interaction
    from app.services.upload_service import get_available_products_list
    cfg = get_config()
    report = {"group": TEST_GROUP, "sections": []}

  # --- specs ---
    specs = resolve_specs_for_group(cfg.attributes, TEST_GROUP) or {}
    spec_rows = []
    for name, spec in specs.items():
        row = {
            "name": name,
            "container_id": spec.container_id or "",
            "enable_sale_attribute": spec.enable_sale_attribute,
            "enable_spec_image": getattr(spec, "enable_spec_image", False),
            "default_values": list(spec.default_values or []),
            "values_pool_len": len(spec.values_pool or []),
            "interaction": _spec_interaction(spec),
        }
        issues = []
        if _is_sale_attribute_enabled(name, spec) and not row["container_id"]:
            issues.append("已启用但 container_id 为空")
        if row["enable_spec_image"] and not row["default_values"]:
            issues.append("开启规格图但无 default_values（将扫图片目录）")
        row["issues"] = issues
        spec_rows.append(row)
    report["sections"].append({"module": "spec", "items": spec_rows})

  # --- attributes ---
    skip = set(cfg.attributes.skip_attrs or [])
    attr_rows = []
    empty_required = []
    for name, item in (cfg.attributes.all_attributes or {}).items():
        if name in skip:
            continue
        pool = [str(v).strip() for v in (item.values or []) if str(v).strip()]
        if not pool and item.type == "required":
            empty_required.append(name)
        if pool:
            attr_rows.append({"name": name, "type": item.type, "values_sample": pool[:3], "pool_len": len(pool)})
    report["sections"].append({"module": "attribute", "empty_required": empty_required, "configured_count": len(attr_rows)})

  # --- paths / product ---
    paths = cfg.paths
    path_checks = {}
    for label, p in [
        ("scene", paths.detail_scene_image_dir),
        ("detail", paths.detail_detail_image_dir),
        ("company", paths.detail_company_image_root_dir),
        ("main", paths.main_image_dir),
        ("primary", paths.primary_image_dir),
    ]:
        p = str(p or "").strip()
        if not p:
            path_checks[label] = {"ok": False, "msg": "未配置"}
        elif not os.path.isdir(p):
            path_checks[label] = {"ok": False, "msg": f"不存在: {p}"}
        else:
            n = len([f for f in os.listdir(p) if f.lower().endswith((".jpg",".jpeg",".png",".webp"))])
            path_checks[label] = {"ok": True, "path": p, "image_files": n}
    report["sections"].append({"module": "paths", "checks": path_checks})

    avail = get_available_products_list() or []
    sample = avail[0] if avail else {}
    pid = sample.get("pid", "")
    main_dir = os.path.join(str(paths.main_image_dir or ""), str(pid)) if pid else ""
    color_spec = specs.get("颜色")
    if color_spec and getattr(color_spec, "enable_spec_image", False) and main_dir:
        sub = str(getattr(color_spec, "image_subdir", "") or "SKU")
        folder = os.path.join(main_dir, sub)
        vals = _list_spec_image_values(main_dir, sub)
        report["sections"].append({
            "module": "spec_images",
            "pid": pid,
            "folder": folder,
            "exists": os.path.isdir(folder),
            "scanned_colors": vals,
        })

    out = ROOT / "scripts" / "accept_fill_modules_last.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    fails = 0
    warns = 0
    print("=" * 60)
    print("填入模块配置验收:", TEST_GROUP)
    print("=" * 60)
    for s in spec_rows:
        flag = "WARN" if s["issues"] else "OK"
        if s["issues"]:
            warns += 1
        print(f"[{flag}] 规格 {s['name']}: container={s['container_id']} sale={s['enable_sale_attribute']} spec_img={s['enable_spec_image']} defaults={s['default_values']}")
        for i in s["issues"]:
            print(f"       ! {i}")
    print(f"\n属性: 已配置 {len(attr_rows)} 个, 必填但空值池 {len(empty_required)} 个")
    if empty_required:
        warns += 1
        print("  空值池必填:", ", ".join(empty_required[:15]), ("..." if len(empty_required)>15 else ""))
    print("\n路径:")
    for k, v in path_checks.items():
        st = "OK" if v.get("ok") else "FAIL"
        if not v.get("ok"):
            fails += 1
        print(f"  [{st}] {k}: {v}")
    if pid:
        print(f"\n样本产品 pid={pid} main_dir={main_dir}")
    print(f"\n报告已写入 {out}")
    print("SUMMARY fail=", fails, "warn=", warns)
    return 1 if fails else 0

if __name__ == "__main__":
    raise SystemExit(main())
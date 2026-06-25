# -*- coding: utf-8 -*-
"""Apply page scan workflows to product config for auto-publish."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from app.core.logger import setup_logger
from app.core.settings import (
    ComplianceFieldSnapshot,
    PageScanProfile,
    PageScanWorkflowSnapshot,
    PublishFieldRequirement,
    SpecificationItemConfig,
    config_manager,
    get_config,
)

logger = setup_logger("page_scan_config_bridge")

_REQUIRED_WORKFLOW_IDS = {
    "product-images",
    "product-title",
    "product-keywords",
    "product-attributes",
    "ladder-price",
}

# workflow_id -> (config_key, category, label)
_WORKFLOW_CONFIG_BINDINGS: Dict[str, List[Tuple[str, str, str]]] = {
    "product-images": [
        ("paths.primary_image_dir", "upload", "首图目录"),
        ("paths.main_image_dir", "upload", "主图目录"),
    ],
    "detail-images": [
        ("paths.detail_scene_image_dir", "upload", "详情-场景图目录"),
        ("paths.detail_detail_image_dir", "upload", "详情-细节图目录"),
    ],
    "text-detail": [
        ("detail.selling_points_excel", "upload", "卖点 Excel"),
    ],
    "company-desc": [
        ("paths.detail_company_intro_file", "text", "公司介绍文本"),
    ],
}

_COMPLIANCE_CONFIG_BINDINGS: Dict[str, Tuple[str, str]] = {
    "国别化阶梯价": ("compliance.country_ladder_price", "compliance"),
    "美国HS编码": ("compliance.us_hs_code", "compliance"),
    "体积与重量": ("compliance.package_volume_weight", "compliance"),
    "样品SKU": ("compliance.sample_sku", "compliance"),
    "产品图片": ("paths.primary_image_dir", "upload"),
}


def _get_config_value(cfg, dot_key: str) -> str:
    parts = dot_key.split(".")
    obj = cfg
    for part in parts:
        obj = getattr(obj, part, None)
        if obj is None:
            return ""
    return str(obj or "").strip()


def _build_field_requirements(cfg, workflows: List[Dict[str, Any]]) -> List[PublishFieldRequirement]:
    """从扫描 workflows 推导必填项与路径配置需求（属性/规格由平台同步单独处理）。"""
    reqs: List[PublishFieldRequirement] = []
    seen: set = set()

    def add(
        workflow_id: str,
        label: str,
        category: str,
        config_key: str,
        *,
        required: bool = True,
    ) -> None:
        key = (workflow_id, config_key, label)
        if key in seen:
            return
        seen.add(key)
        val = _get_config_value(cfg, config_key) if config_key else ""
        configured = bool(val) if category in ("upload", "text") else category == "compliance"
        reqs.append(
            PublishFieldRequirement(
                workflow_id=workflow_id,
                label=label,
                category=category,
                config_key=config_key,
                required=required,
                configured=configured,
                current_value=val[:200] if val else "",
            )
        )

    wf_by_id = {str(w.get("id") or ""): w for w in (workflows or []) if isinstance(w, dict)}

    for wf_id in ("product-attributes",):
        if wf_id in wf_by_id:
            add(wf_id, "产品属性", "form", "attributes.all_attributes", required=True)

    for wf in workflows or []:
        if not isinstance(wf, dict):
            continue
        wf_id = str(wf.get("id") or "")
        if wf.get("type") == "spec_attribute":
            spec_name = str(wf.get("spec_name") or wf.get("title") or "").replace("商品规格 - ", "")
            if spec_name:
                add(
                    wf_id,
                    f"规格-{spec_name}",
                    "form",
                    f"attributes.specifications_by_group",
                    required=True,
                )

    for wf_id, bindings in _WORKFLOW_CONFIG_BINDINGS.items():
        if wf_id not in wf_by_id:
            continue
        for config_key, category, label in bindings:
            add(wf_id, label, category, config_key, required=True)

    comp = wf_by_id.get("compliance-fields") or {}
    for field_name in comp.get("fields") or comp.get("required_fields") or []:
        binding = _COMPLIANCE_CONFIG_BINDINGS.get(str(field_name))
        if binding:
            config_key, category = binding
            add("compliance-fields", str(field_name), category, config_key, required=True)
        else:
            add(
                "compliance-fields",
                str(field_name),
                "compliance",
                f"compliance.{field_name}",
                required=True,
            )

    faq_wf = wf_by_id.get("company-desc")
    if faq_wf:
        add("company-faq", "FAQs 文本", "text", "paths.detail_faq_file", required=False)

    detail_root = wf_by_id.get("detail-images")
    if detail_root:
        add(
            "detail-images",
            "公司介绍图片根目录",
            "upload",
            "paths.detail_company_image_root_dir",
            required=False,
        )

    return reqs


def _extract_compliance_fields(workflows: List[Dict[str, Any]]) -> List[ComplianceFieldSnapshot]:
    from app.services.automation.compliance_filler import is_valid_compliance_label

    for wf in workflows or []:
        if not isinstance(wf, dict) or wf.get("id") != "compliance-fields":
            continue
        items = wf.get("compliance_items") or []
        out: List[ComplianceFieldSnapshot] = []
        seen: set = set()
        for raw in items:
            if not isinstance(raw, dict):
                continue
            label = str(raw.get("label") or "").strip()
            if not label or label in seen or not is_valid_compliance_label(label):
                continue
            seen.add(label)
            out.append(
                ComplianceFieldSnapshot(
                    label=label,
                    struct_id=str(raw.get("struct_id") or ""),
                    source=str(raw.get("source") or ""),
                    required=bool(raw.get("required", True)),
                )
            )
        if out:
            return out
        labels = wf.get("fields") or wf.get("required_fields") or []
        return [
            ComplianceFieldSnapshot(label=str(lb), source="legacy")
            for lb in labels
            if str(lb).strip()
        ]
    return []


def _norm_group(name: str) -> str:
    return str(name or "").strip()


def _workflow_snapshots(workflows: List[Dict[str, Any]]) -> List[PageScanWorkflowSnapshot]:
    out: List[PageScanWorkflowSnapshot] = []
    for wf in workflows or []:
        if not isinstance(wf, dict):
            continue
        wf_id = str(wf.get("id") or "")
        wf_type = str(wf.get("type") or "")
        required = bool(wf.get("required"))
        if not required:
            required = wf_id in _REQUIRED_WORKFLOW_IDS or wf_type == "spec_attribute"
        out.append(
            PageScanWorkflowSnapshot(
                id=wf_id,
                title=str(wf.get("title") or ""),
                type=wf_type,
                operable=bool(wf.get("operable")),
                interaction=str(wf.get("interaction") or ""),
                automation_module=str(wf.get("automation_module") or ""),
                struct_id=str(wf.get("struct_id") or ""),
                spec_name=str(wf.get("spec_name") or ""),
                required=required,
            )
        )
    return out


def assess_publish_readiness(
    cfg,
    group_name: str,
    workflows: List[Dict[str, Any]],
    field_requirements: Optional[List[PublishFieldRequirement]] = None,
) -> Tuple[bool, List[str]]:
    issues: List[str] = []
    group = _norm_group(group_name)
    if not group:
        issues.append("missing group_name")

    url = str((cfg.group_urls.group_url_map or {}).get(group) or "").strip()
    if not url:
        issues.append(f"group '{group}' has no posting URL")

    wf_ids = {str(w.get("id") or "") for w in (workflows or []) if isinstance(w, dict)}
    missing = sorted(_REQUIRED_WORKFLOW_IDS - wf_ids)
    if missing:
        issues.append("missing core workflows: " + ", ".join(missing))

    if len(workflows or []) < 8:
        issues.append(f"too few workflows ({len(workflows or [])})")

    if len(cfg.attributes.all_attributes or {}) < 3:
        issues.append("attributes count < 3, enable platform sync")

    specs = (cfg.attributes.specifications_by_group or {}).get(group) or {}
    if not specs:
        alias = (cfg.attributes.specification_group_alias or {}).get(group)
        if alias:
            specs = (cfg.attributes.specifications_by_group or {}).get(alias) or {}
    if not specs:
        issues.append("no specifications for group, enable platform sync")

    if not str(cfg.paths.primary_image_dir or "").strip():
        issues.append("primary_image_dir not set")
    if not str(cfg.paths.main_image_dir or "").strip():
        issues.append("main_image_dir not set")
    if not str(cfg.paths.title_excel_path or "").strip():
        issues.append("title_excel_path not set")

    reqs = field_requirements
    if reqs is None:
        profile = (cfg.page_scan.profiles_by_group or {}).get(group)
        reqs = list(profile.field_requirements or []) if profile else []
    for req in reqs:
        if req.required and not req.configured and req.category in ("upload", "text"):
            issues.append(f"需配置路径: {req.label} ({req.config_key})")

    return len(issues) == 0, issues


def _merge_spec_hints_from_scan(cfg, group_name: str, workflows: List[Dict[str, Any]]) -> int:
    group = _norm_group(group_name)
    if not group:
        return 0

    specs_by_group = dict(cfg.attributes.specifications_by_group or {})
    group_specs = dict(specs_by_group.get(group) or {})
    updated = 0

    for wf in workflows or []:
        if not isinstance(wf, dict) or wf.get("type") != "spec_attribute":
            continue
        spec_name = str(wf.get("spec_name") or wf.get("title") or "").replace("\u5546\u54c1\u89c4\u683c - ", "").strip()
        if not spec_name or spec_name == "\u89c4\u683c":
            continue
        interaction = str(wf.get("interaction") or "")
        operable = bool(wf.get("operable"))
        existing = group_specs.get(spec_name)
        if existing:
            if interaction and existing.interaction != interaction:
                existing.interaction = interaction
                updated += 1
            if operable and not existing.scan_operable:
                existing.scan_operable = True
                updated += 1
        elif interaction:
            spec_type = "checkbox" if interaction == "checkbox_grid" else "value_rows"
            group_specs[spec_name] = SpecificationItemConfig(
                container_id="",
                values_pool=[],
                default_values=[],
                max_select=2 if interaction == "checkbox_grid" else 1,
                type=spec_type,
                interaction=interaction,
                scan_operable=operable,
            )
            updated += 1

    if group_specs:
        specs_by_group[group] = group_specs
        cfg.attributes.specifications_by_group = specs_by_group
    return updated


def apply_scan_to_config(
    *,
    group_name: str,
    url: str,
    workflows: List[Dict[str, Any]],
    page_type: str = "",
    page_type_label: str = "",
    element_count: int = 0,
    workflow_count: int = 0,
    sync_platform: bool = True,
) -> Dict[str, Any]:
    group = _norm_group(group_name)
    target_url = str(url or "").strip()
    if not group:
        raise ValueError("group_name is required")
    if not target_url.startswith(("http://", "https://")):
        raise ValueError("invalid posting URL")

    cfg = get_config()
    logs: List[str] = []

    group_map = dict(cfg.group_urls.group_url_map or {})
    prev_url = str(group_map.get(group) or "").strip()
    group_map[group] = target_url
    cfg.group_urls.group_url_map = group_map
    logs.append("group URL updated" if prev_url and prev_url != target_url else "group URL bound")

    hint_count = _merge_spec_hints_from_scan(cfg, group, workflows)
    if hint_count:
        logs.append(f"merged {hint_count} spec hints from scan")

    sync_report: Dict[str, Any] = {"skipped": not sync_platform}
    if sync_platform:
        from app.services.page_scanner.platform_sync import sync_group_from_platform

        logs.append("syncing attributes/specs from platform...")
        sync_report = sync_group_from_platform(group_name=group, url=target_url, logs=logs)
        cfg = get_config()
        hint_count += _merge_spec_hints_from_scan(cfg, group, workflows)

    field_requirements = _build_field_requirements(cfg, workflows)
    compliance_fields = _extract_compliance_fields(workflows)
    if compliance_fields:
        logs.append(f"saved {len(compliance_fields)} compliance field(s) for group")
    ready, issues = assess_publish_readiness(cfg, group, workflows, field_requirements)
    profile = PageScanProfile(
        url=target_url,
        group_name=group,
        page_type=str(page_type or ""),
        page_type_label=str(page_type_label or ""),
        scanned_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        element_count=int(element_count or 0),
        workflow_count=int(workflow_count or len(workflows or [])),
        workflows=_workflow_snapshots(workflows),
        field_requirements=field_requirements,
        compliance_fields=compliance_fields,
        ready_for_publish=ready,
        readiness_issues=issues,
    )
    profiles = dict(cfg.page_scan.profiles_by_group or {})
    profiles[group] = profile
    cfg.page_scan.profiles_by_group = profiles
    config_manager.save()
    logs.append("scan profile saved; publish ready=" + ("yes" if ready else "no"))

    return {
        "success": True,
        "group_name": group,
        "url": target_url,
        "ready_for_publish": ready,
        "readiness_issues": issues,
        "workflow_ids": [str(w.get("id") or "") for w in (workflows or []) if isinstance(w, dict)],
        "spec_names": [
            str(w.get("spec_name") or "")
            for w in (workflows or [])
            if isinstance(w, dict) and w.get("type") == "spec_attribute" and w.get("spec_name")
        ],
        "spec_hint_updates": hint_count,
        "platform_sync": sync_report,
        "field_requirements": [r.model_dump() for r in field_requirements],
        "compliance_fields": [c.model_dump() for c in compliance_fields],
        "profile": profile.model_dump(),
        "logs": logs,
    }


def validate_group_for_publish(group_name: str) -> Dict[str, Any]:
    cfg = get_config()
    group = _norm_group(group_name)
    profile = (cfg.page_scan.profiles_by_group or {}).get(group)
    if not profile:
        return {
            "success": False,
            "group_name": group,
            "ready_for_publish": False,
            "issues": [f"no scan profile for group '{group}', apply scan to config first"],
        }
    workflows = [w.model_dump() for w in (profile.workflows or [])]
    ready, issues = assess_publish_readiness(cfg, group, workflows)
    return {
        "success": True,
        "group_name": group,
        "ready_for_publish": ready,
        "issues": issues,
        "profile": profile.model_dump(),
        "attribute_count": len(cfg.attributes.all_attributes or {}),
        "spec_count": len((cfg.attributes.specifications_by_group or {}).get(group) or {}),
        "posting_url": str((cfg.group_urls.group_url_map or {}).get(group) or ""),
    }

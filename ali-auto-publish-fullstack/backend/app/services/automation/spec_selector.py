# -*- coding: utf-8 -*-
"""
规格选择模块（复选框网格 + 颜色/样式输入行与规格图上传）
重构自: main_属性融合.py 中的 select_specifications()
"""
import os
import time
import random
import re
from typing import Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urlparse

from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from app.core.settings import AttributeConfig, SpecificationItemConfig
from app.core.logger import setup_logger

logger = setup_logger("spec_selector")

_IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".JPG", ".JPEG", ".PNG", ".WEBP")


def _norm_text(s: str) -> str:
    return re.sub(r"[\s\-_]+", "", str(s or "").strip()).lower()


def _extract_category_id_from_url(url: str) -> str:
    raw = str(url or "").strip()
    if not raw:
        return ""
    try:
        parsed = urlparse(raw)
        query = parse_qs(parsed.query or "")
        for key in ("catId", "catid", "categoryId", "category_id", "leafCatId", "leafCatid"):
            values = query.get(key) or []
            if values:
                candidate = str(values[0]).strip()
                if candidate.isdigit():
                    return candidate
    except Exception:
        pass
    m = re.search(r"(?:catId|catid|categoryId|leafCatId)=(\d+)", raw, flags=re.IGNORECASE)
    return m.group(1) if m else ""


def resolve_specs_for_group(
    attributes_cfg: AttributeConfig,
    group_name: str,
    category_id: str = "",
    posting_url: str = "",
) -> dict:
    cat_specs = getattr(attributes_cfg, "specifications_by_category_id", {}) or {}
    cid = str(category_id or "").strip() or _extract_category_id_from_url(posting_url)
    if cid and cid in cat_specs:
        hit = cat_specs.get(cid) or {}
        if isinstance(hit, dict) and hit:
            logger.info(f"规格配置命中类目ID: catId={cid} specs={len(hit)}")
            return hit

    specs_by_group = getattr(attributes_cfg, "specifications_by_group", {}) or {}
    alias_map = getattr(attributes_cfg, "specification_group_alias", {}) or {}
    raw_group = str(group_name or "").strip()
    alias_target = str(alias_map.get(raw_group) or "").strip()
    source_group = alias_target if alias_target else raw_group

    if source_group not in specs_by_group:
        target_norm = _norm_text(source_group)
        if target_norm:
            key_map = {_norm_text(k): k for k in specs_by_group.keys()}
            if target_norm in key_map:
                source_group = key_map[target_norm]
            else:
                for nk, original in key_map.items():
                    if target_norm in nk or nk in target_norm:
                        source_group = original
                        break

    if source_group not in specs_by_group and raw_group:
        raw_norm = _norm_text(raw_group)
        alias_norm_map = {_norm_text(k): str(v or "").strip() for k, v in alias_map.items()}
        maybe_alias = alias_norm_map.get(raw_norm, "")
        if maybe_alias and maybe_alias in specs_by_group:
            source_group = maybe_alias

    grouped = specs_by_group.get(source_group)
    if isinstance(grouped, dict) and grouped:
        logger.info(f"规格配置命中组别: request={raw_group} source={source_group} specs={len(grouped)}")
        return grouped

    legacy = getattr(attributes_cfg, "specifications", {}) or {}
    if legacy:
        logger.info(f"规格配置回退全局: request={raw_group} specs={len(legacy)}")
    else:
        logger.warning(f"规格配置未命中任何组别: request={raw_group}")
    return getattr(attributes_cfg, "specifications", {}) or {}


def _spec_interaction(spec: SpecificationItemConfig) -> str:
    typ = str(getattr(spec, "type", "") or "").strip()
    if typ == "checkbox":
        return "checkbox_grid"
    if typ == "value_rows":
        return "value_rows"
    interaction = str(getattr(spec, "interaction", "") or "").strip()
    if interaction:
        return interaction
    return "checkbox_grid"


def _spec_label_aliases(spec_name: str) -> List[str]:
    name = str(spec_name or "").strip()
    aliases = [name] if name else []
    mapping = {
        "颜色": ["颜色", "Color"],
        "戒指尺寸": ["戒指尺寸", "Ring Size"],
        "样式": ["样式", "Style"],
    }
    for key, vals in mapping.items():
        if name == key or key in name:
            aliases.extend(vals)
    return list(dict.fromkeys([a for a in aliases if a]))


def _resolve_sale_attribute_value(spec: SpecificationItemConfig) -> str:
    return str(getattr(spec, "sale_attribute_value", "") or "").strip()


def _legacy_should_enable_sale_attribute(spec_name: str, spec: SpecificationItemConfig) -> bool:
    """旧配置无 enable_sale_attribute 字段时的兼容推断。"""
    if "_规格_p-" in str(spec_name or ""):
        return False
    if str(spec.container_id or "").strip():
        return True
    if _spec_interaction(spec) == "value_rows":
        if bool(getattr(spec, "enable_spec_image", False)):
            return True
        if spec.default_values or spec.values_pool:
            return True
    if _spec_interaction(spec) == "checkbox_grid" and spec.values_pool:
        return True
    return False


def _sale_attr_sort_key(name_spec: Tuple[str, SpecificationItemConfig]) -> Tuple[int, str]:
    name, spec = name_spec
    raw = getattr(spec, "enable_sale_attribute", None)
    if raw is True:
        return (0, name)
    if raw is False:
        return (9, name)
    return (1, name)


def _is_sale_attribute_enabled(spec_name: str, spec: SpecificationItemConfig) -> bool:
    if getattr(spec, "scan_operable", None) is False:
        return False
    raw = getattr(spec, "enable_sale_attribute", None)
    if raw is False:
        return False
    if raw is True:
        return True
    if getattr(spec, "scan_operable", None) is True:
        return True
    return _legacy_should_enable_sale_attribute(spec_name, spec)


def _normalize_image_subdir(image_subdir: str) -> str:
    """规格图子目录；历史配置「颜色」统一映射为 SKU。"""
    sub = str(image_subdir or "").strip()
    if sub in ("颜色", "Color"):
        return "SKU"
    return sub or "SKU"


def _default_image_subdir(attr_name: str) -> str:
    name = str(attr_name or "").strip()
    if name in ("颜色", "Color"):
        return "SKU"
    if name in ("样式", "Style"):
        return "样式"
    return name or "SKU"


def _pick_spec_image_owner(specs: Dict[str, SpecificationItemConfig]) -> str:
    candidates = [
        name
        for name, spec in specs.items()
        if _spec_interaction(spec) == "value_rows" and bool(getattr(spec, "enable_spec_image", False))
    ]
    if not candidates:
        return ""
    for preferred in ("颜色", "Color", "样式", "Style"):
        for name in candidates:
            if name == preferred or preferred in name:
                return name
    return candidates[0]


def _spec_image_subdir_candidates(image_subdir: str) -> List[str]:
    candidates: List[str] = []
    for sub in (
        image_subdir,
        _normalize_image_subdir(image_subdir),
        "SKU",
        "颜色",
        "Color",
    ):
        s = str(sub or "").strip()
        if s and s not in candidates:
            candidates.append(s)
    return candidates


def _resolve_spec_image_path(main_image_dir: str, image_subdir: str, value_name: str) -> str:
    root = str(main_image_dir or "").strip()
    stem = str(value_name or "").strip()
    if not root or not stem:
        return ""
    for sub in _spec_image_subdir_candidates(image_subdir):
        base = os.path.join(root, sub)
        if not base or not os.path.isdir(base):
            continue
        for ext in _IMAGE_EXTS:
            candidate = os.path.join(base, stem + ext)
            if os.path.isfile(candidate):
                return candidate
        try:
            files = os.listdir(base)
        except Exception:
            continue
        stem_lower = stem.lower()
        for fn in files:
            name, ext = os.path.splitext(fn)
            if ext.lower() in {e.lower() for e in _IMAGE_EXTS} and name.lower() == stem_lower:
                return os.path.join(base, fn)
    return ""


def _scan_image_dir(base_dir: str) -> List[str]:
    if not base_dir or not os.path.isdir(base_dir):
        return []
    values: List[str] = []
    seen = set()
    try:
        files = sorted(os.listdir(base_dir))
    except Exception:
        return []
    for fn in files:
        name, ext = os.path.splitext(fn)
        if ext.lower() not in {e.lower() for e in _IMAGE_EXTS}:
            continue
        stem = str(name or "").strip()
        if not stem:
            continue
        key = stem.lower()
        if key in seen:
            continue
        seen.add(key)
        values.append(stem)
    return values


def _list_spec_image_values(main_image_dir: str, image_subdir: str) -> List[str]:
    """从规格图目录扫描图片文件名（不含后缀）作为填充值。"""
    root = str(main_image_dir or "").strip()
    if not root:
        return []
    for sub in _spec_image_subdir_candidates(image_subdir):
        base = os.path.join(root, sub)
        values = _scan_image_dir(base)
        if values:
            logger.info(f"规格图目录命中: {base} → {len(values)} 张")
            return values
    tried = [os.path.join(root, s) for s in _spec_image_subdir_candidates(image_subdir)]
    logger.warning(f"未找到规格图目录（已尝试: {tried}）")
    return []


def _find_sale_attributes_container(driver):
    for selector in ("#struct-saleAttributesItems", ".saleAttributesItems", "#saleAttributesItems"):
        try:
            return WebDriverWait(driver, 5).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, selector))
            )
        except Exception:
            continue
    return None


def _infer_sale_attribute_value(spec: SpecificationItemConfig) -> str:
    raw = _resolve_sale_attribute_value(spec)
    if raw:
        return raw
    cid = str(spec.container_id or "").strip()
    if cid.startswith("p-"):
        return cid[2:]
    return cid


def _normalize_specs_for_run(specs: Dict[str, SpecificationItemConfig]) -> Dict[str, SpecificationItemConfig]:
    """合并动态规格名（如 CHAMPIONSHIP RINGS_规格_p-*）到「样式」，并补全 sale_attribute_value。"""
    if not specs:
        return specs
    out = dict(specs)
    style = out.get("样式")
    style_cid = str(getattr(style, "container_id", "") or "").strip() if style else ""
    if not style_cid:
        for name, spec in specs.items():
            if "_规格_p-" not in str(name):
                continue
            cid = str(spec.container_id or "").strip()
            if not cid:
                continue
            updates = {
                "container_id": cid,
                "sale_attribute_value": _infer_sale_attribute_value(spec),
            }
            if style:
                out["样式"] = style.model_copy(update=updates)
            else:
                out["样式"] = spec.model_copy(update=updates)
            out[name] = spec.model_copy(update={"enable_sale_attribute": False})
            logger.info(f"规格归一化: {name} → 样式 (container={cid})")
            break
    color = out.get("颜色")
    if color:
        inferred = _infer_sale_attribute_value(color)
        updates: dict = {}
        if inferred and not _resolve_sale_attribute_value(color):
            updates["sale_attribute_value"] = inferred
        if getattr(color, "enable_sale_attribute", None) is None:
            updates["enable_sale_attribute"] = True
        if updates:
            out["颜色"] = color.model_copy(update=updates)
    return out


def _confirm_spec_data_clear_dialog(driver, timeout: float = 4.0) -> bool:
    """处理调整商品规格项时的「数据清空提示」弹窗。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            confirmed = driver.execute_script(
                """
                const isVisible = (el) => {
                  if (!el) return false;
                  const st = window.getComputedStyle(el);
                  if (st.display === 'none' || st.visibility === 'hidden') return false;
                  const r = el.getBoundingClientRect();
                  return r.width > 0 && r.height > 0;
                };
                const dialogs = [
                  ...document.querySelectorAll('.next-dialog'),
                  ...document.querySelectorAll('.next-overlay-wrapper.opened .next-dialog'),
                ];
                for (const dlg of dialogs) {
                  if (!isVisible(dlg)) continue;
                  const text = (dlg.innerText || dlg.textContent || '').trim();
                  if (!text.includes('数据清空') && !text.includes('规格项') && !text.includes('确认是否继续')) {
                    continue;
                  }
                  for (const btn of dlg.querySelectorAll('button, .next-btn')) {
                    if (!isVisible(btn)) continue;
                    const t = (btn.innerText || btn.textContent || '').trim();
                    if (t === '确定' || t === '确认') {
                      btn.click();
                      return true;
                    }
                  }
                  const primary = dlg.querySelector('.next-btn-primary');
                  if (primary && isVisible(primary)) {
                    primary.click();
                    return true;
                  }
                }
                return false;
                """
            )
            if confirmed:
                time.sleep(0.5)
                return True
        except Exception:
            pass
        time.sleep(0.2)
    return False


def _sale_attribute_wrapper_checked(wrapper) -> bool:
    try:
        cb = wrapper.find_element(By.CSS_SELECTOR, "input[type='checkbox']")
        if cb.is_selected() or (cb.get_attribute("checked") is not None):
            return True
        cls = str(wrapper.get_attribute("class") or "")
        if "checked" in cls:
            return True
        aria = str(cb.get_attribute("aria-checked") or "").lower()
        return "true" in aria
    except Exception:
        return False


def _read_sale_attribute_label(wrapper) -> str:
    try:
        return str(wrapper.find_element(By.CSS_SELECTOR, ".next-checkbox-label").text or "").strip()
    except Exception:
        return str(wrapper.text or "").strip()


def _wrapper_matches_spec(label_text: str, spec_name: str) -> bool:
    label_norm = _norm_text(label_text.split("\n")[0])
    return any(
        _norm_text(alias) == label_norm or alias in label_text
        for alias in _spec_label_aliases(spec_name)
    )


def _set_sale_attribute_wrapper_checked(
    driver,
    wrapper,
    want_checked: bool,
    spec_name: str,
    label_text: str,
) -> bool:
    try:
        cb = wrapper.find_element(By.CSS_SELECTOR, "input[type='checkbox']")
        disabled = bool(cb.get_attribute("disabled"))
        currently = _sale_attribute_wrapper_checked(wrapper)
        if currently == want_checked:
            return True
        if disabled:
            if want_checked and currently:
                logger.info(f"商品规格项「{spec_name}」已锁定勾选 (label={label_text})")
                return True
            logger.warning(f"商品规格项「{spec_name}」不可选（disabled）")
            return currently == want_checked
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", wrapper)
        try:
            driver.execute_script("arguments[0].click();", wrapper)
        except Exception:
            driver.execute_script("arguments[0].click();", cb)
        time.sleep(0.45)
        _confirm_spec_data_clear_dialog(driver)
        time.sleep(0.35)
        ok = _sale_attribute_wrapper_checked(wrapper) == want_checked
        if ok:
            action = "勾选" if want_checked else "取消勾选"
            logger.info(f"{action}商品规格项: {spec_name} (label={label_text})")
        else:
            logger.warning(f"切换商品规格项未生效: {spec_name} want={want_checked} (label={label_text})")
        return ok
    except Exception as e:
        logger.warning(f"切换商品规格项失败 {spec_name}: {e}")
        return False


def _find_sale_attribute_wrapper(
    driver,
    spec_name: str,
    spec: SpecificationItemConfig,
):
    container = _find_sale_attributes_container(driver)
    if not container:
        return None, "", None

    aliases = _spec_label_aliases(spec_name)
    wrappers = container.find_elements(
        By.CSS_SELECTOR,
        ".next-checkbox-wrapper, label.checkbox-wrapper, label.items, .items label",
    )
    for wrapper in wrappers:
        try:
            label_text = _read_sale_attribute_label(wrapper)
            if not label_text:
                continue
            label_norm = _norm_text(label_text.split("\n")[0])
            matched = any(
                _norm_text(alias) == label_norm or alias in label_text
                for alias in aliases
            )
            if matched:
                return wrapper, label_text, container
        except Exception:
            continue

    sale_val = _infer_sale_attribute_value(spec)
    if sale_val:
        try:
            cb = container.find_element(By.CSS_SELECTOR, f"input.next-checkbox-input[value='{sale_val}']")
            wrapper = cb.find_element(By.XPATH, "./ancestor::label[contains(@class,'checkbox-wrapper')][1]")
            label_text = _read_sale_attribute_label(wrapper) or sale_val
            return wrapper, label_text, container
        except Exception as e:
            logger.warning(f"按 value 定位商品规格项失败 {spec_name} value={sale_val}: {e}")

    return None, "", container


def _ensure_sale_attribute_items(driver, specs: Dict[str, SpecificationItemConfig]) -> None:
    """
    配置顶部「商品规格项」：
    1. 取消配置中未启用的勾选项（含复制页预勾选项）
    2. 取消不在启用列表中的多余勾选项
    3. 对已启用项：先重置清空再勾选并填写
    """
    specs = _normalize_specs_for_run(specs)
    targets = [
        (name, spec)
        for name, spec in specs.items()
        if _is_sale_attribute_enabled(name, spec)
    ]
    enabled_names = {name for name, _ in targets}

    container = _find_sale_attributes_container(driver)
    if container:
        try:
            driver.execute_script("arguments[0].scrollIntoView({block:'center'});", container)
            time.sleep(0.3)
        except Exception:
            pass
        wrappers = container.find_elements(
            By.CSS_SELECTOR,
            ".next-checkbox-wrapper, label.checkbox-wrapper, label.items, .items label",
        )
        for wrapper in wrappers:
            try:
                label_text = _read_sale_attribute_label(wrapper)
                if not label_text:
                    continue
                matched_name = None
                for spec_name in specs:
                    if _wrapper_matches_spec(label_text, spec_name):
                        matched_name = spec_name
                        break
                want_checked = (
                    matched_name in enabled_names
                    if matched_name
                    else False
                )
                if not _sale_attribute_wrapper_checked(wrapper):
                    continue
                if want_checked:
                    continue
                logger.info(
                    f"取消未启用/多余规格项: {label_text}"
                    + (f" ({matched_name})" if matched_name else "")
                )
                _set_sale_attribute_wrapper_checked(
                    driver, wrapper, False, matched_name or label_text, label_text
                )
            except Exception:
                continue

    if not targets:
        logger.info("无需要勾选的顶部规格项（已同步取消未启用项）")
        return

    targets.sort(key=_sale_attr_sort_key)
    if len(targets) > 3:
        skipped = [n for n, _ in targets[3:]]
        logger.warning(f"顶部规格项最多 3 项，将跳过后续: {skipped}")
        targets = targets[:3]

    for spec_name, spec in targets:
        wrapper, label_text, _ = _find_sale_attribute_wrapper(driver, spec_name, spec)
        if not wrapper:
            logger.warning(f"未找到商品规格项复选框: {spec_name}")
            continue
        try:
            cb = wrapper.find_element(By.CSS_SELECTOR, "input[type='checkbox']")
            disabled = bool(cb.get_attribute("disabled"))
        except Exception:
            disabled = False

        if _sale_attribute_wrapper_checked(wrapper):
            if disabled:
                logger.info(f"商品规格项「{spec_name}」已勾选且锁定 (label={label_text})")
            else:
                logger.info(f"商品规格项「{spec_name}」重置清空 (label={label_text})")
                _set_sale_attribute_wrapper_checked(driver, wrapper, False, spec_name, label_text)
                _set_sale_attribute_wrapper_checked(driver, wrapper, True, spec_name, label_text)
        else:
            _set_sale_attribute_wrapper_checked(driver, wrapper, True, spec_name, label_text)

        cid = str(spec.container_id or "").strip()
        if cid:
            try:
                WebDriverWait(driver, 4).until(EC.presence_of_element_located((By.ID, cid)))
            except Exception:
                logger.warning(f"勾选「{spec_name}」后未出现规格区域 {cid}")


def _toggle_spec_image_switch(driver, container, enable: bool) -> bool:
    try:
        switch = container.find_element(By.CSS_SELECTOR, ".upload-image-switch .next-switch")
        aria = str(switch.get_attribute("aria-checked") or "").lower()
        is_on = "true" in aria or "next-switch-on" in (switch.get_attribute("class") or "")
        if enable and not is_on:
            driver.execute_script("arguments[0].scrollIntoView({block:'center'});", switch)
            driver.execute_script("arguments[0].click();", switch)
            time.sleep(0.6)
            return True
        if not enable and is_on:
            driver.execute_script("arguments[0].scrollIntoView({block:'center'});", switch)
            driver.execute_script("arguments[0].click();", switch)
            time.sleep(0.6)
            return True
        return is_on == enable
    except Exception:
        return False


def _get_value_row_items(container):
    return container.find_elements(By.CSS_SELECTOR, ".posting-field-color .list .item[role='item']")


def _clear_value_rows_container(driver, container) -> None:
    """清空 value_rows 规格已有行（颜色/样式输入与规格图）。"""
    try:
        rows = _get_value_row_items(container)
        for row in rows:
            _remove_row_spec_image(driver, row)
            try:
                for btn in row.find_elements(
                    By.CSS_SELECTOR,
                    ".next-tag-close-btn, .remove-btn, [class*='delete'], [class*='remove']",
                ):
                    driver.execute_script("arguments[0].click();", btn)
                    time.sleep(0.15)
            except Exception:
                pass
            try:
                inp = row.find_element(By.CSS_SELECTOR, "input[role='colorCombobox'], input")
                driver.execute_script("arguments[0].click();", inp)
                inp.send_keys(Keys.CONTROL + "a")
                inp.send_keys(Keys.BACKSPACE)
                driver.execute_script(
                    """
                    const el = arguments[0];
                    const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
                    setter.call(el, '');
                    el.dispatchEvent(new Event('input', { bubbles: true }));
                    el.dispatchEvent(new Event('change', { bubbles: true }));
                    """,
                    inp,
                )
                time.sleep(0.1)
            except Exception:
                pass
        while len(_get_value_row_items(container)) > 1:
            rows = _get_value_row_items(container)
            removed = False
            for row in reversed(rows[1:]):
                for sel in (".item-remove", ".remove-item", "[role='btn-remove']"):
                    try:
                        btn = row.find_element(By.CSS_SELECTOR, sel)
                        driver.execute_script("arguments[0].click();", btn)
                        time.sleep(0.2)
                        removed = True
                        break
                    except Exception:
                        continue
                if removed:
                    break
            if not removed:
                break
    except Exception:
        pass


def _click_add_value_row(driver, container) -> bool:
    for selector in (".add-color-btn", "[role='btn-add']", ".add-color-btn a", "a.add-color-btn"):
        try:
            btn = container.find_element(By.CSS_SELECTOR, selector)
            driver.execute_script("arguments[0].scrollIntoView({block:'center'});", btn)
            driver.execute_script("arguments[0].click();", btn)
            time.sleep(0.5)
            return True
        except Exception:
            continue
    return False


def _ensure_value_row_count(driver, container, needed: int) -> int:
    """页面默认已有 1 行颜色；按图片数量补足到 needed 行。"""
    needed = max(1, int(needed or 1))
    for _ in range(max(needed, 12)):
        rows = _get_value_row_items(container)
        current = len(rows)
        if current >= needed:
            if needed > 1 and current == needed:
                logger.info(f"颜色行数已就绪: {current}/{needed}（默认 1 行 + 添加 {max(0, needed - 1)} 次）")
            return current
        if not _click_add_value_row(driver, container):
            logger.warning(f"点击「+ 添加」失败，当前 {current} 行，目标 {needed} 行")
            break
        time.sleep(0.45)
    rows = _get_value_row_items(container)
    return len(rows)


def _read_row_text(row) -> str:
    try:
        inp = row.find_element(By.CSS_SELECTOR, "input[role='colorCombobox']")
        return str(inp.get_attribute("value") or "").strip()
    except Exception:
        return ""


def _row_text_matches(row, value: str) -> bool:
    current = _read_row_text(row)
    if not current:
        return False
    target = str(value or "").strip()
    if not target:
        return False
    if current == target:
        return True
    return _norm_text(current) == _norm_text(target)


def _fill_row_text(driver, row, value: str) -> bool:
    target = str(value or "").strip()
    if not target:
        return False
    if _row_text_matches(row, target):
        return True
    try:
        inp = row.find_element(By.CSS_SELECTOR, "input[role='colorCombobox']")
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", inp)
        driver.execute_script("arguments[0].click();", inp)
        time.sleep(0.15)
        inp.send_keys(Keys.CONTROL + "a")
        inp.send_keys(Keys.BACKSPACE)
        time.sleep(0.1)
        inp.send_keys(target)
        time.sleep(0.35)

        # 尝试点选下拉建议（部分类目为 combobox）
        try:
            for opt in driver.find_elements(
                By.CSS_SELECTOR,
                ".next-menu-item, [role='option'], .next-select-menu-item, .next-autocomplete-menu-item",
            ):
                text = str(opt.text or "").strip()
                if not text:
                    continue
                if _norm_text(text) == _norm_text(target) or target.lower() in text.lower():
                    driver.execute_script("arguments[0].click();", opt)
                    time.sleep(0.2)
                    break
        except Exception:
            pass

        inp.send_keys(Keys.TAB)
        time.sleep(0.15)

        # React 受控输入：用原生 setter 触发 input/change/blur
        driver.execute_script(
            """
            const el = arguments[0];
            const v = arguments[1];
            const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
            setter.call(el, v);
            el.dispatchEvent(new Event('input', { bubbles: true }));
            el.dispatchEvent(new Event('change', { bubbles: true }));
            el.dispatchEvent(new Event('blur', { bubbles: true }));
            """,
            inp,
            target,
        )
        time.sleep(0.25)
        return _row_text_matches(row, target)
    except Exception:
        return False


def _wait_row_image_uploaded(row, timeout: float = 10.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if row.find_elements(
                By.CSS_SELECTOR,
                ".custom-upload-image img, .upload-image-preview img, .next-upload-list-item img, img[src]",
            ):
                return True
        except Exception:
            pass
        time.sleep(0.35)
    return False


def _ensure_row_text_after_upload(driver, container, idx: int, value: str) -> bool:
    """上传规格图后页面常会重渲染并清空颜色输入，需重新定位行并回填。"""
    target = str(value or "").strip()
    if not target:
        return False
    for attempt in range(3):
        time.sleep(0.6 if attempt == 0 else 0.9)
        rows = _get_value_row_items(container)
        if idx >= len(rows):
            continue
        row = rows[idx]
        if _row_text_matches(row, target):
            return True
        if _fill_row_text(driver, row, target):
            logger.info(f"上传规格图后已重新填写颜色 → {target}")
            return True
    return False


def _confirm_row_image_delete_dialog(driver, timeout: float = 3.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            confirmed = driver.execute_script(
                """
                const isVisible = (el) => {
                  if (!el) return false;
                  const st = window.getComputedStyle(el);
                  if (st.display === 'none' || st.visibility === 'hidden') return false;
                  const r = el.getBoundingClientRect();
                  return r.width > 0 && r.height > 0;
                };
                for (const dlg of document.querySelectorAll('.next-dialog, .next-overlay-wrapper.opened .next-dialog')) {
                  if (!isVisible(dlg)) continue;
                  const text = (dlg.innerText || dlg.textContent || '').trim();
                  if (!text.includes('删除') && !/delete/i.test(text)) continue;
                  for (const btn of dlg.querySelectorAll('button, .next-btn')) {
                    if (!isVisible(btn)) continue;
                    const t = (btn.innerText || btn.textContent || '').trim();
                    if (t.includes('确认') || t.includes('删除') || t === '确定') {
                      btn.click();
                      return true;
                    }
                  }
                  const primary = dlg.querySelector('.next-btn-primary');
                  if (primary && isVisible(primary)) {
                    primary.click();
                    return true;
                  }
                }
                return false;
                """
            )
            if confirmed:
                time.sleep(0.4)
                return True
        except Exception:
            pass
        time.sleep(0.15)
    return False


def _remove_row_spec_image(driver, row) -> bool:
    """删除行内已有规格图（复制发品页常残留旧图，需先删再传）。"""
    if not _row_has_spec_image(row):
        return True
    try:
        from selenium.webdriver.common.action_chains import ActionChains

        box = row.find_element(By.CSS_SELECTOR, ".custom-upload-image")
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", box)
        ActionChains(driver).move_to_element(box).perform()
        time.sleep(0.35)
        deleted = driver.execute_script(
            """
            const row = arguments[0];
            const handle = row.querySelector('.custom-upload-image-handle');
            if (handle) {
              for (const btn of handle.querySelectorAll('button, a, span, i')) {
                const t = (btn.innerText || btn.textContent || btn.getAttribute('title') || '').trim();
                const cls = btn.className || '';
                if (t.includes('删除') || cls.includes('delete') || cls.includes('close')) {
                  btn.click();
                  return true;
                }
              }
            }
            for (const el of row.querySelectorAll('[class*="delete"], [class*="remove"], .next-icon-close')) {
              el.click();
              return true;
            }
            return false;
            """,
            row,
        )
        if deleted:
            _confirm_row_image_delete_dialog(driver)
            time.sleep(0.45)
        return not _row_has_spec_image(row)
    except Exception:
        return False


def _upload_row_spec_image(driver, row, image_path: str) -> bool:
    if not image_path or not os.path.isfile(image_path):
        return False
    abs_path = os.path.abspath(image_path)
    _remove_row_spec_image(driver, row)
    try:
        upload_box = row.find_element(By.CSS_SELECTOR, ".custom-upload-image")
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", upload_box)
        driver.execute_script("arguments[0].click();", upload_box)
        time.sleep(0.4)
    except Exception:
        return False

    try:
        handle = row.find_element(By.CSS_SELECTOR, ".custom-upload-image-handle")
        if handle.is_displayed():
            for btn in handle.find_elements(By.CSS_SELECTOR, ".image-upload-button, button, a"):
                label = str(btn.text or "").strip()
                if "本地" in label or "选取" in label or "上传" in label:
                    driver.execute_script("arguments[0].click();", btn)
                    time.sleep(0.3)
                    break
    except Exception:
        pass

    for scope in (row, driver):
        try:
            root = scope if scope is not row else row
            inputs = root.find_elements(By.CSS_SELECTOR, "input[type='file'][accept*='image'], input[type='file']")
            for inp in inputs:
                try:
                    driver.execute_script(
                        "arguments[0].style.cssText='display:block!important;visibility:visible!important;"
                        "opacity:1!important;position:fixed;top:0;left:0;width:1px;height:1px;z-index:2147483647;';",
                        inp,
                    )
                    inp.send_keys(abs_path)
                    time.sleep(1.0)
                    if _wait_row_image_uploaded(row, timeout=8.0):
                        logger.info(f"规格图已上传: {os.path.basename(abs_path)}")
                        return True
                except Exception:
                    continue
        except Exception:
            continue
    logger.warning(f"规格图上传失败: {abs_path}")
    return False


def _fill_value_rows_spec(
    driver,
    wait: WebDriverWait,
    attr_name: str,
    spec: SpecificationItemConfig,
    main_image_dir: str,
    enable_spec_image: bool,
) -> bool:
    container_id = str(spec.container_id or "").strip()
    if not container_id:
        logger.warning(f"{attr_name}: value_rows 规格无 container_id，跳过")
        return False

    fill_values = [str(v).strip() for v in (spec.default_values or spec.values_pool or []) if str(v).strip()]
    image_subdir = str(getattr(spec, "image_subdir", "") or "").strip() or _default_image_subdir(attr_name)
    if not fill_values and enable_spec_image:
        fill_values = _list_spec_image_values(main_image_dir, image_subdir)
        if fill_values:
            logger.info(
                f"{attr_name}: 未配置填充值，已从规格图目录自动读取 → {fill_values} "
                f"（{os.path.join(main_image_dir, image_subdir)}）"
            )
    if not fill_values:
        logger.info(f"{attr_name}: 未配置填充值，跳过 value_rows 填写")
        return True

    try:
        container = wait.until(EC.presence_of_element_located((By.ID, container_id)))
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", container)
        time.sleep(0.6)
        _clear_value_rows_container(driver, container)

        if enable_spec_image:
            _toggle_spec_image_switch(driver, container, True)
        else:
            _toggle_spec_image_switch(driver, container, False)

        row_count = _ensure_value_row_count(driver, container, len(fill_values))
        if row_count < len(fill_values):
            logger.warning(f"{attr_name}: 颜色行不足 {row_count}/{len(fill_values)}，将尽力填写已有行")

        for idx, value in enumerate(fill_values):
            rows = _get_value_row_items(container)
            if idx >= len(rows):
                logger.warning(f"{attr_name}: 无法新增第 {idx + 1} 行")
                break

            row = rows[idx]
            if not _fill_row_text(driver, row, value):
                logger.warning(f"{attr_name}: 填写规格值失败 → {value}")
                continue
            logger.info(f"{attr_name}: 已填写规格值 → {value}")

            if enable_spec_image:
                img_path = _resolve_spec_image_path(main_image_dir, image_subdir, value)
                if img_path:
                    logger.info(f"{attr_name}: 上传规格图 → {img_path}")
                    uploaded = _upload_row_spec_image(driver, row, img_path)
                    if uploaded:
                        _wait_row_image_uploaded(row)
                    elif _row_has_spec_image(row):
                        logger.info(f"{attr_name}: 规格图已存在，跳过重复上传 → {value}")
                    if not _ensure_row_text_after_upload(driver, container, idx, value):
                        logger.warning(f"{attr_name}: 上传规格图后颜色值丢失且回填失败 → {value}")
                else:
                    tried = [os.path.join(main_image_dir, s) for s in _spec_image_subdir_candidates(image_subdir)]
                    logger.warning(f"{attr_name}: 未找到规格图 {value}（已尝试目录: {tried}）")
            elif not _row_text_matches(row, value):
                _fill_row_text(driver, row, value)

        logger.info(f"{attr_name} value_rows 设置完成（{len(fill_values)} 项）")
        return True
    except Exception as e:
        logger.error(f"设置 {attr_name} value_rows 失败: {e}")
        return False


def _pick_checkbox_element(container, target_value: str):
    target = str(target_value or "").strip()
    if not target:
        return None
    target_norm = _norm_text(target)

    pairs = []
    for cb in container.find_elements(By.XPATH, ".//input[@type='checkbox']"):
        try:
            label_text = ""
            try:
                label = cb.find_element(By.XPATH, "./ancestor::label[1]")
                label_text = str(label.text or "").strip()
            except Exception:
                pass
            if not label_text:
                label_text = str(cb.get_attribute("value") or cb.get_attribute("aria-label") or "").strip()
            pairs.append((cb, label_text))
        except Exception:
            continue

    for cb, text in pairs:
        if _norm_text(text) == target_norm:
            return cb
    for cb, text in pairs:
        nt = _norm_text(text)
        if target_norm and (target_norm in nt or nt in target_norm):
            return cb
    for cb, text in pairs:
        if target in text or text in target:
            return cb
    return None


def _fill_checkbox_spec(driver, wait: WebDriverWait, attr_name: str, spec: SpecificationItemConfig) -> bool:
    container_id = str(spec.container_id or "").strip()
    if not container_id:
        logger.warning(f"{attr_name}: 无 container_id，跳过")
        return False

    values_pool = spec.values_pool
    default_values = list(getattr(spec, "default_values", []) or [])
    max_select = spec.max_select

    container = wait.until(EC.presence_of_element_located((By.ID, container_id)))
    driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", container)
    time.sleep(1)

    for cb in container.find_elements(By.XPATH, ".//input[@type='checkbox']"):
        if cb.is_selected():
            driver.execute_script("arguments[0].click();", cb)
            time.sleep(0.3)

    clean_pool = [str(v).strip() for v in (values_pool or []) if str(v).strip()]
    clean_defaults = [str(v).strip() for v in default_values if str(v).strip()]
    if clean_defaults:
        selected_values = [v for v in clean_defaults if v in clean_pool]
    else:
        selected_values = []
        if len(selected_values) < max_select:
            remain = [v for v in clean_pool if v not in selected_values]
            need = min(max_select - len(selected_values), len(remain))
            if need > 0:
                selected_values.extend(random.sample(remain, need))
    logger.info(f"{attr_name}：按配置选择 {len(selected_values)} 项 → {selected_values}")

    for val in selected_values:
        try:
            checkbox = _pick_checkbox_element(container, val)
            if checkbox is None:
                logger.warning(f"{attr_name}：无法匹配选项 '{val}'，跳过")
                continue
            if not checkbox.is_selected():
                driver.execute_script("arguments[0].click();", checkbox)
                time.sleep(0.5)
        except Exception:
            logger.warning(f"{attr_name}：无法找到选项 '{val}'，跳过")

    logger.info(f"{attr_name} 设置完成")
    return True


def select_specifications(
    driver,
    attributes_cfg: AttributeConfig,
    group_name: str = "",
    main_image_dir: str = "",
) -> bool:
    """
    根据配置填写商品规格：
    - checkbox_grid：复选框网格（如戒指尺寸）
    - value_rows：输入行 + 可选规格图本地上传（如颜色/样式）
    """
    wait = WebDriverWait(driver, 10)

    current_url = ""
    try:
        current_url = str(driver.current_url or "").strip()
    except Exception:
        current_url = ""

    specs = resolve_specs_for_group(
        attributes_cfg,
        group_name or "",
        posting_url=current_url,
    )
    if not specs:
        logger.info(f"组别 {group_name or '(默认)'} 未配置规格，跳过规格填写")
        return True

    specs = _normalize_specs_for_run(specs)
    logger.info(f"组别 {group_name or '(默认)'} 使用规格数量: {len(specs)}")

    try:
        WebDriverWait(driver, 8).until(EC.presence_of_element_located((By.ID, "struct-specification")))
        time.sleep(0.5)
    except Exception:
        pass

    _ensure_sale_attribute_items(driver, specs)
    spec_image_owner = _pick_spec_image_owner(specs)
    if spec_image_owner:
        logger.info(f"规格图开关归属: {spec_image_owner}（颜色/样式互斥）")

    for attr_name, spec in specs.items():
        if not _is_sale_attribute_enabled(attr_name, spec):
            logger.info(f"跳过规格「{attr_name}」：未开启顶部规格项")
            continue
        if not str(spec.container_id or "").strip():
            logger.info(f"跳过规格「{attr_name}」：未配置 container_id（请重新获取规格）")
            continue
        interaction = _spec_interaction(spec)
        try:
            if interaction == "value_rows":
                enable_image = (
                    bool(getattr(spec, "enable_spec_image", False))
                    and attr_name == spec_image_owner
                )
                _fill_value_rows_spec(
                    driver,
                    wait,
                    attr_name,
                    spec,
                    main_image_dir,
                    enable_image,
                )
            else:
                _fill_checkbox_spec(driver, wait, attr_name, spec)
        except Exception as e:
            logger.error(f"设置 {attr_name} 失败: {e}")
            continue

    return True


def _row_has_spec_image(row) -> bool:
    try:
        if row.find_elements(
            By.CSS_SELECTOR,
            ".custom-upload-image img, .upload-image-preview img, .next-upload-list-item img",
        ):
            return True
        for img in row.find_elements(By.CSS_SELECTOR, "img"):
            src = str(img.get_attribute("src") or "").strip()
            if src and "blank" not in src.lower():
                return True
    except Exception:
        pass
    return False


def reconcile_value_row_specs(
    driver,
    attributes_cfg: AttributeConfig,
    group_name: str = "",
    main_image_dir: str = "",
) -> None:
    """属性/详情填写后页面可能重渲染，补全颜色行文字与规格图。"""
    wait = WebDriverWait(driver, 8)
    current_url = ""
    try:
        current_url = str(driver.current_url or "").strip()
    except Exception:
        pass

    specs = _normalize_specs_for_run(
        resolve_specs_for_group(attributes_cfg, group_name or "", posting_url=current_url)
    )
    if not specs:
        return

    spec_image_owner = _pick_spec_image_owner(specs)
    for attr_name, spec in specs.items():
        if not _is_sale_attribute_enabled(attr_name, spec):
            continue
        if _spec_interaction(spec) != "value_rows":
            continue
        container_id = str(spec.container_id or "").strip()
        if not container_id:
            continue

        fill_values = [str(v).strip() for v in (spec.default_values or spec.values_pool or []) if str(v).strip()]
        image_subdir = str(getattr(spec, "image_subdir", "") or "").strip() or _default_image_subdir(attr_name)
        enable_image = bool(getattr(spec, "enable_spec_image", False)) and attr_name == spec_image_owner
        if not fill_values and enable_image:
            fill_values = _list_spec_image_values(main_image_dir, image_subdir)
        if not fill_values:
            continue

        try:
            container = wait.until(EC.presence_of_element_located((By.ID, container_id)))
            driver.execute_script("arguments[0].scrollIntoView({block:'center'});", container)
            time.sleep(0.4)
            _ensure_value_row_count(driver, container, len(fill_values))
            rows = _get_value_row_items(container)
            for idx, value in enumerate(fill_values):
                if idx >= len(rows):
                    break
                row = rows[idx]
                if not _row_text_matches(row, value):
                    _fill_row_text(driver, row, value)
                    logger.info(f"[补全] {attr_name} 重新填写 → {value}")
                if enable_image:
                    img_path = _resolve_spec_image_path(main_image_dir, image_subdir, value)
                    if img_path and not _row_has_spec_image(row):
                        _upload_row_spec_image(driver, row, img_path)
                        _wait_row_image_uploaded(row)
                        _ensure_row_text_after_upload(driver, container, idx, value)
                        logger.info(f"[补全] {attr_name} 重新上传规格图 → {os.path.basename(img_path)}")
        except Exception as e:
            logger.warning(f"[补全] {attr_name} 失败: {e}")


def verify_filled_specs(
    driver,
    attributes_cfg: AttributeConfig,
    group_name: str = "",
    main_image_dir: str = "",
) -> List[str]:
    """对比规格配置/磁盘图片与页面实际值，返回问题列表。"""
    issues: List[str] = []
    current_url = ""
    try:
        current_url = str(driver.current_url or "").strip()
    except Exception:
        pass
    specs = _normalize_specs_for_run(
        resolve_specs_for_group(attributes_cfg, group_name or "", posting_url=current_url)
    )
    if not specs:
        return issues
    spec_image_owner = _pick_spec_image_owner(specs)
    for attr_name, spec in specs.items():
        if not _is_sale_attribute_enabled(attr_name, spec):
            continue
        cid = str(spec.container_id or "").strip()
        if not cid:
            issues.append(f"规格/{attr_name}: container_id 为空")
            continue
        try:
            container = driver.find_element(By.ID, cid)
        except Exception:
            issues.append(f"规格/{attr_name}: 页面无容器 {cid}")
            continue
        enable_image = bool(getattr(spec, "enable_spec_image", False)) and attr_name == spec_image_owner
        image_subdir = str(getattr(spec, "image_subdir", "") or "").strip() or _default_image_subdir(attr_name)
        expected = [str(v).strip() for v in (spec.default_values or spec.values_pool or []) if str(v).strip()]
        if not expected and enable_image:
            expected = _list_spec_image_values(main_image_dir, image_subdir)
        if _spec_interaction(spec) == "checkbox_grid":
            selected = []
            for cb in container.find_elements(By.XPATH, ".//input[@type='checkbox']"):
                try:
                    if not cb.is_selected():
                        continue
                    label_text = ""
                    try:
                        label = cb.find_element(By.XPATH, "./ancestor::label[1]")
                        label_text = str(label.text or "").strip()
                    except Exception:
                        pass
                    if not label_text:
                        label_text = str(
                            cb.get_attribute("value") or cb.get_attribute("aria-label") or ""
                        ).strip()
                    if label_text:
                        selected.append(label_text)
                except Exception:
                    pass
            exp = [str(v).strip() for v in (spec.default_values or []) if str(v).strip()]
            if exp and not all(v in selected or any(v in s for s in selected) for v in exp):
                issues.append(f"规格/{attr_name}: 期望勾选 {exp} 实际={selected}")
            elif exp:
                logger.info(f"[验收OK] 规格/{attr_name} 期望={exp} 实际={selected}")
            continue
        rows = _get_value_row_items(container)
        actual_texts = [_read_row_text(r) for r in rows]
        for idx, val in enumerate(expected):
            if idx >= len(rows):
                issues.append(f"规格/{attr_name}: 缺行 期望={val}")
                continue
            actual = _read_row_text(rows[idx])
            if not actual or (_norm_text(actual) != _norm_text(val) and _norm_text(val) not in _norm_text(actual)):
                issues.append(f"规格/{attr_name}: 行{idx + 1} 期望={val} 实际={actual or '(空)'}")
            elif enable_image:
                img_path = _resolve_spec_image_path(main_image_dir, image_subdir, val)
                if img_path and not _row_has_spec_image(rows[idx]):
                    issues.append(f"规格/{attr_name}: 行{idx + 1} 缺图 {os.path.basename(img_path)}")
        if expected and not issues:
            logger.info(f"[验收OK] 规格/{attr_name} 期望={expected} 实际={actual_texts}")
    return issues

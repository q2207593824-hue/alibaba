# -*- coding: utf-8 -*-
"""Sync attributes/specifications from Alibaba publish page for one group."""
from __future__ import annotations

import re
import time
from typing import Any, Dict, List

from app.core.logger import setup_logger
from app.core.settings import AttributeItemConfig, SpecificationItemConfig, config_manager, get_config

logger = setup_logger("page_scan_platform_sync")


def _norm_label(s: str) -> str:
    return str(s or "").strip().replace("*", "").replace("\n", " ").strip()


def _extract_cat_id(url: str, browser=None) -> str:
    text = str(url or "").strip()
    m = re.search(r"(?:catId|catid|categoryId|leafCatId)=(\d+)", text, flags=re.IGNORECASE)
    if m:
        return m.group(1)
    if browser is not None:
        try:
            cur = str(browser.current_url or "").strip()
            m = re.search(r"(?:catId|catid|categoryId|leafCatId)=(\d+)", cur, flags=re.IGNORECASE)
            if m:
                return m.group(1)
        except Exception:
            pass
    return ""


def sync_group_from_platform(*, group_name: str, url: str, logs: List[str]) -> Dict[str, Any]:
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from app.services.automation.browser_manager import BrowserManager
    from app.services.automation.page_helpers import close_all_popups
    from app.services.page_scanner.scanner import _ensure_page_ready

    cfg = get_config()
    browser = BrowserManager()
    if not browser.setup():
        err = BrowserManager.get_last_setup_error() or "browser setup failed"
        logs.append(err)
        return {"success": False, "error": err}

    attr_added = spec_added = scanned_blocks = 0
    cat_id = ""
    next_group: Dict[str, SpecificationItemConfig] = {}
    all_attrs = dict(cfg.attributes.all_attributes or {})

    try:
        _ensure_page_ready(browser.driver, url, wait_seconds=45.0)
        close_all_popups(browser.driver)
        if "login.alibaba.com" in (browser.driver.current_url or "").lower():
            if not browser.login():
                return {"success": False, "error": "login failed"}
            _ensure_page_ready(browser.driver, url, wait_seconds=45.0)
            close_all_popups(browser.driver)
            if "login.alibaba.com" in (browser.driver.current_url or "").lower():
                return {"success": False, "error": "needs login"}

        cat_id = _extract_cat_id(url, browser.driver)
        driver = browser.driver

        try:
            root = WebDriverWait(driver, 20).until(
                EC.presence_of_element_located((By.ID, "struct-icbuCatProp"))
            )
            for i, container in enumerate(root.find_elements(By.CSS_SELECTOR, "div[id^='struct-p-']")):
                cid = str(container.get_attribute("id") or "").strip()
                if not cid:
                    continue
                name = f"attr_{i + 1}"
                try:
                    t = str(container.find_element(By.CLASS_NAME, "label").text or "").strip()
                    if t:
                        name = t
                except Exception:
                    pass
                if name in all_attrs:
                    continue
                req = "required" in str(container.get_attribute("class") or "")
                all_attrs[name] = AttributeItemConfig(
                    container_id=cid,
                    type="required" if req else "optional",
                    select_type="input",
                )
                attr_added += 1
            cfg.attributes.all_attributes = all_attrs
        except Exception as exc:
            logs.append(f"attrs: {exc}")

        try:
            WebDriverWait(driver, 30).until(
                EC.presence_of_element_located((By.ID, "struct-specification"))
            )
            time.sleep(5)
            for block in driver.find_elements(By.CSS_SELECTOR, "div.sell-o-addon[id^='p-']"):
                bid = str(block.get_attribute("id") or "").strip()
                if not bid:
                    continue
                scanned_blocks += 1
                title = ""
                try:
                    title = _norm_label(
                        block.find_element(By.CSS_SELECTOR, ".sell-o-addon-label").text.split("\n")[0]
                    )
                except Exception:
                    title = f"{group_name}_spec_{bid}"

                is_value_rows = bool(
                    block.find_elements(
                        By.CSS_SELECTOR,
                        ".posting-field-color, input[role='colorCombobox']",
                    )
                )
                if is_value_rows:
                    image_subdir = "SKU" if title in ("颜色", "Color") else (
                        "样式" if title in ("样式", "Style") else title
                    )
                    next_group[title] = SpecificationItemConfig(
                        container_id=bid,
                        values_pool=[],
                        default_values=[],
                        max_select=1,
                        type="value_rows",
                        interaction="value_rows",
                        enable_spec_image=title in ("颜色", "Color"),
                        image_subdir=image_subdir,
                    )
                    spec_added += 1
                    continue

                pool, defaults = [], []
                for wrap in block.find_elements(By.CSS_SELECTOR, ".next-checkbox-wrapper, .next-checkbox"):
                    try:
                        lb = _norm_label(wrap.text)
                        inp = wrap.find_element(By.TAG_NAME, "input")
                        if lb and lb not in pool:
                            pool.append(lb)
                        checked = inp.is_selected() or inp.get_attribute("checked")
                        if lb and checked and lb not in defaults:
                            defaults.append(lb)
                    except Exception:
                        continue
                if not pool:
                    continue
                next_group[title] = SpecificationItemConfig(
                    container_id=bid,
                    values_pool=pool,
                    default_values=defaults,
                    max_select=min(2, len(pool)),
                    type="checkbox",
                    interaction="checkbox_grid",
                )
                spec_added += 1
        except Exception as exc:
            logs.append(f"specs: {exc}")

        if next_group:
            all_g = dict(cfg.attributes.specifications_by_group or {})
            all_g[group_name] = next_group
            cfg.attributes.specifications_by_group = all_g
            if cat_id:
                by_cat = dict(cfg.attributes.specifications_by_category_id or {})
                by_cat[str(cat_id)] = next_group
                cfg.attributes.specifications_by_category_id = by_cat
            alias = dict(cfg.attributes.specification_group_alias or {})
            alias[group_name] = group_name
            cfg.attributes.specification_group_alias = alias

        config_manager.save()
        logs.append(f"sync: attrs+{attr_added} specs+{spec_added}")
        return {
            "success": True,
            "attributes_added": attr_added,
            "attributes_total": len(all_attrs),
            "specs_added": spec_added,
            "specs_total": len(next_group),
            "scanned_blocks": scanned_blocks,
            "category_id": cat_id,
        }
    except Exception as exc:
        logger.exception("platform sync failed")
        return {"success": False, "error": str(exc)}
    finally:
        browser.quit()
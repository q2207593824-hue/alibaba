# -*- coding: utf-8 -*-
"""Publish page element scanner (isolated from auto-publish flow)."""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urlparse

from app.core.logger import setup_logger

logger = setup_logger("page_scanner")

_SCAN_JS = r"""
return (function () {
  const MIN = 6;
  const seen = new Set();
  const out = [];
  let seq = 0;

  function cssPath(el) {
    if (!el || el.nodeType !== 1) return "";
    const parts = [];
    let cur = el;
    while (cur && cur.nodeType === 1 && parts.length < 8) {
      let part = cur.tagName.toLowerCase();
      if (cur.id) {
        part += "#" + CSS.escape(cur.id);
        parts.unshift(part);
        break;
      }
      const cls = (cur.getAttribute("class") || "")
        .trim()
        .split(/\s+/)
        .filter(Boolean)
        .slice(0, 2);
      if (cls.length) part += "." + cls.map((c) => CSS.escape(c)).join(".");
      const parent = cur.parentElement;
      if (parent) {
        const siblings = Array.from(parent.children).filter((c) => c.tagName === cur.tagName);
        if (siblings.length > 1) {
          const idx = siblings.indexOf(cur) + 1;
          part += `:nth-of-type(${idx})`;
        }
      }
      parts.unshift(part);
      cur = parent;
    }
    return parts.join(" > ");
  }

  function isVisible(el) {
    if (!el || el.nodeType !== 1) return false;
    const st = window.getComputedStyle(el);
    if (st.display === "none" || st.visibility === "hidden" || Number(st.opacity) === 0) return false;
    const r = el.getBoundingClientRect();
    if (r.width < MIN || r.height < MIN) return false;
    if (r.bottom < -50 || r.right < -50) return false;
    return true;
  }

  function textOf(el) {
    const t = (el.innerText || el.textContent || "").replace(/\s+/g, " ").trim();
    return t.slice(0, 120);
  }

  function labelOf(el) {
    const aria = (el.getAttribute("aria-label") || "").trim();
    if (aria) return aria.slice(0, 120);
    const placeholder = (el.getAttribute("placeholder") || "").trim();
    if (placeholder) return placeholder.slice(0, 120);
    const title = (el.getAttribute("title") || "").trim();
    if (title) return title.slice(0, 120);
    if (el.id) {
      const lab = document.querySelector(`label[for="${CSS.escape(el.id)}"]`);
      if (lab) return textOf(lab).slice(0, 120);
    }
    let p = el.parentElement;
    for (let i = 0; i < 4 && p; i++) {
      const prev = p.previousElementSibling;
      if (prev) {
        const pt = textOf(prev);
        if (pt && pt.length <= 40) return pt;
      }
      const label = p.querySelector(":scope > label, :scope > .next-form-item-label, :scope > [class*='label']");
      if (label) {
        const lt = textOf(label);
        if (lt) return lt.slice(0, 120);
      }
      p = p.parentElement;
    }
    return textOf(el).slice(0, 80);
  }

  function classify(el) {
    const tag = (el.tagName || "").toLowerCase();
    const type = (el.getAttribute("type") || "").toLowerCase();
    const role = (el.getAttribute("role") || "").toLowerCase();
    const cls = (el.getAttribute("class") || "").toLowerCase();
    if (type === "file" || cls.includes("upload") || cls.includes("uploader")) return "upload";
    if (tag === "select" || role === "combobox" || cls.includes("next-select")) return "select";
    if (type === "checkbox" || role === "checkbox" || cls.includes("checkbox")) return "checkbox";
    if (type === "radio" || role === "radio" || cls.includes("radio")) return "radio";
    if (tag === "button" || role === "button" || type === "button" || type === "submit") return "button";
    if (tag === "textarea" || el.isContentEditable) return "textarea";
    if (tag === "input") return "input";
    if (role === "switch") return "switch";
    if (role === "tab") return "tab";
    return "other";
  }

  function push(el, source) {
    if (!isVisible(el)) return;
    const key = cssPath(el);
    if (!key || seen.has(key)) return;
    seen.add(key);
    const r = el.getBoundingClientRect();
    const scrollY = window.scrollY || document.documentElement.scrollTop || 0;
    const scrollX = window.scrollX || document.documentElement.scrollLeft || 0;
    const tag = (el.tagName || "").toLowerCase();
    const type = (el.getAttribute("type") || "").toLowerCase();
    const value = tag === "input" || tag === "textarea" || tag === "select"
      ? String(el.value || "").slice(0, 200) : "";
    out.push({
      id: "el-" + (++seq),
      category: classify(el),
      tag,
      input_type: type,
      role: el.getAttribute("role") || "",
      label: labelOf(el),
      text: textOf(el),
      value,
      name: el.getAttribute("name") || "",
      placeholder: el.getAttribute("placeholder") || "",
      selector: key,
      rect: {
        x: Math.round(r.left + scrollX),
        y: Math.round(r.top + scrollY),
        width: Math.round(r.width),
        height: Math.round(r.height),
      },
      source: source || "static",
      disabled: !!el.disabled || el.getAttribute("aria-disabled") === "true",
    });
  }

  const selectors = [
    "input:not([type='hidden'])", "textarea", "select", "button",
    "[role='button']", "[role='checkbox']", "[role='radio']",
    "[role='combobox']", "[role='switch']", "[role='tab']",
    "[contenteditable='true']", ".next-select", ".next-input input",
    ".next-number-picker input", ".image-upload-list-item", ".image-uploader",
    "label.next-checkbox-wrapper", "label.next-radio-wrapper",
    "[class*='uploader']", "[class*='upload-list']",
  ];

  for (const sel of selectors) {
    try { document.querySelectorAll(sel).forEach((el) => push(el, "static")); } catch (e) {}
  }

  return {
    page_url: location.href,
    page_title: document.title,
    viewport: { width: window.innerWidth, height: window.innerHeight },
    scroll: {
      width: Math.max(document.documentElement.scrollWidth, document.body.scrollWidth),
      height: Math.max(document.documentElement.scrollHeight, document.body.scrollHeight),
    },
    elements: out,
    scanned_at: Date.now(),
  };
})();
"""

_PROBE_KEYWORDS = (
    "添加", "展开", "更多", "选择", "编辑", "设置", "上传", "管理",
    "Add", "More", "Expand", "Edit", "Upload", "Manage", "Select",
)


def _group_into_sections(elements: List[Dict[str, Any]], gap: int = 72) -> List[Dict[str, Any]]:
    if not elements:
        return []
    sorted_els = sorted(elements, key=lambda e: (e["rect"]["y"], e["rect"]["x"]))
    sections: List[Dict[str, Any]] = []
    current: Optional[Dict[str, Any]] = None
    for el in sorted_els:
        y = el["rect"]["y"]
        if current is None or y - current["y_end"] > gap:
            title = (el.get("label") or el.get("text") or "未命名区域").strip()[:40] or "未命名区域"
            current = {
                "id": f"section-{len(sections) + 1}",
                "title": title,
                "y_start": y,
                "y_end": y + el["rect"]["height"],
                "elements": [el],
            }
            sections.append(current)
        else:
            current["elements"].append(el)
            current["y_end"] = max(current["y_end"], y + el["rect"]["height"])
    return sections


def _merge_scan_results(base: Dict[str, Any], extra: Dict[str, Any]) -> Dict[str, Any]:
    seen = {e["selector"] for e in base.get("elements", [])}
    for el in extra.get("elements", []):
        if el["selector"] not in seen:
            base["elements"].append(el)
            seen.add(el["selector"])
    return base


def _probe_dynamic_buttons(driver, raw: Dict[str, Any], max_clicks: int = 12) -> List[Dict[str, str]]:
    revealed: List[Dict[str, str]] = []
    buttons = [e for e in raw.get("elements", []) if e.get("category") == "button" and not e.get("disabled")]
    buttons.sort(key=lambda e: e["rect"]["y"])
    clicked = 0
    for btn in buttons:
        if clicked >= max_clicks:
            break
        label = f"{btn.get('label', '')} {btn.get('text', '')}"
        if not any(kw in label for kw in _PROBE_KEYWORDS):
            continue
        selector = btn.get("selector", "")
        if not selector:
            continue
        try:
            driver.execute_script(
                "const el = document.querySelector(arguments[0]); if(el){ el.scrollIntoView({block:'center'}); el.click(); }",
                selector,
            )
            time.sleep(0.8)
            extra = driver.execute_script(_SCAN_JS)
            before = len(raw.get("elements", []))
            _merge_scan_results(raw, extra)
            after = len(raw.get("elements", []))
            if after > before:
                revealed.append({
                    "button": label.strip()[:80],
                    "selector": selector,
                    "new_elements": str(after - before),
                })
            clicked += 1
        except Exception as exc:
            logger.debug(f"probe skip {selector}: {exc}")
    return revealed


def infer_page_type(url: str) -> Tuple[str, str]:
    """根据 URL 参数推断发品页面类型。"""
    try:
        qs = parse_qs(urlparse(url).query)
    except Exception:
        return "unknown", "未知页面"

    pub_type = (qs.get("pubType") or qs.get("pubtype") or [""])[0]
    behavior = (qs.get("behavior") or [""])[0]
    item_id = (qs.get("itemId") or qs.get("itemid") or [""])[0]
    cat_id = (qs.get("catId") or qs.get("catid") or qs.get("leafCatId") or [""])[0]

    if pub_type == "similarPost" or behavior == "copyNew":
        label = "复制发品"
        if cat_id:
            label += f" (类目 {cat_id})"
        return "copy_new", label
    if item_id:
        return "edit", f"编辑商品 (itemId={item_id})"
    if cat_id:
        return "new", f"新发品 (类目 {cat_id})"
    return "new", "新发品"


def _ensure_page_ready(driver, url: str, wait_seconds: float = 25.0) -> None:
    from selenium.common.exceptions import TimeoutException
    from selenium.webdriver.support.ui import WebDriverWait

    load_timeout = max(60, int(wait_seconds) + 20)
    try:
        driver.set_page_load_timeout(load_timeout)
    except Exception:
        pass
    try:
        driver.get(url)
    except TimeoutException:
        # 发品页较重，load 事件可能超时但 DOM 已部分可用
        try:
            driver.execute_script("window.stop();")
        except Exception:
            pass

    end = time.time() + wait_seconds
    while time.time() < end:
        try:
            if driver.execute_script("return document.readyState") == "complete":
                break
        except Exception:
            pass
        time.sleep(0.2)
    try:
        WebDriverWait(driver, min(15, wait_seconds)).until(
            lambda d: d.execute_script(
                "return document.body && document.body.innerText && document.body.innerText.length > 200"
            )
        )
    except Exception:
        pass
    time.sleep(1.5)


def _get_upload_menu_options(driver) -> List[str]:
    try:
        return list(
            driver.execute_script(
                """
                return [...new Set([...document.querySelectorAll('span,div,li,button,a,label')]
                  .map(n => (n.innerText||'').trim())
                  .filter(t => t && t.length<=30 && (t==='本地上传'||t==='从图片银行选取'||t.includes('图片银行'))))];
                """
            )
            or []
        )
    except Exception:
        return []


def _probe_product_image_workflow(driver, logs: List[str]) -> Dict[str, Any]:
    from selenium.webdriver.common.by import By
    from selenium.webdriver.common.action_chains import ActionChains

    steps: List[Dict[str, Any]] = []
    try:
        slots = [s for s in driver.find_elements(By.CSS_SELECTOR, ".image-upload-list-item, li.image-uploader-item") if s.is_displayed()]
        empty = [s for s in slots if "上传图片" in (s.text or "") or (s.text or "").strip() in ("+", "+\n上传图片")]
        steps.append({
            "step": 1, "action": "定位图片槽位",
            "detail": f"可见 {len(slots)} 个槽位，{len(empty)} 个空槽可上传",
            "selector": ".image-upload-list-item, li.image-uploader-item",
            "operable": bool(empty),
        })
        if not empty:
            return {
                "id": "product-images", "title": "商品图片", "type": "image_upload", "operable": False,
                "steps": steps, "automation_module": "image_uploader.upload_product_images",
                "automation_hint": "复制发品可能已有图；发新品需空槽",
            }
        slot = empty[0]
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", slot)
        time.sleep(0.5)
        ph = slot.find_elements(By.CSS_SELECTOR, ".image-upload-photobank-placeholder")
        target = ph[0] if ph else slot
        try:
            ActionChains(driver).move_to_element(target).click().perform()
        except Exception:
            driver.execute_script("arguments[0].click();", target)
        time.sleep(0.8)
        menu = _get_upload_menu_options(driver)
        steps.append({"step": 2, "action": "点击空槽", "detail": "弹出上传方式", "options": menu, "operable": bool(menu)})
        fi_before = int(driver.execute_script("return document.querySelectorAll('input[type=file]').length") or 0)
        from app.services.automation.image_uploader import _open_local_upload_on_slot
        local_ok = _open_local_upload_on_slot(driver, slot)
        time.sleep(1.0)
        fi_after = int(driver.execute_script("return document.querySelectorAll('input[type=file]').length") or 0)
        steps.append({
            "step": 3, "action": "选择「本地上传」", "clicked": local_ok,
            "file_inputs": f"{fi_before} -> {fi_after}", "operable": local_ok or fi_after > fi_before,
        })
        steps.append({
            "step": 4, "action": "选择「从图片银行选取」",
            "available": any("图片银行" in o for o in menu), "operable": any("图片银行" in o for o in menu),
        })
        logs.append(f"商品图片流程: 菜单={menu}, 本地上传={local_ok}")
        return {
            "id": "product-images", "title": "商品图片", "type": "image_upload", "operable": local_ok or fi_after > fi_before,
            "steps": steps, "upload_methods": menu,
            "local_upload": {"menu_text": "本地上传", "file_input_selector": "input[type='file']"},
            "photobank": {"menu_text": "从图片银行选取", "available": any("图片银行" in o for o in menu)},
            "automation_module": "image_uploader.upload_product_images",
            "automation_hint": "空槽->点击->本地上传->CDP注入 file input（见 image_uploader.py）",
        }
    except Exception as exc:
        logs.append(f"商品图片流程探测失败: {exc}")
        return {"id": "product-images", "title": "商品图片", "type": "image_upload", "operable": False, "steps": steps, "error": str(exc)}


def _find_spec_blocks(driver) -> List[Dict[str, Any]]:
    try:
        return list(driver.execute_script(
            """
            const SPEC_NAMES = ['颜色', '样式', '戒指尺寸', '尺寸', '材质'];
            const blocks = [], seen = new Set();
            function textOf(el) { return (el.innerText || el.textContent || '').replace(/\\s+/g, ' ').trim(); }
            function path(el) {
              if (!el || el.nodeType !== 1) return '';
              const parts = []; let cur = el;
              while (cur && cur.nodeType === 1 && parts.length < 8) {
                let part = cur.tagName.toLowerCase();
                if (cur.id) { parts.unshift(part + '#' + cur.id); break; }
                const cls = (cur.getAttribute('class') || '').trim().split(/\\s+/).filter(Boolean).slice(0, 2);
                if (cls.length) part += '.' + cls.join('.');
                parts.unshift(part); cur = cur.parentElement;
              }
              return parts.join(' > ');
            }
            function inspectBlock(container, specName) {
              if (!container || seen.has(specName)) return;
              seen.add(specName);
              const sw = Array.from(container.querySelectorAll('button,.next-switch,[role=switch],.next-switch-btn'))
                .find(el => textOf(el.parentElement || el).includes('添加规格图'));
              const adds = Array.from(container.querySelectorAll('a,button,span,div'))
                .filter(el => /^\\+?\\s*添加$/.test(textOf(el)) || textOf(el) === '+ 添加');
              const checkboxes = container.querySelectorAll("input[type='checkbox']");
              const textInputs = container.querySelectorAll("input:not([type='hidden']):not([type='checkbox']):not([type='radio'])");
              blocks.push({
                title: specName,
                block_selector: path(container),
                has_spec_image_switch: !!sw,
                spec_image_switch_selector: sw ? path(sw) : '',
                add_button_selectors: adds.slice(0, 2).map(path),
                value_input_count: textInputs.length,
                checkbox_count: checkboxes.length,
                upload_like_count: container.querySelectorAll("[class*='upload']").length,
                interaction: checkboxes.length > 4 && textInputs.length <= 2 ? 'checkbox_grid' : 'value_rows',
                text_preview: textOf(container).slice(0, 120),
              });
            }
            // 优先按规格项标题定位（颜色/样式/戒指尺寸各自独立）
            for (const label of document.querySelectorAll('.next-form-item-label, label, [class*="label"], h3, h4, span')) {
              const raw = textOf(label).replace(/[*:：]/g, '').trim();
              const hit = SPEC_NAMES.find(n => raw === n || raw.startsWith(n + ' ') || raw.endsWith(n));
              if (!hit) continue;
              let container = label.closest('.next-form-item')
                || label.closest('[class*="sku"]')
                || label.closest('[class*="spec"]')
                || label.closest('[class*="sale-prop"]')
                || label.parentElement?.parentElement?.parentElement;
              inspectBlock(container, hit);
            }
            // 兜底：struct-sku 大区块内按关键词再拆
            const skuRoot = document.getElementById('struct-sku') || document.querySelector('[id*="sku"]');
            if (skuRoot && blocks.length === 0) {
              for (const name of SPEC_NAMES) {
                for (const el of skuRoot.querySelectorAll('*')) {
                  const t = textOf(el);
                  if (t === name || t.startsWith(name + ' ')) {
                    const c = el.closest('.next-form-item') || el.parentElement?.parentElement;
                    inspectBlock(c, name);
                    break;
                  }
                }
              }
            }
            return blocks;
            """
        ) or [])
    except Exception:
        return []


def _probe_struct_section(
    driver,
    *,
    wf_id: str,
    title: str,
    struct_id: str,
    module: str,
    hint: str,
    wf_type: str = "form_field",
) -> Optional[Dict[str, Any]]:
    from selenium.webdriver.common.by import By

    roots = driver.find_elements(By.ID, struct_id)
    if not roots:
        return None
    root = roots[0]
    try:
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", root)
        time.sleep(0.3)
    except Exception:
        pass
    inputs = root.find_elements(By.CSS_SELECTOR, "input:not([type='hidden']), textarea, [contenteditable='true']")
    file_inputs = root.find_elements(By.CSS_SELECTOR, "input[type='file']")
    buttons = root.find_elements(By.CSS_SELECTOR, "button, [role='button']")
    steps = [
        {"step": 1, "action": "定位区块", "selector": f"#{struct_id}", "operable": True},
        {
            "step": 2,
            "action": "识别可填控件",
            "detail": f"输入框/文本域 {len(inputs)} 个，file input {len(file_inputs)} 个，按钮 {len(buttons)} 个",
            "operable": len(inputs) > 0 or len(file_inputs) > 0,
        },
    ]
    if file_inputs:
        steps.append({
            "step": 3, "action": "本地上传",
            "detail": "区块内存在 file input，可走 send_keys 或 CDP 注入",
            "selector": f"#{struct_id} input[type='file']",
            "operable": True,
        })
    required = wf_id in (
        "product-title",
        "product-keywords",
        "ladder-price",
        "text-detail",
        "detail-images",
    )
    return {
        "id": wf_id,
        "title": title,
        "type": wf_type,
        "operable": len(inputs) > 0 or len(file_inputs) > 0,
        "required": required,
        "steps": steps,
        "struct_id": struct_id,
        "automation_module": module,
        "automation_hint": hint,
    }


def _probe_attributes_workflow(driver, logs: List[str]) -> Optional[Dict[str, Any]]:
    try:
        info = driver.execute_script(
            """
            const items = [];
            for (const root of document.querySelectorAll('[id^="struct-"]')) {
              if (!root.querySelector('.sell-catProp-struct, .next-select, .next-input input')) continue;
              const label = root.querySelector('.next-form-item-label, label');
              const name = (label && (label.innerText||'').trim()) || root.id;
              if (!name || name.length > 40) continue;
              items.push({
                id: root.id,
                name: name.replace(/[*:：]/g,'').trim(),
                inputs: root.querySelectorAll('input:not([type=hidden]), textarea').length,
              });
            }
            return items.slice(0, 30);
            """
        ) or []
    except Exception:
        info = []
    if not info:
        return None
    logs.append(f"产品属性: 发现 {len(info)} 个属性区块")
    names = [x.get("name") for x in info[:8] if x.get("name")]
    return {
        "id": "product-attributes",
        "title": "产品属性",
        "type": "attributes",
        "operable": True,
        "attribute_count": len(info),
        "attribute_samples": names,
        "steps": [
            {"step": 1, "action": "定位属性区", "detail": f"共 {len(info)} 个属性容器（#struct-* + .sell-catProp-struct）", "operable": True},
            {"step": 2, "action": "逐项填写", "detail": "下拉/输入/标签模式，见 attribute_filler.py", "operable": True},
            {"step": 3, "action": "40%差异规则", "detail": "fill_all_attributes_with_diff 自动生成并比对历史", "operable": True},
        ],
        "automation_module": "attribute_filler.fill_all_attributes_with_diff",
        "automation_hint": "每个属性有 container_id + input_id，按 select_type 填写",
    }


def _probe_compliance_workflow(driver, logs: List[str]) -> Optional[Dict[str, Any]]:
    """动态发现合规/物流必填项（跨类目，不依赖固定标签表）。"""
    skip_structs = {
        "struct-ladderPrice", "struct-sku", "struct-detailImage", "struct-textDesc",
        "struct-companyDesc", "struct-companyImage", "struct-companyFaqDesc",
        "struct-productKeywords", "struct-icbuCatProp", "productTitle",
    }
    try:
        items = driver.execute_script(
            """
            const skip = new Set(arguments[0]);
            const map = new Map();
            function vis(el){ return el && el.offsetParent; }
            function norm(s){ return (s||'').replace(/[*:：\\s]+/g,' ').trim().slice(0,60); }
            function validLabel(lb){
              if(!lb || lb.length<3) return false;
              if(lb.startsWith('/')||lb.includes('共可添加')||lb.includes('已添加')) return false;
              const hasCn = /[\\u4e00-\\u9fa5]/.test(lb);
              if(!hasCn && /^[a-zA-Z][a-zA-Z0-9 ]*$/.test(lb)) return false;
              if(!hasCn && /^(left|right|pinbar|icbu|struct|post|pkg|sc|price|market|logistics)/i.test(lb)) return false;
              return true;
            }
            function add(label, structId, source){
              const lb = norm(label);
              if(!validLabel(lb)) return;
              if(/^(基本信息|商品信息|交易信息|物流信息)$/.test(lb)) return;
              if(!map.has(lb)) map.set(lb, {label: lb, struct_id: structId||'', source, required: true});
            }
            const body = document.body.innerText || '';
            const errRe = /([\\u4e00-\\u9fa5][\\u4e00-\\u9fa5A-Za-z0-9\\/\\\\\\.\\-]{0,28}?)\\s*(\\d+)\\s*项/g;
            let m;
            while((m = errRe.exec(body)) !== null){
              const lb = norm(m[1]);
              if(lb && !/报错|反馈|完善|项/.test(lb)) add(lb, '', 'error_feedback');
            }
            for(const root of document.querySelectorAll('[id^="struct-"]')){
              const id = root.id;
              if(skip.has(id)) continue;
              const t = (root.innerText||'').slice(0,300);
              if(!/HS|编码|体积|重量|样品|物流|合规|国别|阶梯|报关|包装|SKU|海关/i.test(t)) continue;
              let label = '';
              const lab = root.querySelector('.next-form-item-label, .label, h3, h4, legend');
              if(lab) label = norm(lab.innerText);
              if(!label) label = id.replace(/^struct-/,'').replace(/([A-Z])/g,' $1');
              add(label, id, 'struct');
            }
            for(const lab of document.querySelectorAll('.next-form-item-label, label, th')){
              if(!vis(lab)) continue;
              const raw = (lab.innerText||'').trim();
              if(!raw.includes('*')) continue;
              add(raw.replace(/\\*/g,''), '', 'required_label');
            }
            return Array.from(map.values());
            """,
            list(skip_structs),
        ) or []
    except Exception:
        items = []
    if not items:
        return None
    labels = [str(x.get("label") or "") for x in items if x.get("label")]
    logs.append(f"合规字段(动态): {labels}")
    return {
        "id": "compliance-fields",
        "title": "合规 / 物流 / 必填",
        "type": "compliance",
        "operable": True,
        "required": True,
        "fields": labels,
        "required_fields": labels,
        "compliance_items": items,
        "steps": [
            {"step": 1, "action": "动态扫描合规项", "detail": "侧栏报错 + struct-* + 带*标签", "operable": True},
            {"step": 2, "action": "自动填写", "detail": "按扫描清单逐项填写；无配置时用验收占位 a/1", "operable": True},
            {"step": 3, "action": "提交前校验", "detail": "verify_form_ready 动态解析报错反馈", "operable": True},
        ],
        "automation_module": "compliance_filler.fill_mandatory_compliance_fields",
        "automation_hint": "跨类目通用；字段来自本页扫描档案 compliance_fields",
    }


def _probe_spec_workflow(driver, block: Dict[str, Any], logs: List[str]) -> Dict[str, Any]:
    from selenium.webdriver.common.by import By

    title = block.get("title") or "规格"
    interaction = block.get("interaction") or "value_rows"
    steps: List[Dict[str, Any]] = [{
        "step": 1, "action": "定位规格区块", "selector": block.get("block_selector", ""),
        "detail": block.get("text_preview", ""),
        "interaction": interaction,
    }]
    operable = False
    if interaction == "checkbox_grid":
        cb_count = block.get("checkbox_count", 0)
        steps.append({
            "step": 2, "action": "勾选规格值（复选框网格）",
            "detail": f"共 {cb_count} 个可选项，如戒指尺寸 4~13；见 spec_selector.select_specifications",
            "operable": cb_count > 0,
        })
        operable = cb_count > 0
    else:
        sw_sel = block.get("spec_image_switch_selector") or ""
        if block.get("has_spec_image_switch") and sw_sel:
            try:
                sw = driver.find_element(By.CSS_SELECTOR, sw_sel)
                before = block.get("upload_like_count", 0)
                driver.execute_script("arguments[0].scrollIntoView({block:'center'});arguments[0].click();", sw)
                time.sleep(0.8)
                matched = next((b for b in _find_spec_blocks(driver) if b.get("title") == title), block)
                after = matched.get("upload_like_count", 0)
                steps.append({
                    "step": 2, "action": "打开「添加规格图」", "selector": sw_sel,
                    "reveals_upload": after > before, "operable": True,
                    "detail": "颜色/样式各自独立开关，可同时打开",
                })
                operable = True
            except Exception as exc:
                steps.append({"step": 2, "action": "打开「添加规格图」", "error": str(exc)})
        else:
            steps.append({"step": 2, "action": "添加规格图开关", "detail": "本区块未发现开关"})
        for add_sel in (block.get("add_button_selectors") or [])[:1]:
            try:
                btn = driver.find_element(By.CSS_SELECTOR, add_sel)
                before = block.get("value_input_count", 0)
                driver.execute_script("arguments[0].scrollIntoView({block:'center'});arguments[0].click();", btn)
                time.sleep(0.8)
                matched = next((b for b in _find_spec_blocks(driver) if b.get("title") == title), block)
                after = matched.get("value_input_count", 0)
                steps.append({
                    "step": 3, "action": "点击「+ 添加」", "selector": add_sel,
                    "rows": f"{before} -> {after}", "new_row": after > before, "operable": after > before,
                })
                if after > before:
                    operable = True
                    steps.append({
                        "step": 4, "action": "新行规格图上传",
                        "detail": "每行规格值旁图片按钮 → 本地上传/图片银行",
                        "operable": block.get("has_spec_image_switch"),
                    })
                break
            except Exception as exc:
                steps.append({"step": 3, "action": "点击「+ 添加」", "error": str(exc)})
    logs.append(f"规格[{title}] ({interaction}) 探测完成")
    return {
        "id": f"spec-{title}", "title": f"商品规格 - {title}", "type": "spec_attribute",
        "spec_name": title, "interaction": interaction, "operable": operable, "steps": steps,
        "switch_note": "颜色、样式各有独立「添加规格图」开关，可同时打开",
        "add_row_note": "点「+ 添加」新增规格行；戒指尺寸等为复选框网格",
        "automation_module": "spec_selector.select_specifications",
        "automation_hint": "checkbox 网格用 container_id 勾选；规格图按行 upload 按钮上传",
    }


def _probe_page_workflows(driver, logs: List[str]) -> List[Dict[str, Any]]:
    from app.services.automation.page_helpers import close_all_popups

    logs.append("开始功能流程探测（对齐自动发品全流程）…")
    workflows: List[Dict[str, Any]] = []

    def _add(wf: Optional[Dict[str, Any]]) -> None:
        if wf:
            workflows.append(wf)

    _add(_probe_product_image_workflow(driver, logs))
    close_all_popups(driver)

    _add(_probe_struct_section(
        driver, wf_id="product-title", title="商品标题", struct_id="productTitle",
        module="title_manager.fill_title", hint="input#productTitle 填写主标题",
    ))
    _add(_probe_struct_section(
        driver, wf_id="product-keywords", title="关键词", struct_id="struct-productKeywords",
        module="title_manager.fill_keywords", hint="textarea 填写关键词，逗号分隔",
    ))
    _add(_probe_attributes_workflow(driver, logs))
    _add(_probe_struct_section(
        driver, wf_id="ladder-price", title="阶梯价格", struct_id="struct-ladderPrice",
        module="price_setter.set_ladder_price", hint="表格填写 quantity/price，新增价格区间",
    ))
    _add(_probe_struct_section(
        driver, wf_id="sku-quantity", title="SKU 可售数量", struct_id="struct-sku",
        module="price_setter.set_ladder_price", hint="struct-sku 内填写可售数量",
        wf_type="sku",
    ))

    seen_specs: set = set()
    for block in _find_spec_blocks(driver):
        t = block.get("title")
        if not t or t in seen_specs:
            continue
        seen_specs.add(t)
        _add(_probe_spec_workflow(driver, block, logs))
        close_all_popups(driver)

    _add(_probe_struct_section(
        driver, wf_id="detail-images", title="详情图", struct_id="struct-detailImage",
        module="detail_filler.enhance_product_detail", hint="gallery 内 file input 本地上传",
        wf_type="image_upload",
    ))
    _add(_probe_struct_section(
        driver, wf_id="text-detail", title="文字详情", struct_id="struct-textDesc",
        module="detail_filler.enhance_product_detail", hint="contenteditable 富文本编辑",
    ))
    _add(_probe_struct_section(
        driver, wf_id="company-desc", title="公司介绍", struct_id="struct-companyDesc",
        module="detail_filler.enhance_product_detail", hint="公司描述文本区",
    ))
    _add(_probe_compliance_workflow(driver, logs))

    logs.append(f"功能流程探测完成，共 {len(workflows)} 项")
    return workflows


def _ensure_alibaba_logged_in(browser, target_url: str, logs: List[str], wait_seconds: float) -> bool:
    current = (browser.driver.current_url or "").lower()
    if "login.alibaba.com" not in current:
        return True
    logs.append("检测到登录页，尝试 Cookie 登录或等待手动登录…")
    if not browser.login():
        return False
    _ensure_page_ready(browser.driver, target_url, wait_seconds=wait_seconds)
    logs.append(f"登录后页面: {browser.driver.current_url}")
    return True


def _scan_current_page(
    driver,
    *,
    probe_buttons: bool,
    logs: List[str],
) -> Dict[str, Any]:
    from app.services.automation.page_helpers import close_all_popups

    close_all_popups(driver)
    raw = driver.execute_script(_SCAN_JS)
    if not isinstance(raw, dict):
        raise RuntimeError("页面扫描脚本未返回有效数据")

    probe_log: List[Dict[str, str]] = []
    workflows: List[Dict[str, Any]] = []

    # 功能地图：始终探测（商品图片、规格等操作流程）
    logs.append("开始生成功能地图（商品图片、规格操作流程）…")
    workflows = _probe_page_workflows(driver, logs)
    close_all_popups(driver)
    logs.append(f"功能地图完成，共 {len(workflows)} 项")

    if probe_buttons:
        logs.append("开始探测式点击（展开隐藏区域）…")
        probe_log = _probe_dynamic_buttons(driver, raw)
        close_all_popups(driver)
        logs.append(f"探测完成，触发 {len(probe_log)} 次有效展开")

    elements = raw.get("elements", [])
    sections = _group_into_sections(elements)
    categories: Dict[str, int] = {}
    for el in elements:
        cat = el.get("category", "other")
        categories[cat] = categories.get(cat, 0) + 1

    return {
        "url": raw.get("page_url") or driver.current_url,
        "title": raw.get("page_title") or "",
        "viewport": raw.get("viewport"),
        "scroll": raw.get("scroll"),
        "element_count": len(elements),
        "categories": categories,
        "elements": elements,
        "sections": sections,
        "probe_log": probe_log,
        "workflows": workflows,
        "workflow_count": len(workflows),
    }


def scan_publish_pages_batch(
    pages: List[Dict[str, str]],
    *,
    probe_buttons: bool = True,
    wait_seconds: float = 30.0,
) -> Dict[str, Any]:
    """批量扫描多个发品页，复用同一浏览器会话（仅登录一次）。"""
    from app.services.automation.browser_manager import BrowserManager

    browser = BrowserManager()
    started = time.time()
    logs: List[str] = []
    results: List[Dict[str, Any]] = []

    try:
        if not browser.setup():
            err = BrowserManager.get_last_setup_error() or "浏览器启动失败"
            return {"success": False, "error": err, "logs": logs, "pages": []}

        logs.append("浏览器已启动（批量模式，复用会话）")
        session_logged_in = False

        for index, page in enumerate(pages):
            name = (page.get("name") or "").strip() or f"页面 {index + 1}"
            target = (page.get("url") or "").strip()
            page_type, page_type_label = infer_page_type(target)
            item_logs: List[str] = []

            if not target:
                results.append({
                    "name": name,
                    "page_type": page_type,
                    "page_type_label": page_type_label,
                    "success": False,
                    "error": "URL 为空",
                    "url": "",
                    "logs": item_logs,
                })
                continue

            logs.append(f"[{index + 1}/{len(pages)}] 开始扫描: {name}")
            item_logs.append(f"打开: {target}")

            try:
                _ensure_page_ready(browser.driver, target, wait_seconds=wait_seconds)
                item_logs.append(f"当前地址: {browser.driver.current_url}")

                if "login.alibaba.com" in (browser.driver.current_url or "").lower():
                    if not _ensure_alibaba_logged_in(browser, target, item_logs, wait_seconds):
                        results.append({
                            "name": name,
                            "page_type": page_type,
                            "page_type_label": page_type_label,
                            "success": False,
                            "error": "需要登录阿里巴巴账号",
                            "needs_login": True,
                            "url": target,
                            "logs": item_logs,
                        })
                        continue
                    session_logged_in = True
                elif not session_logged_in and "post.alibaba.com" in (browser.driver.current_url or ""):
                    session_logged_in = True

                page_started = time.time()
                scanned = _scan_current_page(
                    browser.driver,
                    probe_buttons=probe_buttons,
                    logs=item_logs,
                )
                results.append({
                    "name": name,
                    "page_type": page_type,
                    "page_type_label": page_type_label,
                    "success": True,
                    "duration_seconds": round(time.time() - page_started, 2),
                    "logs": item_logs,
                    **scanned,
                })
                logs.append(f"[{index + 1}/{len(pages)}] 完成: {name}，{scanned['element_count']} 个元素")
            except Exception as exc:
                logger.exception(f"批量扫描失败: {name}")
                item_logs.append(f"错误: {exc}")
                results.append({
                    "name": name,
                    "page_type": page_type,
                    "page_type_label": page_type_label,
                    "success": False,
                    "error": str(exc),
                    "url": target,
                    "logs": item_logs,
                })
                logs.append(f"[{index + 1}/{len(pages)}] 失败: {name} - {exc}")

        succeeded = sum(1 for r in results if r.get("success"))
        failed = len(results) - succeeded
        return {
            "success": succeeded > 0,
            "total": len(results),
            "succeeded": succeeded,
            "failed": failed,
            "pages": results,
            "duration_seconds": round(time.time() - started, 2),
            "logs": logs,
            "error": None if succeeded > 0 else "所有页面扫描均失败",
        }
    except Exception as exc:
        logger.exception("批量发品页扫描失败")
        logs.append(f"错误: {exc}")
        return {
            "success": False,
            "error": str(exc),
            "logs": logs,
            "pages": results,
            "total": len(pages),
            "succeeded": sum(1 for r in results if r.get("success")),
            "failed": len(pages) - sum(1 for r in results if r.get("success")),
        }
    finally:
        browser.quit()


def scan_publish_page(
    url: str,
    *,
    probe_buttons: bool = True,
    wait_seconds: float = 30.0,
) -> Dict[str, Any]:
    target = (url or "").strip()
    if not target:
        return {"success": False, "error": "URL 不能为空", "logs": []}
    page_type, page_type_label = infer_page_type(target)
    batch = scan_publish_pages_batch(
        [{"name": page_type_label, "url": target}],
        probe_buttons=probe_buttons,
        wait_seconds=wait_seconds,
    )
    if not batch.get("pages"):
        return {
            "success": False,
            "error": batch.get("error") or "扫描失败",
            "logs": batch.get("logs") or [],
        }
    page = batch["pages"][0]
    if not page.get("success"):
        return {
            "success": False,
            "error": page.get("error") or "扫描失败",
            "logs": batch.get("logs") or page.get("logs") or [],
            "needs_login": page.get("needs_login"),
        }
    return {
        "success": True,
        "page_type": page_type,
        "page_type_label": page_type_label,
        "url": page.get("url"),
        "title": page.get("title") or "",
        "viewport": page.get("viewport"),
        "scroll": page.get("scroll"),
        "element_count": page.get("element_count", 0),
        "categories": page.get("categories") or {},
        "elements": page.get("elements") or [],
        "sections": page.get("sections") or [],
        "probe_log": page.get("probe_log") or [],
        "workflows": page.get("workflows") or [],
        "workflow_count": page.get("workflow_count", 0),
        "duration_seconds": batch.get("duration_seconds"),
        "logs": batch.get("logs") or [],
    }

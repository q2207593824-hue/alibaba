# -*- coding: utf-8 -*-
"""Compliance fields filler for Alibaba publish page (category-agnostic)."""
import re
import time
from typing import Any, Dict, List, Optional, Tuple

from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from app.core.logger import setup_logger

logger = setup_logger("compliance_filler")
MIN_PRODUCT_IMAGES = 4

ACCEPT_TEXT = "a"
ACCEPT_NUM = "1"
_SKIP_COMPLIANCE_LABELS = frozenset({"产品图片", "商品图片", "产品主图"})
_PLACEHOLDER_ATTR_VALUES = frozenset({"a", "1", "请输入", "请选择", "请输入或者选择"})
_ERROR_ITEM_PREFIX = "错误项"
_JUNK_LABEL_RE = re.compile(
    r"^(left|right|pinbar|top|bottom|struct|post|export|pkg|sc|price|market|logistics|tradable|box|new|icbu)\b",
    re.I,
)


def is_valid_compliance_label(label: str) -> bool:
    """过滤扫描/页面解析产生的无效合规标签。"""
    lb = str(label or "").strip()
    if len(lb) < 3:
        return False
    if lb.startswith("/") or "共可添加" in lb or "已添加" in lb or "关联已有" in lb:
        return False
    if re.search(r"报错|反馈|完善|项$", lb):
        return False
    has_cn = bool(re.search(r"[\u4e00-\u9fa5]", lb))
    if _JUNK_LABEL_RE.match(lb) and not has_cn:
        return False
    if re.fullmatch(r"[a-zA-Z][a-zA-Z0-9 ]*", lb) and not has_cn:
        return False
    return True


def filter_compliance_labels(labels: List[str]) -> List[str]:
    return list(dict.fromkeys(lb for lb in labels if is_valid_compliance_label(lb)))


def _is_numeric_field(label: str) -> bool:
    text = str(label or "")
    keys = (
        "\u4ef7", "\u6570\u91cf", "\u9636\u68af", "\u7f16\u7801",
        "\u4f53\u79ef", "\u91cd\u91cf", "\u6837\u54c1", "HS", "SKU", "sku",
    )
    return any(k in text for k in keys)


def _placeholder_values(label: str, count: int = 1) -> List[str]:
    n = max(1, int(count or 1))
    if _is_numeric_field(label):
        if "HS" in label.upper() or "\u7f16\u7801" in label:
            return ["1111111111"] * n
        if "\u4f53\u79ef" in label or "\u91cd\u91cf" in label:
            return [ACCEPT_NUM] * min(4, n)
        return [ACCEPT_NUM] * n
    return [ACCEPT_TEXT] * n


def discover_error_feedback_labels(body_text: str) -> List[str]:
    """仅从「报错反馈」区解析中文标签（避免 left/pinbar 等噪声）。"""
    labels: List[str] = []
    for m in re.finditer(
        r"([\u4e00-\u9fa5][\u4e00-\u9fa5A-Za-z0-9/\\.\\-]{0,28}?)\s*(\d+)\s*项",
        body_text or "",
    ):
        lb = m.group(1).strip()
        if is_valid_compliance_label(lb):
            labels.append(lb)
    return list(dict.fromkeys(labels))


def discover_compliance_labels_on_page(driver) -> List[str]:
    try:
        body = driver.find_element(By.TAG_NAME, "body").text or ""
    except Exception:
        body = ""
    return discover_error_feedback_labels(body)


def _resolve_price_hint(price_hint: Optional[float], acceptance: bool) -> Optional[float]:
    if price_hint is not None and price_hint > 0:
        return price_hint
    return float(ACCEPT_NUM) if acceptance else None


def _fill_generic_compliance_field(driver, label: str, values: List[str]) -> bool:
    if _fill_inputs_near_label(driver, label, values):
        logger.info(f"compliance generic filled: {label}={values}")
        return True
    _scroll_to_text(driver, label)
    time.sleep(0.25)
    return bool(_fill_inputs_near_label(driver, label, values))


def _fill_compliance_by_label(
    driver,
    label: str,
    *,
    price_hint: Optional[float],
    ladder_rows: Optional[List[Tuple[int, int]]],
    acceptance: bool,
    sku_outer_id: Optional[str] = None,
) -> bool:
    lb = str(label or "").strip()
    if not lb or lb in _SKIP_COMPLIANCE_LABELS:
        return True
    if "\u56fd\u522b\u5316\u9636\u68af\u4ef7" in lb or ("\u56fd\u522b" in lb and "\u9636\u68af" in lb):
        from app.services.automation.country_region import country_ladder_price_required
        if not country_ladder_price_required(driver):
            logger.info("国家/地区未勾选，跳过国别化阶梯价")
            return True
        return _fill_country_ladder_price(driver, price_hint, ladder_rows)
    if "HS" in lb.upper() or "\u7f8e\u56fd\u5173\u7a0e" in lb:
        code = str(sku_outer_id or "").strip()
        if not code:
            logger.warning(f"未配置商品编码，无法完成美国 HS 编码维护: {lb}")
            return False
        from app.services.automation.price_setter import _fill_sku_outer_id
        logger.info("美国 HS 编码维护与商品编码同一处，使用商品编码填写")
        _fill_sku_outer_id(driver, code)
        return True
    if "\u4f53\u79ef" in lb or "\u91cd\u91cf" in lb or "\u7269\u6d41\u5305\u88c5" in lb:
        dims = _placeholder_values(lb, 4) if acceptance else ["20", "15", "10", "0.5"]
        return _fill_package_weight_volume(driver, dims) or _fill_inputs_near_label(driver, lb, dims)
    if "\u6837\u54c1" in lb or "SKU" in lb.upper():
        return _fill_sample_sku(driver, price_hint)
    if "\u56fe\u7247" in lb or "image" in lb.lower():
        return _fill_compliance_images(driver, lb)
    if "\u6761\u7801" in lb or "barcode" in lb.lower():
        return _fill_compliance_barcode(driver, lb)
    if lb.startswith(_ERROR_ITEM_PREFIX):
        if "\u56fe\u7247" in lb or "image" in lb.lower():
            return _fill_compliance_images(driver, lb)
        logger.info(f"compliance: 跳过报错占位符填充 → {lb}")
        return False
    if acceptance:
        return _fill_generic_compliance_field(driver, lb, _placeholder_values(lb, 2))
    logger.debug(f"compliance: 非验收模式跳过通用占位 → {lb}")
    return False


def fill_mandatory_compliance_fields(
    driver,
    price_hint: Optional[float] = None,
    ladder_rows: Optional[List[Tuple[int, int]]] = None,
    compliance_fields: Optional[List[Any]] = None,
    acceptance: bool = True,
    sku_outer_id: Optional[str] = None,
) -> bool:
    """按扫描档案/页面动态清单填写合规项。"""
    price_hint = _resolve_price_hint(price_hint, acceptance)
    labels: List[str] = []
    for item in compliance_fields or []:
        if isinstance(item, dict):
            lb = str(item.get("label") or "").strip()
        else:
            lb = str(getattr(item, "label", "") or "").strip()
        if lb:
            labels.append(lb)
    labels = filter_compliance_labels(labels)
    page_labels = filter_compliance_labels(discover_compliance_labels_on_page(driver))
    labels = list(dict.fromkeys(labels + page_labels))
    if not labels:
        labels = [
            "\u56fd\u522b\u5316\u9636\u68af\u4ef7",
            "\u7f8e\u56fd\u5173\u7a0eHS\u7f16\u7801\u7ef4\u62a4",
            "\u77e5\u8bc6\u4ea7\u6743\u56fe\u7247",
            "\u77e5\u8bc6\u4ea7\u6743\u516c\u53f8\u56fe\u7247",
            "\u4ea7\u54c1\u56fd\u9645\u6761\u7801\u591a\u9009",
        ]
    ok = True
    for label in list(dict.fromkeys(labels)):
        try:
            if not _fill_compliance_by_label(
                driver,
                label,
                price_hint=price_hint,
                ladder_rows=ladder_rows,
                acceptance=acceptance,
                sku_outer_id=sku_outer_id,
            ):
                logger.warning(f"compliance field not filled: {label}")
        except Exception as exc:
            logger.warning(f"compliance field error [{label}]: {exc}")
            ok = False
    return ok


def verify_form_ready(driver) -> Tuple[bool, List[str]]:
    issues: List[str] = []
    from app.services.automation.image_uploader import count_real_product_images

    img_count = count_real_product_images(driver)
    if img_count < MIN_PRODUCT_IMAGES:
        issues.append(f"product images insufficient: {img_count}/{MIN_PRODUCT_IMAGES}")

    try:
        flags = driver.execute_script(
            """
            const root = document.querySelector('.sell-error, .next-form-item-help, #struct-scImages')
                || document.body;
            const t = (root.innerText || root.textContent || '').slice(0, 8000);
            return {
              missingImg: t.includes('请上传相关产品图片'),
              hasFeedback: t.includes('报错反馈'),
              snippet: t.includes('报错反馈') ? t : ''
            };
            """
        ) or {}
        if flags.get("missingImg"):
            issues.append("missing product images")
        if flags.get("hasFeedback"):
            for label in discover_error_feedback_labels(str(flags.get("snippet") or "")):
                issues.append(f"error feedback: {label}")
    except Exception:
        pass

    return len(issues) == 0, issues


def _count_section_image_previews(driver, section_id: str) -> int:
    try:
        section = driver.find_element(By.ID, section_id)
    except Exception:
        return 0
    try:
        return int(
            driver.execute_script(
                """
                const root = arguments[0];
                let n = 0;
                for (const img of root.querySelectorAll('img')) {
                  const src = (img.getAttribute('src') || '').trim();
                  if (!src || /blank/i.test(src)) continue;
                  const w = img.offsetWidth || img.clientWidth || 0;
                  if (w > 10) n++;
                }
                return n;
                """,
                section,
            )
            or 0
        )
    except Exception:
        return 0


def _compliance_detail_images_sufficient(driver) -> bool:
    return _count_section_image_previews(driver, "struct-detailImage") >= 4


def _compliance_company_images_sufficient(driver) -> bool:
    return _count_section_image_previews(driver, "struct-companyImage") >= 2


def _resolve_sample_image_path() -> Optional[str]:
    """取首图目录中任意一张图用于合规图片上传。"""
    import os
    from app.core.settings import get_config

    cfg = get_config()
    for folder in (
        str(getattr(cfg.paths, "primary_image_dir", "") or ""),
        str(getattr(cfg.paths, "main_image_dir", "") or ""),
    ):
        if not folder or not os.path.isdir(folder):
            continue
        for name in sorted(os.listdir(folder)):
            if name.lower().endswith((".jpg", ".jpeg", ".png")):
                return os.path.abspath(os.path.join(folder, name))
    return None


def _fill_compliance_images(driver, label: str) -> bool:
    """合规区图片上传：定位 label 附近 file input 并注入本地图。"""
    from app.services.automation.image_uploader import _cdp_set_input_files

    lb = str(label or "").strip()
    if "详情" in lb and _compliance_detail_images_sufficient(driver):
        logger.info(f"compliance image skip (detail already filled): {lb}")
        return True
    if "公司" in lb and "知识产权" not in lb and _compliance_company_images_sufficient(driver):
        logger.info(f"compliance image skip (company already filled): {lb}")
        return True

    img_path = _resolve_sample_image_path()
    if not img_path:
        logger.warning(f"compliance image: no local image for {label}")
        return False
    _scroll_to_text(driver, label)
    time.sleep(0.3)
    found = driver.execute_script(
        """
        const label = arguments[0];
        function vis(el){return el&&el.offsetParent;}
        for(const node of document.querySelectorAll('span,div,label,th,td,h3,h4')){
          const t=(node.innerText||'').trim();
          if(!t.includes(label)||!vis(node))continue;
          const root=node.closest('[id^=struct-],.next-form-item,section,tr')||node.parentElement;
          if(!root)continue;
          for(const inp of root.querySelectorAll('input[type=file]')){
            if(vis(inp)){inp.setAttribute('data-compliance-upload','1');return true;}
          }
          for(const btn of root.querySelectorAll('button,span,a')){
            const bt=(btn.innerText||'').trim();
            if(/上传|本地上传|Upload/i.test(bt)&&vis(btn)){btn.click();return 'clicked';}
          }
        }
        return false;
        """,
        label,
    )
    if found == "clicked":
        time.sleep(0.5)
    inputs = driver.find_elements(By.CSS_SELECTOR, "input[type='file'][data-compliance-upload='1']")
    if not inputs:
        logger.warning(f"compliance image: no scoped file input for {label}")
        return False
    for inp in inputs[:1]:
        try:
            if _cdp_set_input_files(driver, inp, [img_path]):
                logger.info(f"compliance image uploaded: {label}")
                time.sleep(1)
                return True
            inp.send_keys(img_path)
            logger.info(f"compliance image sent: {label}")
            time.sleep(1)
            return True
        except Exception:
            continue
    logger.warning(f"compliance image not uploaded: {label}")
    return False


def _fill_compliance_barcode(driver, label: str) -> bool:
    """产品国际条码：勾选第一项或填占位。"""
    _scroll_to_text(driver, label)
    time.sleep(0.3)
    ok = driver.execute_script(
        """
        const label=arguments[0];
        function vis(el){return el&&el.offsetParent;}
        for(const node of document.querySelectorAll('span,div,label,th')){
          const t=(node.innerText||'').trim();
          if(!t.includes(label)||!vis(node))continue;
          const root=node.closest('[id^=struct-],.next-form-item,section')||node.parentElement;
          if(!root)continue;
          const cb=root.querySelector('input[type=checkbox],.next-checkbox input');
          if(cb&&!cb.checked){cb.click();return true;}
          const sel=root.querySelector('select,.next-select');
          if(sel){sel.click();return true;}
        }
        return false;
        """,
        label,
    )
    if ok:
        time.sleep(0.5)
        driver.execute_script(
            """
            for(const opt of document.querySelectorAll('.next-menu-item,.next-select-menu-item,li[role=option]')){
              if(opt.offsetParent){opt.click();return;}
            }
            """
        )
        logger.info(f"compliance barcode filled: {label}")
        return True
    return _fill_generic_compliance_field(driver, label, [ACCEPT_TEXT])


def _scroll_to_text(driver, text: str) -> bool:
    script = (
        "const needle=arguments[0];"
        "for(const el of document.querySelectorAll('span,div,label,h2,h3,h4,th,td,a,button')){"
        "const t=(el.innerText||'').trim();"
        "if(t.includes(needle)&&el.offsetParent){el.scrollIntoView({block:'center'});return true;}}"
        "return false;"
    )
    return bool(driver.execute_script(script, text))


def _fill_inputs_near_label(driver, label: str, values: List[str]) -> bool:
    script = (
        "const label=arguments[0],values=arguments[1];"
        "function vis(el){return el&&el.offsetParent;}"
        "function inCatProp(inp){"
        "  const c=inp.closest('[id^=struct-p-],[id^=struct-catProp],#struct-catProp,.sell-catProp-struct');"
        "  return !!c;"
        "}"
        "function fill(inp,val){"
        "if(!inp||inp.disabled||inCatProp(inp))return false;"
        "inp.value=val;"
        "inp.dispatchEvent(new Event('input',{bubbles:true}));"
        "inp.dispatchEvent(new Event('change',{bubbles:true}));"
        "inp.blur();return true;}"
        "for(const node of document.querySelectorAll('span,div,label,th,td')){"
        "const t=(node.innerText||'').trim();"
        "if(!t.includes(label)||!vis(node))continue;"
        "const root=node.closest('[id^=struct-],.next-form-item,tr,section')||node.parentElement;"
        "if(!root||root.id==='struct-catProp'||root.querySelector('.sell-catProp-struct'))continue;"
        "let idx=0;"
        "for(const inp of root.querySelectorAll('input:not([type=hidden]):not([type=checkbox])')){"
        "if(!vis(inp)||inCatProp(inp)||(inp.value||'').trim())continue;"
        "if(idx>=values.length)break;fill(inp,values[idx++]);}"
        "if(idx>0)return idx;}return 0;"
    )
    filled = driver.execute_script(script, label, [str(v) for v in values])
    return bool(filled)


def _read_main_ladder_from_page(driver) -> List[Tuple[int, int]]:
    """从 struct-ladderPrice 读取已填阶梯价。"""
    try:
        rows = driver.execute_script(
            """
            const root = document.getElementById('struct-ladderPrice');
            if (!root) return [];
            const out = [];
            for (const row of root.querySelectorAll('tr.next-table-row, tr[class*=table-row]')) {
              const q = row.querySelector('input[role=input-quantity], input[placeholder*=数量], input[placeholder*=Quantity]');
              const p = row.querySelector('input[role=input-price], input[placeholder*=价格], input[placeholder*=Price]');
              const qty = q && (q.value || '').trim();
              const price = p && (p.value || '').trim();
              if (qty && price) out.push([qty, price]);
            }
            return out;
            """
        ) or []
        result: List[Tuple[int, int]] = []
        for item in rows:
            try:
                result.append((int(str(item[0])), int(float(str(item[1])))))
            except (TypeError, ValueError, IndexError):
                continue
        return result
    except Exception:
        return []


def _country_ladder_incomplete(driver) -> bool:
    """仅当页面已显示国别化阶梯价报错时视为未完成（避免误拦）。"""
    try:
        body_text = driver.find_element(By.TAG_NAME, "body").text or ""
        if re.search(r"国别化阶梯价\s*\d+\s*项", body_text):
            return True
        return bool(
            driver.execute_script(
                """
                const body = document.body.innerText || '';
                return /国别化阶梯价\\s*\\d+\\s*项/.test(body)
                  || /error feedback.*国别化/i.test(body);
                """
            )
        )
    except Exception:
        return False


def _click_country_ladder_entry(driver) -> bool:
    """点击报错反馈或「去设置」入口，打开国别化阶梯价编辑区。"""
    try:
        return bool(
            driver.execute_script(
                """
                function vis(el){return el&&el.offsetParent;}
                for (const el of document.querySelectorAll('a,span,div,li,button')) {
                  const t = (el.innerText || '').trim();
                  if (!vis(el) || !t) continue;
                  if (t.includes('国别化阶梯价')) { el.click(); return true; }
                }
                for (const el of document.querySelectorAll('button, a, span')) {
                  const t = (el.innerText || '').trim();
                  if (!vis(el)) continue;
                  if (!/去设置|设置|编辑|Configure|Set/i.test(t)) continue;
                  const root = el.closest('[id^=struct-], section, div');
                  if (root && (root.innerText || '').includes('国别化阶梯价')) {
                    el.click(); return true;
                  }
                }
                return false;
                """
            )
        )
    except Exception:
        return False


def _selenium_fill_country_inputs(driver, tiers: List[Tuple[int, int]], fallback: str) -> bool:
    """用 send_keys 填写国别化阶梯价（React 表单比 JS 赋值更可靠）。"""
    from selenium.webdriver.common.by import By
    from selenium.webdriver.common.keys import Keys

    pairs = tiers or [(1, int(fallback or 4))]
    struct_ids = (
        "struct-countryLadderPrice",
        "struct-regionLadderPrice",
        "struct-nationalLadderPrice",
        "struct-overseasLadderPrice",
    )
    roots = []
    for sid in struct_ids:
        try:
            el = driver.find_element(By.ID, sid)
            roots.append(el)
        except Exception:
            pass
    if not roots:
        try:
            roots = driver.find_elements(
                By.XPATH,
                "//*[contains(@id,'struct-')][.//*[contains(text(),'国别化阶梯价') or contains(text(),'国别')]]",
            )
        except Exception:
            roots = []

    filled = 0
    for root in roots:
        try:
            driver.execute_script("arguments[0].scrollIntoView({block:'center'});", root)
            time.sleep(0.5)
            inputs = root.find_elements(By.CSS_SELECTOR, "input:not([type=checkbox]):not([type=hidden])")
            visible = [i for i in inputs if i.is_displayed()]
            pi = 0
            for inp in visible:
                if (inp.get_attribute("value") or "").strip():
                    continue
                qty, price = pairs[min(pi // 2, len(pairs) - 1)]
                val = str(qty) if pi % 2 == 0 else str(price)
                inp.click()
                inp.send_keys(Keys.CONTROL + "a")
                inp.send_keys(val)
                driver.execute_script(
                    "arguments[0].dispatchEvent(new Event('change',{bubbles:true})); arguments[0].blur();",
                    inp,
                )
                pi += 1
                filled += 1
                if pi >= len(pairs) * 2:
                    break
        except Exception:
            continue
    return filled > 0


def _fill_country_ladder_price(
    driver,
    price_hint: Optional[float],
    ladder_rows: Optional[List[Tuple[int, int]]] = None,
) -> bool:
    try:
        _click_country_ladder_entry(driver)
        _scroll_to_text(driver, "\u56fd\u522b\u5316\u9636\u68af\u4ef7")
        time.sleep(0.4)

        tiers = list(ladder_rows or [])
        if not tiers:
            tiers = _read_main_ladder_from_page(driver)
        if not tiers and price_hint:
            tiers = [(1, int(price_hint))]

        fallback_price = str(int(price_hint or (tiers[0][1] if tiers else int(ACCEPT_NUM))))
        tier_payload = [[str(q), str(p)] for q, p in tiers]

        result = driver.execute_script(
            """
            const tiers = arguments[0], fallback = arguments[1];
            function vis(el){return el&&el.offsetParent;}
            function fill(inp,val){
              if(!inp||!vis(inp))return false;
              inp.focus();
              inp.value=val;
              inp.dispatchEvent(new Event('input',{bubbles:true}));
              inp.dispatchEvent(new Event('change',{bubbles:true}));
              inp.blur();
              return true;
            }
            function findCountryRoot(){
              let root = document.getElementById('struct-countryLadderPrice')
                || document.querySelector('[id*=countryLadder], [id*=CountryLadder]');
              if (root) return root;
              for (const el of document.querySelectorAll('[id^=struct-], section, div')) {
                const t = (el.innerText || '');
                if (t.includes('国别化阶梯价') && vis(el)) return el;
              }
              return null;
            }
            function clickSyncIn(root){
              if (!root) return false;
              for (const el of root.querySelectorAll('button, span, a, div')) {
                const t = (el.innerText || '').trim();
                if (!vis(el)) continue;
                if ((/同步|复制|应用|一键/.test(t)) && (/阶梯|国别|价格|价/.test(t))) {
                  el.click();
                  return true;
                }
              }
              return false;
            }
            function confirmDialog(){
              for (const btn of document.querySelectorAll('button')) {
                const t = (btn.innerText || '').trim();
                if (!vis(btn)) continue;
                if (/确定|确认|应用|OK|同步/.test(t)) { btn.click(); return true; }
              }
              return false;
            }
            function fillTierPairs(inputs, tierList, fb){
              const pairs = tierList.length ? tierList : [['1', fb]];
              let n = 0;
              let pi = 0;
              for (const inp of inputs) {
                if (!vis(inp) || (inp.value || '').trim()) { n++; continue; }
                const pair = pairs[Math.floor(pi / 2)] || pairs[0];
                const val = (pi % 2 === 0) ? pair[0] : pair[1];
                if (fill(inp, val)) pi++;
                n++;
              }
              return pi;
            }
            function fillUsRow(){
              const root = findCountryRoot();
              const tierList = tiers.length ? tiers : [['1', fallback]];
              if (root) {
                for (const el of root.querySelectorAll('i, span, button, div')) {
                  const t = (el.innerText || '').trim();
                  if (vis(el) && (/展开|更多|Expand/i.test(t) || el.className.includes('expand'))) {
                    try { el.click(); } catch(e) {}
                  }
                }
              }
              for (const row of document.querySelectorAll('tr, [class*=row], [class*=Row]')) {
                const t = (row.innerText || '');
                if (!(t.includes('美国') || t.includes('United States') || /\\bUS\\b/.test(t))) continue;
                const inputs = [...row.querySelectorAll('input:not([type=checkbox]):not([type=hidden])')].filter(vis);
                if (!inputs.length) continue;
                const filled = fillTierPairs(inputs, tierList, fallback);
                if (filled) return 'us_row';
              }
              if (root) {
                const filled = fillTierPairs(
                  [...root.querySelectorAll('input:not([type=checkbox]):not([type=hidden])')].filter(vis),
                  tierList,
                  fallback
                );
                if (filled) return 'root_tiers';
              }
              return '';
            }
            function fillAllEmptyInRoot(root){
              if (!root) return '';
              let n = 0;
              const prices = tiers.length ? tiers.map(t => t[1]) : [fallback];
              const qtys = tiers.length ? tiers.map(t => t[0]) : ['1'];
              for (const inp of root.querySelectorAll('input:not([type=checkbox]):not([type=hidden])')) {
                if (!vis(inp) || (inp.value || '').trim()) continue;
                const val = (n % 2 === 0) ? (qtys[Math.floor(n/2)] || '1') : (prices[Math.floor(n/2)] || fallback);
                fill(inp, val);
                n++;
              }
              return n ? 'generic' : '';
            }

            const root = findCountryRoot();
            if (clickSyncIn(root)) {
              confirmDialog();
            }
            let mode = fillUsRow();
            if (!mode) mode = fillAllEmptyInRoot(root);
            if (!mode && clickSyncIn(root)) {
              confirmDialog();
              mode = 'sync_retry';
            }
            if (!mode) mode = fillUsRow() || fillAllEmptyInRoot(root);
            return mode;
            """,
            tier_payload,
            fallback_price,
        )

        if _selenium_fill_country_inputs(driver, tiers, fallback_price):
            result = result or "selenium_inputs"

        time.sleep(0.8)
        if click_confirm := driver.execute_script(
            """
            for (const btn of document.querySelectorAll('button')) {
              const t = (btn.innerText || '').trim();
              if (t && /确定|确认|应用/.test(t) && btn.offsetParent) { btn.click(); return true; }
            }
            return false;
            """
        ):
            logger.info("country ladder confirm dialog clicked")
            time.sleep(1.5)

        if result:
            logger.info(f"country ladder price filled via {result}")
            return True

        if not _country_ladder_incomplete(driver):
            logger.info("country ladder price section has no visible errors")
            return True

        logger.warning("country ladder price not filled and page shows errors")
        return False
    except Exception as e:
        logger.warning(f"country ladder price error: {e}")
        return False


def _fill_us_hs_code(driver, hs_code: str = "1111111111") -> bool:
    try:
        _scroll_to_text(driver, "HS编码")
        time.sleep(0.3)
        hs_script = (
            "const code=arguments[0];"
            "function vis(el){return el&&el.offsetParent;}"
            "function fill(inp){"
            "if(!inp||!vis(inp)||(inp.value||'').trim().length>=6)return !!((inp.value||'').trim());"
            "inp.value=code;"
            "inp.dispatchEvent(new Event('input',{bubbles:true}));"
            "inp.dispatchEvent(new Event('change',{bubbles:true}));return true;}"
            "for(const lb of ['美国HS','HS编码','HS Code','海关编码']){"
            "for(const el of document.querySelectorAll('span,label,div,th')){"
            "const t=(el.innerText||'').trim();"
            "if(!t.includes(lb)||!vis(el))continue;"
            "const root=el.closest('[id^=struct-],.next-form-item,tr,section')||el.parentElement;"
            "for(const inp of (root?root.querySelectorAll('input'):[])){if(fill(inp))return true;}}}"
            "for(const inp of document.querySelectorAll('input[placeholder*=HS],input[name*=hs],input[id*=hs]')){"
            "if(fill(inp))return true;}return false;"
        )
        if driver.execute_script(hs_script, hs_code):
            logger.info(f"US HS code filled: {hs_code}")
            return True
        logger.warning("US HS code not filled")
        return False
    except Exception as e:
        logger.warning(f"US HS code error: {e}")
        return False


def _fill_package_weight_volume(driver, dims: Optional[List[str]] = None) -> bool:
    try:
        _scroll_to_text(driver, "\u4f53\u79ef\u4e0e\u91cd\u91cf")
        time.sleep(0.35)
        values = dims or [ACCEPT_NUM, ACCEPT_NUM, ACCEPT_NUM, ACCEPT_NUM]
        if _fill_inputs_near_label(driver, "\u4f53\u79ef\u4e0e\u91cd\u91cf", values):
            logger.info("package volume/weight filled")
            return True
        if _fill_inputs_near_label(driver, "\u7269\u6d41\u5305\u88c5", values):
            return True
        logger.warning("package volume/weight not filled")
        return False
    except Exception as e:
        logger.warning(f"package volume/weight error: {e}")
        return False


def _fill_sample_sku(driver, price_hint: Optional[float]) -> bool:
    try:
        from app.core.settings import get_config
        from app.services.automation.price_setter import set_sample_service

        cfg = get_config()
        sample_price = int(price_hint or int(ACCEPT_NUM))
        if set_sample_service(driver, cfg.price, ladder_max_usd=sample_price):
            return True
        _scroll_to_text(driver, "\u6837\u54c1")
        time.sleep(0.35)
        sample_price = str(int(price_hint or int(ACCEPT_NUM)))
        result = driver.execute_script(
            """
            const price = arguments[0];
            function vis(el){return el&&el.offsetParent;}
            function fill(inp,val){
              if(!inp||!vis(inp))return false;
              inp.focus(); inp.value=val;
              inp.dispatchEvent(new Event('input',{bubbles:true}));
              inp.dispatchEvent(new Event('change',{bubbles:true}));
              inp.blur(); return true;
            }
            for(const el of document.querySelectorAll('span,label,div,button')){
              const t=(el.innerText||'').trim();
              if((t.includes('样品')||t.includes('Sample')) && (t.includes('支持')||t.includes('提供')||t.includes('订购'))){
                const root=el.closest('[id^=struct-],.next-form-item,section')||el.parentElement;
                const cb=root&&root.querySelector('input[type=checkbox],.next-checkbox input');
                if(cb && !cb.checked) cb.click();
              }
            }
            for(const inp of document.querySelectorAll(
              '[data-name*=sample] input,[data-name*=Sample] input,td[class*=sample] input,td[data-name*=sample] input'
            )){
              if(fill(inp,price)) return 'sample_col';
            }
            for(const el of document.querySelectorAll('span,label,div,th')){
              const t=(el.innerText||'').trim();
              if(t.includes('样品') && (t.includes('价')||t.includes('Price'))){
                const root=el.closest('tr,[id^=struct-],.next-form-item,section')||el.parentElement;
                const inp=root&&root.querySelector('input:not([type=checkbox])');
                if(inp && fill(inp,price)) return 'sample_price';
              }
            }
            const sku=document.getElementById('struct-sku');
            if(sku){
              sku.scrollIntoView({block:'center'});
              const headers=[...sku.querySelectorAll('th,span,div')];
              for(const h of headers){
                const t=(h.innerText||'').trim();
                if(!t.includes('样品')) continue;
                const cell=h.closest('th,td')||h.parentElement;
                const colIdx=[...cell.parentElement.children].indexOf(cell);
                for(const row of sku.querySelectorAll('tr')){
                  const cells=row.querySelectorAll('td');
                  if(colIdx>=0 && cells[colIdx]){
                    const inp=cells[colIdx].querySelector('input');
                    if(inp && fill(inp,price)) return 'sku_col';
                  }
                }
              }
              for(const inp of sku.querySelectorAll('input[placeholder],input[role=input]')){
                const ph=(inp.placeholder||'').toLowerCase();
                if(ph.includes('样品')||ph.includes('sample')){
                  if(fill(inp,price)) return 'sku_ph';
                }
              }
            }
            return '';
            """,
            sample_price,
        )
        if result:
            logger.info(f"sample SKU filled via {result}")
            return True
        try:
            sku_area = WebDriverWait(driver, 5).until(
                EC.presence_of_element_located((By.ID, "struct-sku"))
            )
            driver.execute_script("arguments[0].scrollIntoView({block:'center'});", sku_area)
            cells = sku_area.find_elements(
                By.XPATH,
                ".//td[contains(@class,'sample') or contains(@data-name,'sample') or contains(@data-name,'Sample')]",
            )
            for cell in cells:
                for inp in cell.find_elements(By.XPATH, ".//input"):
                    if not (inp.get_attribute("value") or "").strip():
                        inp.click()
                        inp.send_keys(Keys.CONTROL + "a")
                        inp.send_keys(sample_price)
                        driver.execute_script(
                            "arguments[0].dispatchEvent(new Event('change',{bubbles:true}));",
                            inp,
                        )
                        logger.info("sample SKU filled in sku column")
                        return True
        except Exception:
            pass
        logger.warning("sample SKU not filled")
        return False
    except Exception as e:
        logger.warning(f"sample SKU error: {e}")
        return False

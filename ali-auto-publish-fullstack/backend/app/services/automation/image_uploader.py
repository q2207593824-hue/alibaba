# -*- coding: utf-8 -*-
"""
图片上传自动化
重构自: main_属性融合.py 中的 upload_via_input_element() 等函数

【如何修改】
- 修改上传方式（Shadow DOM穿透 vs 文件对话框）→ 修改 _upload_batch() 方法
- 修改上传等待逻辑 → 修改 _wait_for_uploaded_count() 方法
- 修改图片清除逻辑 → 修改 _clear_existing_images() 方法
"""
import os
import re
import time
import logging
from contextlib import contextmanager
from typing import List, Optional, Tuple

from app.core.logger import setup_logger

logger = setup_logger("image_uploader")

_COUNT_IMAGES_JS = """
const root = document.getElementById('struct-scImages') || document;
const items = root.querySelectorAll('.image-upload-list-item, li.image-uploader-item');
let filled = 0;
for (const item of items) {
  if (!item.offsetParent) continue;
  const text = (item.innerText || '').trim();
  const cls = (item.className || '').toLowerCase();
  if (cls.includes('uploading') || cls.includes('loading')) { filled++; continue; }
  if (text === '上传图片' || text === '+' || (text.includes('上传图片') && text.length <= 12)) continue;
  if (item.querySelector('.image-upload-img-bottoom-action-delete, [class*="action-delete"]')) {
    filled++; continue;
  }
  const inner = (item.innerHTML || '').toLowerCase();
  if (inner.includes('background-image') && !text.includes('上传图片')) { filled++; continue; }
  for (const img of item.querySelectorAll('img')) {
    const src = (img.getAttribute('src') || '').trim();
    if (/^(https?:|\\/\\/|blob:|data:)/i.test(src) && !src.toLowerCase().includes('placeholder')) {
      filled++; break;
    }
  }
}
return filled;
"""

_HAS_FILLED_IMAGES_JS = """
const items = document.querySelectorAll('.image-upload-list-item');
if (!items.length) return false;
const html = items[0].outerHTML || '';
return html.length > 0 && !html.includes('上传图片');
"""


@contextmanager
def _upload_fast_context(driver):
    """上传阶段关闭 implicit wait，避免 find_elements 每次阻塞数秒。"""
    old_wait = 3
    try:
        old_wait = driver.timeouts.implicit_wait
    except Exception:
        pass
    try:
        driver.implicitly_wait(0)
        yield
    finally:
        try:
            driver.implicitly_wait(old_wait)
        except Exception:
            pass


def _count_real_images_fast(driver) -> int:
    """单次 JS 统计已填充主图槽位（上传热路径专用）。"""
    try:
        return int(driver.execute_script(_COUNT_IMAGES_JS) or 0)
    except Exception:
        return 0


def _poll_upload_target(
    driver,
    before: int,
    need: int,
    *,
    timeout: float = 8.0,
    interval: float = 0.05,
) -> bool:
    """短轮询直到槽位数达标（仅在上传注入后、未立即达标时使用）。"""
    target = before + max(1, int(need))
    end = time.time() + max(0.5, float(timeout))
    while time.time() < end:
        current = _count_real_images_fast(driver)
        if current >= target:
            logger.info(f"上传检测通过: {before} -> {current} (目标>={target})")
            return True
        time.sleep(interval)
    return _count_real_images_fast(driver) >= target


def natural_key(s: str):
    return [int(c) if c.isdigit() else c.lower() for c in re.split(r'(\d+)', s)]


def _count_upload_slots(driver) -> int:
    """可见图片槽位数（含复制发品页已填充的槽）。"""
    from selenium.webdriver.common.by import By

    try:
        items = driver.find_elements(By.CSS_SELECTOR, ".image-upload-list-item, li.image-uploader-item")
        return len([e for e in items if e.is_displayed()])
    except Exception:
        return 0


def count_real_product_images(driver) -> int:
    """统计页面上已有有效产品图（非空「上传图片」占位）。"""
    return _count_real_images(driver)


def _slot_is_empty(item) -> bool:
    from selenium.webdriver.common.by import By

    text = (item.text or "").strip()
    cls = (item.get_attribute("class") or "").lower()
    if "uploading" in cls or "loading" in cls:
        return False
    if text in ("上传图片", "+") or text == "+\n上传图片":
        return True
    if "上传图片" in text and len(text) <= 12:
        return True
    if item.find_elements(By.CSS_SELECTOR, ".image-upload-img-bottoom-action-delete, [class*='action-delete']"):
        return False
    inner = (item.get_attribute("innerHTML") or "").lower()
    if "background-image" in inner and "上传图片" not in text:
        return False
    for img in item.find_elements(By.CSS_SELECTOR, "img"):
        src = (img.get_attribute("src") or "").strip()
        if src.startswith(("http", "//", "blob:")) and "placeholder" not in src.lower():
            return False
    return True


def _count_filled_image_slots(driver) -> int:
    """统计已填充的图片槽位（含 background-image、删除按钮，不仅 img[src]）。"""
    from selenium.webdriver.common.by import By

    try:
        items = driver.find_elements(
            By.CSS_SELECTOR, "#struct-scImages .image-upload-list-item, #struct-scImages li.image-uploader-item"
        )
        if not items:
            items = driver.find_elements(
                By.CSS_SELECTOR, ".image-upload-list-item, li.image-uploader-item"
            )
        return sum(1 for item in items if item.is_displayed() and not _slot_is_empty(item))
    except Exception:
        return 0


def _count_real_images(driver) -> int:
    """统计有效产品图数量：img[src] 与已填充槽位取较大值。"""
    from selenium.webdriver.common.by import By

    img_count = 0
    try:
        scoped = "#struct-scImages .image-upload-list-item img, #struct-scImages li.image-uploader-item img"
        img_elems = driver.find_elements(By.CSS_SELECTOR, scoped)
        if not img_elems:
            img_elems = driver.find_elements(
                By.CSS_SELECTOR, ".image-upload-list-item img, li.image-uploader-item img"
            )
        for img in img_elems:
            src = (img.get_attribute("src") or "").strip()
            if src.startswith(("http", "//", "blob:", "data:")) and "placeholder" not in src.lower():
                img_count += 1
    except Exception:
        pass

    slot_count = _count_filled_image_slots(driver)
    return max(img_count, slot_count)


def _find_empty_slots(driver):
    from selenium.webdriver.common.by import By

    slots = []
    for item in driver.find_elements(By.CSS_SELECTOR, ".image-upload-list-item, li.image-uploader-item"):
        if item.is_displayed() and _slot_is_empty(item):
            slots.append(item)
    return slots


def _resolve_cdp_node_id(driver, element) -> Optional[int]:
    """通过 CDP 获取元素的 nodeId（支持 Shadow DOM pierce）。"""
    import uuid

    mark = f"cdp-{uuid.uuid4().hex[:10]}"
    try:
        driver.execute_script(
            "arguments[0].setAttribute('data-cdp-mark', arguments[1]);",
            element,
            mark,
        )
        doc = driver.execute_cdp_cmd("DOM.getDocument", {"depth": -1, "pierce": True})
        for selector in (f'input[data-cdp-mark="{mark}"]', f'[data-cdp-mark="{mark}"]'):
            node = driver.execute_cdp_cmd(
                "DOM.querySelector",
                {"nodeId": doc["root"]["nodeId"], "selector": selector},
            )
            node_id = node.get("nodeId")
            if node_id:
                return node_id
    except Exception as e:
        logger.warning(f"  解析 CDP nodeId 失败: {e}")
    return None


def _cdp_set_input_files(driver, file_input, paths: List[str], *, mark: str = "") -> bool:
    """通过 Chrome DevTools Protocol 向 file input 注入本地文件。"""
    abs_paths = [os.path.abspath(p) for p in paths if os.path.isfile(p)]
    if not abs_paths or file_input is None:
        return False
    try:
        node_id = _resolve_cdp_node_id(driver, file_input)
        if not node_id:
            return False
        driver.execute_cdp_cmd("DOM.setFileInputFiles", {"nodeId": node_id, "files": abs_paths})
        files_len = 0
        if mark:
            files_len = int(
                driver.execute_script(
                    """
                    const inp = document.querySelector('input[data-sc-batch-mark="' + arguments[0] + '"]');
                    if (!inp) return 0;
                    inp.dispatchEvent(new Event('input', {bubbles: true}));
                    inp.dispatchEvent(new Event('change', {bubbles: true}));
                    return (inp.files && inp.files.length) || 0;
                    """,
                    mark,
                )
                or 0
            )
        else:
            try:
                driver.execute_script(
                    """
                    const el = arguments[0];
                    el.dispatchEvent(new Event('input', {bubbles: true}));
                    el.dispatchEvent(new Event('change', {bubbles: true}));
                    """,
                    file_input,
                )
                files_len = int(
                    driver.execute_script(
                        "return (arguments[0].files && arguments[0].files.length) || 0;", file_input
                    )
                    or 0
                )
            except Exception:
                files_len = 0
        return bool(files_len and files_len >= len(abs_paths))
    except Exception as e:
        logger.warning(f"  CDP setFileInputFiles 失败: {e}")
        return False


SHADOW_PENETRATE_JS = """
function findInputDeep(root) {
    if (!root) return null;
    let input = root.querySelector("input[type='file'][accept*='image']");
    if (!input) input = root.querySelector("input[type='file']");
    if (input) return input;
    let all = root.querySelectorAll('*');
    for (let el of all) {
        if (el.shadowRoot) {
            let found = findInputDeep(el.shadowRoot);
            if (found) return found;
        }
    }
    return null;
}
let spans = document.querySelectorAll('span, div, li, button, a, label');
for (let s of spans) {
    if (s.innerText && s.innerText.trim() === '本地上传' && s.offsetParent !== null) {
        s.click();
        break;
    }
}
let input = findInputDeep(document);
if (input) {
    input.style.display = 'block';
    input.style.visibility = 'visible';
    input.style.opacity = '1';
    input.style.position = 'fixed';
    input.style.top = '10px';
    input.style.left = '10px';
    input.style.width = '200px';
    input.style.height = '50px';
    input.style.zIndex = '999999';
    input.style.pointerEvents = 'auto';
    return input;
}
return null;
"""


SLOT_SHADOW_JS = """
const slot = arguments[0];
function findInputDeep(root) {
    if (!root) return null;
    let input = root.querySelector("input[type='file'][accept*='image']");
    if (!input) input = root.querySelector("input[type='file']");
    if (input) return input;
    const all = root.querySelectorAll ? root.querySelectorAll('*') : [];
    for (const el of all) {
        if (el.shadowRoot) {
            const found = findInputDeep(el.shadowRoot);
            if (found) return found;
        }
    }
    return null;
}
function clickLocal(scope) {
    if (!scope) return false;
    for (const n of scope.querySelectorAll('span, div, li, button, a, label')) {
        const t = (n.innerText || '').trim();
        if (t === '本地上传' && n.offsetParent !== null) {
            n.click();
            return true;
        }
    }
    return false;
}
if (slot) clickLocal(slot);
clickLocal(document);
let input = (slot ? findInputDeep(slot) : null) || findInputDeep(document);
if (input) {
    input.style.display = 'block';
    input.style.visibility = 'visible';
    input.style.opacity = '1';
    input.style.position = 'fixed';
    input.style.top = '10px';
    input.style.left = '10px';
    input.style.width = '200px';
    input.style.height = '50px';
    input.style.zIndex = '999999';
    input.style.pointerEvents = 'auto';
    return input;
}
return null;
"""


def _prepare_file_input_without_photobank(driver, slot=None):
    """获取 file input：只点槽内「本地上传」，不点击图片银行占位符。"""
    from app.services.automation.page_helpers import close_photobank_popup

    close_photobank_popup(driver)
    if slot is None:
        empty = _find_empty_slots(driver)
        slot = empty[0] if empty else None
    if slot is not None:
        try:
            driver.execute_script("arguments[0].scrollIntoView({block:'center'});", slot)
            time.sleep(0.15)
        except Exception:
            pass
        file_input = driver.execute_script(SLOT_SHADOW_JS, slot)
        if file_input:
            return file_input, slot
        marked = _find_file_input_for_slot(driver, slot)
        if marked:
            return marked, slot
        for cand in _collect_file_input_candidates(driver, slot):
            return cand, slot
    file_input = driver.execute_script(SHADOW_PENETRATE_JS)
    return file_input, slot


def _upload_target_met(driver, before: int, count: int) -> bool:
    return _count_real_images_fast(driver) >= before + max(1, int(count))


def _wait_image_count_increase(
    driver,
    before: int,
    *,
    timeout: float = 18.0,
    interval: float = 0.35,
    min_delta: int = 1,
) -> bool:
    """等待已上传图数量增加（补传等回退路径）。"""
    return _poll_upload_target(
        driver, before, min_delta, timeout=timeout, interval=min(interval, 0.1)
    )


def _upload_one_fast(driver, abs_path: str) -> bool:
    """单张快速上传：悬停空槽 + 本地上传 + send_keys，减少等待。"""
    from app.services.automation.page_helpers import close_photobank_popup

    if not os.path.isfile(abs_path):
        return False

    before = _count_real_images(driver)
    for attempt in range(3):
        try:
            close_photobank_popup(driver)
            empty = _find_empty_slots(driver)
            slot = empty[0] if empty else None
            if slot is None:
                return _count_real_images(driver) > before

            driver.execute_script(
                """
                const slot = arguments[0];
                slot.scrollIntoView({block:'center'});
                const ph = slot.querySelector('.image-upload-photobank-placeholder') || slot;
                ph.dispatchEvent(new MouseEvent('mouseover', {bubbles:true}));
                for (const n of document.querySelectorAll('span,div,button,label,a')) {
                    const t = (n.innerText || '').trim();
                    if (t === '本地上传' && n.offsetParent) { n.click(); return true; }
                }
                return false;
                """,
                slot,
            )
            time.sleep(0.25)
            close_photobank_popup(driver)
            inp = _find_file_input_for_slot(driver, slot) or driver.execute_script(SLOT_SHADOW_JS, slot)
            if not inp:
                _open_local_upload_on_slot(driver, slot)
                time.sleep(0.2)
                inp = _find_file_input_for_slot(driver, slot) or driver.execute_script(SLOT_SHADOW_JS, slot)
            if not inp:
                continue
            try:
                inp.send_keys(abs_path)
            except Exception:
                if not _cdp_set_input_files(driver, inp, [abs_path]):
                    continue
            if _wait_image_count_increase(driver, before, timeout=15, interval=0.2):
                close_photobank_popup(driver)
                return True
        except Exception as exc:
            logger.warning(f"快速上传尝试 {attempt + 1} 失败: {str(exc)[:60]}")

    return _count_real_images(driver) > before


def _upload_one_via_slot(driver, abs_path: str, file_input=None) -> Tuple[bool, Optional[object]]:
    """单张上传：悬停空槽 + 本地上传 + CDP/send_keys，关闭图片银行弹窗。"""
    from app.services.automation.page_helpers import close_photobank_popup

    if not os.path.isfile(abs_path):
        return False, file_input

    before = _count_real_images(driver)
    for attempt in range(5):
        try:
            close_photobank_popup(driver)
            empty = _find_empty_slots(driver)
            slot = empty[0] if empty else None
            inp = None
            if file_input is not None and attempt == 0:
                try:
                    inp = file_input
                except Exception:
                    inp = None
            if inp is None:
                inp = _capture_shadow_file_input(driver, slot)
            if inp is None and slot is not None:
                _open_local_upload_on_slot(driver, slot)
                time.sleep(0.5)
                close_photobank_popup(driver)
                inp = _capture_shadow_file_input(driver, slot) or _find_file_input_for_slot(driver, slot)

            if inp:
                try:
                    inp.send_keys(abs_path)
                    if _wait_image_count_increase(driver, before, timeout=12, interval=0.2):
                        close_photobank_popup(driver)
                        return True, None
                except Exception as exc:
                    logger.warning(f"send_keys 失败: {str(exc)[:60]}")

            if inp and _cdp_set_input_files(driver, inp, [abs_path]):
                if _wait_image_count_increase(driver, before, timeout=12, interval=0.2):
                    close_photobank_popup(driver)
                    return True, None

            for cand in reversed(_collect_file_input_candidates(driver, slot)):
                try:
                    cand.send_keys(abs_path)
                    if _wait_image_count_increase(driver, before, timeout=10, interval=0.2):
                        close_photobank_popup(driver)
                        return True, None
                except Exception:
                    if _cdp_set_input_files(driver, cand, [abs_path]):
                        if _wait_image_count_increase(driver, before, timeout=10, interval=0.2):
                            close_photobank_popup(driver)
                            return True, None
            file_input = None
        except Exception as exc:
            file_input = None
            logger.warning(f"槽位上传尝试 {attempt + 1} 失败: {str(exc)[:80]}")

    return _count_real_images(driver) > before, None


def _get_uploaded_count(driver) -> int:
    """当前页面有效产品图数量（兼容 background-image 槽位）。"""
    return _count_real_images(driver)


def _capture_shadow_file_input(driver, slot=None):
    """悬停空槽占位符 + 影子穿透，返回 file input 元素。"""
    from selenium.webdriver.common.by import By
    from selenium.webdriver.common.action_chains import ActionChains
    from app.services.automation.page_helpers import close_photobank_popup

    close_photobank_popup(driver)
    target_slot = slot
    if target_slot is None:
        empty = _find_empty_slots(driver)
        target_slot = empty[0] if empty else None

    if target_slot is not None:
        try:
            driver.execute_script("arguments[0].scrollIntoView({block:'center'});", target_slot)
            time.sleep(0.3)
            ph = target_slot.find_elements(By.CSS_SELECTOR, ".image-upload-photobank-placeholder")
            hover_el = ph[0] if ph else target_slot
            ActionChains(driver).move_to_element(hover_el).pause(0.2).perform()
            time.sleep(0.2)
            close_photobank_popup(driver)
            _open_local_upload_on_slot(driver, target_slot)
            time.sleep(0.35)
            close_photobank_popup(driver)
            file_input = driver.execute_script(SLOT_SHADOW_JS, target_slot)
            if file_input:
                return file_input
            marked = _find_file_input_for_slot(driver, target_slot)
            if marked:
                return marked
            return driver.execute_script(SHADOW_PENETRATE_JS)
        except Exception:
            pass

    placeholders = driver.find_elements(By.CLASS_NAME, "image-upload-photobank-placeholder")
    if placeholders:
        try:
            ActionChains(driver).move_to_element(placeholders[0]).perform()
        except Exception:
            pass
        time.sleep(0.5)
        close_photobank_popup(driver)
    file_input = driver.execute_script(SHADOW_PENETRATE_JS)
    if file_input:
        return file_input
    if placeholders:
        driver.execute_script("arguments[0].click();", placeholders[0])
        time.sleep(0.5)
        close_photobank_popup(driver)
        return driver.execute_script(SHADOW_PENETRATE_JS)
    return None


def _prepare_sc_images_upload_mark(driver) -> Optional[str]:
    """悬停 sc-images 槽位并标记 multiple file input，返回用于重新定位的 mark。"""
    import uuid
    from selenium.webdriver.common.action_chains import ActionChains
    from selenium.webdriver.common.by import By
    from app.services.automation.page_helpers import close_photobank_popup

    mark = f"sc-batch-{uuid.uuid4().hex[:8]}"
    close_photobank_popup(driver)
    try:
        root = driver.find_element(By.ID, "struct-scImages")
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", root)
    except Exception:
        root = None

    placeholders = []
    if root:
        placeholders = root.find_elements(By.CSS_SELECTOR, ".image-upload-photobank-placeholder")
    if not placeholders:
        placeholders = driver.find_elements(By.CSS_SELECTOR, ".image-upload-photobank-placeholder")

    target = placeholders[0] if placeholders else root
    if target is None:
        return None

    try:
        ActionChains(driver).move_to_element(target).pause(0.2).perform()
    except Exception:
        driver.execute_script(
            "arguments[0].dispatchEvent(new MouseEvent('mouseover',{bubbles:true}));", target
        )
    time.sleep(0.15)
    close_photobank_popup(driver)

    tagged = driver.execute_script(
        """
        const mark = arguments[0];
        const selectors = [
          '.sc-images-upload-dropdown input[type=file][multiple]',
          '.sc-images-upload-dropdown input[type=file]',
          '.sc-images-menu input[type=file][multiple]',
          '.sc-images-menu input[type=file]',
          '#struct-scImages input[type=file][multiple]',
          '#struct-scImages input[type=file]',
        ];
        for (const sel of selectors) {
          for (const inp of document.querySelectorAll(sel)) {
            if (!inp) continue;
            inp.setAttribute('data-sc-batch-mark', mark);
            inp.style.display = 'block';
            inp.style.visibility = 'visible';
            inp.style.opacity = '1';
            inp.style.position = 'fixed';
            inp.style.top = '0';
            inp.style.left = '0';
            inp.style.width = '120px';
            inp.style.height = '40px';
            inp.style.zIndex = '2147483647';
            return true;
          }
        }
        return false;
        """,
        mark,
    )
    return mark if tagged else None


def _find_sc_images_input_by_mark(driver, mark: str):
    from selenium.webdriver.common.by import By

    sel = f'input[data-sc-batch-mark="{mark}"]'
    found = driver.find_elements(By.CSS_SELECTOR, sel)
    return found[-1] if found else None


def _capture_sc_images_file_input(driver, slot=None):
    """
    悬停商品图槽位，从 sc-images 下拉气泡获取支持 multiple 的本地上传 input。
    参考: struct-scImages + .sc-images-upload-dropdown
    """
    from selenium.webdriver.common.action_chains import ActionChains
    from selenium.webdriver.common.by import By
    from app.services.automation.page_helpers import close_photobank_popup

    close_photobank_popup(driver)
    try:
        root = driver.find_element(By.ID, "struct-scImages")
    except Exception:
        root = None

    if root:
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", root)
        time.sleep(0.25)
        placeholders = root.find_elements(By.CSS_SELECTOR, ".image-upload-photobank-placeholder")
    else:
        placeholders = driver.find_elements(By.CSS_SELECTOR, ".image-upload-photobank-placeholder")

    target = slot
    if target is None and placeholders:
        target = placeholders[0]
    if target is None:
        return None

    try:
        ActionChains(driver).move_to_element(target).pause(0.45).perform()
    except Exception:
        driver.execute_script(
            "arguments[0].dispatchEvent(new MouseEvent('mouseover',{bubbles:true}));", target
        )
    time.sleep(0.35)
    close_photobank_popup(driver)

    file_input = driver.execute_script(
        """
        const menus = document.querySelectorAll(
          '.sc-images-upload-dropdown, .sc-images-menu, .menu-button-balloon-wrapper.sc-images-upload-dropdown'
        );
        for (const menu of menus) {
          if (!menu.offsetParent && menu.style.display === 'none') continue;
          const inp = menu.querySelector(
            'input[type=file][multiple], input[type=file][accept*="image"], .upload-select-inner input[type=file]'
          );
          if (inp) {
            inp.style.display = 'block';
            inp.style.visibility = 'visible';
            inp.style.opacity = '1';
            inp.style.position = 'fixed';
            inp.style.top = '0';
            inp.style.left = '0';
            inp.style.width = '120px';
            inp.style.height = '40px';
            inp.style.zIndex = '2147483647';
            return inp;
          }
        }
        return null;
        """
    )
    if file_input:
        return file_input

    for sel in (
        ".sc-images-upload-dropdown input[type='file']",
        ".sc-images-menu input[type='file']",
        "#struct-scImages input[type='file'][multiple]",
    ):
        found = driver.find_elements(By.CSS_SELECTOR, sel)
        if found:
            return found[-1]
    return None


def upload_via_sc_images_batch(driver, file_paths: List[str]) -> bool:
    """struct-scImages 悬停槽位 → 本地上传 multiple input → 一次上传多张。"""
    from app.services.automation.page_helpers import close_photobank_popup

    abs_paths = [os.path.abspath(p) for p in file_paths if os.path.isfile(p)]
    if not abs_paths:
        return False

    before = _count_real_images_fast(driver)
    need = len(abs_paths)
    if _upload_target_met(driver, before, need):
        logger.info(f"sc-images 跳过：已有 {before} 张")
        return True

    combined = "\n".join(abs_paths)

    for attempt in range(2):
        if _upload_target_met(driver, before, need):
            logger.info(f"sc-images 第{attempt + 1}次前已满足: {_count_real_images_fast(driver)} 张")
            return True

        close_photobank_popup(driver)
        mark = _prepare_sc_images_upload_mark(driver)
        if not mark:
            logger.warning(f"sc-images 未捕获 file input (第 {attempt + 1} 次)")
            time.sleep(0.1)
            continue

        file_input = _find_sc_images_input_by_mark(driver, mark)
        if not file_input:
            time.sleep(0.1)
            continue

        _cdp_set_input_files(driver, file_input, abs_paths, mark=mark)
        if _upload_target_met(driver, before, need):
            logger.info(f"sc-images CDP 注入后已满足: {_count_real_images_fast(driver)} 张")
            close_photobank_popup(driver)
            return True
        if _poll_upload_target(driver, before, need, timeout=8):
            close_photobank_popup(driver)
            return True

        file_input = _find_sc_images_input_by_mark(driver, mark)
        if file_input:
            try:
                file_input.send_keys(combined)
                logger.info(f"sc-images send_keys 批量 {need} 张")
            except Exception as exc:
                logger.warning(f"sc-images send_keys 失败: {str(exc)[:80]}")

        if _upload_target_met(driver, before, need):
            logger.info(f"sc-images send_keys 后已满足: {_count_real_images_fast(driver)} 张")
            close_photobank_popup(driver)
            return True
        if _poll_upload_target(driver, before, need, timeout=6):
            close_photobank_popup(driver)
            return True

    if _upload_target_met(driver, before, need):
        logger.info(f"sc-images 结束但页面已有图: {_count_real_images_fast(driver)}")
        return True
    return False


def upload_via_input_element(driver, file_paths: List[str]) -> bool:
    """商品主图上传：暂仅 sc-images 批量（方式1），其他回退已关闭。"""
    if not file_paths:
        logger.error("上传文件列表为空")
        return False

    abs_paths = [os.path.abspath(p) for p in file_paths]
    for p in abs_paths:
        if not os.path.isfile(p):
            logger.error(f"文件不存在: {p}")
            return False

    logger.info(f"准备上传 {len(abs_paths)} 张图片（仅 sc-images 批量）")

    try:
        if upload_via_sc_images_batch(driver, abs_paths):
            return True
        logger.error("sc-images 批量上传失败（影子穿透/逐张回退已暂时禁用）")
        return False

        # --- 以下回退路径暂时注释，验收仅测 sc-images 批量 ---
        # from selenium.webdriver.common.action_chains import ActionChains
        # from selenium.webdriver.common.by import By
        # from app.services.automation.page_helpers import close_photobank_popup
        # combined_paths = "\n".join(abs_paths)
        # before = _count_real_images(driver)
        # for attempt in range(3):
        #     ...
        # logger.warning("影子批量未成功，交由槽位补传")
        # return False
    except Exception as e:
        logger.error(f"图片上传异常: {e}", exc_info=True)
        return False


def wait_for_uploaded_count(
    driver,
    expected_count: int,
    timeout: float = 30.0,
    interval: float = 0.3,
) -> Tuple[bool, Optional[str]]:
    """等待缩略图数量达到预期（对齐老脚本 wait_for_uploaded_count）。"""
    from selenium.webdriver.common.by import By
    from app.services.automation.page_helpers import debug_print_html

    start = time.time()
    used_sel = ".image-upload-list-item"
    while time.time() - start < timeout:
        real = _count_real_images(driver)
        slots = _count_filled_image_slots(driver)
        if max(real, slots) >= expected_count:
            logger.info(f"当前检测到 {max(real, slots)}/{expected_count} 张 (img={real}, slots={slots})")
            return True, used_sel

        current = 0
        try:
            img_elems = driver.find_elements(
                By.CSS_SELECTOR, ".image-upload-list-item img, li.image-uploader-item img"
            )
            valid_imgs = []
            for img in img_elems:
                src = img.get_attribute("src") or ""
                if src.startswith(("http", "//", "blob:")) and "placeholder" not in src.lower():
                    valid_imgs.append(img)
            current = len(valid_imgs)
            used_sel = "img"
            if current == 0:
                for sel in (".image-upload-list-item", "li.image-uploader-item"):
                    elems = driver.find_elements(By.CSS_SELECTOR, sel)
                    valid_elems = [
                        e
                        for e in elems
                        if e.is_displayed()
                        and "上传图片" not in (e.text or "")
                        and "placeholder" not in (e.get_attribute("outerHTML") or "").lower()
                    ]
                    if valid_elems:
                        current = len(valid_elems)
                        used_sel = sel
                        break
            logger.info(f"当前检测到 {max(real, current)}/{expected_count} 张 (selector={used_sel})")
            if current >= expected_count or real >= expected_count:
                time.sleep(0.5)
                return True, used_sel
        except Exception as e:
            logger.warning(f"检测上传数异常: {e}")
        time.sleep(interval)

    logger.error(f"超时：{timeout}s 内未检测到 {expected_count} 张 (real={_count_real_images(driver)})")
    debug_print_html(driver, ".image-uploader")
    return False, None


def clear_marked_uploaded_images(driver) -> bool:
    """仅清除脚本标记的图片（对齐老脚本，不清复制页自带图）。"""
    from selenium.webdriver.common.by import By

    try:
        marked = driver.find_elements(By.CSS_SELECTOR, ".image-upload-list-item[data-auto-upload='true']")
        if not marked:
            logger.info("无脚本标记图片，跳过清理")
            return True
        logger.info(f"清理 {len(marked)} 张脚本标记图片...")
        for img_el in marked:
            try:
                driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", img_el)
                time.sleep(0.2)
                delete_btn = img_el.find_element(By.CSS_SELECTOR, ".image-upload-img-bottoom-action-delete")
                driver.execute_script("arguments[0].click();", delete_btn)
                time.sleep(0.5)
            except Exception:
                continue
        remaining = driver.find_elements(By.CSS_SELECTOR, ".image-upload-list-item[data-auto-upload='true']")
        return len(remaining) == 0
    except Exception as e:
        logger.warning(f"清理标记图片异常: {e}")
        return False


def upload_product_images(driver, primary_path: str, main_dir: str, batch_size: int = 6) -> bool:
    """上传产品图片（首图 + 主图），优先 sc-images 批量。"""
    try:
        with _upload_fast_context(driver):
            upload_list = [os.path.abspath(primary_path)]
            if os.path.isdir(main_dir):
                main_files = sorted(
                    [f for f in os.listdir(main_dir) if f.lower().endswith((".jpg", ".png", ".jpeg"))],
                    key=natural_key,
                )
                upload_list += [os.path.abspath(os.path.join(main_dir, f)) for f in main_files]

            upload_list = list(dict.fromkeys(upload_list))
            total = len(upload_list)
            logger.info(f"共 {total} 张图片待上传")

            for p in upload_list:
                if not os.path.isfile(p):
                    logger.error(f"图片文件不存在: {p}")
                    return False

            try:
                has_existing = bool(driver.execute_script(_HAS_FILLED_IMAGES_JS))
            except Exception:
                has_existing = False

            if has_existing:
                clear_marked_uploaded_images(driver)

            initial_count = _count_real_images_fast(driver)
            logger.info(f"上传前页面已有 {initial_count} 张有效图")

            cumulative = initial_count
            batch_sz = max(1, int(batch_size or 6))
            for start in range(0, total, batch_sz):
                batch = upload_list[start : start + batch_sz]
                expected = cumulative + len(batch)

                if not upload_via_input_element(driver, batch):
                    logger.error("sc-images 批量上传失败，槽位逐张补传已暂时禁用")
                    return False

                _mark_uploaded_images(driver, ".image-upload-list-item", len(batch))
                cumulative = expected
                logger.info(f"批次上传完成 {cumulative - initial_count}/{total}")

            logger.info(f"图片上传完成，共 {total} 张")
            return True

    except Exception as e:
        logger.error(f"图片上传异常: {e}", exc_info=True)
        return False


def _find_file_input_for_slot(driver, slot) -> Optional[object]:
    from selenium.webdriver.common.by import By

    found = driver.execute_script(
        """
        function findInputDeep(root) {
            if (!root) return null;
            let input = root.querySelector("input[type='file']");
            if (input) return input;
            const all = root.querySelectorAll ? root.querySelectorAll('*') : [];
            for (const el of all) {
                if (el.shadowRoot) {
                    const f = findInputDeep(el.shadowRoot);
                    if (f) return f;
                }
            }
            return null;
        }
        document.querySelectorAll('input[data-auto-upload-target]').forEach(e => {
            e.removeAttribute('data-auto-upload-target');
        });
        const slot = arguments[0];
        let input = findInputDeep(slot);
        if (!input) {
            const ph = slot.querySelector('.image-upload-photobank-placeholder') || slot;
            input = findInputDeep(ph);
        }
        if (!input) input = findInputDeep(document.body);
        if (!input) return false;
        input.setAttribute('data-auto-upload-target', '1');
        input.style.cssText = 'display:block!important;visibility:visible!important;opacity:1!important;position:fixed;top:0;left:0;width:120px;height:40px;z-index:2147483647;';
        return true;
        """,
        slot,
    )
    if not found:
        return None
    marked = driver.find_elements(By.CSS_SELECTOR, "input[type='file'][data-auto-upload-target='1']")
    return marked[0] if marked else None


def _collect_file_input_candidates(driver, slot):
    from selenium.webdriver.common.by import By

    selectors = [
        ".icbu-photobank input[type='file']",
        ".photobank-dialog input[type='file']",
        "[class*='photobank'] input[type='file']",
        ".image-upload-list-item input[type='file']",
        "input[type='file'][accept*='image']",
        "input[type='file']",
    ]
    seen = set()
    candidates = []
    for sel in selectors:
        for el in driver.find_elements(By.CSS_SELECTOR, sel):
            try:
                key = el.id
            except Exception:
                continue
            if key in seen:
                continue
            seen.add(key)
            candidates.append(el)
    if not candidates:
        marked = _find_file_input_for_slot(driver, slot)
        if marked:
            candidates.append(marked)
    return candidates


def _open_local_upload_on_slot(driver, slot) -> bool:
    from selenium.webdriver.common.by import By
    from selenium.webdriver.common.action_chains import ActionChains

    driver.execute_script("arguments[0].scrollIntoView({block:'center'});", slot)
    time.sleep(0.2)
    placeholder = slot.find_elements(By.CSS_SELECTOR, ".image-upload-photobank-placeholder")
    target = placeholder[0] if placeholder else slot
    try:
        ActionChains(driver).move_to_element(target).pause(0.3).perform()
    except Exception:
        pass
    time.sleep(0.3)
    try:
        ActionChains(driver).move_to_element(target).click().perform()
    except Exception:
        driver.execute_script("arguments[0].click();", target)
    time.sleep(0.3)
    return bool(
        driver.execute_script(
            """
            const slot = arguments[0];
            function clickLocal(scope) {
                if (!scope) return false;
                for (const n of scope.querySelectorAll('span, div, li, button, a, label')) {
                    const t = (n.innerText || '').trim();
                    if (t === '本地上传' && n.offsetParent !== null) {
                        n.click();
                        return true;
                    }
                }
                return false;
            }
            if (clickLocal(document)) return true;
            if (clickLocal(slot)) return true;
            const ph = slot.querySelector('.image-upload-photobank-placeholder');
            if (ph) {
                ph.dispatchEvent(new MouseEvent('mouseover', {bubbles: true}));
                ph.click();
            }
            return clickLocal(document);
            """,
            slot,
        )
    )


def _send_file_to_input(driver, file_input, abs_path: str) -> bool:
    try:
        file_input.send_keys(abs_path)
        return True
    except Exception as e:
        logger.warning(f"  send_keys 失败: {e}")
    return _cdp_set_input_files(driver, file_input, [abs_path])


def _upload_one_image(driver, file_path: str) -> bool:
    """向下一个空槽位上传单张图片（多 input 候选 + CDP 优先）。"""
    from app.services.automation.page_helpers import close_photobank_popup

    abs_path = os.path.abspath(file_path)
    if not os.path.isfile(abs_path):
        logger.error(f"文件不存在: {abs_path}")
        return False

    before_real = _count_real_images(driver)
    for attempt in range(8):
        try:
            empty_slots = _find_empty_slots(driver)
            if not empty_slots:
                after = _count_real_images(driver)
                if after > before_real:
                    logger.info(f"  无空槽但有效图片已增加: {before_real} -> {after}")
                    return True
                logger.error("没有可用的空图片槽位")
                return False

            slot = empty_slots[0]
            logger.info(f"  向空槽上传 (第 {attempt + 1} 次)...")
            _open_local_upload_on_slot(driver, slot)
            time.sleep(1.2)
            candidates = _collect_file_input_candidates(driver, slot)
            logger.info(f"  候选 file input 数量: {len(candidates)}")
            if not candidates:
                logger.warning("  未找到 file input")
                time.sleep(1)
                continue

            for idx, file_input in enumerate(candidates):
                logger.info(f"  尝试 input #{idx + 1}/{len(candidates)}")
                try:
                    sent = _send_file_to_input(driver, file_input, abs_path)
                except Exception as e:
                    logger.warning(f"  input #{idx + 1} 发送失败: {e}")
                    sent = False
                if not sent:
                    continue
                for _ in range(18):
                    time.sleep(1)
                    after_real = _count_real_images(driver)
                    if after_real > before_real:
                        logger.info(f"  有效图片: {before_real} -> {after_real}")
                        close_photobank_popup(driver)
                        return True
                logger.warning(f"  input #{idx + 1} 上传后仍无缩略图")

            close_photobank_popup(driver)
        except Exception as e:
            logger.warning(f"  上传尝试失败: {e}")
            close_photobank_popup(driver)

    return _count_real_images(driver) > before_real


def _wait_for_real_image_count(driver, expected_count: int, timeout: int = 60) -> bool:
    """仅根据有效缩略图数量判断上传是否完成。"""
    start = time.time()
    while time.time() - start < timeout:
        current = _count_real_images(driver)
        if current >= expected_count:
            time.sleep(0.5)
            return True
        time.sleep(0.5)
    logger.error(f"超时：{timeout}s 内有效产品图仍为 {_count_real_images(driver)}/{expected_count}")
    return False


def _mark_uploaded_images(driver, used_selector: Optional[str], n: int):
    """标记新上传的图片"""
    if not used_selector:
        return
    try:
        script = """
        (function(sel, n){
            const elems = Array.from(document.querySelectorAll(sel));
            if(!elems || elems.length===0) return 0;
            const start = Math.max(0, elems.length - n);
            for(let i=start;i<elems.length;i++){
                elems[i].setAttribute('data-auto-upload','true');
            }
            return elems.length - start;
        })(arguments[0], arguments[1]);
        """
        driver.execute_script(script, used_selector, n)
    except Exception:
        pass


def _clear_all_product_images(driver):
    """删除复制发品页自带的全部主图（保留空占位）。"""
    from selenium.webdriver.common.by import By

    removed = 0
    for _ in range(30):
        items = driver.find_elements(By.CSS_SELECTOR, ".image-upload-list-item, li.image-uploader-item")
        deleted = False
        for img_el in items:
            try:
                if not img_el.is_displayed():
                    continue
                text = (img_el.text or "").strip()
                html = (img_el.get_attribute("outerHTML") or "")
                if "上传图片" in text or "上传图片" in html:
                    continue
                has_img = bool(img_el.find_elements(By.CSS_SELECTOR, "img"))
                if not has_img and "上传" in text:
                    continue
                for sel in (
                    ".image-upload-img-bottoom-action-delete",
                    "[class*='action-delete']",
                    "[class*='delete']",
                ):
                    btns = img_el.find_elements(By.CSS_SELECTOR, sel)
                    if btns:
                        driver.execute_script("arguments[0].click();", btns[0])
                        time.sleep(0.7)
                        removed += 1
                        deleted = True
                        break
            except Exception:
                continue
        if not deleted:
            break
    if removed:
        logger.info(f"已清除复制页自带图片 {removed} 张")


def _clear_existing_images(driver):
    """清除页面上已有的标记图片"""
    from selenium.webdriver.common.by import By
    try:
        existing = driver.find_elements(By.CSS_SELECTOR, ".image-upload-list-item")
        has_existing = len(existing) > 0 and "上传图片" not in existing[0].get_attribute("outerHTML")
        if not has_existing:
            return

        marked = driver.find_elements(By.CSS_SELECTOR, ".image-upload-list-item[data-auto-upload='true']")
        for img_el in marked:
            try:
                driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", img_el)
                time.sleep(0.2)
                delete_btn = img_el.find_element(By.CSS_SELECTOR, ".image-upload-img-bottoom-action-delete")
                driver.execute_script("arguments[0].click();", delete_btn)
                time.sleep(0.5)
            except Exception:
                continue
    except Exception:
        pass

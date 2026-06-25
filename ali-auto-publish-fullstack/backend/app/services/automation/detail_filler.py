# -*- coding: utf-8 -*-
"""
产品详情填写模块（已切换为老脚本逻辑）
来源脚本: cs_新版详情.py

仅替换“详情部分”逻辑，不影响其他发布步骤。
"""
import os
import re
import time
from typing import Dict, List, Optional, Tuple

import pandas as pd
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from app.core.settings import DetailConfig, PathConfig
from app.core.logger import setup_logger

logger = setup_logger("detail_filler")


# ==============================
# 工具函数
# ==============================

def _get_images_from_dir(folder: str, max_num: int = 0) -> List[str]:
    if not folder or (not os.path.exists(folder)):
        return []

    imgs = sorted(
        os.path.abspath(os.path.join(folder, f))
        for f in os.listdir(folder)
        if f.lower().endswith((".jpg", ".png", ".jpeg", ".webp"))
        and os.path.isfile(os.path.join(folder, f))
    )
    return imgs[:max_num] if max_num and max_num > 0 else imgs


# 详情图 / 公司图 checkbox id → 模块中文名（与阿里发品页 DOM 一致）
_DETAIL_GALLERY_CN: Dict[str, str] = {
    "150": "尺寸图",
    "200": "场景图",
    "300": "细节图",
    "350": "其他商品图片",
}
_COMPANY_GALLERY_CN: Dict[str, str] = {
    "400": "公司介绍",
    "450": "公司优势",
    "500": "工厂情况",
    "550": "定制能力",
    "600": "生产流程",
    "650": "参展情况",
    "700": "包装运输",
    "750": "其他公司介绍",
}


def _gallery_module_js(driver, section_id: str, cn_name: str, script: str, *args):
    """在指定图集模块上执行 JS（按中文名定位，避免持有 stale WebElement）。"""
    return driver.execute_script(
        """
        const section = document.getElementById(arguments[0]);
        if (!section) return null;
        for (const root of section.querySelectorAll('.gallery-item-container')) {
          const name = root.querySelector('.gallery-item-header-cn-name');
          if (!name || name.innerText.trim() !== arguments[1]) continue;
          return (function(root, extra) {
        """
        + script
        + """
          })(root, arguments[2]);
        }
        return null;
        """,
        section_id,
        cn_name,
        *args,
    )


def _count_module_images_js(driver, section_id: str, cn_name: str) -> int:
    """JS 统计模块已上传预览数。"""
    try:
        return int(
            _gallery_module_js(
                driver,
                section_id,
                cn_name,
                """
            const area = root.querySelector('.gallery-item-images');
            if (!area) return 0;
            let n = 0;
            const wrappers = area.querySelectorAll('.gallery-item-image-wrapper');
            if (wrappers.length) {
              for (const wrap of wrappers) {
                for (const img of wrap.querySelectorAll('.gallery-item-image img, img')) {
                  const src = (img.getAttribute('src') || '').trim();
                  if (!src || /blank/i.test(src)) continue;
                  if ((img.offsetWidth || img.clientWidth || 0) > 10) { n++; break; }
                }
              }
              return n;
            }
            for (const slot of area.querySelectorAll('.gallery-item-image:not(.gallery-item-image-empty)')) {
              if (slot.querySelector('.upload-button-container, .image-upload-wrapper')) continue;
              for (const img of slot.querySelectorAll('img')) {
                const src = (img.getAttribute('src') || '').trim();
                if (!src || /blank/i.test(src)) continue;
                if ((img.offsetWidth || img.clientWidth || 0) > 10) { n++; break; }
              }
            }
            return n;
                """,
            )
            or 0
        )
    except Exception:
        return 0


def _confirm_gallery_delete_dialog(driver) -> bool:
    """图集「删除全部」后的确认弹窗：点击「确认删除」。"""
    try:
        for _ in range(8):
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
                  if (!text.includes('删除') && !/delete/i.test(text)) continue;
                  for (const btn of dlg.querySelectorAll('button')) {
                    if (!isVisible(btn)) continue;
                    const t = (btn.innerText || btn.textContent || '').trim();
                    if (t === '确认删除' || /^确认删除$/i.test(t)) {
                      btn.click();
                      return true;
                    }
                  }
                  for (const btn of dlg.querySelectorAll('.next-dialog-footer button, .next-dialog-footer .next-btn')) {
                    if (!isVisible(btn)) continue;
                    const t = (btn.innerText || btn.textContent || '').trim();
                    if (!t || t === '取消' || /^cancel$/i.test(t)) continue;
                    if (t.includes('确认') || t.includes('删除') || /confirm|delete/i.test(t)) {
                      btn.click();
                      return true;
                    }
                  }
                  const primary = dlg.querySelector('.next-dialog-footer .next-btn-primary');
                  if (primary && isVisible(primary)) {
                    const t = (primary.innerText || primary.textContent || '').trim();
                    if (t && t !== '取消') {
                      primary.click();
                      return true;
                    }
                  }
                }
                for (const btn of document.querySelectorAll('button')) {
                  if (!isVisible(btn)) continue;
                  const t = (btn.innerText || btn.textContent || '').trim();
                  if (t === '确认删除') {
                    btn.click();
                    return true;
                  }
                }
                return false;
                """
            )
            if confirmed:
                time.sleep(0.35)
                return True
            time.sleep(0.12)
        return False
    except Exception:
        return False


def _click_gallery_delete_all(driver, section_id: str, cn_name: str) -> bool:
    """复制发品页图集模块头部的「删除全部」。"""
    try:
        clicked = _gallery_module_js(
            driver,
            section_id,
            cn_name,
            """
            root.scrollIntoView({block: 'nearest'});
            const btn = root.querySelector('.gallery-item-header-delete-all');
            if (!btn) return false;
            const style = window.getComputedStyle(btn);
            if (style.display === 'none' || style.visibility === 'hidden') return false;
            if (btn.classList.contains('gallery-item-header-delete-all-disabled')) return false;
            btn.click();
            return true;
            """,
        )
        if clicked:
            time.sleep(0.25)
            if not _confirm_gallery_delete_dialog(driver):
                logger.warning(f"{cn_name} 点击删除全部后未找到确认弹窗")
            time.sleep(0.4)
        return bool(clicked)
    except Exception:
        return False


def _count_duplicate_markers_js(driver, section_id: str, cn_name: str) -> int:
    try:
        return int(
            _gallery_module_js(
                driver,
                section_id,
                cn_name,
                """
            let n = 0;
            for (const el of root.querySelectorAll('span,div')) {
              const t = (el.innerText || '').trim();
              if (t === '重复图' || t === 'Duplicate image') n++;
            }
            return n;
                """,
            )
            or 0
        )
    except Exception:
        return 0


def _module_visible_js(driver, section_id: str, cn_name: str) -> bool:
    """图集模块是否已展开（勾选后 gallery 区域可见）。"""
    try:
        return bool(
            driver.execute_script(
                """
                const section = document.getElementById(arguments[0]);
                if (!section) return false;
                for (const root of section.querySelectorAll('.gallery-item-container')) {
                  const name = root.querySelector('.gallery-item-header-cn-name');
                  if (!name || name.innerText.trim() !== arguments[1]) continue;
                  const area = root.querySelector('.gallery-item-images');
                  return !!(area && area.offsetParent);
                }
                return false;
                """,
                section_id,
                cn_name,
            )
        )
    except Exception:
        return False


def _ensure_gallery_checkbox(driver, checkbox_id: str, section_id: str, cn_name: str) -> bool:
    """逐个勾选图集 checkbox 并等待对应模块出现（不可批量连点，否则只剩最后一项）。"""
    cid = str(checkbox_id or "").strip()
    if not cid:
        return False
    try:
        driver.execute_script(
            """
            const cb = document.getElementById(arguments[0]);
            if (!cb) return false;
            cb.scrollIntoView({block: 'nearest'});
            if (!cb.checked) {
              cb.click();
              cb.dispatchEvent(new Event('change', {bubbles: true}));
            }
            return cb.checked;
            """,
            cid,
        )
        deadline = time.time() + 2.5
        while time.time() < deadline:
            if _module_visible_js(driver, section_id, cn_name):
                return True
            time.sleep(0.06)
        logger.warning(f"{cn_name} 勾选后模块未出现 (checkbox={cid})")
        return False
    except Exception as exc:
        logger.warning(f"勾选图集 {cid} 失败: {exc}")
        return False


def _prepare_module_local_upload_js(
    driver,
    section_id: str,
    cn_name: str,
    *,
    skip_upload_click: bool = False,
) -> Optional[str]:
    """展开本地上传菜单并标记 file input，返回 CSS 选择器。"""
    try:
        return driver.execute_script(
            """
            const section = document.getElementById(arguments[0]);
            const skipClick = !!arguments[2];
            if (!section) return null;
            for (const root of section.querySelectorAll('.gallery-item-container')) {
              const name = root.querySelector('.gallery-item-header-cn-name');
              if (!name || name.innerText.trim() !== arguments[1]) continue;
              root.scrollIntoView({block: 'nearest'});
              const wrapper = root.querySelector('.image-upload-wrapper');
              if (wrapper) {
                wrapper.dispatchEvent(new MouseEvent('mouseover', {bubbles: true}));
                wrapper.dispatchEvent(new MouseEvent('mouseenter', {bubbles: true}));
              }
              const popup = root.querySelector('.upload-popup-container');
              if (popup) popup.style.display = 'block';
              for (const item of root.querySelectorAll('.upload-style-item')) {
                const text = item.querySelector('.upload-style-item-text');
                if (!text || text.innerText.trim() !== '本地上传') continue;
                const inp = item.querySelector('input[type=file][multiple]');
                if (!inp) continue;
                const uid = 'gup-' + Date.now() + '-' + Math.random().toString(36).slice(2, 8);
                inp.setAttribute('data-gallery-upload', uid);
                inp.style.cssText = 'display:block!important;visibility:visible!important;opacity:1!important;';
                if (!skipClick) {
                  item.querySelector('.upload-style-item-content')?.click();
                }
                return '[data-gallery-upload="' + uid + '"]';
              }
            }
            return null;
            """,
            section_id,
            cn_name,
            skip_upload_click,
        )
    except Exception:
        return None


def _cdp_inject_files_fast(driver, css_selector: str, paths: List[str]) -> bool:
    """CDP 注入文件（用选择器重新取元素，避免 stale 导致误判失败）。"""
    from app.services.automation.image_uploader import _resolve_cdp_node_id

    abs_paths = [os.path.abspath(p) for p in paths if os.path.isfile(p)]
    if not abs_paths or not css_selector:
        return False
    try:
        inp = driver.find_element(By.CSS_SELECTOR, css_selector)
        node_id = _resolve_cdp_node_id(driver, inp)
        if not node_id:
            return False
        driver.execute_cdp_cmd("DOM.setFileInputFiles", {"nodeId": node_id, "files": abs_paths})
        driver.execute_script(
            """
            const inp = document.querySelector(arguments[0]);
            if (!inp) return false;
            inp.dispatchEvent(new Event('input', {bubbles: true}));
            inp.dispatchEvent(new Event('change', {bubbles: true}));
            return true;
            """,
            css_selector,
        )
        return True
    except Exception as exc:
        logger.warning(f"CDP 注入失败: {exc}")
        return False


def _clear_gallery_module_images(driver, section_id: str, cn_name: str) -> int:
    """清空单个详情/公司图集模块内已有图片（复制发品页预填图需先删后传）。"""
    initial = _count_module_images_js(driver, section_id, cn_name)
    if initial <= 0:
        return 0

    # 复制发品页：模块头「删除全部」一次清空（见有内容的详情 DOM）
    for _ in range(3):
        before = _count_module_images_js(driver, section_id, cn_name)
        if before <= 0:
            break
        if not _click_gallery_delete_all(driver, section_id, cn_name):
            break
        deadline = time.time() + 3.0
        while time.time() < deadline:
            if _count_module_images_js(driver, section_id, cn_name) < before:
                break
            time.sleep(0.1)

    removed = max(0, initial - _count_module_images_js(driver, section_id, cn_name))

    # 回退：逐张删除（空白页或其它 DOM 变体）
    for _ in range(40):
        before = _count_module_images_js(driver, section_id, cn_name)
        if before <= 0:
            break
        clicked = _gallery_module_js(
            driver,
            section_id,
            cn_name,
            """
            const area = root.querySelector('.gallery-item-images');
            if (!area) return false;
            const targets = area.querySelectorAll('.gallery-item-image-wrapper, .gallery-item-image:not(.gallery-item-image-empty)');
            for (const slot of targets) {
              if (slot.classList.contains('upload-button-container')) continue;
              if (slot.querySelector('.upload-button-container, .image-upload-wrapper')) continue;
              let hasImg = false;
              for (const img of slot.querySelectorAll('img')) {
                const src = (img.getAttribute('src') || '').trim();
                if (!src || /blank/i.test(src)) continue;
                if ((img.offsetWidth || img.clientWidth || 0) > 10) { hasImg = true; break; }
              }
              if (!hasImg) continue;
              slot.dispatchEvent(new MouseEvent('mouseover', {bubbles: true}));
              slot.dispatchEvent(new MouseEvent('mouseenter', {bubbles: true}));
              for (const sel of [
                '.gallery-item-image-delete',
                '.image-upload-img-bottoom-action-delete',
                '[class*="action-delete"]',
                '[class*="image-delete"]',
                'i.next-icon-delete',
                'button[class*="delete"]',
                'span[class*="delete"]',
              ]) {
                const btn = slot.querySelector(sel);
                if (btn && btn.offsetParent !== null) {
                  btn.click();
                  return true;
                }
              }
              for (const el of slot.querySelectorAll('i, span, button, a')) {
                const hint = ((el.className || '') + ' ' + (el.getAttribute('aria-label') || '')).toLowerCase();
                if ((hint.includes('delete') || hint.includes('删除') || hint.includes('remove'))
                    && el.offsetParent !== null) {
                  el.click();
                  return true;
                }
              }
            }
            return false;
            """,
        )
        if not clicked:
            break
        removed = max(removed, initial - before)
        deadline = time.time() + 2.0
        while time.time() < deadline:
            now = _count_module_images_js(driver, section_id, cn_name)
            if now < before:
                removed = max(removed, initial - now)
                break
            time.sleep(0.08)
        else:
            time.sleep(0.25)

    remaining = _count_module_images_js(driver, section_id, cn_name)
    if removed > 0 or remaining < initial:
        logger.info(f"{cn_name} 已清空 {max(removed, initial - remaining)} 张原有图片（剩余 {remaining} 张）")
    elif remaining > 0:
        logger.warning(f"{cn_name} 检测到 {remaining} 张原有图片但未能全部清空")
    return max(removed, initial - remaining)


def _wait_upload_fast(
    driver,
    section_id: str,
    cn_name: str,
    before: int,
    expected_add: int,
    timeout: float = 2.0,
) -> int:
    """短轮询等待预览出现（50ms 间隔，有进展即提前结束）。"""
    target = before + expected_add
    deadline = time.time() + timeout
    progress_at = None
    while time.time() < deadline:
        now = _count_module_images_js(driver, section_id, cn_name)
        if now >= target:
            return max(0, now - before)
        if now > before:
            if progress_at is None:
                progress_at = time.time()
            elif time.time() - progress_at >= 0.2:
                return max(0, now - before)
        time.sleep(0.05)
    return max(0, _count_module_images_js(driver, section_id, cn_name) - before)


def _batch_upload_company_overview_module(
    driver,
    section_id: str,
    checkbox_id: str,
    img_paths: List[str],
) -> int:
    """
    公司介绍图集专用：静默 CDP 注入，不点击「本地上传」、不用 send_keys，
    避免弹出 Windows 文件选择框。
    """
    from app.services.automation.page_helpers import close_photobank_popup

    cn_name = "公司介绍"
    abs_paths = [os.path.abspath(p) for p in img_paths if os.path.isfile(p)]
    if not abs_paths:
        return 0

    if not _ensure_gallery_checkbox(driver, checkbox_id, section_id, cn_name):
        return 0

    before = _count_module_images_js(driver, section_id, cn_name)
    if before > 0:
        logger.info(f"{cn_name} 检测到 {before} 张已有图片，先清空再上传")
        _clear_gallery_module_images(driver, section_id, cn_name)
        before = _count_module_images_js(driver, section_id, cn_name)

    close_photobank_popup(driver)
    injected = False
    for attempt in range(3):
        close_photobank_popup(driver)
        selector = _prepare_module_local_upload_js(
            driver, section_id, cn_name, skip_upload_click=True
        )
        if not selector:
            logger.warning(f"{cn_name} 未找到本地上传 input (第 {attempt + 1} 次)")
            time.sleep(0.15)
            continue
        if _cdp_inject_files_fast(driver, selector, abs_paths):
            logger.info(f"{cn_name} 静默 CDP 一次上传 {len(abs_paths)} 张")
            injected = True
            break
        time.sleep(0.15)

    if not injected:
        logger.warning(f"{cn_name} 静默 CDP 上传失败，已跳过 send_keys 以免弹出文件筐")
        return 0

    uploaded = _wait_upload_fast(driver, section_id, cn_name, before, len(abs_paths), timeout=3.0)
    dup = _count_duplicate_markers_js(driver, section_id, cn_name)
    if dup:
        logger.warning(f"{cn_name} 出现 {dup} 处重复图标记")
    if uploaded < len(abs_paths):
        logger.warning(f"{cn_name} 上传 {uploaded}/{len(abs_paths)} 张")
    else:
        logger.info(f"{cn_name} 上传完成 {uploaded}/{len(abs_paths)} 张")
    return uploaded


def _batch_upload_to_gallery_module(
    driver,
    section_id: str,
    checkbox_id: str,
    cn_name: str,
    img_paths: List[str],
) -> int:
    """
    单个图集模块：勾选 → 清空已有图 → 本地上传一次 → 批量传入文件夹全部图片。
    """
    from app.services.automation.page_helpers import close_photobank_popup

    abs_paths = [os.path.abspath(p) for p in img_paths if os.path.isfile(p)]
    if not abs_paths:
        return 0

    if not _ensure_gallery_checkbox(driver, checkbox_id, section_id, cn_name):
        return 0

    before = _count_module_images_js(driver, section_id, cn_name)
    if before > 0:
        logger.info(f"{cn_name} 检测到 {before} 张已有图片，先清空再上传")
        _clear_gallery_module_images(driver, section_id, cn_name)
        before = _count_module_images_js(driver, section_id, cn_name)

    to_upload = abs_paths
    if not to_upload:
        return 0

    close_photobank_popup(driver)
    selector = _prepare_module_local_upload_js(driver, section_id, cn_name)
    if not selector:
        logger.warning(f"{cn_name} 打开本地上传失败")
        return 0
    close_photobank_popup(driver)

    injected = False
    if _cdp_inject_files_fast(driver, selector, to_upload):
        logger.info(f"{cn_name} CDP 一次上传 {len(to_upload)} 张")
        injected = True
    else:
        try:
            driver.find_element(By.CSS_SELECTOR, selector).send_keys("\n".join(to_upload))
            logger.info(f"{cn_name} send_keys 一次上传 {len(to_upload)} 张")
            injected = True
        except Exception as exc:
            logger.warning(f"{cn_name} 上传失败: {exc}")

    uploaded = _wait_upload_fast(driver, section_id, cn_name, before, len(to_upload)) if injected else 0

    dup = _count_duplicate_markers_js(driver, section_id, cn_name)
    if dup:
        logger.warning(f"{cn_name} 出现 {dup} 处重复图标记")
    if uploaded < len(to_upload):
        logger.warning(f"{cn_name} 上传 {uploaded}/{len(to_upload)} 张（未逐张补传，避免重复）")
    else:
        logger.info(f"{cn_name} 上传完成 {uploaded}/{len(to_upload)} 张")
    return uploaded


def _scroll_to_element(driver, element):
    driver.execute_script("arguments[0].scrollIntoView({block: 'nearest'});", element)
    time.sleep(0.05)


def _safe_read_text(path: str) -> str:
    if not path or (not os.path.exists(path)):
        return ""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return ""


# ==============================
# 详情图（老脚本逻辑）
# ==============================

def _upload_detail_images(driver, scene_dir: str, detail_dir: str, max_image_upload: int):
    """详情图片：勾选图集 → 按模块本地上传 → 一次传入对应文件夹全部图片。"""
    logger.info("开始上传详情图...")
    section_id = "struct-detailImage"
    try:
        section = WebDriverWait(driver, 5).until(
            EC.presence_of_element_located((By.ID, section_id))
        )
        _scroll_to_element(driver, section)
    except Exception as exc:
        logger.error(f"未找到详情图区域: {exc}")
        return

    gallery_dirs = [
        ("200", scene_dir),
        ("300", detail_dir),
    ]
    for checkbox_id, folder in gallery_dirs:
        cn_name = _DETAIL_GALLERY_CN.get(checkbox_id, "")
        if not cn_name or not folder:
            continue
        images = _get_images_from_dir(folder, max_image_upload)
        if not images:
            logger.info(f"{cn_name} 目录无图片: {folder}")
            continue
        try:
            _batch_upload_to_gallery_module(driver, section_id, checkbox_id, cn_name, images)
        except Exception as exc:
            logger.warning(f"{cn_name} 上传异常: {exc}")


# ==============================
# 卖点（老脚本逻辑）
# ==============================

def _is_excel_file(path: str) -> bool:
    """按文件头判断是否为真实 Excel（避免 .xlsx 扩展名的纯文本被误读）。"""
    try:
        with open(path, "rb") as f:
            head = f.read(8)
        if head[:2] == b"PK":
            return True
        if head[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
            return True
    except Exception:
        pass
    return False


def _read_selling_points_as_text(path: str, max_selling_points: int) -> List[str]:
    """按纯文本读取卖点（兼容 GBK/UTF-8 及首行「卖点」标题）。"""
    raw = ""
    for enc in ("utf-8-sig", "utf-8", "gbk", "gb2312"):
        try:
            with open(path, "r", encoding=enc) as f:
                raw = f.read()
            break
        except Exception:
            continue
    if not raw.strip():
        return []

    lines: List[str] = []
    for ln in raw.splitlines():
        s = str(ln or "").strip().strip('"').strip("'").strip()
        if not s:
            continue
        if s.lower() in {"卖点", "商品卖点", "selling points", "selling point"}:
            continue
        lines.append(s)
    return lines[:max_selling_points]


def _read_selling_points(excel_path: str, max_selling_points: int) -> List[str]:
    """读取卖点列表（兼容 xlsx/xls/纯文本及误用 .xlsx 扩展名的文本文件）。"""
    if not excel_path or not os.path.isfile(excel_path):
        return []

    last_err = ""
    if _is_excel_file(excel_path):
        ext = os.path.splitext(excel_path)[1].lower()
        engines: List[Optional[str]]
        if ext in (".xlsx", ".xlsm"):
            engines = ["openpyxl"]
        elif ext == ".xls":
            engines = ["xlrd"]
        else:
            engines = ["openpyxl", "xlrd", None]
        for engine in engines:
            try:
                kwargs = {"engine": engine} if engine else {}
                df = pd.read_excel(excel_path, header=None, **kwargs)
                points = df.iloc[:max_selling_points, 0].dropna().astype(str).tolist()
                points = [p.strip() for p in points if p and str(p).strip()]
                if points:
                    return points
            except Exception as exc:
                last_err = str(exc)

    text_points = _read_selling_points_as_text(excel_path, max_selling_points)
    if text_points:
        return text_points

    if last_err:
        logger.warning(f"卖点文件读取失败: {last_err[:120]}")
    return []


ACCEPT_TEXT = "a"
ACCEPT_NUM = "1"


def _fill_selling_points(driver, excel_path: str, max_selling_points: int):
    logger.info("填写卖点...")
    points = _read_selling_points(excel_path, max_selling_points)
    if not points:
        points = [ACCEPT_TEXT] * min(3, max(1, max_selling_points))
        logger.warning(f"卖点无配置，验收占位: {points}")

    # 优先定位到卖点区域，避免被图片区域遮挡
    try:
        selling_container = WebDriverWait(driver, 5).until(
            EC.presence_of_element_located((By.ID, "struct-textDesc"))
        )
        driver.execute_script("arguments[0].scrollIntoView({block: 'nearest', behavior: 'instant'});", selling_container)
        time.sleep(0.05)
    except Exception:
        pass

    editor = WebDriverWait(driver, 5).until(
        EC.presence_of_element_located((By.XPATH, "//div[@id='struct-textDesc']//div[@contenteditable='true']"))
    )
    _scroll_to_element(driver, editor)
    try:
        driver.execute_script("arguments[0].focus();", editor)
        editor.click()
    except Exception:
        driver.execute_script("arguments[0].click();", editor)
    time.sleep(0.15)

    body = "\n".join(str(p) for p in points)
    injected = driver.execute_script(
        """
        const el = arguments[0], text = arguments[1];
        if (!el) return false;
        el.focus();
        el.innerText = text;
        el.dispatchEvent(new Event('input', {bubbles: true}));
        el.dispatchEvent(new Event('change', {bubbles: true}));
        return (el.innerText || '').trim().length > 0;
        """,
        editor,
        body,
    )
    if not injected:
        for p in points:
            editor.send_keys(str(p))
            editor.send_keys(Keys.ENTER)
    logger.info(f"卖点已填写 {len(points)} 条")


# ==============================
# 公司介绍文本（老脚本逻辑）
# ==============================

def _fill_company_intro(driver, company_txt: str):
    logger.info("自动定位并填写公司介绍...")
    content = _safe_read_text(company_txt)
    if not content:
        content = ACCEPT_TEXT
        logger.warning("公司介绍无配置，验收占位: a")

    try:
        container = WebDriverWait(driver, 12).until(
            EC.presence_of_element_located((By.ID, "struct-companyDesc"))
        )
        _scroll_to_element(driver, container)
        time.sleep(0.3)

        textarea = container.find_element(By.TAG_NAME, "textarea")
        driver.execute_script(
            "arguments[0].value=arguments[1];"
            "arguments[0].dispatchEvent(new Event('input',{bubbles:true}));"
            "arguments[0].dispatchEvent(new Event('change',{bubbles:true}));",
            textarea,
            content,
        )
        logger.info("公司介绍填写完成")
    except Exception as e:
        logger.error(f"公司介绍填写失败: {e}")


# ==============================
# FAQs（老脚本逻辑）
# ==============================

def _parse_faq_data(faq_txt: str) -> List[Tuple[str, str]]:
    try:
        all_lines = [
            l.strip() for l in open(faq_txt, "r", encoding="utf-8").readlines() if l.strip()
        ]
        qa_list: List[Tuple[str, str]] = []
        for i in range(0, len(all_lines), 2):
            if i + 1 < len(all_lines):
                q = re.sub(r"^[qQ]\d+[:：\s]*", "", all_lines[i]).strip()
                a = re.sub(r"^[aA]\d+[:：\s]*", "", all_lines[i + 1]).strip()
                if q and a:
                    qa_list.append((q, a))
        return qa_list[:8]
    except Exception as e:
        logger.error(f"解析FAQ失败: {e}")
        return []


def _pre_scroll_faq_area(driver) -> None:
    """详情填写过程中提前滚到 FAQ 区域，避免后续长等待。"""
    try:
        driver.execute_script(
            """
            const el = document.getElementById('struct-companyFaqDesc');
            if (el) el.scrollIntoView({block: 'center', behavior: 'instant'});
            """
        )
    except Exception:
        pass


def _locate_faq_section(driver):
    try:
        _pre_scroll_faq_area(driver)
        try:
            faq_section = WebDriverWait(driver, 4).until(
                EC.presence_of_element_located((By.ID, "struct-companyFaqDesc"))
            )
        except Exception:
            faq_section = driver.find_element(
                By.XPATH,
                "//*[contains(text(), 'FAQs')]/ancestor::div[contains(@class, 'com-struct')]",
            )

        _scroll_to_element(driver, faq_section)
        time.sleep(0.15)
    except Exception as e:
        logger.error(f"定位FAQ模块失败: {e}")
        raise


def _ensure_faq_groups_by_inputs(driver, target_count: int):
    add_btn_xpath = "//div[@id='struct-companyFaqDesc']//*[contains(text(),'添加FAQ')]"
    input_xpath = "//div[@id='struct-companyFaqDesc']//input"

    for _ in range(15):
        current_inputs = driver.find_elements(By.XPATH, input_xpath)
        current_count = len(current_inputs)

        if current_count >= target_count:
            logger.info(f"FAQ组数已就位: {current_count}")
            break

        try:
            add_btn = driver.find_element(By.XPATH, add_btn_xpath)
            _scroll_to_element(driver, add_btn)
            time.sleep(0.06)
            driver.execute_script("arguments[0].click();", add_btn)
            time.sleep(0.06)
        except Exception:
            driver.execute_script("window.scrollBy(0, 300);")
            time.sleep(0.06)


def _inject_faq_content_final(driver, qa_list: List[Tuple[str, str]]):
    time.sleep(0.1)
    js_fill = """
    (function(question, answer, index) {
        var container = document.getElementById('struct-companyFaqDesc');
        if (!container) return "CONTAINER_NOT_FOUND";

        var inputs = container.querySelectorAll('input');
        var textareas = container.querySelectorAll('textarea[data-real="true"]');
        if (textareas.length === 0) textareas = container.querySelectorAll('textarea');

        if (!inputs[index] || !textareas[index]) return "INPUTS_NOT_FOUND_AT_INDEX_" + index;

        var qInput = inputs[index];
        var aTextarea = textareas[index];

        function setValue(el, val) {
            if (!el || !val) return;
            el.value = val;
            el.dispatchEvent(new Event('input', { bubbles: true }));
            el.dispatchEvent(new Event('change', { bubbles: true }));
            el.dispatchEvent(new Event('blur', { bubbles: true }));
        }

        setValue(qInput, question);
        setValue(aTextarea, answer);
        return "SUCCESS";
    })(arguments[0], arguments[1], arguments[2]);
    """

    for i, (q, a) in enumerate(qa_list):
        result = driver.execute_script(js_fill, q, a, i)
        logger.info(f"FAQ第{i + 1}组注入结果: {result}")
        time.sleep(0.1)


def _fill_faqs(driver, faq_txt: str):
    logger.info("自动定位并填写FAQs...")
    qa_list: List[Tuple[str, str]] = []
    if faq_txt and os.path.exists(faq_txt):
        qa_list = _parse_faq_data(faq_txt)
    if not qa_list:
        qa_list = [(f"Q{i+1}", ACCEPT_TEXT) for i in range(2)]
        logger.warning(f"FAQ无配置，验收占位: {qa_list}")

    _locate_faq_section(driver)
    _ensure_faq_groups_by_inputs(driver, len(qa_list))
    _inject_faq_content_final(driver, qa_list)
    logger.info("FAQs填写完成")


# ==============================
# 公司图片（老脚本逻辑）
# ==============================

def _upload_company_images(driver, company_image_dir_map: Dict[str, str], max_image_upload: int):
    """公司图片：每个 checkbox 对应独立 gallery-item-container，本地上传一次批量传入。"""
    logger.info("开始上传公司介绍图片...")
    section_id = "struct-companyImage"
    try:
        section = WebDriverWait(driver, 5).until(
            EC.presence_of_element_located((By.ID, section_id))
        )
        _scroll_to_element(driver, section)
    except Exception as exc:
        logger.warning(f"未找到公司图片主区域: {exc}")
        return

    for cid, folder in company_image_dir_map.items():
        cn_name = _COMPANY_GALLERY_CN.get(cid, "")
        if not cn_name:
            continue
        images = _get_images_from_dir(folder, max_image_upload)
        if not images:
            logger.info(f"公司模块 {cn_name} 目录无图片: {folder}")
            continue
        try:
            if cid == "400" and cn_name == "公司介绍":
                _batch_upload_company_overview_module(driver, section_id, cid, images)
            else:
                _batch_upload_to_gallery_module(driver, section_id, cid, cn_name, images)
        except Exception as exc:
            logger.error(f"公司模块 {cn_name} 上传失败: {exc}")

    logger.info("公司介绍图片上传完成")


def verify_detail_uploads(driver, path_cfg: PathConfig, detail_cfg: DetailConfig) -> List[str]:
    """对比磁盘图片数量与页面有效预览数量。"""
    issues: List[str] = []
    max_upload = int(getattr(detail_cfg, "max_image_upload", 100) or 100)
    scene_dir = str(getattr(path_cfg, "detail_scene_image_dir", "") or "").strip()
    detail_dir = str(getattr(path_cfg, "detail_detail_image_dir", "") or "").strip()
    if not scene_dir:
        scene_dir = str(getattr(path_cfg, "detail_image_dir", "") or "").strip()
    if not detail_dir:
        detail_dir = str(getattr(path_cfg, "detail_image_dir", "") or "").strip()
    company_root = str(getattr(path_cfg, "detail_company_image_root_dir", "") or "").strip()

    for cid, label in _DETAIL_GALLERY_CN.items():
        if cid not in ("200", "300"):
            continue
        folder = scene_dir if cid == "200" else detail_dir
        provided = _get_images_from_dir(folder, max_upload)
        if not provided:
            continue
        actual = _count_module_images_js(driver, "struct-detailImage", label)
        dup = _count_duplicate_markers_js(driver, "struct-detailImage", label)
        if dup:
            issues.append(f"详情/{label}: 页面有 {dup} 处重复图标记")
        elif actual >= len(provided):
            logger.info(f"[验收OK] 详情/{label} 提供={len(provided)} 页面有效预览={actual}")
        elif actual > 0:
            issues.append(f"详情/{label}: 提供 {len(provided)} 张，页面仅 {actual} 张有效预览")
        else:
            issues.append(f"详情/{label}: 提供 {len(provided)} 张，页面无有效预览（裂图）")

    for cid, cname in _COMPANY_GALLERY_CN.items():
        num_dir = os.path.join(company_root, cid) if company_root else ""
        cn_dir = os.path.join(company_root, cname) if company_root else ""
        folder = num_dir if os.path.isdir(num_dir) else (cn_dir if os.path.isdir(cn_dir) else "")
        provided = _get_images_from_dir(folder, max_upload)
        if not provided:
            continue
        try:
            if not driver.find_element(By.ID, cid).is_selected():
                continue
            actual = _count_module_images_js(driver, "struct-companyImage", cname)
        except Exception:
            actual = 0
        if actual >= len(provided):
            logger.info(f"[验收OK] 详情/{cname} 提供={len(provided)} 页面有效预览={actual}")
        elif actual > 0:
            issues.append(f"详情/{cname}: 提供 {len(provided)} 张，页面仅 {actual} 张")
        else:
            issues.append(f"详情/{cname}: 提供 {len(provided)} 张，页面无有效预览")
    return issues


# ==============================
# 对外入口
# ==============================

def enhance_product_detail(driver, detail_cfg: DetailConfig, path_cfg: PathConfig):
    """
    老脚本详情总流程：
    1) 上传详情图（场景图+细节图）
    2) 填写卖点
    3) 上传公司图片
    4) 填写公司介绍
    5) 填写FAQs
    """
    logger.info("开始执行详情模块（老脚本逻辑）")

    max_image_upload = int(getattr(detail_cfg, "max_image_upload", 100) or 100)
    max_selling_points = int(getattr(detail_cfg, "max_selling_points", 6) or 6)

    # 目录映射策略（优先读取配置管理中的专用路径）
    scene_dir = str(getattr(path_cfg, "detail_scene_image_dir", "") or "").strip()
    detail_dir = str(getattr(path_cfg, "detail_detail_image_dir", "") or "").strip()

    if not scene_dir:
        scene_dir = str(getattr(path_cfg, "detail_image_dir", "") or "").strip()
    if not detail_dir:
        detail_dir = str(getattr(path_cfg, "detail_image_dir", "") or "").strip()

    company_root = str(getattr(path_cfg, "detail_company_image_root_dir", "") or "").strip()

    # 自动按目录读取公司图片：优先数字目录，其次中文目录；都不存在时回退根目录
    company_dir_names = {
        "400": "公司介绍",
        "450": "公司优势",
        "500": "工厂情况",
        "550": "定制能力",
        "600": "生产流程",
        "650": "参展情况",
        "700": "包装运输",
    }

    company_image_dir_map: Dict[str, str] = {}
    for cid, cname in company_dir_names.items():
        num_dir = os.path.join(company_root, cid) if company_root else ""
        cn_dir = os.path.join(company_root, cname) if company_root else ""
        if num_dir and os.path.isdir(num_dir) and _get_images_from_dir(num_dir, 1):
            company_image_dir_map[cid] = num_dir
        elif cn_dir and os.path.isdir(cn_dir) and _get_images_from_dir(cn_dir, 1):
            company_image_dir_map[cid] = cn_dir
        # 无专属子目录时不回退到根目录，避免所有模块上传到同一块

    project_root = str(getattr(path_cfg, "project_files_root", "") or "").strip()
    company_txt = str(getattr(path_cfg, "detail_company_intro_file", "") or "").strip()
    faq_txt = str(getattr(path_cfg, "detail_faq_file", "") or "").strip()
    if not company_txt:
        company_txt = os.path.join(project_root, "公司介绍.txt") if project_root else ""
    if not faq_txt:
        faq_txt = os.path.join(project_root, "FAQs.txt") if project_root else ""

    try:
        _upload_detail_images(driver, scene_dir, detail_dir, max_image_upload)
    except Exception as e:
        logger.error(f"上传详情图异常: {e}")

    try:
        _fill_selling_points(driver, str(getattr(detail_cfg, "selling_points_excel", "") or ""), max_selling_points)
    except Exception as e:
        logger.error(f"填写卖点异常: {e}")

    try:
        _pre_scroll_faq_area(driver)
        _upload_company_images(driver, company_image_dir_map, max_image_upload)
    except Exception as e:
        logger.error(f"上传公司图片异常: {e}")

    try:
        _fill_company_intro(driver, company_txt)
    except Exception as e:
        logger.error(f"填写公司介绍异常: {e}")

    try:
        _fill_faqs(driver, faq_txt)
    except Exception as e:
        logger.error(f"填写FAQs异常: {e}")

    logger.info("详情模块执行完成")

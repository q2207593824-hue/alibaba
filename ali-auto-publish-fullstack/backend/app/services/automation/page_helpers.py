# -*- coding: utf-8 -*-
"""
页面辅助函数
重构自: main_属性融合.py 中的各种弹窗关闭、页面操作辅助函数

【如何修改】
- 添加新的弹窗处理 → 在 close_all_popups() 中添加新的选择器
- 修改图片银行弹窗处理 → 修改 close_photobank_popup()
"""
import time
import logging

from selenium.webdriver.common.by import By

from app.core.logger import setup_logger

logger = setup_logger("page_helpers")


def close_all_popups(driver):
    """关闭弹窗：优先 JS 批量隐藏，仅对可见 dialog 点关闭（避免通配选择器扫全页）。"""
    try:
        driver.execute_script(
            """
            document.querySelectorAll(
              '.product-sub-title-guide-balloon,.icbu-photobank,.next-balloon,.compose-notice,.guide-layer'
            ).forEach(el => {
              el.style.display = 'none';
              el.style.visibility = 'hidden';
              if (el._tippy) try { el._tippy.hide(); } catch(e) {}
            });
            for (const sel of ['.next-dialog-close','.next-overlay-close','.compose-notice-close']) {
              for (const btn of document.querySelectorAll(sel)) {
                if (!btn.offsetParent) continue;
                btn.click();
              }
            }
            """
        )
    except Exception:
        pass


def close_photobank_popup(driver):
    """关闭图片银行弹窗（无弹窗时立即返回，不阻塞）。"""
    try:
        popups = driver.find_elements(By.CSS_SELECTOR, ".icbu-photobank")
        for popup in popups:
            if not popup.is_displayed():
                continue
            close_btns = popup.find_elements(By.CSS_SELECTOR, ".next-dialog-close")
            if close_btns:
                driver.execute_script("arguments[0].click();", close_btns[0])
                return True
    except Exception:
        pass
    return False


def debug_print_html(driver, selector: str):
    """调试用：打印指定元素的 HTML"""
    try:
        elements = driver.find_elements(By.CSS_SELECTOR, selector)
        for i, el in enumerate(elements):
            html = el.get_attribute("outerHTML")
            logger.debug(f"[DEBUG] {selector}[{i}]: {html[:200]}...")
    except Exception:
        pass

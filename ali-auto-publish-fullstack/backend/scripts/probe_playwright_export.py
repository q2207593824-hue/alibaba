# -*- coding: utf-8 -*-
"""Playwright 导出探测：验证 expect_download 能否拿到 xls。"""
import os
import pickle
import sys
import time

BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND_ROOT)
os.chdir(BACKEND_ROOT)

from playwright.sync_api import sync_playwright
from app.core.settings import get_config
from app.services.data_download_service import _get_daily_staging_download_dir


def load_cookies(context, cookie_file: str):
    if not os.path.exists(cookie_file):
        return
    with open(cookie_file, "rb") as f:
        cookies = pickle.load(f)
    pw = []
    for c in cookies:
        if not isinstance(c, dict):
            continue
        dom = c.get("domain") or ""
        if "alibaba.com" not in dom:
            continue
        pw.append(
            {
                "name": c["name"],
                "value": c["value"],
                "domain": dom if dom.startswith(".") else f".{dom.lstrip('.')}",
                "path": c.get("path") or "/",
            }
        )
    if pw:
        context.add_cookies(pw)


def main():
    cfg = get_config()
    staging = _get_daily_staging_download_dir()
    target = os.path.join(staging, "Products-playwright-test.xls")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        ctx = browser.new_context(accept_downloads=True)
        load_cookies(ctx, cfg.paths.cookie_file)
        page = ctx.new_page()
        page.goto("https://data.alibaba.com/product/overview", wait_until="domcontentloaded", timeout=60000)
        page.wait_for_selector(".product-datepicker", timeout=30000)

        # 切日粒度（简化）
        page.click(".datepicker-container .next-select-trigger")
        time.sleep(1)
        page.click("//ul[@class='static-menu']/li[span[text()='日']]")
        time.sleep(1)
        page.wait_for_selector(".next-date-picker")
        cells = page.locator("//td[not(contains(@class, 'next-disabled'))]//motion.div[@class='next-calendar-date']")
        if cells.count() == 0:
            cells = page.locator("//td[not(contains(@class, 'next-disabled'))]//motion.div")
        # fallback old xpath
        cells = page.locator("xpath=//td[not(contains(@class, 'next-disabled'))]//div[@class='next-calendar-date']")
        n = cells.count()
        print("calendar cells", n)
        if n:
            cells.nth(n - 1).click()
        page.click("body")
        time.sleep(2)

        print("click export with expect_download...")
        try:
            with page.expect_download(timeout=120000) as dl_info:
                page.click("a.product-effective-download")
            download = dl_info.value
            print("download url:", download.url)
            print("suggested:", download.suggested_filename)
            download.save_as(target)
            print("saved:", target, os.path.getsize(target))
        except Exception as e:
            print("expect_download failed:", e)
            page.click("a.product-effective-download")
            time.sleep(30)
            print("staging:", os.listdir(staging))

        browser.close()


if __name__ == "__main__":
    main()

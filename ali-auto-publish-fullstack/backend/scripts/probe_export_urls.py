# -*- coding: utf-8 -*-
"""探测点击导出后产生的网络 URL。"""
import json
import os
import sys
import time

BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND_ROOT)
os.chdir(BACKEND_ROOT)

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from app.core.settings import get_config
from app.services.data_download_service import (
    _build_isolated_chrome_driver,
    _daily_load_cookies_from_paths,
    _daily_cookie_paths,
    _legacy_overview_setup_day_mode,
    _get_daily_staging_download_dir,
)

HOOK_JS = """
window.__aliExportUrls = [];
(function () {
  if (window.__aliExportHooked) return;
  window.__aliExportHooked = true;
  const push = (u) => {
    if (!u) return;
    const s = String(u);
    if (s.startsWith('http')) window.__aliExportUrls.push(s);
  };
  const origFetch = window.fetch;
  window.fetch = function (...args) {
    push(args[0] && args[0].url ? args[0].url : args[0]);
    return origFetch.apply(this, args);
  };
  const origOpen = XMLHttpRequest.prototype.open;
  XMLHttpRequest.prototype.open = function (method, url) {
    push(url);
    return origOpen.apply(this, arguments);
  };
})();
"""


def collect_perf_urls(driver):
    urls = []
    try:
        logs = driver.get_log("performance")
    except Exception:
        return urls
    for entry in logs:
        try:
            msg = json.loads(entry.get("message", "{}")).get("message", {})
        except Exception:
            continue
        params = msg.get("params") or {}
        if msg.get("method") == "Network.responseReceived":
            u = (params.get("response") or {}).get("url") or ""
        elif msg.get("method") == "Network.requestWillBeSent":
            u = (params.get("request") or {}).get("url") or ""
        else:
            continue
        if u.startswith("http"):
            urls.append(u)
    return urls


def main():
    cfg = get_config()
    driver = _build_isolated_chrome_driver(cfg.data_download.daily_output_dir)
    wait = WebDriverWait(driver, 20)
    target = "https://data.alibaba.com/product/overview"
    _daily_load_cookies_from_paths(driver, _daily_cookie_paths(cfg, cfg.data_download.daily_output_dir))
    driver.get(target)
    wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, ".product-datepicker")))
    driver.execute_script(HOOK_JS)
    _legacy_overview_setup_day_mode(wait, driver)

    a = driver.find_element(By.CSS_SELECTOR, "a.product-effective-download")
    print("export outerHTML:", (a.get_attribute("outerHTML") or "")[:500])
    print("href:", a.get_attribute("href"))
    print("onclick:", a.get_attribute("onclick"))

    driver.get_log("performance")  # clear
    a.click()
    time.sleep(15)

    hooked = driver.execute_script("return window.__aliExportUrls || []")
    perf = collect_perf_urls(driver)

    all_urls = list(dict.fromkeys(hooked + perf))
    print("\n=== hooked urls ===")
    for u in hooked:
        print(u)
    print("\n=== perf urls (download/export/mydata) ===")
    for u in perf:
        low = u.lower()
        if any(k in low for k in ("export", "download", "mydata", ".xls", "excel", "product")):
            if "aplus.alibaba.com" not in low:
                print(u)

    staging = _get_daily_staging_download_dir()
    print("\n=== staging files ===", staging)
    print(os.listdir(staging))


if __name__ == "__main__":
    main()

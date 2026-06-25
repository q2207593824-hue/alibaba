# -*- coding: utf-8 -*-
import json
import os
import re
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

def perf_mydata_urls(driver):
    out = []
    try:
        logs = driver.get_log("performance")
    except Exception:
        return out
    for entry in logs:
        try:
            msg = json.loads(entry.get("message", "{}")).get("message", {})
        except Exception:
            continue
        params = msg.get("params") or {}
        if msg.get("method") == "Network.responseReceived":
            u = (params.get("response") or {}).get("url") or ""
            mime = (params.get("response") or {}).get("mimeType") or ""
        elif msg.get("method") == "Network.requestWillBeSent":
            u = (params.get("request") or {}).get("url") or ""
            mime = ""
        else:
            continue
        if "mydata.alibaba.com" in u:
            out.append((u, mime))
    return out


def main():
    cfg = get_config()
    driver = _build_isolated_chrome_driver(cfg.data_download.daily_output_dir)
    wait = WebDriverWait(driver, 20)
    _daily_load_cookies_from_paths(driver, _daily_cookie_paths(cfg, cfg.data_download.daily_output_dir))
    driver.get("https://data.alibaba.com/product/overview")
    wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, ".product-datepicker")))
    _legacy_overview_setup_day_mode(wait, driver)

    src = driver.page_source or ""
    for pat in [r"export[^\"']{0,80}", r"download[^\"']{0,80}", r"Products-\d{4}-\d{2}-\d{2}\.xls", r"iName=[^\"'&]+"]:
        hits = re.findall(pat, src, re.I)
        if hits:
            print(f"\n=== page_source pattern {pat[:30]} (first 8) ===")
            for h in list(dict.fromkeys(hits))[:8]:
                print(h[:200])

    driver.get_log("performance")
    driver.find_element(By.CSS_SELECTOR, "a.product-effective-download").click()
    print("\nclicked export, polling 90s...")

    staging = _get_daily_staging_download_dir()
    seen = set()
    for i in range(90):
        time.sleep(1)
        for d in [staging, os.path.join(os.environ["USERPROFILE"], "Downloads")]:
            if os.path.isdir(d):
                for f in os.listdir(d):
                    if f.endswith(".xls") and f not in seen:
                        seen.add(f)
                        fp = os.path.join(d, f)
                        print(f"[{i}s] FILE {fp} size={os.path.getsize(fp)}")
        for u, mime in perf_mydata_urls(driver):
            if u not in seen and any(k in u.lower() for k in ("export", "download", "effective", "product", "xls", "excel")):
                seen.add(u)
                print(f"[{i}s] MYDATA {mime} {u[:200]}")


if __name__ == "__main__":
    main()

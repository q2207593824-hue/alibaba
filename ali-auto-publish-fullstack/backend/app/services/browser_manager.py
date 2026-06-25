# -*- coding: utf-8 -*-
"""
浏览器管理器
重构自: main_属性融合.py 中的 AlibabaPoster.setup_driver() / wait_and_login()

【如何修改】
- 更换浏览器类型 → 修改 setup() 方法中的 webdriver 配置
- 修改登录逻辑 → 修改 login() 方法
- 修改 Cookie 策略 → 修改 _load_cookies() / _save_cookies()
"""
import os
import sys
import time
import pickle
import logging
from typing import Optional

from app.core.settings import get_config
from app.core.logger import setup_logger

logger = setup_logger("browser_manager")


class BrowserManager:
    """
    Selenium 浏览器生命周期管理
    封装了驱动初始化、Cookie 管理、登录检测
    """

    def __init__(self):
        self.driver = None

    def setup(self, download_dir: Optional[str] = None) -> bool:
        """
        初始化 Chrome 驱动

        Args:
            download_dir: 可选，Chrome 默认下载目录（绝对路径）

        【修改指南】
        - 如需更换为 Firefox/Edge，替换此方法中的 webdriver 初始化代码
        - 如需添加更多 Chrome 参数，在 options.add_argument() 处添加
        """
        try:
            from selenium import webdriver
            from selenium.webdriver.chrome.options import Options
            from selenium.webdriver.chrome.service import Service

            cfg = get_config()
            options = Options()

            # Chrome 启动参数
            # 绑定店铺场景避免全屏铺满，固定为中等窗口
            options.add_argument("--window-size=1200,820")

            if cfg.data_download.headless:
                options.add_argument("--headless=new")
                options.add_argument("--disable-gpu")
            options.add_experimental_option("useAutomationExtension", False)
            options.add_experimental_option("excludeSwitches", ["enable-automation"])
            options.add_argument("--disable-blink-features=AutomationControlled")
            options.add_argument("--no-sandbox")
            options.add_argument("--disable-dev-shm-usage")
            options.add_argument("--disable-extensions")
            options.add_argument("--ignore-certificate-errors")
            options.add_argument("--disable-cache")
            options.add_argument("--disable-web-security")
            options.add_argument("--disable-features=VizDisplayCompositor")
            options.add_argument("--disable-foregrounding")
            options.add_argument("--disable-backgrounding-occluded-windows")
            options.add_argument("--disable-renderer-backgrounding")

            if download_dir:
                abs_download = os.path.abspath(download_dir)
                os.makedirs(abs_download, exist_ok=True)
                options.add_experimental_option(
                    "prefs",
                    {
                        "download.default_directory": abs_download,
                        "download.prompt_for_download": False,
                        "download.directory_upgrade": True,
                        "safebrowsing.enabled": True,
                    },
                )

            # 使用 webdriver-manager 自动管理驱动
            try:
                from webdriver_manager.chrome import ChromeDriverManager
                service = Service(ChromeDriverManager().install())
            except ImportError:
                # 如果没有 webdriver-manager，尝试使用配置的路径或系统 PATH
                if cfg.paths.chrome_driver_path:
                    service = Service(cfg.paths.chrome_driver_path)
                else:
                    service = Service()

            self.driver = webdriver.Chrome(service=service, options=options)

            if download_dir:
                try:
                    abs_download = os.path.abspath(download_dir)
                    self.driver.execute_cdp_cmd(
                        "Page.setDownloadBehavior",
                        {"behavior": "allow", "downloadPath": abs_download},
                    )
                except Exception:
                    pass

            self.driver.set_page_load_timeout(30)
            self.driver.implicitly_wait(3)
            logger.info("浏览器启动完成")
            return True

        except Exception as e:
            logger.error(f"浏览器启动失败: {e}")
            return False

    def login(self) -> bool:
        """
        检查并执行登录

        【修改指南】
        - 如需更改登录检测逻辑，修改 _check_logged_in() 方法
        - 如需支持自动输入账号密码，在此方法中添加表单填写逻辑
        """
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC
        from selenium.common.exceptions import TimeoutException

        cfg = get_config()
        default_url = cfg.group_urls.default_posting_url

        logger.info("尝试自动登录（加载 Cookie）...")
        self.driver.get(default_url)
        time.sleep(2)

        # 尝试加载 Cookie
        self._load_cookies()
        self.driver.refresh()
        time.sleep(2)

        # 尝试自动处理登录确认页
        self._auto_confirm_login()

        # 检查是否已登录（优先用 URL 判断，其次用按钮文案）
        try:
            WebDriverWait(self.driver, 10).until(
                EC.url_contains("post.alibaba.com/product/publish")
            )
            logger.info("已自动登录")
            return True
        except TimeoutException:
            pass

        # 需要手动登录 - 等待用户完成登录
        logger.warning("需要手动登录，请在浏览器中完成登录操作")
        try:
            # 在等待期间持续尝试自动点击“继续/确认”
            end_time = time.time() + 300
            while time.time() < end_time:
                self._auto_confirm_login()
                if "post.alibaba.com/product/publish" in (self.driver.current_url or ""):
                    break
                time.sleep(1)

            WebDriverWait(self.driver, 10).until(
                EC.url_contains("post.alibaba.com/product/publish")
            )
            self._save_cookies()
            logger.info("登录成功，Cookie 已保存")
            return True
        except TimeoutException:
            logger.error("登录超时")
            return False

    def _load_cookies(self):
        """加载 Cookie"""
        cfg = get_config()
        cookie_file = cfg.paths.cookie_file
        if not os.path.exists(cookie_file):
            return

        try:
            with open(cookie_file, "rb") as f:
                cookies = pickle.load(f)
            for cookie in cookies:
                if "domain" in cookie and "alibaba.com" in cookie.get("domain", ""):
                    cookie["domain"] = ".alibaba.com"
                    try:
                        self.driver.add_cookie(cookie)
                    except Exception:
                        pass
            logger.info("Cookie 已加载")
        except Exception as e:
            logger.warning(f"Cookie 加载失败: {e}")

    def _save_cookies(self):
        """保存 Cookie"""
        cfg = get_config()
        try:
            cookies = self.driver.get_cookies()
            fixed = []
            for cookie in cookies:
                if cookie.get("domain", "").endswith("alibaba.com"):
                    cookie["domain"] = ".alibaba.com"
                fixed.append(cookie)
            with open(cfg.paths.cookie_file, "wb") as f:
                pickle.dump(fixed, f)
            logger.info("Cookie 已保存")
        except Exception as e:
            logger.error(f"Cookie 保存失败: {e}")

    def _auto_confirm_login(self):
        """自动点击登录确认页上的“继续/确认”按钮"""
        try:
            from selenium.webdriver.common.by import By
            from selenium.webdriver.support.ui import WebDriverWait
            from selenium.webdriver.support import expected_conditions as EC

            # 优先等待“继续”按钮出现
            possible_xpaths = [
                "//button[contains(.,'继续') and not(@disabled)]",
                "//button[contains(.,'确认') and not(@disabled)]",
                "//button[contains(.,'Continue') and not(@disabled)]",
                "//a[contains(.,'继续') and not(@disabled)]",
                "//a[contains(.,'确认') and not(@disabled)]",
                "//input[@type='submit' and (contains(@value,'继续') or contains(@value,'确认') or contains(@value,'Continue'))]",
            ]

            for xpath in possible_xpaths:
                try:
                    btn = WebDriverWait(self.driver, 1).until(
                        EC.element_to_be_clickable((By.XPATH, xpath))
                    )
                    if btn:
                        self.driver.execute_script("arguments[0].click();", btn)
                        logger.info("已自动点击登录确认按钮")
                        time.sleep(1)
                        break
                except Exception:
                    continue
        except Exception:
            pass

    def check_session(self) -> bool:
        """检查 WebDriver 会话是否有效"""
        if not self.driver:
            return False
        try:
            self.driver.execute_script("return 1")
            return True
        except Exception:
            return False

    def quit(self):
        """关闭浏览器"""
        if self.driver:
            try:
                self.driver.quit()
            except Exception:
                pass
            self.driver = None

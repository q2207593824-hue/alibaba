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
import shutil
import atexit
import threading
from pathlib import Path
from typing import List, Optional

from app.core.settings import get_config
from app.core.logger import setup_logger

logger = setup_logger("browser_manager")


def _appdata_driver_root() -> Path:
    appdata = os.environ.get("APPDATA", "").strip()
    if appdata:
        return Path(appdata) / "AliAutoPublish" / "chromedriver"
    return Path.home() / "AliAutoPublish" / "chromedriver"


def _init_selenium_driver_env() -> None:
    """桌面/打包态：驱动缓存写到用户目录，避免 Program Files 无写权限。"""
    root = _appdata_driver_root()
    try:
        root.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    wdm = str(root / "wdm")
    os.environ.setdefault("WDM_LOCAL", wdm)
    os.environ.setdefault("SE_AVOID_STATS", "1")
    os.environ.setdefault("WDM_LOG", "0")


if getattr(sys, "frozen", False) or os.getenv("ALI_DESKTOP", "").strip() == "1":
    _init_selenium_driver_env()


class BrowserManager:
    """
    Selenium 浏览器生命周期管理
    封装了驱动初始化、Cookie 管理、登录检测
    """

    _shared_driver = None
    _shared_lock = threading.RLock()
    _active_leases = 0
    _last_setup_error: str = ""

    @classmethod
    def _find_chrome_binary(cls) -> str:
        """解析本机 Chrome 可执行文件（桌面客户机常见为已安装但 Selenium 未自动识别）。"""
        env_bin = os.getenv("CHROME_BINARY", "").strip() or os.getenv("GOOGLE_CHROME_BIN", "").strip()
        if env_bin and os.path.isfile(env_bin):
            return os.path.normpath(env_bin)

        if sys.platform == "win32":
            try:
                import winreg

                for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
                    try:
                        with winreg.OpenKey(
                            hive,
                            r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe",
                        ) as key:
                            val, _ = winreg.QueryValueEx(key, "")
                            if val and os.path.isfile(val):
                                return os.path.normpath(val)
                    except OSError:
                        pass
            except Exception:
                pass

        candidates: List[str] = []
        if sys.platform == "win32":
            candidates.extend(
                [
                    os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
                    os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
                    os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe"),
                ]
            )
        elif sys.platform == "darwin":
            candidates.append("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
        else:
            candidates.extend(["/usr/bin/google-chrome", "/usr/bin/chromium-browser", "/usr/bin/chromium"])

        for path in candidates:
            if path and os.path.isfile(path):
                return os.path.normpath(path)
        return ""

    @classmethod
    def _get_chrome_version(cls) -> str:
        chrome = cls._find_chrome_binary()
        if not chrome:
            return ""
        try:
            import subprocess

            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0
            out = subprocess.check_output(
                [chrome, "--version"],
                stderr=subprocess.STDOUT,
                text=True,
                timeout=15,
                creationflags=flags,
            )
            token = str(out or "").strip().split()[-1]
            return token if token and token[0].isdigit() else ""
        except Exception:
            return ""

    @classmethod
    def _persist_driver_copy(cls, src: str) -> str:
        """将已解析的 driver 复制到 AppData，下次离线可用。"""
        if not src or not os.path.isfile(src):
            return src
        try:
            dest_dir = _appdata_driver_root()
            dest_dir.mkdir(parents=True, exist_ok=True)
            name = "chromedriver.exe" if sys.platform == "win32" else "chromedriver"
            dest = dest_dir / name
            if not dest.is_file() or os.path.getmtime(src) > os.path.getmtime(dest):
                shutil.copy2(src, dest)
            return str(dest)
        except Exception as e:
            logger.warning(f"ChromeDriver 缓存到 AppData 失败: {e}")
            return src

    @classmethod
    def _chromedriver_search_paths(cls) -> List[str]:
        """桌面安装包/开发环境可能出现的 ChromeDriver 位置。"""
        paths: List[str] = []
        cfg = get_config()
        if cfg.paths.chrome_driver_path:
            paths.append(str(cfg.paths.chrome_driver_path).strip())
        env_driver = os.getenv("CHROME_DRIVER_PATH", "").strip()
        if env_driver:
            paths.append(env_driver)

        appdata_root = _appdata_driver_root()
        for name in ("chromedriver.exe", "chromedriver"):
            paths.append(str(appdata_root / name))

        names = ("chromedriver.exe", "chromedriver") if sys.platform == "win32" else ("chromedriver",)
        roots: List[Path] = []
        if getattr(sys, "frozen", False):
            exe_dir = Path(sys.executable).resolve().parent
            roots.extend(
                [
                    exe_dir,
                    exe_dir / "chromedriver",
                    exe_dir / "chromedriver-win64",
                    exe_dir.parent,
                    exe_dir.parent / "chromedriver",
                    exe_dir.parent.parent,
                    exe_dir.parent.parent / "chromedriver",
                    exe_dir.parent.parent.parent / "resources" / "chromedriver",
                ]
            )
        meipass = getattr(sys, "_MEIPASS", "")
        if meipass:
            mp = Path(meipass)
            roots.extend([mp, mp / "chromedriver", mp / "chromedriver-win64"])

        for root in roots:
            for name in names:
                paths.append(str((root / name).resolve()))

        # 去重保序
        seen = set()
        ordered: List[str] = []
        for p in paths:
            norm = os.path.normpath(p)
            if norm not in seen:
                seen.add(norm)
                ordered.append(norm)
        return ordered

    @classmethod
    def _build_chrome_service(cls):
        from selenium.webdriver.chrome.service import Service

        for candidate in cls._chromedriver_search_paths():
            if candidate and os.path.isfile(candidate):
                logger.info(f"使用 ChromeDriver: {candidate}")
                return Service(candidate)

        # 桌面端：按本机 Chrome 版本下载匹配驱动并缓存到 AppData
        try:
            from webdriver_manager.chrome import ChromeDriverManager

            ver = cls._get_chrome_version()
            if ver:
                logger.info(f"webdriver-manager 匹配 Chrome {ver}")
                try:
                    driver_path = ChromeDriverManager(driver_version=ver).install()
                except Exception:
                    driver_path = ChromeDriverManager(driver_version=ver.split(".", 1)[0]).install()
            else:
                driver_path = ChromeDriverManager().install()
            driver_path = cls._persist_driver_copy(driver_path)
            logger.info(f"使用 webdriver-manager ChromeDriver: {driver_path}")
            return Service(driver_path)
        except Exception as e:
            logger.warning(f"webdriver-manager 初始化失败: {e}")

        logger.info("回退 Selenium Manager 自动解析 ChromeDriver")
        return Service()

    @classmethod
    def get_last_setup_error(cls) -> str:
        return str(cls._last_setup_error or "").strip()

    def __init__(self):
        self.driver = None

    def _wait_dom_ready(self, timeout: float = 3.0) -> bool:
        """短轮询等待页面基础可操作，避免固定 sleep 过长。"""
        if not self.driver:
            return False
        end = time.time() + max(0.2, float(timeout))
        while time.time() < end:
            try:
                state = self.driver.execute_script("return document.readyState")
                if state in ("interactive", "complete"):
                    return True
            except Exception:
                pass
            time.sleep(0.1)
        return False

    def _safe_get(self, url: str, timeout: float = 90, retries: int = 3) -> bool:
        """导航到 URL；超时则 window.stop 后继续（阿里发品页资源多，易触发 page load timeout）。"""
        from selenium.common.exceptions import TimeoutException, WebDriverException

        if not self.driver:
            return False
        last_exc: Optional[Exception] = None
        for attempt in range(max(1, retries)):
            try:
                self.driver.set_page_load_timeout(timeout)
                self.driver.get(url)
                return True
            except TimeoutException:
                try:
                    self.driver.execute_script("window.stop();")
                except Exception:
                    pass
                logger.warning(f"页面加载超时({timeout}s)，已中止并继续: {url[:100]}")
                return True
            except WebDriverException as exc:
                last_exc = exc
                msg = str(exc).lower()
                if "timeout" in msg or "renderer" in msg:
                    try:
                        self.driver.execute_script("window.stop();")
                    except Exception:
                        pass
                    logger.warning(f"页面加载异常，已尝试继续: {str(exc)[:120]}")
                    return True
                if "err_name_not_resolved" in msg or "net::err" in msg:
                    logger.warning(f"网络异常，重试 {attempt + 1}/{retries}: {str(exc)[:80]}")
                    time.sleep(3.0 * (attempt + 1))
                    continue
                raise
        if last_exc:
            raise last_exc
        return True

    @classmethod
    def _is_driver_alive(cls, driver) -> bool:
        if not driver:
            return False
        try:
            driver.execute_script("return 1")
            return True
        except Exception:
            return False

    @classmethod
    def _apply_download_dir(cls, driver, download_dir: str) -> None:
        """通过 CDP 设置 Chrome 下载目录（复用会话时也可调用）。"""
        if not driver or not download_dir:
            return
        abs_path = os.path.abspath(download_dir)
        os.makedirs(abs_path, exist_ok=True)
        for path in (abs_path, abs_path.replace("\\", "/")):
            for cmd in ("Page.setDownloadBehavior", "Browser.setDownloadBehavior"):
                try:
                    driver.execute_cdp_cmd(cmd, {"behavior": "allow", "downloadPath": path})
                except Exception:
                    pass

    @classmethod
    def _build_driver(cls, download_dir: Optional[str] = None):
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
        from selenium.webdriver.chrome.service import Service

        cfg = get_config()
        options = Options()
        options.page_load_strategy = "eager"

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

        chrome_bin = cls._find_chrome_binary()
        if not chrome_bin:
            raise RuntimeError(
                "未检测到 Google Chrome。请先安装 Chrome 浏览器后重试："
                "https://www.google.com/chrome/"
            )
        options.binary_location = chrome_bin
        logger.info(f"使用 Chrome 浏览器: {chrome_bin}")

        service = cls._build_chrome_service()

        try:
            driver = webdriver.Chrome(service=service, options=options)
        except Exception as exc:
            msg = str(exc)
            if "Unable to obtain driver for chrome" in msg or "driver_location" in msg:
                raise RuntimeError(
                    "无法获取 ChromeDriver（驱动程序）。"
                    "请确认已安装 Google Chrome，并保持网络可访问 googlechromelabs.github.io；"
                    "若在公司网络/代理环境，请联系技术支持配置驱动路径。"
                ) from exc
            raise
        cls._apply_download_dir(driver, download_dir or os.getcwd())
        driver.set_page_load_timeout(90)
        driver.implicitly_wait(3)
        return driver

    @classmethod
    def warmup_shared(cls) -> bool:
        """后台预热浏览器，降低首次真实任务启动耗时。"""
        with cls._shared_lock:
            if cls._is_driver_alive(cls._shared_driver):
                logger.info("浏览器预热跳过：已存在可复用会话")
                return True
            try:
                cls._shared_driver = cls._build_driver()
                logger.info("浏览器预热完成")
                return True
            except Exception as e:
                cls._shared_driver = None
                logger.warning(f"浏览器预热失败: {e}")
                return False

    @classmethod
    def shutdown_shared(cls):
        """应用退出时关闭共享浏览器。"""
        with cls._shared_lock:
            driver = cls._shared_driver
            cls._shared_driver = None
            cls._active_leases = 0
        if driver:
            try:
                driver.quit()
            except Exception:
                pass

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
            with self.__class__._shared_lock:
                shared = self.__class__._shared_driver
                if self.__class__._is_driver_alive(shared):
                    self.driver = shared
                    self.__class__._active_leases += 1
                    if download_dir:
                        self.__class__._apply_download_dir(self.driver, download_dir)
                    logger.info(f"复用已预热浏览器会话 | active_leases={self.__class__._active_leases}")
                    return True

                self.__class__._shared_driver = self.__class__._build_driver(download_dir)
                self.driver = self.__class__._shared_driver
                self.__class__._active_leases = 1
                logger.info("浏览器启动完成（新建共享会话）")
            return True

        except Exception as e:
            self.__class__._last_setup_error = str(e)
            logger.error(f"浏览器启动失败: {e}")
            return False

    def login(self, manual_wait_seconds: int = 300) -> bool:
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
        self._safe_get(default_url)
        self._wait_dom_ready(8.0)

        # 尝试加载 Cookie
        self._load_cookies()
        try:
            self.driver.refresh()
        except Exception as exc:
            if "timeout" in str(exc).lower() or "renderer" in str(exc).lower():
                try:
                    self.driver.execute_script("window.stop();")
                except Exception:
                    pass
            else:
                raise
        self._wait_dom_ready(8.0)

        # 尝试自动处理登录确认页
        self._auto_confirm_login()

        # 检查是否已登录（优先用 URL 判断，其次用按钮文案）
        if "post.alibaba.com/product/publish" in (self.driver.current_url or ""):
            logger.info("已自动登录（快速命中）")
            return True
        try:
            WebDriverWait(self.driver, 4).until(
                EC.url_contains("post.alibaba.com/product/publish")
            )
            logger.info("已自动登录")
            return True
        except TimeoutException:
            pass

        # 需要手动登录 - 等待用户完成登录
        logger.warning("需要手动登录，请在浏览器中完成登录操作")
        try:
            wait_sec = max(60, int(manual_wait_seconds or 300))
            # 在等待期间持续尝试自动点击“继续/确认”
            end_time = time.time() + wait_sec
            while time.time() < end_time:
                self._auto_confirm_login()
                if "post.alibaba.com/product/publish" in (self.driver.current_url or ""):
                    break
                time.sleep(0.35)

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
        """释放当前实例对共享浏览器的占用，不主动销毁共享会话。"""
        if not self.driver:
            return

        with self.__class__._shared_lock:
            if self.driver == self.__class__._shared_driver:
                self.__class__._active_leases = max(0, self.__class__._active_leases - 1)
                logger.info(f"释放浏览器会话 | active_leases={self.__class__._active_leases}")
                self.driver = None
                return

        try:
            self.driver.quit()
        except Exception:
            pass
        self.driver = None


atexit.register(BrowserManager.shutdown_shared)

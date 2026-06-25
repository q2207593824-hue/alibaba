# -*- coding: utf-8 -*-
"""
新品绑定视频服务
迁移自: cs_新品绑定视频/cs_视频.py
"""
import os
import time
import re
from typing import Dict, List, Optional, Set, Tuple

import pandas as pd

from app.core.logger import setup_logger
from app.core.settings import get_config
from app.core.task_manager import TaskInfo
from app.services.automation.browser_manager import BrowserManager

logger = setup_logger("video_bind_service")

VIDEO_BANK_URL = "https://hz-productposting.alibaba.com/product/videobank/home.htm"
LOGIN_URL = "https://login.alibaba.com/newlogin/icbuLogin.htm?return_url=https%3A%2F%2Fhz-productposting.alibaba.com%2F"


def _extract_pid(val: str) -> Optional[str]:
    s = str(val or "").strip()
    if not s:
        return None

    m = re.search(r"(\d+)\.html", s)
    if m:
        return m.group(1)

    if s.isdigit():
        return s

    long_digits = re.findall(r"\d{9,}", s)
    if long_digits:
        return long_digits[0]
    return None


def load_new_links_for_video_bind():
    """读取新发链接监控，返回用于绑定与回写的数据。"""
    cfg = get_config()
    excel_path = (cfg.data_analysis.new_links_file_path or "").strip()
    sheet_name = (cfg.data_analysis.new_links_sheet_name or "新链接").strip()
    id_col = (cfg.data_analysis.new_links_column_name or "新发链接").strip()
    type_col = "类型"
    bind_col = "绑定视频"

    if not excel_path:
        raise ValueError("未配置 data_analysis.new_links_file_path")
    if not os.path.exists(excel_path):
        raise ValueError(f"新发链接监控文件不存在: {excel_path}")

    try:
        df = pd.read_excel(excel_path, sheet_name=sheet_name, dtype=str)
    except Exception:
        df = pd.read_excel(excel_path, dtype=str)

    if id_col not in df.columns or type_col not in df.columns:
        raise ValueError(f"Excel 缺少列: {id_col} 或 {type_col}")

    if bind_col not in df.columns:
        df[bind_col] = ""

    type_to_ids: Dict[str, List[str]] = {}
    rowidx_to_pid: Dict[int, str] = {}
    pid_to_rowidxs: Dict[str, List[int]] = {}
    skip_bound_count = 0
    skip_type_empty_count = 0
    skip_pid_invalid_count = 0

    for idx, row in df.iterrows():
        raw_id = row.get(id_col)
        raw_type = row.get(type_col)
        raw_bind = row.get(bind_col)

        if pd.isna(raw_id):
            continue

        bind_text = "" if pd.isna(raw_bind) else str(raw_bind).strip()
        if bind_text:
            skip_bound_count += 1
            continue

        p_type = "" if pd.isna(raw_type) else str(raw_type).strip()
        if not p_type:
            skip_type_empty_count += 1
            logger.info(f"新发链接第 {idx + 2} 行类型为空，跳过")
            continue

        pid = _extract_pid(str(raw_id))
        if not pid:
            skip_pid_invalid_count += 1
            continue

        rowidx_to_pid[idx] = pid
        pid_to_rowidxs.setdefault(pid, []).append(idx)
        type_to_ids.setdefault(p_type, [])
        if pid not in type_to_ids[p_type]:
            type_to_ids[p_type].append(pid)

    if skip_bound_count > 0:
        logger.info(f"已跳过 {skip_bound_count} 条已写入绑定结果的数据")
    if skip_type_empty_count > 0:
        logger.info(f"已跳过 {skip_type_empty_count} 条类型为空的数据")
    if skip_pid_invalid_count > 0:
        logger.info(f"已跳过 {skip_pid_invalid_count} 条无法解析产品ID的数据")

    return {
        "excel_path": excel_path,
        "sheet_name": sheet_name,
        "id_col": id_col,
        "type_col": type_col,
        "bind_col": bind_col,
        "df": df,
        "type_to_ids": type_to_ids,
        "rowidx_to_pid": rowidx_to_pid,
        "pid_to_rowidxs": pid_to_rowidxs,
        "filtered_count": sum(len(v) for v in type_to_ids.values()),
        "skip_bound_count": skip_bound_count,
        "skip_type_empty_count": skip_type_empty_count,
        "skip_pid_invalid_count": skip_pid_invalid_count,
    }


def save_bind_results_append_only(excel_path: str, sheet_name: str, df: pd.DataFrame, bind_col: str, updates: Dict[int, str]):
    """仅追加写入绑定结果：只填空单元格，不覆盖已有数据。"""
    if bind_col not in df.columns:
        df[bind_col] = ""

    write_count = 0
    for row_idx, value in updates.items():
        if row_idx not in df.index:
            continue
        if value is None:
            continue

        old_val = df.at[row_idx, bind_col]
        old_text = "" if pd.isna(old_val) else str(old_val).strip()
        if old_text:
            continue

        new_text = str(value).strip()
        if not new_text:
            continue

        df.at[row_idx, bind_col] = new_text
        write_count += 1

    if write_count <= 0:
        logger.info("绑定结果无新增写入")
        return

    try:
        if os.path.exists(excel_path):
            with pd.ExcelWriter(excel_path, engine="openpyxl", mode="a", if_sheet_exists="replace") as writer:
                df.to_excel(writer, sheet_name=sheet_name, index=False)
        else:
            with pd.ExcelWriter(excel_path, engine="openpyxl") as writer:
                df.to_excel(writer, sheet_name=sheet_name, index=False)
        logger.info(f"已新增写入绑定结果 {write_count} 条到列[{bind_col}]")
    except Exception as e:
        logger.error(f"写入绑定结果失败: {e}")


def _safe_click(driver, element):
    try:
        element.click()
    except Exception:
        driver.execute_script("arguments[0].click();", element)
    time.sleep(0.5)


def _force_clear_input(driver, element):
    from selenium.webdriver.common.keys import Keys

    try:
        element.clear()
        element.send_keys(Keys.CONTROL + "a")
        element.send_keys(Keys.BACKSPACE)
        if (element.get_attribute("value") or "") != "":
            driver.execute_script("arguments[0].value = '';", element)
        time.sleep(0.2)
    except Exception:
        pass


def _wait_if_needed(task: TaskInfo, sec: float) -> bool:
    """可中断等待，返回 False 表示任务已要求停止。"""
    t = 0.0
    step = 0.2
    while t < sec:
        if task.should_stop():
            return False
        task.wait_if_paused()
        time.sleep(step)
        t += step
    return True


def _safe_close_bind_dialog(driver, wait) -> bool:
    """尽量关闭绑定弹窗，避免因弹窗残留影响后续类型。"""
    from selenium.webdriver.common.by import By

    try:
        driver.switch_to.default_content()
    except Exception:
        pass

    selectors = [
        ".next-dialog-close",
        "button.next-dialog-close",
        "i.next-dialog-close",
        ".next-overlay-wrapper .next-dialog .next-icon-close",
    ]

    for sel in selectors:
        try:
            btn = wait.until(lambda d: d.find_element(By.CSS_SELECTOR, sel))
            driver.execute_script("arguments[0].click();", btn)
            time.sleep(0.25)
            return True
        except Exception:
            continue

    # 兜底：直接尝试按 ESC
    try:
        from selenium.webdriver.common.keys import Keys
        body = driver.find_element(By.TAG_NAME, "body")
        body.send_keys(Keys.ESCAPE)
        time.sleep(0.25)
        return True
    except Exception:
        return False


def _normalize_text(text: str) -> str:
    text = (text or "").lower().strip()
    # 去掉空白与常见分隔符
    return re.sub(r"[\s\-_/\\|（）()\[\]{}，,。.]+", "", text)


def _first_line(text: str) -> str:
    t = (text or "").strip()
    if not t:
        return ""
    return t.splitlines()[0].strip()


def _extract_vid(text: str) -> Optional[str]:
    m = re.search(r"VID\s*[:：]\s*(\d+)", str(text or ""), re.IGNORECASE)
    return m.group(1) if m else None


def _longest_common_substring(a: str, b: str) -> str:
    """返回最长公共连续子串（自适应，无词表）。"""
    if not a or not b:
        return ""

    # 动态规划，空间 O(min(len(a), len(b)))
    if len(a) < len(b):
        short, long = a, b
    else:
        short, long = b, a

    prev = [0] * (len(short) + 1)
    max_len = 0
    end_idx_in_short = 0

    for ch in long:
        curr = [0] * (len(short) + 1)
        for j, ch2 in enumerate(short, start=1):
            if ch == ch2:
                curr[j] = prev[j - 1] + 1
                if curr[j] > max_len:
                    max_len = curr[j]
                    end_idx_in_short = j
        prev = curr

    if max_len <= 0:
        return ""
    return short[end_idx_in_short - max_len:end_idx_in_short]


def _score_pair(a: str, b: str) -> float:
    from difflib import SequenceMatcher
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0

    short, long = (a, b) if len(a) <= len(b) else (b, a)
    if short in long:
        ratio = len(short) / max(len(long), 1)
        return 0.7 + 0.3 * ratio

    return SequenceMatcher(None, a, b).ratio()


def _match_score(type_text: str, video_text: str) -> float:
    """双向模糊匹配评分（0~1），越大越匹配。

    自适应策略：
    1) 基础双向匹配分
    2) 最长公共子串占比加权（无词表）
    3) 两者取最大
    """
    a = _normalize_text(type_text)
    b = _normalize_text(video_text)
    if not a or not b:
        return 0.0

    base_score = _score_pair(a, b)

    lcs = _longest_common_substring(a, b)
    if lcs:
        lcs_ratio = len(lcs) / max(min(len(a), len(b)), 1)
        # 公共主干越长，分数越高；给一个较保守的加权通道
        lcs_score = 0.55 + 0.45 * lcs_ratio
    else:
        lcs_score = 0.0

    return max(base_score, lcs_score)


def _login_for_video_bank(browser: BrowserManager, task: TaskInfo) -> bool:
    """仅面向视频银行登录：优先 Cookie，避免先跳发品页。"""
    driver = browser.driver
    try:
        # 先打开阿里域名以便注入 cookie
        driver.get("https://www.alibaba.com")
        if not _wait_if_needed(task, 1.0):
            return False

        # 复用 BrowserManager 的 cookie 逻辑
        try:
            browser._load_cookies()  # noqa
        except Exception:
            pass

        # 直接进入视频银行
        driver.get(VIDEO_BANK_URL)
        if not _wait_if_needed(task, 2.0):
            return False

        cur = (driver.current_url or "").lower()
        if "login.alibaba.com" in cur or "newlogin" in cur or "passport" in cur:
            # 需要人工确认时，仍停留在视频银行登录流，不走发品页
            logger.warning("视频银行需要登录确认，请在浏览器完成登录")
            end_time = time.time() + 300
            while time.time() < end_time:
                if task.should_stop():
                    return False
                task.wait_if_paused()
                cur = (driver.current_url or "").lower()
                if "hz-productposting.alibaba.com" in cur and "videobank" in cur:
                    return True
                time.sleep(1)
            return False

        return True
    except Exception:
        return False


def process_videos(task: TaskInfo, browser: BrowserManager, type_to_ids: Dict[str, List[str]], pid_to_rowidxs: Dict[str, List[int]], video_per_product_limit: int, max_linked_count: int):
    """按 Excel 类型驱动匹配视频：全库扫描一次，为每个类型选最佳视频后再绑定。"""
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.common.exceptions import TimeoutException, NoSuchElementException, StaleElementReferenceException

    driver = browser.driver
    wait = WebDriverWait(driver, 20)
    short_wait = WebDriverWait(driver, 5)

    task.current_step = "打开视频素材库..."
    driver.get(VIDEO_BANK_URL)
    if not _wait_if_needed(task, 4):
        return

    processed_ids: Set[str] = set()
    bind_updates: Dict[int, str] = {}

    # 先全库扫描一次候选视频（提速）
    task.current_step = "扫描视频库候选视频..."
    all_videos: List[Dict[str, str]] = []
    while not task.should_stop():
        task.wait_if_paused()
        try:
            rows = wait.until(EC.presence_of_all_elements_located((By.CSS_SELECTOR, "tbody.next-table-body tr.next-table-row")))
        except Exception:
            rows = []

        for row in rows:
            try:
                cells = row.find_elements(By.TAG_NAME, "td")
                if len(cells) < 3:
                    continue
                video_name = (cells[0].text or "").strip()
                linked_count_text = (cells[2].text or "").strip()
                linked_count = int(linked_count_text) if linked_count_text.isdigit() else 0
                if video_name and linked_count <= max_linked_count:
                    all_videos.append({
                        "display_name": video_name,
                        "first_line": _first_line(video_name),
                        "vid": _extract_vid(video_name) or "",
                    })
            except Exception:
                continue

        try:
            next_page = wait.until(EC.element_to_be_clickable((By.XPATH, "//button[contains(@class, 'next-pagination-item-next')]")))
            classes = (next_page.get_attribute("class") or "")
            if next_page.is_enabled() and "disabled" not in classes:
                _safe_click(driver, next_page)
                if not _wait_if_needed(task, 0.8):
                    return
            else:
                break
        except Exception:
            break

    # 去重保序（按 VID 优先，其次首行名）
    seen = set()
    dedup_videos: List[Dict[str, str]] = []
    for v in all_videos:
        key = v.get("vid") or v.get("first_line") or v.get("display_name")
        if not key or key in seen:
            continue
        seen.add(key)
        dedup_videos.append(v)
    all_videos = dedup_videos

    if not all_videos:
        task.current_step = "视频库无可用视频"
        return

    # 逐类型匹配并绑定
    for p_type, all_ids in type_to_ids.items():
        if task.should_stop():
            return
        task.wait_if_paused()

        if not p_type:
            continue

        ids_to_process = [pid for pid in all_ids if pid not in processed_ids]
        if not ids_to_process:
            continue

        # 在内存中选最佳视频（优先首行名称评分，避免整格文本匹配导致定位失败）
        best_video = None
        best_score = 0.0
        for v in all_videos:
            s = _match_score(p_type, v.get("first_line") or v.get("display_name") or "")
            if s > best_score:
                best_score = s
                best_video = v

        if not best_video or best_score < 0.5:
            logger.info(f"类型[{p_type}]未找到合适视频，最高匹配度={best_score:.3f}")
            for pid in ids_to_process:
                for ridx in pid_to_rowidxs.get(pid, []):
                    bind_updates.setdefault(ridx, "未找到匹配视频")
            continue

        best_video_name = best_video.get("display_name", "")
        best_video_first_line = best_video.get("first_line", "")
        best_video_vid = best_video.get("vid", "")
        logger.info(f"类型[{p_type}]最佳视频[{best_video_first_line or best_video_name}]，匹配度={best_score:.3f}")

        try:
            # 回到视频库第一页，快速定位目标视频并点击绑定
            driver.get(VIDEO_BANK_URL)
            if not _wait_if_needed(task, 1.0):
                return

            bind_btn = None
            while not task.should_stop():
                task.wait_if_paused()
                try:
                    rows = wait.until(EC.presence_of_all_elements_located((By.CSS_SELECTOR, "tbody.next-table-body tr.next-table-row")))
                except Exception:
                    rows = []

                for row in rows:
                    try:
                        cells = row.find_elements(By.TAG_NAME, "td")
                        if len(cells) < 1:
                            continue
                        cur_name = (cells[0].text or "").strip()
                        cur_first_line = _first_line(cur_name)
                        cur_vid = _extract_vid(cur_name) or ""

                        matched = False
                        if best_video_vid and cur_vid and best_video_vid == cur_vid:
                            matched = True
                        elif best_video_first_line and cur_first_line == best_video_first_line:
                            matched = True
                        elif cur_name == best_video_name:
                            matched = True

                        if matched:
                            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", row)
                            bind_btn = row.find_element(By.XPATH, ".//button[contains(., '关联产品主图')]")
                            break
                    except Exception:
                        continue

                if bind_btn:
                    break

                try:
                    next_page = wait.until(EC.element_to_be_clickable((By.XPATH, "//button[contains(@class, 'next-pagination-item-next')]")))
                    classes = (next_page.get_attribute("class") or "")
                    if next_page.is_enabled() and "disabled" not in classes:
                        _safe_click(driver, next_page)
                        if not _wait_if_needed(task, 0.8):
                            return
                    else:
                        break
                except Exception:
                    break

            if not bind_btn:
                logger.warning(f"未定位到目标视频，跳过类型[{p_type}]：{best_video_first_line or best_video_name}")
                for pid in ids_to_process:
                    for ridx in pid_to_rowidxs.get(pid, []):
                        bind_updates.setdefault(ridx, "未找到匹配视频")
                continue

            _safe_click(driver, bind_btn)

            task.current_step = f"绑定类型: {p_type} -> {best_video_name} (匹配度 {best_score:.2f})"
            wait.until(EC.frame_to_be_available_and_switch_to_it((By.CSS_SELECTOR, "div.next-dialog-body iframe, iframe[src*='products_popup']")))

            batch_ids = ids_to_process[:max(1, int(video_per_product_limit))]
            checked = 0
            for pid in batch_ids:
                if task.should_stop():
                    driver.switch_to.default_content()
                    return
                task.wait_if_paused()

                pid_input = wait.until(EC.visibility_of_element_located((By.ID, "productId")))
                _force_clear_input(driver, pid_input)
                pid_input.send_keys(pid)

                search_btn = wait.until(EC.element_to_be_clickable((By.XPATH, "//button[contains(., '搜索')]")))
                _safe_click(driver, search_btn)
                if not _wait_if_needed(task, 0.8):
                    driver.switch_to.default_content()
                    return

                try:
                    checkbox_xpath = f"//input[@type='checkbox' and @value='{pid}']"
                    checkbox = WebDriverWait(driver, 8).until(EC.presence_of_element_located((By.XPATH, checkbox_xpath)))
                    if not checkbox.is_selected():
                        _safe_click(driver, checkbox)
                    checked += 1
                    processed_ids.add(pid)
                    for ridx in pid_to_rowidxs.get(pid, []):
                        bind_updates.setdefault(ridx, best_video_name)
                except TimeoutException:
                    logger.info(f"视频绑定未找到产品ID，跳过: {pid}")
                    for ridx in pid_to_rowidxs.get(pid, []):
                        bind_updates.setdefault(ridx, "已绑定视频")
                except Exception as e:
                    logger.warning(f"产品ID[{pid}]勾选失败，跳过: {e}")
                    for ridx in pid_to_rowidxs.get(pid, []):
                        bind_updates.setdefault(ridx, "已绑定视频")
                    continue

            if checked > 0:
                confirm_btn = wait.until(EC.element_to_be_clickable((By.ID, "confirm")))
                _safe_click(driver, confirm_btn)
                logger.info(f"类型[{p_type}]已绑定{checked}个产品")
            else:
                driver.switch_to.default_content()
                close_btn = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, ".next-dialog-close")))
                _safe_click(driver, close_btn)
                logger.info(f"类型[{p_type}]未找到可勾选产品，已关闭弹窗")

            driver.switch_to.default_content()
            if not _wait_if_needed(task, 0.6):
                return

        except Exception as e:
            logger.warning(f"类型[{p_type}]绑定失败: {e}")
            _safe_close_bind_dialog(driver, wait)
            # 发生异常后强制回到视频银行主页，避免后续类型沿用坏状态
            try:
                driver.get(VIDEO_BANK_URL)
                _wait_if_needed(task, 1.0)
            except Exception:
                pass
            continue

    task.current_step = "所有类型匹配与绑定处理完成"
    return bind_updates


def run_video_bind_task(task: TaskInfo, video_per_product_limit: int = 10, max_linked_count: int = 18):
    """新品绑定视频主任务"""
    task.current_step = "加载新发链接监控数据..."
    task.progress = 0

    browser = None
    try:
        bind_data = load_new_links_for_video_bind()
        type_to_ids = bind_data["type_to_ids"]
        pid_to_rowidxs = bind_data["pid_to_rowidxs"]
        df = bind_data["df"]
        excel_path = bind_data["excel_path"]
        sheet_name = bind_data["sheet_name"]
        bind_col = bind_data["bind_col"]
        filtered_count = int(bind_data.get("filtered_count", 0))

        if not type_to_ids:
            task.current_step = "新发链接监控中无可处理数据（类型为空或已绑定视频）"
            return

        total_ids = filtered_count if filtered_count > 0 else sum(len(v) for v in type_to_ids.values())
        task.total = total_ids

        task.current_step = "启动浏览器..."
        browser = BrowserManager()
        if not browser.setup():
            raise Exception("浏览器启动失败")

        task.current_step = "进入视频银行并登录..."
        if not _login_for_video_bank(browser, task):
            raise Exception("视频银行登录失败")

        bind_updates = process_videos(
            task=task,
            browser=browser,
            type_to_ids=type_to_ids,
            pid_to_rowidxs=pid_to_rowidxs,
            video_per_product_limit=video_per_product_limit,
            max_linked_count=max_linked_count,
        )

        # 仅追加写入结果，不覆盖已有绑定值
        save_bind_results_append_only(
            excel_path=excel_path,
            sheet_name=sheet_name,
            df=df,
            bind_col=bind_col,
            updates=bind_updates or {},
        )

        task.progress = task.total
        if not task.current_step:
            task.current_step = "新品绑定视频完成"

    except Exception as e:
        logger.error(f"新品绑定视频任务异常: {e}")
        task.error = str(e)
        raise
    finally:
        try:
            if browser:
                browser.quit()
        except Exception:
            pass

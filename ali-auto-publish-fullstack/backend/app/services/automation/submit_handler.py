# -*- coding: utf-8 -*-
"""
产品提交和验证模块
重构自: main_属性融合.py 中的 direct_submit_product()
"""
import time
import re
from typing import List, Optional, Tuple
from urllib.parse import urlparse, parse_qs

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException

from app.core.logger import setup_logger

logger = setup_logger("submit_handler")


def _collect_publish_blockers(driver) -> List[str]:
    """检测页面是否仍有阻断发布的错误。"""
    issues: List[str] = []
    try:
        from app.services.automation.compliance_filler import verify_form_ready

        _, form_issues = verify_form_ready(driver)
        issues.extend(form_issues)
    except Exception:
        pass

    try:
        body_text = driver.find_element(By.TAG_NAME, "body").text or ""
        if "请上传相关产品图片" in body_text and "请上传相关产品图片" not in issues:
            issues.append("请上传相关产品图片")
        if "报错反馈" in body_text:
            from app.services.automation.compliance_filler import discover_error_feedback_labels

            for label in discover_error_feedback_labels(body_text):
                issues.append(f"报错反馈: {label}")
    except Exception:
        pass
    return list(dict.fromkeys(issues))


def _extract_primary_id_from_url(url: str) -> Optional[str]:
    try:
        q = parse_qs(urlparse(url).query)
        pid = (q.get("primaryId") or [""])[0].strip()
        return pid or None
    except Exception:
        return None


def submit_and_verify(driver) -> Tuple[bool, Optional[str]]:
    """
    直接提交产品（增强版：智能判断成功/失败/弹窗，并返回状态）

    Returns:
        (是否成功, primaryId)
    """
    try:
        blockers = _collect_publish_blockers(driver)
        if blockers:
            country_only = blockers and all("国别化阶梯价" in b for b in blockers)
            if country_only:
                try:
                    from app.services.automation.compliance_filler import (
                        _fill_country_ladder_price,
                        _read_main_ladder_from_page,
                    )

                    logger.warning("提交前国别化阶梯价报错，尝试补填后继续提交...")
                    tiers = _read_main_ladder_from_page(driver)
                    _fill_country_ladder_price(driver, None, tiers or None)
                    time.sleep(2)
                    blockers = _collect_publish_blockers(driver)
                except Exception as exc:
                    logger.warning(f"国别化阶梯价提交前补填失败: {exc}")
            if blockers and all("国别化阶梯价" in b for b in blockers):
                logger.warning(f"国别化阶梯价仍报错，仍尝试提交: {blockers}")
                blockers = []
            if blockers:
                logger.error(f"提交前检测到未填项，拒绝提交: {blockers}")
                return False, None

        driver.execute_script("window.scrollTo(0, 0);")
        time.sleep(0.25)

        submit_btn = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((
                By.XPATH,
                "//button[contains(.,'提交') or contains(.,'发布') or @id='submitBtn' or contains(@class,'submit-btn')]"
            ))
        )
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", submit_btn)
        time.sleep(0.15)
        if not submit_btn.is_enabled():
            logger.warning("提交按钮不可点击，疑似未满足必填项")
            return False, None
        logger.info("定位到提交按钮，点击")
        driver.execute_script("arguments[0].click();", submit_btn)
        logger.info("已点击提交按钮")

        wait = WebDriverWait(driver, 15)
        start_time = time.time()
        original_url = driver.current_url

        # 方案1：URL变化
        try:
            WebDriverWait(driver, 8).until(lambda d: d.current_url != original_url)
            new_url = driver.current_url
            if "success.htm" in new_url and "isSuccess=true" in new_url:
                primary_id = _extract_primary_id_from_url(new_url)
                logger.info(f"检测到成功跳转到 success 页面, primaryId={primary_id}")
                return True, primary_id
        except TimeoutException:
            pass

        # 方案2：质量分检测提示弹窗
        try:
            quality_popup = WebDriverWait(driver, 3).until(
                EC.presence_of_element_located((
                    By.XPATH,
                    "//div[contains(@class, 'next-dialog') and .//div[contains(text(), '质量分检测提示')]]"
                ))
            )
            logger.warning("检测到“质量分检测提示”弹窗，判定为发布异常")
            try:
                back_btn = quality_popup.find_element(By.XPATH, ".//button[contains(text(), '返回修改')]" )
                driver.execute_script("arguments[0].click();", back_btn)
            except Exception:
                try:
                    close_btn = quality_popup.find_element(By.XPATH, ".//i[contains(@class, 'next-icon-close')]" )
                    driver.execute_script("arguments[0].click();", close_btn)
                except Exception:
                    driver.find_element(By.TAG_NAME, "body").click()
            return False, None
        except TimeoutException:
            pass

        # 方案3：关键词检测
        success_keywords = ["进入审核", "提交成功", "审核通过", "发布成功", "Success"]
        error_keywords = ["失败", "请填写", "不能为空", "校验", "error", "invalid", "不合法"]

        while time.time() - start_time < 15:
            blockers = _collect_publish_blockers(driver)
            if blockers:
                country_err = any("国别化阶梯价" in b for b in blockers)
                if country_err and time.time() - start_time < 5:
                    try:
                        from app.services.automation.compliance_filler import (
                            _fill_country_ladder_price,
                            _read_main_ladder_from_page,
                        )
                        logger.warning("提交后国别化阶梯价报错，尝试补填并重提...")
                        tiers = _read_main_ladder_from_page(driver)
                        _fill_country_ladder_price(driver, None, tiers or None)
                        time.sleep(2)
                        driver.execute_script(
                            "const b=[...document.querySelectorAll('button')].find(x=>"
                            "x.offsetParent&&(x.innerText||'').includes('提交'));"
                            "if(b)b.click();"
                        )
                        time.sleep(3)
                        blockers = _collect_publish_blockers(driver)
                        if not blockers:
                            continue
                    except Exception as exc:
                        logger.warning(f"国别化阶梯价补填失败: {exc}")
                logger.error(f"提交后仍存在校验错误: {blockers}")
                return False, None

            page_text = driver.find_element(By.TAG_NAME, "body").text.lower()
            current_url = (driver.current_url or "").lower()
            if "publish.htm" in current_url and "post.alibaba.com" in current_url:
                if any(kw.lower() in page_text for kw in error_keywords):
                    logger.error("仍在发品编辑页且存在错误提示，判定为失败")
                    return False, None

            for kw in success_keywords:
                if kw.lower() in page_text:
                    if "success.htm" in current_url or "isSuccess=true" in current_url:
                        primary_id = _extract_primary_id_from_url(driver.current_url)
                        logger.info(f"提交成功！检测到关键词：{kw}, primaryId={primary_id}")
                        return True, primary_id
                    blockers = _collect_publish_blockers(driver)
                    if blockers:
                        logger.error(f"检测到成功文案但表单仍有错误: {blockers}")
                        return False, None
                    primary_id = _extract_primary_id_from_url(driver.current_url)
                    logger.info(f"提交成功！检测到关键词：{kw}, primaryId={primary_id}")
                    return True, primary_id
            for kw in error_keywords:
                if kw.lower() in page_text:
                    logger.error(f"提交失败！检测到关键词：{kw}")
                    return False, None
            time.sleep(1)

        if "publish.htm" in (driver.current_url or ""):
            blockers = _collect_publish_blockers(driver)
            if blockers:
                logger.error(f"超时且仍在编辑页，报错: {blockers}")
            else:
                logger.warning("15秒内未跳转成功页，判定为失败")
            return False, None

        logger.warning("15秒内未检测到明确结果，判定为失败")
        return False, None

    except Exception as e:
        logger.error(f"submit_and_verify 异常: {e}")
        return False, None

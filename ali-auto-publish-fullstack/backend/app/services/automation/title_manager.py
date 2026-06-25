# -*- coding: utf-8 -*-
"""
标题和关键词填写
重构自: main_属性融合.py 中的 fill_text_field() 和关键词填写逻辑

【如何修改】
- 修改标题填写方式 → 修改 fill_title()
- 修改关键词填写方式 → 修改 fill_keywords()
- 修改文本字段通用填写逻辑 → 修改 _fill_text_field()
"""
import time
import logging
from typing import List

from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import StaleElementReferenceException

from app.core.logger import setup_logger

logger = setup_logger("title_manager")


def _fill_text_field(driver, selector: str, text: str, field_name: str = "字段") -> bool:
    """通用文本字段填写"""
    if not text:
        return False
    for retry in range(3):
        try:
            el = WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.XPATH, selector))
            )
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", el)
            driver.execute_script("document.activeElement.blur();", el)
            el.click()
            driver.execute_script("arguments[0].value = '';", el)
            el.send_keys(Keys.CONTROL + "a")
            el.send_keys(Keys.BACKSPACE)
            el.send_keys(text)
            filled = el.get_attribute("value")
            if filled == text:
                logger.info(f"已填写 {field_name}: {text[:50]}...")
                return True
            time.sleep(0.5)
        except StaleElementReferenceException:
            time.sleep(0.5)
        except Exception as e:
            logger.error(f"填写 {field_name} 失败: {e}")
            if retry == 2:
                return False
            time.sleep(0.5)
    return False


def fill_title(driver, main_title: str, sub_title: str = ""):
    """填写主副标题"""
    _fill_text_field(driver, "//input[@id='productTitle']", main_title, "商品名称")
    # 副标题（如需启用，取消注释下行）
    # _fill_text_field(driver, "//input[@id='productSubTitle']", sub_title, "副标题")


def fill_keywords(driver, keywords: List[str]):
    """
    填写关键词

    【修改指南】
    - 修改关键词输入框选择器 → 更新 keyword_xpath
    - 修改关键词输入方式 → 修改 send_keys 逻辑
    """
    keyword_xpath = "//div[@id='struct-productKeywords']//span[@class='common-input-wrapper']//textarea[@role='input']"
    try:
        el = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.XPATH, keyword_xpath))
        )
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", el)
        el.click()
        el.send_keys(Keys.CONTROL + "a")
        el.send_keys(Keys.BACKSPACE)
        for kw in keywords:
            el.send_keys(kw.strip())
            el.send_keys(Keys.ENTER)
            time.sleep(0.1)
        driver.find_element(By.TAG_NAME, "body").click()
        time.sleep(2)
        logger.info(f"已填写关键词（{len(keywords)}个）")
    except Exception as e:
        logger.error(f"关键词填写失败: {e}")

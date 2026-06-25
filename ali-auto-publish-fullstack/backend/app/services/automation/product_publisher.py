# -*- coding: utf-8 -*-
"""
产品发布器 - 单个产品的完整发布流程
重构自: main_属性融合.py 中的 upload_product_with_title()

【发布流程】
1. 打开发布链接
2. 上传图片（首图 + 主图）
3. 填写标题
4. 填写关键词
5. 选择规格（材质/尺寸）
6. 设置阶梯价格
7. 填写属性（满足40%差异规则）
8. 填写产品详情
9. 提交并验证

【如何修改】
- 增减发布步骤 → 修改 publish_single_product() 函数中的步骤列表
- 修改某个步骤的逻辑 → 编辑对应的子模块文件
- 调整步骤顺序 → 修改 publish_single_product() 中的调用顺序
"""
import os
import time
import random
import json
import logging
import re
from typing import Dict, List, Optional, Tuple

from app.core.settings import AppConfig
from app.core.logger import setup_logger

# 发品子模块提前导入，避免价格等步骤跑完才因缺模块失败
from app.services.automation.attribute_filler import (  # noqa: F401
    fill_all_attributes_with_diff,
    verify_filled_attributes,
)
from app.services.automation.detail_filler import enhance_product_detail, verify_detail_uploads  # noqa: F401
from app.services.automation.price_setter import (  # noqa: F401
    fill_sale_unit,
    set_ladder_price,
)
from app.services.automation.submit_handler import submit_and_verify  # noqa: F401

logger = setup_logger("product_publisher")


def _extract_category_id(url: str) -> str:
    text = str(url or "").strip()
    if not text:
        return ""
    m = re.search(r"(?:catId|catid|categoryId|leafCatId)=(\d+)", text, flags=re.IGNORECASE)
    return m.group(1) if m else ""


def _step_tick(step_timings: Optional[Dict[str, float]], step: str, t0: List[float]) -> None:
    """记录上一步耗时（秒），step_timings[step]=duration。"""
    if step_timings is None:
        return
    now = time.perf_counter()
    step_timings[step] = round(now - t0[0], 2)
    t0[0] = now


def publish_single_product(
    browser,
    product: Dict,
    main_title: str,
    sub_title: str,
    keywords: List[str],
    cfg: AppConfig,
    task=None,
    skip_submit: bool = False,
    step_timings: Optional[Dict[str, float]] = None,
) -> Tuple[bool, Optional[str]]:
    """
    发布单个产品的完整流程

    Args:
        browser: BrowserManager 实例
        product: 产品信息字典
        main_title: 主标题
        sub_title: 副标题
        keywords: 关键词列表
        cfg: 应用配置

    Returns:
        (是否发布成功, 新发产品ID primaryId)
    """
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.common.exceptions import TimeoutException

    driver = browser.driver
    pid = product["pid"]
    category = product["category"]
    filename = product["filename"]

    def _ensure_not_stopped() -> bool:
        if task is not None and getattr(task, "should_stop", None) and task.should_stop():
            logger.info(f"产品 {pid} 收到停止信号，中断当前发布")
            return False
        return True

    _t0 = [time.perf_counter()]

    try:
        if not _ensure_not_stopped():
            return False, None
        # ===== Step 1: 打开发布链接 =====
        group_map = cfg.group_urls.group_url_map or {}
        post_url = str(group_map.get(category) or "").strip()
        if not post_url:
            cat_norm = re.sub(r"[\s\-_]+", "", str(category or "")).lower()
            for g, u in group_map.items():
                if re.sub(r"[\s\-_]+", "", str(g or "")).lower() == cat_norm:
                    post_url = str(u or "").strip()
                    category = str(g or "").strip() or category
                    break
        if not post_url:
            post_url = str(cfg.group_urls.default_posting_url or "").strip()
        if not post_url:
            logger.error(f"未配置类别 '{category}' 的发布链接")
            return False, None

        # 以“实际发品 URL”反查最终组别，确保规格读取与打开链接一致
        resolved_group = category
        try:
            for g, u in (cfg.group_urls.group_url_map or {}).items():
                if str(u or "").strip() == post_url:
                    resolved_group = str(g or "").strip() or category
                    break
        except Exception:
            resolved_group = category

        category_id = _extract_category_id(post_url)
        logger.info(f"打开发布链接: {post_url}")
        logger.info(f"规格组别解析: 原始组别={category} | 最终组别={resolved_group}")
        if category_id:
            logger.info(f"规格类目ID解析: catId={category_id}")
        driver.get(post_url)
        for _ in range(2):
            if not _ensure_not_stopped():
                return False, None
            time.sleep(0.2)

        # 等待页面加载（基本信息或商品图区域任一出现即可继续）
        try:
            WebDriverWait(driver, 12).until(
                EC.any_of(
                    EC.presence_of_element_located((By.XPATH, "//h2//span[text()='基本信息']")),
                    EC.presence_of_element_located((By.ID, "struct-scImages")),
                )
            )
            logger.info("成功进入产品编辑页面")
        except TimeoutException:
            logger.error("页面未加载出编辑区域")
            return False, None

        from app.services.automation.page_helpers import close_all_popups
        from app.services.automation.country_region import clear_country_region_selection

        close_all_popups(driver)
        clear_country_region_selection(driver)
        _step_tick(step_timings, "1_打开页面", _t0)

        # ===== Step 2: 上传图片 =====
        from app.services.automation.image_uploader import upload_product_images
        primary_path = os.path.join(cfg.paths.primary_image_dir, filename)
        main_dir = os.path.join(cfg.paths.main_image_dir, pid)

        if not upload_product_images(driver, primary_path, main_dir, cfg.upload.batch_size):
            logger.error("图片上传失败")
            return False, None
        _step_tick(step_timings, "2_上传图片", _t0)

        # ===== Step 3: 填写标题 =====
        from app.services.automation.title_manager import fill_title, fill_keywords
        fill_title(driver, main_title, sub_title)

        # ===== Step 4: 填写关键词 =====
        if keywords:
            k = random.randint(cfg.keywords.keyword_min_count,
                              min(cfg.keywords.keyword_max_count, len(keywords)))
            selected = random.sample(keywords, k)
            fill_keywords(driver, selected)
        _step_tick(step_timings, "3_标题关键词", _t0)

        # ===== Step 5: 选择规格 =====
        from app.services.automation.spec_selector import select_specifications, resolve_specs_for_group
        current_page_url = str(driver.current_url or "").strip()
        current_category_id = _extract_category_id(current_page_url) or category_id
        preview_specs = resolve_specs_for_group(
            cfg.attributes,
            resolved_group,
            category_id=current_category_id,
            posting_url=current_page_url or post_url,
        )
        try:
            preview_names = list(preview_specs.keys())
        except Exception:
            preview_names = []
        logger.info(f"规格配置预览: 组别={resolved_group} | 规格数={len(preview_names)} | 规格={preview_names}")
        select_specifications(driver, cfg.attributes, resolved_group, main_dir)
        from app.services.automation.spec_selector import verify_filled_specs
        spec_issues = verify_filled_specs(driver, cfg.attributes, resolved_group, main_dir)
        for msg in spec_issues:
            logger.warning(f"[规格验收] {msg}")
        _step_tick(step_timings, "4_规格选择", _t0)

        # ===== Step 6: 售卖单位 + 阶梯价格 + 发货期 =====
        try:
            fill_sale_unit(driver, cfg.price)
        except Exception as exc:
            logger.warning(f"售卖单位填写异常（非致命）: {exc}")

        if not set_ladder_price(driver, main_dir, cfg.price, cfg.delivery):
            logger.error("阶梯价格设置失败")
            return False, None
        _step_tick(step_timings, "5_价格库存", _t0)

        # ===== Step 7: 生成并填写属性（40%差异规则） =====
        attr_fill_report: Optional[list] = [] if skip_submit else None
        attr_value_audit: Optional[list] = [] if skip_submit else None
        planned_attrs = fill_all_attributes_with_diff(
            driver,
            cfg.attributes,
            fill_report=attr_fill_report,
            acceptance_audit=attr_value_audit,
        )
        if step_timings is not None and skip_submit:
            step_timings["attr_fill_report"] = attr_fill_report or []
            step_timings["attr_value_audit"] = attr_value_audit or []
            step_timings["planned_attrs"] = planned_attrs
        _step_tick(step_timings, "6_属性填写", _t0)

        # ===== Step 8: 填写产品详情（属性填完立即进入，不做中间验收/补全） =====
        enhance_product_detail(driver, cfg.detail, cfg.paths)
        _step_tick(step_timings, "7_详情模块", _t0)

        from app.services.automation.spec_selector import reconcile_value_row_specs, verify_filled_specs
        reconcile_value_row_specs(driver, cfg.attributes, resolved_group, main_dir)
        _step_tick(step_timings, "8_规格补全", _t0)

        if skip_submit:
            final_spec = verify_filled_specs(driver, cfg.attributes, resolved_group, main_dir)
            final_attr = verify_filled_attributes(driver, cfg.attributes, planned_attrs)
            final_detail = verify_detail_uploads(driver, cfg.paths, cfg.detail)
            logger.info("========== 真实验收汇总（未提交） ==========")
            logger.info(f"规格问题 {len(final_spec)} 条: {final_spec or '无'}")
            logger.info(f"属性问题 {len(final_attr)} 条: {final_attr or '无'}")
            logger.info(f"详情图问题 {len(final_detail)} 条: {final_detail or '无'}")
            logger.info("========== 请在浏览器中目视确认后关闭 ==========")
            _step_tick(step_timings, "9_最终验收", _t0)
            if step_timings is not None:
                from app.services.automation.attribute_filler import _sum_numeric_timings
                step_timings["总计"] = _sum_numeric_timings(step_timings)
                logger.info(f"[步骤耗时] {step_timings}")
            return True, None

        # ===== Step 9: 提交并验证 =====
        success, primary_id = submit_and_verify(driver)
        _step_tick(step_timings, "9_提交发布", _t0)
        if step_timings is not None:
            from app.services.automation.attribute_filler import _sum_numeric_timings
            step_timings["总计"] = _sum_numeric_timings(step_timings)
            logger.info(f"[步骤耗时] {step_timings}")

        if success:
            logger.info(f"产品 {pid} 发布成功！primaryId={primary_id}")
            return True, primary_id
        else:
            logger.error(f"产品 {pid} 提交失败")
            return False, None

    except Exception as e:
        logger.error(f"产品 {pid} 发布异常: {e}", exc_info=True)
        return False, None


def _handle_failed_product(filename: str, cfg: AppConfig):
    """处理发布失败的产品（移动异常首图）"""
    try:
        exceptional_dir = cfg.paths.exceptional_main_image_dir
        os.makedirs(exceptional_dir, exist_ok=True)

        # 尝试恢复原始文件名
        original_name = filename
        mapping_file = cfg.paths.name_mapping_file
        if mapping_file and os.path.exists(mapping_file):
            try:
                reverse_map = {}
                with open(mapping_file, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if " → " in line:
                            orig, new = line.split(" → ", 1)
                            reverse_map[new] = orig
                if filename in reverse_map:
                    original_name = reverse_map[filename]
            except Exception:
                pass

        source = os.path.join(cfg.paths.primary_image_dir, filename)
        target = os.path.join(exceptional_dir, original_name)
        if os.path.exists(source):
            os.rename(source, target)
            logger.info(f"异常首图已移至: {target}")
    except Exception as e:
        logger.error(f"处理异常首图失败: {e}")

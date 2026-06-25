# -*- coding: utf-8 -*-
"""
数据分析服务层
综合分析：按老脚本 main.py 思路完整迁移到系统内执行（不外调脚本文件）
"""
import json
import os
import re
import time
import threading
from copy import deepcopy
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd
import requests
from scipy.stats import linregress, ttest_ind

from app.core.admin_runtime_config import resolve_runtime_secret
from app.core.settings import config_manager, get_config
from app.core.task_manager import TaskInfo
from app.core.logger import setup_logger

logger = setup_logger("analysis_service")

_table_cache_lock = threading.RLock()
_table_cache: Dict[str, Dict] = {}

API_BASE_URL = "https://ark.cn-beijing.volces.com/api/v3"
API_ENDPOINT = "/responses"

STORE_DIAGNOSIS_PROMPT = """一、身份与核心要求
你是拥有 8 年以上实战经验的阿里巴巴国际站资深运营专家 & 数据分析师，精通平台算法、流量逻辑、转化链路、行业对标、风险预警与落地运营策略。
请严格基于我提供的 **「周期数据趋势（周汇总）」+「流量渠道明细数据」，按照以下规则、框架，输出100% 数据驱动、逻辑严谨、结论明确、可落地执行 ** 的深度诊断报告，所有分析必须有数据支撑，不做无依据的主观臆断。
二、必须严格遵守的涨跌评级标准
上涨区间
正常波动：±5% 以内
小幅上涨：+5% ～ +10%
明显上涨：+10% ～ +20%
大幅上涨 / 爆发增长：＞ +20%
下跌区间
正常波动：±5% 以内
小幅下跌：-5% ～ -10%
明显下跌：-10% ～ -20%
大幅下跌 / 崩盘风险：＜ -20%
三、数据维度与分析要求（必须 100% 覆盖）
（一）数据维度说明
你将收到两类核心数据：
周期数据趋势（周汇总）：包含「我的数据（最新 / 上周 / 差值 / 环比）」+「行业平均（最新 / 上周 / 差值 / 环比）」+「同行优秀（最新 / 上周）」，覆盖全店、搜索、自然、营销、信保、客服等全链路指标
流量渠道明细数据：包含各渠道（搜索、系统推荐、其他、店内、会场、直接访问、询盘、收藏等）的「店铺访问人数、店内询盘人数、店内 TM 咨询人数、商机转化率」
（二）核心分析要求
所有指标必须先做 3 层判定：① 自身周环比涨跌等级 ② 与行业平均的对标差距 ③ 与同行优秀的对标差距
完整漏斗分析：从「曝光→点击→访客→询盘→TM 咨询→加购→信保成交」全链路拆解，定位每一层的健康度、瓶颈、流失原因
流量结构深度拆解：结合渠道数据，分析各流量来源的质量、占比、贡献、利弊，定位结构隐患
风险分级预警：所有风险点必须标注「严重风险 / 一般风险 / 轻微隐患」，明确影响范围
优化方案分级落地：按「紧急修复（1-3 天）→ 高优先级增长（1 周内）→ 中优先级优化（1 个月内）→ 长期战略（3 个月）」分级，每个方案必须明确「动作、目标、数据验收标准」
行业对标分析：必须横向对比行业平均、同行优秀，明确店铺在行业中的位置、差距、追赶路径
结论先行：每个模块先给核心结论，再做数据拆解，最后给优化方向，逻辑清晰，重点突出
四、完整分析框架（必须严格按此结构输出）
模块 1：店铺整体经营大盘深度诊断
1.1 核心经营指标全链路对标分析
必须覆盖以下指标，每个指标做 3 层判定 + 对标分析：
店铺访问人数、店铺访问次数、人均访问深度（访问次数 / 访问人数）
全店曝光次数、全店点击次数、全店点击率（点击 / 曝光）
询盘人数、询盘个数、询盘转化率（询盘人数 / 访问人数）
TM 咨询人数、TM 咨询转化率
加购笔数、加购人数、加购率
信保交易订单个数、信保交易金额、信保转化率（订单数 / 询盘数）
商机人数、全店品的商机量、商机转化率（商机人数/访问人数）
近 30 天商机人数（长期趋势）
客服指标：及时回复率、极速回复率、平均回复时长
1.2 全链路漏斗健康度诊断
拆解「全店曝光次数→全店点击次数→店铺访问人数→商机人数→信保交易金额(美元)」每一层的转化率、环比变化、行业对标
定位当前漏斗的最薄弱环节（如：曝光够但点击低 / 点击够但询盘低 / 询盘够但成交低）
结合流量渠道数据，解释漏斗变化的核心原因
核心漏斗问题原因
1.3 店铺整体阶段判定
综合所有数据，明确店铺当前处于：爆发增长期 / 稳定上升期 / 平稳期 / 下滑期 / 危机期
总结核心增长引擎、核心风险点
模块 2：搜索流量专项深度诊断
2.1 搜索流量核心指标分析
搜索曝光次数、搜索点击次数、搜索点击率（点击 / 曝光）：环比涨跌 + 行业对标
搜索流量占全店曝光 / 点击的比例，判断搜索流量的基本盘地位
搜索流量对全店询盘的贡献度（结合渠道数据）
2.2 搜索流量质量与权重诊断
分析搜索点击率的行业对标：高于行业说明主图 / 标题 / 关键词精准，低于行业说明匹配度不足
结合搜索点击→询盘的转化，判断搜索流量的精准度、承接能力
诊断店铺自然搜索权重的健康度、增长瓶颈
2.3 搜索流量优化方向
曝光增长策略、点击率优化策略、转化提升策略
模块 3：自然流量专项深度诊断
3.1 自然流量核心指标分析
自然曝光量、自然点击量、自然商机量：环比涨跌 + 行业对标
自然流量占全店流量的比例，判断免费流量的健康度
自然点击率、自然商机转化率的行业对标，分析免费流量的转化效率
3.2 自然流量结构与标签诊断
结合渠道数据，拆解自然流量中「搜索、系统推荐、其他」的占比
分析系统推荐流量的质量、标签匹配度，判断店铺标签的精准性
重点预警「其他渠道占比过高」的结构风险
3.3 自然流量优化方向
自然曝光增长策略、自然转化提升策略、流量结构优化策略
模块 4：营销流量（付费推广）专项深度诊断
4.1 营销流量核心指标分析
营销曝光次数、营销点击次数、营销点击率：环比涨跌 + 行业对标
全站推曝光、全站推点击、全站推商机量：环比涨跌 + 行业对标
标准推广曝光、标准推广点击（若为 0 需重点分析）
营销流量占全店流量的比例，判断付费流量的健康度
4.2 推广效率与 ROI 诊断
分析营销点击→商机的转化效率，定位「高点击低商机」的流量浪费问题
对比自然流量与营销流量的转化效率，判断付费流量的性价比
诊断推广结构是否健康（如仅依赖全站推、无标准推广的问题）
4.3 营销流量优化方向
推广结构优化、高转化商品放大、低转化商品优化、ROI 提升策略
模块 5：流量渠道结构深度诊断
5.1 全渠道明细分析
必须覆盖所有渠道（搜索、系统推荐、其他、店内、会场、直接访问、询盘、站内收藏、站外、RFQ、直播等），每个渠道分析：
访问人数占全店的比例
商机转化率（询盘 + TM / 访问人数）
渠道质量高低排序（按转化率）
渠道对全店询盘的贡献度
对所有的流量渠道进行综合分析，主要当前的流量结构是否健康，是否存在问题，如果存在问题，需要给出优化建议。
5.2 流量结构健康度诊断
核心免费流量（搜索 + 系统推荐）占比是否健康
私域老客流量（直接访问 + 询盘 + 收藏）占比与转化价值
活动流量（会场）的贡献与稳定性
「其他渠道」占比是否过高，是否存在不可控风险
付费流量占比是否合理，是否有主动获客能力
零转化 / 低转化渠道的流量浪费情况
5.3 流量结构利弊总结
明确当前结构的核心优势、核心隐患
给出健康流量结构的参考目标（按渠道占比）
模块 6：行业对标与竞争定位分析
6.1 行业横向对标
对比店铺与行业平均、同行优秀的核心指标差距（曝光、点击、询盘、成交、转化）
明确店铺在行业中的位置：领先 / 中等 / 落后
定位与同行优秀的核心差距（如：曝光不足 / 转化不足 / 成交不足）
6.2 竞争优势与机会
店铺领先于行业的指标，总结核心竞争优势
行业增长趋势（行业环比），判断店铺是否踩中行业风口
可追赶的机会点（如：行业平均增长，店铺可放大优势）
模块 7：核心风险分级预警
按严重程度分级，每个风险点必须说明：风险内容、数据支撑、影响范围、修复优先级
🔴 严重风险（立即修复，否则影响店铺权重 / 流量）
🟡 一般风险（1 周内修复，影响转化 / 增长）
🟢 轻微隐患（长期优化，影响长期增长）
模块 8：分级落地优化方案（可直接执行）
每个方案必须包含：执行动作、预期目标、数据验收标准
8.1 紧急修复项（1-3 天必须完成）
针对严重风险的 immediate 动作
8.2 高优先级增长项（1 周内完成）
针对核心增长瓶颈的动作，快速提升数据
8.3 中优先级优化项（1 个月内完成）
针对流量结构、转化链路的中长期优化
8.4 长期战略优化项（3 个月内完成）
针对店铺长期健康、竞争壁垒的动作
模块 9：最终总结与运营建议
一句话总结店铺当前的核心状态
核心增长逻辑与核心风险
未来 1 个月的核心运营主线
健康流量结构与指标的参考目标"""


def run_analysis_task(
    task: TaskInfo,
    task_type: str,
    source_file: Optional[str] = None,
    user_id: int = 0,
    skip_points: bool = False,
    token: str = "",
):
    cfg = config_manager.reload_from_disk() if task_type in ("title_optimize", "traffic_ai") else get_config()
    task.current_step = f"初始化 {task_type} 分析..."
    try:
        if task_type == "comprehensive":
            _run_comprehensive_analysis(task, cfg)
        elif task_type == "single_analysis":
            _run_single_analysis(task, cfg)
        elif task_type == "title_optimize":
            from app.services.title_optimize_service import run_title_optimize_task
            manual_ids = []
            if source_file:
                manual_ids = [x.strip() for x in str(source_file).split(",") if x.strip()]
            logger.info(f"产品优化建议任务启动参数: manual_ids={manual_ids}")
            run_title_optimize_task(
                task, manual_ids, user_id=user_id, skip_points=skip_points, token=token
            )
        elif task_type == "traffic_ai":
            _run_traffic_ai_analysis(
                task, cfg, user_id=user_id, skip_points=skip_points, token=token
            )
        else:
            raise ValueError(f"未知的分析类型: {task_type}")
        task.current_step = "分析完成"
    except Exception as e:
        logger.error(f"分析任务异常: {e}")
        task.error = str(e)
        raise


# 日数据下载完成后自动执行（与 Dashboard「自动分析数据」一致）
DAILY_DOWNLOAD_ANALYSIS_CHAIN = (
    ("comprehensive", "综合分析"),
    ("single_analysis", "单品分析"),
    ("traffic_ai", "流量分析"),
    ("title_optimize", "产品优化建议"),
)


def run_analysis_chain_after_daily_download(download_task: TaskInfo) -> None:
    """日数据/周数据下载结束后，在同一任务线程内顺序执行分析。"""
    from datetime import datetime

    from app.core.task_manager import TaskStatus, task_manager

    if download_task.should_stop():
        return

    logger.info("数据下载完成，开始自动分析链")
    failed: list[str] = []

    for task_type, label in DAILY_DOWNLOAD_ANALYSIS_CHAIN:
        if download_task.should_stop():
            logger.info("自动分析链已中止")
            break

        analysis_id = f"analysis_{task_type}"
        existing = task_manager.get_task(analysis_id)
        if existing and existing.status == TaskStatus.RUNNING:
            logger.warning(f"{label} 正在运行，跳过")
            continue

        download_task.current_step = f"下载完成，正在执行{label}..."
        analysis_task = task_manager.create_task(analysis_id, label)
        analysis_task.status = TaskStatus.RUNNING
        analysis_task.started_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        analysis_task._stop_event = download_task._stop_event
        analysis_task._pause_event = download_task._pause_event

        try:
            run_analysis_task(analysis_task, task_type, "" if task_type == "title_optimize" else None)
            if analysis_task.status not in (TaskStatus.FAILED,):
                analysis_task.status = TaskStatus.COMPLETED
        except Exception as e:
            logger.error(f"{label} 失败: {e}")
            failed.append(label)
            analysis_task.status = TaskStatus.FAILED
            analysis_task.error = str(e)
        finally:
            analysis_task.finished_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if download_task.should_stop():
        download_task.current_step = "已停止"
    elif failed:
        download_task.current_step = f"分析完成（部分失败: {', '.join(failed)}）"
    else:
        download_task.current_step = "下载与分析已全部完成"
    logger.info(download_task.current_step)


# ====== 迁移自老脚本 main.py 的辅助函数 ======

def is_valid_filename(filename):
    """兼容旧周报命名 + 日数据命名。"""
    old_style = bool(re.match(r'^\d{6}-\d{6}\.(xlsx|xls)$', filename, re.IGNORECASE))
    products_daily = bool(re.match(r'^Products-\d{4}-\d{2}-\d{2}\.(xlsx|xls)$', filename, re.IGNORECASE))
    return old_style or products_daily


def is_daily_filename(filename):
    return bool(re.match(r'^Products-\d{4}-\d{2}-\d{2}\.(xlsx|xls)$', filename, re.IGNORECASE))


def extract_date_from_daily_filename(filename):
    match = re.match(r'^Products-(\d{4})-(\d{2})-(\d{2})\.(xlsx|xls)$', filename, re.IGNORECASE)
    if match:
        y, m, d = match.groups()[:3]
        return f"{y[2:]}{m}{d}"
    return None


def normalize_status(val):
    if pd.isna(val):
        return None
    str_val = str(val).strip().upper()
    if str_val == "Y":
        return True
    elif str_val == "N":
        return False
    return None


def analyze_trend_with_regression(values, p_value_threshold, min_data_points):
    values = np.array(values)
    valid_vals = values[~np.isnan(values)]
    if len(valid_vals) < min_data_points:
        return None
    x = np.arange(len(valid_vals))
    try:
        slope, _, _, p_value, _ = linregress(x, valid_vals)
        if p_value < p_value_threshold:
            return "上升" if slope > 0 else "下降"
        return "平稳"
    except Exception:
        return "平稳"


def get_change_symbol(old_val, new_val):
    if np.isnan(old_val) or np.isnan(new_val):
        return None
    if new_val > old_val:
        return "↑"
    elif new_val < old_val:
        return "↓"
    return "—"


def safe_sub(a, b):
    a = a if pd.notna(a) and a is not None else 0
    b = b if pd.notna(b) and b is not None else 0
    return max(a - b, 0)


def safe_add(a, b):
    a = a if pd.notna(a) and a is not None else 0
    b = b if pd.notna(b) and b is not None else 0
    return a + b


def calculate_volatility_metrics(df_input, base_names_sorted):
    if len(base_names_sorted) < 2:
        return df_input
    latest_week = base_names_sorted[-1]
    previous_week = base_names_sorted[-2]
    df = df_input.copy()
    df["异动"] = None
    df["涨跌"] = None
    for idx, row in df.iterrows():
        latest_val = row[latest_week] if pd.notna(row[latest_week]) else 0
        previous_val = row[previous_week] if pd.notna(row[previous_week]) else 0
        volatility = latest_val - previous_val
        df.at[idx, "异动"] = volatility
        if previous_val != 0:
            df.at[idx, "涨跌"] = f"{(volatility / previous_val):.1%}"
        else:
            df.at[idx, "涨跌"] = "∞" if volatility > 0 else "-∞" if volatility < 0 else "0%"
    return df


def analyze_traffic_volatility(df_exposure, base_names_sorted, all_data):
    if len(base_names_sorted) < 2:
        return set()
    volatile_products = set()
    latest_week = base_names_sorted[-1]
    previous_week = base_names_sorted[-2]

    exposure_df = all_data["全店曝光次数"]
    search_exposure_df = all_data["搜索曝光次数"]
    click_df = all_data["全店点击次数"]
    search_click_df = all_data["搜索点击次数"]
    visit_df = all_data["访问人数"]

    for pid in exposure_df.index:
        if pid not in df_exposure["产品ID"].values:
            continue
        latest_val = exposure_df.loc[pid, latest_week] if pd.notna(exposure_df.loc[pid, latest_week]) else 0
        previous_val = exposure_df.loc[pid, previous_week] if pd.notna(exposure_df.loc[pid, previous_week]) else 0
        volatility = latest_val - previous_val
        if volatility >= 100 or volatility <= -100:
            volatile_products.add(pid)

    if len(base_names_sorted) >= 3:
        for pid in exposure_df.index:
            if pid not in df_exposure["产品ID"].values:
                continue
            latest_val = exposure_df.loc[pid, latest_week] if pd.notna(exposure_df.loc[pid, latest_week]) else 0
            previous_val = exposure_df.loc[pid, previous_week] if pd.notna(exposure_df.loc[pid, previous_week]) else 0
            volatility = latest_val - previous_val
            if (50 < volatility < 100) or (-100 < volatility <= -50):
                recent_weeks = base_names_sorted[-3:]
                values = [exposure_df.loc[pid, week] if pd.notna(exposure_df.loc[pid, week]) else 0 for week in recent_weeks]
                is_continuous_up = all(values[i] <= values[i + 1] for i in range(len(values) - 1)) and any(values[i] < values[i + 1] for i in range(len(values) - 1))
                is_continuous_down = all(values[i] >= values[i + 1] for i in range(len(values) - 1)) and any(values[i] > values[i + 1] for i in range(len(values) - 1))
                if is_continuous_up or is_continuous_down:
                    volatile_products.add(pid)

    for pid in search_exposure_df.index:
        if pid not in df_exposure["产品ID"].values:
            continue
        latest_val = search_exposure_df.loc[pid, latest_week] if pd.notna(search_exposure_df.loc[pid, latest_week]) else 0
        previous_val = search_exposure_df.loc[pid, previous_week] if pd.notna(search_exposure_df.loc[pid, previous_week]) else 0
        volatility = latest_val - previous_val
        if volatility >= 100 or volatility <= -100:
            volatile_products.add(pid)

    if len(base_names_sorted) >= 8:
        recent_8_weeks = base_names_sorted[-8:]
        for pid in search_exposure_df.index:
            if pid not in df_exposure["产品ID"].values:
                continue
            latest_val = search_exposure_df.loc[pid, latest_week] if pd.notna(search_exposure_df.loc[pid, latest_week]) else 0
            previous_val = search_exposure_df.loc[pid, previous_week] if pd.notna(search_exposure_df.loc[pid, previous_week]) else 0
            volatility = latest_val - previous_val
            if (50 < volatility < 100) or (-100 < volatility <= -50):
                values_8 = [search_exposure_df.loc[pid, week] if pd.notna(search_exposure_df.loc[pid, week]) else 0 for week in recent_8_weeks]
                max_val_8 = max(values_8)
                min_val_8 = min(values_8)
                if max_val_8 - min_val_8 > 500:
                    volatile_products.add(pid)
                    continue
                consecutive_down_count = 0
                max_consecutive_down = 0
                for i in range(len(values_8) - 1):
                    if values_8[i] > values_8[i + 1]:
                        consecutive_down_count += 1
                        max_consecutive_down = max(max_consecutive_down, consecutive_down_count)
                    else:
                        consecutive_down_count = 0
                if max_consecutive_down >= 4:
                    volatile_products.add(pid)

    for pid in click_df.index:
        if pid not in df_exposure["产品ID"].values:
            continue
        latest_val = click_df.loc[pid, latest_week] if pd.notna(click_df.loc[pid, latest_week]) else 0
        previous_val = click_df.loc[pid, previous_week] if pd.notna(click_df.loc[pid, previous_week]) else 0
        volatility = latest_val - previous_val
        if volatility >= 100 or volatility <= -100:
            volatile_products.add(pid)

    if len(base_names_sorted) >= 3:
        for pid in click_df.index:
            if pid not in df_exposure["产品ID"].values:
                continue
            latest_val = click_df.loc[pid, latest_week] if pd.notna(click_df.loc[pid, latest_week]) else 0
            previous_val = click_df.loc[pid, previous_week] if pd.notna(click_df.loc[pid, previous_week]) else 0
            volatility = latest_val - previous_val
            if (50 < volatility < 100) or (-100 < volatility <= -50):
                recent_weeks = base_names_sorted[-3:]
                values = [click_df.loc[pid, week] if pd.notna(click_df.loc[pid, week]) else 0 for week in recent_weeks]
                is_continuous_up = all(values[i] <= values[i + 1] for i in range(len(values) - 1)) and any(values[i] < values[i + 1] for i in range(len(values) - 1))
                is_continuous_down = all(values[i] >= values[i + 1] for i in range(len(values) - 1)) and any(values[i] > values[i + 1] for i in range(len(values) - 1))
                if is_continuous_up or is_continuous_down:
                    volatile_products.add(pid)

    for pid in search_click_df.index:
        if pid not in df_exposure["产品ID"].values:
            continue
        latest_val = search_click_df.loc[pid, latest_week] if pd.notna(search_click_df.loc[pid, latest_week]) else 0
        previous_val = search_click_df.loc[pid, previous_week] if pd.notna(search_click_df.loc[pid, previous_week]) else 0
        volatility = latest_val - previous_val
        if volatility >= 15 or volatility <= -15:
            volatile_products.add(pid)

    for pid in visit_df.index:
        if pid not in df_exposure["产品ID"].values:
            continue
        latest_val = visit_df.loc[pid, latest_week] if pd.notna(visit_df.loc[pid, latest_week]) else 0
        previous_val = visit_df.loc[pid, previous_week] if pd.notna(visit_df.loc[pid, previous_week]) else 0
        volatility = latest_val - previous_val
        if volatility >= 10 or volatility <= -10:
            volatile_products.add(pid)

    return volatile_products


def save_volatility_data(volatile_products, all_data, base_names_sorted, VOLATILITY_OUTPUT, TARGET_COLUMNS):
    if not volatile_products:
        logger.info("未发现符合流量波动规则的产品")
        return

    derived_metrics = {
        "自然曝光": ("全店曝光次数", "全站推广曝光次数"),
        "自然点击": ("全店点击次数", "全站推广点击次数"),
        "场景曝光": ("全店曝光次数", "搜索曝光次数"),
        "场景点击": ("全店点击次数", "搜索点击次数")
    }

    with pd.ExcelWriter(VOLATILITY_OUTPUT, engine='openpyxl') as writer:
        for col in TARGET_COLUMNS:
            if col in all_data:
                df = all_data[col]
                volatile_df = df[df.index.isin(volatile_products)].copy().reset_index()
                if not volatile_df.empty:
                    volatile_df.to_excel(writer, sheet_name=col, index=False)

        for metric, (minuend, subtrahend) in derived_metrics.items():
            df_min = all_data[minuend]
            df_sub = all_data[subtrahend]
            records = []
            for pid in volatile_products:
                row = {"产品ID": pid}
                for week in base_names_sorted:
                    a = df_min.loc[pid, week] if pid in df_min.index else np.nan
                    b = df_sub.loc[pid, week] if pid in df_sub.index else np.nan
                    val = np.nan if (metric.startswith("场景") and pd.isna(a)) else (a or 0) - (b or 0)
                    row[week] = val
                records.append(row)
            df_metric = pd.DataFrame(records, columns=["产品ID"] + base_names_sorted)
            df_metric = calculate_volatility_metrics(df_metric, base_names_sorted)
            df_metric.to_excel(writer, sheet_name=metric, index=False)

        if len(base_names_sorted) >= 2:
            latest_week = base_names_sorted[-1]
            previous_week = base_names_sorted[-2]
            summary_cols = TARGET_COLUMNS + ["自然曝光", "自然点击", "场景曝光", "场景点击"]
            summary_rows = []
            for pid in sorted(volatile_products):
                row = {"产品ID": pid}
                for col in TARGET_COLUMNS:
                    df = all_data.get(col)
                    val = (df.loc[pid, latest_week] if df is not None and pid in df.index else 0) - \
                          (df.loc[pid, previous_week] if df is not None and pid in df.index else 0)
                    row[col] = val
                for metric, (minuend, subtrahend) in derived_metrics.items():
                    df_a = all_data.get(minuend)
                    df_b = all_data.get(subtrahend)
                    a_new = df_a.loc[pid, latest_week] if df_a is not None and pid in df_a.index else 0
                    a_old = df_a.loc[pid, previous_week] if df_a is not None and pid in df_a.index else 0
                    b_new = df_b.loc[pid, latest_week] if df_b is not None and pid in df_b.index else 0
                    b_old = df_b.loc[pid, previous_week] if df_b is not None and pid in df_b.index else 0
                    row[metric] = (a_new - b_new) - (a_old - b_old)
                summary_rows.append(row)
            pd.DataFrame(summary_rows, columns=["产品ID"] + summary_cols).to_excel(writer, sheet_name="异动", index=False)


def _normalize_header_token(val: str) -> str:
    return str(val).strip().replace(" ", "").replace("，", "").replace(",", "")


def _detect_excel_header_row(path: str, max_scan_rows: int = 20) -> Optional[int]:
    """自动检测真实表头行（返回0-based行号），用于跳过前置无效说明行。"""
    try:
        preview = pd.read_excel(path, header=None, nrows=max_scan_rows)
    except Exception:
        return None

    if preview is None or preview.empty:
        return None

    expected_headers = {
        "产品ID", "产品名称", "产品名", "是否橱窗", "是否顶展", "是否P4P",
        "搜索曝光次数", "搜索点击次数", "搜索点击率", "访问人数", "询盘个数", "近90天商机人数",
        "询盘人数", "询盘率", "收藏人数", "分享人数", "对比人数", "提交订单个数",
        "TM咨询人数", "产品负责人", "RTS线上买家数", "RTS线上实收GMV", "全店曝光次数",
        "全店点击次数", "营销曝光次数", "营销点击次数", "标准推广曝光次数", "标准推广点击次数",
        "全站推广曝光次数", "全站推广点击次数"
    }
    expected_norm = {_normalize_header_token(x) for x in expected_headers}

    for idx in range(len(preview)):
        raw_vals = [str(v) for v in preview.iloc[idx].tolist() if pd.notna(v)]
        vals = [_normalize_header_token(v) for v in raw_vals if str(v).strip()]
        if not vals:
            continue

        has_pid = any(v == _normalize_header_token("产品ID") for v in vals)
        match_count = sum(1 for v in vals if v in expected_norm)

        # 判定条件：必须有产品ID，且命中至少6个目标表头，避免误判说明行
        if has_pid and match_count >= 6:
            return idx

    return None


def _read_daily_excel_with_auto_header(path: str, fallback_skiprows: int = 5) -> pd.DataFrame:
    """按日数据格式读取：优先自动识别表头，失败回退到配置skiprows。"""
    header_row = _detect_excel_header_row(path)
    if header_row is not None:
        return pd.read_excel(path, header=header_row, dtype={"产品ID": str})
    return pd.read_excel(path, skiprows=fallback_skiprows, dtype={"产品ID": str})


def _read_main_data_excel(path: str, daily_skiprows: int = 5, is_daily: bool = False) -> pd.DataFrame:
    """主数据目录统一读取：优先常规读取；若未识别到产品ID则自动表头兜底。"""
    if is_daily:
        # 日文件优先沿用历史行为，再兜底自动表头
        try:
            df = pd.read_excel(path, skiprows=daily_skiprows, dtype={"产品ID": str})
            df.columns = df.columns.astype(str).str.strip()
            if "产品ID" in df.columns:
                return df
        except Exception:
            pass
    else:
        # 周文件/历史文件先走默认读取
        try:
            df = pd.read_excel(path, dtype={"产品ID": str})
            df.columns = df.columns.astype(str).str.strip()
            if "产品ID" in df.columns:
                return df
        except Exception:
            pass

    # 兜底：自动识别真实表头行（仅用于主数据目录）
    header_row = _detect_excel_header_row(path)
    if header_row is not None:
        return pd.read_excel(path, header=header_row, dtype={"产品ID": str})

    # 最后兜底回到默认读取，保持与历史兼容
    return pd.read_excel(path, dtype={"产品ID": str})


def _get_val(df, pid, col):
    try:
        val = df.loc[pid, col]
        return float(val) if pd.notna(val) else 0.0
    except Exception:
        return 0.0


def _get_p4p_business_val(p4p_data_sheets, pid, week):
    try:
        val = p4p_data_sheets["全站商机量"].get(pid, {}).get(week, 0.0)
        return float(val) if pd.notna(val) else 0.0
    except Exception:
        return 0.0


def _get_trend_score(series, p_value_threshold, min_weeks=2):
    vals = [x for x in series if not pd.isna(x) and x is not None]
    if len(vals) < min_weeks:
        return False
    try:
        x = np.arange(len(vals))
        slope, _, _, p_value, _ = linregress(x, vals)
        return slope > 0 and p_value < p_value_threshold
    except Exception:
        return False


def _calculate_weight_score(latest, weekly, p_value_threshold, weight_config=None, normalize_base=None):
    # 默认对齐 m_日数据分析.py；可由系统配置覆盖
    WEIGHT_CONFIG = weight_config or {
        "自然曝光": 0.30,
        "搜索曝光": 0.25,
        "综合询盘": 0.20,
        "收藏人数": 0.15,
        "访问人数": 0.10,
    }
    NORMALIZE_BASE = normalize_base or {
        "自然曝光": 1000,
        "搜索曝光": 500,
        "综合询盘": 10,
        "收藏人数": 20,
        "访问人数": 100,
    }

    metrics = {
        "自然曝光次数": [w["自然曝光次数"] for w in weekly],
        "搜索曝光次数": [w["搜索曝光次数"] for w in weekly],
        "综合询盘": [w["综合询盘"] for w in weekly],
        "收藏人数": [w["收藏人数"] for w in weekly],
        "访问人数": [w["访问人数"] for w in weekly],
    }

    avg_metrics = {}
    for key, values in metrics.items():
        valid_vals = [v for v in values if pd.notna(v) and v >= 0]
        avg_metrics[key] = np.mean(valid_vals) if valid_vals else 0.0

    base_score = (
        WEIGHT_CONFIG["自然曝光"] * min(avg_metrics["自然曝光次数"] / NORMALIZE_BASE["自然曝光"], 1) +
        WEIGHT_CONFIG["搜索曝光"] * min(avg_metrics["搜索曝光次数"] / NORMALIZE_BASE["搜索曝光"], 1) +
        WEIGHT_CONFIG["综合询盘"] * min(avg_metrics["综合询盘"] / NORMALIZE_BASE["综合询盘"], 1) +
        WEIGHT_CONFIG["收藏人数"] * min(avg_metrics["收藏人数"] / NORMALIZE_BASE["收藏人数"], 1) +
        WEIGHT_CONFIG["访问人数"] * min(avg_metrics["访问人数"] / NORMALIZE_BASE["访问人数"], 1)
    ) * 100

    trend_bonus = 0
    recent_weeks = weekly[-30:] if len(weekly) >= 30 else weekly
    if _get_trend_score([w["自然曝光次数"] for w in recent_weeks], p_value_threshold):
        trend_bonus += 5
    if _get_trend_score([w["搜索曝光次数"] for w in recent_weeks], p_value_threshold):
        trend_bonus += 5
    if _get_trend_score([w["综合询盘"] for w in recent_weeks], p_value_threshold):
        trend_bonus += 5
    if _get_trend_score([w["访问人数"] for w in recent_weeks], p_value_threshold):
        trend_bonus += 5
    if _get_trend_score([w["收藏人数"] for w in recent_weeks], p_value_threshold):
        trend_bonus += 5

    total_score = min(base_score + trend_bonus, 100)
    return total_score / 100


def _classify_exposure(latest):
    # 完全对齐 m_日数据分析.py 的阈值
    shop_exp = latest["全店曝光次数"]
    search_exp = latest["搜索曝光次数"]
    if shop_exp >= 500 or (pd.isna(shop_exp) and search_exp >= 100):
        return "有大曝光"
    elif (100 <= shop_exp < 500) or (pd.isna(shop_exp) and 50 <= search_exp < 100):
        return "有曝光"
    elif (20 <= shop_exp < 100) or (pd.isna(shop_exp) and 10 <= search_exp < 50):
        return "低曝光"
    return "未启动"


def _is_focus_new_product(weekly, consecutive_weeks=3, focus_exposure=100):
    for w in weekly:
        if w["综合询盘"] > 0:
            return True
    if len(weekly) >= consecutive_weeks:
        for i in range(len(weekly) - consecutive_weeks + 1):
            seq = weekly[i:i + consecutive_weeks]
            if all(r["全店曝光次数"] >= focus_exposure for r in seq) or all(r["搜索曝光次数"] >= focus_exposure for r in seq):
                return True
    return False


def _is_watchlist_new_product(weekly, total_weeks, consecutive_weeks=3, watch_exposure=50):
    if total_weeks >= 2:
        last = weekly[-1]
        prev_all_zero = all(r["全店曝光次数"] == 0 and r["搜索曝光次数"] == 0 for r in weekly[:-1])
        if prev_all_zero and (last["全店曝光次数"] > 0 or last["搜索曝光次数"] > 0):
            return True
    if len(weekly) >= consecutive_weeks:
        for i in range(len(weekly) - consecutive_weeks + 1):
            seq = weekly[i:i + consecutive_weeks]
            if all(r["全店曝光次数"] >= watch_exposure for r in seq) or all(r["搜索曝光次数"] >= watch_exposure for r in seq):
                return True
    return False


def _calculate_incremental_lift(pid, weekly_data, product_status_history, base_names_sorted):
    core_metric = "搜索曝光次数"
    groups = {"双关": [], "仅橱窗": [], "仅P4P": [], "双开": []}

    data_by_week = {r["week"]: r for r in weekly_data}
    history = product_status_history.get(pid, {})

    for week in base_names_sorted:
        if week not in history or week not in data_by_week:
            continue
        chuang = history[week]["是否橱窗"]
        p4p = history[week]["是否P4P"]
        exp = data_by_week[week][core_metric]

        if pd.isna(exp) or exp == 0:
            continue

        if chuang is True and p4p is True:
            groups["双开"].append(exp)
        elif chuang is True and p4p is False:
            groups["仅橱窗"].append(exp)
        elif chuang is False and p4p is True:
            groups["仅P4P"].append(exp)
        else:
            groups["双关"].append(exp)

    means = {k: np.mean(v) if v else 0 for k, v in groups.items()}
    counts = {k: len(v) for k, v in groups.items()}
    results = {}

    if counts["仅橱窗"] >= 3 and counts["双关"] >= 3:
        _, p_val = ttest_ind(groups["仅橱窗"], groups["双关"], equal_var=False)
        lift = (means["仅橱窗"] - means["双关"]) / means["双关"] if means["双关"] > 0 else 0
        results["橱窗效果"] = f"{('↑' if lift > 0 else '↓')}{abs(lift):.0%} (p={p_val:.2f})" if (p_val < 0.1 and abs(lift) > 0.1) else "不显著"

    if counts["仅P4P"] >= 3 and counts["双关"] >= 3:
        _, p_val = ttest_ind(groups["仅P4P"], groups["双关"], equal_var=False)
        lift = (means["仅P4P"] - means["双关"]) / means["双关"] if means["双关"] > 0 else 0
        results["P4P效果"] = f"{('↑' if lift > 0 else '↓')}{abs(lift):.0%} (p={p_val:.2f})" if (p_val < 0.1 and abs(lift) > 0.1) else "不显著"

    if counts["双开"] >= 3:
        expected = means["双关"] + (means["仅橱窗"] - means["双关"]) + (means["仅P4P"] - means["双关"])
        synergy = (means["双开"] - expected) / expected if expected > 0 else 0
        results["协同效应"] = "存在" if synergy > 0.1 else "无"

    return results


def _detect_status_change(pid, base_names_sorted, product_status_history):
    history = product_status_history.get(pid, {})
    changelog = []
    weeks = [w for w in base_names_sorted if w in history]
    if len(weeks) < 2:
        return ""
    prev_chuang = history[weeks[0]]["是否橱窗"]
    prev_p4p = history[weeks[0]]["是否P4P"]
    for week in weeks[1:]:
        curr = history[week]
        curr_chuang = curr["是否橱窗"]
        curr_p4p = curr["是否P4P"]
        if prev_chuang is not None and curr_chuang is not None and prev_chuang != curr_chuang:
            changelog.append(f"{week} {'加入橱窗' if curr_chuang else '退出橱窗'}")
        if prev_p4p is not None and curr_p4p is not None and prev_p4p != curr_p4p:
            changelog.append(f"{week} {'开启P4P' if curr_p4p else '暂停P4P'}")
        prev_chuang = curr_chuang
        prev_p4p = curr_p4p
    return "；".join(changelog)


def _run_single_analysis(task: TaskInfo, cfg):
    dacfg = cfg.data_analysis
    input_dir = (dacfg.single_analysis_input_file or "").strip()
    output_dir = (dacfg.single_analysis_output_file or "").strip()

    if not input_dir or not os.path.isdir(input_dir):
        raise FileNotFoundError(f"单品分析输入目录不存在: {input_dir}")
    if not output_dir:
        raise FileNotFoundError("单品分析输出目录未配置")
    os.makedirs(output_dir, exist_ok=True)

    task.current_step = "扫描单品分析输入目录"
    files = [f for f in os.listdir(input_dir) if f.lower().endswith((".xlsx", ".xls"))]
    if not files:
        raise FileNotFoundError(f"输入目录下未找到Excel文件: {input_dir}")

    # 单品分析严格按日数据命名读取（与 m_日数据分析.py 对齐）
    valid_files = [f for f in files if is_daily_filename(f)]
    if not valid_files:
        raise FileNotFoundError("输入目录中没有符合命名规则(Products-YYYY-MM-DD.xls/xlsx)的文件")

    tmp_source_dir = os.path.join(output_dir, "_single_analysis_source")
    os.makedirs(tmp_source_dir, exist_ok=True)

    task.current_step = "准备单品分析源文件"
    for f in os.listdir(tmp_source_dir):
        fp = os.path.join(tmp_source_dir, f)
        if os.path.isfile(fp):
            try:
                os.remove(fp)
            except Exception:
                pass

    for f in valid_files:
        src = os.path.join(input_dir, f)
        dst = os.path.join(tmp_source_dir, f)
        try:
            with open(src, "rb") as rf, open(dst, "wb") as wf:
                wf.write(rf.read())
        except Exception as e:
            logger.warning(f"复制单品分析文件失败 {f}: {e}")

    single_cfg = get_config()
    # 单品分析仅输出老脚本等价的两个文件：日数据统计 + 日数据诊断
    task.current_step = "执行单品分析（统计汇总）"

    OUTPUT_FILE = os.path.join(output_dir, "日数据统计.xlsx")
    DIAGNOSIS_OUTPUT = os.path.join(output_dir, "日数据产品诊断与优化建议.xlsx")

    # 1) 扫描并按日期排序
    sorted_pairs = []
    for f in valid_files:
        key = extract_date_from_daily_filename(f)
        if key:
            sorted_pairs.append((key, f))
    sorted_pairs = sorted(sorted_pairs)
    base_names_sorted = [x[0] for x in sorted_pairs]
    valid_files_sorted = [x[1] for x in sorted_pairs]

    # 2) 聚合主数据（对齐老脚本 skiprows=5）
    TARGET_COLUMNS = cfg.data_analysis.target_columns
    # 单品分析统计sheet补充：提交订单个数
    if "提交订单个数" not in TARGET_COLUMNS:
        TARGET_COLUMNS = TARGET_COLUMNS + ["提交订单个数"]

    all_product_ids = []
    product_id_set = set()
    data_sheets = {col: {} for col in TARGET_COLUMNS}
    product_status_history = {}

    for file_ext, base_name in zip(valid_files_sorted, base_names_sorted):
        file_path = os.path.join(tmp_source_dir, file_ext)
        try:
            df = _read_daily_excel_with_auto_header(file_path, fallback_skiprows=5)
            df.columns = df.columns.astype(str).str.strip()
        except Exception:
            continue

        if "产品ID" not in df.columns:
            continue

        df = df.drop_duplicates(subset=["产品ID"], keep="first")
        for pid in df["产品ID"]:
            if pd.notna(pid):
                pid_clean = str(pid).strip()
                if pid_clean not in product_id_set:
                    all_product_ids.append(pid_clean)
                    product_id_set.add(pid_clean)

        for col in TARGET_COLUMNS:
            if col in df.columns:
                series = df.set_index("产品ID")[col]
                for pid, value in series.items():
                    if pd.notna(pid):
                        pid_clean = str(pid).strip()
                        data_sheets[col].setdefault(pid_clean, {})[base_name] = value

        for _, row in df.iterrows():
            pid = row.get("产品ID")
            if pd.notna(pid):
                pid_clean = str(pid).strip()
                product_status_history.setdefault(pid_clean, {})[base_name] = {
                    "是否橱窗": normalize_status(row.get("是否橱窗")),
                    "是否P4P": normalize_status(row.get("是否P4P")),
                }

    # 3) 输出统计文件（日数据统计.xlsx）
    with pd.ExcelWriter(OUTPUT_FILE, engine="openpyxl") as writer:
        for col in TARGET_COLUMNS:
            rows = []
            for pid in all_product_ids:
                row = [pid] + [data_sheets[col].get(pid, {}).get(bn, None) for bn in base_names_sorted]
                rows.append(row)
            df_out = pd.DataFrame(rows, columns=["产品ID"] + base_names_sorted)
            df_out.to_excel(writer, sheet_name=col, index=False)

    # 4) 基于“日数据统计.xlsx”生成单品近90天统计汇总
    def _latest_n_cols(cols, n):
        return cols[-n:] if len(cols) >= n else cols

    def _to_num(v):
        try:
            if pd.isna(v):
                return 0.0
            return float(str(v).replace(",", "").strip())
        except Exception:
            return 0.0

    order_cols_90 = _latest_n_cols(base_names_sorted, 90)
    visit_cols_30 = _latest_n_cols(base_names_sorted, 30)

    summary_rows = []
    for pid in all_product_ids:
        order_90 = sum(_to_num(data_sheets.get("提交订单个数", {}).get(pid, {}).get(c, 0)) for c in order_cols_90)
        tm_90 = sum(_to_num(data_sheets.get("TM咨询人数", {}).get(pid, {}).get(c, 0)) for c in order_cols_90)
        inquiry_90 = sum(_to_num(data_sheets.get("询盘人数", {}).get(pid, {}).get(c, 0)) for c in order_cols_90)
        visit_30 = sum(_to_num(data_sheets.get("访问人数", {}).get(pid, {}).get(c, 0)) for c in visit_cols_30)

        summary_rows.append({
            "产品ID": pid,
            "90天提交订单数": int(round(order_90)),
            "90天TM+询盘人数": int(round(tm_90 + inquiry_90)),
            "30天访客数": int(round(visit_30)),
        })

    summary_default_path = os.path.join(output_dir, "单品近90天统计.xlsx")
    summary_output = (cfg.data_analysis.single_analysis_summary_file or summary_default_path).strip()
    if not summary_output:
        summary_output = summary_default_path
    summary_parent = os.path.dirname(summary_output) or output_dir
    os.makedirs(summary_parent, exist_ok=True)
    pd.DataFrame(summary_rows).to_excel(summary_output, index=False)

    # 5) 复用当前诊断逻辑生成诊断文件（日数据产品诊断与优化建议.xlsx）
    single_cfg = deepcopy(cfg)
    single_cfg.data_analysis.source_dir = tmp_source_dir
    single_cfg.data_analysis.p4p_source_dir = os.path.join(tmp_source_dir, "P4P数据")
    single_cfg.data_analysis.output_file = OUTPUT_FILE
    single_cfg.data_analysis.p4p_output_file = os.path.join(output_dir, "_unused_p4p.xlsx")
    single_cfg.data_analysis.new_output_file = os.path.join(output_dir, "_unused_new_links.xlsx")
    single_cfg.data_analysis.diagnosis_output_file = DIAGNOSIS_OUTPUT
    single_cfg.data_analysis.volatility_file_path = os.path.join(output_dir, "_unused_volatility.xlsx")

    task.current_step = "执行单品分析（诊断输出）"
    _run_comprehensive_analysis(task, single_cfg)

    # 5) 清理非老脚本产物，仅保留两个目标文件
    for fp in [
        single_cfg.data_analysis.p4p_output_file,
        single_cfg.data_analysis.new_output_file,
        single_cfg.data_analysis.volatility_file_path,
    ]:
        try:
            if fp and os.path.exists(fp):
                os.remove(fp)
        except Exception:
            pass

    try:
        if os.path.isdir(tmp_source_dir):
            for f in os.listdir(tmp_source_dir):
                fp = os.path.join(tmp_source_dir, f)
                if os.path.isfile(fp):
                    try:
                        os.remove(fp)
                    except Exception:
                        pass
            os.rmdir(tmp_source_dir)
    except Exception:
        pass


def _run_comprehensive_analysis(task: TaskInfo, cfg):
    dacfg = cfg.data_analysis

    SOURCE_DIR = (dacfg.source_dir or cfg.paths.download_save_dir).strip()
    P4P_SOURCE_DIR = (dacfg.p4p_source_dir or os.path.join(SOURCE_DIR, "P4P数据")).strip()
    P4P_OUTPUT_FILE = (dacfg.p4p_output_file or os.path.join(SOURCE_DIR, "P4P数据统计.xlsx")).strip()
    OUTPUT_FILE = (dacfg.output_file or os.path.join(SOURCE_DIR, "统计csss.xlsx")).strip()
    NEW_LINKS_FILE = (dacfg.new_links_file_path or os.path.join(SOURCE_DIR, "新发链接监控.xlsx")).strip()
    NEW_OUTPUT_FILE = (dacfg.new_output_file or os.path.join(SOURCE_DIR, "新发链接数据监控.xlsx")).strip()
    DIAGNOSIS_OUTPUT = (dacfg.diagnosis_output_file or os.path.join(SOURCE_DIR, "产品诊断与优化建议.xlsx")).strip()
    VOLATILITY_OUTPUT = (dacfg.volatility_file_path or os.path.join(SOURCE_DIR, "流量波动.xlsx")).strip()
    NEW_LINKS_SHEET_NAME = (dacfg.new_links_sheet_name or "新链接").strip()
    NEW_LINKS_COLUMN_NAME = (dacfg.new_links_column_name or "新发链接").strip()

    TARGET_COLUMNS = cfg.data_analysis.target_columns
    P_VALUE_THRESHOLD = cfg.data_analysis.p_value_threshold
    MIN_DATA_POINTS = cfg.data_analysis.min_data_points
    DAILY_SKIPROWS = int(getattr(cfg.data_analysis, "daily_read_skiprows", 5) or 5)

    da_cfg = cfg.data_analysis
    WEIGHT_CONFIG = {
        "自然曝光": float((da_cfg.weight_config or {}).get("自然曝光", 0.30)),
        "搜索曝光": float((da_cfg.weight_config or {}).get("搜索曝光", 0.25)),
        "综合询盘": float((da_cfg.weight_config or {}).get("综合询盘", 0.20)),
        "收藏人数": float((da_cfg.weight_config or {}).get("收藏人数", 0.15)),
        "访问人数": float((da_cfg.weight_config or {}).get("访问人数", 0.10)),
    }
    NORMALIZE_BASE = {
        "自然曝光": float((da_cfg.normalize_base or {}).get("自然曝光", 1000)),
        "搜索曝光": float((da_cfg.normalize_base or {}).get("搜索曝光", 500)),
        "综合询盘": float((da_cfg.normalize_base or {}).get("综合询盘", 10)),
        "收藏人数": float((da_cfg.normalize_base or {}).get("收藏人数", 20)),
        "访问人数": float((da_cfg.normalize_base or {}).get("访问人数", 100)),
    }

    if not os.path.exists(SOURCE_DIR):
        raise FileNotFoundError(f"SOURCE_DIR 路径不存在: {SOURCE_DIR}")

    task.current_step = "整合主数据"
    all_files_main = [f for f in os.listdir(SOURCE_DIR) if f.lower().endswith(('.xls', '.xlsx'))]
    valid_files_main = [f for f in all_files_main if is_valid_filename(f)]
    if not valid_files_main:
        raise Exception("未找到主数据文件")

    def _to_sort_key(fname: str):
        if is_daily_filename(fname):
            extracted = extract_date_from_daily_filename(fname)
            return extracted or os.path.splitext(fname)[0]
        return os.path.splitext(fname)[0]

    base_names = [_to_sort_key(f) for f in valid_files_main]
    sorted_pairs = sorted(zip(base_names, valid_files_main))
    base_names_sorted = [x[0] for x in sorted_pairs]
    valid_files_sorted = [x[1] for x in sorted_pairs]

    all_product_ids = []
    product_id_set = set()
    data_sheets = {col: {} for col in TARGET_COLUMNS}
    product_status_history = {}

    for file_ext, base_name in zip(valid_files_sorted, base_names_sorted):
        if task.should_stop():
            return
        task.wait_if_paused()

        file_path = os.path.join(SOURCE_DIR, file_ext)
        try:
            df = _read_main_data_excel(
                file_path,
                daily_skiprows=DAILY_SKIPROWS,
                is_daily=is_daily_filename(file_ext),
            )
            df.columns = df.columns.astype(str).str.strip()
        except Exception:
            continue
        if "产品ID" not in df.columns:
            # 仅对主数据目录尝试自动表头识别回退
            if file_path.startswith(SOURCE_DIR) and is_daily_filename(file_ext):
                try:
                    df = _read_daily_excel_with_auto_header(file_path, fallback_skiprows=0)
                    df.columns = df.columns.astype(str).str.strip()
                except Exception:
                    continue
            if "产品ID" not in df.columns:
                continue

        df = df.drop_duplicates(subset=["产品ID"], keep="first")
        for pid in df["产品ID"]:
            if pd.notna(pid):
                pid_clean = str(pid).strip()
                if pid_clean not in product_id_set:
                    all_product_ids.append(pid_clean)
                    product_id_set.add(pid_clean)

        for col in TARGET_COLUMNS:
            if col in df.columns:
                series = df.set_index("产品ID")[col]
                for pid, value in series.items():
                    if pd.notna(pid):
                        pid_clean = str(pid).strip()
                        data_sheets[col].setdefault(pid_clean, {})[base_name] = value

        for _, row in df.iterrows():
            pid = row.get("产品ID")
            if pd.notna(pid):
                pid_clean = str(pid).strip()
                product_status_history.setdefault(pid_clean, {})[base_name] = {
                    "是否橱窗": normalize_status(row.get("是否橱窗")),
                    "是否P4P": normalize_status(row.get("是否P4P")),
                }

    task.current_step = "整合P4P数据"
    P4P_TARGET_COLUMNS = ["全站商机量", "曝光量", "点击量", "全站商机-询盘量", "全站商机-TM咨询量", "计划ID"]
    p4p_data_sheets = {col: {} for col in P4P_TARGET_COLUMNS}
    p4p_product_ids = set()
    p4p_base_names_sorted = []
    p4p_valid_files_sorted = []

    if os.path.exists(P4P_SOURCE_DIR):
        all_files_p4p = [f for f in os.listdir(P4P_SOURCE_DIR) if f.lower().endswith(('.xls', '.xlsx'))]
        valid_files_p4p = [f for f in all_files_p4p if is_valid_filename(f)]
        if valid_files_p4p:
            p4p_base_names = [os.path.splitext(f)[0] for f in valid_files_p4p]
            sorted_pairs_p4p = sorted(zip(p4p_base_names, valid_files_p4p))
            p4p_base_names_sorted = [x[0] for x in sorted_pairs_p4p]
            p4p_valid_files_sorted = [x[1] for x in sorted_pairs_p4p]

    time_columns = p4p_base_names_sorted if p4p_base_names_sorted else base_names_sorted

    for file_ext, base_name in zip(p4p_valid_files_sorted, p4p_base_names_sorted):
        file_path = os.path.join(P4P_SOURCE_DIR, file_ext)
        try:
            df = pd.read_excel(file_path, dtype={"产品ID": str})
            df.columns = df.columns.astype(str).str.strip()
        except Exception:
            continue

        if "产品ID" not in df.columns:
            continue
        df_cols_str = [str(col).strip() for col in df.columns]
        is_p4p_file = any("商品信息" in col or "计划ID" in col or "计划名称" in col for col in df_cols_str)
        if not is_p4p_file:
            continue

        df = df.drop_duplicates(subset=["产品ID"], keep="first")
        for pid in df["产品ID"]:
            if pd.notna(pid):
                p4p_product_ids.add(str(pid).strip())

        for col in P4P_TARGET_COLUMNS:
            if col in df.columns:
                series = df.set_index("产品ID")[col]
                for pid, value in series.items():
                    if pd.notna(pid):
                        pid_clean = str(pid).strip()
                        p4p_data_sheets[col].setdefault(pid_clean, {})[base_name] = value

    all_product_ids = sorted(set(all_product_ids) | p4p_product_ids)

    task.current_step = "输出统计文件"
    with pd.ExcelWriter(OUTPUT_FILE, engine='openpyxl') as writer:
        for col in TARGET_COLUMNS:
            rows = []
            for pid in all_product_ids:
                rows.append([pid] + [data_sheets[col].get(pid, {}).get(bn, None) for bn in base_names_sorted])
            pd.DataFrame(rows, columns=["产品ID"] + base_names_sorted).to_excel(writer, sheet_name=col, index=False)

    with pd.ExcelWriter(P4P_OUTPUT_FILE, engine='openpyxl') as writer:
        for col in P4P_TARGET_COLUMNS:
            rows = []
            for pid in all_product_ids:
                rows.append([pid] + [p4p_data_sheets[col].get(pid, {}).get(bn, None) for bn in time_columns])
            pd.DataFrame(rows, columns=["产品ID"] + time_columns).to_excel(writer, sheet_name=col, index=False)

    task.current_step = "趋势/异动分析"
    updated_dfs = {}
    VOLATILITY_SHEETS = ["全店曝光次数", "全站推广曝光次数", "搜索曝光次数", "全店点击次数", "全站推广点击次数", "搜索点击次数", "访问人数"]
    for col in VOLATILITY_SHEETS:
        rows = []
        for pid in all_product_ids:
            rows.append([pid] + [data_sheets[col].get(pid, {}).get(bn, None) for bn in base_names_sorted])
        updated_dfs[col] = calculate_volatility_metrics(pd.DataFrame(rows, columns=["产品ID"] + base_names_sorted), base_names_sorted)

    original_dfs = {}
    for col in TARGET_COLUMNS:
        rows = []
        for pid in all_product_ids:
            rows.append([pid] + [data_sheets[col].get(pid, {}).get(bn, None) for bn in base_names_sorted])
        original_dfs[col] = pd.DataFrame(rows, columns=["产品ID"] + base_names_sorted).set_index("产品ID")

    derived_metrics = {
        "自然曝光": ("全店曝光次数", "全站推广曝光次数"),
        "自然点击": ("全店点击次数", "全站推广点击次数"),
        "场景曝光": ("全店曝光次数", "搜索曝光次数"),
        "场景点击": ("全店点击次数", "搜索点击次数")
    }

    with pd.ExcelWriter(OUTPUT_FILE, engine='openpyxl') as writer:
        for col in TARGET_COLUMNS:
            if col in updated_dfs:
                updated_dfs[col].to_excel(writer, sheet_name=col, index=False)
            else:
                original_dfs[col].reset_index().to_excel(writer, sheet_name=col, index=False)

        for metric, (minuend, subtrahend) in derived_metrics.items():
            df_min = original_dfs[minuend]
            df_sub = original_dfs[subtrahend]
            df_result = df_min.copy()
            for week in base_names_sorted:
                a = df_min[week]
                b = df_sub[week].fillna(0)
                df_result[week] = np.where(pd.isna(a), np.nan, a - b) if metric.startswith("场景") else a.fillna(0) - b
            calculate_volatility_metrics(df_result.reset_index(), base_names_sorted).to_excel(writer, sheet_name=metric, index=False)

    task.current_step = "流量波动"
    all_data_for_volatility = {}
    df_exposure = pd.read_excel(OUTPUT_FILE, sheet_name="全店曝光次数", dtype={"产品ID": str})
    for col in TARGET_COLUMNS:
        df = pd.read_excel(OUTPUT_FILE, sheet_name=col, dtype={"产品ID": str})
        df["产品ID"] = df["产品ID"].astype(str).str.strip()
        all_data_for_volatility[col] = df.set_index("产品ID")
    volatile_products = analyze_traffic_volatility(df_exposure, base_names_sorted, all_data_for_volatility)
    save_volatility_data(volatile_products, all_data_for_volatility, base_names_sorted, VOLATILITY_OUTPUT, TARGET_COLUMNS)

    task.current_step = "新发链接监控"
    if os.path.exists(NEW_LINKS_FILE):
        try:
            df_new_links = pd.read_excel(NEW_LINKS_FILE, sheet_name=NEW_LINKS_SHEET_NAME, dtype={NEW_LINKS_COLUMN_NAME: str})
            if NEW_LINKS_COLUMN_NAME in df_new_links.columns:
                new_product_ids = df_new_links[NEW_LINKS_COLUMN_NAME].dropna().astype(str).str.strip().replace('', pd.NA).dropna().unique().tolist()
                with pd.ExcelWriter(NEW_OUTPUT_FILE, engine='openpyxl') as writer:
                    for col in TARGET_COLUMNS:
                        df_stat = pd.read_excel(OUTPUT_FILE, sheet_name=col, dtype={"产品ID": str})
                        df_stat["产品ID"] = df_stat["产品ID"].astype(str).str.strip()
                        df_filtered = df_stat[df_stat["产品ID"].isin(new_product_ids)]
                        df_filtered = df_filtered.set_index("产品ID").reindex(new_product_ids).reset_index()
                        if col == "全店曝光次数":
                            chuang_status = [product_status_history.get(pid, {}).get(base_names_sorted[-1], {}).get("是否橱窗") for pid in new_product_ids]
                            p4p_status = [product_status_history.get(pid, {}).get(base_names_sorted[-1], {}).get("是否P4P") for pid in new_product_ids]
                            df_filtered["最近橱窗状态"] = chuang_status
                            df_filtered["最近P4P状态"] = p4p_status
                        df_filtered.to_excel(writer, sheet_name=col, index=False)
        except Exception as e:
            logger.warning(f"处理新发链接时出错: {e}")

    task.current_step = "诊断报告"
    all_data = {}
    for col in TARGET_COLUMNS:
        df = pd.read_excel(OUTPUT_FILE, sheet_name=col, dtype={"产品ID": str})
        df["产品ID"] = df["产品ID"].astype(str).str.strip()
        all_data[col] = df.set_index("产品ID")

    new_product_set = set()
    if os.path.exists(NEW_LINKS_FILE):
        try:
            df_new = pd.read_excel(NEW_LINKS_FILE, sheet_name=NEW_LINKS_SHEET_NAME, dtype={NEW_LINKS_COLUMN_NAME: str})
            if NEW_LINKS_COLUMN_NAME in df_new.columns:
                new_product_set = set(df_new[NEW_LINKS_COLUMN_NAME].dropna().astype(str).str.strip())
        except Exception:
            pass

    product_weekly = {}
    for pid in all_product_ids:
        product_weekly[pid] = []
        for week in base_names_sorted:
            record = {
                "week": week,
                "全店曝光次数": _get_val(all_data["全店曝光次数"], pid, week),
                "全站推广曝光次数": _get_val(all_data["全站推广曝光次数"], pid, week),
                "搜索曝光次数": _get_val(all_data["搜索曝光次数"], pid, week),
                "全店点击次数": _get_val(all_data["全店点击次数"], pid, week),
                "全站推广点击次数": _get_val(all_data["全站推广点击次数"], pid, week),
                "搜索点击次数": _get_val(all_data["搜索点击次数"], pid, week),
                "访问人数": _get_val(all_data["访问人数"], pid, week),
                "收藏人数": _get_val(all_data["收藏人数"], pid, week),
                "询盘人数": _get_val(all_data["询盘人数"], pid, week),
                "TM咨询人数": _get_val(all_data["TM咨询人数"], pid, week),
            }
            record["自然曝光次数"] = safe_sub(record["全店曝光次数"], record["全站推广曝光次数"])
            record["自然点击次数"] = safe_sub(record["全店点击次数"], record["全站推广点击次数"])
            record["场景曝光次数"] = safe_sub(safe_sub(record["全店曝光次数"], record["搜索曝光次数"]), record["全站推广曝光次数"])
            record["场景点击次数"] = safe_sub(safe_sub(record["全店点击次数"], record["搜索点击次数"]), record["全站推广点击次数"])
            record["综合询盘"] = safe_add(record["询盘人数"], record["TM咨询人数"])
            record["自然询盘"] = safe_sub(record["综合询盘"], _get_p4p_business_val(p4p_data_sheets, pid, week))
            record["点击率"] = (record["全店点击次数"] / record["全店曝光次数"]) if record["全店曝光次数"] > 0 else 0
            record["修正询盘率"] = (record["综合询盘"] / record["访问人数"]) if record["访问人数"] > 0 else 0
            product_weekly[pid].append(record)

    diagnosis_rows = []
    click_rate_threshold = float(getattr(da_cfg, "click_rate_threshold", 0.02) or 0.02)
    inquiry_rate_threshold = float(getattr(da_cfg, "inquiry_rate_threshold", 0.05) or 0.05)

    for pid in all_product_ids:
        weekly = product_weekly[pid]
        latest = weekly[-1]
        is_new = pid in new_product_set

        exposure_level = _classify_exposure(latest)

        # 完全对齐 m_日数据分析.py 的历史表现逻辑
        exp_threshold = int((da_cfg.exposure_thresholds or {}).get("有曝光_min", 100))

        valid_weeks = [w for w in weekly if w["全店曝光次数"] >= exp_threshold]
        if not valid_weeks:
            detail = "非新品且长期无曝光，建议下架" if not is_new else "曝光不足，需先解决流量"
            history_status = "待启动品"
            action_priority = "低"
        else:
            current_qualified = (
                latest["全店曝光次数"] >= exp_threshold and
                latest["点击率"] >= click_rate_threshold and
                latest["修正询盘率"] >= inquiry_rate_threshold
            )

            if current_qualified:
                detail = f"当前表现优秀：点击率{latest['点击率']:.1%}，询盘率{latest['修正询盘率']:.1%}"
                history_status = "优质品"
                action_priority = "高"
            elif latest["全店曝光次数"] >= exp_threshold:
                if latest["全店点击次数"] < 2 and latest["综合询盘"] == 0:
                    detail = "有曝光但无点击/询盘 → 主图吸引力不足或与产品不符"
                else:
                    detail = "有曝光有点击但无有效询盘 → 标题/属性/价格与买家预期不一致"
                history_status = "问题品"
                action_priority = "中"
            else:
                detail = "非新品且长期无曝光，建议下架" if not is_new else "新品待观察"
                history_status = "待启动品"
                action_priority = "低"

        new_group = "普通"
        if is_new:
            consecutive_weeks = int(getattr(da_cfg, "new_product_consecutive_weeks", 3) or 3)
            focus_exp = int(getattr(da_cfg, "new_product_focus_exposure", 100) or 100)
            watch_exp = int(getattr(da_cfg, "new_product_watch_exposure", 50) or 50)
            if _is_focus_new_product(weekly, consecutive_weeks=consecutive_weeks, focus_exposure=focus_exp):
                new_group = "重点关注"
            elif _is_watchlist_new_product(weekly, len(base_names_sorted), consecutive_weeks=consecutive_weeks, watch_exposure=watch_exp):
                new_group = "待观察"

        # 混合方案：所有产品都计算连续评分；分层仅用于决策与排序分组
        score = _calculate_weight_score(
            latest,
            weekly,
            P_VALUE_THRESHOLD,
            weight_config=WEIGHT_CONFIG,
            normalize_base=NORMALIZE_BASE,
        )

        lift_analysis = _calculate_incremental_lift(pid, weekly, product_status_history, base_names_sorted)
        if lift_analysis:
            if isinstance(lift_analysis, dict):
                detail += "；增量分析：" + "，".join([f"{k}:{v}" for k, v in lift_analysis.items()])
            else:
                detail += f"；增量分析：{lift_analysis}"

        status_log = _detect_status_change(pid, base_names_sorted, product_status_history)

        if history_status == "优质品" or new_group == "重点关注":
            chuang_recommend = "✅ 推荐"
            action_suggest = "推进"
        elif history_status == "问题品" or new_group == "待观察":
            chuang_recommend = "⚠️ 优化后推"
            action_suggest = "优化"
        else:
            chuang_recommend = "❌ 不推荐"
            action_suggest = "放弃"

        if new_group == "重点关注":
            action_suggest = "培养"
        elif new_group == "待观察":
            action_suggest = "观察"

        p4p_recommend = "— 日数据暂不分析P4P"

        latest_status = product_status_history.get(pid, {}).get(base_names_sorted[-1], {}) if base_names_sorted else {}
        latest_chuang = latest_status.get("是否橱窗")
        latest_p4p = latest_status.get("是否P4P")
        latest_chuang_text = "投放中" if latest_chuang is True else ("未投放" if latest_chuang is False else "未知")
        latest_p4p_text = "投放中" if latest_p4p is True else ("未投放" if latest_p4p is False else "未知")

        row = {
            "产品ID": pid,
            "是否新品": "是" if is_new else "否",
            "曝光层级": exposure_level,
            "历史最佳状态": history_status,
            "新品分组": new_group if is_new else "",
            "最近自然曝光": latest["自然曝光次数"],
            "最近搜索曝光": latest["搜索曝光次数"],
            "最近点击率": f"{latest['点击率']:.1%}" if isinstance(latest['点击率'], float) else "0%",
            "最近自然询盘": latest["自然询盘"],
            "最近综合询盘": latest["综合询盘"],
            "修正询盘率": f"{latest['修正询盘率']:.1%}" if isinstance(latest['修正询盘率'], float) else "0%",
            "权重评分": round(score * 100, 1),
            "橱窗状态": latest_chuang_text,
            "P4P状态": latest_p4p_text,
            "橱窗建议": chuang_recommend,
            "P4P建议": p4p_recommend,
            "诊断详情": detail,
            "行动优先级": action_priority,
            "建议动作": action_suggest,
            "操作变更记录": status_log,
        }
        diagnosis_rows.append(row)

    def sort_key(row):
        # 混合方案统一排序：先分层，再分层内按连续评分降序
        # 层级（高->低）：优质品 > 新品重点关注 > 新品待观察 > 问题品 > 待启动品
        layer_score = 0
        if row["历史最佳状态"] == "优质品":
            layer_score = 5
        elif row["新品分组"] == "重点关注":
            layer_score = 4
        elif row["新品分组"] == "待观察":
            layer_score = 3
        elif row["历史最佳状态"] == "问题品":
            layer_score = 2
        elif row["历史最佳状态"] == "待启动品":
            layer_score = 1

        action_priority_score = {"高": 3, "中": 2, "低": 1}.get(row.get("行动优先级", "低"), 1)
        return (-layer_score, -action_priority_score, -row["权重评分"], str(row.get("产品ID", "")))

    diagnosis_rows.sort(key=sort_key)
    pd.DataFrame(diagnosis_rows).to_excel(DIAGNOSIS_OUTPUT, index=False)


def _extract_response_text(data: Dict) -> str:
    for item in (data or {}).get("output", []):
        if item.get("type") == "message" and item.get("role") == "assistant":
            for c in item.get("content", []):
                if c.get("type") == "output_text":
                    return str(c.get("text") or "")
    return ""


def _pick_sheet_name(path: str, preferred: str, fuzzy_keywords: Optional[List[str]] = None) -> str:
    excel = pd.ExcelFile(path)
    names = [str(x).strip() for x in excel.sheet_names]
    if not names:
        raise ValueError(f"Excel文件无可用sheet: {path}")

    if preferred in names:
        return preferred

    normalized = {re.sub(r"\s+", "", n): n for n in names}
    key = re.sub(r"\s+", "", preferred)
    if key in normalized:
        return normalized[key]

    kws = fuzzy_keywords or []
    for n in names:
        n2 = re.sub(r"\s+", "", n)
        if all(k in n2 for k in kws):
            return n

    for n in names:
        if "上周" in n:
            return n

    return names[0]


def _run_traffic_ai_analysis(
    task: TaskInfo, cfg, user_id: int = 0, skip_points: bool = False, token: str = ""
):
    da = cfg.data_analysis
    dd = cfg.data_download
    so = cfg.store_overview

    api_key = resolve_runtime_secret("data_analysis", "doubao_api_key")
    model_name = (getattr(da, "doubao_model_name", "doubao-seed-2-0-pro-260215") or "doubao-seed-2-0-pro-260215").strip()
    output_file = (getattr(da, "traffic_ai_output_file", "") or "").strip()

    if not api_key:
        raise ValueError("豆包 API Key 未配置或为脱敏占位，请管理员保存完整 Key 后重试")
    if not output_file:
        raise ValueError("未配置流量分析输出文件路径")

    summary_path = (getattr(so, "summary_output_path", "") or "").strip()
    channel_path = (getattr(dd, "traffic_channel_output_file", "") or "").strip()

    if not os.path.exists(summary_path):
        raise FileNotFoundError(f"未找到全店运营数据文件: {summary_path}")
    if not os.path.exists(channel_path):
        raise FileNotFoundError(f"未找到流量渠道数据文件: {channel_path}")

    task.current_step = "读取全店运营数据(总结sheet)"
    summary_sheet = _pick_sheet_name(summary_path, "总结", fuzzy_keywords=["总结"])
    summary_df = pd.read_excel(summary_path, sheet_name=summary_sheet)
    summary_df = summary_df.replace([np.nan, np.inf, -np.inf], None)

    task.current_step = "读取流量渠道数据(按单日聚合上周数据)"
    from app.services.data_download_service import get_traffic_channel_overview

    overview = get_traffic_channel_overview(channel_path, None)
    channel_sheet = "聚合上周数据"
    week_rows = []
    if isinstance(overview, dict):
        week_rows = overview.get("week", []) or []

    channel_df = pd.DataFrame(week_rows)
    channel_df = channel_df.replace([np.nan, np.inf, -np.inf], None)

    summary_records = summary_df.to_dict(orient="records")
    channel_records = channel_df.to_dict(orient="records")

    def _safe_num(v):
        try:
            if v is None or (isinstance(v, float) and np.isnan(v)):
                return 0
            s = str(v).replace(",", "").strip()
            if not s:
                return 0
            n = float(s)
            # 保留原值风格：整数不带小数；非整数保留原始小数表现（去掉浮点尾巴）
            if abs(n - int(n)) < 1e-9:
                return int(n)
            return float(f"{n:.12g}")
        except Exception:
            return 0

    summary_stats = {
        "summary_rows": len(summary_records),
        "summary_cols": len(summary_df.columns),
        "channel_rows": len(channel_records),
        "channel_cols": len(channel_df.columns),
    }

    key_metrics = []
    summary_metric_map = {}

    def _pct_change(new_v: float, old_v: float) -> float:
        if old_v == 0:
            return 0.0
        return (new_v - old_v) / old_v

    def _level_by_change(chg: float) -> str:
        if chg > 0.20:
            return "大幅上涨"
        if chg > 0.10:
            return "明显上涨"
        if chg > 0.05:
            return "小幅上涨"
        if chg < -0.20:
            return "大幅下跌"
        if chg < -0.10:
            return "明显下跌"
        if chg < -0.05:
            return "小幅下跌"
        return "正常波动"

    for r in summary_records:
        name = str(r.get("指标") or r.get("指标名称") or r.get("名称") or "").strip()
        if not name:
            continue

        mine_latest = _safe_num(r.get("我的最新", r.get("我的数据（最新）", r.get("我的数据", r.get("最新", 0)))) )
        mine_last = _safe_num(r.get("我的上周", r.get("我的数据（上周）", r.get("上周", 0))))
        mine_diff = mine_latest - mine_last
        mine_wow = _pct_change(mine_latest, mine_last)

        ind_latest = _safe_num(r.get("行业最新", r.get("行业平均（最新）", r.get("行业平均", 0))))
        ind_last = _safe_num(r.get("行业上周", r.get("行业平均（上周）", 0)))
        ind_wow = _pct_change(ind_latest, ind_last)

        peer_latest = _safe_num(r.get("同行最新", r.get("同行优秀（最新）", r.get("同行优秀", 0))))
        peer_last = _safe_num(r.get("同行上周", r.get("同行优秀（上周）", 0)))
        peer_wow = _pct_change(peer_latest, peer_last)

        gap_vs_ind = mine_latest - ind_latest
        gap_vs_peer = mine_latest - peer_latest

        row = {
            "指标": name,
            "我的最新": mine_latest,
            "我的上周": mine_last,
            "我的差值": mine_diff,
            "我的环比": mine_wow,
            "我的涨跌等级": _level_by_change(mine_wow),
            "行业最新": ind_latest,
            "行业上周": ind_last,
            "行业环比": ind_wow,
            "同行最新": peer_latest,
            "同行上周": peer_last,
            "同行环比": peer_wow,
            "与行业差值": gap_vs_ind,
            "与同行差值": gap_vs_peer,
        }
        key_metrics.append(row)
        summary_metric_map[name] = row

    # ===== 衍生指标统一口径：我的/行业/同行使用同一计算公式 =====
    def _pick_metric_row(*names: str) -> Optional[Dict]:
        for n in names:
            r0 = summary_metric_map.get(n)
            if r0 is not None:
                return r0
        return None

    def _extract_side_vals(row_obj: Optional[Dict], side: str) -> tuple[float, float]:
        if not row_obj:
            return 0.0, 0.0
        if side == "mine":
            return float(row_obj.get("我的最新", 0.0) or 0.0), float(row_obj.get("我的上周", 0.0) or 0.0)
        if side == "industry":
            return float(row_obj.get("行业最新", 0.0) or 0.0), float(row_obj.get("行业上周", 0.0) or 0.0)
        return float(row_obj.get("同行最新", 0.0) or 0.0), float(row_obj.get("同行上周", 0.0) or 0.0)

    def _calc_ratio(num: float, den: float) -> float:
        return (float(num) / float(den)) if float(den) > 0 else 0.0

    def _upsert_derived_metric(name: str, calc_fn):
        mine_latest, mine_last = calc_fn("mine")
        ind_latest, ind_last = calc_fn("industry")
        peer_latest, peer_last = calc_fn("peer")

        mine_diff = mine_latest - mine_last
        mine_wow = _pct_change(mine_latest, mine_last)
        ind_wow = _pct_change(ind_latest, ind_last)
        peer_wow = _pct_change(peer_latest, peer_last)

        row_new = {
            "指标": name,
            "我的最新": mine_latest,
            "我的上周": mine_last,
            "我的差值": mine_diff,
            "我的环比": mine_wow,
            "我的涨跌等级": _level_by_change(mine_wow),
            "行业最新": ind_latest,
            "行业上周": ind_last,
            "行业环比": ind_wow,
            "同行最新": peer_latest,
            "同行上周": peer_last,
            "同行环比": peer_wow,
            "与行业差值": mine_latest - ind_latest,
            "与同行差值": mine_latest - peer_latest,
        }

        summary_metric_map[name] = row_new
        replaced = False
        for i, old in enumerate(key_metrics):
            if str(old.get("指标") or "").strip() == name:
                key_metrics[i] = row_new
                replaced = True
                break
        if not replaced:
            key_metrics.append(row_new)

    _upsert_derived_metric(
        "人均访问深度",
        lambda side: (
            _calc_ratio(*_extract_side_vals(_pick_metric_row("店铺访问次数"), side)),
            _calc_ratio(*_extract_side_vals(_pick_metric_row("店铺访问次数"), side)),
        ) if False else (
            _calc_ratio(_extract_side_vals(_pick_metric_row("店铺访问次数"), side)[0], _extract_side_vals(_pick_metric_row("店铺访问人数", "访问人数"), side)[0]),
            _calc_ratio(_extract_side_vals(_pick_metric_row("店铺访问次数"), side)[1], _extract_side_vals(_pick_metric_row("店铺访问人数", "访问人数"), side)[1]),
        ),
    )

    _upsert_derived_metric(
        "全店点击率",
        lambda side: (
            _calc_ratio(_extract_side_vals(_pick_metric_row("全店点击次数"), side)[0], _extract_side_vals(_pick_metric_row("全店曝光次数"), side)[0]),
            _calc_ratio(_extract_side_vals(_pick_metric_row("全店点击次数"), side)[1], _extract_side_vals(_pick_metric_row("全店曝光次数"), side)[1]),
        ),
    )

    _upsert_derived_metric(
        "询盘转化率(含TM)",
        lambda side: (
            _calc_ratio(
                _extract_side_vals(_pick_metric_row("询盘人数"), side)[0] + _extract_side_vals(_pick_metric_row("TM咨询人数"), side)[0],
                _extract_side_vals(_pick_metric_row("店铺访问人数", "访问人数"), side)[0],
            ),
            _calc_ratio(
                _extract_side_vals(_pick_metric_row("询盘人数"), side)[1] + _extract_side_vals(_pick_metric_row("TM咨询人数"), side)[1],
                _extract_side_vals(_pick_metric_row("店铺访问人数", "访问人数"), side)[1],
            ),
        ),
    )

    _upsert_derived_metric(
        "TM咨询转化率",
        lambda side: (
            _calc_ratio(_extract_side_vals(_pick_metric_row("TM咨询人数"), side)[0], _extract_side_vals(_pick_metric_row("店铺访问人数", "访问人数"), side)[0]),
            _calc_ratio(_extract_side_vals(_pick_metric_row("TM咨询人数"), side)[1], _extract_side_vals(_pick_metric_row("店铺访问人数", "访问人数"), side)[1]),
        ),
    )

    _upsert_derived_metric(
        "信保转化率",
        lambda side: (
            _calc_ratio(
                _extract_side_vals(_pick_metric_row("信保交易订单个数"), side)[0],
                _extract_side_vals(_pick_metric_row("询盘人数"), side)[0] + _extract_side_vals(_pick_metric_row("TM咨询人数"), side)[0],
            ),
            _calc_ratio(
                _extract_side_vals(_pick_metric_row("信保交易订单个数"), side)[1],
                _extract_side_vals(_pick_metric_row("询盘人数"), side)[1] + _extract_side_vals(_pick_metric_row("TM咨询人数"), side)[1],
            ),
        ),
    )

    _upsert_derived_metric(
        "搜索点击率",
        lambda side: (
            _calc_ratio(_extract_side_vals(_pick_metric_row("搜索点击次数"), side)[0], _extract_side_vals(_pick_metric_row("搜索曝光次数"), side)[0]),
            _calc_ratio(_extract_side_vals(_pick_metric_row("搜索点击次数"), side)[1], _extract_side_vals(_pick_metric_row("搜索曝光次数"), side)[1]),
        ),
    )

    _upsert_derived_metric(
        "自然流量占比",
        lambda side: (
            _calc_ratio(_extract_side_vals(_pick_metric_row("自然曝光量", "自然曝光次数"), side)[0], _extract_side_vals(_pick_metric_row("全店曝光次数"), side)[0]),
            _calc_ratio(_extract_side_vals(_pick_metric_row("自然曝光量", "自然曝光次数"), side)[1], _extract_side_vals(_pick_metric_row("全店曝光次数"), side)[1]),
        ),
    )

    _upsert_derived_metric(
        "自然点击率",
        lambda side: (
            _calc_ratio(_extract_side_vals(_pick_metric_row("自然点击量", "自然点击次数"), side)[0], _extract_side_vals(_pick_metric_row("自然曝光量", "自然曝光次数"), side)[0]),
            _calc_ratio(_extract_side_vals(_pick_metric_row("自然点击量", "自然点击次数"), side)[1], _extract_side_vals(_pick_metric_row("自然曝光量", "自然曝光次数"), side)[1]),
        ),
    )

    _upsert_derived_metric(
        "自然商机转化率",
        lambda side: (
            _calc_ratio(_extract_side_vals(_pick_metric_row("自然商机量"), side)[0], _extract_side_vals(_pick_metric_row("自然点击量", "自然点击次数"), side)[0]),
            _calc_ratio(_extract_side_vals(_pick_metric_row("自然商机量"), side)[1], _extract_side_vals(_pick_metric_row("自然点击量", "自然点击次数"), side)[1]),
        ),
    )

    _upsert_derived_metric(
        "营销点击率",
        lambda side: (
            _calc_ratio(_extract_side_vals(_pick_metric_row("营销点击次数"), side)[0], _extract_side_vals(_pick_metric_row("营销曝光次数"), side)[0]),
            _calc_ratio(_extract_side_vals(_pick_metric_row("营销点击次数"), side)[1], _extract_side_vals(_pick_metric_row("营销曝光次数"), side)[1]),
        ),
    )

    _upsert_derived_metric(
        "营销流量占比",
        lambda side: (
            _calc_ratio(_extract_side_vals(_pick_metric_row("营销曝光次数"), side)[0], _extract_side_vals(_pick_metric_row("全店曝光次数"), side)[0]),
            _calc_ratio(_extract_side_vals(_pick_metric_row("营销曝光次数"), side)[1], _extract_side_vals(_pick_metric_row("全店曝光次数"), side)[1]),
        ),
    )

    # ===== 后端固定计算：模块5数值口径 =====
    normalized_rows = []
    total_uv = 0.0
    total_leads = 0.0
    for r in channel_records:
        name = str(r.get("流量渠道", "") or "").strip()
        uv = _safe_num(r.get("店铺访问人数", 0))
        ask = _safe_num(r.get("店内询盘人数", 0))
        tm = _safe_num(r.get("店内TM咨询人数", 0))
        leads = ask + tm
        cvr = (leads / uv) if uv > 0 else 0.0
        total_uv += uv
        total_leads += leads
        normalized_rows.append({
            "流量渠道": name,
            "店铺访问人数": uv,
            "店内询盘人数": ask,
            "店内TM咨询人数": tm,
            "商机人数": leads,
            "商机转化率": cvr,
        })

    rank_rows = sorted(normalized_rows, key=lambda x: x.get("商机转化率", 0), reverse=True)
    quality_rank_map = {r.get("流量渠道", ""): i + 1 for i, r in enumerate(rank_rows)}

    channel_fixed_metrics = []
    for r in normalized_rows:
        uv = r["店铺访问人数"]
        leads = r["商机人数"]
        channel_fixed_metrics.append({
            "流量渠道": r["流量渠道"],
            "店铺访问人数": uv,
            "店内询盘人数": r["店内询盘人数"],
            "店内TM咨询人数": r["店内TM咨询人数"],
            "商机人数": leads,
            "人数占比": (uv / total_uv) if total_uv > 0 else 0.0,
            "商机转化率": r["商机转化率"],
            "质量排序": quality_rank_map.get(r["流量渠道"], 0),
            "询盘贡献度": (leads / total_leads) if total_leads > 0 else 0.0,
        })

    channel_top = sorted(channel_fixed_metrics, key=lambda x: x.get("店铺访问人数", 0), reverse=True)[:10]

    fixed_calc_meta = {
        "总访问人数": total_uv,
        "总商机人数": total_leads,
        "人数占比公式": "店铺访问人数 / 全渠道总访问人数",
        "询盘贡献度公式": "(店内询盘人数+店内TM咨询人数) / 全渠道总商机人数",
        "质量排序规则": "按商机转化率降序，1为最高",
    }

    # ===== 后端固定计算：全模块统一数值口径（供AI只做解释） =====
    def _get_metric(name: str) -> Dict:
        return summary_metric_map.get(name, {
            "指标": name,
            "我的最新": 0.0,
            "我的上周": 0.0,
            "我的差值": 0.0,
            "我的环比": 0.0,
            "我的涨跌等级": "正常波动",
            "行业最新": 0.0,
            "行业上周": 0.0,
            "行业环比": 0.0,
            "同行最新": 0.0,
            "同行上周": 0.0,
            "同行环比": 0.0,
            "与行业差值": 0.0,
            "与同行差值": 0.0,
        })

    def _latest_of(*names: str) -> float:
        for n in names:
            m = summary_metric_map.get(n)
            if m is not None:
                return float(m.get("我的最新", 0.0) or 0.0)
        return 0.0

    def _latest_of_fuzzy(keyword: str, *preferred: str) -> float:
        # 先走精确别名，再走模糊匹配，避免“店铺访问人数/店铺访客人数/访问人数”等命名差异导致读成0
        v = _latest_of(*preferred)
        if v:
            return v
        kw = str(keyword or "").strip()
        if not kw:
            return 0.0
        for k, m in summary_metric_map.items():
            if kw in str(k or ""):
                return float(m.get("我的最新", 0.0) or 0.0)
        return 0.0

    store_visits = _latest_of_fuzzy("访问", "店铺访问人数", "店铺访客人数", "访问人数")
    store_visit_times = _latest_of("店铺访问次数")
    shop_exposure = _latest_of("全店曝光次数")
    shop_clicks = _latest_of("全店点击次数")
    inquiry_people = _latest_of("询盘人数")
    tm_people = _latest_of("TM咨询人数")
    sinosure_orders = _latest_of("信保交易订单个数")
    biz_people = _latest_of("商机人数")

    search_exposure = _latest_of("搜索曝光次数")
    search_clicks = _latest_of("搜索点击次数")

    natural_exposure = _latest_of("自然曝光量", "自然曝光次数")
    natural_clicks = _latest_of("自然点击量", "自然点击次数")
    natural_biz = _latest_of("自然商机量")

    marketing_exposure = _latest_of("营销曝光次数")
    p4p_clicks = _latest_of("全站推点击次数", "全站推广点击次数")
    p4p_biz = _latest_of("全站推商机量", "全站商机量")

    combined_inquiry = inquiry_people + tm_people

    # 按用户指定公式统一计算
    avg_visit_depth = (store_visit_times / store_visits) if store_visits > 0 else 0.0
    shop_ctr = (shop_clicks / shop_exposure) if shop_exposure > 0 else 0.0
    inquiry_cvr = (combined_inquiry / store_visits) if store_visits > 0 else 0.0
    sinosure_cvr = (sinosure_orders / combined_inquiry) if combined_inquiry > 0 else 0.0
    biz_cvr = (biz_people / shop_clicks) if shop_clicks > 0 else 0.0

    search_ctr = (search_clicks / search_exposure) if search_exposure > 0 else 0.0

    natural_share = (natural_exposure / shop_exposure) if shop_exposure > 0 else 0.0
    natural_ctr = (natural_clicks / natural_exposure) if natural_exposure > 0 else 0.0
    natural_biz_cvr = (natural_biz / natural_clicks) if natural_clicks > 0 else 0.0

    marketing_share = (marketing_exposure / shop_exposure) if shop_exposure > 0 else 0.0
    p4p_biz_cvr = (p4p_biz / p4p_clicks) if p4p_clicks > 0 else 0.0

    funnel_fixed = {
        "店铺访问人数": store_visits,
        "店铺访问次数": store_visit_times,
        "人均访问深度": avg_visit_depth,
        "全店曝光次数": shop_exposure,
        "全店点击次数": shop_clicks,
        "全店点击率": shop_ctr,
        "询盘人数": inquiry_people,
        "TM咨询人数": tm_people,
        "询盘转化率(含TM)": inquiry_cvr,
        "信保交易订单个数": sinosure_orders,
        "信保转化率": sinosure_cvr,
        "商机人数": biz_people,
        "商机转化率": biz_cvr,
    }

    search_fixed = {
        "搜索曝光次数": search_exposure,
        "搜索点击次数": search_clicks,
        "搜索点击率": search_ctr,
    }
    natural_fixed = {
        "自然曝光量": natural_exposure,
        "自然点击量": natural_clicks,
        "自然商机量": natural_biz,
        "自然流量占比": natural_share,
        "自然点击率": natural_ctr,
        "自然商机转化率": natural_biz_cvr,
    }
    marketing_fixed = {
        "营销曝光次数": marketing_exposure,
        "营销流量占比": marketing_share,
        "全站推点击次数": p4p_clicks,
        "全站推商机量": p4p_biz,
        "全站推商机转化率": p4p_biz_cvr,
    }

    risk_flags = []
    if shop_ctr < 0.02:
        risk_flags.append({"级别": "一般风险", "风险": "全店点击率偏低", "当前值": shop_ctr, "阈值": 0.02})
    if inquiry_cvr < 0.03:
        risk_flags.append({"级别": "严重风险" if inquiry_cvr < 0.015 else "一般风险", "风险": "询盘转化率(含TM)偏低", "当前值": inquiry_cvr, "阈值": 0.03})
    if _get_metric("全店曝光次数").get("我的环比", 0) < -0.2:
        risk_flags.append({"级别": "严重风险", "风险": "全店曝光大幅下跌", "当前值": _get_metric("全店曝光次数").get("我的环比", 0), "阈值": -0.2})

    fixed_analysis_pack = {
        "规则": {
            "涨跌评级阈值": {"正常波动": "±5%", "小幅": "5%-10%", "明显": "10%-20%", "大幅": ">20%"},
            "风险阈值": {"全店点击率": 0.02, "询盘转化率(含TM)": 0.03},
            "计算公式": {
                "人均访问深度": "店铺访问次数/店铺访问人数",
                "全店点击率": "全店点击次数/全店曝光次数",
                "询盘转化率": "(询盘人数+TM咨询人数)/店铺访问人数",
                "信保转化率": "信保交易订单个数/(询盘人数+TM咨询人数)",
                "商机转化率": "商机人数/全店点击次数",
                "搜索点击率": "搜索点击次数/搜索曝光次数",
                "自然流量占比": "自然曝光量/全店曝光次数",
                "自然点击率": "自然点击量/自然曝光量",
                "自然商机转化率": "自然商机量/自然点击量",
                "营销流量占比": "营销曝光次数/全店曝光次数",
                "全站推商机转化率": "全站推商机量/全站推点击次数"
            },
            "不计算项": ["加购率"],
            "要求": "AI禁止重算上述数值，只能引用并解释",
        },
        "模块1_店铺整体": {
            "核心指标固定计算": key_metrics,
            "漏斗固定计算": funnel_fixed,
        },
        "模块2_搜索": search_fixed,
        "模块3_自然": natural_fixed,
        "模块4_营销": marketing_fixed,
        "模块5_渠道": {
            "计算口径": fixed_calc_meta,
            "逐渠道固定结果": channel_fixed_metrics,
            "渠道Top10": channel_top,
        },
        "模块6_行业对标": key_metrics,
        "模块7_风险预警": risk_flags,
        "模块8_执行优先级建议输入": {
            "高优先指标": [x["指标"] for x in key_metrics if x.get("我的涨跌等级") in {"大幅下跌", "明显下跌"}],
            "可放大指标": [x["指标"] for x in key_metrics if x.get("我的涨跌等级") in {"大幅上涨", "明显上涨"}],
        },
    }

    system_text = (
        "你是阿里巴巴国际站资深运营与数据分析顾问。"
        "请严格遵循用户提供的规则与输出框架，不要遗漏任何模块。"
        "所有结论都必须引用数据证据，禁止空泛表述。"
        "你必须把【全模块固定计算结果包】作为唯一数值来源。"
        "严禁你自行重算、改写、估算任何数字。"
        "严格禁止合并渠道名称（例如把'系统推荐'与'其他'合并成一行）。"
        "若数据不足以计算，必须明确写'缺失'并说明缺失字段，不得臆造。"
    )

    user_text = (
        "以下是店铺数据分析任务，请严格按预设模块输出。\n\n"
        "【硬性约束（所有模块）】\n"
        "1) 所有数值、占比、环比、排序、风险分级，必须直接引用后端固定计算结果。\n"
        "2) 禁止你自行重算、改写、估算任何数字。\n"
        "3) 若固定计算包缺少某指标，只能标注缺失，不得补算。\n"
        "4) 渠道必须逐条输出，禁止合并渠道。\n\n"
        f"【数据概况摘要】\n{json.dumps(summary_stats, ensure_ascii=False)}\n\n"
        f"【全模块固定计算结果包（唯一数值依据）】\n{json.dumps(fixed_analysis_pack, ensure_ascii=False)}\n\n"
        f"【全店运营数据（周期数据趋势-{summary_sheet}，原始全量，仅供引用）】\n"
        f"{json.dumps(summary_records, ensure_ascii=False)}\n\n"
        "【全店渠道数据（流量渠道-上周数据聚合结果，原始全量，仅供引用）】\n"
        f"{json.dumps(channel_records, ensure_ascii=False)}"
    )

    payload = {
        "model": model_name,
        "temperature": 0.2,
        "top_p": 0.9,
        "input": [
            {
                "role": "system",
                "content": [
                    {"type": "input_text", "text": system_text},
                    {"type": "input_text", "text": STORE_DIAGNOSIS_PROMPT},
                ],
            },
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": user_text},
                ],
            },
        ],
    }

    task.current_step = "调用AI生成店铺诊断"
    resp = requests.post(
        API_BASE_URL + API_ENDPOINT,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json=payload,
        timeout=300,
    )
    resp.raise_for_status()
    data = resp.json()

    text = _extract_response_text(data)
    if not text.strip():
        raise ValueError("AI未返回有效分析文本")

    # ===== 结果一致性校验器（与后端固定计算包对齐） =====
    def _fmt_pct(v: float) -> str:
        return f"{(v or 0.0) * 100:.2f}%"

    validation_issues = []

    # 1) 渠道名称是否都出现
    for row in channel_fixed_metrics:
        ch = str(row.get("流量渠道", "") or "").strip()
        if ch and ch not in text:
            validation_issues.append(f"缺少渠道名称: {ch}")

    # 2) 核心百分比是否被正确引用（模块5关键数字）
    for row in channel_fixed_metrics:
        ch = str(row.get("流量渠道", "") or "").strip()
        if not ch:
            continue
        uv_ratio = _fmt_pct(float(row.get("人数占比", 0) or 0))
        cvr = _fmt_pct(float(row.get("商机转化率", 0) or 0))

        if uv_ratio not in text:
            validation_issues.append(f"人数占比未匹配: {ch} -> {uv_ratio}")
        if cvr not in text:
            validation_issues.append(f"商机转化率未匹配: {ch} -> {cvr}")

    # 3) 全模块核心计算项校验（按你指定公式）
    global_fixed_pct = {
        "全店点击率": _fmt_pct(shop_ctr),
        "询盘转化率": _fmt_pct(inquiry_cvr),
        "信保转化率": _fmt_pct(sinosure_cvr),
        "商机转化率": _fmt_pct(biz_cvr),
        "搜索点击率": _fmt_pct(search_ctr),
        "自然流量占比": _fmt_pct(natural_share),
        "自然点击率": _fmt_pct(natural_ctr),
        "自然商机转化率": _fmt_pct(natural_biz_cvr),
        "营销流量占比": _fmt_pct(marketing_share),
        "全站推商机转化率": _fmt_pct(p4p_biz_cvr),
    }
    for k, v in global_fixed_pct.items():
        if v not in text:
            validation_issues.append(f"核心指标未匹配: {k} -> {v}")

    # 4) 禁止渠道合并的简单检测
    forbidden_merge_patterns = ["系统推荐+其他", "系统推荐 / 其他", "系统推荐与其他合并", "搜索+系统推荐"]
    for pat in forbidden_merge_patterns:
        if pat in text:
            validation_issues.append(f"检测到疑似渠道合并表述: {pat}")

    validated_text = text.strip()
    if validation_issues:
        validated_text += "\n\n---\n【结果校验告警】\n"
        validated_text += "以下项目与后端固定计算结果可能不一致，请人工复核：\n"
        for i, issue in enumerate(validation_issues, 1):
            validated_text += f"{i}. {issue}\n"
    else:
        validated_text += "\n\n---\n【结果校验】通过（已与后端固定计算结果对齐）\n"

    os.makedirs(os.path.dirname(output_file) or da.source_dir, exist_ok=True)
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(validated_text)

    if not skip_points and user_id > 0:
        from app.services.membership_service import deduct_traffic_ai_points

        deduct_traffic_ai_points(user_id, biz_id=task.task_id, token=token)


def get_traffic_ai_result() -> Dict:
    cfg = get_config()
    da = cfg.data_analysis
    output_file = (getattr(da, "traffic_ai_output_file", "") or "").strip()
    if not output_file or not os.path.exists(output_file):
        return {"output_file": output_file, "content": "", "generated_at": ""}

    with open(output_file, "r", encoding="utf-8") as f:
        content = f.read()

    generated_at = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(os.path.getmtime(output_file)))
    return {"output_file": output_file, "content": content, "generated_at": generated_at}


def get_analysis_result(task_type: str) -> Dict:
    cfg = get_config()
    dacfg = cfg.data_analysis
    result_files = {
        "comprehensive": dacfg.output_file,
        "single_analysis": dacfg.single_analysis_output_file,
        "p4p": dacfg.p4p_output_file,
        "new_links": dacfg.new_output_file,
        "diagnosis": dacfg.diagnosis_output_file,
        "volatility": dacfg.volatility_file_path,
    }
    filepath = result_files.get(task_type)
    if not filepath:
        raise ValueError(f"未知的分析类型: {task_type}")
    if not os.path.exists(filepath):
        raise FileNotFoundError(f"结果文件不存在: {filepath}")

    excel = pd.ExcelFile(filepath)
    sheet = excel.sheet_names[0]
    df = pd.read_excel(filepath, sheet_name=sheet)
    return {
        "file": filepath,
        "sheets": excel.sheet_names,
        "rows": len(df),
        "columns": list(df.columns),
        "preview": df.head(20).to_dict(orient="records"),
    }


_OVERVIEW_CACHE: Dict[str, Any] = {"ts": 0.0, "data": None}
_OVERVIEW_CACHE_TTL_SECONDS = 20


def get_overview_data() -> Dict:
    import time
    from app.services.upload_service import scan_available_products

    now = time.time()
    cached = _OVERVIEW_CACHE.get("data")
    if isinstance(cached, dict) and (now - float(_OVERVIEW_CACHE.get("ts") or 0) < _OVERVIEW_CACHE_TTL_SECONDS):
        return cached

    products = scan_available_products()
    total = len(products)
    published = sum(1 for p in products if p["is_published"])
    available = sum(1 for p in products if p["can_publish"])
    data = {
        "total_products": total,
        "published_products": published,
        "available_products": available,
        "publish_rate": f"{published / total * 100:.1f}%" if total > 0 else "0%",
    }
    _OVERVIEW_CACHE["ts"] = now
    _OVERVIEW_CACHE["data"] = data
    return data


def _fix_mojibake_text(val: str) -> str:
    text = str(val)
    if not text:
        return text
    for enc in ("gbk", "utf-8"):
        try:
            fixed = text.encode("latin1").decode(enc)
            if fixed and "�" not in fixed:
                return fixed
        except Exception:
            continue
    return text


def get_volatility_anomaly_data(file_path: Optional[str] = None) -> Dict:
    cfg = get_config()
    path = (file_path or cfg.data_analysis.volatility_file_path or "").strip()
    if not os.path.exists(path):
        raise FileNotFoundError(f"结果文件不存在: {path}")

    excel = pd.ExcelFile(path)
    normalized_map = { _fix_mojibake_text(s): s for s in excel.sheet_names }
    target_sheet = normalized_map.get("异动")
    if not target_sheet:
        # 兜底：优先找包含“异动”字样的sheet，否则取最后一个sheet
        for name in excel.sheet_names:
            if "异动" in _fix_mojibake_text(name):
                target_sheet = name
                break
    if not target_sheet:
        target_sheet = excel.sheet_names[-1] if excel.sheet_names else ""

    if not target_sheet:
        return {"rows": [], "sheet": "异动"}

    df = pd.read_excel(path, sheet_name=target_sheet)
    if df is None or df.empty:
        return {"rows": [], "sheet": "异动"}

    # 修复列名乱码
    df.columns = [_fix_mojibake_text(c) for c in df.columns]
    cols = list(df.columns)

    def _norm_col_name(v: object) -> str:
        return str(v or "").strip().replace("\u3000", " ")

    def _find_col_by_alias(candidates: List[str], aliases: List[str]) -> Optional[str]:
        alias_set = {_norm_col_name(x).lower() for x in aliases}
        for c in candidates:
            if _norm_col_name(c).lower() in alias_set:
                return c
        return None

    id_col = _find_col_by_alias(cols, ["产品ID", "产品id", "product_id", "productid"]) or cols[0]

    def g(row, cands):
        for c in cands:
            if c in cols:
                return row.get(c, 0)
        return 0

    def _to_float(v):
        try:
            if pd.isna(v):
                return 0.0
            return float(v)
        except Exception:
            try:
                s = str(v).strip().replace(",", "")
                if not s or s.lower() in {"nan", "none"}:
                    return 0.0
                return float(s)
            except Exception:
                return 0.0

    def _to_product_id(v) -> str:
        if pd.isna(v):
            return ""
        s = str(v).strip()
        if not s:
            return ""
        # 避免 Excel 把 ID 变成浮点，如 1601234567890.0
        if re.fullmatch(r"\d+\.0+", s):
            return s.split(".")[0]
        return s

    rows = []
    for _, r in df.iterrows():
        rows.append({
            "productId": _to_product_id(r.get(id_col, "")),
            "shopExposure": _to_float(g(r, ["全店曝光次数", "全店曝光"])),
            "p4pExposure": _to_float(g(r, ["全站推广曝光次数", "全站推曝光"])),
            "searchExposure": _to_float(g(r, ["搜索曝光次数", "搜索曝光"])),
            "naturalExposure": _to_float(g(r, ["自然曝光"])),
            "sceneExposure": _to_float(g(r, ["场景曝光"])),
            "shopClicks": _to_float(g(r, ["全店点击次数", "全店点击"])),
            "p4pClicks": _to_float(g(r, ["全站推广点击次数", "全站推点击"])),
            "searchClicks": _to_float(g(r, ["搜索点击次数", "搜索点击"])),
            "naturalClicks": _to_float(g(r, ["自然点击"])),
            "sceneClicks": _to_float(g(r, ["场景点击"])),
        })
    rows.sort(key=lambda x: abs(x.get("shopExposure", 0)), reverse=True)
    return {"rows": rows, "sheet": "异动"}


def get_new_links_monitor_data(file_path: Optional[str] = None, sheet_name: Optional[str] = None) -> Dict:
    cfg = get_config()
    path = (file_path or cfg.data_analysis.new_output_file or "").strip()
    if not os.path.exists(path):
        raise FileNotFoundError(f"结果文件不存在: {path}")

    excel = pd.ExcelFile(path)
    target_sheet = (sheet_name or "全店曝光次数").strip()
    if target_sheet not in excel.sheet_names:
        target_sheet = excel.sheet_names[0]

    df = pd.read_excel(path, sheet_name=target_sheet)
    if df is None or df.empty:
        return {"sheet": target_sheet, "columns": [], "rows": []}

    cols = list(df.columns)
    id_col = "产品ID" if "产品ID" in cols else cols[0]

    # 尝试从“新发链接监控.xlsx”的源表补充 发品日期/发品天数（用于前端“新品”列表展示）
    try:
        new_links_src = (cfg.data_analysis.new_links_file_path or "").strip()
        sheet_src = (cfg.data_analysis.new_links_sheet_name or "新链接").strip()
        col_id_src = (cfg.data_analysis.new_links_column_name or "新发链接").strip()
        if new_links_src and os.path.exists(new_links_src):
            df_src = pd.read_excel(new_links_src, sheet_name=sheet_src, dtype={col_id_src: str})
            if df_src is not None and not df_src.empty and col_id_src in df_src.columns:
                # 常见表头：发品日期、新发链接
                date_col = "发品日期" if "发品日期" in df_src.columns else None
                if date_col:
                    def _norm_pid(v) -> str:
                        s = str(v or "").strip()
                        return s.replace(".0", "") if s else ""

                    def _parse_yyMMdd(v) -> Optional[int]:
                        try:
                            s = str(v or "").strip()
                            if not s:
                                return None
                            # 允许 excel 把 240423 读成 240423.0
                            s = s.replace(".0", "")
                            if len(s) != 6 or not s.isdigit():
                                return None
                            yy = int(s[0:2]) + 2000
                            mm = int(s[2:4])
                            dd = int(s[4:6])
                            import datetime
                            dt = datetime.date(yy, mm, dd)
                            return int(dt.strftime("%Y%m%d"))
                        except Exception:
                            return None

                    import datetime
                    today = datetime.date.today()
                    pid_to_date = {}
                    pid_to_days = {}
                    for _, r in df_src.iterrows():
                        pid = _norm_pid(r.get(col_id_src))
                        if not pid:
                            continue
                        raw_date = r.get(date_col)
                        ymd_int = _parse_yyMMdd(raw_date)
                        if not ymd_int:
                            continue
                        # 计算天数差
                        try:
                            y = ymd_int // 10000
                            m = (ymd_int // 100) % 100
                            d = ymd_int % 100
                            dt = datetime.date(y, m, d)
                            pid_to_date[pid] = str(raw_date).replace(".0", "")
                            pid_to_days[pid] = int((today - dt).days)
                        except Exception:
                            continue

                    if pid_to_date:
                        # 将两列插入到 id_col 后面（若已存在近似列名则覆写并归一，避免重复列）
                        date_col_alias = _find_col_by_alias(list(df.columns), ["发品日期", "发品时间", "publish_date", "date"])
                        days_col_alias = _find_col_by_alias(list(df.columns), ["发品天数", "发布天数", "publish_days", "days"])

                        date_series = df[id_col].astype(str).map(lambda x: pid_to_date.get(_norm_pid(x), ""))
                        days_series = df[id_col].astype(str).map(lambda x: pid_to_days.get(_norm_pid(x), None))

                        if date_col_alias is None:
                            insert_at = int(list(df.columns).index(id_col) + 1) if id_col in df.columns else 1
                            df.insert(insert_at, "发品日期", date_series)
                        else:
                            df[date_col_alias] = date_series
                            if date_col_alias != "发品日期":
                                df = df.rename(columns={date_col_alias: "发品日期"})

                        if days_col_alias is None:
                            insert_at = int(list(df.columns).index("发品日期") + 1) if "发品日期" in df.columns else 2
                            df.insert(insert_at, "发品天数", days_series)
                        else:
                            df[days_col_alias] = days_series
                            if days_col_alias != "发品天数":
                                df = df.rename(columns={days_col_alias: "发品天数"})

                        # 兜底：若因历史脏表头导致重复列（如“发品日期 ”），仅保留第一列
                        keep_cols: List[str] = []
                        seen_date = False
                        seen_days = False
                        for c in list(df.columns):
                            n = _norm_col_name(c).lower()
                            if n in {"发品日期", "publish_date", "date"}:
                                if seen_date:
                                    continue
                                seen_date = True
                                keep_cols.append(c)
                                continue
                            if n in {"发品天数", "publish_days", "days", "发布天数"}:
                                if seen_days:
                                    continue
                                seen_days = True
                                keep_cols.append(c)
                                continue
                            keep_cols.append(c)
                        df = df.loc[:, keep_cols]

                        cols = list(df.columns)
    except Exception:
        # 读取源表失败时不影响监控表主流程
        pass

    latest_col = None
    for c in reversed(cols):
        if c in {id_col, "异动", "涨跌", "最近橱窗状态", "最近P4P状态"}:
            continue
        latest_col = c
        break

    def _to_num(v):
        try:
            if pd.isna(v):
                return 0.0
            return float(str(v).replace(",", "").strip())
        except Exception:
            return 0.0

    # JSON 序列化安全处理：NaN/Inf -> None
    df = df.replace([np.nan, np.inf, -np.inf], None)
    rows = df.to_dict(orient="records")
    if latest_col is not None:
        rows.sort(key=lambda r: abs(_to_num(r.get(latest_col, 0))), reverse=True)

    return {
        "sheet": target_sheet,
        "columns": [str(c) for c in cols],
        "latest_col": str(latest_col) if latest_col is not None else None,
        "rows": rows,
    }


def get_diagnosis_table_data(file_path: Optional[str] = None) -> Dict:
    cfg = get_config()
    path = (file_path or cfg.data_analysis.diagnosis_output_file or "").strip()

    # 兼容目录入参：自动定位目录中的标准诊断文件
    if os.path.isdir(path):
        candidate = os.path.join(path, "产品诊断与优化建议.xlsx")
        if os.path.exists(candidate):
            path = candidate

    if not os.path.exists(path):
        raise FileNotFoundError(f"结果文件不存在: {path}")

    df = pd.read_excel(path)
    if df is None or df.empty:
        return {"columns": [], "rows": []}

    df = df.replace([np.nan, np.inf, -np.inf], None)
    return {
        "columns": [str(c) for c in df.columns],
        "rows": df.to_dict(orient="records"),
    }


def _read_excel_table(path: str, sheet_name: Optional[str] = None) -> Dict:
    p = str(path or "").strip()
    if re.match(r"^[\\/]+[A-Za-z]:", p):
        p = re.sub(r"^[\\/]+", "", p)
    p = os.path.normpath(p)

    # 兼容目录入参：默认挑目录内最新 xlsx/xls
    if os.path.isdir(p):
        files = [
            os.path.join(p, x)
            for x in os.listdir(p)
            if str(x).lower().endswith((".xlsx", ".xls"))
        ]
        if not files:
            raise FileNotFoundError(f"目录下无Excel文件: {p}")
        files.sort(key=lambda fp: os.path.getmtime(fp), reverse=True)
        p = files[0]

    if not os.path.exists(p):
        raise FileNotFoundError(f"结果文件不存在: {p}")

    try:
        excel = pd.ExcelFile(p)
    except Exception as e:
        raise ValueError(f"Excel文件读取失败: {p} | {e}")

    sheets = list(excel.sheet_names or [])
    file_mtime = 0
    try:
        file_mtime = int(os.path.getmtime(p))
    except Exception:
        file_mtime = 0

    if not sheets:
        return {"sheet": "", "sheets": [], "columns": [], "rows": [], "file": p, "file_mtime": file_mtime}

    target_sheet = str(sheet_name or sheets[0]).strip()
    if target_sheet not in sheets:
        target_sheet = sheets[0]

    df = pd.read_excel(p, sheet_name=target_sheet)
    if df is None or df.empty:
        return {"sheet": target_sheet, "sheets": sheets, "columns": [], "rows": [], "file": p, "file_mtime": file_mtime}

    df = df.replace([np.nan, np.inf, -np.inf], None)
    return {
        "sheet": target_sheet,
        "sheets": sheets,
        "columns": [str(c) for c in df.columns],
        "rows": df.to_dict(orient="records"),
        "file": p,
        "file_mtime": file_mtime,
    }


def get_statistics_table_data(file_path: Optional[str] = None, sheet_name: Optional[str] = None) -> Dict:
    cfg = get_config()
    path = (file_path or cfg.data_analysis.output_file or "").strip()
    return _read_excel_table(path, sheet_name)


def get_p4p_table_data(file_path: Optional[str] = None, sheet_name: Optional[str] = None) -> Dict:
    cfg = get_config()
    path = (file_path or cfg.data_analysis.p4p_output_file or "").strip()
    if not path:
        return _read_excel_table(path, sheet_name)

    abs_path = os.path.abspath(path)
    target_sheet = (sheet_name or "").strip()
    try:
        file_mtime = os.path.getmtime(abs_path)
    except OSError:
        return _read_excel_table(path, sheet_name)

    cache_key = f"{abs_path}::{target_sheet or '__default__'}::{file_mtime}"
    with _table_cache_lock:
        cached = _table_cache.get(cache_key)
        if cached is not None:
            return deepcopy(cached)

    data = _read_excel_table(path, sheet_name)
    with _table_cache_lock:
        _table_cache.clear()
        _table_cache[cache_key] = deepcopy(data)
    return data


def get_statistics_table_data(file_path: Optional[str] = None, sheet_name: Optional[str] = None) -> Dict:
    cfg = get_config()
    path = (file_path or cfg.data_analysis.output_file or "").strip()
    if not os.path.exists(path):
        raise FileNotFoundError(f"结果文件不存在: {path}")

    excel = pd.ExcelFile(path)
    target = (sheet_name or "全店曝光次数").strip()
    if target not in excel.sheet_names:
        target = excel.sheet_names[0]

    df = pd.read_excel(path, sheet_name=target)
    if df is None or df.empty:
        return {"sheet": target, "sheets": excel.sheet_names, "columns": [], "rows": []}

    df = df.replace([np.nan, np.inf, -np.inf], None)
    return {
        "sheet": target,
        "sheets": excel.sheet_names,
        "columns": [str(c) for c in df.columns],
        "rows": df.to_dict(orient="records"),
    }

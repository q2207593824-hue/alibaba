# -*- coding: utf-8 -*-
import base64
import json
import os
import re
import time
from typing import Dict, List, Optional, Tuple

import pandas as pd
import requests

from app.core.admin_runtime_config import resolve_runtime_secret
from app.core.logger import setup_logger
from app.core.settings import config_manager, get_config
from app.core.task_manager import TaskInfo

logger = setup_logger("title_optimize_service")

API_BASE_URL = "https://ark.cn-beijing.volces.com/api/v3"
API_ENDPOINT = "/responses"


def _safe_pid(v: any) -> str:
    s = str(v or "").strip()
    if re.fullmatch(r"\d+\.0+", s):
        return s.split(".")[0]
    by_param = re.search(r"(?:itemId=|productId=|id=)(\d{10,20})", s, re.I)
    if by_param:
        return by_param.group(1)
    arr = re.findall(r"\d{10,20}", s)
    if arr:
        arr.sort(key=lambda x: len(x), reverse=True)
        return arr[0]
    return s


def _parse_date(v) -> Optional[pd.Timestamp]:
    if v is None or str(v).strip() == "":
        return None
    try:
        if isinstance(v, pd.Timestamp):
            return pd.Timestamp(v.date())
    except Exception:
        pass
    s = str(v).strip().replace("'", "")
    digits = re.sub(r"\D", "", s)
    if len(digits) == 6:
        y = 2000 + int(digits[:2])
        m = int(digits[2:4])
        d = int(digits[4:6])
        try:
            return pd.Timestamp(year=y, month=m, day=d)
        except Exception:
            return None
    if len(digits) == 8:
        y = int(digits[:4])
        m = int(digits[4:6])
        d = int(digits[6:8])
        try:
            return pd.Timestamp(year=y, month=m, day=d)
        except Exception:
            return None
    try:
        dt = pd.to_datetime(s, errors="coerce")
        if pd.notna(dt):
            return pd.Timestamp(dt.date())
    except Exception:
        pass
    return None


def _load_title_map(image_save_dir: str) -> Dict[str, str]:
    title_path = os.path.join(image_save_dir, "产品标题.xlsx")
    if not os.path.exists(title_path):
        return {}
    try:
        df = pd.read_excel(title_path, engine="openpyxl", dtype=str)
    except Exception:
        return {}
    m = {}
    for _, r in df.iterrows():
        pid = _safe_pid(r.get("产品ID"))
        title = str(r.get("产品标题") or "").strip()
        if pid and title and title.lower() != "nan":
            m[pid] = title
    return m


def _find_image_path(image_save_dir: str, pid: str) -> str:
    for ext in (".jpg", ".jpeg", ".png", ".webp"):
        p = os.path.join(image_save_dir, f"{pid}{ext}")
        if os.path.exists(p):
            return p
    return ""


def _find_latest_excel_in_dir(dir_path: str) -> str:
    if not os.path.isdir(dir_path):
        return ""
    files = []
    for n in os.listdir(dir_path):
        if n.startswith("~$"):
            continue
        if n.lower().endswith((".xlsx", ".xls")):
            fp = os.path.join(dir_path, n)
            try:
                files.append((os.path.getmtime(fp), fp))
            except Exception:
                continue
    files.sort(key=lambda x: x[0], reverse=True)
    return files[0][1] if files else ""


def _load_keyword_map(product360_excel_result_dir: str) -> Dict[str, Dict[str, List[str]]]:
    result: Dict[str, Dict[str, List[str]]] = {}
    excel_path = _find_latest_excel_in_dir(product360_excel_result_dir)
    if not excel_path:
        return result

    try:
        xls = pd.ExcelFile(excel_path)
        if "关键词" not in xls.sheet_names:
            return result
        df = pd.read_excel(excel_path, sheet_name="关键词", dtype=str)
    except Exception:
        return result

    cols = [str(c).strip() for c in df.columns]
    pid_col = "产品ID" if "产品ID" in cols else (cols[0] if cols else "")
    kw_col = "关键词" if "关键词" in cols else (cols[1] if len(cols) > 1 else "")
    click_col = "搜索点击次数" if "搜索点击次数" in cols else ""

    if not pid_col or not kw_col:
        return result

    for _, r in df.iterrows():
        pid = _safe_pid(r.get(pid_col))
        kw = str(r.get(kw_col) or "").strip()
        if not pid or not kw:
            continue
        click_num = 0.0
        if click_col:
            try:
                click_num = float(str(r.get(click_col) or "0").replace(",", "").strip())
            except Exception:
                click_num = 0.0
        obj = result.setdefault(pid, {"clicked": [], "unclicked": []})
        if click_num >= 1:
            if kw not in obj["clicked"]:
                obj["clicked"].append(kw)
        else:
            if kw not in obj["unclicked"]:
                obj["unclicked"].append(kw)
    return result


def inspect_title_optimize_inputs(product_ids: List[str]) -> Dict:
    cfg = get_config()
    da = cfg.data_analysis
    dd = cfg.data_download
    image_save_dir = (dd.store_image_save_dir or "").strip()
    product360_excel_result_dir = (dd.product360_excel_result_dir or "").strip()

    title_map = _load_title_map(image_save_dir)
    kw_map = _load_keyword_map(product360_excel_result_dir)

    rows = []
    for raw in product_ids or []:
        pid = _safe_pid(raw)
        if not pid:
            continue
        kws = kw_map.get(pid, {"clicked": [], "unclicked": []})
        rows.append({
            "product_id": pid,
            "has_title": bool(title_map.get(pid)),
            "has_image": bool(_find_image_path(image_save_dir, pid)),
            "clicked_keyword_count": len(kws.get("clicked", []) or []),
            "unclicked_keyword_count": len(kws.get("unclicked", []) or []),
            "keyword_count": len((kws.get("clicked", []) or []) + (kws.get("unclicked", []) or [])),
        })

    return {
        "image_save_dir": image_save_dir,
        "product360_excel_result_dir": product360_excel_result_dir,
        "rows": rows,
    }


def _load_anomaly_ids(volatility_file_path: str) -> List[str]:
    if not os.path.exists(volatility_file_path):
        return []
    try:
        xls = pd.ExcelFile(volatility_file_path)
        target = "异动" if "异动" in xls.sheet_names else (xls.sheet_names[-1] if xls.sheet_names else "")
        if not target:
            return []
        df = pd.read_excel(volatility_file_path, sheet_name=target, dtype=str)
    except Exception:
        return []
    ids: List[str] = []

    cols = [str(c).strip() for c in list(df.columns)]
    pid_col = "产品ID" if "产品ID" in cols else (cols[0] if cols else "")

    # 仅分析“全店曝光为负数”的异动产品
    # 兼容不同表头：全店曝光次数/全店曝光/shopExposure
    exposure_candidates = ["全店曝光次数", "全店曝光", "shopExposure"]
    exposure_col = next((c for c in exposure_candidates if c in cols), "")

    def _to_float(v) -> float:
        try:
            s = str(v if v is not None else "").strip()
            if not s or s.lower() == "nan":
                return 0.0
            return float(s.replace(",", ""))
        except Exception:
            return 0.0

    for _, r in df.iterrows():
        pid = _safe_pid(r.get(pid_col) if pid_col else "")
        if not pid:
            continue

        # 无法定位曝光列时，为了满足“仅负数”约束，这里选择跳过该行
        if not exposure_col:
            continue

        shop_exposure = _to_float(r.get(exposure_col))
        if shop_exposure < 0 and pid not in ids:
            ids.append(pid)

    return ids


def _load_new_ids_7_30(new_output_file: str) -> List[str]:
    if not os.path.exists(new_output_file):
        return []
    try:
        df = pd.read_excel(new_output_file, sheet_name="全店曝光次数", dtype=str)
    except Exception:
        return []

    ids = []
    today = pd.Timestamp.now().normalize()
    for _, r in df.iterrows():
        pid = _safe_pid(r.get("产品ID"))
        if not pid:
            continue
        raw_date = r.get("发品日期") or r.get("发布时间") or r.get("发布日") or r.get("日期")
        dt = _parse_date(raw_date)
        if dt is None:
            continue
        days = int((today - dt).days)
        if 7 <= days <= 30 and pid not in ids:
            ids.append(pid)
    return ids


def _build_prompt(title: str, clicked: List[str], unclicked: List[str]) -> str:
    clicked_text = ", ".join(clicked[:60]) if clicked else ""
    unclicked_text = ", ".join(unclicked[:60]) if unclicked else ""
    return f"""你是一名阿里巴巴国际站资深运营专家，请根据以下资料进行专业分析：

【产品标题】
{title}

【有点击关键词】(用户搜索这些词后点击了产品)
{clicked_text}

【无点击关键词】(用户搜索这些词后曝光但未点击)
{unclicked_text}

【产品图片】
(见附件图片链接，请结合视觉内容分析)

【分析任务】（请用中文回复，结构清晰，建议具体可执行）
1️⃣ 判定标题描述与图片内容是否相符（重点检查：折叠/扩展/花园/双层/阳台/露台/庭院/别墅/岗亭/工地/厕所/储物间/健身房/超市/餐厅/咖啡厅/车间/工厂/农场/宿舍/运动场馆/车棚/房屋/卫生间//俯瞰图等视觉元素）
2️⃣ 分析为什么某些关键词有点击，某些无点击（从用户意图、匹配度、场景契合度角度）
3️⃣ 给出标题优化建议（保留高点击词、删除误导词、突出可视化卖点）
4️⃣ 提供 2 个优化后的标题版本（符合阿里国际站规则，128 字符内，核心词前置）
5️⃣ 建议哪些关键词融入产品属性/卖点描述中，能更好提升转化

要求：分析要具体、可落地，避免空泛描述。关键建议用【】标出。
第五点返回的格式：属性埋词推荐：【推荐的关键词】（关键词不能出现中文）    详情页卖点埋词推荐：【关键词：紧扣关键词以及产品核心写60-80字符的标题】（标题需要用英文写，这里建议放多少个关键词就写多少条接口,格式为只能是：关键词：标题）  禁止埋入关键词：【禁止埋入的关键词】"""


def _image_path_to_data_url(path: str) -> str:
    ext = os.path.splitext(path)[1].lower()
    mime = "image/jpeg"
    if ext == ".png":
        mime = "image/png"
    elif ext == ".webp":
        mime = "image/webp"
    elif ext in {".jpg", ".jpeg"}:
        mime = "image/jpeg"

    with open(path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("utf-8")
    return f"data:{mime};base64,{b64}"


def _call_doubao(api_key: str, model_name: str, prompt: str, image_data_url: str) -> Tuple[str, str, str]:
    url = API_BASE_URL + API_ENDPOINT
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    # 强制多模态：必须包含图片 + 文本
    if not image_data_url or not str(image_data_url).startswith("data:image/"):
        raise ValueError("图片数据无效，已禁止纯文本分析")

    content = [
        {"type": "input_image", "image_url": image_data_url},
        {"type": "input_text", "text": prompt},
    ]

    payload = {
        "model": model_name,
        "input": [{"role": "user", "content": content}],
    }

    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=300)
        resp.raise_for_status()
    except requests.HTTPError as e:
        status = getattr(getattr(e, "response", None), "status_code", None)
        if status == 401:
            raise ValueError(
                "豆包 API Key 无效或模型无权限（401），请管理员检查 data_analysis.doubao_api_key 与 doubao_model_name"
            ) from e
        if status == 404:
            raise ValueError(
                f"豆包模型不存在或 endpoint 错误（404），请检查模型名称：{model_name}"
            ) from e
        raise ValueError(f"豆包 API 调用失败（HTTP {status}）：{e}") from e
    except requests.RequestException as e:
        raise ValueError(f"豆包 API 网络异常：{e}") from e
    data = resp.json()

    text = ""
    for item in data.get("output", []):
        if item.get("type") == "message" and item.get("role") == "assistant":
            for c in item.get("content", []):
                if c.get("type") == "output_text":
                    text = c.get("text") or ""
                    break
    if not text:
        return "", "", json.dumps(data, ensure_ascii=False)

    analysis = text.strip()

    # 仅从“版本1/版本2”结构中提取，禁止再从分析正文里猜测，避免错把分析句当标题
    v1, v2 = _extract_title_versions_from_analysis(analysis)
    suggested = "\n".join([x for x in [v1, v2] if x])
    return suggested, analysis, text


def _append_result(results: List[Dict], pid: str, source: str, title_map: Dict[str, str], kw_map: Dict[str, Dict[str, List[str]]], image_save_dir: str, api_key: str, model_name: str, detail_dir: str):
    original_title = title_map.get(pid, "")
    kw = kw_map.get(pid, {"clicked": [], "unclicked": []})
    clicked = kw.get("clicked", [])
    unclicked = kw.get("unclicked", [])
    image_path = _find_image_path(image_save_dir, pid)

    if not original_title:
        results.append({
            "product_id": pid,
            "original_title": "",
            "suggested_title": "",
            "source": source,
            "detail_file": "",
            "error": "未在产品标题.xlsx中找到原标题",
        })
        return

    if not image_path:
        results.append({
            "product_id": pid,
            "original_title": original_title,
            "suggested_title": "",
            "source": source,
            "detail_file": "",
            "error": "未找到产品图片，已按要求禁止纯文本分析",
        })
        return

    prompt = _build_prompt(original_title, clicked, unclicked)

    try:
        image_data_url = _image_path_to_data_url(image_path)
        suggested_title, analysis, raw_text = _call_doubao(api_key, model_name, prompt, image_data_url)
        if not suggested_title:
            suggested_title = original_title

        # 详情文件按日期文件夹+产品ID命名：YYMMDD/产品ID.txt（同一天同产品覆盖，避免重复）
        day_folder = time.strftime("%y%m%d")
        day_dir = os.path.join(detail_dir, day_folder)
        os.makedirs(day_dir, exist_ok=True)
        detail_file = os.path.join(day_dir, f"{pid}.txt")
        detail_body = (
            f"产品ID: {pid}\n"
            f"来源: {source}\n"
            f"原标题: {original_title}\n"
            f"建议优化标题: {suggested_title}\n"
            f"\n--- 详细分析 ---\n{analysis}\n"
        )
        with open(detail_file, "w", encoding="utf-8") as f:
            f.write(detail_body)

        results.append({
            "product_id": pid,
            "original_title": original_title,
            "suggested_title": suggested_title,
            "source": source,
            "detail_file": detail_file,
            "error": "",
        })
    except Exception as e:
        results.append({
            "product_id": pid,
            "original_title": original_title,
            "suggested_title": "",
            "source": source,
            "detail_file": "",
            "error": str(e),
        })


def _save_live_results(result_file: str, rows: List[Dict]):
    data = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "results": rows,
    }
    with open(result_file, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def count_title_optimize_targets(product_ids: Optional[List[str]] = None) -> int:
    cfg = get_config()
    da = cfg.data_analysis

    manual_ids: List[str] = []
    for pid in (product_ids or []):
        p = _safe_pid(pid)
        if p and p not in manual_ids:
            manual_ids.append(p)

    if manual_ids:
        return len(manual_ids)

    anomaly_ids = _load_anomaly_ids(da.volatility_file_path)
    new_ids = _load_new_ids_7_30(da.new_output_file)
    target_pids: List[str] = []
    for pid in anomaly_ids + new_ids:
        if pid and pid not in target_pids:
            target_pids.append(pid)
    return len(target_pids)


def run_title_optimize_task(
    task: TaskInfo,
    product_ids: Optional[List[str]] = None,
    user_id: int = 0,
    skip_points: bool = False,
    token: str = "",
):
    cfg = config_manager.reload_from_disk()
    da = cfg.data_analysis
    dd = cfg.data_download

    api_key = resolve_runtime_secret("data_analysis", "doubao_api_key")
    model_name = (getattr(da, "doubao_model_name", "doubao-seed-2-0-pro-260215") or "doubao-seed-2-0-pro-260215").strip()
    if not api_key:
        raise ValueError("豆包 API Key 未配置或为脱敏占位，请管理员保存完整 Key 后重试")
    result_file = (getattr(da, "title_optimize_result_file", "") or os.path.join(da.source_dir, "产品优化建议结果.json")).strip()
    detail_dir = (getattr(da, "title_optimize_detail_dir", "") or os.path.join(da.source_dir, "产品优化建议详情")).strip()

    os.makedirs(os.path.dirname(result_file) or da.source_dir, exist_ok=True)
    os.makedirs(detail_dir, exist_ok=True)

    image_save_dir = (dd.store_image_save_dir or "").strip()
    product360_excel_result_dir = (dd.product360_excel_result_dir or "").strip()

    task.current_step = "读取标题与关键词数据"
    title_map = _load_title_map(image_save_dir)
    kw_map = _load_keyword_map(product360_excel_result_dir)

    task.current_step = "收集待分析产品"
    anomaly_ids = _load_anomaly_ids(da.volatility_file_path)
    new_ids = _load_new_ids_7_30(da.new_output_file)

    manual_ids = []
    for pid in (product_ids or []):
        p = _safe_pid(pid)
        if p and p not in manual_ids:
            manual_ids.append(p)

    source_map: Dict[str, List[str]] = {}
    target_pids: List[str] = []

    def add_source(pid: str, label: str):
        if not pid:
            return
        if pid not in source_map:
            source_map[pid] = []
            target_pids.append(pid)
        if label not in source_map[pid]:
            source_map[pid].append(label)

    if manual_ids:
        for pid in manual_ids:
            add_source(pid, "指定产品")
    else:
        for pid in anomaly_ids:
            add_source(pid, "异动")
        for pid in new_ids:
            add_source(pid, "新品")

    if not target_pids:
        task.current_step = "未找到待分析产品"
        raise ValueError("未找到待分析产品：请检查异动表、新品数据或手动指定产品ID")

    task.total = len(target_pids)
    task.progress = 0
    task.current_step = f"待分析产品 {task.total} 个"
    logger.info(f"产品优化建议任务已启动，待分析产品数: {task.total}")

    # 给前端一个稳定的 running 观察窗口，避免任务极快完成时状态一闪而过
    grace_end = time.time() + 1.2
    while time.time() < grace_end:
        if task.should_stop():
            break
        task.wait_if_paused()
        time.sleep(0.1)

    merged_results: List[Dict] = []
    success_count = 0
    error_count = 0
    _save_live_results(result_file, merged_results)

    for pid in target_pids:
        if task.should_stop():
            break
        task.wait_if_paused()
        labels = source_map.get(pid, [])
        source = "/".join(labels) if labels else "未知"
        task.current_step = f"分析: {pid}"
        before_len = len(merged_results)
        _append_result(merged_results, pid, source, title_map, kw_map, image_save_dir, api_key, model_name, detail_dir)
        task.progress += 1
        _save_live_results(result_file, merged_results)
        if len(merged_results) > before_len:
            last = merged_results[-1]
            if last.get("error"):
                error_count += 1
                logger.warning(f"产品优化建议分析失败 {pid}: {last.get('error')}")
            else:
                success_count += 1
                logger.info(f"产品优化建议分析完成 {pid}")
                if not skip_points and user_id > 0:
                    try:
                        from app.services.membership_service import deduct_title_optimize_points

                        deduct_title_optimize_points(user_id, biz_id=pid, token=token)
                    except Exception as e:
                        logger.error(f"产品优化建议扣积分失败 {pid}: {e}")
                        raise

    _save_live_results(result_file, merged_results)

    if not task.should_stop() and success_count == 0 and error_count > 0:
        raise ValueError(f"没有任何产品成功生成优化建议，全部失败 {error_count} 个，请检查产品标题、图片目录和关键词数据")


def _extract_title_versions_from_analysis(analysis: str) -> Tuple[str, str]:
    text = str(analysis or "")

    def clean(s: str) -> str:
        x = str(s or "").strip().strip("`“”\"' ")
        x = re.sub(r"^[\-•\*\s]+", "", x)
        return x

    def is_title_like(s: str) -> bool:
        x = clean(s)
        if len(x) < 25:
            return False
        bad_words = ["匹配", "建议", "误导", "点击", "曝光", "转化", "原因", "属性", "卖点", "场景", "结论", "分析", "关键词"]
        if any(w in x for w in bad_words):
            return False
        cjk_count = len(re.findall(r"[\u4e00-\u9fff]", x))
        return cjk_count <= 2

    # 先截取“优化后标题版本”段，避免误抓上文
    block = text
    m_block = re.search(r"(?:4️⃣|4\.|四、)?\s*优化后标题版本[\s\S]*", text)
    if m_block:
        block = m_block.group(0)

    lines = [ln.strip() for ln in block.splitlines() if ln.strip()]
    v1 = ""
    v2 = ""

    def pick_after(idx: int, tail: str) -> str:
        cands = [tail]
        for k in range(1, 4):
            if idx + k < len(lines):
                cands.append(lines[idx + k])
        for c in cands:
            cc = clean(c).strip("`")
            if is_title_like(cc):
                return cc
        return ""

    for i, ln in enumerate(lines):
        norm = re.sub(r"^[>#\-•*\d\.、\s]+", "", ln).strip()
        m1 = re.search(r"^版本\s*1\s*(?:[:：]|\(|（)?\s*(.*)$", norm, re.I)
        m2 = re.search(r"^版本\s*2\s*(?:[:：]|\(|（)?\s*(.*)$", norm, re.I)

        if m1 and not v1:
            v1 = pick_after(i, m1.group(1))
        if m2 and not v2:
            v2 = pick_after(i, m2.group(1))

    # 兜底：在标题版本段内提取反引号标题（适配“> `Title`”格式）
    if not v1 or not v2:
        quoted = []
        for ln in lines:
            line = str(ln or "").strip()
            m = re.search(r"`([^`]{20,})`", line)
            if m:
                t = clean(m.group(1))
                if is_title_like(t):
                    quoted.append(t)
                    continue
            t2 = clean(re.sub(r"^[>\-•\s]+", "", line))
            if is_title_like(t2):
                quoted.append(t2)

        dedup = []
        seen = set()
        for q in quoted:
            k = q.lower()
            if k in seen:
                continue
            seen.add(k)
            dedup.append(q)

        if not v1 and len(dedup) >= 1:
            v1 = dedup[0]
        if not v2 and len(dedup) >= 2:
            v2 = dedup[1]

    # 硬兜底：如果还是没拿到，不返回“分析句”，宁可留空
    return v1, v2


def _latest_day_dir(detail_dir: str) -> str:
    if not os.path.isdir(detail_dir):
        return ""
    candidates = []
    for n in os.listdir(detail_dir):
        p = os.path.join(detail_dir, n)
        if not os.path.isdir(p):
            continue
        if re.fullmatch(r"\d{6}", str(n)):
            candidates.append(n)
    if not candidates:
        return ""
    candidates.sort(reverse=True)
    return os.path.join(detail_dir, candidates[0])


def _parse_detail_txt(path: str) -> Dict:
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    head = content
    analysis = ""
    if "--- 详细分析 ---" in content:
        parts = content.split("--- 详细分析 ---", 1)
        head = parts[0]
        analysis = parts[1]

    marker = "--- 原始模型返回 ---"
    if marker in analysis:
        analysis = analysis.split(marker, 1)[0]

    pid = ""
    source = ""
    original_title = ""
    suggested_title = ""

    for ln in head.splitlines():
        line = ln.strip()
        if line.startswith("产品ID:"):
            pid = _safe_pid(line.split(":", 1)[1].strip())
        elif line.startswith("来源:"):
            source = line.split(":", 1)[1].strip()
        elif line.startswith("原标题:"):
            original_title = line.split(":", 1)[1].strip()
        elif line.startswith("建议优化标题:"):
            suggested_title = line.split(":", 1)[1].strip()

    v1, v2 = _extract_title_versions_from_analysis(analysis)
    # 只信任“版本1/版本2”提取结果，旧文件头里的“建议优化标题”可能是错误内容
    suggested_title = "\n".join([x for x in [v1, v2] if x])

    optimize_attr_lines = []
    for ln in analysis.splitlines():
        t = ln.strip()
        if not t:
            continue
        if any(t.startswith(prefix) for prefix in ("属性埋词推荐", "详情页卖点埋词推荐", "禁止埋入关键词", "关键词:")):
            optimize_attr_lines.append(t)
    optimize_attr = "\n".join(optimize_attr_lines)

    return {
        "product_id": pid,
        "original_title": original_title,
        "suggested_title": suggested_title,
        "source": source,
        "optimize_time": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(os.path.getmtime(path))),
        "optimize_attr": optimize_attr,
        "history_data": analysis.strip(),
        "detail_file": path,
        "error": "",
    }


def get_title_optimize_results() -> Dict:
    cfg = get_config()
    da = cfg.data_analysis
    detail_dir = (getattr(da, "title_optimize_detail_dir", "") or os.path.join(da.source_dir, "产品优化建议详情")).strip()

    def _normalize_row(row: Dict) -> Dict:
        return {
            "product_id": str(row.get("product_id") or row.get("产品ID") or "").strip(),
            "original_title": str(row.get("original_title") or row.get("原标题") or "").strip(),
            "suggested_title": str(row.get("suggested_title") or row.get("优化后的标题") or "").strip(),
            "source": str(row.get("source") or row.get("来源") or "").strip(),
            "detail_file": str(row.get("detail_file") or row.get("detail_path") or "").strip(),
            "error": str(row.get("error") or "").strip(),
        }

    rows: List[Dict] = []
    source_file = ""
    generated_at = ""

    day_dir = _latest_day_dir(detail_dir)
    if day_dir:
        source_file = day_dir
        for name in sorted(os.listdir(day_dir)):
            if not str(name).lower().endswith(".txt"):
                continue
            fp = os.path.join(day_dir, name)
            if not os.path.isfile(fp):
                continue
            try:
                row = _parse_detail_txt(fp)
                normalized = _normalize_row(row)
                if normalized["product_id"]:
                    rows.append(normalized)
            except Exception:
                continue

        generated_at = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(os.path.getmtime(day_dir)))

    if not rows:
        # 如果最新详情目录没有解析出任何行，回退读取旧 JSON 结果，避免页面空白
        result_file = (getattr(da, "title_optimize_result_file", "") or os.path.join(da.source_dir, "产品优化建议结果.json")).strip()
        source_file = result_file if os.path.exists(result_file) else source_file
        if os.path.exists(result_file):
            with open(result_file, "r", encoding="utf-8") as f:
                data = json.load(f)

            if not generated_at:
                generated_at = str(data.get("generated_at", "") or "").strip()
            raw_rows: List[Dict] = []
            if isinstance(data.get("results"), list):
                raw_rows = data.get("results", [])
            else:
                raw_rows.extend(data.get("anomaly", []) or [])
                raw_rows.extend(data.get("new_product", []) or [])

            for row in raw_rows:
                normalized = _normalize_row(row if isinstance(row, dict) else {})
                if normalized["product_id"]:
                    rows.append(normalized)

    return {
        "generated_at": generated_at,
        "source_file": source_file,
        "result_count": len(rows),
        "results": rows,
    }


def get_title_optimize_detail(product_id: str) -> Dict:
    data = get_title_optimize_results()
    all_rows = list(data.get("results", []))
    pid = _safe_pid(product_id)
    matched = [r for r in all_rows if _safe_pid(r.get("product_id")) == pid and r.get("detail_file")]
    if not matched:
        return {"product_id": pid, "content": "未找到该产品的分析详情"}
    latest = sorted(matched, key=lambda x: str(x.get("detail_file")), reverse=True)[0]
    detail_file = latest.get("detail_file")
    if not detail_file or not os.path.exists(detail_file):
        return {"product_id": pid, "content": "详情文件不存在"}
    with open(detail_file, "r", encoding="utf-8") as f:
        content = f.read()

    # 兼容旧文件：去掉“原始模型返回”重复段
    marker = "--- 原始模型返回 ---"
    if marker in content:
        content = content.split(marker, 1)[0].rstrip()

    return {"product_id": pid, "content": content, "detail_file": detail_file}

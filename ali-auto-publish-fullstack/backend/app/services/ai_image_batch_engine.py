# -*- coding: utf-8 -*-
"""AI 批量生图引擎 — 由原 main-批量生成.py 完整内嵌，勿删减业务逻辑。"""
import os
import sys
import base64
import requests
import json
import re
import time
import threading
import shutil
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

# Windows 控制台默认 GBK，避免 emoji / 中文输出报错
if sys.platform == "win32":
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8")
            except Exception:
                pass

# ==========================================
# 配置区域 (Configuration Area)
# ==========================================
CONFIG = {
    "API_KEY": "",
    "MODEL": "gemini-3.1-flash-image-preview",
    "BASE_URL": "https://aigc.dianlichina.com.cn",

    # 目录配置
    "INPUT_ROOT_DIR": r"D:\桌面\珠宝图批量生成\原图",
    "OUTPUT_ROOT_DIR": r"D:\桌面\珠宝图批量生成\生成图",

    # 图片生成配置
    "GENERATIONS_PER_IMAGE": 6,
    "ASPECT_RATIO": "1:1",
    "IMAGE_SIZE": "1K",

    # 速度配置（12 张图目标 <240s：全局 4 并发 + 略缩小上传图）
    "CONCURRENT_WORKERS": 5,
    "PROMPT_WORKERS": 2,
    "RESIZE_MAX_EDGE": 1280,
    "JPEG_QUALITY": 82,
    "GLOBAL_GEMINI_POOL": True,

    # 稳定性配置（上游流式接口易 500，默认仅用非流式）
    "USE_STREAM": False,
    "MAX_RETRIES": 3,
    "RETRY_DELAY": 6,
    "REQUEST_INTERVAL": 0,
    "SKIP_EXISTING": True,

    # ---------- 豆包（火山方舟官方 API，与上方 Gemini 完全独立）----------
    # 获取 Key: https://console.volcengine.com/ark/region:ark+cn-beijing/apiKey
    # 创建推理接入点: 方舟控制台 -> 在线推理 -> 创建接入点 -> 复制 ep-xxx 或模型名
    "DOUBAO": {
        "ENABLED": True,
        "API_KEY": "",  # 火山方舟官方 API Key；留空则读取环境变量 ARK_API_KEY
        "BASE_URL": "https://ark.cn-beijing.volces.com/api/v3",
        # API Model ID（与 KEY 权限「Doubao-Seed-2.0-lite」对应）或 ep- 接入点 ID
        # 展示名 Doubao-Seed-2.0-lite 会自动映射为 doubao-seed-2-0-lite-260428
        # 官方示例模型；也可用 ep- 接入点（写入 doubao_ep.txt）
        "MODEL": "doubao-seed-2-0-lite-260215",
        "USE_OFFICIAL_SDK": True,
        # 同目录 doubao_ep.txt 可写 ep-xxx，会覆盖上面 MODEL
        "EP_FILE": "doubao_ep.txt",
        "PROBE_ON_STARTUP": True,
        "PROBE_STRICT": False,
        "OUTPUT_LANGUAGE": "English",
        "CACHE_PROMPTS": True,
        "USE_CACHED_PROMPTS": True,
        "FORCE_REFRESH": False,
        "MAX_RETRIES": 3,
        "RETRY_DELAY": 5,
    },
    # 提示词来源优先级: 有缓存用缓存；否则调豆包；最后回退 txt
    "PROMPT_SOURCE_PRIORITY": ["cache", "doubao", "txt"],
    # SKU 图：0 或不填表示不生成；>0 时在主图目录下 SKU/ 子文件夹保存
    "SKU_GENERATIONS_COUNT": 0,
    "SKU_NAMES": [],
}

_log_lock = threading.Lock()

_external_log_fn = None
_points_charge_fn = None
_points_batch_stopped = False
_points_charge_lock = threading.Lock()

def set_external_log_fn(fn):
    global _external_log_fn
    _external_log_fn = fn


def set_points_charge_fn(fn):
    """每张成功出图后回调；fn(label: str) -> None，失败应抛出 ValueError。"""
    global _points_charge_fn
    _points_charge_fn = fn


def reset_points_charge_state():
    global _points_batch_stopped
    _points_batch_stopped = False


_delivery_lock = threading.Lock()
_delivery_state = {
    "date_tag": "",
    "product_index": 0,
    "used_scenes": set(),
}


def reset_delivery_state():
    """重置批次归档编号（每个产品一张图1占用一个编号）。"""
    with _delivery_lock:
        _delivery_state["date_tag"] = datetime.now().strftime("%m%d").lstrip("0")
        _delivery_state["product_index"] = 0
        _delivery_state["used_scenes"] = set()


def _sanitize_path_component(name: str) -> str:
    return re.sub(r'[\\/:*?"<>|]', "", str(name or "").strip()) or "默认"


_ENGLISH_SKU_FILENAME_RE = re.compile(r"^[A-Za-z0-9]+(?:[-_][A-Za-z0-9]+)*$")
_SKU_EN_NAME_CACHE: dict[str, str] = {}
_SKU_EN_NAME_LOCK = threading.Lock()

_COMMON_SKU_EN_MAP = {
    "红": "Red",
    "红色": "Red",
    "深红": "Deep-Red",
    "深红色": "Deep-Red",
    "酒红": "Wine-Red",
    "酒红色": "Wine-Red",
    "蓝": "Blue",
    "蓝色": "Blue",
    "深蓝": "Deep-Blue",
    "深蓝色": "Deep-Blue",
    "天蓝": "Sky-Blue",
    "天蓝色": "Sky-Blue",
    "绿": "Green",
    "绿色": "Green",
    "墨绿": "Dark-Green",
    "墨绿色": "Dark-Green",
    "黄": "Yellow",
    "黄色": "Yellow",
    "金": "Gold",
    "金色": "Gold",
    "银": "Silver",
    "银色": "Silver",
    "玫瑰金": "Rose-Gold",
    "香槟金": "Champagne-Gold",
    "黑": "Black",
    "黑色": "Black",
    "白": "White",
    "白色": "White",
    "灰": "Gray",
    "灰色": "Gray",
    "紫": "Purple",
    "紫色": "Purple",
    "粉": "Pink",
    "粉色": "Pink",
    "橙": "Orange",
    "橙色": "Orange",
    "棕": "Brown",
    "棕色": "Brown",
    "咖色": "Coffee",
    "咖啡色": "Coffee",
    "米色": "Beige",
    "透明": "Transparent",
    "多色": "Multi-Color",
    "大号": "Large",
    "中号": "Medium",
    "小号": "Small",
    "均码": "One-Size",
}


def _looks_english_sku_filename(name: str) -> bool:
    s = re.sub(r"\s+", "-", str(name or "").strip())
    return bool(s and _ENGLISH_SKU_FILENAME_RE.match(s))


def _normalize_english_sku_filename(name: str) -> str:
    s = re.sub(r"\s+", "-", str(name or "").strip())
    s = re.sub(r"[^\w.\-]", "", s, flags=re.ASCII)
    s = re.sub(r"-+", "-", s).strip("-_.")
    return s or "SKU"


def _local_translate_sku_name(name: str) -> str:
    raw = str(name or "").strip()
    if not raw:
        return ""
    if raw in _COMMON_SKU_EN_MAP:
        return _COMMON_SKU_EN_MAP[raw]
    for suffix in ("色", "款", "号"):
        if raw.endswith(suffix) and raw[:-len(suffix)] in _COMMON_SKU_EN_MAP:
            return _COMMON_SKU_EN_MAP[raw[:-len(suffix)]]
    return ""


def _doubao_translate_sku_name(name: str) -> str:
    global _doubao_blocked
    if _doubao_blocked == "ModelNotOpen":
        raise RuntimeError("豆包不可用")
    cfg = CONFIG.get("DOUBAO", {})
    if not cfg.get("ENABLED"):
        raise RuntimeError("豆包未启用")
    client = get_ark_client()
    model = get_doubao_model()
    prompt = (
        "将以下产品 SKU / 颜色 / 规格名称翻译为简短的英文文件名。\n"
        "要求：仅输出英文名称本身；使用 Title-Case；单词之间用连字符连接；"
        "1-4 个英文单词；只能包含英文字母和连字符；不要解释、不要引号、不要 JSON。\n"
        f"名称：{name}"
    )
    response = client.responses.create(
        model=model,
        input=[{"role": "user", "content": [{"type": "input_text", "text": prompt}]}],
    )
    text = _extract_ark_response_text(response).strip()
    if not text:
        raise ValueError("豆包未返回翻译结果")
    text = text.strip("\"'` ")
    text = text.splitlines()[0].strip()
    text = re.sub(r"^(?:filename|name|output)\s*[:：]\s*", "", text, flags=re.IGNORECASE)
    return text


def _english_sku_save_name(name: str) -> str:
    """SKU 保存文件名（不含扩展名），非英文名称会翻译为英文。"""
    raw = str(name or "").strip()
    if not raw:
        return "SKU"
    with _SKU_EN_NAME_LOCK:
        cached = _SKU_EN_NAME_CACHE.get(raw)
    if cached:
        return cached

    if _looks_english_sku_filename(re.sub(r"\s+", "-", raw)):
        result = _normalize_english_sku_filename(raw)
    else:
        local = _local_translate_sku_name(raw)
        if local:
            result = _normalize_english_sku_filename(local)
        else:
            try:
                translated = _doubao_translate_sku_name(raw)
                result = _normalize_english_sku_filename(translated)
            except Exception as e:
                log(f"    [SKU] 名称翻译失败 ({raw}): {e}")
                result = _normalize_english_sku_filename(local) or "SKU"
        if not _looks_english_sku_filename(result):
            result = f"SKU-{abs(hash(raw)) % 100000}"

    with _SKU_EN_NAME_LOCK:
        _SKU_EN_NAME_CACHE[raw] = result
    return result


def _pick_title_scene_for_delivery(level_tag: str) -> str:
    try:
        from app.services.image_service import (
            _get_compatible_title_scene,
            _get_title_scenes,
            get_image_norm_config,
        )

        delivery_cfg = CONFIG.get("DELIVERY") or {}
        excel = (delivery_cfg.get("title_excel_path") or "").strip()
        scenes = _get_title_scenes(excel)
        norm = get_image_norm_config()
        with _delivery_lock:
            scene = _get_compatible_title_scene(
                level_tag or None,
                scenes,
                _delivery_state["used_scenes"],
                norm.get("house_type_allowed_scenes", {}),
                norm.get("house_type_forbidden_scenes", {}),
            )
            _delivery_state["used_scenes"].add(scene)
        return scene
    except Exception:
        return "默认场景"


def _allocate_delivery_bundle(level_tag: str, scene_from_file: str | None = None) -> dict:
    """为当前原图分配 日期-编号；场景仅用于图1首图文件名，不写进提示词。"""
    delivery_cfg = CONFIG.get("DELIVERY") or {}
    primary_dir = (delivery_cfg.get("primary_image_dir") or "").strip()
    main_dir = (delivery_cfg.get("main_image_dir") or "").strip()
    enabled = bool(primary_dir and main_dir)

    with _delivery_lock:
        _delivery_state["product_index"] += 1
        idx = _delivery_state["product_index"]
        date_tag = _delivery_state["date_tag"]
    delivery_id = f"{date_tag}-{idx}"
    scene_override = (scene_from_file or "").strip()
    if scene_override:
        scene_raw = scene_override
        with _delivery_lock:
            _delivery_state["used_scenes"].add(scene_raw)
    else:
        scene_raw = _pick_title_scene_for_delivery(level_tag)
    level = _sanitize_path_component(level_tag or "默认")
    scene = _sanitize_path_component(scene_raw)

    primary_path = ""
    main_folder = ""
    if enabled:
        os.makedirs(primary_dir, exist_ok=True)
        os.makedirs(main_dir, exist_ok=True)
        primary_path = os.path.join(primary_dir, f"{delivery_id}-{level}-{scene}.jpg")
        main_folder = os.path.join(main_dir, delivery_id)
        os.makedirs(main_folder, exist_ok=True)

    return {
        "enabled": enabled,
        "delivery_id": delivery_id,
        "level_tag": level,
        "scene": scene,
        "primary_path": primary_path,
        "main_folder": main_folder,
    }


def _delivery_target_path(task: dict) -> str:
    delivery = task.get("delivery") or {}
    if not delivery.get("enabled"):
        return ""
    seq = int(task.get("seq") or 0)
    if seq == 1:
        return delivery.get("primary_path") or ""
    main_folder = delivery.get("main_folder") or ""
    if not main_folder:
        return ""
    level = delivery.get("level_tag") or "默认"
    if seq == 2:
        return os.path.join(main_folder, f"2-{level}.jpg")
    if 3 <= seq <= 6:
        return os.path.join(main_folder, f"{seq}.jpg")
    return os.path.join(main_folder, f"{seq}.jpg")


def _sku_target_path(delivery: dict, sku_name: str) -> str:
    """SKU 图保存路径：主图目录/SKU/{英文名称}.jpg"""
    main_folder = (delivery.get("main_folder") or "").strip()
    if not main_folder:
        return ""
    save_name = _english_sku_save_name(sku_name)
    sku_dir = os.path.join(main_folder, "SKU")
    return os.path.join(sku_dir, f"{save_name}.jpg")


def _get_sku_config() -> tuple[int, list[str]]:
    count = max(0, int(CONFIG.get("SKU_GENERATIONS_COUNT") or 0))
    names = [str(n).strip() for n in (CONFIG.get("SKU_NAMES") or []) if str(n).strip()]
    return count, names


def _save_image_as_jpeg(src_path: str, dest_path: str) -> None:
    try:
        from PIL import Image

        with Image.open(src_path) as img:
            if img.mode in ("RGBA", "P"):
                img = img.convert("RGB")
            img.save(dest_path, format="JPEG", quality=92, optimize=True)
        return
    except Exception:
        pass
    shutil.copy2(src_path, dest_path)


def _write_main_image_price_csv(task: dict) -> None:
    """主图2 归档目录写入出厂价（仅发品目录）。"""
    delivery = task.get("delivery") or {}
    if int(task.get("seq") or 0) != 2 or not task.get("price"):
        return
    csv_path = os.path.join(delivery.get("main_folder") or "", "出厂价格.csv")
    try:
        with open(csv_path, "w", encoding="utf-8") as f:
            f.write(str(task.get("price")))
    except OSError as e:
        log(f"    [警告] 写入出厂价格.csv 失败: {e}")


def _persist_generation_result(save_path: str, res_type: str, res_data) -> bool:
    """写入生成结果；发品路径为 .jpg 时转 JPEG，否则保留 PNG 字节。"""
    os.makedirs(os.path.dirname(save_path) or ".", exist_ok=True)
    use_jpeg = save_path.lower().endswith((".jpg", ".jpeg"))

    if res_type == "base64":
        raw = base64.b64decode(res_data)
        if use_jpeg:
            try:
                from PIL import Image
                import io

                with Image.open(io.BytesIO(raw)) as img:
                    if img.mode in ("RGBA", "P"):
                        img = img.convert("RGB")
                    img.save(save_path, format="JPEG", quality=92, optimize=True)
                return True
            except Exception:
                pass
        with open(save_path, "wb") as f:
            f.write(raw)
        return True

    if res_type == "url":
        import tempfile

        tmp = None
        try:
            fd, tmp = tempfile.mkstemp(suffix=".png")
            os.close(fd)
            if not download_image_from_url(res_data, tmp):
                return False
            if use_jpeg:
                _save_image_as_jpeg(tmp, save_path)
            else:
                shutil.copy2(tmp, save_path)
            return True
        finally:
            if tmp and os.path.isfile(tmp):
                try:
                    os.remove(tmp)
                except OSError:
                    pass
    return False


def _charge_points_for_success(task: dict) -> bool:
    global _points_batch_stopped
    if _points_batch_stopped or not _points_charge_fn:
        return True
    label = str(task.get("label") or task.get("img_base_name") or "")
    try:
        with _points_charge_lock:
            _points_charge_fn(label)
        return True
    except ValueError as e:
        _points_batch_stopped = True
        log(f"    [积分] {e}，后续出图已中止")
        return False
    except Exception as e:
        _points_batch_stopped = True
        log(f"    [积分] 扣费异常: {e}，后续出图已中止")
        return False

_session_local = threading.local()
_doubao_blocked = None  # ModelNotOpen 等不可恢复错误，避免重复请求
_gemini_quota_exhausted = False  # Gemini 余额不足后不再重试/不再并发浪费


def log(msg):
    with _log_lock:
        if _external_log_fn:
            _external_log_fn(str(msg))
        else:
            print(msg, flush=True)


def get_session():
    """Gemini 图片生成用 HTTP 会话"""
    if not getattr(_session_local, "session", None):
        _session_local.session = requests.Session()
    return _session_local.session


def get_doubao_api_key():
    key = (CONFIG.get("DOUBAO", {}).get("API_KEY") or "").strip()
    if not key:
        key = os.environ.get("ARK_API_KEY", "").strip()
    return key


# 控制台展示名 -> 官方 API Model ID（与 KEY 权限页「Doubao-Seed-2.0-lite」对应）
DOUBAO_MODEL_ALIASES = {
    "Doubao-Seed-2.0-lite": "doubao-seed-2-0-lite-260215",
    "doubao-seed-2-0-lite": "doubao-seed-2-0-lite-260215",
    "doubao-seed-2-0-lite-260428": "doubao-seed-2-0-lite-260215",
    "Doubao-Seed-2.0-pro": "doubao-seed-2-0-pro-260215",
}


def _load_ep_from_file():
    """从项目目录 doubao_ep.txt 读取 ep- 接入点（一行，推荐）"""
    ep_abs = CONFIG.get("DOUBAO", {}).get("_EP_FILE_ABSPATH")
    if ep_abs and os.path.isfile(ep_abs):
        with open(ep_abs, "r", encoding="utf-8") as f:
            line = f.read().strip().splitlines()[0].strip()
            if line.startswith("ep-"):
                return line
    ep_file = CONFIG.get("DOUBAO", {}).get("EP_FILE", "doubao_ep.txt")
    for base in (os.path.dirname(os.path.abspath(__file__)), os.getcwd()):
        path = os.path.join(base, ep_file)
        if os.path.isfile(path):
            with open(path, "r", encoding="utf-8") as f:
                line = f.read().strip().splitlines()[0].strip()
                if line.startswith("ep-"):
                    return line
    return ""


def get_doubao_model():
    ep = _load_ep_from_file()
    if ep:
        return ep
    model = (CONFIG.get("DOUBAO", {}).get("MODEL") or "").strip()
    if not model:
        model = os.environ.get("ARK_ENDPOINT_ID", "").strip()
    return DOUBAO_MODEL_ALIASES.get(model, model)


def get_ark_client():
    """火山方舟官方 SDK 客户端（volcenginesdkarkruntime.Ark）"""
    if not getattr(_session_local, "ark_client", None):
        from volcenginesdkarkruntime import Ark

        cfg = CONFIG["DOUBAO"]
        _session_local.ark_client = Ark(
            base_url=cfg["BASE_URL"].rstrip("/"),
            api_key=get_doubao_api_key(),
        )
    return _session_local.ark_client


def _extract_ark_response_text(response):
    """从 Responses API 返回中提取文本（跳过 reasoning 块）"""
    texts = []
    for item in getattr(response, "output", None) or []:
        if getattr(item, "type", None) == "message" and getattr(item, "content", None):
            for part in item.content:
                text = getattr(part, "text", None)
                if text:
                    texts.append(text)
    return "\n".join(texts).strip()


def _mark_doubao_blocked_from_error(exc):
    global _doubao_blocked
    msg = str(exc)
    if "ModelNotOpen" in msg or "not activated the model" in msg:
        _doubao_blocked = "ModelNotOpen"
        return True
    return False


def _doubao_model_format_hint(model):
    """仅拦截明显错误的 MODEL 格式"""
    if model.startswith("ep-"):
        return None
    if re.match(r"^doubao-[a-z0-9.-]+$", model):
        if "seedance" in model or "seedream" in model:
            return (
                f"MODEL=\"{model}\" 是视频/生图模型，不能用于「看图写策划」。\n"
                "请改用 doubao-seed-2-0-lite-260215 或视觉类 ep- 接入点。"
            )
        return None
    if re.match(r"^Doubao-", model) or re.search(r"\d+\.\d", model):
        mapped = DOUBAO_MODEL_ALIASES.get(model)
        if mapped:
            return None
        return (
            f"MODEL=\"{model}\" 无法识别。\n"
            "Doubao-Seed-2.0-lite 请填: doubao-seed-2-0-lite-260215\n"
            "或在「自定义推理接入点」复制 ep-xxxxxxxx"
        )
    return None


def list_doubao_vision_model_ids():
    """查询账号下名称含 vision 的模型（需先在控制台开通）"""
    cfg = CONFIG["DOUBAO"]
    url = f"{cfg['BASE_URL'].rstrip('/')}/models"
    try:
        resp = requests.get(
            url,
            headers={"Authorization": f"Bearer {get_doubao_api_key()}"},
            timeout=30,
        )
        if resp.status_code != 200:
            return []
        items = resp.json().get("data", [])
        ids = []
        for m in items:
            mid = m.get("id", m) if isinstance(m, dict) else m
            s = str(mid).lower()
            if "vision" in s or ("seed" in s and "seedance" not in s and "seedream" not in s):
                ids.append(str(mid))
        return ids[:15]
    except requests.exceptions.RequestException:
        return []


def probe_doubao_model():
    """启动时探测 MODEL 是否可用，失败则给出明确指引"""
    cfg = CONFIG.get("DOUBAO", {})
    if not cfg.get("ENABLED") or not cfg.get("PROBE_ON_STARTUP", True):
        return

    raw_model = (CONFIG.get("DOUBAO", {}).get("MODEL") or os.environ.get("ARK_ENDPOINT_ID", "")).strip()
    model = get_doubao_model()
    if raw_model and raw_model != model:
        log(f"[配置] 豆包 MODEL 已映射: {raw_model} -> {model}")
    else:
        log(f"[配置] 豆包 MODEL = {model} (官方 SDK Responses API)")

    fmt_err = _doubao_model_format_hint(model)
    if fmt_err:
        raise RuntimeError(fmt_err)

    try:
        get_ark_client().responses.create(model=model, input="回复 OK")
        log("[配置] 豆包官方 SDK 探测成功")
        return
    except Exception as e:
        _mark_doubao_blocked_from_error(e)
        hint = f"\n豆包探测失败: {e}\n"
        if _doubao_blocked == "ModelNotOpen":
            hint += "【操作】MODEL 使用 doubao-seed-2-0-lite-260215（与官方示例一致）\n"
        if cfg.get("PROBE_STRICT", False):
            raise RuntimeError(hint) from e
        log("[警告] 豆包不可用，将尝试缓存/txt。")
        log(f"         {hint.strip()}")


def validate_doubao_config():
    """启动前校验豆包官方配置（仅 ENABLED 时）"""
    cfg = CONFIG.get("DOUBAO", {})
    if not cfg.get("ENABLED"):
        return
    key = get_doubao_api_key()
    model = get_doubao_model()
    if not key:
        raise RuntimeError(
            "豆包已启用但未配置官方 API Key。\n"
            "请在 CONFIG['DOUBAO']['API_KEY'] 填写火山方舟 Key，"
            "或设置环境变量 ARK_API_KEY。\n"
            "获取地址: https://console.volcengine.com/ark/region:ark+cn-beijing/apiKey"
        )
    if not model:
        raise RuntimeError(
            "豆包已启用但未配置 MODEL（推理接入点 ID）。\n"
            "请打开方舟控制台 -> 在线推理 -> 创建接入点 -> 复制 ep-xxxxxxxx\n"
            "填入 CONFIG['DOUBAO']['MODEL']，或设置环境变量 ARK_ENDPOINT_ID。\n"
            "可先运行: py 检查豆包配置.py"
        )
    fmt_err = _doubao_model_format_hint(model)
    if fmt_err:
        raise RuntimeError(fmt_err)
    if key == CONFIG.get("API_KEY"):
        log("    [警告] 豆包 Key 与 Gemini Key 相同，请确认使用的是火山方舟官方 Key")
    probe_doubao_model()

PROMPT_TEMPLATES = [
    # 若 txt 未按「图 N」分段，可在此填写任务类型列表作为兜底
]

# 发给豆包的策划指令（{image_count}、{output_language} 运行时替换）
DOUBAO_PLANNER_PROMPT = """你是一位资深电商视觉策划专家，精通多品类产品的视觉设计规范制定。请务必为 正好 {image_count} 张 图片制定独立且互不重复的设计计划。
你的任务是：
分析用户提供的产品图片。
判断产品是否为复杂品类。
结合用户的需求描述（特别注意用户是否要求 "无文字 / 纯净版" 设计）。
制定整体设计规范（design_specs）。
为每张图片制定详细的设计计划。
复杂结构判断：产品符合以下任一条件即判定为 true：
（1）含可折叠 / 伸缩 / 旋转的机械关节或活动部件
（2）由多个独立零件组合，零件数量、位置、比例有明确物理约束
（3）存在精密结构（螺纹、卡扣、铰链、导轨、齿轮等）
若判定为 true，执行以下约束：
参考图视角分析：规划每张图前，先分析参考图中实际存在的拍摄角度，为每张图选定一个具体视角（正面、侧面、45 度斜角、俯视或局部特写等），写入该图 design_content 的 选用视角 字段。只能选用参考图中实际存在的角度；允许在已有视角基础上做局部特写放大，但不得改变拍摄方向。严禁：第一人称视角、使用者主观视角、透过产品任何部件的内视角、参考图中不存在的纵深透视构图。
产品形态锁定：形态、外形、颜色、材质、零件数量、连接关系、机械结构必须与参考图完全一致，不得改变。
创意边界：仅限场景选择、光影设计、背景氛围、装饰道具。
若判定为 false：不执行上述任何约束，保持正常创意自由度。
判断结果写入：① JSON 顶层字段 is_complex_product（布尔值，不加引号）；② 每张图 design_content 第一行 产品复杂结构判定 字段。当 is_complex_product 为 true 时，在 design_content 第二行写入 选用视角：[从参考图视角分析得出的视角]。
其他逻辑规则：
文案区分原则：区分 "设计文案"（后期排版加入的标题 / 卖点）与 "产品文字"（产品瓶身 / 包装上固有的 Logo、成分、标签）。
无文案处理逻辑：若用户需求为 "无文案" 设计，则 文字内容 下的所有字段填入 "None"，并在 展示重点 中强调 "通过纯视觉、构图和光影展现产品，不添加任何排版文案"。design_specs 中的 ## 字体系统 部分必须输出为："无 (纯视觉设计，不涉及排版文案)"，不提供具体的字体推荐。
输出必须是严格的 JSON 格式，包含以下结构：
{{
"is_complex_product": 布尔值，
"design_specs": "# 整体设计规范 \\n\\n> 所有图片必须遵循以下统一规范，确保视觉连贯性 \\n\\n## 色彩系统 \\n-主色调：{{主色}}\\n- 辅助色：{{辅助色}}\\n- 背景色：{{背景色}}\\n\\n## 字体系统 \\n- 标题字体：{{字体}}\\n- 正文字体：{{字体}}\\n-字号层级：大标题：副标题：正文 = 3:1.8:1\\n\\n## 视觉语言 \\n- 装饰元素：{{装饰}}\\n- 图标风格：{{风格}}\\n-留白原则：{{原则}}\\n\\n## 摄影风格 \\n- 光线：{{光线}}\\n- 景深：{{景深}}\\n- 相机参数参考：{{参数}}\\n\\n## 品质要求 \\n - 分辨率：4K / 高清 \\n- 风格：专业产品摄影 / 商业广告级 \\n- 真实感：超写实 / 照片级 ",
"images": [
{{
"title": "{{标题 4-8 字}}",
"description": "{{描述 1-2 句}}",
"design_content": "产品复杂结构判定：{{true/false}}\\n选用视角：{{视角}}\\n\\n## 图 {{N}}：{{图片类型}}\\n\\n设计目标：{{目标}}\\n\\n产品出现：{{是 / 否}}\\n\\n图中图元素：\\n-{{元素}}\\n\\n构图方案：\\n- 产品占比：{{百分比}}\\n- 布局方式：{{布局}}\\n - 文字区域：{{位置}}\\n\\n内容要素：\\n- 展示重点：{{重点}}\\n- 突出卖点：{{卖点}}\\n- 背景元素：{{背景}}\\n - 装饰元素：{{装饰}}\\n\\n文字内容（使用 {output_language}）：\\n- 主标题：{{文字}}\\n- 副标题：{{文字}}\\n- 说明文字：{{文字}}\\n\\n氛围营造：\\n- 情绪关键词：{{关键词}}\\n - 光影效果：{{光影}}"
}}
]
}}
重要规则：
images 数组必须包含用户指定数量的元素。
每张图的设计内容必须独特，覆盖不同角度和场景。
设计规范必须基于产品图片的实际特征。
design_content 中的文字内容必须使用目标输出语言：{output_language}。
核心指令：整体设计规范 (design_specs)、图片计划中的 title 和 description 必须使用中文编写；只有 design_content 中的 "文字内容" 部分必须根据目标输出语言编写。
输出限制：只输出纯 JSON 字符串，禁止包含任何 Markdown 代码块标签、禁止包含任何前导或后置的解释性文字。确保 JSON 格式合法。
is_complex_product 与每张图 design_content 第一行的 产品复杂结构判定 必须保持一致，均根据判断结果动态输出，不得写死。

{sku_requirement_block}

{user_requirement_block}"""

# 价格：从 txt 提取，不进入提示词；仅用于第 2 张输出文件名后缀
# 场景：从 txt 提取，不进入提示词；仅用于图1首图归档文件名
_SCENE_LINE_RE = re.compile(
    r"^\s*(?:场景|标题场景)\s*[：:=]?\s*(.+?)\s*$",
    re.IGNORECASE | re.MULTILINE,
)
_SCENE_INLINE_RE = re.compile(
    r"(?:场景|标题场景)\s*[：:=]?\s*[^\n\r]+",
    re.IGNORECASE,
)
_SCENE_REMOVE_RE = re.compile(
    r"(?:^|\n)\s*(?:场景|标题场景)\s*[：:=]?\s*[^\n\r]*",
    re.IGNORECASE | re.MULTILINE,
)

_PRICE_LINE_RE = re.compile(
    r"^\s*(?:价格|售价|Price)\s*[：:=]?\s*([0-9]+(?:\.[0-9]+)?)\s*$",
    re.IGNORECASE | re.MULTILINE,
)
_PRICE_INLINE_RE = re.compile(
    r"(?:价格|售价|Price)\s*[：:=]?\s*([0-9]+(?:\.[0-9]+)?)",
    re.IGNORECASE,
)
_PRICE_REMOVE_RE = re.compile(
    r"(?:^|\n)\s*(?:价格|售价|Price)\s*[：:=]?\s*[0-9]+(?:\.[0-9]+)?\s*",
    re.IGNORECASE | re.MULTILINE,
)

_SKU_LINE_RE = re.compile(
    r"^\s*SKU\s*[：:=]\s*(.+?)\s*$",
    re.IGNORECASE | re.MULTILINE,
)
_SKU_INLINE_RE = re.compile(
    r"SKU\s*[：:=]\s*([^\n\r]+)",
    re.IGNORECASE,
)
_SKU_REMOVE_RE = re.compile(
    r"(?:^|\n)\s*SKU\s*[：:=]\s*[^\n\r]*",
    re.IGNORECASE | re.MULTILINE,
)


def _parse_sku_name_list(raw: str) -> list[str]:
    parts = re.split(r"[,，、;；|\n]+", str(raw or "").strip())
    return [p.strip() for p in parts if p.strip()]


def _extract_sku_from_text(text):
    """从文本提取 SKU 列表并移除 SKU 行。返回 (清理后文本, [名称...] 或 None)"""
    if not text:
        return text, None
    names = None
    m = _SKU_LINE_RE.search(text) or _SKU_INLINE_RE.search(text)
    if m:
        parsed = _parse_sku_name_list(m.group(1))
        if parsed:
            names = parsed
    cleaned = _SKU_REMOVE_RE.sub("\n", text)
    cleaned = _SKU_INLINE_RE.sub("", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    return cleaned, names


def _iter_product_txt_files(files):
    """目录内 txt 读取顺序：需求类优先，其余按文件名排序。"""
    names: list[str] = []
    for name in ("需求.txt", "用户需求.txt", "user_requirement.txt"):
        if name in files:
            names.append(name)
    seen = set(names)
    for name in sorted(files):
        if name.lower().endswith(".txt") and name not in seen:
            names.append(name)
            seen.add(name)
    return names


def _sanitize_price_for_filename(price):
    return re.sub(r"[^\w.\-]", "", str(price).strip())


def _is_price_token(part: str) -> bool:
    s = str(part or "").strip()
    if not s:
        return False
    try:
        return float(s) > 0
    except ValueError:
        return False


def _is_position_token(part: str) -> bool:
    """规范化命名中的主图序号 1~6（单段为纯数字且在该范围）。"""
    s = str(part or "").strip()
    if not s.isdigit():
        return False
    return 1 <= int(s) <= 6


def _parse_filename_scene_price(img_base_name: str):
    """
    从原图文件名解析：自由名-场景-价格 或 自由名-价格-场景。
    兼容规范化命名 自由名-图位(1~6)-价格，仅提取价格。
    返回 (自由名, 场景或 None, 价格或 None)；无法识别时均为 None。
    """
    parts = [p.strip() for p in str(img_base_name or "").split("-") if p.strip()]
    if len(parts) < 3:
        return None, None, None

    free_name = "-".join(parts[:-2])
    a, b = parts[-2], parts[-1]
    a_price = _is_price_token(a)
    b_price = _is_price_token(b)
    a_pos = _is_position_token(a)
    b_pos = _is_position_token(b)

    if a_pos and b_price:
        return free_name, None, _sanitize_price_for_filename(b)

    if a_price and not b_price and not b_pos:
        return free_name, _sanitize_path_component(b), _sanitize_price_for_filename(a)

    if b_price and not a_price and not a_pos:
        return free_name, _sanitize_path_component(a), _sanitize_price_for_filename(b)

    return None, None, None


def _sanitize_folder_tag(name: str) -> str:
    """一级子目录名用于文件名后缀（去掉非法字符）"""
    return re.sub(r"[^\w.\-]", "", str(name or "").strip())


def _first_level_subdir_tag(input_root: str, product_dir: str) -> str:
    """
    原图相对配置根目录的一级子目录名。
    例：原图/A/001.jpg -> A；原图/A/B/001.jpg -> A；原图/001.jpg -> 空
    """
    root = os.path.normpath((input_root or "").strip())
    folder = os.path.normpath((product_dir or "").strip())
    if not root or not folder:
        return ""
    try:
        rel = os.path.relpath(folder, root)
    except ValueError:
        return ""
    if rel in (".", ""):
        return ""
    first = rel.split(os.sep)[0].split("/")[0].strip()
    return _sanitize_folder_tag(first)


def _build_output_basename(
    img_base_name: str, seq: int, level_tag: str = "", price: str | None = None
) -> str:
    """生成图文件名（不含扩展名）。第 1 张可带一级子目录后缀：001_1_A；第 2 张追加价格：001_2_30"""
    if seq == 1 and level_tag:
        base = f"{img_base_name}_{seq}_{level_tag}"
    else:
        base = f"{img_base_name}_{seq}"
    if seq == 2 and price:
        base = f"{base}_{price}"
    return base


def _extract_price_from_text(text):
    """从文本提取价格并移除所有价格相关行/片段。返回 (清理后文本, 价格或 None)"""
    if not text:
        return text, None
    price = None
    m = _PRICE_LINE_RE.search(text) or _PRICE_INLINE_RE.search(text)
    if m:
        price = m.group(1)
    cleaned = _PRICE_REMOVE_RE.sub("\n", text)
    cleaned = _PRICE_INLINE_RE.sub("", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    return cleaned, price


def _extract_scene_from_text(text):
    """从文本提取场景并移除场景相关行/片段。返回 (清理后文本, 场景或 None)"""
    if not text:
        return text, None
    scene = None
    m = _SCENE_LINE_RE.search(text)
    if m:
        scene = m.group(1).strip()
    cleaned = _SCENE_REMOVE_RE.sub("\n", text)
    cleaned = _SCENE_INLINE_RE.sub("", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    return cleaned, scene


def _strip_metadata_from_text(text):
    """移除价格、场景、SKU 等仅用于本地配置/命名的字段。"""
    cleaned, _ = _extract_price_from_text(text or "")
    cleaned, _ = _extract_scene_from_text(cleaned)
    cleaned, _ = _extract_sku_from_text(cleaned)
    return cleaned


def _load_product_price(root, files):
    """从目录内 txt 读取价格（首个匹配）"""
    for name in _iter_product_txt_files(files):
        path = os.path.join(root, name)
        try:
            with open(path, "r", encoding="utf-8") as f:
                _, price = _extract_price_from_text(f.read())
            if price:
                return _sanitize_price_for_filename(price)
        except OSError:
            pass
    return None


def _load_product_scene(root, files):
    """从目录内 txt 读取场景（首个匹配），仅用于图1首图文件名。"""
    for name in _iter_product_txt_files(files):
        path = os.path.join(root, name)
        try:
            with open(path, "r", encoding="utf-8") as f:
                _, scene = _extract_scene_from_text(f.read())
            if scene:
                return _sanitize_path_component(scene)
        except OSError:
            pass
    return None


def _load_product_sku_from_txt(root, files):
    """从目录内 txt 读取 SKU（首个匹配）。返回 (数量, 名称列表) 或 (0, [])。"""
    for name in _iter_product_txt_files(files):
        path = os.path.join(root, name)
        try:
            with open(path, "r", encoding="utf-8") as f:
                _, sku_names = _extract_sku_from_text(f.read())
            if sku_names:
                return len(sku_names), list(sku_names)
        except OSError:
            pass
    return 0, []


def _resolve_product_sku_config(root, files):
    """
    解析当前产品 SKU 配置：txt 优先于页面/全局配置。
    返回 (sku_count, sku_names, from_txt)。
    """
    txt_count, txt_names = _load_product_sku_from_txt(root, files)
    if txt_count > 0 and txt_names:
        return txt_count, txt_names, True
    count, names = _get_sku_config()
    return count, names, False


def _strip_sku_from_prompts(common_prompt, prompts_by_num):
    """从提示词正文中移除 SKU 行（SKU 仅走独立策划，不进用户需求/主图 prompt）。"""
    common_prompt, _ = _extract_sku_from_text(common_prompt or "")
    cleaned = {}
    for k, v in (prompts_by_num or {}).items():
        text, _ = _extract_sku_from_text(v or "")
        cleaned[k] = text
    return common_prompt, cleaned


def _strip_price_from_prompts(common_prompt, prompts_by_num):
    """从提示词中移除价格信息，并尝试从正文提取价格"""
    price = None
    common_prompt, p = _extract_price_from_text(common_prompt or "")
    if p:
        price = p
    cleaned = {}
    for k, v in (prompts_by_num or {}).items():
        text, p = _extract_price_from_text(v or "")
        cleaned[k] = text
        if not price and p:
            price = p
    if price:
        price = _sanitize_price_for_filename(price)
    return common_prompt, cleaned, price


def _strip_scene_from_prompts(common_prompt, prompts_by_num):
    """从提示词中移除场景信息，并尝试从正文提取场景（仅用于首图命名）。"""
    scene = None
    common_prompt, s = _extract_scene_from_text(common_prompt or "")
    if s:
        scene = s
    cleaned = {}
    for k, v in (prompts_by_num or {}).items():
        text, s = _extract_scene_from_text(v or "")
        cleaned[k] = text
        if not scene and s:
            scene = s
    if scene:
        scene = _sanitize_path_component(scene)
    return common_prompt, cleaned, scene


def _output_path_with_price(output_path, seq, price, img_base_name: str = ""):
    """第 2 张图在文件名末尾追加价格，如 001_2_30.png"""
    if seq != 2 or not price:
        return output_path
    parent, name = os.path.split(output_path)
    base, ext = os.path.splitext(name)
    img_base = (img_base_name or "").strip()
    if img_base:
        expected = _build_output_basename(img_base, seq, "", price)
        if base == expected:
            return output_path
        bare = _build_output_basename(img_base, seq, "", None)
        if base == bare:
            return os.path.join(parent, f"{expected}{ext}")
    if base.endswith(f"_{price}") and base.count("_") >= 2:
        return output_path
    return os.path.join(parent, f"{base}_{price}{ext}")


def parse_prompts_from_txt(content):
    """
    解析 txt：公共规范（图1之前的内容）+ 按「图 N：」拆分的各张提示词。
    返回 (common_prompt, {序号: 该图提示词})
    """
    content = content.replace("\\n", "\n").strip()
    content = _strip_metadata_from_text(content)
    if not content:
        return "", {}

    pattern = re.compile(r"图\s*(\d+)\s*[：:]")
    matches = list(pattern.finditer(content))
    if not matches:
        return "", {0: content}

    common = content[: matches[0].start()].strip()
    prompts = {}
    for i, m in enumerate(matches):
        num = int(m.group(1))
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(content)
        prompts[num] = content[start:end].strip()

    return common, prompts


def _extract_json_from_text(text):
    """从豆包回复中提取 JSON（兼容 markdown 代码块）"""
    text = (text or "").strip()
    if not text:
        raise ValueError("豆包返回内容为空")

    fence = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text, re.IGNORECASE)
    if fence:
        text = fence.group(1).strip()

    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError(f"未找到 JSON 对象: {text[:200]}")
    return json.loads(text[start : end + 1])


def doubao_json_to_prompts(data):
    """将豆包 JSON 转为 (公共规范, {序号: 单图提示词})"""
    common = (data.get("design_specs") or "").strip()
    if isinstance(common, dict):
        common = json.dumps(common, ensure_ascii=False, indent=2)

    complex_flag = data.get("is_complex_product")
    if complex_flag is not None and common:
        common = f"产品复杂结构判定：{str(complex_flag).lower()}\n\n{common}"

    prompts = {}
    images = data.get("images") or []
    for i, item in enumerate(images, 1):
        if not isinstance(item, dict):
            continue
        design = (item.get("design_content") or "").strip()
        title = (item.get("title") or "").strip()
        desc = (item.get("description") or "").strip()

        parts = []
        if title:
            parts.append(title)
        if desc:
            parts.append(desc)
        if design:
            parts.append(design)
        if not parts:
            continue

        body = "\n\n".join(parts)
        if not re.search(r"图\s*\d+\s*[：:]", design):
            body = f"图 {i}：{title or '设计方案'}\n\n{body}"
        prompts[i] = body.strip()

    return common, prompts


def _build_variant_prompt(item: dict, fallback_label: str) -> str:
    if not isinstance(item, dict):
        return ""
    design = (item.get("design_content") or "").strip()
    title = (item.get("title") or "").strip()
    desc = (item.get("description") or "").strip()
    parts = []
    if title:
        parts.append(title)
    if desc:
        parts.append(desc)
    if design:
        parts.append(design)
    if not parts:
        return ""
    body = "\n\n".join(parts)
    if not re.search(r"图\s*\d+\s*[：:]", design):
        body = f"图 {fallback_label}：{title or '设计方案'}\n\n{body}"
    return body.strip()


def doubao_json_to_sku_prompts(data, sku_count: int = 0, sku_names=None):
    """将豆包 JSON 转为 [(SKU名称, 提示词), ...]"""
    if sku_count <= 0:
        return []
    common = (data.get("design_specs") or "").strip()
    if isinstance(common, dict):
        common = json.dumps(common, ensure_ascii=False, indent=2)
    complex_flag = data.get("is_complex_product")
    if complex_flag is not None and common:
        common = f"产品复杂结构判定：{str(complex_flag).lower()}\n\n{common}"

    configured_names = [str(n).strip() for n in (sku_names or []) if str(n).strip()]
    variants = data.get("sku_variants") or []
    result = []
    for i in range(sku_count):
        if i < len(configured_names):
            name = configured_names[i]
        elif i < len(variants) and isinstance(variants[i], dict):
            name = (variants[i].get("name") or variants[i].get("title") or f"SKU-{i + 1}").strip()
        else:
            name = f"SKU-{i + 1}"
        variant = variants[i] if i < len(variants) else {}
        body = _build_variant_prompt(variant, f"SKU-{name}")
        if not body:
            body = (
                f"图 SKU-{name}：{name} 规格展示图\n\n"
                f"设计目标：展示 {name} 规格/颜色变体，背景简洁，产品居中。\n"
                f"比例：1:1 正方形，适合电商 SKU 缩略图。"
            )
        prompt_parts = []
        if common:
            prompt_parts.append(f"整体设计规范：\n{common}")
        prompt_parts.append(body)
        prompt_parts.append(
            "请根据以上信息和原图，生成一张 1:1 正方形的高质量 SKU 展示图，"
            f"突出「{name}」这一规格/颜色变体。"
        )
        result.append((name, "\n\n".join(prompt_parts)))
    return result


def _load_user_requirement(root, files):
    """读取目录内用户需求描述（需求.txt / 用户需求.txt），不含价格、场景字段"""
    for name in ("需求.txt", "用户需求.txt", "user_requirement.txt"):
        if name in files:
            path = os.path.join(root, name)
            with open(path, "r", encoding="utf-8") as f:
                return _strip_metadata_from_text(f.read().strip())
    cfg_text = CONFIG.get("DOUBAO", {}).get("USER_REQUIREMENT", "").strip()
    return _strip_metadata_from_text(cfg_text)


def _prompt_cache_path(root, img_base_name):
    return os.path.join(root, f"{img_base_name}_prompts.json")


def _load_prompt_cache(cache_path, sku_count=None, sku_names=None):
    try:
        with open(cache_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if sku_count is None:
            sku_count, sku_names = _get_sku_config()
        common, prompts = doubao_json_to_prompts(data)
        sku_prompts = doubao_json_to_sku_prompts(data, sku_count, sku_names)
        return common, prompts, sku_prompts, data
    except (OSError, json.JSONDecodeError, ValueError) as e:
        log(f"    [警告] 读取提示词缓存失败: {e}")
        return None, None, None, None


def _cache_sku_matches(data, sku_count: int) -> bool:
    if sku_count <= 0:
        return True
    cached = data.get("sku_variants") if isinstance(data, dict) else None
    return bool(cached) and len(cached) >= sku_count


def _save_prompt_cache(cache_path, data):
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _build_sku_requirement_block(sku_count: int, sku_names: list) -> str:
    if sku_count <= 0:
        return "【SKU 图】无需生成 SKU 图，JSON 中不需要 sku_variants 字段。"
    lines = [
        f"【SKU 图要求】除主图外，还需策划 {sku_count} 张 SKU 展示图（比例 1:1 正方形）。",
        "JSON 须增加 sku_variants 数组，包含正好 "
        f"{sku_count} 个元素；每项含 name（SKU 名称）、title、description、design_content。",
        "SKU 图用于展示产品不同规格/颜色变体，背景简洁、产品居中，适合电商平台 SKU 选择缩略图。",
        "design_content 须标注「比例：1:1」。",
    ]
    if sku_names:
        names_text = "、".join(sku_names[:sku_count])
        lines.append(f"须为以下 SKU 分别策划（name 字段须与下列名称完全一致）：{names_text}")
    else:
        lines.append("用户未指定 SKU 名称，请根据产品特点自主策划变体（如不同颜色、材质、规格等），name 用中文简短命名。")
    lines.append(
        "sku_variants 示例结构："
        '{"name":"红色","title":"红色款","description":"...","design_content":"比例：1:1\\n..."}'
    )
    return "\n".join(lines)


def _build_doubao_planner_text(user_requirement, sku_count=None, sku_names=None):
    cfg = CONFIG["DOUBAO"]
    n = CONFIG["GENERATIONS_PER_IMAGE"]
    lang = cfg.get("OUTPUT_LANGUAGE", "English")
    if sku_count is None:
        sku_count, sku_names = _get_sku_config()
    if user_requirement:
        req_block = f"【用户需求描述】\n{user_requirement}"
    else:
        req_block = "【用户需求描述】\n（用户未提供额外需求，请根据产品图自主策划）"
    sku_block = _build_sku_requirement_block(sku_count, sku_names or [])
    planner = DOUBAO_PLANNER_PROMPT
    if "{sku_requirement_block}" not in planner:
        planner = planner.replace(
            "{user_requirement_block}",
            "{sku_requirement_block}\n\n{user_requirement_block}",
        )
    return planner.format(
        image_count=n,
        output_language=lang,
        sku_requirement_block=sku_block,
        user_requirement_block=req_block,
    )


def call_doubao_planner(image_path, user_requirement="", sku_count=None, sku_names=None):
    """使用火山方舟官方 SDK (Ark.responses.create) 策划提示词"""
    global _doubao_blocked
    if _doubao_blocked == "ModelNotOpen":
        raise RuntimeError(
            "豆包模型不可用(ModelNotOpen)。请使用 MODEL=doubao-seed-2-0-lite-260215 "
            "或在 doubao_ep.txt 填入 ep- 接入点 ID。"
        )

    cfg = CONFIG["DOUBAO"]
    model = get_doubao_model()
    img_b64, mime_type = prepare_image_for_api(image_path)
    if not img_b64:
        raise RuntimeError("无法读取产品图片")

    if sku_count is None:
        sku_count, sku_names = _get_sku_config()

    planner_text = _build_doubao_planner_text(user_requirement, sku_count, sku_names)
    image_url = f"data:{mime_type};base64,{img_b64}"
    ark_input = [
        {
            "role": "user",
            "content": [
                {"type": "input_text", "text": planner_text},
                {"type": "input_image", "image_url": image_url, "detail": "auto"},
            ],
        }
    ]

    last_err = None
    client = get_ark_client()
    for attempt in range(cfg.get("MAX_RETRIES", 3)):
        try:
            log(f"    [豆包/官方SDK] 正在策划 {CONFIG['GENERATIONS_PER_IMAGE']} 张图提示词（第 {attempt + 1} 次）...")
            response = client.responses.create(
                model=model,
                input=ark_input,
            )
            content = _extract_ark_response_text(response)
            if not content:
                raise ValueError("Responses API 未返回文本内容")
            data = _extract_json_from_text(content)
            images = data.get("images") or []
            if len(images) < CONFIG["GENERATIONS_PER_IMAGE"]:
                log(f"    [豆包] 警告: 仅返回 {len(images)} 条图片计划，期望 {CONFIG['GENERATIONS_PER_IMAGE']}")
            if sku_count > 0:
                sku_variants = data.get("sku_variants") or []
                if len(sku_variants) < sku_count:
                    log(f"    [豆包] 警告: 仅返回 {len(sku_variants)} 条 SKU 计划，期望 {sku_count}")
            return data

        except (KeyError, IndexError, json.JSONDecodeError, ValueError) as e:
            last_err = str(e)
            log(f"    [豆包] 解析失败: {e}")
        except Exception as e:
            last_err = str(e)
            if _mark_doubao_blocked_from_error(e):
                log("    [豆包] 模型不可用，已跳过后续重试")
                raise RuntimeError(last_err) from e
            log(f"    [豆包] 请求异常: {e}")

        time.sleep(cfg.get("RETRY_DELAY", 5) * (attempt + 1))

    raise RuntimeError(f"豆包策划失败: {last_err}")


def resolve_prompts(root, files, img_path, img_base_name, sku_count=None, sku_names=None):
    """
    按优先级获取提示词: doubao / cache / txt
    返回 (common_prompt, prompts_by_num, sku_prompts, source_label)
    sku_prompts: [(name, prompt), ...]
    """
    cfg = CONFIG.get("DOUBAO", {})
    cache_path = _prompt_cache_path(root, img_base_name)
    priority = CONFIG.get("PROMPT_SOURCE_PRIORITY", ["doubao", "cache", "txt"])
    if sku_count is None:
        sku_count, sku_names = _get_sku_config()
    sku_names = list(sku_names or [])

    for source in priority:
        if source == "cache" and cfg.get("USE_CACHED_PROMPTS") and not cfg.get("FORCE_REFRESH"):
            if os.path.isfile(cache_path):
                common, prompts, sku_prompts, cached_data = _load_prompt_cache(
                    cache_path, sku_count, sku_names
                )
                if prompts:
                    if sku_count > 0 and (
                        not sku_prompts or not _cache_sku_matches(cached_data, sku_count)
                    ):
                        log(f"    [提示词] 缓存 SKU 策划与当前配置不一致，尝试其他来源...")
                    else:
                        log(f"    [提示词] 使用缓存 {os.path.basename(cache_path)}")
                        return common, prompts, sku_prompts or [], "cache"

        if source == "doubao" and cfg.get("ENABLED"):
            user_req = _load_user_requirement(root, files)
            try:
                data = call_doubao_planner(
                    img_path, user_req, sku_count=sku_count, sku_names=sku_names
                )
                if cfg.get("CACHE_PROMPTS", True):
                    _save_prompt_cache(cache_path, data)
                    log(f"    [豆包] 已缓存 -> {os.path.basename(cache_path)}")
                common, prompts = doubao_json_to_prompts(data)
                sku_prompts = doubao_json_to_sku_prompts(data, sku_count, sku_names)
                if prompts:
                    nums = sorted(prompts.keys())
                    log(f"    [豆包] 策划完成: 公共规范 + 图 {nums[0]}~{nums[-1]} 共 {len(nums)} 段")
                    if sku_count > 0:
                        log(f"    [豆包] SKU 策划: {len(sku_prompts)} 张")
                    return common, prompts, sku_prompts, "doubao"
            except Exception as e:
                log(f"    [豆包] 失败: {e}，尝试其他来源...")

        if source == "txt":
            skip_names = {"需求.txt", "用户需求.txt", "user_requirement.txt"}
            txt_files = [
                f for f in files
                if f.lower().endswith(".txt") and f not in skip_names
            ]
            if txt_files:
                with open(os.path.join(root, txt_files[0]), "r", encoding="utf-8") as f:
                    common, prompts = parse_prompts_from_txt(f.read())
                if prompts or common:
                    log(f"    [提示词] 使用文本文件 {txt_files[0]}")
                    sku_prompts = doubao_json_to_sku_prompts({}, sku_count, sku_names)
                    return common, prompts, sku_prompts, "txt"

    return "", {}, [], "none"


def encode_image_to_base64(image_path):
    try:
        with open(image_path, "rb") as f:
            return base64.b64encode(f.read()).decode("utf-8")
    except Exception as e:
        log(f"读取图片失败 {image_path}: {e}")
        return None


def prepare_image_for_api(image_path):
    """缩小原图再上传，减少请求体与推理耗时。返回 (base64, mime_type)"""
    max_edge = CONFIG.get("RESIZE_MAX_EDGE", 0)
    ext = os.path.splitext(image_path)[1].lower()
    default_mime = "image/png" if ext == ".png" else "image/jpeg"

    if not max_edge:
        b64 = encode_image_to_base64(image_path)
        return (b64, default_mime) if b64 else (None, None)

    try:
        from PIL import Image
        import io

        with Image.open(image_path) as img:
            if img.mode in ("RGBA", "P") and ext != ".png":
                img = img.convert("RGB")
            w, h = img.size
            if max(w, h) > max_edge:
                img.thumbnail((max_edge, max_edge), Image.Resampling.LANCZOS)
                log(f"    [压缩] {w}x{h} -> {img.size[0]}x{img.size[1]}")
            buf = io.BytesIO()
            if ext == ".png":
                img.save(buf, format="PNG", optimize=True)
                mime = "image/png"
            else:
                img.save(buf, format="JPEG", quality=CONFIG.get("JPEG_QUALITY", 85), optimize=True)
                mime = "image/jpeg"
            return base64.b64encode(buf.getvalue()).decode("utf-8"), mime
    except ImportError:
        log("    [提示] 未安装 Pillow，跳过缩图。可执行: pip install Pillow")
    except Exception as e:
        log(f"    [警告] 缩图失败，使用原图: {e}")

    b64 = encode_image_to_base64(image_path)
    return (b64, default_mime) if b64 else (None, None)


def download_image_from_url(image_url, output_path):
    try:
        img_data = get_session().get(image_url, stream=True, timeout=60)
        img_data.raise_for_status()
        with open(output_path, "wb") as f:
            for chunk in img_data.iter_content(chunk_size=8192):
                f.write(chunk)
        return True
    except Exception as e:
        print(f"下载图片失败: {e}")
        return False


def _build_payload(image_base64, prompt, mime_type="image/jpeg", aspect_ratio=None, image_size=None):
    return {
        "contents": [{
            "role": "user",
            "parts": [
                {"inline_data": {"mime_type": mime_type, "data": image_base64}},
                {"text": prompt},
            ],
        }],
        "generationConfig": {
            "responseModalities": ["TEXT", "IMAGE"],
            "imageConfig": {
                "aspectRatio": aspect_ratio or CONFIG["ASPECT_RATIO"],
                "imageSize": image_size or CONFIG["IMAGE_SIZE"],
            },
        },
    }


def _parse_api_error(response):
    try:
        err = response.json().get("error", {})
        msg = err.get("message", response.text[:300])
        meta = err.get("metadata") or {}
        upstream = meta.get("upstream") or {}
        code = upstream.get("code") or err.get("code") or response.status_code
        return code, msg
    except (json.JSONDecodeError, AttributeError):
        return response.status_code, response.text[:300]


def _is_fatal_gemini_error(http_status, err_code, err_msg):
    """不可恢复：余额不足等，重试无意义"""
    if err_code in ("insufficient_user_quota", "insufficient_quota", "billing_not_enough"):
        return True
    if err_msg and ("预扣费额度失败" in err_msg or "余额不足" in err_msg):
        return True
    if http_status == 403 and err_msg and "quota" in err_msg.lower():
        return True
    return False


def _is_retryable(status_code, err_code, err_msg=""):
    if _is_fatal_gemini_error(status_code, err_code, err_msg):
        return False
    if status_code in (429, 500, 502, 503):
        return True
    if err_code in (429, 500, 502, 503):
        return True
    return False


def _extract_image_from_parts(parts):
    image_data_b64 = ""
    image_url = ""
    for part in parts:
        if "inlineData" in part:
            image_data_b64 = part["inlineData"].get("data", "")
        if "fileData" in part:
            image_url = part["fileData"].get("fileUri", "")
        if "text" in part:
            match = re.search(r"!\[image\]\((.*?)\)", part["text"])
            if match:
                image_url = match.group(1)
    if image_data_b64:
        return ("base64", image_data_b64)
    if image_url:
        return ("url", image_url)
    return None, None


def _parse_stream_response(response):
    image_data_b64 = ""
    image_url = ""
    for line in response.iter_lines():
        if not line:
            continue
        raw_line = line.decode("utf-8").strip()
        clean_line = raw_line[len("data: "):] if raw_line.startswith("data: ") else raw_line
        if clean_line.startswith("["):
            clean_line = clean_line[1:]
        if clean_line.endswith("]"):
            clean_line = clean_line[:-1]
        if clean_line.startswith(","):
            clean_line = clean_line[1:]
        if clean_line.endswith(","):
            clean_line = clean_line[:-1]
        if not clean_line:
            continue
        try:
            data = json.loads(clean_line)
            if "candidates" in data:
                for candidate in data["candidates"]:
                    parts = candidate.get("content", {}).get("parts", [])
                    res = _extract_image_from_parts(parts)
                    if res[0]:
                        return res
        except json.JSONDecodeError:
            continue
    return None, None


def _request_generate(url, headers, payload, stream=False):
    session = get_session()
    if stream:
        response = session.post(url, headers=headers, json=payload, stream=True, timeout=600)
        if response.status_code >= 400:
            code, msg = _parse_api_error(response)
            return None, response.status_code, code, msg
        result = _parse_stream_response(response)
        if result and result[0]:
            return result, response.status_code, None, ""
        return None, response.status_code, None, "流式响应中无图片数据"

    response = session.post(url, headers=headers, json=payload, timeout=600)
    if response.status_code >= 400:
        code, msg = _parse_api_error(response)
        return None, response.status_code, code, msg

    data = response.json()
    if "candidates" in data:
        for candidate in data["candidates"]:
            parts = candidate.get("content", {}).get("parts", [])
            res = _extract_image_from_parts(parts)
            if res[0]:
                return res, response.status_code, None, ""
    return None, response.status_code, None, "响应中无图片数据"


def call_gemini_api(image_base64, prompt, mime_type="image/jpeg", aspect_ratio=None, image_size=None):
    global _gemini_quota_exhausted
    if _gemini_quota_exhausted:
        return None, None

    headers = {
        "Authorization": f"Bearer {CONFIG['API_KEY']}",
        "Content-Type": "application/json",
    }
    payload = _build_payload(image_base64, prompt, mime_type, aspect_ratio, image_size)
    base = f"{CONFIG['BASE_URL']}/v1beta/models/{CONFIG['MODEL']}"
    endpoints = []
    if not CONFIG.get("USE_STREAM", False):
        endpoints.append(("非流式", f"{base}:generateContent", False))
    else:
        endpoints.append(("流式", f"{base}:streamGenerateContent", True))
        endpoints.append(("非流式", f"{base}:generateContent", False))

    for attempt in range(CONFIG["MAX_RETRIES"]):
        mode, url, stream = endpoints[attempt % len(endpoints)]
        wait = CONFIG["RETRY_DELAY"] * (1.5 ** min(attempt, 4))

        result, http_status, err_code, err_msg = _request_generate(url, headers, payload, stream=stream)

        if result and result[0]:
            return result

        if _is_fatal_gemini_error(http_status, err_code, err_msg):
            _gemini_quota_exhausted = True
            log(f"      [Gemini] 余额不足 (剩余约 ¥0.15，单张约需 ¥0.18)，已停止后续出图重试")
            log(f"      [Gemini] 请充值 aigc.dianlichina.com.cn 账户后重新运行（已生成的图会跳过）")
            break

        if err_code == 429 or (err_msg and "quota" in err_msg.lower() and http_status != 403):
            wait = max(wait, 30)
            log(f"      ⚠️ [{mode}] 限流 (code={err_code})，等待 {int(wait)}s 后重试...")
        elif http_status >= 400 or err_msg:
            log(f"      ⚠️ [{mode}] HTTP {http_status} code={err_code}: {err_msg[:200]}")
            if _is_retryable(http_status, err_code, err_msg):
                log(f"         第 {attempt + 1}/{CONFIG['MAX_RETRIES']} 次重试，等待 {int(wait)}s...")
            else:
                break
        else:
            log(f"      ⚠️ [{mode}] 未获取到图片，第 {attempt + 1}/{CONFIG['MAX_RETRIES']} 次重试...")

        if not _is_retryable(http_status, err_code, err_msg):
            break
        time.sleep(wait)

    return None, None


def _build_final_prompt(common_prompt, prompts_by_num, seq, i):
    prompt_parts = []
    if common_prompt:
        prompt_parts.append(f"整体设计规范：\n{common_prompt}")
    if prompts_by_num.get(seq):
        prompt_parts.append(prompts_by_num[seq])
    elif prompts_by_num.get(0):
        prompt_parts.append(prompts_by_num[0])
    elif PROMPT_TEMPLATES:
        prompt_parts.append(f"任务类型：{PROMPT_TEMPLATES[i % len(PROMPT_TEMPLATES)]}")
    if not prompt_parts:
        return None
    return "\n\n".join(prompt_parts) + "\n\n请根据以上信息和原图，生成一张高质量的产品效果图。"


def _generate_and_save(task):
    """单张图生成任务（供线程池调用）"""
    if _points_batch_stopped:
        return {"status": "fail", "seq": task.get("seq"), "reason": "points"}

    seq = task.get("seq")
    is_sku = bool(task.get("is_sku"))
    sku_name = task.get("sku_name") or ""
    gen_count = task["gen_count"]
    output_path = task["output_path"]
    img_base_name = task["img_base_name"]

    delivery_dest = _delivery_target_path(task) if not is_sku else ""
    if is_sku:
        save_path = task.get("output_path") or _sku_target_path(task.get("delivery") or {}, sku_name)
    elif delivery_dest:
        save_path = delivery_dest
    else:
        save_path = _output_path_with_price(output_path, seq, task.get("price"), img_base_name)

    if CONFIG["SKIP_EXISTING"] and os.path.isfile(save_path) and os.path.getsize(save_path) > 0:
        return {"status": "skip", "seq": seq, "path": save_path, "is_sku": is_sku}

    t0 = time.time()
    label = task.get("label", f"{img_base_name}_{seq}")
    log(f"    [生成] {label} 开始（提示词约 {len(task['prompt'])} 字）")

    res_type, res_data = call_gemini_api(
        task["img_b64"],
        task["prompt"],
        task["mime_type"],
        aspect_ratio=task.get("aspect_ratio"),
        image_size=task.get("image_size"),
    )
    elapsed = time.time() - t0

    if res_type in ("base64", "url"):
        if not _persist_generation_result(save_path, res_type, res_data):
            log(f"    [失败] {label} 保存失败")
            return {"status": "fail", "seq": seq, "is_sku": is_sku}
        log(f"    [成功] {label} {elapsed:.0f}s -> {save_path}")
        if not _charge_points_for_success(task):
            return {"status": "fail", "seq": seq, "reason": "points", "is_sku": is_sku}
        if is_sku:
            save_name = _english_sku_save_name(sku_name)
            if save_name != sku_name:
                log(f"    [保存] SKU/{save_name} ({sku_name}) -> {save_path}")
            else:
                log(f"    [保存] SKU/{save_name} -> {save_path}")
        elif delivery_dest:
            seq_i = int(seq or 0)
            if seq_i == 1:
                log(f"    [保存] 首图 -> {save_path}")
            else:
                log(f"    [保存] 主图{seq_i} -> {save_path}")
            _write_main_image_price_csv(task)
        return {
            "status": "ok",
            "seq": seq,
            "elapsed": elapsed,
            "label": label,
            "path": save_path,
            "is_sku": is_sku,
        }

    log(f"    [失败] {label} 生成失败 ({elapsed:.0f}s)")
    return {"status": "fail", "seq": seq, "is_sku": is_sku}


def _prepare_one_product(root, files, img_name):
    """单产品：解析提示词 + 压缩原图一次，返回 Gemini 任务列表"""
    img_path = os.path.join(root, img_name)
    img_base_name = os.path.splitext(img_name)[0]

    log(f"\n[目录] {root}")
    log(f"  [原图] {img_name}")

    sku_count, sku_names, sku_from_txt = _resolve_product_sku_config(root, files)
    if sku_from_txt:
        log(f"    [SKU] 来源=txt（覆盖页面配置），共 {sku_count} 张: {', '.join(sku_names)}")
    elif sku_count > 0:
        log(
            f"    [SKU] 来源=页面配置，共 {sku_count} 张"
            + (f": {', '.join(sku_names)}" if sku_names else "（名称由策划决定）")
        )

    common_prompt, prompts_by_num, sku_prompts, prompt_source = resolve_prompts(
        root, files, img_path, img_base_name, sku_count=sku_count, sku_names=sku_names
    )
    name_free, scene_from_name, price_from_name = _parse_filename_scene_price(img_base_name)
    product_price = _load_product_price(root, files)
    product_scene = _load_product_scene(root, files)
    common_prompt, prompts_by_num, price_from_prompts = _strip_price_from_prompts(
        common_prompt, prompts_by_num
    )
    common_prompt, prompts_by_num, scene_from_prompts = _strip_scene_from_prompts(
        common_prompt, prompts_by_num
    )
    common_prompt, prompts_by_num = _strip_sku_from_prompts(common_prompt, prompts_by_num)
    if price_from_name:
        product_price = price_from_name
    elif not product_price and price_from_prompts:
        product_price = price_from_prompts
    if scene_from_name:
        scene_for_name = scene_from_name
    else:
        scene_for_name = product_scene or scene_from_prompts
    log(f"    [提示词] 来源={prompt_source}")
    if name_free and (scene_from_name or price_from_name):
        log(
            f"    [命名] 原图文件名解析 自由名={name_free}"
            + (f" 场景={scene_from_name}" if scene_from_name else "")
            + (f" 价格={price_from_name}" if price_from_name else "")
            + "（优先于 txt）"
        )
    if product_price:
        price_src = "原图文件名" if price_from_name else "txt"
        log(f"    [价格] {product_price}（来源={price_src}，仅用于第 2 张输出文件名，不写入提示词）")
    if scene_for_name:
        scene_src = "原图文件名" if scene_from_name else ("txt" if product_scene or scene_from_prompts else "标题Excel")
        log(f"    [场景] {scene_for_name}（来源={scene_src}，仅用于图1首图文件名，不写入提示词）")
    if not prompts_by_num and not common_prompt:
        log(f"    [错误] 无法获取提示词，跳过 {img_name}")
        return []

    img_b64, mime_type = prepare_image_for_api(img_path)
    if not img_b64:
        return []

    input_root = CONFIG.get("INPUT_ROOT_DIR") or ""
    level_tag = _first_level_subdir_tag(input_root, root)
    if level_tag:
        log(f"    [命名] 一级子目录后缀: {level_tag}")

    delivery = _allocate_delivery_bundle(level_tag, scene_for_name)
    if delivery.get("enabled"):
        if scene_from_name:
            scene_src = "原图文件名"
        elif scene_for_name and (product_scene or scene_from_prompts):
            scene_src = "txt"
        else:
            scene_src = "标题Excel"
        log(
            f"    [归档] 批次 {delivery['delivery_id']} "
            f"场景={delivery['scene']}({scene_src}) 主图目录={delivery['main_folder']}"
        )
    else:
        log("    [错误] 未配置首图/主图文件夹，跳过该产品（请在配置管理 → 路径配置中设置）")
        return []

    gen_count = max(1, int(CONFIG["GENERATIONS_PER_IMAGE"]))
    cached_max = max((k for k in (prompts_by_num or {}) if k > 0), default=0)
    if cached_max and cached_max != gen_count:
        log(
            f"    [出图数量] 配置每张 {gen_count} 张"
            + (f"（缓存含 {cached_max} 条 prompt，仅取前 {gen_count} 张）" if cached_max > gen_count else "")
        )

    tasks = []
    for i in range(gen_count):
        seq = i + 1
        final_prompt = _build_final_prompt(common_prompt, prompts_by_num, seq, i)
        if not final_prompt:
            continue
        out_base = _build_output_basename(img_base_name, seq, level_tag, product_price)
        task_stub = {
            "seq": seq,
            "delivery": delivery,
            "price": product_price,
        }
        file_path = _delivery_target_path(task_stub)
        if not file_path:
            continue
        tasks.append({
            "seq": seq,
            "gen_count": gen_count,
            "img_base_name": img_base_name,
            "price": product_price,
            "label": out_base,
            "output_path": file_path,
            "delivery": delivery,
            "prompt": final_prompt,
            "img_b64": img_b64,
            "mime_type": mime_type,
            "is_sku": False,
        })

    if sku_count > 0 and delivery.get("enabled"):
        if not sku_prompts:
            sku_prompts = doubao_json_to_sku_prompts({}, sku_count, sku_names)
        if sku_names:
            log(f"    [SKU] 将生成 {len(sku_prompts)} 张: {', '.join(n for n, _ in sku_prompts)}")
        else:
            log(f"    [SKU] 将生成 {len(sku_prompts)} 张（名称由策划决定）")
        for sku_name, sku_prompt in sku_prompts:
            sku_path = _sku_target_path(delivery, sku_name)
            if not sku_path:
                continue
            save_name = _english_sku_save_name(sku_name)
            tasks.append({
                "seq": None,
                "gen_count": gen_count,
                "img_base_name": img_base_name,
                "price": product_price,
                "label": f"{img_base_name}_SKU_{save_name}",
                "output_path": sku_path,
                "delivery": delivery,
                "prompt": sku_prompt,
                "img_b64": img_b64,
                "mime_type": mime_type,
                "is_sku": True,
                "sku_name": sku_name,
                "sku_save_name": save_name,
                "aspect_ratio": "1:1",
            })
    return tasks


def _run_gemini_tasks(tasks, label=""):
    if not tasks:
        return []
    workers = min(CONFIG.get("CONCURRENT_WORKERS", 1), len(tasks))
    batch_start = time.time()
    prefix = f"[{label}] " if label else ""
    log(f"    {prefix}[出图] {len(tasks)} 张，{workers} 线程并行")

    results = []
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(_generate_and_save, t): t for t in tasks}
        for future in as_completed(futures):
            results.append(future.result())

    ok = sum(1 for r in results if r["status"] == "ok")
    skipped = sum(1 for r in results if r["status"] == "skip")
    failed = sum(1 for r in results if r["status"] == "fail")
    log(f"    {prefix}[汇总] 成功 {ok} / 跳过 {skipped} / 失败 {failed}，耗时 {time.time() - batch_start:.0f}s")
    return results


def _validate_publish_paths():
    delivery = CONFIG.get("DELIVERY") or {}
    primary = (delivery.get("primary_image_dir") or "").strip()
    main = (delivery.get("main_image_dir") or "").strip()
    if not primary or not main:
        raise RuntimeError(
            "未配置发品图片目录。请在「配置管理 → 路径配置」中设置首图文件夹与主图文件夹。"
        )


def process_batch():
    reset_points_charge_state()
    reset_delivery_state()
    validate_doubao_config()
    _validate_publish_paths()

    product_jobs = []
    for root, dirs, files in os.walk(CONFIG["INPUT_ROOT_DIR"]):
        for img_name in [f for f in files if f.lower().endswith((".png", ".jpg", ".jpeg"))]:
            product_jobs.append((root, files, img_name))

    if not product_jobs:
        log("[提示] 未找到原图")
        return

    total_start = time.time()
    all_tasks = []

    # 阶段1：并行解析各产品提示词（有缓存时几乎瞬间完成）
    prompt_workers = min(CONFIG.get("PROMPT_WORKERS", 2), len(product_jobs))

    def _job_wrapper(args):
        return _prepare_one_product(*args)

    if prompt_workers > 1 and len(product_jobs) > 1:
        log(f"[阶段1] {len(product_jobs)} 个产品，{prompt_workers} 线程解析提示词")
        with ThreadPoolExecutor(max_workers=prompt_workers) as ex:
            for batch in ex.map(_job_wrapper, product_jobs):
                all_tasks.extend(batch)
    else:
        for job in product_jobs:
            all_tasks.extend(_job_wrapper(job))

    if not all_tasks:
        log("[错误] 无有效出图任务")
        return

    # 阶段2：全部出图任务放入同一线程池（避免 001+test1 串行等待）
    if CONFIG.get("GLOBAL_GEMINI_POOL", True):
        log(f"\n[阶段2] 全局并发出图（共 {len(all_tasks)} 张）")
        _run_gemini_tasks(all_tasks, "全局")
    else:
        by_product = {}
        for t in all_tasks:
            by_product.setdefault(t["img_base_name"], []).append(t)
        for name, tasks in by_product.items():
            _run_gemini_tasks(tasks, name)

    if _points_batch_stopped:
        log("\n[积分] 因积分不足已中止后续出图")
    log(f"\n[总计] 全流程耗时 {time.time() - total_start:.0f}s")


if __name__ == "__main__":
    log("[配置] Gemini: " + CONFIG["BASE_URL"])
    if CONFIG.get("DOUBAO", {}).get("ENABLED"):
        log("[配置] 豆包(火山方舟官方): " + CONFIG["DOUBAO"]["BASE_URL"])
    process_batch()
    log("\n[完成] 所有批量任务处理完毕！")
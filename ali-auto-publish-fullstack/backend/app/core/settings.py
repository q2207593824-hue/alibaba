# -*- coding: utf-8 -*-
"""
全局配置中心 - 所有可配置项集中管理
通过 JSON 文件持久化，支持前端热更新
"""
import os
import sys
import json
import re
import shutil
import time
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, model_validator

# ===================== 配置文件路径 =====================
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PROJECT_ROOT = os.path.dirname(BASE_DIR)


def _default_desktop_data_dir() -> str:
    """用户可写目录，避免安装到 Program Files 时无写权限。"""
    appdata = os.environ.get("APPDATA", "").strip()
    if appdata:
        return str(Path(appdata) / "AliAutoPublish" / "data")
    return str(Path.home() / "AliAutoPublish" / "data")


def _resolve_data_dir() -> str:
    explicit = os.getenv("ALI_APP_DATA_DIR", "").strip()
    if explicit:
        return explicit
    if getattr(sys, "frozen", False) or os.getenv("ALI_DESKTOP", "").strip() == "1":
        return _default_desktop_data_dir()
    return os.path.join(PROJECT_ROOT, "data")


# 桌面版可通过环境变量指定可持久化数据目录（避免 onefile 解包临时目录丢失）
DATA_DIR = _resolve_data_dir()
CONFIG_FILE = os.path.join(DATA_DIR, "config.json")
PROJECT_FILES_ROOT_DEFAULT = os.path.join(PROJECT_ROOT, "店铺数据")

os.makedirs(DATA_DIR, exist_ok=True)


# ===================== 配置数据模型 =====================

class PathConfig(BaseModel):
    """路径配置"""
    project_files_root: str = PROJECT_FILES_ROOT_DEFAULT
    chrome_driver_path: str = ""
    primary_image_dir: str = ""
    main_image_dir: str = ""
    detail_image_dir: str = ""
    detail_scene_image_dir: str = ""
    detail_detail_image_dir: str = ""
    detail_company_image_root_dir: str = ""
    detail_company_intro_file: str = ""
    detail_faq_file: str = ""
    title_excel_path: str = ""
    cookie_file: str = ""
    name_mapping_file: str = ""
    published_products_file: str = ""
    used_titles_file: str = ""
    exceptional_main_image_dir: str = ""
    download_save_dir: str = ""


class GroupUrlConfig(BaseModel):
    """组别-发布链接映射"""
    group_url_map: Dict[str, str] = {
        "Detachable Container House": "https://post.alibaba.com/product/publish.htm?spm=a2747.product_manager.0.0.738471d20Xldip&pubType=similarPost&itemId=1601423555947&behavior=copyNew",
        "Flat-packed Container House": "https://post.alibaba.com/product/publish.htm?spm=a2747.product_manager.0.0.738471d20Xldip&pubType=similarPost&itemId=1601468068153&behavior=copyNew",
        "Modular Container House": "https://post.alibaba.com/product/publish.htm?spm=a2747.product_manager.0.0.738471d20Xldip&pubType=similarPost&itemId=1601455150558&behavior=copyNew",
        "Expandable Container House": "https://post.alibaba.com/product/publish.htm?spm=a2747.product_manager.0.0.738471d20Xldip&pubType=similarPost&itemId=1601407357396&behavior=copyNew",
        "Transportable Container House": "https://post.alibaba.com/product/publish.htm?spm=a2747.product_manager.0.0.738471d20Xldip&pubType=similarPost&itemId=1601442233339&behavior=copyNew",
        "Portable Toilet And Bathroom": "https://post.alibaba.com/product/publish.htm?spm=a2747.product_manager.0.0.738471d20Xldip&pubType=similarPost&itemId=1601521709279&behavior=copyNew",
    }
    default_posting_url: str = "https://post.alibaba.com/product/publish.htm?spm=a2747.product_manager.0.0.35bc71d2F06YdT&pubType=similarPost&itemId=1601521798158&behavior=copyNew"


class UploadConfig(BaseModel):
    """上传配置"""
    batch_size: int = 6
    upload_timeout: int = 10
    upload_detect_timeout: float = 30.0
    upload_detect_interval: float = 0.3
    dialog_timeout: int = 10
    upload_interval_seconds: int = 15
    interactive_confirm_before_clear: bool = False
    max_products_per_run: int = 5
    close_browser_after_finish: bool = False

    # 独立功能：产品优化上架（不影响自动发品）
    optimize_edit_url_template: str = "https://post.alibaba.com/product/publish.htm?spm=a2747.product_manager.0.0.6cdb71d2h3NV16&itemId=1601711190204"
    optimize_output_dir: str = ""
    # 逗号分隔的属性名称，例如："特性,应用场景,型号,使用"
    optimize_attribute_names: str = "特性,应用场景,型号,使用"
    # 是否自动点击提交（建议先关闭做联调）
    optimize_auto_submit: bool = False


class ScheduleConfig(BaseModel):
    """定时发布配置"""
    daily_limit_enabled: bool = False
    daily_max_products: int = 5
    publish_time_window: str = "22:00-1:00"
    check_interval: int = 60


class KeywordConfig(BaseModel):
    """关键词配置"""
    keyword_min_count: int = 8
    keyword_max_count: int = 10


class AttributeItemConfig(BaseModel):
    """单个属性配置"""
    container_id: str
    values: List[str] = []
    input_id: Optional[str] = None
    type: str = "required"  # required / optional
    select_type: str = "tag"  # tag / input / single_search / auto_complete


class SpecificationItemConfig(BaseModel):
    """单个规格配置"""
    container_id: str
    values_pool: List[str] = []
    default_values: List[str] = []
    max_select: int = 2
    type: str = "checkbox"
    interaction: str = ""  # checkbox_grid | value_rows（来自发品页扫描）
    scan_operable: bool = False
    # 顶部「商品规格项」复选框 value（如 191292953），用于勾选戒指尺寸/样式等
    sale_attribute_value: str = ""
    # 是否勾选发品页顶部「商品规格项」（None=兼容旧配置自动推断）
    enable_sale_attribute: Optional[bool] = None
    # value_rows 型规格（颜色/样式）：是否开启「添加规格图」
    enable_spec_image: bool = False
    # 规格图目录：主图目录/{产品ID}/image_subdir/SKU名.后缀（颜色规格默认 SKU）
    image_subdir: str = ""


class PageScanWorkflowSnapshot(BaseModel):
    """功能地图快照（写入配置供自动发品校验）"""
    id: str
    title: str = ""
    type: str = ""
    operable: bool = False
    interaction: str = ""
    automation_module: str = ""
    struct_id: str = ""
    spec_name: str = ""
    required: bool = False


class PublishFieldRequirement(BaseModel):
    """扫描页推导的必填/上传项，对接路径配置与自动发品。"""
    workflow_id: str = ""
    label: str = ""
    category: str = ""  # upload | text | compliance | form
    config_key: str = ""  # 如 paths.detail_scene_image_dir
    required: bool = True
    configured: bool = False
    current_value: str = ""


class ComplianceFieldSnapshot(BaseModel):
    """扫描发现的合规/物流必填项（按发品页动态，跨类目通用）。"""
    label: str = ""
    struct_id: str = ""
    source: str = ""  # error_feedback | struct | required_label
    required: bool = True


class PageScanProfile(BaseModel):
    """单个发品页扫描档案"""
    url: str = ""
    group_name: str = ""
    page_type: str = ""
    page_type_label: str = ""
    scanned_at: str = ""
    element_count: int = 0
    workflow_count: int = 0
    workflows: List[PageScanWorkflowSnapshot] = []
    field_requirements: List[PublishFieldRequirement] = []
    compliance_fields: List[ComplianceFieldSnapshot] = []
    ready_for_publish: bool = False
    readiness_issues: List[str] = []


class PageScanConfig(BaseModel):
    """发品页扫描与自动发品对接配置"""
    profiles_by_group: Dict[str, PageScanProfile] = {}


class AttributeConfig(BaseModel):
    """属性填写配置"""
    target_attrs: List[str] = ["型号", "品种", "形状", "品牌", "使用", "设计风格"]
    skip_attrs: List[str] = ["省份", "质保服务"]
    attr_wait_time: int = 2
    retry_times: int = 1
    short_sleep: float = 0.05
    normal_sleep: float = 0.1
    all_attributes: Dict[str, AttributeItemConfig] = {}
    count_rule: Dict[str, int] = {}
    # 兼容旧版本：全局规格（未分组）
    specifications: Dict[str, SpecificationItemConfig] = {}
    # 新版：按分组发品链接组别存储规格
    specifications_by_group: Dict[str, Dict[str, SpecificationItemConfig]] = {}
    # 新增：按类目ID存储规格（优先级高于组别）
    specifications_by_category_id: Dict[str, Dict[str, SpecificationItemConfig]] = {}
    # 组别规格共用映射：group -> source_group
    specification_group_alias: Dict[str, str] = {}
    diff_compare_attrs: List[str] = []

    @model_validator(mode="after")
    def _ensure_always_skip_attrs(self) -> "AttributeConfig":
        """省份等字段强制跳过，避免复制页空等定位。"""
        forced = {"省份"}
        merged = list(dict.fromkeys([*(self.skip_attrs or []), *forced]))
        object.__setattr__(self, "skip_attrs", merged)
        return self


class PriceConfig(BaseModel):
    """阶梯价格配置。默认留空，使用前必须由用户填写。"""
    exchange_rate: Optional[float] = None
    # 售卖单位（struct-priceUnit，阶梯价之前填写）
    sale_type: str = ""
    price_unit: str = ""
    batch_num: Optional[int] = None
    ladder_min_orders: List[Optional[int]] = Field(default_factory=list)
    ladder_factor_ranges: List[List[Optional[float]]] = Field(default_factory=list)
    enable_random_float: bool = False
    round_price_to_integer: bool = True
    product_inventory: Optional[int] = None
    sku_outer_id: str = ""
    # 样品服务（发品时填入 struct-marketSample / struct-sampleSku）
    sample_service_enabled: bool = False
    sample_support_light_customization: bool = False
    sample_max_quantity: Optional[int] = None
    sample_sku_price_usd: Optional[float] = None


class DeliveryConfig(BaseModel):
    """发货期配置。默认不创建档位。"""
    ladder_delivery: List[Dict[str, int]] = Field(default_factory=list)


class LogisticsConfig(BaseModel):
    """物流配置"""
    fill_enable: bool = False
    gross_weight: int = 1500
    dimensions: Dict[str, int] = {"length": 600, "width": 240, "height": 280}
    logistics_attr: str = "普货"
    hs_code: str = "9406300000"


class DetailConfig(BaseModel):
    """商品详情配置"""
    selling_points_excel: str = ""
    max_image_upload: int = 100
    max_selling_points: int = 6


class DataDownloadConfig(BaseModel):
    """数据下载配置"""
    login_url: str = "https://login.alibaba.com/newlogin/icbuLogin.htm?return_url=https%3A%2F%2Fdata.alibaba.com%2F"
    data_url: str = "https://data.alibaba.com/"
    product360_output_dir: str = ""
    product360_json_dir: str = ""
    product360_keyword_json_dir: str = ""
    product360_excel_result_dir: str = ""
    daily_output_dir: str = ""
    weekly_output_dir: str = ""
    traffic_channel_output_file: str = ""
    traffic_channel_cookies_file: str = ""
    traffic_channel_target_url: str = "https://data.alibaba.com/traffic/source?spm=a2700.micro_cgs_home.0.0.54d63e5fh024lb"
    traffic_channel_login_url: str = "https://login.alibaba.com/newlogin/icbuLogin.htm"
    store_image_target_url: str = "https://szdabojin.en.alibaba.com/productlist.html"
    store_image_save_dir: str = ""
    store_image_max_pages: int = 100
    product_operate_output_file: str = ""
    period_type: str = "week"
    headless: bool = False


class KeywordDownloadConfig(BaseModel):
    """选词参谋关键词下载配置"""
    keyword_url: str = "https://data.alibaba.com/traffic/keyword?spm=a2700.micro_cgs_home.0.0.5c353e5fG3MwWr"
    login_url: str = "https://login.alibaba.com/newlogin/icbuLogin.htm?defaultActive=signIn&return_url=https%3A%2F%2Fwww.alibaba.com%2F&_lang=zh_CN"
    download_folder: str = ""
    output_folder: str = ""
    download_wait_time: float = 0.2
    page_wait_time: float = 0.3
    poll_interval: float = 0.1
    size_stable_wait: float = 0.2
    file_detect_timeout: int = 12


class IndustryKeywordConfig(BaseModel):
    """行业关键词下载与整合配置"""
    save_folder: str = ""
    # 逗号/分号/换行分隔，如: tiny house,container house,prefab house
    big_keywords: str = ""
    # 行业关键词整合输出文件
    output_file: str = ""
    # 下拉词关键词（可手工配置，也可由页面选中关键词写入）
    dropdown_keywords: str = ""
    # 下拉词结果输出文件
    dropdown_output_file: str = ""
    # 下载节流秒数
    delay_seconds: float = 2.0


class StoreOverviewConfig(BaseModel):
    """店铺运营数据（数据概览）配置"""
    save_path: str = ""
    summary_output_path: str = ""
    cookie_file: str = ""
    cate_id: str = "201650701"
    login_url: str = "https://login.alibaba.com/newlogin/icbuLogin.htm?return_url=https%3A%2F%2Fdata.alibaba.com%2F"
    # 使用数据概览首页地址，避免落到错误子页面
    data_url: str = "https://data.alibaba.com/?spm=a2793.11769229.0.0.20023e5fc1895x"
    default_end_date: str = "20000101"
    period_type: str = "week"  # day/week/month
    headless: bool = False


class DataAnalysisConfig(BaseModel):
    """数据分析配置"""
    # 强烈建议通过环境变量 DOUBAO_API_KEY 或前端配置写入 data/config.json 提供
    doubao_api_key: str = ""
    doubao_model_name: str = "doubao-seed-2-0-pro-260215"
    title_optimize_result_file: str = ""
    title_optimize_detail_dir: str = ""
    traffic_ai_output_file: str = ""
    target_columns: List[str] = [
        "全店曝光次数", "全站推广曝光次数", "搜索曝光次数",
        "全店点击次数", "全站推广点击次数", "搜索点击次数",
        "访问人数", "收藏人数", "询盘人数", "TM咨询人数"
    ]
    # 目录与文件配置（对齐老脚本）
    source_dir: str = ""
    p4p_source_dir: str = ""
    output_file: str = ""
    p4p_output_file: str = ""
    new_links_file_path: str = ""
    new_output_file: str = ""
    diagnosis_output_file: str = ""
    volatility_file_path: str = ""
    single_analysis_input_file: str = ""
    single_analysis_output_file: str = ""
    single_analysis_summary_file: str = ""
    new_links_sheet_name: str = "新链接"
    new_links_column_name: str = "新发链接"
    legacy_main_path: str = r"D:\Users\mikey\Desktop\Alibaba运营分析\main.py"
    use_legacy_main: bool = False
    p_value_threshold: float = 0.1
    min_data_points: int = 10
    exposure_thresholds: Dict[str, int] = {
        "大曝光_min": 500, "有曝光_min": 100, "低曝光_min": 20,
        "搜索_大曝光_min": 100, "搜索_有曝光_min": 50, "搜索_低曝光_min": 10,
    }
    click_rate_threshold: float = 0.02
    inquiry_rate_threshold: float = 0.05
    new_product_consecutive_weeks: int = 3
    new_product_focus_exposure: int = 100
    new_product_watch_exposure: int = 50
    daily_read_skiprows: int = 5
    weight_config: Dict[str, float] = {
        "自然曝光": 0.25, "搜索曝光": 0.20, "综合询盘": 0.15,
        "自然询盘": 0.20, "收藏人数": 0.10, "访问人数": 0.08,
    }
    normalize_base: Dict[str, int] = {
        "自然曝光": 1000, "搜索曝光": 500, "综合询盘": 10,
        "自然询盘": 8, "收藏人数": 20, "访问人数": 100,
    }


class ImageNormConfig(BaseModel):
    """图片命名规范化配置"""
    config_file: str = os.path.join(DATA_DIR, "image_norm.json")
    groups: List[str] = []
    main_image_lib: Dict[str, str] = {}
    house_type_forbidden_scenes: Dict[str, List[str]] = {}
    house_type_allowed_scenes: Dict[str, List[str]] = {}
    processed_products_file: str = os.path.join(DATA_DIR, "已处理产品记录.txt")


class AiImageGenConfig(BaseModel):
    """AI 批量生图（Gemini + 豆包策划）— 对应内嵌 ai_image_batch_engine 全部 CONFIG"""
    gemini_api_key: str = ""
    gemini_base_url: str = "https://aigc.dianlichina.com.cn"
    gemini_model: str = "gemini-3.1-flash-image-preview"
    input_root_dir: str = r"D:\桌面\珠宝图批量生成\原图"
    output_root_dir: str = r"D:\桌面\珠宝图批量生成\生成图"
    generations_per_image: int = 6
    aspect_ratio: str = "1:1"
    image_size: str = "1K"
    concurrent_workers: int = 5
    prompt_workers: int = 2
    resize_max_edge: int = 1280
    jpeg_quality: int = 82
    global_gemini_pool: bool = True
    use_stream: bool = False
    max_retries: int = 3
    retry_delay: int = 6
    request_interval: int = 0
    skip_existing: bool = True
    prompt_source_priority: List[str] = Field(default_factory=lambda: ["cache", "doubao", "txt"])
    prompt_templates: List[str] = Field(default_factory=list)
    doubao_planner_prompt: str = ""
    user_requirement: str = ""
    doubao_enabled: bool = True
    doubao_api_key: str = ""
    doubao_model: str = "doubao-seed-2-0-lite-260215"
    doubao_base_url: str = "https://ark.cn-beijing.volces.com/api/v3"
    doubao_use_official_sdk: bool = True
    doubao_ep_file: str = ""
    doubao_probe_on_startup: bool = True
    doubao_probe_strict: bool = False
    doubao_output_language: str = "English"
    cache_prompts: bool = True
    use_cached_prompts: bool = True
    force_refresh: bool = False
    doubao_max_retries: int = 3
    doubao_retry_delay: int = 5
    sku_generations_count: int = 0
    sku_names: List[str] = Field(default_factory=list)


class PointsPricingConfig(BaseModel):
    """功能积分扣费（管理员可在配置中心调整）"""
    title_optimize_per_item: float = Field(default=0.2, ge=0, le=9999)
    traffic_ai_per_run: float = Field(default=0.5, ge=0, le=9999)
    ai_image_1k: float = Field(default=0.6, ge=0, le=9999)
    ai_image_2k: float = Field(default=0.7, ge=0, le=9999)
    ai_image_4k: float = Field(default=0.85, ge=0, le=9999)


class PaymentConfig(BaseModel):
    """支付配置"""
    strict_gateway_mode: bool = False  # 开启后，缺少网关必要参数将拒绝下单
    production_gateway_mode: bool = False  # 开启后，要求具备生产网关参数（证书/密钥）

    admin_username: str = "admin"

    wechat_enabled: bool = False
    alipay_enabled: bool = False

    # 微信
    wechat_mch_id: str = ""
    wechat_app_id: str = ""
    wechat_secret: str = "change-me-wechat"
    wechat_api_v3_key: str = ""
    wechat_serial_no: str = ""
    wechat_private_key_pem: str = ""
    wechat_callback_allowed_ips: List[str] = []

    # 支付宝
    alipay_app_id: str = ""
    alipay_public_key: str = ""
    alipay_private_key: str = ""
    alipay_secret: str = "change-me-alipay"
    alipay_gateway_url: str = "https://openapi.alipay.com/gateway.do"
    alipay_callback_allowed_ips: List[str] = []

    callback_timestamp_tolerance_sec: int = 600
    admin_api_key: str = "change-me-admin"
    admin_console_username: str = "owner"
    admin_console_password: str = "change-me-owner-pass"


def _apply_env_overrides(cfg: "AppConfig") -> None:
    """
    用环境变量覆盖敏感配置（避免把 Key 硬编码进代码或误提交到文件）。
    - DOUBAO_API_KEY: 豆包 API Key
    - ALI_ADMIN_API_KEY: 管理端 API Key（可选）
    """
    doubao_key = os.getenv("DOUBAO_API_KEY", "").strip()
    if doubao_key:
        cfg.data_analysis.doubao_api_key = doubao_key

    gemini_key = os.getenv("GEMINI_API_KEY", "").strip()
    if gemini_key:
        cfg.ai_image_gen.gemini_api_key = gemini_key

    ark_key = os.getenv("ARK_API_KEY", "").strip()
    if ark_key:
        if not cfg.data_analysis.doubao_api_key:
            cfg.data_analysis.doubao_api_key = ark_key
        if not cfg.ai_image_gen.doubao_api_key:
            cfg.ai_image_gen.doubao_api_key = ark_key

    admin_api_key = os.getenv("ALI_ADMIN_API_KEY", "").strip()
    if admin_api_key:
        cfg.payment.admin_api_key = admin_api_key


class AppConfig(BaseModel):
    """应用总配置"""
    paths: PathConfig = PathConfig()
    group_urls: GroupUrlConfig = GroupUrlConfig()
    upload: UploadConfig = UploadConfig()
    schedule: ScheduleConfig = ScheduleConfig()
    keywords: KeywordConfig = KeywordConfig()
    attributes: AttributeConfig = AttributeConfig()
    price: PriceConfig = PriceConfig()
    delivery: DeliveryConfig = DeliveryConfig()
    logistics: LogisticsConfig = LogisticsConfig()
    detail: DetailConfig = DetailConfig()
    data_download: DataDownloadConfig = DataDownloadConfig()
    keyword_download: KeywordDownloadConfig = KeywordDownloadConfig()
    industry_keyword: IndustryKeywordConfig = IndustryKeywordConfig()
    store_overview: StoreOverviewConfig = StoreOverviewConfig()
    data_analysis: DataAnalysisConfig = DataAnalysisConfig()
    image_norm: ImageNormConfig = ImageNormConfig()
    ai_image_gen: AiImageGenConfig = AiImageGenConfig()
    points_pricing: PointsPricingConfig = PointsPricingConfig()
    payment: PaymentConfig = PaymentConfig()
    page_scan: PageScanConfig = PageScanConfig()


def _join_under(root: str, *parts: str) -> str:
    return os.path.normpath(os.path.join(root, *parts))


def _is_explicit_absolute_path(p: str) -> bool:
    """仅把 盘符路径/UNC 视为完整绝对路径；单纯以斜杠开头的不算。"""
    if not p:
        return False
    p = str(p).strip()
    if not p:
        return False
    # Windows: C:\xxx / D:/xxx
    if len(p) >= 2 and p[1] == ":":
        return True
    # UNC: \\server\share\...
    if p.startswith("\\\\"):
        return True
    return False


# 从绝对路径中提取、并挂到项目资料根目录下的已知锚点目录
_PROJECT_PATH_ANCHORS = (
    "Alibaba自动发品",
    "店铺数据",
    "产品上传配置管理",
    "产品分析",
    "数据下载",
    "关键词分析",
    "店铺运营数据",
    "图片生成",
)


def _path_is_under(path: str, root: str) -> bool:
    if not path or not root:
        return False
    try:
        p = os.path.normcase(os.path.normpath(path))
        r = os.path.normcase(os.path.normpath(root))
        return os.path.commonpath([p, r]) == r
    except ValueError:
        return False


def _default_parts_under_root(default_parts: List[str]) -> List[str]:
    """空路径时的默认相对结构（上传类目录统一为 Alibaba自动发品\\data\\...）。"""
    if not default_parts:
        return ["Alibaba自动发品", "data"]
    if default_parts[0] == "产品上传配置管理":
        return ["Alibaba自动发品", "data", *default_parts[1:]]
    return default_parts


def _suffix_from_absolute_path(path: str, default_parts: List[str]) -> Optional[str]:
    """从旧绝对路径提取应挂在项目根下的相对后缀。"""
    norm = os.path.normpath(path)

    m = re.search(r"\.ali-auto-publish[\\/]+data[\\/](.+)$", norm, flags=re.IGNORECASE)
    if m:
        tail = m.group(1).replace("/", os.sep).replace("\\", os.sep)
        return os.path.join("Alibaba自动发品", "data", tail)

    for anchor in _PROJECT_PATH_ANCHORS:
        idx = norm.find(anchor)
        if idx >= 0:
            return norm[idx:]

    if default_parts:
        parts = norm.split(os.sep)
        dp = list(default_parts)
        n = len(dp)
        if len(parts) >= n and parts[-n:] == dp:
            for anchor in _PROJECT_PATH_ANCHORS:
                if anchor in parts:
                    return os.path.join(*parts[parts.index(anchor) :])

        last = dp[-1]
        if last in parts:
            i = parts.index(last)
            for anchor in _PROJECT_PATH_ANCHORS:
                if anchor in parts[:i]:
                    return os.path.join(*parts[parts.index(anchor) :])

    return None


def _resolve_path_under_root(
    root: str,
    current_value: str,
    default_parts: List[str],
    old_root: str = "",
) -> str:
    """
    规则（保存/加载时统一执行）：
    - 所有路径强制落在 project_files_root 下
    - 若原路径在旧根目录下 => 替换盘符前缀
    - 若原路径在根外 => 提取 Alibaba自动发品 / 产品分析 等锚点后的后缀再拼接
    - 相对路径 / 空值 => 拼到根目录下
    - 显式绝对路径且无法映射时 => 保留用户手工输入（不强制回写到根目录）
    """
    new_root = os.path.normpath((root or "").strip() or PROJECT_FILES_ROOT_DEFAULT)
    parts_default = _default_parts_under_root(default_parts)
    raw = str(current_value or "").strip()

    if not raw:
        return _join_under(new_root, *parts_default)

    if not _is_explicit_absolute_path(raw):
        return _join_under(new_root, raw.lstrip("\\/"))

    norm = os.path.normpath(raw)
    old_root_n = os.path.normpath((old_root or "").strip()) if (old_root or "").strip() else ""

    if _path_is_under(norm, new_root):
        return norm

    if old_root_n and _path_is_under(norm, old_root_n):
        rel = os.path.relpath(norm, old_root_n)
        return os.path.normpath(os.path.join(new_root, rel))

    suffix = _suffix_from_absolute_path(norm, default_parts)
    if suffix:
        return os.path.normpath(os.path.join(new_root, suffix))

    # 无法映射到既有锚点时，保留用户手填的绝对路径，避免“保存后被覆盖”
    return norm


def _ensure_dir_for_path(path: str, is_file: bool = False):
    try:
        if not path:
            return
        target = os.path.dirname(path) if is_file else path
        if target:
            os.makedirs(target, exist_ok=True)
    except Exception:
        pass


def _apply_project_root_paths(cfg: AppConfig, old_root: str = ""):
    root = (getattr(cfg.paths, "project_files_root", "") or PROJECT_FILES_ROOT_DEFAULT).strip() or PROJECT_FILES_ROOT_DEFAULT
    cfg.paths.project_files_root = root
    prev_root = (old_root or "").strip()

    cfg.paths.primary_image_dir = _resolve_path_under_root(root, cfg.paths.primary_image_dir, ["产品上传配置管理", "首图"], prev_root)
    cfg.paths.main_image_dir = _resolve_path_under_root(root, cfg.paths.main_image_dir, ["产品上传配置管理", "主图"], prev_root)
    cfg.paths.detail_image_dir = _resolve_path_under_root(root, cfg.paths.detail_image_dir, ["产品上传配置管理", "详情"], prev_root)
    cfg.paths.detail_scene_image_dir = _resolve_path_under_root(root, cfg.paths.detail_scene_image_dir, ["产品上传配置管理", "详情", "场景图"], prev_root)
    cfg.paths.detail_detail_image_dir = _resolve_path_under_root(root, cfg.paths.detail_detail_image_dir, ["产品上传配置管理", "详情", "细节图"], prev_root)
    cfg.paths.detail_company_image_root_dir = _resolve_path_under_root(root, cfg.paths.detail_company_image_root_dir, ["产品上传配置管理", "详情", "公司介绍"], prev_root)
    cfg.paths.detail_company_intro_file = _resolve_path_under_root(root, cfg.paths.detail_company_intro_file, ["产品上传配置管理", "详情", "公司介绍.txt"], prev_root)
    cfg.paths.detail_faq_file = _resolve_path_under_root(root, cfg.paths.detail_faq_file, ["产品上传配置管理", "详情", "FAQs.txt"], prev_root)
    cfg.paths.exceptional_main_image_dir = _resolve_path_under_root(root, cfg.paths.exceptional_main_image_dir, ["产品上传配置管理", "异常主图"], prev_root)
    cfg.paths.download_save_dir = _resolve_path_under_root(root, cfg.paths.download_save_dir, ["数据下载", "下载数据"], prev_root)

    cfg.paths.title_excel_path = _resolve_path_under_root(root, cfg.paths.title_excel_path, ["产品上传配置管理", "标题.xlsx"], prev_root)
    cfg.paths.cookie_file = _resolve_path_under_root(root, cfg.paths.cookie_file, ["产品上传配置管理", "cookies.pkl"], prev_root)
    cfg.paths.name_mapping_file = _resolve_path_under_root(root, cfg.paths.name_mapping_file, ["产品上传配置管理", "图片名称映射.txt"], prev_root)
    cfg.paths.published_products_file = _resolve_path_under_root(root, cfg.paths.published_products_file, ["产品上传配置管理", "已发布产品记录.txt"], prev_root)
    cfg.paths.used_titles_file = _resolve_path_under_root(root, cfg.paths.used_titles_file, ["产品上传配置管理", "标题使用记录.txt"], prev_root)

    cfg.detail.selling_points_excel = _resolve_path_under_root(root, cfg.detail.selling_points_excel, ["产品上传配置管理", "详情", "卖点.xlsx"], prev_root)

    cfg.upload.optimize_output_dir = _resolve_path_under_root(root, cfg.upload.optimize_output_dir, ["产品分析", "产品优化上架结果"], prev_root)

    cfg.data_download.product360_output_dir = _resolve_path_under_root(root, cfg.data_download.product360_output_dir, ["产品分析", "详细分析", "输出根目录"], prev_root)
    cfg.data_download.product360_json_dir = _resolve_path_under_root(root, cfg.data_download.product360_json_dir, ["产品分析", "详细分析", "Json文件"], prev_root)
    cfg.data_download.product360_keyword_json_dir = _resolve_path_under_root(root, cfg.data_download.product360_keyword_json_dir, ["产品分析", "详细分析", "关键词json"], prev_root)
    cfg.data_download.product360_excel_result_dir = _resolve_path_under_root(root, cfg.data_download.product360_excel_result_dir, ["产品分析", "详细分析", "Excel结果"], prev_root)
    cfg.data_download.daily_output_dir = _resolve_path_under_root(root, cfg.data_download.daily_output_dir, ["产品分析", "产品日数据分析"], prev_root)
    cfg.data_download.weekly_output_dir = _resolve_path_under_root(root, cfg.data_download.weekly_output_dir, ["产品分析", "产品周数据分析"], prev_root)
    cfg.data_download.traffic_channel_output_file = _resolve_path_under_root(root, cfg.data_download.traffic_channel_output_file, ["产品分析", "流量渠道", "流量渠道分析.xlsx"], prev_root)
    cfg.data_download.traffic_channel_cookies_file = _resolve_path_under_root(root, cfg.data_download.traffic_channel_cookies_file, ["数据下载", "cookies.pkl"], prev_root)
    cfg.data_download.store_image_save_dir = _resolve_path_under_root(root, cfg.data_download.store_image_save_dir, ["图片生成", "shop_images_by_id"], prev_root)
    cfg.data_download.product_operate_output_file = _resolve_path_under_root(root, cfg.data_download.product_operate_output_file, ["数据下载", "产品运营", "产品运营.xlsx"], prev_root)

    cfg.keyword_download.download_folder = _resolve_path_under_root(root, cfg.keyword_download.download_folder, ["关键词分析", "下载文件夹"], prev_root)
    cfg.keyword_download.output_folder = _resolve_path_under_root(root, cfg.keyword_download.output_folder, ["关键词分析", "输出文件夹"], prev_root)
    cfg.industry_keyword.save_folder = _resolve_path_under_root(root, cfg.industry_keyword.save_folder, ["关键词分析", "行业关键词"], prev_root)
    cfg.industry_keyword.output_file = _resolve_path_under_root(root, cfg.industry_keyword.output_file, ["关键词分析", "行业关键词", "关键词数据总表_宽表版.xlsx"], prev_root)
    cfg.industry_keyword.dropdown_output_file = _resolve_path_under_root(root, cfg.industry_keyword.dropdown_output_file, ["关键词分析", "行业关键词", "下拉词结果.xlsx"], prev_root)

    cfg.store_overview.save_path = _resolve_path_under_root(root, cfg.store_overview.save_path, ["店铺运营数据", "运营数据.xlsx"], prev_root)
    cfg.store_overview.summary_output_path = _resolve_path_under_root(root, cfg.store_overview.summary_output_path, ["店铺运营数据", "运营数据_周汇总.xlsx"], prev_root)
    cfg.store_overview.cookie_file = _resolve_path_under_root(root, cfg.store_overview.cookie_file, ["店铺运营数据", "cookies.pkl"], prev_root)

    cfg.data_analysis.source_dir = _resolve_path_under_root(root, cfg.data_analysis.source_dir, ["产品分析", "产品数据分析"], prev_root)
    cfg.data_analysis.p4p_source_dir = _resolve_path_under_root(root, cfg.data_analysis.p4p_source_dir, ["产品分析", "产品数据分析", "P4P数据"], prev_root)
    cfg.data_analysis.output_file = _resolve_path_under_root(root, cfg.data_analysis.output_file, ["产品分析", "产品数据分析", "统计csss.xlsx"], prev_root)
    cfg.data_analysis.p4p_output_file = _resolve_path_under_root(root, cfg.data_analysis.p4p_output_file, ["产品分析", "产品数据分析", "P4P数据统计.xlsx"], prev_root)
    cfg.data_analysis.new_links_file_path = _resolve_path_under_root(root, cfg.data_analysis.new_links_file_path, ["产品分析", "产品数据分析", "新发链接监控.xlsx"], prev_root)
    cfg.data_analysis.new_output_file = _resolve_path_under_root(root, cfg.data_analysis.new_output_file, ["产品分析", "产品数据分析", "新发链接数据监控.xlsx"], prev_root)
    cfg.data_analysis.diagnosis_output_file = _resolve_path_under_root(root, cfg.data_analysis.diagnosis_output_file, ["产品分析", "产品数据分析", "产品诊断与优化建议.xlsx"], prev_root)
    cfg.data_analysis.volatility_file_path = _resolve_path_under_root(root, cfg.data_analysis.volatility_file_path, ["产品分析", "产品数据分析", "流量波动.xlsx"], prev_root)
    cfg.data_analysis.single_analysis_input_file = _resolve_path_under_root(root, cfg.data_analysis.single_analysis_input_file, ["产品分析", "产品数据分析", "单品分析输入目录"], prev_root)
    cfg.data_analysis.single_analysis_output_file = _resolve_path_under_root(root, cfg.data_analysis.single_analysis_output_file, ["产品分析", "产品数据分析", "单品分析输出目录"], prev_root)
    cfg.data_analysis.single_analysis_summary_file = _resolve_path_under_root(root, cfg.data_analysis.single_analysis_summary_file, ["产品分析", "产品数据分析", "单品分析输出目录", "单品近90天统计.xlsx"], prev_root)
    cfg.data_analysis.title_optimize_result_file = _resolve_path_under_root(root, cfg.data_analysis.title_optimize_result_file, ["产品分析", "产品数据分析", "产品优化建议结果.json"], prev_root)
    cfg.data_analysis.title_optimize_detail_dir = _resolve_path_under_root(root, cfg.data_analysis.title_optimize_detail_dir, ["产品分析", "产品数据分析", "产品优化建议详情"], prev_root)
    cfg.data_analysis.traffic_ai_output_file = _resolve_path_under_root(root, cfg.data_analysis.traffic_ai_output_file, ["产品分析", "店铺整体数据分析", "店铺诊断分析结果.txt"], prev_root)

    for p in [
        cfg.paths.project_files_root,
        cfg.paths.primary_image_dir,
        cfg.paths.main_image_dir,
        cfg.paths.detail_image_dir,
        cfg.paths.detail_scene_image_dir,
        cfg.paths.detail_detail_image_dir,
        cfg.paths.detail_company_image_root_dir,
        cfg.paths.exceptional_main_image_dir,
        cfg.paths.download_save_dir,
        cfg.upload.optimize_output_dir,
        cfg.data_download.product360_output_dir,
        cfg.data_download.product360_json_dir,
        cfg.data_download.product360_keyword_json_dir,
        cfg.data_download.product360_excel_result_dir,
        cfg.data_download.daily_output_dir,
        cfg.data_download.weekly_output_dir,
        os.path.dirname(cfg.data_download.traffic_channel_output_file) if cfg.data_download.traffic_channel_output_file else "",
        cfg.data_download.store_image_save_dir,
        os.path.dirname(cfg.data_download.product_operate_output_file) if cfg.data_download.product_operate_output_file else "",
        cfg.keyword_download.download_folder,
        cfg.keyword_download.output_folder,
        cfg.industry_keyword.save_folder,
        cfg.data_analysis.source_dir,
        cfg.data_analysis.p4p_source_dir,
        cfg.data_analysis.single_analysis_input_file,
        cfg.data_analysis.single_analysis_output_file,
        cfg.data_analysis.title_optimize_detail_dir,
    ]:
        _ensure_dir_for_path(p, is_file=False)

    for p in [
        cfg.paths.title_excel_path,
        cfg.paths.cookie_file,
        cfg.paths.name_mapping_file,
        cfg.paths.published_products_file,
        cfg.paths.used_titles_file,
        cfg.paths.detail_company_intro_file,
        cfg.paths.detail_faq_file,
        cfg.detail.selling_points_excel,
        cfg.store_overview.save_path,
        cfg.store_overview.summary_output_path,
        cfg.store_overview.cookie_file,
        cfg.data_download.traffic_channel_output_file,
        cfg.data_download.traffic_channel_cookies_file,
        cfg.data_download.product_operate_output_file,
        cfg.data_analysis.output_file,
        cfg.data_analysis.p4p_output_file,
        cfg.data_analysis.new_links_file_path,
        cfg.data_analysis.new_output_file,
        cfg.data_analysis.diagnosis_output_file,
        cfg.data_analysis.volatility_file_path,
        cfg.data_analysis.single_analysis_summary_file,
        cfg.data_analysis.title_optimize_result_file,
        cfg.data_analysis.traffic_ai_output_file,
        cfg.industry_keyword.output_file,
    ]:
        _ensure_dir_for_path(p, is_file=True)


# ===================== 配置管理器（线程安全单例） =====================

class ConfigManager:
    """配置管理器 - 加载/保存/更新配置"""
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._config = None
            return cls._instance

    @property
    def config(self) -> AppConfig:
        if self._config is None:
            self.load()
        return self._config

    def load(self) -> AppConfig:
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8-sig") as f:
                    data = json.load(f)
                old_root = str((data.get("paths") or {}).get("project_files_root") or "")
                self._config = AppConfig(**data)
                _apply_project_root_paths(self._config, old_root=old_root)
                _apply_env_overrides(self._config)
            except Exception as e:
                # 1. 备份损坏的文件，防止数据彻底丢失
                backup_file = f"{CONFIG_FILE}.{int(time.time())}.bak"
                try:
                    shutil.copy2(CONFIG_FILE, backup_file)
                    print(f"配置文件解析失败，已备份至: {backup_file}, 错误: {e}")
                except Exception:
                    pass
                
                # 2. 生成默认配置
                self._config = self._load_defaults()
                self.save()
        else:
            self._config = self._load_defaults()
            self.save()
        return self._config

    def save(self):
        """保存当前配置到 JSON 文件"""
        if self._config is None:
            return
        _apply_project_root_paths(self._config)
        with open(CONFIG_FILE, "w", encoding="utf-8", newline="\n") as f:
            json.dump(self._config.model_dump(), f, ensure_ascii=False, indent=2)
            f.write("\n")

    def reload_from_disk(self) -> AppConfig:
        """强制从磁盘重新加载（其他客户端保存后同步用）。"""
        self._config = None
        return self.load()

    def update(self, section: str, data: Dict[str, Any]) -> AppConfig:
        """更新指定配置段"""
        cfg = self.config
        old_root = ""
        if section == "paths" or (isinstance(data, dict) and "project_files_root" in data):
            old_root = str(cfg.paths.project_files_root or "")
        if hasattr(cfg, section):
            current = getattr(cfg, section)
            updated = current.model_copy(update=data)
            setattr(cfg, section, updated)
            if old_root or section == "paths":
                _apply_project_root_paths(cfg, old_root=old_root)
            self.save()
        return cfg

    def update_full(self, data: Dict[str, Any]) -> AppConfig:
        """全量更新配置"""
        old_root = str(self._config.paths.project_files_root or "") if self._config else ""
        self._config = AppConfig(**data)
        _apply_project_root_paths(self._config, old_root=old_root)
        self.save()
        return self._config

    def get_section(self, section: str) -> Optional[BaseModel]:
        """获取指定配置段"""
        cfg = self.config
        return getattr(cfg, section, None)

    def _load_defaults(self) -> AppConfig:
        """加载默认配置（含原 config.py 的属性数据）"""
        cfg = AppConfig()
        # 从原 config.py 迁移默认属性配置
        cfg.attributes.all_attributes = {
            "工程解决方案能力": AttributeItemConfig(
                container_id="struct-p-230257561",
                values=["total solution for projects", "Cross Categories Consolidation",
                         "3D model design", "graphic design", "Others"],
                input_id="icbuCatProp", type="required", select_type="tag"
            ),
            "特性": AttributeItemConfig(
                container_id="struct-p-191284141",
                values=["wind resistance", "earthquake-resistant",
                         "High resistance to deformation", "Long service life",
                         "Environmental friendly", "Low cost", "Easy to maintain",
                         "Modular", "standardization", "Sturdy structure", "Easy to set up."],
                input_id="icbuCatProp", type="required", select_type="tag"
            ),
            "厚度": AttributeItemConfig(
                container_id="struct-p-256166240",
                values=["50mm", "50/75mm"],
                input_id="icbuCatProp", type="required", select_type="tag"
            ),
            "售后服务": AttributeItemConfig(
                container_id="struct-p-200009644",
                values=["Online Technical Support", "Warranty Service",
                         "Renovate the interior layout", "Parts supply and replacement"],
                input_id="icbuCatProp", type="required", select_type="tag"
            ),
            "应用场景": AttributeItemConfig(
                container_id="struct-p-234916993",
                values=["Hotel", "House", "Kiosk", "Booth", "office", "Sentry Box",
                         "Guard House", "shop", "Toilet", "Villa", "Warehouse",
                         "storage room", "Workshop", "Plant", "Farms", "Apartments",
                         "office Bulldlngs", "Bar", "Restaurant", "Dormitory", "Carport",
                         "Park", "Scenic Area", "Farmhouse", "Courtyard", "Kitchen",
                         "Bathroom", "Home Office", "Living Room", "Bedroom", "Dining",
                         "Babies and Kids", "Outdoor", "Storage and Closet", "Gym",
                         "Laundry", "garage", "Construction site", "Hospital", "School",
                         "Apartment", "Leisure Facilities", "Supermarket", "Sports Venues",
                         "living container house", "Mall", "container home",
                         "Temporary housing", "Camping Base", "snack bar", "coffee shop"],
                input_id="icbuCatProp", type="required", select_type="tag"
            ),
            "原产地": AttributeItemConfig(
                container_id="struct-p-1", values=["China"],
                input_id=None, type="required", select_type="single_search"
            ),
            "产品类型": AttributeItemConfig(
                container_id="struct-p-210188459",
                values=["Greenhouse", "Steel Structure", "container house",
                         "container structure", "Expandable Container",
                         "Flat Pack Container", "Folding Container",
                         "Detachable Container", "Standard insulated type",
                         "High insulation type"],
                input_id=None, type="required", select_type="single_search"
            ),
            "省份": AttributeItemConfig(
                container_id="struct-p-1-1", values=["Zhejiang"],
                input_id=None, type="optional", select_type="single_search"
            ),
            "型号": AttributeItemConfig(
                container_id="struct-p-3",
                values=["Container-House-A1", "Prefabricated-B2", "Modular-C3", "Expandable-D4", "Flatpack-E5"],
                input_id="icbuCatProp", type="optional", select_type="input"
            ),
            "品种": AttributeItemConfig(
                container_id="struct-p-100004171",
                values=["Container House", "Modular Container", "40FT", "20FT"],
                input_id="icbuCatProp", type="optional", select_type="input"
            ),
            "形状": AttributeItemConfig(
                container_id="struct-p-191288241",
                values=["Square", "Rectangular"],
                input_id="icbuCatProp", type="optional", select_type="tag"
            ),
            "质保服务": AttributeItemConfig(
                container_id="struct-p-100008447", values=["1 Year"],
                input_id=None, type="optional", select_type="single_search"
            ),
            "品牌": AttributeItemConfig(
                container_id="struct-p-2", values=["DBJ"],
                input_id="icbuCatProp", type="optional", select_type="input"
            ),
            "使用": AttributeItemConfig(
                container_id="struct-p-100004185",
                values=["Hotel", "House", "Kiosk", "Booth", "office", "Sentry Box",
                         "Guard House", "shop", "Toilet", "Villa", "Warehouse",
                         "storage room", "Workshop", "Plant", "Farms", "Apartments",
                         "office Buildings", "Bar", "Restaurant", "Dormitory", "Carport",
                         "Park", "Scenic Area", "Farmhouse", "Courtyard", "Kitchen",
                         "Bathroom", "Home Office", "Living Room", "Bedroom", "Dining",
                         "Babies and Kids", "Outdoor", "Storage and Closet", "Gym",
                         "Laundry", "garage", "Construction site", "Hospital", "School",
                         "Apartment", "Leisure Facilities", "Supermarket", "Sports Venues",
                         "living container house", "Mall", "container home",
                         "Temporary housing", "Camping Base", "snack bar", "coffee shop"],
                input_id=None, type="optional", select_type="input"
            ),
            "设计风格": AttributeItemConfig(
                container_id="struct-p-235983983",
                values=["Farmhouse", "Midcentury Modern", "Mediterranean",
                         "Southeast Asia", "Postmodern", "Craftsman", "Contemporary",
                         "Victorian", "Japanese", "Southwestern", "Industrial",
                         "European", "Modern", "Scandinavian", "Coastal", "Rustic",
                         "Tiffany", "Eclectic", "Transitional", "Midcentury", "Asian",
                         "Minimalist", "Traditional", "Chinese", "French", "Tropical"],
                input_id=None, type="optional", select_type="auto_complete"
            ),
        }
        cfg.attributes.count_rule = {
            "工程解决方案能力": 1, "特性": 3, "厚度": 1, "售后服务": 1,
            "应用场景": 5, "产品类型": 1, "型号": 1, "品种": 1, "形状": 1,
            "使用": 5, "设计风格": 1, "品牌": 1,
        }
        cfg.attributes.specifications = {
            "材质": SpecificationItemConfig(
                container_id="p-191284014",
                values_pool=["Container", "Sandwich Panel"],
                max_select=2
            ),
            "尺寸": SpecificationItemConfig(
                container_id="p-191284006",
                values_pool=["20ft", "40 ft"],
                max_select=2
            ),
        }
        cfg.attributes.diff_compare_attrs = [
            "材质", "尺寸", "特性", "厚度", "售后服务", "应用场景",
            "产品类型", "品种", "形状", "使用", "设计风格", "品牌"
        ]
        return cfg


# 全局配置管理器实例
config_manager = ConfigManager()


def get_config() -> AppConfig:
    """获取当前配置（快捷方式）"""
    return config_manager.config

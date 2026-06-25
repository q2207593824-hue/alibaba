# -*- coding: utf-8 -*-
"""
配置管理 API
对应前端: ProductConfig 页面
"""
from typing import Any, Dict, Optional
import os
import time
import asyncio
import json
import pickle
import requests
from fastapi import APIRouter, Body, HTTPException, Depends, Header
from fastapi.concurrency import run_in_threadpool
from app.core.membership_guard import require_membership_or_trial
from pydantic import BaseModel

from app.core.settings import config_manager, get_config, CONFIG_FILE
from app.core.admin_runtime_config import (
    build_admin_runtime_payload,
    get_config_revision,
    mask_full_config_dump,
    merge_admin_runtime_on_save,
    merge_payment_on_save,
)
from app.core.logger import logger
from app.services.automation.browser_manager import BrowserManager
from app.services.membership_service import (
    _uid_by_token,
    init_db,
    _conn,
    _hash_pwd,
    _new_invite_code,
    _now_str,
    CLOUD_MEMBERSHIP_API_BASE,
    CLOUD_MEMBERSHIP_ME_URL,
)

router = APIRouter(dependencies=[Depends(require_membership_or_trial)])


class ConfigUpdateRequest(BaseModel):
    """配置更新请求"""
    section: str
    data: Dict[str, Any]


class FullConfigUpdateRequest(BaseModel):
    """全量配置更新请求"""
    config: Dict[str, Any]


class SaveCookieFromDesktopReq(BaseModel):
    cookies: list[Dict[str, Any]]
    source_url: str = ""


def _admin_full_access(x_admin_key: Optional[str] = None) -> bool:
    from app.services.membership_service import verify_admin_api_key

    return verify_admin_api_key(x_admin_key)


def _config_read_full_access(
    authorization: Optional[str] = None,
    x_admin_key: Optional[str] = None,
) -> bool:
    """暂不对已登录会员脱敏运行时 API Key（先保证全客户端可用）。"""
    from app.services.membership_service import verify_admin_api_key

    if verify_admin_api_key(x_admin_key):
        return True
    token = _bearer_from_header(authorization)
    if not token:
        return False
    try:
        from app.services.membership_service import me

        me(token)
        return True
    except Exception:
        pass
    try:
        from app.services.membership_service import _uid_by_token

        return int(_uid_by_token(token)) == 1
    except ValueError:
        return False


_config_disk_mtime: float = 0.0


def _reload_config_if_changed() -> None:
    global _config_disk_mtime
    try:
        mtime = float(os.path.getmtime(CONFIG_FILE))
    except Exception:
        return
    if mtime != _config_disk_mtime:
        config_manager.reload_from_disk()
        _config_disk_mtime = mtime


@router.get("/revision")
async def get_config_revision_api():
    """配置 revision（mtime），用于多客户端检测变更。"""
    _reload_config_if_changed()
    rev = get_config_revision()
    return {"success": True, "data": {"revision": rev}}


@router.get("/admin-runtime")
async def get_admin_runtime_config(
    authorization: Optional[str] = Header(default=None),
    x_admin_key: Optional[str] = Header(default=None, alias="X-Admin-Key"),
):
    """管理员运行时配置（API Key / 模型等），供各客户端同步。"""
    _reload_config_if_changed()
    payload = build_admin_runtime_payload(
        full_access=_config_read_full_access(authorization, x_admin_key),
    )
    return {"success": True, "data": payload}


@router.get("")
@router.get("/")
async def get_all_config(
    authorization: Optional[str] = Header(default=None),
    x_admin_key: Optional[str] = Header(default=None, alias="X-Admin-Key"),
):
    """获取全部配置（非管理员脱敏 API Key 等敏感字段）。"""
    _reload_config_if_changed()
    cfg = get_config()
    data = mask_full_config_dump(
        cfg.model_dump(),
        full_access=_config_read_full_access(authorization, x_admin_key),
    )
    data["_meta"] = {"revision": get_config_revision()}
    return {"success": True, "data": data}


@router.put("")
@router.put("/")
async def update_full_config(
    body: Dict[str, Any] = Body(...),
    x_admin_key: Optional[str] = Header(default=None, alias="X-Admin-Key"),
    _=Depends(require_membership_or_trial),
):
    """全量更新配置（兼容前端直接提交 config 对象）"""
    try:
        # 兼容两种格式：
        # 1) {"config": {...}}  (旧/严格格式)
        # 2) {...}             (前端直接提交整份配置)
        if "config" in body and isinstance(body["config"], dict):
            data = body["config"]
        else:
            data = body

        if not isinstance(data, dict) or not data:
            raise ValueError("请求体不能为空")

        data = {k: v for k, v in data.items() if k != "_meta"}
        for section in ("data_analysis", "ai_image_gen", "paths", "payment"):
            sec = data.get(section)
            if isinstance(sec, dict) and "_meta" in sec:
                data[section] = {k: v for k, v in sec.items() if k != "_meta"}

        full_access = _admin_full_access(x_admin_key)
        data = merge_admin_runtime_on_save(data, full_access=full_access, section="data_analysis")
        data = merge_admin_runtime_on_save(data, full_access=full_access, section="ai_image_gen")
        data = merge_payment_on_save(data, full_access=full_access)

        cfg = config_manager.update_full(data)
        out = mask_full_config_dump(cfg.model_dump(), full_access=full_access)
        out["_meta"] = {"revision": get_config_revision()}
        if full_access:
            try:
                from app.services.cloud_admin_runtime_service import save_cloud_admin_runtime

                save_cloud_admin_runtime(
                    data_analysis=(data.get("data_analysis") if isinstance(data.get("data_analysis"), dict) else None),
                    ai_image_gen=(data.get("ai_image_gen") if isinstance(data.get("ai_image_gen"), dict) else None),
                    points_pricing=(data.get("points_pricing") if isinstance(data.get("points_pricing"), dict) else None),
                    merge=True,
                )
            except Exception as local_err:
                logger.warning("save local admin runtime config failed: %s", local_err)
            try:
                from app.services.admin_runtime_cloud_sync import push_local_admin_runtime_to_cloud

                push_local_admin_runtime_to_cloud(admin_key=str(x_admin_key or ""))
            except Exception as push_err:
                logger.warning("push admin runtime config to cloud failed: %s", push_err)
        return {"success": True, "data": out}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


def _bearer_from_header(authorization: Optional[str]) -> str:
    v = str(authorization or "").strip()
    if v.lower().startswith("bearer "):
        return v[7:].strip()
    return v


@router.get("/cloud-admin-revision")
async def get_cloud_admin_revision(
    authorization: Optional[str] = Header(default=None),
    x_admin_key: Optional[str] = Header(default=None, alias="X-Admin-Key"),
    _=Depends(require_membership_or_trial),
):
    """云端管理员配置 revision（供各客户端轮询是否变更）。"""
    from app.services.admin_runtime_cloud_sync import fetch_cloud_admin_runtime_revision
    from app.services.membership_service import _membership_cloud_sync_enabled

    if not _membership_cloud_sync_enabled():
        return {"success": True, "data": {"revision": get_config_revision(), "source": "local"}}
    try:
        rev = fetch_cloud_admin_runtime_revision(
            bearer=_bearer_from_header(authorization),
            admin_key=str(x_admin_key or ""),
        )
        return {"success": True, "data": {"revision": rev, "source": "cloud"}}
    except Exception as e:
        return {
            "success": True,
            "data": {"revision": 0, "source": "unavailable", "error": str(e)},
        }


@router.post("/pull-cloud-admin-runtime")
async def pull_cloud_admin_runtime(
    authorization: Optional[str] = Header(default=None),
    x_admin_key: Optional[str] = Header(default=None, alias="X-Admin-Key"),
    _=Depends(require_membership_or_trial),
):
    """从云端拉取管理员配置并写入本机 config.json。"""
    from app.services.admin_runtime_cloud_sync import (
        ensure_runtime_secrets_ready_detail,
        pull_cloud_admin_runtime_to_local,
        runtime_secrets_unavailable_message,
    )

    try:
        bearer = _bearer_from_header(authorization)
        data = pull_cloud_admin_runtime_to_local(
            bearer=bearer,
            admin_key=str(x_admin_key or ""),
        )
        if not data.get("secrets_ready"):
            ready, reason = ensure_runtime_secrets_ready_detail(
                bearer=bearer,
                admin_key=str(x_admin_key or ""),
                skip_pull=True,
            )
            data["secrets_ready"] = ready
            if not ready:
                data["secrets_message"] = runtime_secrets_unavailable_message(reason)
        if data.get("secrets_ready"):
            from app.services.admin_runtime_cloud_sync import _clear_stale_analysis_failures_if_ready

            data["cleared_stale_tasks"] = _clear_stale_analysis_failures_if_ready(True)
        return {"success": True, "data": data}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/ensure-runtime-secrets")
async def ensure_runtime_secrets(
    authorization: Optional[str] = Header(default=None),
    x_admin_key: Optional[str] = Header(default=None, alias="X-Admin-Key"),
    _=Depends(require_membership_or_trial),
):
    """
    会员/管理员：启动 AI 功能前由本机后端从总部云端同步 API Key（不返回 Key 明文给浏览器）。
    """
    from app.services.admin_runtime_cloud_sync import (
        ensure_runtime_secrets_ready_detail,
        runtime_secrets_unavailable_message,
    )

    bearer = _bearer_from_header(authorization)
    ready, reason = ensure_runtime_secrets_ready_detail(
        bearer=bearer,
        admin_key=str(x_admin_key or ""),
    )
    return {
        "success": True,
        "data": {
            "secrets_ready": ready,
            "message": "API 配置已就绪" if ready else runtime_secrets_unavailable_message(reason),
            "reason": reason if not ready else "",
        },
    }


@router.get("/template")
async def get_config_template():
    """获取默认配置模板（不落盘）"""
    try:
        default_cfg = config_manager._load_defaults()  # type: ignore[attr-defined]
        return {"success": True, "data": default_cfg.model_dump()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/reset")
async def reset_config_to_defaults(_=Depends(require_membership_or_trial)):
    """重置为默认配置（会落盘保存）"""
    try:
        default_cfg = config_manager._load_defaults()  # type: ignore[attr-defined]
        config_manager.update_full(default_cfg.model_dump())
        return {"success": True, "data": config_manager.config.model_dump()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/reload")
async def reload_config(_=Depends(require_membership_or_trial)):
    """重新加载配置文件"""
    try:
        cfg = config_manager.load()
        return {"success": True, "data": cfg.model_dump()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/section/{section}")
async def get_config_section(
    section: str,
    authorization: Optional[str] = Header(default=None),
    x_admin_key: Optional[str] = Header(default=None, alias="X-Admin-Key"),
):
    """获取指定配置段（敏感段对非管理员脱敏）。"""
    result = config_manager.get_section(section)
    if result is None:
        raise HTTPException(status_code=404, detail=f"配置段 '{section}' 不存在")
    data = result.model_dump()
    if section in ("data_analysis", "ai_image_gen", "payment"):
        data = mask_full_config_dump(
            {section: data},
            full_access=_config_read_full_access(authorization, x_admin_key),
        ).get(section, data)
    return {"success": True, "data": data}


@router.put("/section/{section}")
async def update_config_section(
    section: str,
    body: Dict[str, Any],
    authorization: Optional[str] = Header(default=None),
    x_admin_key: Optional[str] = Header(default=None, alias="X-Admin-Key"),
    _=Depends(require_membership_or_trial),
):
    """更新指定配置段（与全量保存相同的 admin-runtime / payment 合并保护）。"""
    try:
        full_access = _admin_full_access(x_admin_key)
        cfg = get_config()
        data = cfg.model_dump()
        data[section] = {**(data.get(section) or {}), **body}
        if section == "data_analysis":
            data = merge_admin_runtime_on_save(data, full_access=full_access, section="data_analysis")
        elif section == "ai_image_gen":
            data = merge_admin_runtime_on_save(data, full_access=full_access, section="ai_image_gen")
        elif section == "payment":
            data = merge_payment_on_save(data, full_access=full_access)
        cfg = config_manager.update_full(data)
        read_access = _config_read_full_access(authorization, x_admin_key)
        saved = cfg.model_dump()
        out = mask_full_config_dump(saved, full_access=read_access)
        if full_access and section in ("data_analysis", "ai_image_gen", "points_pricing"):
            try:
                from app.services.cloud_admin_runtime_service import save_cloud_admin_runtime

                save_cloud_admin_runtime(
                    data_analysis=(saved.get("data_analysis") if section == "data_analysis" else None),
                    ai_image_gen=(saved.get("ai_image_gen") if section == "ai_image_gen" else None),
                    points_pricing=(saved.get("points_pricing") if section == "points_pricing" else None),
                    merge=True,
                )
            except Exception as local_err:
                logger.warning("save local admin runtime config failed: %s", local_err)
            try:
                from app.services.admin_runtime_cloud_sync import push_local_admin_runtime_to_cloud

                push_local_admin_runtime_to_cloud(admin_key=str(x_admin_key or ""))
            except Exception as push_err:
                logger.warning("push admin runtime config to cloud failed: %s", push_err)
        return {"success": True, "data": out}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


# ===================== 属性管理子路由 =====================

@router.get("/attributes/list")
async def list_attributes():
    """获取所有属性配置"""
    cfg = get_config()
    return {
        "success": True,
        "data": {
            "all_attributes": {k: v.model_dump() for k, v in cfg.attributes.all_attributes.items()},
            "count_rule": cfg.attributes.count_rule,
            "specifications": {k: v.model_dump() for k, v in cfg.attributes.specifications.items()},
            "specifications_by_group": {
                g: {k: v.model_dump() for k, v in (items or {}).items()}
                for g, items in (cfg.attributes.specifications_by_group or {}).items()
            },
            "specifications_by_category_id": {
                cat_id: {k: v.model_dump() for k, v in (items or {}).items()}
                for cat_id, items in (cfg.attributes.specifications_by_category_id or {}).items()
            },
            "specification_group_alias": cfg.attributes.specification_group_alias,
            "target_attrs": cfg.attributes.target_attrs,
            "skip_attrs": cfg.attributes.skip_attrs,
            "diff_compare_attrs": cfg.attributes.diff_compare_attrs,
        }
    }


@router.put("/attributes/{attr_name}")
async def update_attribute(attr_name: str, body: Dict[str, Any], _=Depends(require_membership_or_trial)):
    """更新单个属性配置"""
    from app.core.settings import AttributeItemConfig
    cfg = get_config()
    try:
        attr_config = AttributeItemConfig(**body)
        cfg.attributes.all_attributes[attr_name] = attr_config
        config_manager.save()
        return {"success": True, "message": f"属性 '{attr_name}' 已更新"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/attributes/{attr_name}")
async def delete_attribute(attr_name: str, _=Depends(require_membership_or_trial)):
    """删除单个属性配置"""
    cfg = get_config()
    if attr_name in cfg.attributes.all_attributes:
        del cfg.attributes.all_attributes[attr_name]
        cfg.attributes.count_rule.pop(attr_name, None)
        config_manager.save()
        return {"success": True, "message": f"属性 '{attr_name}' 已删除"}
    raise HTTPException(status_code=404, detail=f"属性 '{attr_name}' 不存在")


@router.post("/attributes/fetch-from-platform")
async def fetch_attributes_from_platform(_=Depends(require_membership_or_trial)):
    """从平台URL配置抓取属性并合并到属性配置"""
    from app.core.settings import AttributeItemConfig

    cfg = get_config()
    target_urls = [str(cfg.group_urls.default_posting_url or "").strip()]
    target_urls += [str(v or "").strip() for v in (cfg.group_urls.group_url_map or {}).values()]
    target_urls = [u for u in target_urls if u]

    logger.info(f"[属性抓取] 开始执行，URL数量={len(target_urls)}")
    for i, u in enumerate(target_urls, start=1):
        logger.info(f"[属性抓取] URL{i}: {u}")

    if not target_urls:
        raise HTTPException(status_code=400, detail="未配置可用的平台URL")

    cookie_file = str(cfg.paths.cookie_file or "").strip()
    logger.info(f"[属性抓取] Cookie文件: {cookie_file}")
    if not cookie_file or not os.path.exists(cookie_file):
        raise HTTPException(status_code=400, detail="Cookie文件不存在，请先在Cookie管理中配置并登录")

    try:
        from selenium import webdriver
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC
        from selenium.webdriver.chrome.options import Options
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Selenium环境不可用: {e}")

    browser = None
    grabbed: Dict[str, Dict[str, Any]] = {}

    try:
        options = Options()
        options.add_argument("--start-maximized")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        browser = webdriver.Chrome(service=BrowserManager._build_chrome_service(), options=options)
        logger.info("[属性抓取] 浏览器启动成功")

        # cookie登录
        browser.get("https://www.alibaba.com/")
        with open(cookie_file, "rb") as f:
            cookies = pickle.load(f)
        logger.info(f"[属性抓取] 读取Cookie数量={len(cookies or [])}")
        for c in (cookies or []):
            try:
                browser.add_cookie(c)
            except Exception:
                pass
        browser.refresh()
        await asyncio.sleep(1.2)
        logger.info("[属性抓取] Cookie注入完成")

        for idx, url in enumerate(target_urls, start=1):
            logger.info(f"[属性抓取] 正在访问({idx}/{len(target_urls)}): {url}")
            browser.get(url)
            cur = str(browser.current_url or "")
            logger.info(f"[属性抓取] 当前页面: {cur}")
            if "login.alibaba.com" in cur:
                logger.error("[属性抓取] 检测到登录页，Cookie失效")
                raise HTTPException(status_code=400, detail="Cookie已失效，请先在Cookie管理重新登录")

            main_container = WebDriverWait(browser, 20).until(
                EC.presence_of_element_located((By.ID, "struct-icbuCatProp"))
            )
            items = main_container.find_elements(By.CSS_SELECTOR, "div[id^='struct-p-']")
            logger.info(f"[属性抓取] URL#{idx} 识别到属性容器数量={len(items)}")

            got_this_url = 0
            for i, container in enumerate(items):
                try:
                    container_id = str(container.get_attribute("id") or "").strip()
                    if not container_id:
                        continue

                    attr_name = f"属性_{i+1}"
                    try:
                        label_el = container.find_element(By.CLASS_NAME, "label")
                        label_text = str(label_el.text or "").strip()
                        if label_text:
                            attr_name = label_text
                    except Exception:
                        pass

                    is_required = ("required" in str(container.get_attribute("class") or "")) or (len(container.find_elements(By.CLASS_NAME, "required")) > 0)

                    grabbed[attr_name] = {
                        "container_id": container_id,
                        "input_id": "",
                        "type": "required" if is_required else "optional",
                        "select_type": "input",
                    }
                    got_this_url += 1
                    logger.info(f"[属性抓取] + 属性: {attr_name} | {container_id} | {'required' if is_required else 'optional'}")
                except Exception as e:
                    logger.warning(f"[属性抓取] 跳过属性容器#{i+1}: {e}")
                    continue

            logger.info(f"[属性抓取] URL#{idx} 有效抓取属性数={got_this_url}")

        all_attrs = dict(cfg.attributes.all_attributes or {})
        before_total = len(all_attrs)
        add_count = 0
        skip_existing_count = 0

        for name, item in grabbed.items():
            existing = all_attrs.get(name)
            if existing is not None:
                skip_existing_count += 1
                logger.info(f"[属性抓取] 跳过已存在属性: {name}")
                continue

            all_attrs[name] = AttributeItemConfig(
                container_id=item.get("container_id", ""),
                values=[],
                input_id=item.get("input_id", ""),
                type=item.get("type", "required"),
                select_type=item.get("select_type", "input"),
            )
            add_count += 1

        cfg.attributes.all_attributes = all_attrs
        config_manager.save()

        logger.info(
            f"[属性抓取] 完成: 抓取={len(grabbed)} 新增={add_count} 跳过已存在={skip_existing_count} 总数(前->后)={before_total}->{len(all_attrs)}"
        )

        return {
            "success": True,
            "data": {
                "target_url_count": len(target_urls),
                "fetched_count": len(grabbed),
                "added_count": add_count,
                "skipped_existing_count": skip_existing_count,
                "attribute_total": len(all_attrs),
            },
            "message": "属性抓取完成并已写入配置（增量）",
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"抓取属性失败: {e}")
    finally:
        try:
            if browser:
                browser.quit()
        except Exception:
            pass


@router.post("/specifications/fetch-from-platform")
async def fetch_specifications_from_platform(_=Depends(require_membership_or_trial)):
    """从平台URL配置抓取商品规格并合并到规格配置"""
    from app.core.settings import SpecificationItemConfig

    cfg = get_config()
    group_url_map = cfg.group_urls.group_url_map or {}
    target_urls = {str(k or "").strip(): str(v or "").strip() for k, v in group_url_map.items()}
    target_urls = {k: v for k, v in target_urls.items() if k and v}

    logger.info(f"[规格抓取] 开始执行，URL数量={len(target_urls)}")
    for name, u in target_urls.items():
        logger.info(f"[规格抓取] 目标类目: {name} | URL: {u}")

    if not target_urls:
        raise HTTPException(status_code=400, detail="未配置分组发品链接，无法抓取规格")

    cookie_file = str(cfg.paths.cookie_file or "").strip()
    logger.info(f"[规格抓取] Cookie文件: {cookie_file}")
    if not cookie_file or not os.path.exists(cookie_file):
        raise HTTPException(status_code=400, detail="Cookie文件不存在，请先在Cookie管理中配置并登录")

    try:
        from selenium import webdriver
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC
        from selenium.webdriver.chrome.options import Options
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Selenium环境不可用: {e}")

    browser = None
    grabbed_specs_by_group: Dict[str, Dict[str, Dict[str, Any]]] = {}
    group_category_id_map: Dict[str, str] = {}
    scanned_blocks = 0

    def _norm_label(s: str) -> str:
        txt = str(s or "").strip()
        txt = txt.replace("*", "").strip()
        txt = txt.replace("\n", " ").strip()
        return txt

    def _norm_spec_key(s: str) -> str:
        import re as _re
        return _re.sub(r"[\s\-_]+", "", str(s or "").strip()).lower()

    def _clean_spec_title(raw: str) -> str:
        title = _norm_label(str(raw or "").split("\n")[0])
        for noise in ("添加规格图", "支持传图", "Add specification image"):
            title = title.replace(noise, "").strip()
        return title

    def _match_sale_attr(title: str, meta_map: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
        if title in meta_map:
            return meta_map[title]
        target = _norm_spec_key(title)
        for key, meta in meta_map.items():
            if _norm_spec_key(key) == target:
                return meta
        return {}

    def _detect_spec_interaction(block) -> str:
        """按页面结构判断规格交互类型（适配不同行业）。"""
        checkbox_labels = block.find_elements(
            By.CSS_SELECTOR,
            ".sell-sequential-combobox .next-checkbox-label, .sell-sequential-combocheckbox .next-checkbox-label",
        )
        checkbox_count = len(
            [
                lb
                for lb in checkbox_labels
                if _norm_label(getattr(lb, "text", "") or "")
                and "添加" not in str(getattr(lb, "text", "") or "")
            ]
        )
        if checkbox_count >= 2:
            return "checkbox_grid"

        generic_cbs = block.find_elements(By.CSS_SELECTOR, ".next-checkbox-wrapper input[type='checkbox']")
        if len(generic_cbs) >= 2:
            return "checkbox_grid"

        has_color_input = bool(
            block.find_elements(
                By.CSS_SELECTOR,
                "input[role='colorCombobox'], .posting-field-color, .new-posting-field-color",
            )
        )
        if has_color_input:
            return "value_rows"
        return "checkbox_grid"

    def _default_image_subdir(title: str) -> str:
        if title in ("颜色", "Color"):
            return "SKU"
        if title in ("样式", "Style"):
            return "样式"
        return title or "SKU"

    def _extract_cat_id_from_url(url: str) -> str:
        text = str(url or "").strip()
        if not text:
            return ""
        import re as _re
        m = _re.search(r"(?:catId|catid|categoryId|leafCatId)=(\d+)", text, flags=_re.IGNORECASE)
        return m.group(1) if m else ""

    def _extract_cat_id_from_page(browser_obj) -> str:
        try:
            cur = str(browser_obj.current_url or "").strip()
        except Exception:
            cur = ""
        cat_id = _extract_cat_id_from_url(cur)
        if cat_id:
            return cat_id
        try:
            html = str(browser_obj.page_source or "")
        except Exception:
            html = ""
        if html:
            import re as _re
            m = _re.search(r'"(?:catId|categoryId|leafCatId)"\s*:\s*"?(\d+)"?', html)
            if m:
                return m.group(1)
        return ""

    try:
        options = Options()
        options.add_argument("--start-maximized")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        browser = webdriver.Chrome(service=BrowserManager._build_chrome_service(), options=options)
        logger.info("[规格抓取] 浏览器启动成功")

        # cookie登录
        browser.get("https://www.alibaba.com/")
        with open(cookie_file, "rb") as f:
            cookies = pickle.load(f)
        logger.info(f"[规格抓取] 读取Cookie数量={len(cookies or [])}")
        for c in (cookies or []):
            try:
                browser.add_cookie(c)
            except Exception:
                pass
        browser.refresh()
        await asyncio.sleep(1.2)
        logger.info("[规格抓取] Cookie注入完成")

        for idx, (group_name, target_url) in enumerate(target_urls.items(), start=1):
            logger.info(f"[规格抓取] 正在访问({idx}/{len(target_urls)}): {group_name}")
            browser.get(target_url)
            cur = str(browser.current_url or "")
            cat_id = _extract_cat_id_from_url(target_url) or _extract_cat_id_from_page(browser)
            if cat_id:
                group_category_id_map[group_name] = cat_id
                logger.info(f"[规格抓取] 类目ID: {group_name} -> {cat_id}")
            if "login.alibaba.com" in cur:
                logger.error("[规格抓取] 检测到登录页，Cookie失效")
                raise HTTPException(status_code=400, detail="Cookie已失效，请先在Cookie管理重新登录")

            try:
                from fastapi.concurrency import run_in_threadpool
                def wait_element():
                    WebDriverWait(browser, 30).until(
                        EC.presence_of_element_located((By.ID, "struct-specification"))
                    )
                await run_in_threadpool(wait_element)
                await asyncio.sleep(8)
            except Exception:
                logger.warning(f"[规格抓取] 规格区域未加载成功，跳过类目: {group_name}")
                continue

            sale_attr_meta: Dict[str, Dict[str, Any]] = {}
            for selector in ["#struct-saleAttributesItems", ".saleAttributesItems", "#saleAttributesItems"]:
                try:
                    container = WebDriverWait(browser, 5).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, selector))
                    )
                except Exception:
                    container = None
                if not container:
                    continue
                wrappers = container.find_elements(
                    By.CSS_SELECTOR, ".next-checkbox-wrapper, [class*='checkbox-wrapper'], label.items, .items label"
                )
                for wrapper in wrappers:
                    try:
                        cb = wrapper.find_element(By.TAG_NAME, "input")
                        label = ""
                        try:
                            label = _norm_label(wrapper.find_element(By.CSS_SELECTOR, ".next-checkbox-label").text)
                        except Exception:
                            pass
                        val = str(cb.get_attribute("value") or "").strip()
                        wrapper_text = str(wrapper.text or "")
                        supports_image = "支持传图" in wrapper_text
                        is_checked = cb.is_selected() or (cb.get_attribute("checked") is not None)
                        disabled = bool(cb.get_attribute("disabled"))
                        if label and val:
                            sale_attr_meta[label] = {
                                "value": val,
                                "supports_image": supports_image,
                                "disabled": disabled,
                                "checked": is_checked,
                            }
                        if (not is_checked) and (not disabled):
                            browser.execute_script("arguments[0].click();", wrapper)
                            await asyncio.sleep(1.0)
                    except Exception:
                        continue
                break

            await asyncio.sleep(1.5) 

            spec_blocks = browser.find_elements(By.CSS_SELECTOR, "div.sell-o-addon[id^='p-']")
            logger.info(f"[规格抓取] 类目 {group_name} 识别到规格块数量={len(spec_blocks)}")

            for block in spec_blocks:
                try:
                    block_id = str(block.get_attribute("id") or "").strip()
                    if not block_id:
                        continue
                    scanned_blocks += 1

                    raw_title = ""
                    for sel in (
                        ".sell-o-addon-label",
                        ".oly-label-container",
                        "label.required",
                        ".next-form-item-label",
                    ):
                        try:
                            els = block.find_elements(By.CSS_SELECTOR, sel)
                            if els:
                                raw_title = str(els[0].text or "").strip()
                                if raw_title:
                                    break
                        except Exception:
                            continue
                    title = _clean_spec_title(raw_title)
                    if not title:
                        title = f"{group_name}_规格_{block_id}"

                    sale_meta = _match_sale_attr(title, sale_attr_meta)
                    sale_attr_value = str(sale_meta.get("value") or "").strip()
                    supports_image = bool(sale_meta.get("supports_image"))

                    interaction = _detect_spec_interaction(block)
                    has_image_switch = bool(
                        block.find_elements(By.CSS_SELECTOR, ".upload-image-switch .next-switch")
                    )
                    switch_on = False
                    try:
                        sw = block.find_element(By.CSS_SELECTOR, ".upload-image-switch .next-switch")
                        aria = str(sw.get_attribute("aria-checked") or "").lower()
                        switch_on = "true" in aria or "next-switch-on" in (sw.get_attribute("class") or "")
                    except Exception:
                        pass

                    values_pool: list[str] = []
                    default_values: list[str] = []
                    if interaction == "checkbox_grid":
                        cbs = block.find_elements(
                            By.CSS_SELECTOR,
                            ".sell-sequential-combobox .next-checkbox-wrapper, "
                            ".sell-sequential-combocheckbox .next-checkbox-wrapper, "
                            ".next-checkbox-wrapper",
                        )
                        for cb_wrap in cbs:
                            try:
                                lb = _norm_label(cb_wrap.text)
                                if not lb or lb in ("添加", "+ 添加") or "添加" == lb:
                                    continue
                                cb_input = cb_wrap.find_element(By.TAG_NAME, "input")
                                if lb and (lb not in values_pool):
                                    values_pool.append(lb)
                                try:
                                    is_checked = bool(
                                        cb_input.is_selected()
                                        or (cb_input.get_attribute("checked") is not None)
                                    )
                                except Exception:
                                    is_checked = False
                                if lb and is_checked and (lb not in default_values):
                                    default_values.append(lb)
                            except Exception:
                                continue

                    image_subdir = _default_image_subdir(title)
                    group_specs = grabbed_specs_by_group.setdefault(group_name, {})

                    if interaction == "value_rows":
                        enable_image = False
                        if title in ("颜色", "Color"):
                            enable_image = supports_image or has_image_switch or switch_on
                        elif title in ("样式", "Style"):
                            enable_image = False
                        else:
                            enable_image = supports_image and has_image_switch

                        existing_rows: list[str] = []
                        for row in block.find_elements(
                            By.CSS_SELECTOR, ".posting-field-color .list .item[role='item']"
                        ):
                            try:
                                inp = row.find_element(By.CSS_SELECTOR, "input[role='colorCombobox']")
                                val = str(inp.get_attribute("value") or "").strip()
                                if val and val not in existing_rows:
                                    existing_rows.append(val)
                            except Exception:
                                continue

                        group_specs[title] = {
                            "container_id": block_id,
                            "values_pool": existing_rows,
                            "default_values": existing_rows,
                            "max_select": max(1, len(existing_rows)),
                            "type": "value_rows",
                            "interaction": "value_rows",
                            "sale_attribute_value": sale_attr_value,
                            "enable_sale_attribute": bool(sale_meta.get("checked")),
                            "enable_spec_image": enable_image,
                            "image_subdir": image_subdir,
                            "scan_operable": True,
                        }
                        logger.info(
                            f"[规格抓取] + 输入型规格: {title} | {block_id} | "
                            f"规格图={has_image_switch} | 已有行={len(existing_rows)} | sale={sale_attr_value}"
                        )
                        continue

                    if not values_pool:
                        logger.info(f"[规格抓取] 跳过无选项规格块: {title} ({block_id})")
                        continue

                    old = group_specs.get(title, {})
                    old_values = old.get("values_pool") if isinstance(old, dict) else []
                    if isinstance(old_values, list) and len(old_values) > len(values_pool):
                        continue

                    group_specs[title] = {
                        "container_id": block_id,
                        "values_pool": values_pool,
                        "default_values": default_values,
                        "max_select": min(3, len(default_values)) if default_values else min(2, len(values_pool)),
                        "type": "checkbox",
                        "interaction": "checkbox_grid",
                        "sale_attribute_value": sale_attr_value,
                        "enable_sale_attribute": bool(sale_meta.get("checked")),
                        "enable_spec_image": False,
                        "image_subdir": "",
                        "scan_operable": True,
                    }
                    logger.info(
                        f"[规格抓取] + 复选框规格: {title} | {block_id} | 可选值={len(values_pool)} | sale={sale_attr_value}"
                    )
                except Exception as e:
                    logger.warning(f"[规格抓取] 跳过规格块: {e}")
                    continue

        all_group_specs = dict(cfg.attributes.specifications_by_group or {})
        before_group_count = len(all_group_specs)
        add_count = 0
        update_count = 0

        # 先落每个组的规格明细
        for group_name, group_specs in grabbed_specs_by_group.items():
            prev_group_specs = dict(all_group_specs.get(group_name) or {})
            next_group_specs: Dict[str, SpecificationItemConfig] = dict(prev_group_specs)
            for name, item in group_specs.items():
                interaction = str(item.get("interaction") or "").strip()
                prev_item = prev_group_specs.get(name)
                fetched_defaults = [
                    str(v).strip() for v in (item.get("default_values") or []) if str(v).strip()
                ]
                fetched_pool = [
                    str(v).strip() for v in (item.get("values_pool") or []) if str(v).strip()
                ]
                # 输入型规格：保留用户已配置的颜色填充值（页面上通常为空）
                if interaction == "value_rows" and prev_item:
                    prev_fill = [
                        str(v).strip() for v in (prev_item.default_values or []) if str(v).strip()
                    ]
                    if prev_fill:
                        fetched_defaults = prev_fill
                        fetched_pool = prev_fill

                enable_spec_image = bool(item.get("enable_spec_image"))
                image_subdir = str(item.get("image_subdir") or "").strip()
                enable_sale_attribute = item.get("enable_sale_attribute")
                if enable_sale_attribute is not None:
                    enable_sale_attribute = bool(enable_sale_attribute)
                if interaction == "value_rows" and prev_item:
                    if prev_item.enable_spec_image:
                        enable_spec_image = prev_item.enable_spec_image
                    if str(prev_item.image_subdir or "").strip():
                        image_subdir = str(prev_item.image_subdir).strip()
                if prev_item is not None and prev_item.enable_sale_attribute is not None:
                    enable_sale_attribute = prev_item.enable_sale_attribute

                merged = SpecificationItemConfig(
                    container_id=str(item.get("container_id") or "").strip(),
                    values_pool=fetched_pool,
                    default_values=fetched_defaults,
                    max_select=int(item.get("max_select") or 1),
                    type=str(item.get("type") or "checkbox").strip() or "checkbox",
                    interaction=interaction,
                    sale_attribute_value=str(item.get("sale_attribute_value") or "").strip(),
                    enable_sale_attribute=enable_sale_attribute,
                    enable_spec_image=enable_spec_image,
                    image_subdir=image_subdir or _default_image_subdir(name),
                    scan_operable=bool(item.get("scan_operable")),
                )
                next_group_specs[name] = merged
                if name in prev_group_specs:
                    update_count += 1
                else:
                    add_count += 1
            all_group_specs[group_name] = next_group_specs

        # 生成“共用规格”映射：规格结构完全一致的组别指向同一来源组
        signature_to_source: Dict[str, str] = {}
        alias_map: Dict[str, str] = {}
        canonical_group_specs: Dict[str, Dict[str, SpecificationItemConfig]] = {}

        def _spec_signature(spec_map: Dict[str, SpecificationItemConfig]) -> str:
            norm_items = []
            for k in sorted(spec_map.keys()):
                v = spec_map[k]
                values = sorted([str(x).strip() for x in (v.values_pool or []) if str(x).strip()])
                norm_items.append({
                    "name": k,
                    "container_id": str(v.container_id or "").strip(),
                    "max_select": int(v.max_select or 1),
                    "type": str(v.type or "checkbox").strip(),
                    "interaction": str(v.interaction or "").strip(),
                    "sale_attribute_value": str(v.sale_attribute_value or "").strip(),
                    "enable_sale_attribute": v.enable_sale_attribute,
                    "enable_spec_image": bool(v.enable_spec_image),
                    "image_subdir": str(v.image_subdir or "").strip(),
                    "values_pool": values,
                    "default_values": sorted([str(x).strip() for x in (v.default_values or []) if str(x).strip()]),
                })
            return json.dumps(norm_items, ensure_ascii=False, sort_keys=True)

        for group_name in sorted(all_group_specs.keys()):
            spec_map = all_group_specs.get(group_name) or {}
            sig = _spec_signature(spec_map)
            if sig in signature_to_source:
                alias_map[group_name] = signature_to_source[sig]
            else:
                signature_to_source[sig] = group_name
                alias_map[group_name] = group_name
                canonical_group_specs[group_name] = spec_map

        cfg.attributes.specifications_by_group = canonical_group_specs
        cfg.attributes.specification_group_alias = alias_map
        # 新增：按类目ID映射规格（发布时优先使用）
        by_category_id: Dict[str, Dict[str, SpecificationItemConfig]] = {}
        for group_name, cat_id in (group_category_id_map or {}).items():
            if not cat_id:
                continue
            source_group = alias_map.get(group_name, group_name)
            source_specs = canonical_group_specs.get(source_group) or {}
            if source_specs:
                by_category_id[str(cat_id)] = source_specs
        cfg.attributes.specifications_by_category_id = by_category_id

        # 兼容旧逻辑：保留一份全局规格（优先默认发品链接对应组，否则取首个组）
        default_group = ""
        default_url = str(cfg.group_urls.default_posting_url or "").strip()
        for g, u in (cfg.group_urls.group_url_map or {}).items():
            if str(u or "").strip() == default_url:
                default_group = g
                break
        fallback_group = default_group or (next(iter(alias_map.keys()), "") if alias_map else "")
        source_group = alias_map.get(fallback_group) if fallback_group else ""
        cfg.attributes.specifications = dict(canonical_group_specs.get(source_group or "", {}) or {})
        config_manager.save()

        logger.info(
            f"[规格抓取] 完成: 分组抓取={len(grabbed_specs_by_group)} 扫描块={scanned_blocks} 新增={add_count} 更新={update_count} 组总数(前->后)={before_group_count}->{len(canonical_group_specs)}"
        )

        return {
            "success": True,
            "data": {
                "target_url_count": len(target_urls),
                "fetched_group_count": len(grabbed_specs_by_group),
                "scanned_blocks": scanned_blocks,
                "added_count": add_count,
                "updated_count": update_count,
                "spec_group_total": len(canonical_group_specs),
                "shared_group_total": len([g for g, src in alias_map.items() if g != src]),
                "spec_category_total": len(by_category_id),
                "group_category_id_map": group_category_id_map,
                "specification_group_alias": alias_map,
            },
            "message": "商品规格抓取完成并已写入配置",
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"抓取规格失败: {e}")
    finally:
        try:
            if browser:
                browser.quit()
        except Exception:
            pass


# ===================== 组别链接管理 =====================

@router.get("/group-urls/list")
async def list_group_urls():
    """获取所有组别链接"""
    cfg = get_config()
    return {
        "success": True,
        "data": {
            "group_url_map": cfg.group_urls.group_url_map,
            "default_posting_url": cfg.group_urls.default_posting_url,
        }
    }


@router.put("/group-urls/{group_name}")
async def update_group_url(group_name: str, body: Dict[str, str], _=Depends(require_membership_or_trial)):
    """更新单个组别链接"""
    cfg = get_config()
    url = body.get("url", "")
    if not url:
        raise HTTPException(status_code=400, detail="URL 不能为空")
    cfg.group_urls.group_url_map[group_name] = url
    config_manager.save()
    return {"success": True, "message": f"组别 '{group_name}' 链接已更新"}


@router.delete("/group-urls/{group_name}")
async def delete_group_url(group_name: str, _=Depends(require_membership_or_trial)):
    """删除单个组别链接"""
    cfg = get_config()
    if group_name in cfg.group_urls.group_url_map:
        del cfg.group_urls.group_url_map[group_name]
        config_manager.save()
        return {"success": True, "message": f"组别 '{group_name}' 已删除"}
    raise HTTPException(status_code=404, detail=f"组别 '{group_name}' 不存在")


@router.post("/cookie/save-from-desktop")
async def save_cookie_from_desktop(req: SaveCookieFromDesktopReq, _=Depends(require_membership_or_trial)):
    """保存桌面端采集到的阿里登录 cookies 到配置的 cookie 文件路径。"""
    try:
      cfg = get_config()
      cookie_path = (getattr(cfg.paths, "cookie_file", "") or "").strip()
      if not cookie_path:
          raise ValueError("未配置 Cookie 文件路径，请先到配置管理中设置 paths.cookie_file")

      cookies = req.cookies or []
      if not isinstance(cookies, list) or len(cookies) == 0:
          raise ValueError("未采集到 cookies，请完成登录后再试")

      parent = os.path.dirname(cookie_path) or "."
      os.makedirs(parent, exist_ok=True)

      # 兼容旧逻辑：写入 pkl（如果读取端使用 pickle 加载）
      with open(cookie_path, "wb") as f:
          pickle.dump(cookies, f)

      # 同目录附加一份 JSON 便于排查
      json_path = f"{cookie_path}.json"
      with open(json_path, "w", encoding="utf-8") as f:
          json.dump(
              {
                  "source_url": req.source_url or "",
                  "count": len(cookies),
                  "cookies": cookies,
              },
              f,
              ensure_ascii=False,
              indent=2,
          )

      return {
          "success": True,
          "data": {
              "cookie_file": cookie_path,
              "cookie_json_file": json_path,
              "count": len(cookies),
          },
      }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/cookie/login-by-browser-manager")
async def login_cookie_by_browser_manager(authorization: str | None = Header(default=None), _=Depends(require_membership_or_trial)):
    """复用自动发品同款登录流程：打开浏览器登录并保存 Cookie，同时采集 supplierIdentity 信息写入当前会员资料。"""

    # 绑定店铺只要求通过全局登录校验；这里不再强依赖 Authorization 头，
    # 以兼容不同登录来源（本地会话/云端映射会话）下的绑定场景。

    # 优先使用本地会员 token；若是云端 token，则回退到云端 /membership/me 再映射本地账号
    user_id = 0
    current_username = ""
    auth = str(authorization or "").strip()
    token = auth[7:].strip() if auth.lower().startswith("bearer ") else auth
    try:
        user_id = int(_uid_by_token(token) or 0)
        if user_id > 0:
            try:
                conn0 = _conn()
                cur0 = conn0.cursor()
                row0 = cur0.execute("SELECT username FROM users WHERE id=? LIMIT 1", (int(user_id),)).fetchone()
                if row0:
                    current_username = str(row0["username"] or "").strip()
                conn0.close()
            except Exception:
                pass
    except Exception:
        user_id = 0

    if user_id <= 0 and token:
        try:
            r = requests.get(
                CLOUD_MEMBERSHIP_ME_URL,
                headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
                timeout=(3, 6),
            )
            if r.ok:
                payload = r.json() or {}
                data = payload.get("data") if isinstance(payload, dict) else None
                username = str((data or {}).get("username") or "").strip()
                if username:
                    current_username = username
                    trial_end_at = str((data or {}).get("trial_end_at") or "2099-12-31 23:59:59").strip() or "2099-12-31 23:59:59"
                    vip_expire_at = str((data or {}).get("vip_expire_at") or "").strip() or None
                    init_db()
                    conn = _conn()
                    cur = conn.cursor()
                    row = cur.execute("SELECT id FROM users WHERE username=? LIMIT 1", (username,)).fetchone()
                    if not row:
                        cur.execute(
                            """
                            INSERT INTO users(username,password_hash,invite_code,inviter_user_id,invited_at,trial_start_at,trial_end_at,vip_expire_at,created_at)
                            VALUES(?,?,?,?,?,?,?,?,?)
                            """,
                            (
                                username,
                                _hash_pwd("temp-bind-store"),
                                _new_invite_code(),
                                None,
                                None,
                                _now_str(),
                                trial_end_at,
                                vip_expire_at,
                                _now_str(),
                            ),
                        )
                        user_id = int(cur.lastrowid)
                    else:
                        user_id = int(row["id"])
                        cur.execute(
                            "UPDATE users SET trial_end_at=?, vip_expire_at=? WHERE id=?",
                            (trial_end_at, vip_expire_at, user_id),
                        )

                    # 建立 token -> 本地会话映射，后续本地功能校验直接命中本地 user_sessions
                    cur.execute(
                        "INSERT OR REPLACE INTO user_sessions(token,user_id,created_at,expire_at,last_seen_at) VALUES(?,?,?,?,?)",
                        (token, user_id, _now_str(), "2099-12-31 23:59:59", _now_str()),
                    )
                    conn.commit()
                    conn.close()
        except Exception:
            user_id = 0

    # 绑定店铺允许弱会话：即使会员 token 解析失败，也允许继续执行绑定流程。
    # 仅在无法识别用户ID时跳过“回写会员资料”步骤，不影响Cookie保存和绑定动作。
    if user_id <= 0:
        user_id = 0

    browser = BrowserManager()
    try:
        ok_setup = await run_in_threadpool(browser.setup)
        if not ok_setup:
            err = BrowserManager.get_last_setup_error()
            hint = (
                "请先安装 Google Chrome（https://www.google.com/chrome/）；"
                "若已安装仍失败，请检查网络能否下载 ChromeDriver，或联系技术支持。"
            )
            detail = f"浏览器启动失败：{err}" if err else f"浏览器启动失败：{hint}"
            raise HTTPException(status_code=500, detail=detail)

        # 绑定店铺专用：不走发品链接，直接进店铺后台登录
        driver = browser.driver
        backend_url = "https://i.alibaba.com/index.htm?spm=a2700.product_home_fy25.home_header.5.710867af0QVxzG"
        login_url = (
            "https://login.alibaba.com/newlogin/icbuLogin.htm?defaultActive=signIn"
            "&return_url=https%3A%2F%2Fi.alibaba.com%2Findex.htm"
        )

        # 按新流程：启动浏览器后直接等待用户登录，不再预先尝试本地 cookie 直登
        import time as _t
        driver.get(login_url)

        # 缩短等待时间：优先快轮询，避免长时间阻塞
        end_time = _t.time() + 180
        while _t.time() < end_time:
            browser._auto_confirm_login()
            c = str(driver.current_url or "")
            if ("i.alibaba.com" in c) and ("login.alibaba.com" not in c):
                break
            _t.sleep(0.12)

        c = str(driver.current_url or "")
        if ("i.alibaba.com" not in c) or ("login.alibaba.com" in c):
            raise HTTPException(status_code=400, detail="登录未完成或超时，请重试（请在打开的浏览器窗口完成阿里登录）")

        # 无论是自动命中 cookie 还是手动登录，统一刷新保存一份最新 cookie
        try:
            browser._save_cookies()
        except Exception:
            pass

        cfg = get_config()
        cookie_path = (getattr(cfg.paths, "cookie_file", "") or "").strip()
        json_path = f"{cookie_path}.json" if cookie_path else ""

        count = 0
        cookies = []
        try:
            if cookie_path and os.path.exists(cookie_path):
                with open(cookie_path, "rb") as f:
                    cookies = pickle.load(f)
                if isinstance(cookies, list):
                    count = len(cookies)
                if json_path:
                    with open(json_path, "w", encoding="utf-8") as jf:
                        json.dump({"count": count, "cookies": cookies}, jf, ensure_ascii=False, indent=2)
        except Exception:
            pass

        # 绑定成功后自动进入店铺后台并读取 supplierIdentity.json
        backend_url = "https://i.alibaba.com/index.htm?spm=a2700.product_home_fy25.home_header.5.710867af0QVxzG"
        supplier_url = "https://crmweb.alibaba.com/rightcenter/right/supplierIdentity.json"
        profile = {
            "company_name": "",
            "main_category": "",
            "is_verified": "",
            "service_years": "",
            "page_level_star": "",
        }

        try:
            driver = browser.driver
            cur2 = str(driver.current_url or "")
            if ("i.alibaba.com" not in cur2) or ("login.alibaba.com" in cur2):
                driver.get(backend_url)
                import time as _t
                _t.sleep(0.2)

            # 关键：优先复用当前登录会话，从页面上下文 fetch（等价于 Network 那条请求）
            payload = {}
            try:
                js = driver.execute_async_script(
                    """
                    const done = arguments[0];
                    const url = arguments[1];
                    fetch(url, {
                      method: 'GET',
                      credentials: 'include',
                      headers: { 'Accept': 'application/json,text/plain,*/*' }
                    })
                    .then(async (r) => {
                      const t = await r.text();
                      let j = null;
                      try { j = t ? JSON.parse(t) : null; } catch (_) {}
                      done({ ok: r.ok, status: r.status, json: j, text: t });
                    })
                    .catch((e) => done({ ok: false, status: 0, error: String(e && e.message ? e.message : e) }));
                    """,
                    supplier_url,
                )
                if isinstance(js, dict) and bool(js.get("ok")) and isinstance(js.get("json"), dict):
                    payload = js.get("json") or {}
            except Exception:
                payload = {}

            # 回退：若页面 fetch 失败，再用 cookies 发 requests
            if not payload:
                cookie_dict = {c.get("name"): c.get("value") for c in (cookies or []) if isinstance(c, dict) and c.get("name")}
                if cookie_dict:
                    resp = requests.get(
                        supplier_url,
                        cookies=cookie_dict,
                        timeout=(6, 15),
                        headers={
                            "User-Agent": "Mozilla/5.0",
                            "Referer": backend_url,
                            "Accept": "application/json,text/plain,*/*",
                        },
                    )
                    if resp.ok:
                        payload = resp.json() or {}

            data = {}
            if isinstance(payload, dict):
                if isinstance(payload.get("data"), dict):
                    data = payload.get("data")
                elif isinstance(payload.get("content"), dict):
                    data = payload.get("content")
                else:
                    data = payload

            if isinstance(data, dict):
                verified_raw = str(data.get("isVerified") or data.get("is_verified") or "").strip().upper()
                profile = {
                    "company_name": str(
                        data.get("companyName")
                        or data.get("company_name")
                        or data.get("company")
                        or data.get("enterpriseName")
                        or ""
                    ).strip(),
                    "main_category": str(
                        data.get("mainCategory")
                        or data.get("main_category")
                        or data.get("主营类目")
                        or data.get("主营行业")
                        or ""
                    ).strip(),
                    "is_verified": verified_raw,
                    "service_years": str(data.get("serviceYears") or data.get("service_years") or "").strip(),
                    "page_level_star": str(data.get("pageLevelStar") or data.get("page_level_star") or "").strip(),
                }

            # 调试落盘：不是 cookies.pkl.json，而是 supplierIdentity 原始响应
            try:
                base_dir = os.path.dirname((get_config().paths.cookie_file or "") or ".") or "."
                os.makedirs(base_dir, exist_ok=True)
                debug_path = os.path.join(base_dir, "supplierIdentity.last.json")
                with open(debug_path, "w", encoding="utf-8") as f:
                    json.dump(payload if isinstance(payload, dict) else {"raw": payload}, f, ensure_ascii=False, indent=2)
            except Exception:
                pass
        except Exception:
            # 采集失败不阻断绑定流程
            pass

        # 写入会员资料（含公司级会员强绑定，防止重复注册薅试用）
        if int(user_id or 0) > 0:
            from app.services.membership_service import _conn, _company_key, _sync_company_membership_by_user
            conn = _conn()
            cur = conn.cursor()

            company_name = str(profile.get("company_name") or "").strip()
            ck = _company_key(company_name)

            # 先写店铺基础信息
            cur.execute(
                """
                UPDATE users
                SET company_name=?, main_category=?, is_verified=?, service_years=?, page_level_star=?, created_at=created_at
                WHERE id=?
                """,
                (
                    company_name,
                    profile.get("main_category", ""),
                    profile.get("is_verified", ""),
                    profile.get("service_years", ""),
                    profile.get("page_level_star", ""),
                    int(user_id),
                ),
            )

            if ck:
                bind = cur.execute(
                    "SELECT trial_start_at, trial_end_at, vip_expire_at FROM company_membership_bindings WHERE company_key=?",
                    (ck,),
                ).fetchone()
                if bind:
                    # 已存在公司绑定：新账号继承该公司首个绑定沉淀下来的到期状态
                    cur.execute(
                        "UPDATE users SET trial_start_at=?, trial_end_at=?, vip_expire_at=? WHERE id=?",
                        (bind["trial_start_at"], bind["trial_end_at"], bind["vip_expire_at"], int(user_id)),
                    )
                else:
                    # 首次绑定：以当前账号状态创建公司绑定
                    _sync_company_membership_by_user(cur, int(user_id))

            conn.commit()
            conn.close()

        # ---------------- 自动采集分组和发品链接逻辑 ----------------
        try:
            import time as _t
            # 1. 采集分组接口
            group_url = "https://hz-productposting.alibaba.com/product/group_query_ajax.do?event=listGroupCombine"
            group_js = f"""
                const done = arguments[0];
                fetch('{group_url}', {{
                  method: 'GET',
                  credentials: 'include',
                  headers: {{ 'Accept': 'application/json,text/plain,*/*' }}
                }} )
                .then(async (r) => {{
                  const t = await r.text();
                  let j = null;
                  try {{ j = t ? JSON.parse(t) : null; }} catch (_) {{}}
                  done({{ ok: r.ok, json: j }});
                }})
                .catch((e) => done({{ ok: false, error: String(e) }}));
            """
            group_res = driver.execute_async_script(group_js)
            
            # 2. 采集产品列表接口 (获取所有商品，这里为了避免超时，假设最多取前5页)
            all_products = []
            for page in range(1, 6):
                product_url = f"https://hz-productposting.alibaba.com/product/managementproducts/asyQueryProductsList.do?statisticsType=month&repositoryType=all&imageType=all&showPowerScore=&status=approved&showType=onlyMarket&page={page}&size=50&displayStatus=online"
                prod_js = f"""
                    const done = arguments[0];
                    fetch('{product_url}', {{
                      method: 'GET',
                      credentials: 'include',
                      headers: {{ 'Accept': 'application/json,text/plain,*/*' }}
                    }} )
                    .then(async (r) => {{
                      const t = await r.text();
                      let j = null;
                      try {{ j = t ? JSON.parse(t) : null; }} catch (_) {{}}
                      done({{ ok: r.ok, json: j }});
                    }})
                    .catch((e) => done({{ ok: false, error: String(e) }}));
                """
                prod_res = driver.execute_async_script(prod_js)
                if isinstance(prod_res, dict) and prod_res.get("ok") and isinstance(prod_res.get("json"), list):
                    items = prod_res["json"]
                    if not items:
                        break
                    all_products.extend(items)
                    _t.sleep(0.5)
                else:
                    break

            # 3. 解析分组树，提取所有叶子分组 (一、二、三级)
            groups_map = {{}}  # groupId -> groupName
            def extract_groups(nodes, prefix=""):
                for node in nodes:
                    name = node.get("name", "").strip()
                    gid = node.get("id")
                    if not name or not gid:
                        continue
                    # 也可以拼层级名，这里按需求只用当前节点名
                    groups_map[str(gid)] = name
                    if node.get("children"):
                        extract_groups(node["children"], name)

            if isinstance(group_res, dict) and group_res.get("ok") and isinstance(group_res.get("json"), list):
                extract_groups(group_res["json"])

            # 4. 按分组统计产品月曝光量 (showNum)
            group_top_products = {{}}  # groupId -> {"id": prod_id, "showNum": num}
            for prod in all_products:
                pid = str(prod.get("id", ""))
                if not pid:
                    continue
                # 月曝光量
                show_num = int(prod.get("showNum", 0))
                
                # 确定产品所属的最深分组
                gid = ""
                if prod.get("groupId3"):
                    gid = str(prod.get("groupId3"))
                elif prod.get("groupId2"):
                    gid = str(prod.get("groupId2"))
                elif prod.get("groupId"):
                    gid = str(prod.get("groupId"))
                
                if gid and gid in groups_map:
                    current_top = group_top_products.get(gid)
                    if not current_top or show_num > current_top["showNum"]:
                        group_top_products[gid] = {{"id": pid, "showNum": show_num}}

            # 5. 更新配置管理的平台URL配置
            if groups_map and group_top_products:
                cfg = get_config()
                if not hasattr(cfg, "group_urls"):
                    from app.core.config_manager import GroupUrlsConfig
                    cfg.group_urls = GroupUrlsConfig()
                if not cfg.group_urls.group_url_map:
                    cfg.group_urls.group_url_map = {{}}
                
                base_pub_url = "https://post.alibaba.com/product/publish.htm?spm=a2700.micro_product_manager.0.0.5d083e5f7ZITpt&pubType=similarPost&behavior=copyNew&itemId="
                
                for gid, top_prod in group_top_products.items( ):
                    gname = groups_map[gid]
                    pid = top_prod["id"]
                    # 组装发品链接
                    pub_url = f"{{base_pub_url}}{{pid}}"
                    # 自动填充到配置
                    cfg.group_urls.group_url_map[gname] = pub_url
                
                # 保存配置
                from app.core.config_manager import config_manager
                config_manager.save()
        except Exception as e:
            # 采集失败不阻断主流程
            import logging
            logging.warning(f"自动采集分组发品链接失败: {{e}}")
        # ---------------- 自动采集分组和发品链接逻辑结束 ----------------


        # 绑定成功后：同步店铺资料到云端会员库，避免云端 me 无 company_name
        cloud_sync = {"ok": False, "detail": "", "status": 0}
        try:
            admin_key = str(getattr(get_config().payment, "admin_api_key", "") or "").strip()
            if admin_key and current_username and (str(profile.get("company_name") or "").strip() or str(profile.get("main_category") or "").strip()):
                sync_resp = requests.post(
                    f"{CLOUD_MEMBERSHIP_API_BASE}/admin/users/profile-upsert",
                    json={
                        "username": current_username,
                        "company_name": str(profile.get("company_name") or ""),
                        "main_category": str(profile.get("main_category") or ""),
                        "is_verified": str(profile.get("is_verified") or ""),
                        "service_years": str(profile.get("service_years") or ""),
                        "page_level_star": str(profile.get("page_level_star") or ""),
                    },
                    headers={
                        "X-Admin-Key": admin_key,
                        "Authorization": f"Bearer {token}",
                        "Content-Type": "application/json",
                    },
                    timeout=(3, 6),
                )
                cloud_sync["status"] = int(sync_resp.status_code or 0)
                if sync_resp.ok:
                    cloud_sync["ok"] = True
                else:
                    cloud_sync["detail"] = sync_resp.text[:300]
        except Exception as e:
            cloud_sync["detail"] = str(e)

        return {
            "success": True,
            "data": {
                "cookie_file": cookie_path,
                "cookie_json_file": json_path,
                "count": count,
                "profile": profile,
                "backend_url": backend_url,
                "supplier_identity_url": supplier_url,
                "cloud_sync": cloud_sync,
            },
            "message": "登录成功，Cookie 已保存",
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"绑定店铺失败：{e}")
    finally:
        await run_in_threadpool(browser.quit)

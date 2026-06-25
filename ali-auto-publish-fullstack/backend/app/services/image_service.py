# -*- coding: utf-8 -*-
"""
图片管理服务层
重构自: cs_图片命名规范化.py
"""
import os
import re
import json
import math
import time
import shutil
import random
from datetime import datetime
from collections import deque
from typing import Dict, List, Optional, Tuple

import pandas as pd

from app.core.settings import get_config
from app.core.task_manager import TaskInfo
from app.core.logger import setup_logger

logger = setup_logger("image_service")

_MAIN_IMAGE_ROUND_ROBIN_CACHE: Dict[Tuple[int, str], deque] = {}


# ===================== 配置读取/保存 =====================

def get_image_norm_config() -> Dict:
    """合并配置中心 + image_norm.json（文件优先）"""
    cfg = get_config()
    base = cfg.image_norm.model_dump()

    file_path = base.get("config_file")
    if file_path and os.path.exists(file_path):
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                file_cfg = json.load(f)
            base.update(file_cfg)
        except Exception as e:
            logger.warning(f"读取 image_norm 配置文件失败: {e}")

    # 附加路径配置（用于前端展示/编辑）
    base["exceptional_main_image_dir"] = cfg.paths.exceptional_main_image_dir
    return base


def save_image_norm_config(data: Dict) -> Dict:
    """保存 image_norm.json，同时更新配置中心"""
    cfg = get_config()
    config_file = data.get("config_file") or cfg.image_norm.config_file

    # 保存到文件（剔除非 image_norm 字段）
    file_payload = dict(data)
    file_payload.pop("exceptional_main_image_dir", None)

    if config_file:
        try:
            os.makedirs(os.path.dirname(config_file), exist_ok=True)
            with open(config_file, "w", encoding="utf-8") as f:
                json.dump(file_payload, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(f"保存 image_norm 配置文件失败: {e}")

    # 更新配置中心
    try:
        from app.core.settings import config_manager
        config_manager.update("image_norm", file_payload)
        if data.get("exceptional_main_image_dir"):
            config_manager.update("paths", {"exceptional_main_image_dir": data.get("exceptional_main_image_dir")})
    except Exception as e:
        logger.warning(f"更新配置中心 image_norm 失败: {e}")

    return data


# ===================== 分组扫描 =====================

def scan_image_groups() -> List[Dict]:
    """扫描所有图片分组（源素材目录）"""
    cfg = get_config()
    norm_cfg = get_image_norm_config()
    groups = []

    source_dirs = norm_cfg.get("groups") or []
    if not source_dirs:
        return groups

    for dir_path in source_dirs:
        if not os.path.isdir(dir_path):
            try:
                os.makedirs(dir_path, exist_ok=True)
            except Exception:
                continue
        images = [f for f in os.listdir(dir_path) if f.lower().endswith((".jpg", ".jpeg", ".png", ".webp"))]
        img_items = []
        for img in images:
            filepath = os.path.join(dir_path, img)
            stat = os.stat(filepath)
            parsed = _parse_image_name(img)
            sku_parsed = _parse_sku_image_name(img)
            is_normalized = bool((parsed and parsed[1] is not None) or sku_parsed[0])
            img_items.append({
                "name": img,
                "path": filepath,
                "scene": _infer_scene_from_name(img),
                "size": "--",
                "fileSize": _format_size(stat.st_size),
                "normalized": is_normalized,
            })

        groups.append({
            "id": os.path.basename(dir_path),
            "name": os.path.basename(dir_path),
            "folder": dir_path,
            "image_count": len(images),
            "images": img_items,
        })

    return groups


def get_group_images(group_id: str) -> List[Dict]:
    """获取指定分组的图片详情"""
    norm_cfg = get_image_norm_config()
    source_dirs = norm_cfg.get("groups") or []

    target_dir = None
    for p in source_dirs:
        if os.path.basename(p) == group_id or p == group_id:
            target_dir = p
            break
    if not target_dir or not os.path.isdir(target_dir):
        return []

    images = []
    for f in sorted(os.listdir(target_dir)):
        if not f.lower().endswith((".jpg", ".jpeg", ".png", ".webp")):
            continue
        filepath = os.path.join(target_dir, f)
        stat = os.stat(filepath)
        parsed = _parse_image_name(f)
        sku_parsed = _parse_sku_image_name(f)
        is_normalized = bool((parsed and parsed[1] is not None) or sku_parsed[0])
        images.append({
            "name": f,
            "path": filepath,
            "scene": _infer_scene_from_name(f),
            "size": "--",
            "fileSize": _format_size(stat.st_size),
            "normalized": is_normalized,
        })

    return images


# ===================== 统计 =====================

def get_image_statistics() -> Dict:
    cfg = get_config()
    stats = {
        "total_groups": 0,
        "total_images": 0,
        "total_size_bytes": 0,
        "scenes": {},
        "primary_count": 0,
    }

    norm_cfg = get_image_norm_config()
    source_dirs = norm_cfg.get("groups") or []

    for dir_path in source_dirs:
        if not os.path.isdir(dir_path):
            try:
                os.makedirs(dir_path, exist_ok=True)
            except Exception:
                continue
        stats["total_groups"] += 1
        for f in os.listdir(dir_path):
            if f.lower().endswith((".jpg", ".jpeg", ".png", ".webp")):
                stats["total_images"] += 1
                size = os.path.getsize(os.path.join(dir_path, f))
                stats["total_size_bytes"] += size
                scene = _infer_scene_from_name(f)
                stats["scenes"][scene] = stats["scenes"].get(scene, 0) + 1

    primary_dir = cfg.paths.primary_image_dir
    if os.path.isdir(primary_dir):
        stats["primary_count"] = len([
            f for f in os.listdir(primary_dir)
            if f.lower().endswith((".jpg", ".jpeg", ".png", ".webp"))
        ])

    stats["total_size_display"] = _format_size(stats["total_size_bytes"])
    return stats


# ===================== 规范化任务 =====================

def run_normalize_task(task: TaskInfo, source_dirs: Optional[List[str]] = None):
    """图片命名规范化任务"""
    cfg = get_config()
    norm_cfg = get_image_norm_config()

    groups = source_dirs or norm_cfg.get("groups") or []
    if not groups:
        task.current_step = "未配置图片分组目录"
        task.progress = task.total = 0
        return

    # 确保关键路径存在
    os.makedirs(cfg.paths.primary_image_dir, exist_ok=True)
    os.makedirs(cfg.paths.main_image_dir, exist_ok=True)

    if cfg.paths.name_mapping_file:
        os.makedirs(os.path.dirname(cfg.paths.name_mapping_file), exist_ok=True)
        if not os.path.exists(cfg.paths.name_mapping_file):
            open(cfg.paths.name_mapping_file, "a", encoding="utf-8").close()

    processed_file = norm_cfg.get("processed_products_file")
    if processed_file:
        os.makedirs(os.path.dirname(processed_file), exist_ok=True)
        if not os.path.exists(processed_file):
            open(processed_file, "a", encoding="utf-8").close()

    task.current_step = "扫描图片..."
    task.total = len(groups)

    logger.info(f"规范化开始：分组目录数量={len(groups)}")

    processed_products = _load_processed_products(norm_cfg)
    title_scenes = _get_title_scenes(cfg.paths.title_excel_path)
    if not title_scenes:
        title_scenes = ["默认场景"]

    random.shuffle(title_scenes)

    today = datetime.now().strftime("%m%d").lstrip("0")
    product_index = 1

    for i, group_path in enumerate(groups):
        if task.should_stop():
            break
        task.wait_if_paused()
        task.current_step = f"处理分组: {os.path.basename(group_path)}"
        task.progress = i

        if not os.path.exists(group_path):
            try:
                os.makedirs(group_path, exist_ok=True)
            except Exception:
                logger.warning(f"分组目录不存在且创建失败: {group_path}")
                continue

        group_name = os.path.basename(group_path)
        image_files = [
            f for f in os.listdir(group_path)
            if f.lower().endswith((".jpg", ".jpeg", ".png"))
        ]
        logger.info(f"扫描分组: {group_name}，图片数量={len(image_files)}")
        if not image_files:
            continue

        # 按自主名分组（主图 1~6 + SKU 图）
        groups_map: Dict[str, List[Tuple[str, int]]] = {}
        sku_map: Dict[str, List[Tuple[str, str]]] = {}
        for img in image_files:
            sku_parsed = _parse_sku_image_name(img)
            if sku_parsed[0]:
                group_key, spec = sku_parsed
                sku_map.setdefault(group_key, []).append((img, spec))
                continue
            result = _parse_image_name(img)
            if result is None:
                continue
            group_key, position, _ = result
            if group_key is None:
                continue
            groups_map.setdefault(group_key, []).append((img, position))

        for group_key, images in groups_map.items():
            if task.should_stop():
                logger.info("图片规范化收到停止信号，终止当前分组处理")
                break
            task.wait_if_paused()

            primary_img = None
            main_imgs = []
            for img, pos in images:
                if pos == 1:
                    primary_img = img
                elif 2 <= pos <= 6:
                    main_imgs.append((img, pos))

            if not primary_img:
                logger.warning(f"分组 {group_name} 子组 {group_key} 缺少 position=1，跳过")
                continue

            base = os.path.splitext(primary_img)[0]
            parts = base.split("-")
            if len(parts) >= 2:
                real_pid = f"{parts[0]}-{parts[1]}"
                _, _, house_type = _parse_image_name(primary_img)
                product_key = f"{real_pid}-{house_type}" if house_type else real_pid
            else:
                product_key = base

            if product_key in processed_products:
                logger.info(f"已处理跳过: {product_key}")
                continue

            # 标题场景
            all_scenes = _get_title_scenes(cfg.paths.title_excel_path)
            used_global: set = set()
            _, _, house_type = _parse_image_name(primary_img)
            title_scene = _get_compatible_title_scene(
                house_type,
                all_scenes,
                used_global,
                norm_cfg.get("house_type_allowed_scenes", {}),
                norm_cfg.get("house_type_forbidden_scenes", {}),
            )
            used_global.add(title_scene)

            # 新首图
            new_primary_name = f"{today}-{product_index}-{group_name}-{title_scene}.jpg"
            new_primary_path = os.path.join(cfg.paths.primary_image_dir, new_primary_name)

            # 主图目录
            main_folder = os.path.join(cfg.paths.main_image_dir, f"{today}-{product_index}")
            os.makedirs(main_folder, exist_ok=True)
            os.makedirs(cfg.paths.primary_image_dir, exist_ok=True)

            src_primary = os.path.join(group_path, primary_img)
            shutil.copy2(src_primary, new_primary_path)

            # 映射文件
            if cfg.paths.name_mapping_file:
                os.makedirs(os.path.dirname(cfg.paths.name_mapping_file), exist_ok=True)
                with open(cfg.paths.name_mapping_file, "a", encoding="utf-8") as f:
                    f.write(f"{primary_img} → {new_primary_name}\n")

            # 处理主图2（可能从主图库补齐）
            existing_positions = set()
            pos2_source_path = None
            pos2_filename = None

            for img, pos in main_imgs:
                if pos == 2:
                    pos2_source_path = os.path.join(group_path, img)
                    pos2_filename = img
                    break

            if pos2_source_path is None:
                lib_img_path = _get_random_image_from_lib(2, house_type, norm_cfg.get("main_image_lib", {}))
                if lib_img_path:
                    pos2_source_path = lib_img_path
                    pos2_filename = os.path.basename(lib_img_path)

            if pos2_source_path:
                # 主图2文件名：规范为“2-房子类型.jpg”，价格仅写入 CSV，不保留在文件名中
                pos2_source_name = os.path.basename(pos2_filename or pos2_source_path)
                pos2_base = os.path.splitext(pos2_source_name)[0]
                parts = [p for p in pos2_base.split("-") if p]

                if len(parts) >= 3 and parts[-1].replace(".", "", 1).isdigit():
                    label = "-".join(parts[1:-1])
                elif len(parts) >= 2:
                    label = "-".join(parts[1:])
                else:
                    label = pos2_base

                dst2_name = f"{parts[0] if parts else '2'}-{label}.jpg" if label else f"{parts[0] if parts else '2'}.jpg"
                dst2 = os.path.join(main_folder, dst2_name)
                shutil.copy2(pos2_source_path, dst2)
                existing_positions.add(2)

                price = _extract_price_from_filename(pos2_filename)
                if price is not None:
                    price_csv_path = os.path.join(main_folder, "出厂价格.csv")
                    with open(price_csv_path, "w", encoding="utf-8") as f:
                        f.write(str(price))

            # 处理3-6
            for img, pos in main_imgs:
                if pos < 3 or pos > 6:
                    continue
                dst = os.path.join(main_folder, f"{pos}.jpg")
                src = os.path.join(group_path, img)
                shutil.copy2(src, dst)
                existing_positions.add(pos)

            # 补齐3-6
            needed_positions = {3, 4, 5, 6}
            missing_positions = needed_positions - existing_positions
            if missing_positions:
                source_group_images = groups_map.get(group_key, [])
                source_house_type = house_type

                for pos in sorted(missing_positions):
                    found_in_source = False
                    for img, img_pos in source_group_images:
                        if img_pos == pos:
                            _, _, img_house_type = _parse_image_name(img)
                            if (
                                img_house_type == source_house_type or
                                (img_house_type and source_house_type and _fuzzy_match(source_house_type, img_house_type))
                            ):
                                src = os.path.join(group_path, img)
                                dst = os.path.join(main_folder, f"{pos}.jpg")
                                shutil.copy2(src, dst)
                                found_in_source = True
                                break

                    if found_in_source:
                        continue

                    src_img = _get_random_image_from_lib(pos, house_type, norm_cfg.get("main_image_lib", {}))
                    if src_img:
                        dst = os.path.join(main_folder, f"{pos}.jpg")
                        shutil.copy2(src_img, dst)

            _copy_group_sku_images(group_path, group_key, sku_map, main_folder)

            logger.info(f"完成产品: {product_key}")
            _save_processed_product(product_key, norm_cfg)
            processed_products.add(product_key)
            product_index += 1

    task.progress = task.total
    task.current_step = "规范化完成"


# ===================== 核心逻辑函数 =====================

def _sanitize_sku_spec_name(spec: str) -> str:
    """SKU 规格名用于文件名（去掉非法路径字符）。"""
    return re.sub(r'[\\/:*?"<>|]', "", str(spec or "").strip()) or "SKU"


def _parse_sku_image_name(filename: str):
    """
    解析源素材 SKU 图：{自由名}-SKU-{规格}
    规格可为颜色或其他名称；SKU 段不区分大小写。
    返回 (group_key, spec) 或 (None, None)
    """
    base = os.path.splitext(filename)[0]
    parts = [p.strip() for p in base.split("-") if p.strip()]
    if len(parts) < 3:
        return None, None
    for i, part in enumerate(parts):
        if part.upper() == "SKU":
            group_key = "-".join(parts[:i])
            spec = "-".join(parts[i + 1:])
            if group_key and spec:
                return group_key, spec
            return None, None
    return None, None


def _copy_group_sku_images(
    group_path: str,
    group_key: str,
    sku_map: Dict[str, List[Tuple[str, str]]],
    main_folder: str,
) -> int:
    """将同自由名下的 SKU 源图复制到主图目录/SKU/{规格}.jpg"""
    items = sku_map.get(group_key) or []
    if not items:
        return 0
    sku_dir = os.path.join(main_folder, "SKU")
    os.makedirs(sku_dir, exist_ok=True)
    copied = 0
    for img, spec in items:
        safe_spec = _sanitize_sku_spec_name(spec)
        src = os.path.join(group_path, img)
        if not os.path.isfile(src):
            logger.warning(f"SKU 源图不存在，跳过: {src}")
            continue
        ext = os.path.splitext(img)[1]
        if ext.lower() not in (".jpg", ".jpeg", ".png", ".webp"):
            ext = ".jpg"
        dst = os.path.join(sku_dir, f"{safe_spec}{ext}")
        if os.path.isfile(dst):
            logger.warning(f"SKU 规格重复，覆盖: {safe_spec}{ext}")
        shutil.copy2(src, dst)
        copied += 1
        logger.info(f"SKU 图: {img} → {os.path.join('SKU', safe_spec + ext)}")
    if copied:
        logger.info(f"SKU 目录: {sku_dir}（共 {copied} 张）")
    return copied


def _parse_image_name(filename: str):
    base = os.path.splitext(filename)[0]
    parts = base.split("-")

    if len(parts) < 2:
        return None, None, None

    group_key_parts = []
    position = None
    house_type = None

    for i, part in enumerate(parts):
        if part.isdigit():
            pos_val = int(part)
            if 1 <= pos_val <= 6:
                position = pos_val
                group_key_parts = parts[:i]
                remaining = parts[i + 1:]
                if position == 1 and remaining:
                    house_type = remaining[0]
                break
        else:
            continue

    if position is None:
        return None, None, None

    group_key = "-".join(group_key_parts) if group_key_parts else parts[0]
    return group_key, position, house_type


def _infer_scene_from_name(filename: str) -> str:
    if _parse_sku_image_name(filename)[0]:
        return "sku"
    _, pos, _ = _parse_image_name(filename)
    if pos == 1:
        return "main"
    if pos and 2 <= pos <= 6:
        return "detail"
    return "other"


def _fuzzy_match(house_type, candidate_type):
    if not house_type or not candidate_type:
        return False
    house_type = house_type.lower()
    candidate_type = candidate_type.lower()
    return candidate_type in house_type or house_type in candidate_type


def _extract_price_from_filename(filename: Optional[str]):
    if not filename:
        return None
    group_key, position, _ = _parse_image_name(filename)
    if position != 2:
        return None

    base = os.path.splitext(filename)[0]
    parts = base.split("-")
    if len(parts) < 2:
        return None

    last_part = parts[-1]
    if last_part.replace(".", "", 1).isdigit() and last_part != ".":
        try:
            price = float(last_part)
            if price > 0:
                return price
        except (ValueError, OverflowError):
            pass
    return None


def _get_compatible_title_scene(
    house_type,
    all_scenes,
    used_scenes,
    allowed_map: Dict[str, List[str]],
    forbidden_map: Dict[str, List[str]],
):
    if not house_type:
        candidates = [s for s in all_scenes if s not in used_scenes]
        if not candidates:
            candidates = all_scenes
        return random.choice(candidates) if candidates else "默认场景"

    if house_type in allowed_map:
        allowed = allowed_map[house_type]
        candidates = [s for s in all_scenes if s in allowed and s not in used_scenes]
        if not candidates:
            candidates = [s for s in all_scenes if s in allowed]
        if candidates:
            return random.choice(candidates)

    if house_type in forbidden_map:
        forbidden = forbidden_map[house_type]
        candidates = [s for s in all_scenes if s not in forbidden and s not in used_scenes]
        if not candidates:
            candidates = [s for s in all_scenes if s not in forbidden]
        if candidates:
            return random.choice(candidates)

    candidates = [s for s in all_scenes if s not in used_scenes]
    if not candidates:
        candidates = all_scenes
    return random.choice(candidates) if candidates else "默认场景"


def _get_title_scenes(excel_path: str) -> List[str]:
    try:
        df = pd.read_excel(excel_path, sheet_name="产品标题")
        for col in ("场景", "标题场景"):
            if col in df.columns:
                scenes = df[col].dropna().astype(str).str.strip().unique().tolist()
                return [s for s in scenes if s] or ["默认场景"]
        return ["默认场景"]
    except Exception:
        return ["默认场景"]


def _get_random_image_from_lib(position: int, house_type: Optional[str], main_image_lib: Dict):
    lib_path = main_image_lib.get(str(position)) or main_image_lib.get(position)
    if not lib_path or not os.path.exists(lib_path):
        return None

    all_images = [f for f in os.listdir(lib_path) if f.lower().endswith((".jpg", ".jpeg", ".png"))]
    if not all_images:
        return None

    if position == 5:
        return os.path.join(lib_path, random.choice(all_images))

    effective_house_type = house_type
    if effective_house_type is None:
        if position in (2, 6):
            effective_house_type = "快拼箱"
        elif position in (3, 4):
            kuaipin_images = []
            standard_images = []
            for img in all_images:
                img_house_type = _parse_lib_house_type(img, position)
                if img_house_type == "快拼箱":
                    kuaipin_images.append(img)
                elif img_house_type == "标箱":
                    standard_images.append(img)
            candidate_images = kuaipin_images + standard_images
            if candidate_images:
                return os.path.join(lib_path, random.choice(candidate_images))
            return os.path.join(lib_path, random.choice(all_images))
        else:
            return os.path.join(lib_path, random.choice(all_images))

    exact_matches = []
    fuzzy_matches = []
    kuaipin_images = []
    standard_images = []

    for img in all_images:
        img_house_type = _parse_lib_house_type(img, position)
        if img_house_type is not None:
            if img_house_type == effective_house_type:
                exact_matches.append(img)
            elif _fuzzy_match(effective_house_type, img_house_type):
                fuzzy_matches.append(img)
            elif img_house_type == "快拼箱":
                kuaipin_images.append(img)
            elif img_house_type == "标箱":
                standard_images.append(img)

    cache_key = (position, effective_house_type)
    if exact_matches:
        if cache_key not in _MAIN_IMAGE_ROUND_ROBIN_CACHE:
            shuffled = exact_matches.copy()
            random.shuffle(shuffled)
            _MAIN_IMAGE_ROUND_ROBIN_CACHE[cache_key] = deque(shuffled)
        queue = _MAIN_IMAGE_ROUND_ROBIN_CACHE[cache_key]
        if not queue:
            shuffled = exact_matches.copy()
            random.shuffle(shuffled)
            queue = deque(shuffled)
            _MAIN_IMAGE_ROUND_ROBIN_CACHE[cache_key] = queue
        chosen_img = queue.popleft()
        return os.path.join(lib_path, chosen_img)

    if fuzzy_matches:
        return os.path.join(lib_path, random.choice(fuzzy_matches))
    if kuaipin_images:
        return os.path.join(lib_path, random.choice(kuaipin_images))
    if standard_images:
        return os.path.join(lib_path, random.choice(standard_images))
    return os.path.join(lib_path, random.choice(all_images))


def _parse_lib_house_type(img: str, position: int) -> Optional[str]:
    name_no_ext = os.path.splitext(img)[0]
    parts = name_no_ext.split("-")
    img_house_type = None

    if len(parts) == 3:
        try:
            pos_in_name = int(parts[1])
            if pos_in_name == position:
                img_house_type = parts[2]
        except ValueError:
            pass

    if img_house_type is None and len(parts) == 3:
        try:
            first_part = int(parts[0])
            if first_part == position:
                img_house_type = parts[1]
        except ValueError:
            pass

    if img_house_type is None and len(parts) == 2:
        try:
            first_part = int(parts[0])
            if first_part == position:
                img_house_type = parts[1]
        except ValueError:
            pass

    return img_house_type


def _load_processed_products(norm_cfg: Dict) -> set:
    processed = set()
    file_path = norm_cfg.get("processed_products_file")
    if not file_path:
        return processed
    try:
        if os.path.exists(file_path):
            with open(file_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        processed.add(line)
    except Exception:
        pass
    return processed


def _save_processed_product(product_key: str, norm_cfg: Dict):
    file_path = norm_cfg.get("processed_products_file")
    if not file_path:
        return
    try:
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        with open(file_path, "a", encoding="utf-8") as f:
            f.write(f"{product_key}\n")
    except Exception:
        pass


def _format_size(size_bytes: int) -> str:
    if size_bytes < 1024:
        return f"{size_bytes}B"
    if size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f}KB"
    if size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f}MB"
    return f"{size_bytes / (1024 * 1024 * 1024):.1f}GB"

# -*- coding: utf-8 -*-
"""云端 app_runtime_settings 表：API/模型/积分单价等全局配置的权威存储。"""
from __future__ import annotations

import json
import os
import time
from typing import Any, Dict, Optional

from app.core.admin_runtime_config import (
    AI_IMAGE_GEN_ADMIN_KEYS,
    DATA_ANALYSIS_ADMIN_KEYS,
    should_skip_runtime_secret_merge,
)
from app.core.logger import setup_logger
from app.core.settings import DATA_DIR, PointsPricingConfig

logger = setup_logger("app_runtime_settings")

POINTS_PRICING_KEYS = (
    "title_optimize_per_item",
    "traffic_ai_per_run",
    "ai_image_1k",
    "ai_image_2k",
    "ai_image_4k",
)

RUNTIME_CONFIG_FILE = os.path.join(DATA_DIR, "admin_runtime_config.json")
_SETTINGS_ROW_ID = 1


def _default_points_pricing_dict() -> Dict[str, float]:
    pp = PointsPricingConfig()
    return {
        "title_optimize_per_item": float(pp.title_optimize_per_item),
        "traffic_ai_per_run": float(pp.traffic_ai_per_run),
        "ai_image_1k": float(pp.ai_image_1k),
        "ai_image_2k": float(pp.ai_image_2k),
        "ai_image_4k": float(pp.ai_image_4k),
    }


def _empty_payload() -> Dict[str, Any]:
    return {
        "revision": 0,
        "updated_at": "",
        "updated_by": "",
        "data_analysis": {},
        "ai_image_gen": {},
        "points_pricing": _default_points_pricing_dict(),
    }


def _json_loads(raw: Any, default: Dict[str, Any]) -> Dict[str, Any]:
    if isinstance(raw, dict):
        return dict(raw)
    if not raw:
        return dict(default)
    try:
        data = json.loads(str(raw))
        return dict(data) if isinstance(data, dict) else dict(default)
    except Exception:
        return dict(default)


def _pick_section(incoming: Optional[Dict[str, Any]], allowed: tuple[str, ...]) -> Dict[str, Any]:
    if not isinstance(incoming, dict):
        return {}
    return {k: incoming[k] for k in allowed if k in incoming}


def _pick_points_pricing(incoming: Optional[Dict[str, Any]]) -> Dict[str, float]:
    if not isinstance(incoming, dict):
        return {}
    out: Dict[str, float] = {}
    for k in POINTS_PRICING_KEYS:
        if k not in incoming or incoming[k] is None:
            continue
        try:
            out[k] = float(incoming[k])
        except (TypeError, ValueError):
            continue
    return out


def ensure_app_runtime_settings_schema(cur) -> None:
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS app_runtime_settings (
          id INTEGER PRIMARY KEY CHECK (id = 1),
          data_analysis_json TEXT NOT NULL DEFAULT '{}',
          ai_image_gen_json TEXT NOT NULL DEFAULT '{}',
          points_pricing_json TEXT NOT NULL DEFAULT '{}',
          revision INTEGER NOT NULL DEFAULT 0,
          updated_at TEXT NOT NULL DEFAULT '',
          updated_by TEXT NULL
        )
        """
    )


def _conn():
    from app.services.membership_service import _conn as membership_conn

    return membership_conn()


def _load_legacy_json_file() -> Dict[str, Any]:
    if not os.path.isfile(RUNTIME_CONFIG_FILE):
        return _empty_payload()
    try:
        with open(RUNTIME_CONFIG_FILE, "r", encoding="utf-8-sig") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return _empty_payload()
        out = _empty_payload()
        out["revision"] = int(data.get("revision") or 0)
        out["updated_at"] = str(data.get("updated_at") or "")
        out["data_analysis"] = _pick_section(data.get("data_analysis"), DATA_ANALYSIS_ADMIN_KEYS)
        out["ai_image_gen"] = _pick_section(data.get("ai_image_gen"), AI_IMAGE_GEN_ADMIN_KEYS)
        pp = _pick_points_pricing(data.get("points_pricing"))
        if pp:
            out["points_pricing"] = {**out["points_pricing"], **pp}
        return out
    except Exception as e:
        logger.warning("read legacy admin_runtime_config.json failed: %s", e)
        return _empty_payload()


def _load_points_pricing_from_local_config() -> Dict[str, float]:
    try:
        from app.core.settings import get_config

        pp = get_config().points_pricing
        return {
            "title_optimize_per_item": float(pp.title_optimize_per_item),
            "traffic_ai_per_run": float(pp.traffic_ai_per_run),
            "ai_image_1k": float(pp.ai_image_1k),
            "ai_image_2k": float(pp.ai_image_2k),
            "ai_image_4k": float(pp.ai_image_4k),
        }
    except Exception:
        return _default_points_pricing_dict()


def migrate_legacy_runtime_to_db_if_needed() -> bool:
    """DB 无有效 revision 时，从 admin_runtime_config.json（及本地 config 单价）导入。"""
    try:
        from app.services.membership_service import init_db

        init_db()
        conn = _conn()
        cur = conn.cursor()
        ensure_app_runtime_settings_schema(cur)
        row = cur.execute(
            "SELECT revision FROM app_runtime_settings WHERE id=? LIMIT 1",
            (_SETTINGS_ROW_ID,),
        ).fetchone()
        if row and int(row["revision"] or 0) > 0:
            conn.close()
            return False

        legacy = _load_legacy_json_file()
        if int(legacy.get("revision") or 0) <= 0:
            legacy["points_pricing"] = _load_points_pricing_from_local_config()
            legacy["revision"] = int(time.time())
            legacy["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        elif not _pick_points_pricing(legacy.get("points_pricing")):
            legacy["points_pricing"] = _load_points_pricing_from_local_config()

        cur.execute(
            """
            INSERT INTO app_runtime_settings(
              id, data_analysis_json, ai_image_gen_json, points_pricing_json,
              revision, updated_at, updated_by
            ) VALUES(?,?,?,?,?,?,?)
            ON CONFLICT(id) DO UPDATE SET
              data_analysis_json=excluded.data_analysis_json,
              ai_image_gen_json=excluded.ai_image_gen_json,
              points_pricing_json=excluded.points_pricing_json,
              revision=excluded.revision,
              updated_at=excluded.updated_at,
              updated_by=excluded.updated_by
            """,
            (
                _SETTINGS_ROW_ID,
                json.dumps(legacy.get("data_analysis") or {}, ensure_ascii=False),
                json.dumps(legacy.get("ai_image_gen") or {}, ensure_ascii=False),
                json.dumps(legacy.get("points_pricing") or _default_points_pricing_dict(), ensure_ascii=False),
                int(legacy.get("revision") or int(time.time())),
                str(legacy.get("updated_at") or time.strftime("%Y-%m-%d %H:%M:%S")),
                str(legacy.get("updated_by") or "migrate"),
            ),
        )
        conn.commit()
        conn.close()
        logger.info("migrated legacy runtime config into app_runtime_settings (revision=%s)", legacy.get("revision"))
        return True
    except Exception as e:
        logger.warning("migrate legacy runtime to db failed: %s", e)
        return False


def load_app_runtime_settings() -> Dict[str, Any]:
    migrate_legacy_runtime_to_db_if_needed()
    try:
        from app.services.membership_service import init_db

        init_db()
        conn = _conn()
        cur = conn.cursor()
        ensure_app_runtime_settings_schema(cur)
        row = cur.execute(
            """
            SELECT data_analysis_json, ai_image_gen_json, points_pricing_json,
                   revision, updated_at, updated_by
            FROM app_runtime_settings WHERE id=? LIMIT 1
            """,
            (_SETTINGS_ROW_ID,),
        ).fetchone()
        conn.close()
        if not row:
            return _empty_payload()
        pp_default = _default_points_pricing_dict()
        pp = _json_loads(row["points_pricing_json"], pp_default)
        for k, v in pp_default.items():
            pp.setdefault(k, v)
        return {
            "revision": int(row["revision"] or 0),
            "updated_at": str(row["updated_at"] or ""),
            "updated_by": str(row["updated_by"] or ""),
            "data_analysis": _json_loads(row["data_analysis_json"], {}),
            "ai_image_gen": _json_loads(row["ai_image_gen_json"], {}),
            "points_pricing": pp,
        }
    except Exception as e:
        logger.warning("load_app_runtime_settings failed: %s", e)
        return _load_legacy_json_file()


def save_app_runtime_settings(
    *,
    data_analysis: Optional[Dict[str, Any]] = None,
    ai_image_gen: Optional[Dict[str, Any]] = None,
    points_pricing: Optional[Dict[str, Any]] = None,
    merge: bool = True,
    updated_by: str = "",
) -> Dict[str, Any]:
    from app.services.membership_service import init_db

    init_db()
    current = load_app_runtime_settings() if merge else _empty_payload()

    if isinstance(data_analysis, dict):
        da = dict(current.get("data_analysis") or {})
        for k, v in _pick_section(data_analysis, DATA_ANALYSIS_ADMIN_KEYS).items():
            if should_skip_runtime_secret_merge(k, v, da.get(k)):
                continue
            da[k] = v
        current["data_analysis"] = da
    if isinstance(ai_image_gen, dict):
        ai = dict(current.get("ai_image_gen") or {})
        for k, v in _pick_section(ai_image_gen, AI_IMAGE_GEN_ADMIN_KEYS).items():
            if should_skip_runtime_secret_merge(k, v, ai.get(k)):
                continue
            ai[k] = v
        current["ai_image_gen"] = ai
    if isinstance(points_pricing, dict):
        pp = dict(current.get("points_pricing") or _default_points_pricing_dict())
        pp.update(_pick_points_pricing(points_pricing))
        current["points_pricing"] = pp

    current["revision"] = int(time.time())
    current["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    if updated_by:
        current["updated_by"] = str(updated_by).strip()

    conn = _conn()
    cur = conn.cursor()
    ensure_app_runtime_settings_schema(cur)
    cur.execute(
        """
        INSERT INTO app_runtime_settings(
          id, data_analysis_json, ai_image_gen_json, points_pricing_json,
          revision, updated_at, updated_by
        ) VALUES(?,?,?,?,?,?,?)
        ON CONFLICT(id) DO UPDATE SET
          data_analysis_json=excluded.data_analysis_json,
          ai_image_gen_json=excluded.ai_image_gen_json,
          points_pricing_json=excluded.points_pricing_json,
          revision=excluded.revision,
          updated_at=excluded.updated_at,
          updated_by=excluded.updated_by
        """,
        (
            _SETTINGS_ROW_ID,
            json.dumps(current.get("data_analysis") or {}, ensure_ascii=False),
            json.dumps(current.get("ai_image_gen") or {}, ensure_ascii=False),
            json.dumps(current.get("points_pricing") or _default_points_pricing_dict(), ensure_ascii=False),
            int(current["revision"]),
            str(current["updated_at"]),
            str(current.get("updated_by") or "") or None,
        ),
    )
    conn.commit()
    conn.close()

    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(RUNTIME_CONFIG_FILE, "w", encoding="utf-8", newline="\n") as f:
            json.dump(
                {
                    "revision": current["revision"],
                    "updated_at": current["updated_at"],
                    "updated_by": current.get("updated_by") or "",
                    "data_analysis": current.get("data_analysis") or {},
                    "ai_image_gen": current.get("ai_image_gen") or {},
                    "points_pricing": current.get("points_pricing") or {},
                },
                f,
                ensure_ascii=False,
                indent=2,
            )
            f.write("\n")
    except Exception as e:
        logger.warning("write runtime json backup failed: %s", e)

    return current


def get_app_runtime_revision() -> int:
    return int(load_app_runtime_settings().get("revision") or 0)


def get_effective_points_pricing_config() -> PointsPricingConfig:
    """云端：读 DB；桌面端：读 pull 同步后的 config.json。"""
    from app.services.membership_service import _is_cloud_membership_host

    if _is_cloud_membership_host():
        pp = load_app_runtime_settings().get("points_pricing") or {}
        defaults = _default_points_pricing_dict()
        return PointsPricingConfig(
            title_optimize_per_item=float(pp.get("title_optimize_per_item", defaults["title_optimize_per_item"])),
            traffic_ai_per_run=float(pp.get("traffic_ai_per_run", defaults["traffic_ai_per_run"])),
            ai_image_1k=float(pp.get("ai_image_1k", defaults["ai_image_1k"])),
            ai_image_2k=float(pp.get("ai_image_2k", defaults["ai_image_2k"])),
            ai_image_4k=float(pp.get("ai_image_4k", defaults["ai_image_4k"])),
        )

    from app.core.settings import get_config

    return get_config().points_pricing

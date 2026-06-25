# -*- coding: utf-8 -*-
"""API 路由包。惰性加载子模块，避免 cloud_app 只引 membership 时拉起 config_router 等重依赖。"""
from __future__ import annotations

from importlib import import_module
from typing import Any

__all__ = [
    "config_router",
    "upload_router",
    "image_router",
    "data_router",
    "analysis_router",
    "task_router",
    "ws_router",
    "membership_router",
    "video_bind_router",
    "page_scan_router",
]

_SUBMODULES = {
    "config_router": "app.api.config_router",
    "upload_router": "app.api.upload_router",
    "image_router": "app.api.image_router",
    "data_router": "app.api.data_router",
    "analysis_router": "app.api.analysis_router",
    "task_router": "app.api.task_router",
    "ws_router": "app.api.ws_router",
    "membership_router": "app.api.membership_router",
    "video_bind_router": "app.api.video_bind_router",
    "page_scan_router": "app.api.page_scan_router",
}


def __getattr__(name: str) -> Any:
    path = _SUBMODULES.get(name)
    if path:
        return import_module(path)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

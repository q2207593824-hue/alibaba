# -*- coding: utf-8 -*-
"""
云端专用轻量 FastAPI（仅会员 API + health）。
宝塔 run_cloud.py 默认加载此应用，避免完整 main.py 拉取发品/自动化等重依赖导致启动慢或 504。
"""
from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# 勿 from app.api import membership_router —— __init__.py 会拉起 config_router 等全量路由，
# 云端代码未整包同步时易 ImportError（如 admin_runtime_config 缺函数）。
from app.api.membership_router import router as membership_router


@asynccontextmanager
async def _cloud_lifespan(app: FastAPI):
    """后台初始化 DB，不阻塞 health 与首屏请求。"""
    async def _bg_init() -> None:
        try:
            from app.services.membership_service import init_db

            await asyncio.to_thread(init_db)
        except Exception as e:
            print(f"[cloud_app] init_db background failed: {e}", flush=True)

    task = asyncio.create_task(_bg_init())
    yield
    task.cancel()


app = FastAPI(
    title="Ali Membership Cloud API",
    description="云端会员/积分权威服务",
    version="1.0.0",
    lifespan=_cloud_lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# health 必须在 membership 路由之前注册，且不参与 membership startup 阻塞
@app.get("/api/health")
async def health_check():
    return {
        "status": "ok",
        "service": "ali-membership-cloud",
        "cloud_host": os.getenv("MEMBERSHIP_IS_CLOUD_HOST", ""),
    }


app.include_router(membership_router, prefix="/api/membership", tags=["会员中心"])

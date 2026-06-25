# -*- coding: utf-8 -*-
"""
WebSocket API - 实时日志推送和任务状态更新
"""
import asyncio
import json
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from app.core.membership_guard import extract_bearer

from app.core.logger import log_buffer
from app.core.task_manager import task_manager
from app.core.settings import config_manager
from app.services.membership_service import can_use_by_token

router = APIRouter()


def _ws_access_allowed(token: str = "", admin_key: str = "") -> bool:
    """WebSocket 鉴权：会员 token 或管理员钥匙（与 HTTP X-Admin-Key 一致）。"""
    try:
        cfg = config_manager.load()
        expected = str(getattr(cfg.payment, "admin_api_key", "") or "").strip()
    except Exception:
        expected = ""
    if expected and str(admin_key or "").strip() == expected:
        return True
    if token and can_use_by_token(token):
        return True
    return False


class ConnectionManager:
    """WebSocket 连接管理器"""
    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        for conn in self.active_connections:
            try:
                await conn.send_json(message)
            except Exception:
                pass


ws_manager = ConnectionManager()


@router.websocket("/logs")
async def websocket_logs(websocket: WebSocket):
    """实时日志推送"""
    auth = websocket.headers.get("authorization")
    token = str(websocket.query_params.get("token") or "").strip()
    admin_key = str(websocket.query_params.get("admin_key") or "").strip()
    if not token and auth:
        try:
            token = extract_bearer(auth)
        except Exception:
            token = ""
    if not _ws_access_allowed(token, admin_key):
        await websocket.close(code=4403)
        return

    await ws_manager.connect(websocket)
    try:
        # 先发送最近的日志历史
        recent = log_buffer.get_recent(50)
        for entry in recent:
            await websocket.send_json({"type": "log", "data": entry})

        # 持续推送新日志
        while True:
            entry = log_buffer.get_nowait()
            if entry:
                await websocket.send_json({"type": "log", "data": entry})
            else:
                await asyncio.sleep(0.5)
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)
    except Exception:
        ws_manager.disconnect(websocket)


@router.websocket("/tasks")
async def websocket_tasks(websocket: WebSocket):
    """实时任务状态推送"""
    auth = websocket.headers.get("authorization")
    try:
        token = extract_bearer(auth)
        if not can_use_by_token(token):
            await websocket.close(code=4403)
            return
    except Exception:
        await websocket.close(code=4401)
        return

    await ws_manager.connect(websocket)
    try:
        while True:
            tasks = task_manager.get_all_tasks()
            await websocket.send_json({"type": "tasks", "data": tasks})
            await asyncio.sleep(1)
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)
    except Exception:
        ws_manager.disconnect(websocket)

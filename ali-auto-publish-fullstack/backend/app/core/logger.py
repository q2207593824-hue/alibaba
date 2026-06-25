# -*- coding: utf-8 -*-
"""
日志系统 - 支持文件+控制台+WebSocket实时推送
"""
import os
import logging
import queue
from datetime import datetime
from typing import Optional

from app.core.settings import DATA_DIR

LOG_DIR = os.path.join(DATA_DIR, "logs")
os.makedirs(LOG_DIR, exist_ok=True)


class LogBuffer:
    """日志缓冲区 - 供 WebSocket 实时推送"""
    def __init__(self, maxsize: int = 2000):
        self._queue: queue.Queue = queue.Queue(maxsize=maxsize)
        self._history: list = []

    def put(self, record: dict):
        if self._queue.full():
            try:
                self._queue.get_nowait()
            except queue.Empty:
                pass
        self._queue.put(record)
        self._history.append(record)
        if len(self._history) > 2000:
            self._history = self._history[-1000:]

    def get_recent(self, count: int = 100) -> list:
        return self._history[-count:]

    def get_nowait(self) -> Optional[dict]:
        try:
            return self._queue.get_nowait()
        except queue.Empty:
            return None


# 全局日志缓冲区
log_buffer = LogBuffer()


class WebSocketHandler(logging.Handler):
    """将日志记录推送到 WebSocket 缓冲区"""
    def emit(self, record):
        try:
            log_entry = {
                "timestamp": datetime.fromtimestamp(record.created).strftime("%Y-%m-%d %H:%M:%S"),
                "level": record.levelname,
                "module": record.name,
                "message": self.format(record),
            }
            log_buffer.put(log_entry)
        except Exception:
            pass


def setup_logger(name: str = "ali_publish", level: int = logging.INFO) -> logging.Logger:
    """创建并配置日志器"""
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    logger.setLevel(level)
    formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")

    # 控制台输出
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # 文件输出
    log_file = os.path.join(LOG_DIR, f"{name}_{datetime.now().strftime('%Y%m%d')}.log")
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    # WebSocket 推送
    ws_handler = WebSocketHandler()
    ws_handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(ws_handler)

    return logger


# 默认日志器
logger = setup_logger()

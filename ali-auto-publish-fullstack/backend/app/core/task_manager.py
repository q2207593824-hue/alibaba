# -*- coding: utf-8 -*-
"""
任务管理器 - 管理后台异步任务的生命周期
支持启动、暂停、停止、状态查询
"""
import threading
import time
from enum import Enum
from typing import Any, Callable, Dict, Optional
from datetime import datetime


class TaskStatus(str, Enum):
    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    STOPPING = "stopping"
    COMPLETED = "completed"
    FAILED = "failed"


class TaskInfo:
    """单个任务的状态信息"""
    def __init__(self, task_id: str, name: str):
        self.task_id = task_id
        self.name = name
        self.status = TaskStatus.IDLE
        self.progress: int = 0
        self.total: int = 0
        self.current_step: str = ""
        self.started_at: Optional[str] = None
        self.finished_at: Optional[str] = None
        self.error: Optional[str] = None
        self.result: Any = None
        self._stop_event = threading.Event()
        self._pause_event = threading.Event()
        self._pause_event.set()  # 默认不暂停
        self._thread: Optional[threading.Thread] = None

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "name": self.name,
            "status": self.status.value,
            "progress": self.progress,
            "total": self.total,
            "current_step": self.current_step,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "error": self.error,
        }

    def should_stop(self) -> bool:
        return self._stop_event.is_set()

    def wait_if_paused(self):
        """如果任务被暂停，则阻塞等待（可响应停止信号）"""
        while not self._pause_event.is_set():
            if self.should_stop():
                break
            time.sleep(0.1)


class TaskManager:
    """全局任务管理器"""
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._tasks: Dict[str, TaskInfo] = {}
            return cls._instance

    def create_task(self, task_id: str, name: str) -> TaskInfo:
        """创建任务"""
        task = TaskInfo(task_id, name)
        self._tasks[task_id] = task
        return task

    def start_task(self, task_id: str, target: Callable, args: tuple = ()) -> bool:
        """启动任务"""
        task = self._tasks.get(task_id)
        if not task:
            return False
        if task.status == TaskStatus.RUNNING:
            return False

        task.status = TaskStatus.RUNNING
        task.started_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        task._stop_event.clear()
        task._pause_event.set()

        def wrapper():
            try:
                target(task, *args)
                if task.should_stop():
                    task.status = TaskStatus.COMPLETED
                    task.current_step = "已停止"
                elif task.status in (TaskStatus.RUNNING, TaskStatus.PAUSED, TaskStatus.STOPPING):
                    task.status = TaskStatus.COMPLETED
            except Exception as e:
                task.status = TaskStatus.FAILED
                task.error = str(e)
            finally:
                task.finished_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        task._thread = threading.Thread(target=wrapper, daemon=True)
        task._thread.start()
        return True

    def pause_task(self, task_id: str) -> bool:
        task = self._tasks.get(task_id)
        if task and task.status == TaskStatus.RUNNING:
            task._pause_event.clear()
            task.status = TaskStatus.PAUSED
            return True
        return False

    def resume_task(self, task_id: str) -> bool:
        task = self._tasks.get(task_id)
        if task and task.status == TaskStatus.PAUSED:
            task._pause_event.set()
            task.status = TaskStatus.RUNNING
            return True
        return False

    def stop_task(self, task_id: str) -> bool:
        task = self._tasks.get(task_id)
        if task and task.status in (TaskStatus.RUNNING, TaskStatus.PAUSED):
            task._stop_event.set()
            task._pause_event.set()  # 解除暂停以便线程退出
            task.status = TaskStatus.STOPPING
            task.current_step = "正在停止..."
            return True
        return False

    def get_task(self, task_id: str) -> Optional[TaskInfo]:
        return self._tasks.get(task_id)

    def get_all_tasks(self) -> Dict[str, dict]:
        return {k: v.to_dict() for k, v in self._tasks.items()}

    def remove_task(self, task_id: str):
        self._tasks.pop(task_id, None)

    def clear_stale_failed_tasks(
        self,
        *,
        task_id_prefix: str = "analysis_",
        error_substrings: tuple[str, ...] = (
            "api key",
            "apikey",
            "密钥",
            "脱敏",
            "***",
            "未配置",
            "doubao",
            "runtime",
            "secrets_ready",
        ),
    ) -> int:
        """密钥修复后清除因旧 Key/脱敏导致的 failed 状态，避免 UI 一直显示历史错误。"""
        cleared = 0
        needles = tuple(s.lower() for s in error_substrings if s)
        for task_id, task in list(self._tasks.items()):
            if not str(task_id).startswith(task_id_prefix):
                continue
            if task.status != TaskStatus.FAILED:
                continue
            err = str(task.error or "").lower()
            if not err or not any(n in err for n in needles):
                continue
            task.status = TaskStatus.IDLE
            task.error = None
            task.progress = 0
            task.total = 0
            task.current_step = ""
            task.finished_at = None
            cleared += 1
        return cleared


# 全局实例
task_manager = TaskManager()

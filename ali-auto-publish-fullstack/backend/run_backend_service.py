# -*- coding: utf-8 -*-
"""Windows Service entrypoint for backend.

Service name: AliAutoPublishBackend
"""
import os
import sys
import socket
import threading
from pathlib import Path

import servicemanager
import win32event
import win32service
import win32serviceutil
import uvicorn

BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

# 桌面端默认把数据写到用户目录，避免安装目录不可写
# 服务通常运行在 LocalSystem 下，HOME 可能不可预期，优先使用 ProgramData
program_data = Path(os.getenv("PROGRAMDATA", r"C:\ProgramData"))
default_data_dir = program_data / "AliAutoPublish" / "data"
os.environ.setdefault("ALI_APP_DATA_DIR", str(default_data_dir))

from app.main import app  # noqa: E402


class BackendWindowsService(win32serviceutil.ServiceFramework):
    _svc_name_ = "AliAutoPublishBackend"
    _svc_display_name_ = "Ali Auto Publish Backend Service"
    _svc_description_ = "Provides local backend API for Ali Auto Publish desktop client."

    def __init__(self, args):
        super().__init__(args)
        self.stop_event = win32event.CreateEvent(None, 0, 0, None)
        self.server = None

    def SvcStop(self):
        self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
        if self.server is not None:
            self.server.should_exit = True
        win32event.SetEvent(self.stop_event)

    def SvcDoRun(self):
        servicemanager.LogInfoMsg(f"{self._svc_name_} starting")
        host = os.getenv("BACKEND_HOST", "127.0.0.1")
        port = int(os.getenv("BACKEND_PORT", "8000"))

        config = uvicorn.Config(app, host=host, port=port, log_level="info")
        self.server = uvicorn.Server(config)

        thread = threading.Thread(target=self.server.run, daemon=True)
        thread.start()

        win32event.WaitForSingleObject(self.stop_event, win32event.INFINITE)
        servicemanager.LogInfoMsg(f"{self._svc_name_} stopped")


def main():
    # 支持调试模式直接运行：python run_backend_service.py debug
    if len(sys.argv) == 1:
        servicemanager.Initialize()
        servicemanager.PrepareToHostSingle(BackendWindowsService)
        servicemanager.StartServiceCtrlDispatcher()
    else:
        win32serviceutil.HandleCommandLine(BackendWindowsService)


if __name__ == "__main__":
    main()

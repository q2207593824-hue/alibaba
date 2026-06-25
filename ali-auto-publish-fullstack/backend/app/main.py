# -*- coding: utf-8 -*-
"""
FastAPI 主应用入口 (已优化为支持 PyInstaller 打包)
"""
import os
import sys
import webbrowser
import threading
import time
import socket

IS_DESKTOP_ENV = os.getenv("ALI_DESKTOP", "").strip().lower() in {"1", "true", "yes"}


def _should_auto_open_browser() -> bool:
    if IS_DESKTOP_ENV:
        return False
    if os.getenv("ALI_DISABLE_BROWSER_OPEN", "").strip().lower() in {"1", "true", "yes"}:
        return False
    if os.getenv("MEMBERSHIP_IS_CLOUD_HOST", "").strip().lower() in {"1", "true", "yes"}:
        return False
    return True
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse

from app.core.settings import config_manager
from app.core.logger import logger
from app.api import config_router, upload_router, image_router, data_router, analysis_router, task_router, ws_router, membership_router, video_bind_router, page_scan_router


# ================== 🔴 打包支持工具函数 🔴 ==================
def get_resource_path(relative_path: str) -> str:
    """
    获取资源文件的绝对路径。
    兼容开发环境 (python 运行) 和 生产环境 (pyinstaller 打包后的 exe)。
    """
    if getattr(sys, 'frozen', False):
        # 如果是打包后的 exe，资源在 _MEIPASS 临时目录中
        base_path = sys._MEIPASS
    else:
        # 如果是开发环境，资源在当前脚本的上级目录的 frontend/dist
        base_path = os.path.dirname(os.path.abspath(__file__))
        # 开发环境下，main.py 在 backend/app/，所以 dist 在 ../../frontend/dist
        # 但为了统一，我们假设打包时把数据放到了 "frontend/dist" 相对路径下
        # 这里我们直接返回基于 base_path 的拼接，具体看下面的调用
    
    return os.path.join(base_path, relative_path)

# 定义前端静态文件目录的相对路径 (必须与 pyinstaller --add-data 的目标路径一致)
FRONTEND_DIST_DIR = "frontend/dist"
FRONTEND_DEV_PORTS = [3000, 5173, 4173]


def detect_frontend_dev_url() -> str:
    for port in FRONTEND_DEV_PORTS:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.25):
                return f"http://127.0.0.1:{port}"
        except OSError:
            continue
    return ""

@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    logger.info("🚀 正在启动 Ali Auto Publish 后端服务...")
    try:
        from app.services.membership_service import apply_cloud_network_bypass

        apply_cloud_network_bypass()
    except Exception:
        pass

    # 1. 加载配置
    config_manager.load()
    logger.info("✅ 配置加载完成")
    try:
        from app.core.desktop_bootstrap import ensure_desktop_admin_api_key
        from app.core.admin_runtime_config import purge_masked_runtime_secrets_from_local

        ensure_desktop_admin_api_key()
        purge_masked_runtime_secrets_from_local()
    except Exception as e:
        logger.warning(f"admin_api_key bootstrap skipped: {e}")
    try:
        from app.services.membership_service import (
            _is_cloud_membership_host,
            cloud_quick_unreachable,
            use_cloud_points,
        )

        if _is_cloud_membership_host():
            logger.info(
                "☁️ 云端会员主机模式已启用 (MEMBERSHIP_IS_CLOUD_HOST=1)："
                "登录/积分仅读写本机 membership.db，不请求公网 membership API"
            )
        elif use_cloud_points() and cloud_quick_unreachable():
            os.environ["MEMBERSHIP_POINTS_SOURCE"] = "local"
            logger.warning(
                "⚠️ 云端 echo-yiwu.cloud 不可达，已自动切换 MEMBERSHIP_POINTS_SOURCE=local（本地会员库）"
            )
        logger.info(
            f"📋 会员积分模式: use_cloud_points={use_cloud_points()}, "
            f"MEMBERSHIP_POINTS_SOURCE={os.getenv('MEMBERSHIP_POINTS_SOURCE', '(default)')}"
        )
    except Exception as e:
        logger.warning(f"会员模式自检日志跳过: {e}")

    try:
        from app.services.membership_service import ensure_membership_db_ready

        ensure_membership_db_ready()
        logger.info("✅ 会员数据库 schema 已就绪")
    except Exception as e:
        logger.warning(f"会员数据库初始化跳过: {e}")

    # 2. 前端资源挂载/开发代理
    frontend_dev_url = os.getenv("FRONTEND_DEV_URL", "").strip() or detect_frontend_dev_url()
    if frontend_dev_url:
        logger.info(f"📡 检测到开发前端地址，跳过静态资源挂载: {frontend_dev_url}")
        if _should_auto_open_browser():
            def open_browser_task():
                time.sleep(1.5)
                logger.info(f"🌐 正在自动打开浏览器: {frontend_dev_url}")
                webbrowser.open(frontend_dev_url)

            threading.Thread(target=open_browser_task, daemon=True).start()
        else:
            logger.info("☁️ 云端/桌面模式：跳过自动打开系统浏览器")
    else:
        if getattr(sys, 'frozen', False):
            static_root = os.path.join(sys._MEIPASS, FRONTEND_DIST_DIR)
        else:
            static_root = os.path.join(os.path.dirname(__file__), "..", "..", "frontend", "dist")

        if os.path.exists(static_root) and os.path.exists(os.path.join(static_root, "index.html")):
            logger.info(f"📂 检测到前端文件，正在挂载静态资源: {static_root}")
            
            assets_path = os.path.join(static_root, "assets")
            if os.path.exists(assets_path):
                app.mount("/assets", StaticFiles(directory=assets_path), name="assets")
            
            @app.get("/{full_path:path}")
            async def serve_frontend(full_path: str):
                if full_path.startswith("api"):
                    return {"detail": "API endpoint not found"}
                
                file_path = os.path.join(static_root, full_path)
                if os.path.isfile(file_path):
                    return FileResponse(file_path)
                
                return FileResponse(os.path.join(static_root, "index.html"))
                
            logger.info("✅ 前端服务已就绪")
            
            if _should_auto_open_browser():
                def open_browser_task():
                    time.sleep(1.5)
                    port = os.getenv("BACKEND_PORT", "8000").strip() or "8000"
                    url = f"http://127.0.0.1:{port}"
                    logger.info(f"🌐 正在自动打开浏览器: {url}")
                    webbrowser.open(url)

                threading.Thread(target=open_browser_task, daemon=True).start()
            else:
                logger.info("☁️ 云端/桌面模式：跳过自动打开系统浏览器")
        else:
            logger.warning(f"⚠️ 未找到前端文件 (路径: {static_root})。仅运行 API 服务。")
            logger.warning("💡 如果是打包后的 exe，请检查 --add-data 参数是否正确。")

    yield

    # 若任务期间曾启动过 Selenium，退出时关闭共享会话
    try:
        from app.services.automation.browser_manager import BrowserManager
        BrowserManager.shutdown_shared()
    except Exception:
        pass
    logger.info("🛑 后端服务已关闭")


app = FastAPI(
    title="Ali Auto Publish API",
    description="阿里巴巴国际站自动发品系统 - 后端API",
    version="1.0.0",
    lifespan=lifespan,
)


@app.exception_handler(HTTPException)
async def _http_exception_handler(request: Request, exc: HTTPException):
    """统一透传 HTTPException headers，避免 X-Auth-Reason 等诊断头丢失。"""
    headers = dict(exc.headers or {})
    content = {"detail": exc.detail}
    if "x-auth-reason" in {str(k).lower() for k in headers.keys()}:
        logger.info(
            f"http_exception: path={request.url.path}, status={exc.status_code}, reason={headers.get('X-Auth-Reason') or headers.get('x-auth-reason')}"
        )
    return JSONResponse(status_code=exc.status_code, content=content, headers=headers)

# CORS 配置
# 🔴 更新：允许更多来源，包括打包后可能的情况
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173", 
        "http://localhost:3000", 
        "http://127.0.0.1:5173", 
        "http://127.0.0.1:3000",
        "http://localhost:4173", # 预览模式
        "null" # 有时本地文件协议需要
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ===================== 注册 API 路由 =====================
app.include_router(config_router.router, prefix="/api/config", tags=["配置管理"])
app.include_router(upload_router.router, prefix="/api/upload", tags=["产品上传"])
app.include_router(image_router.router, prefix="/api/images", tags=["图片管理"])
app.include_router(data_router.router, prefix="/api/data", tags=["数据下载"])
app.include_router(analysis_router.router, prefix="/api/analysis", tags=["数据分析"])
app.include_router(task_router.router, prefix="/api/tasks", tags=["任务管理"])
app.include_router(ws_router.router, prefix="/api/ws", tags=["WebSocket"])
app.include_router(membership_router.router, prefix="/api/membership", tags=["会员中心"])
app.include_router(video_bind_router.router, prefix="/api/video-bind", tags=["新品绑定视频"])
app.include_router(page_scan_router.router, prefix="/api/page-scan", tags=["发品页扫描"])


@app.get("/api/health")
async def health_check():
    """健康检查"""
    return {"status": "ok", "service": "ali-auto-publish-backend"}

# 注意：不需要手动写 uvicorn.run，通常通过命令行启动
# 如果要写成独立脚本运行，可以在底部加：
# ===================== 🚀 程序入口 (专为 PyInstaller 打包设计) =====================
if __name__ == "__main__":
    import uvicorn
    
    print("✅ 程序已启动！正在初始化服务器...")
    # 确保输出立即刷新到控制台，防止缓冲导致看不到
    import sys
    sys.stdout.flush()

    try:
        # 启动 UVicorn 服务器
        # host="0.0.0.0" 允许局域网访问，port=8000 是默认端口
        uvicorn.run(
            app, 
            host="0.0.0.0", 
            port=8000, 
            log_level="info"
        )


    except Exception as e:
        # 🔴 关键：捕获所有异常并打印，防止窗口闪退
        print(f"\n❌ 发生严重错误，服务启动失败: {e}")
        import traceback
        traceback.print_exc()  # 打印详细堆栈信息
        
        print("\n💡 提示：请检查端口是否被占用，或前端资源路径是否正确。")
        print("\n按回车键退出窗口...")
        input()  # ⏸️ 暂停程序，让你有时间看清报错信息
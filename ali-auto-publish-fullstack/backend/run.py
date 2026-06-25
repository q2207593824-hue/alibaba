import uvicorn
import os
import sys

# 将 backend 目录添加到 Python 路径，确保可以正确导入 app 模块
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def _apply_dev_membership_defaults() -> None:
    """仅显式离线开发时走本地积分；默认 cloud（与生产一致）。"""
    if os.getenv("MEMBERSHIP_POINTS_SOURCE", "").strip():
        return
    if os.getenv("ALI_DESKTOP", "").strip().lower() in {"1", "true", "yes"}:
        return
    if getattr(sys, "frozen", False):
        return
    offline = os.getenv("ALI_OFFLINE_DEV", "").strip().lower() in {"1", "true", "yes"}
    if offline:
        os.environ["MEMBERSHIP_POINTS_SOURCE"] = "local"
        print("[dev] ALI_OFFLINE_DEV=1 → MEMBERSHIP_POINTS_SOURCE=local（纯离线调试）")
        return
    try:
        from app.services.membership_service import cloud_quick_unreachable

        if cloud_quick_unreachable():
            os.environ["MEMBERSHIP_POINTS_SOURCE"] = "local"
            print(
                "[dev] 检测到云端 echo-yiwu.cloud 不可达 → MEMBERSHIP_POINTS_SOURCE=local（本地会员库登录）"
            )
            print("[dev] 云端恢复后请设置 MEMBERSHIP_POINTS_SOURCE=cloud 或重启并 unset ALI_OFFLINE_DEV")
    except Exception:
        pass


def _pick_backend_port(default: int = 8000) -> int:
    """开发时若 8000 被安装包 ali-backend 占用，自动换到 8001。"""
    import socket

    for port in (default, default + 1, default + 2):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(("0.0.0.0", port))
            return port
        except OSError:
            continue
    return default


def _apply_cloud_network_bypass() -> None:
    try:
        from app.services.membership_service import apply_cloud_network_bypass

        apply_cloud_network_bypass()
    except Exception:
        pass


if __name__ == "__main__":
    print("Starting Alibaba Auto Publish Backend Server...")
    _apply_cloud_network_bypass()
    _apply_dev_membership_defaults()

    reload_enabled = os.getenv("ALI_BACKEND_RELOAD", "0").strip().lower() in {"1", "true", "yes"}
    workers = int(os.getenv("ALI_BACKEND_WORKERS", "1").strip() or "1")
    workers = max(1, workers)

    requested = int(os.getenv("BACKEND_PORT", "8000").strip() or "8000")
    port = _pick_backend_port(requested)
    os.environ["BACKEND_PORT"] = str(port)
    if port != requested:
        print(f"[dev] 端口 {requested} 已被占用，开发后端改用 {port}")

    try:
        frontend_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frontend")
        port_file = os.path.join(frontend_dir, ".dev-backend-port")
        with open(port_file, "w", encoding="utf-8") as f:
            f.write(str(port))
        print(f"[dev] 已写入前端代理端口文件: frontend/.dev-backend-port → {port}")
        if port != requested:
            print(f"[dev] 若前端已在运行，请重启 pnpm run dev 使 Vite 代理指向 {port}")
    except Exception as e:
        print(f"[dev] 写入 .dev-backend-port 失败: {e}")

    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=port,
        reload=reload_enabled,
        workers=workers if not reload_enabled else 1,
        timeout_keep_alive=5,
    )

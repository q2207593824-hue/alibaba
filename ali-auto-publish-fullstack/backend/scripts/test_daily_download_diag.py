# -*- coding: utf-8 -*-
"""日数据下载诊断：直接调用 _download_daily_data 并输出关键状态。"""
import os
import sys
import time
import tempfile

BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND_ROOT)
os.chdir(BACKEND_ROOT)

from app.core.settings import get_config
from app.core.task_manager import TaskInfo
from app.services.data_download_service import _download_daily_data, _get_daily_staging_download_dir


def main():
    cfg = get_config()
    daily_dir = cfg.data_download.daily_output_dir
    staging = _get_daily_staging_download_dir()

    print("=" * 60)
    print("日数据下载诊断")
    print(f"用户目录: {daily_dir}")
    print(f"暂存目录: {staging}")
    print(f"Cookie: {cfg.paths.cookie_file}")
    print("=" * 60)

    task = TaskInfo("diag_daily", "诊断-日数据下载")
    started = time.time()
    try:
        _download_daily_data(task, cfg, None)
    except Exception as e:
        print(f"\n[异常] {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()

    elapsed = time.time() - started
    print("\n" + "=" * 60)
    print(f"耗时: {elapsed:.1f}s")
    print(f"步骤: {task.current_step}")
    print(f"错误: {task.error}")
    print("=" * 60)

    def list_xls(path: str, label: str):
        print(f"\n[{label}] {path}")
        if not os.path.isdir(path):
            print("  (目录不存在)")
            return
        files = [f for f in os.listdir(path) if f.lower().endswith(".xls")]
        if not files:
            print("  (无 xls 文件)")
        else:
            for f in sorted(files, key=lambda x: os.path.getmtime(os.path.join(path, x)), reverse=True)[:10]:
                fp = os.path.join(path, f)
                print(f"  {f}  ({os.path.getsize(fp)} bytes)")

    list_xls(daily_dir, "用户日数据目录")
    list_xls(staging, "Chrome 暂存目录")


if __name__ == "__main__":
    main()

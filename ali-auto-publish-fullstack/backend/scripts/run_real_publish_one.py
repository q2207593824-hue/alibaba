# -*- coding: utf-8 -*-
"""Real publish test: max 1 product (full submit to Alibaba)."""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core.task_manager import TaskInfo, TaskStatus
from app.services.upload_service import get_available_products_list, run_upload_task


def main() -> int:
    avail = get_available_products_list()
    print("=" * 60)
    print("REAL PUBLISH TEST (max_products=1)")
    print("=" * 60)
    if not avail:
        print("FAIL: no publishable products in primary image folder")
        return 1
    p = avail[0]
    print(f"product: {p.get('pid')} | group: {p.get('category')} | file: {p.get('filename')}")
    print("Starting browser + full publish flow (several minutes)...")
    print()

    task = TaskInfo("product_upload_test", "auto publish test")
    task.status = TaskStatus.RUNNING
    started = time.time()

    try:
        run_upload_task(task, mode="batch", max_products=1, scheduled_time=None)
    except Exception as exc:
        print(f"TASK ERROR: {exc}")
        if task.error:
            print(f"task.error: {task.error}")
        return 1

    elapsed = round(time.time() - started, 1)
    print()
    print("=" * 60)
    print(f"step: {task.current_step}")
    print(f"progress: {task.progress}/{task.total}")
    print(f"elapsed: {elapsed}s")
    if task.error:
        print(f"error: {task.error}")
        return 1
    if "成功发布 0" in (task.current_step or ""):
        print("FAIL: publish returned 0 success")
        return 1
    print("DONE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

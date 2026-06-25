# -*- coding: utf-8 -*-
"""一键全量验收：TypeScript 检查 + 各 acceptance 脚本。"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
BASE = os.getenv("ACCEPTANCE_BACKEND", "http://127.0.0.1:8000")
PY = sys.executable


def ok(name: str, passed: bool, detail: str = "") -> bool:
    mark = "PASS" if passed else "FAIL"
    line = f"[{mark}] {name}"
    if detail:
        line += f" — {detail}"
    print(line)
    return passed


def ensure_backend() -> bool:
    try:
        r = requests.get(f"{BASE}/api/health", timeout=5)
        if r.ok:
            return True
    except Exception:
        pass
    backend = ROOT / "backend"
    venv_py = backend / "venv" / "Scripts" / "python.exe"
    py = str(venv_py) if venv_py.is_file() else PY
    print("[info] Starting backend on :8000 ...")
    env = os.environ.copy()
    env["ALI_DESKTOP"] = "1"
    env.setdefault("ALI_APP_DATA_DIR", str(Path(os.environ.get("APPDATA", Path.home())) / "AliAutoPublish" / "data"))
    subprocess.Popen(
        [py, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000"],
        cwd=str(backend),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    for _ in range(40):
        time.sleep(0.5)
        try:
            if requests.get(f"{BASE}/api/health", timeout=2).ok:
                return True
        except Exception:
            pass
    return False


def run_script(name: str) -> tuple[bool, int]:
    path = SCRIPTS / name
    print(f"\n{'=' * 60}\n>>> {name}\n{'=' * 60}")
    proc = subprocess.run([PY, str(path)], cwd=str(ROOT), env=os.environ.copy())
    return proc.returncode == 0, proc.returncode


def run_tsc() -> bool:
    frontend = ROOT / "frontend"
    print(f"\n{'=' * 60}\n>>> frontend pnpm run check\n{'=' * 60}")
    proc = subprocess.run(["pnpm", "run", "check"], cwd=str(frontend), shell=True)
    return proc.returncode == 0


def main() -> int:
    print("=== FULL PROJECT ACCEPTANCE RUNNER ===\n")
    suite_results: list[bool] = []

    if not ensure_backend():
        suite_results.append(ok("suite:backend_up", False, "could not reach /api/health"))
        print("\nAbort: start backend manually.")
        return 1
    suite_results.append(ok("suite:backend_up", True, BASE))

    tsc_ok = run_tsc()
    suite_results.append(ok("suite:typescript_check", tsc_ok, "pnpm run check"))

    for script in (
        "acceptance_comprehensive.py",
        "acceptance_full_system.py",
        "acceptance_crud.py",
        "acceptance_three_issues.py",
        "acceptance_sync_and_points.py",
    ):
        script_path = SCRIPTS / script
        if not script_path.is_file():
            suite_results.append(ok(f"suite:{script}", False, "missing"))
            continue
        passed, code = run_script(script)
        suite_results.append(ok(f"suite:{script}", passed, f"exit={code}"))

    passed = sum(1 for x in suite_results if x)
    total = len(suite_results)
    print(f"\n{'=' * 60}")
    print(f"=== FINAL SUITE: {passed}/{total} suites passed ===")
    print(f"{'=' * 60}")
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())

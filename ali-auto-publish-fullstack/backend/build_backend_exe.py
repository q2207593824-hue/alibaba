# -*- coding: utf-8 -*-
"""Build backend standalone executables with PyInstaller.

使用 ali-backend.spec / ali-backend-service.spec（含 automation hiddenimports）。

生成文件：
- backend/dist/ali-backend/ali-backend.exe  (onedir)
- backend/dist/ali-backend-service.exe      (onefile)
"""
import importlib.util
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DIST_DIR = ROOT / "dist"
BUILD_DIR = ROOT / "build"
SPEC_BACKEND = ROOT / "ali-backend.spec"
SPEC_SERVICE = ROOT / "ali-backend-service.spec"


def run(cmd, cwd=None):
    print("[run]", " ".join(str(c) for c in cmd))
    subprocess.check_call(cmd, cwd=str(cwd) if cwd else None)


def ensure_pyinstaller():
    if importlib.util.find_spec("PyInstaller") is None:
        print("[info] PyInstaller not found, installing...")
        run([sys.executable, "-m", "pip", "install", "pyinstaller"], cwd=ROOT)


def main():
    ensure_pyinstaller()

    frontend_index = ROOT.parent / "frontend" / "dist" / "index.html"
    if not frontend_index.exists():
        raise RuntimeError(
            f"frontend build output missing: {frontend_index}\n"
            "Please run frontend build first: pnpm run desktop:build:web"
        )

    if BUILD_DIR.exists():
        shutil.rmtree(BUILD_DIR, ignore_errors=True)

    for spec in (SPEC_BACKEND, SPEC_SERVICE):
        if not spec.exists():
            raise RuntimeError(f"Missing spec file: {spec}")

    run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", str(SPEC_BACKEND)], cwd=ROOT)
    run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", str(SPEC_SERVICE)], cwd=ROOT)

    built_files = []
    backend_exe = DIST_DIR / "ali-backend" / ("ali-backend.exe" if os.name == "nt" else "ali-backend")
    service_exe = DIST_DIR / ("ali-backend-service.exe" if os.name == "nt" else "ali-backend-service")

    for exe in (backend_exe, service_exe):
        if not exe.exists():
            raise RuntimeError(f"Backend executable not found: {exe}")
        built_files.append(exe)

    bundled = DIST_DIR / "chromedriver" / ("chromedriver.exe" if os.name == "nt" else "chromedriver")
    if bundled.is_file() and backend_exe.parent.is_dir():
        target_dir = backend_exe.parent / "chromedriver"
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / bundled.name
        shutil.copy2(bundled, target)
        print(f"[info] bundled ChromeDriver: {target}")

    print("\nBuild success:")
    for p in built_files:
        print(f"- {p}")


if __name__ == "__main__":
    main()

# -*- coding: utf-8 -*-
"""Build-time: download ChromeDriver into backend/dist/chromedriver."""
from __future__ import annotations
import shutil, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
OUT_DIR = BACKEND / "dist" / "chromedriver"
OUT_EXE = OUT_DIR / ("chromedriver.exe" if sys.platform == "win32" else "chromedriver")

def main() -> int:
    sys.path.insert(0, str(BACKEND))
    from webdriver_manager.chrome import ChromeDriverManager
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    src = Path(ChromeDriverManager().install())
    shutil.copy2(src, OUT_EXE)
    print(f"[fetch_chromedriver] OK: {OUT_EXE}")
    ali_backend = BACKEND / "dist" / "ali-backend" / "chromedriver"
    ali_backend.mkdir(parents=True, exist_ok=True)
    shutil.copy2(OUT_EXE, ali_backend / OUT_EXE.name)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())

# -*- coding: utf-8 -*-
"""对比本机各来源 admin_key 与云端是否一致；扫描 Electron localStorage。"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
CLOUD = "https://echo-yiwu.cloud/api/membership"
PLACEHOLDERS = {"", "change-me-admin", "change-me", "***"}


def load_key(path: Path, *keys: str) -> str:
    try:
        d = json.loads(path.read_text(encoding="utf-8-sig"))
        cur = d
        for k in keys:
            cur = cur.get(k) if isinstance(cur, dict) else None
        return str(cur or "").strip()
    except Exception as e:
        return f"ERR:{e}"


def mask(key: str) -> str:
    if not key or key.startswith("ERR"):
        return key
    if key in PLACEHOLDERS:
        return key
    return f"{key[:8]}...{key[-4:]} (len={len(key)})"


def cloud_test(label: str, key: str) -> None:
    if not key or key.startswith("ERR") or key in PLACEHOLDERS:
        print(f"  [{label}] skip key={mask(key)}")
        return
    try:
        r = requests.get(
            f"{CLOUD}/admin/users",
            headers={"X-Admin-Key": key},
            params={"limit": 1},
            timeout=25,
        )
        print(f"  [{label}] HTTP {r.status_code}  key={mask(key)}  body={r.text[:100]}")
    except Exception as e:
        print(f"  [{label}] ERROR {e}")


def scan_leveldb() -> None:
    ls = Path.home() / "AppData/Roaming/ali-auto-publish-frontend/Local Storage/leveldb"
    print("\n=== Electron localStorage (ali-auto-publish-frontend) ===")
    if not ls.is_dir():
        print(f"  missing: {ls}")
        return
    needles = [
        b"membership_admin_key",
        b"control_admin_key",
        b"admin_console_logged_in",
        b"GKtXsIeo",
        b"change-me-admin",
    ]
    for f in sorted(ls.iterdir()):
        if f.is_dir():
            continue
        try:
            data = f.read_bytes()
        except OSError:
            continue
        hits = [n.decode() for n in needles if n in data]
        if hits:
            print(f"  {f.name}: {hits}")
    for f in ls.glob("*.ldb"):
        try:
            raw = f.read_bytes().decode("latin1", errors="ignore")
        except OSError:
            continue
        for store in ("membership_admin_key", "control_admin_key"):
            if store not in raw:
                continue
            idx = raw.find(store)
            snippet = raw[idx : idx + 220]
            print(f"  extract {store} from {f.name}:")
            print(f"    {snippet!r}")


def main() -> None:
    sources = {
        "deploy_json": load_key(ROOT / "frontend/electron/desktop.deploy.json", "admin_api_key"),
        "project_config": load_key(ROOT / "data/config.json", "payment", "admin_api_key"),
        "appdata_config": load_key(
            Path.home() / "AppData/Roaming/AliAutoPublish/data/config.json",
            "payment",
            "admin_api_key",
        ),
    }

    print("=== Key sources ===")
    for name, key in sources.items():
        print(f"  {name}: {mask(key)}")

    deploy = sources["deploy_json"]
    appdata = sources["appdata_config"]
    print("\n=== Consistency ===")
    if deploy == appdata:
        print("  deploy_json == appdata_config")
    else:
        print("  deploy_json != appdata_config  <-- mismatch")
        print(f"    deploy:  {mask(deploy)}")
        print(f"    appdata: {mask(appdata)}")

    print("\n=== Cloud /admin/users ===")
    seen: set[str] = set()
    for name, key in sources.items():
        if key not in seen:
            cloud_test(name, key)
            seen.add(key)
    cloud_test("placeholder", "change-me-admin")

    scan_leveldb()

    db = Path.home() / "AppData/Roaming/AliAutoPublish/data/membership.db"
    print("\n=== admin_accounts (AppData membership.db) ===")
    if db.is_file():
        conn = sqlite3.connect(db)
        rows = conn.execute("SELECT username, is_active FROM admin_accounts").fetchall()
        print(" ", rows if rows else "(empty)")
        conn.close()
    else:
        print("  db not found:", db)


if __name__ == "__main__":
    main()

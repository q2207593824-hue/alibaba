# -*- coding: utf-8 -*-
import os
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
paths = [
    ("AppData", Path(os.environ.get("APPDATA", "")) / "AliAutoPublish" / "data" / "membership.db"),
    ("Project", ROOT / "data" / "membership.db"),
]

CORE = ("users", "user_sessions", "user_points_accounts", "admin_accounts")
AGENT = ("agent_nodes", "agent_policies", "keyword_reports", "keyword_report_items")

for label, db in paths:
    print(f"=== {label} {db} exists={db.is_file()} ===")
    if not db.is_file():
        continue
    print(f"  size={db.stat().st_size} bytes")
    conn = sqlite3.connect(db)
    tables = {
        r[0]
        for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
    }
    conn.close()
    for name in CORE:
        print(f"  core {name}: {'yes' if name in tables else 'NO'}")
    for name in AGENT:
        print(f"  agent {name}: {'yes' if name in tables else 'NO'}")
    print(f"  total tables: {len(tables)}")

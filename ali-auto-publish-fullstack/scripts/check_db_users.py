# -*- coding: utf-8 -*-
import os
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
paths = [
    ("AppData", Path(os.environ.get("APPDATA", "")) / "AliAutoPublish" / "data" / "membership.db"),
    ("Project", ROOT / "data" / "membership.db"),
]
for label, p in paths:
    if not p.is_file():
        print(label, "missing", p)
        continue
    c = sqlite3.connect(p)
    print(label, p)
    print("  admins:", c.execute("SELECT username FROM admin_accounts").fetchall())
    print("  users:", c.execute("SELECT username FROM users LIMIT 20").fetchall())

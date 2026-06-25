import json, os, sys, time
from pathlib import Path
import requests
ROOT = Path(r"D:\桌面\ali-auto-publish-fullstack (3)\ali-auto-publish-fullstack")
BASE = "http://127.0.0.1:8000"
admin_key = json.loads((ROOT/"desktop.deploy.json").read_text(encoding="utf-8-sig"))["admin_api_key"]
s = requests.Session(); s.headers["Content-Type"] = "application/json"
h = s.get(BASE+"/api/health", timeout=10); print("health:", h.status_code)
r = s.post(BASE+"/api/membership/auth/sync-admin-session", headers={"X-Admin-Key": admin_key}, timeout=30)
token = ((r.json() or {}).get("data") or {}).get("token") or ""
print("admin_login:", r.status_code, bool(token))
s.headers["Authorization"] = f"Bearer {token}"; s.headers["X-Admin-Key"] = admin_key
print("=== fetch specs start ===")
t0=time.time(); fr=s.post(BASE+"/api/config/specifications/fetch-from-platform", json={}, timeout=360)
print("fetch:", fr.status_code, round(time.time()-t0,1), "s")
payload=fr.json(); print(json.dumps(payload, ensure_ascii=False)[:1500])
cfg=s.get(BASE+"/api/config/", timeout=30).json()
specs=(cfg.get("attributes") or {}).get("specifications_by_group") or {}
for g, items in specs.items():
    print("GROUP", g, "count", len(items))
    for name, d in items.items():
        if not isinstance(d, dict): d=d
        print(" ", name, "id=", d.get("container_id"), "interaction=", d.get("interaction"), "sale=", d.get("sale_attribute_value"), "img=", d.get("enable_spec_image"), "pool=", len(d.get("values_pool") or []))

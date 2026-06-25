# -*- coding: utf-8 -*-
"""Test: admin points_pricing change -> member sync (no code changes)."""
import json, os, sys, time
from pathlib import Path
import requests

ROOT = Path(__file__).resolve().parents[1]
BASE = os.getenv("ACCEPTANCE_BACKEND", "http://127.0.0.1:8000")
MEMBER_USER = os.getenv("ACCEPTANCE_MEMBER_USER", "321654")
MEMBER_PASS = os.getenv("ACCEPTANCE_MEMBER_PASS", "Aa3456")
ADMIN_USER = os.getenv("ACCEPTANCE_ADMIN_USER", "admin11")
ADMIN_PASS = os.getenv("ACCEPTANCE_ADMIN_PASS", "yingshengchongadmin")
ADMIN_KEY = os.getenv("ACCEPTANCE_ADMIN_KEY", "")
TIMEOUT = int(os.getenv("ACCEPTANCE_TIMEOUT", "60"))
CLOUD = os.getenv("CLOUD_MEMBERSHIP_API_BASE", "https://echo-yiwu.cloud/api/membership")

def load_admin_key():
    k = (ADMIN_KEY or "").strip()
    if k: return k
    p = ROOT / "data" / "config.json"
    return str((json.loads(p.read_text(encoding="utf-8-sig")).get("payment") or {}).get("admin_api_key") or "").strip()

def login(user, pwd):
    s = requests.Session()
    s.headers["Content-Type"] = "application/json"
    r = s.post(f"{BASE}/api/membership/auth/login", json={"username": user, "password": pwd}, timeout=TIMEOUT)
    r.raise_for_status()
    d = (r.json() or {}).get("data") or {}
    tok = d.get("token") or ""
    s.headers["Authorization"] = f"Bearer {tok}"
    ak = d.get("admin_key") or load_admin_key()
    if ak: s.headers["X-Admin-Key"] = ak
    return s, d

def get_member_pricing(s):
    a = s.get(f"{BASE}/api/analysis/points-pricing", timeout=TIMEOUT).json()
    i = s.get(f"{BASE}/api/images/ai-gen/points-pricing", timeout=TIMEOUT).json()
    rt = s.get(f"{BASE}/api/membership/admin/runtime-config", timeout=TIMEOUT).json()
    return (a.get("data") or {}), (i.get("data") or {}), ((rt.get("data") or {}).get("points_pricing") or {})

def cloud_get(key):
    r = requests.get(f"{CLOUD}/admin/runtime-config", headers={"X-Admin-Key": key}, timeout=TIMEOUT)
    r.raise_for_status()
    return (r.json() or {}).get("data") or {}

def cloud_put(key, body):
    r = requests.put(f"{CLOUD}/admin/runtime-config", headers={"X-Admin-Key": key, "Content-Type": "application/json"}, json=body, timeout=TIMEOUT)
    r.raise_for_status()
    return (r.json() or {}).get("data") or {}

def main():
    admin_key = load_admin_key()
    print("=== points_pricing sync test ===\n")
    member_s, _ = login(MEMBER_USER, MEMBER_PASS)
    admin_s, admin_data = login(ADMIN_USER, ADMIN_PASS)
    if admin_key: admin_s.headers["X-Admin-Key"] = admin_key

    base_a, base_i, base_rt = get_member_pricing(member_s)
    orig_1k = float((base_a.get("ai_image_cost_per_size") or {}).get("1K") or 0.6)
    print(f"[1] member baseline ai_image 1K = {orig_1k}")
    print(f"    analysis snapshot = {json.dumps(base_a, ensure_ascii=False)}")
    print(f"    runtime-config points_pricing = {json.dumps(base_rt, ensure_ascii=False)}")

    cloud = cloud_get(admin_key)
    orig_pp = dict(cloud.get("points_pricing") or {})
    if not orig_pp:
        orig_pp = {"title_optimize_per_item": 0.2, "traffic_ai_per_run": 0.5, "ai_image_1k": 0.6, "ai_image_2k": 0.7, "ai_image_4k": 0.85}
    test_1k = round(orig_1k + 0.037, 4)
    new_pp = dict(orig_pp)
    new_pp["ai_image_1k"] = test_1k
    print(f"\n[2] admin cloud PUT ai_image_1k: {orig_pp.get('ai_image_1k', orig_1k)} -> {test_1k}")
    put_res = cloud_put(admin_key, {
        "data_analysis": cloud.get("data_analysis") or {},
        "ai_image_gen": cloud.get("ai_image_gen") or {},
        "points_pricing": new_pp,
    })
    print(f"    cloud revision -> {put_res.get('revision')}")

    # member BEFORE pull
    pre_a, _, pre_rt = get_member_pricing(member_s)
    pre_val = float((pre_a.get("ai_image_cost_per_size") or {}).get("1K") or -1)
    print(f"\n[3] member BEFORE pull: ai_image 1K = {pre_val}")

    # member pull (same as desktop login sync)
    pr = member_s.post(f"{BASE}/api/config/pull-cloud-admin-runtime", timeout=TIMEOUT)
    print(f"[4] member pull-cloud-admin-runtime: HTTP {pr.status_code}")
    pull_data = (pr.json() or {}).get("data") or {}
    print(f"    pull secrets_ready={pull_data.get('secrets_ready')} revision={pull_data.get('revision')}")

    post_a, post_i, post_rt = get_member_pricing(member_s)
    post_val = float((post_a.get("ai_image_cost_per_size") or {}).get("1K") or -1)
    post_i_1k = float((post_i.get("cost_per_size") or post_i.get("ai_image_cost_per_size") or {}).get("1K", post_i.get("1K", -1)) if isinstance(post_i, dict) else -1)
    if post_i_1k < 0 and isinstance(post_i, dict):
        post_i_1k = float(post_i.get("ai_image_1k") or -1)
    print(f"\n[5] member AFTER pull:")
    print(f"    /analysis/points-pricing 1K = {post_val}")
    print(f"    /images/ai-gen/points-pricing = {json.dumps(post_i, ensure_ascii=False)}")
    print(f"    runtime-config points_pricing = {json.dumps(post_rt, ensure_ascii=False)}")

    synced = abs(post_val - test_1k) < 0.0001
    print(f"\n=== RESULT: member synced after pull = {'PASS' if synced else 'FAIL'} (expected {test_1k}, got {post_val}) ===")

    # restore
    restore_pp = dict(orig_pp)
    cloud_put(admin_key, {
        "data_analysis": cloud.get("data_analysis") or {},
        "ai_image_gen": cloud.get("ai_image_gen") or {},
        "points_pricing": restore_pp,
    })
    member_s.post(f"{BASE}/api/config/pull-cloud-admin-runtime", timeout=TIMEOUT)
    print(f"[6] restored ai_image_1k to {restore_pp.get('ai_image_1k', orig_1k)}")

    return 0 if synced else 1

if __name__ == "__main__":
    raise SystemExit(main())

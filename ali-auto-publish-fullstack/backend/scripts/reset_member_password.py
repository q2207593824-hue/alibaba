#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""云端 membership.db：创建或重置会员账号密码（users 表）。"""
import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

os.environ.setdefault("MEMBERSHIP_IS_CLOUD_HOST", "1")
os.environ.setdefault(
    "ALI_APP_DATA_DIR",
    os.environ.get("ALI_APP_DATA_DIR", "").strip()
    or os.path.join(os.path.dirname(ROOT), "data"),
)

from app.services.membership_service import reset_member_password, DB_PATH  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description="创建/重置 users 表会员密码")
    ap.add_argument("username", help="会员登录名")
    ap.add_argument("password", help="新密码")
    args = ap.parse_args()
    result = reset_member_password(args.username, args.password)
    print(f"[ok] users {result['action']}: {result['username']} (user_id={result.get('user_id')})")
    print(f"[db] {DB_PATH}")


if __name__ == "__main__":
    main()

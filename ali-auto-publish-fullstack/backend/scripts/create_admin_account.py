#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""在 membership.db 的 admin_accounts 表中创建或重置管理员（代码中不再内置默认管理员）。"""
import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from app.services.membership_service import create_admin_account, DB_PATH  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description="创建/重置 admin_accounts 管理员")
    ap.add_argument("username", help="管理员登录名")
    ap.add_argument("password", help="管理员密码")
    args = ap.parse_args()
    result = create_admin_account(args.username, args.password)
    print(f"[ok] admin_accounts {result['action']}: {result['username']}")
    print(f"[db] {DB_PATH}")


if __name__ == "__main__":
    main()

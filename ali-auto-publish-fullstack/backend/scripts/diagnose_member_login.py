#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""诊断会员登录：数据库路径、账号是否存在、密码是否匹配、模拟 login()。"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

os.environ.setdefault("MEMBERSHIP_IS_CLOUD_HOST", "1")
os.environ.setdefault("MEMBERSHIP_POINTS_SOURCE", "local")
os.environ.setdefault(
    "ALI_APP_DATA_DIR",
    os.environ.get("ALI_APP_DATA_DIR", "").strip()
    or os.path.join(os.path.dirname(ROOT), "data"),
)

from app.services.membership_service import (  # noqa: E402
    DB_PATH,
    _hash_pwd,
    _is_cloud_membership_host,
    init_db,
    login,
    _conn,
)


def main():
    username = (sys.argv[1] if len(sys.argv) > 1 else "321654").strip()
    password = (sys.argv[2] if len(sys.argv) > 2 else "").strip()
    if not password:
        print("用法: python3 scripts/diagnose_member_login.py <用户名> <密码>")
        sys.exit(1)

    print("=== 环境 ===")
    print("ALI_APP_DATA_DIR =", os.environ.get("ALI_APP_DATA_DIR"))
    print("MEMBERSHIP_IS_CLOUD_HOST =", os.environ.get("MEMBERSHIP_IS_CLOUD_HOST"))
    print("MEMBERSHIP_POINTS_SOURCE =", os.environ.get("MEMBERSHIP_POINTS_SOURCE"))
    print("cloud_host_mode =", _is_cloud_membership_host())
    print("DB_PATH =", DB_PATH)
    print("db_exists =", os.path.isfile(DB_PATH))

    init_db()
    conn = _conn()
    cur = conn.cursor()
    row = cur.execute(
        "SELECT id, username, password_hash FROM users WHERE username=?",
        (username,),
    ).fetchone()
    admin = cur.execute(
        "SELECT username FROM admin_accounts WHERE username=?",
        (username,),
    ).fetchone()
    conn.close()

    print("\n=== 账号 ===")
    print("users 表存在:", bool(row))
    if row:
        print("user_id:", row["id"])
        print("password_match:", str(row["password_hash"]) == _hash_pwd(password))
    print("admin_accounts 存在:", bool(admin), "(若存在且密码错会提示「管理员账号或密码错误」)")

    print("\n=== 模拟 login() ===")
    try:
        data = login(username, password)
        print("OK token 前8位:", str(data.get("token", ""))[:8], "...")
    except Exception as e:
        print("FAIL:", e)
        sys.exit(2)


if __name__ == "__main__":
    main()

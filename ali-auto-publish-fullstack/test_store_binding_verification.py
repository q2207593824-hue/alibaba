#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
店铺绑定验收脚本
验证：绑定店铺后，公司名称是否写入云端，管理员是否能看到
"""
import requests
import json
from typing import Optional

# 配置
BASE_URL = "http://localhost:8000"  # 根据实际后端地址修改
ADMIN_USERNAME = "admin11"
ADMIN_PASSWORD = "yingshengchongadmin"
MEMBER_USERNAME = "321654"
MEMBER_PASSWORD = "Aa3456"


def login(username: str, password: str) -> Optional[str]:
    """登录获取 token"""
    try:
        resp = requests.post(
            f"{BASE_URL}/api/membership/login",
            json={"username": username, "password": password},
            timeout=10
        )
        if resp.ok:
            data = resp.json()
            token = data.get("data", {}).get("token")
            print(f"✓ 登录成功: {username} -> token: {token[:20]}...")
            return token
        else:
            print(f"✗ 登录失败: {username} - {resp.status_code} - {resp.text[:200]}")
            return None
    except Exception as e:
        print(f"✗ 登录异常: {username} - {e}")
        return None


def get_me(token: str) -> dict:
    """获取当前用户信息"""
    try:
        resp = requests.get(
            f"{BASE_URL}/api/membership/me",
            headers={"Authorization": f"Bearer {token}"},
            timeout=10
        )
        if resp.ok:
            data = resp.json().get("data", {})
            print(f"✓ 获取用户信息成功")
            print(f"  - 用户名: {data.get('username')}")
            print(f"  - 公司名称: {data.get('company_name', '(空)')}")
            print(f"  - 主营类目: {data.get('main_category', '(空)')}")
            return data
        else:
            print(f"✗ 获取用户信息失败: {resp.status_code} - {resp.text[:200]}")
            return {}
    except Exception as e:
        print(f"✗ 获取用户信息异常: {e}")
        return {}


def get_admin_users_list(token: str) -> list:
    """管理员获取用户列表"""
    try:
        resp = requests.get(
            f"{BASE_URL}/api/membership/admin/users",
            headers={"Authorization": f"Bearer {token}"},
            timeout=10
        )
        if resp.ok:
            data = resp.json().get("data", [])
            print(f"✓ 获取管理员用户列表成功，共 {len(data)} 个用户")
            return data
        else:
            print(f"✗ 获取管理员用户列表失败: {resp.status_code} - {resp.text[:200]}")
            return []
    except Exception as e:
        print(f"✗ 获取管理员用户列表异常: {e}")
        return []


def check_member_in_admin_list(users: list, member_username: str) -> Optional[dict]:
    """检查会员是否在管理员列表中，并返回其信息"""
    for user in users:
        if user.get("username") == member_username:
            return user
    return None


def main():
    print("=" * 60)
    print("店铺绑定验收脚本")
    print("=" * 60)
    print()
    
    # Step 1: 会员登录
    print("【步骤 1】会员账号登录")
    member_token = login(MEMBER_USERNAME, MEMBER_PASSWORD)
    if not member_token:
        print("\n✗✗✗ 会员登录失败，无法继续验收")
        return
    print()
    
    # Step 2: 查看会员自己的公司信息
    print("【步骤 2】查看会员自己的公司信息（/me 接口）")
    member_info = get_me(member_token)
    member_company_name = member_info.get("company_name", "")
    if not member_company_name:
        print("\n⚠️  会员自己的 /me 接口返回的 company_name 为空")
        print("   这可能意味着：")
        print("   1. 该用户尚未绑定店铺")
        print("   2. 绑定时采集到的 company_name 为空")
        print("   3. 云端同步失败，且本地 SQLite 也没有该字段")
        print("\n请先用该账号绑定店铺，再重新运行此脚本")
        return
    else:
        print(f"\n✓✓✓ 会员公司名称: {member_company_name}")
    print()
    
    # Step 3: 管理员登录
    print("【步骤 3】管理员账号登录")
    admin_token = login(ADMIN_USERNAME, ADMIN_PASSWORD)
    if not admin_token:
        print("\n✗✗✗ 管理员登录失败，无法继续验收")
        return
    print()
    
    # Step 4: 管理员查询用户列表
    print("【步骤 4】管理员查询用户列表")
    admin_users = get_admin_users_list(admin_token)
    if not admin_users:
        print("\n✗✗✗ 管理员用户列表为空或获取失败")
        return
    print()
    
    # Step 5: 检查会员是否在列表中，且 company_name 是否正确
    print(f"【步骤 5】检查会员 {MEMBER_USERNAME} 在管理员列表中的 company_name")
    member_in_admin = check_member_in_admin_list(admin_users, MEMBER_USERNAME)
    
    if not member_in_admin:
        print(f"\n✗✗✗ 会员 {MEMBER_USERNAME} 不在管理员用户列表中")
        print("   可能的原因：")
        print("   1. 该用户确实不存在")
        print("   2. 管理员接口有权限限制")
        return
    
    admin_view_company = member_in_admin.get("company_name", "")
    print(f"\n管理员视图中的用户信息：")
    print(f"  - ID: {member_in_admin.get('id')}")
    print(f"  - 用户名: {member_in_admin.get('username')}")
    print(f"  - 公司名称: {admin_view_company or '(空)'}")
    print(f"  - 主营类目: {member_in_admin.get('main_category', '(空)')}")
    print(f"  - 积分余额: {member_in_admin.get('points_balance', 0)}")
    print()
    
    # Step 6: 对比结果
    print("【步骤 6】验收结果")
    print("=" * 60)
    if admin_view_company and admin_view_company == member_company_name:
        print("✓✓✓ 验收通过！")
        print(f"    会员自己看到的公司名称: {member_company_name}")
        print(f"    管理员看到的公司名称:   {admin_view_company}")
        print("    两者一致，修复生效！")
    elif admin_view_company and admin_view_company != member_company_name:
        print("⚠️  部分通过")
        print(f"    会员自己看到的公司名称: {member_company_name}")
        print(f"    管理员看到的公司名称:   {admin_view_company}")
        print("    两者不一致，可能存在数据同步延迟")
    else:
        print("✗✗✗ 验收失败！")
        print(f"    会员自己看到的公司名称: {member_company_name}")
        print(f"    管理员看到的公司名称:   (空)")
        print()
        print("可能的原因：")
        print("  1. 云端同步失败（绑定时 cloud_sync.ok = false）")
        print("  2. 本地 SQLite users.company_name 字段为空")
        print("  3. _merge_cloud_points_into_admin_users 未被调用")
        print("     （检查是否启用了 USE_CLOUD_POINTS / MEMBERSHIP_CLOUD_SYNC_ENABLED）")
        print()
        print("排查步骤：")
        print("  1. 重启后端服务")
        print("  2. 管理员刷新会员中心页面")
        print("  3. 检查后端日志")
    print("=" * 60)


if __name__ == "__main__":
    main()

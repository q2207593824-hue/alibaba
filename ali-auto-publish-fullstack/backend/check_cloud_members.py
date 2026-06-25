#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
读取云端会员列表，查看包含哪些字段信息
"""
import os
import sys
import json
import requests
from typing import List, Dict, Any

# 添加 app 目录到 Python 路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'app'))

# 云端 API 配置
CLOUD_MEMBERSHIP_API_BASE = os.getenv("CLOUD_MEMBERSHIP_API_BASE", "https://echo-yiwu.cloud/api/membership")


def get_admin_api_key() -> str:
    """获取管理员 API Key"""
    # 1. 从环境变量读取
    env_key = os.getenv("ALI_ADMIN_API_KEY", "").strip()
    if env_key and env_key not in ("change-me-admin", "change-me"):
        return env_key
    
    # 2. 从配置文件读取
    try:
        from app.core.settings import get_config
        cfg = get_config()
        key = str(getattr(cfg.payment, "admin_api_key", "") or "").strip()
        if key and key not in ("change-me-admin", "change-me"):
            return key
    except Exception as e:
        print(f"⚠️  读取配置文件失败: {e}")
    
    # 3. 从 desktop.deploy.json 读取
    try:
        from app.core.desktop_bootstrap import _resolve_deploy_admin_key
        deploy_key = _resolve_deploy_admin_key()
        if deploy_key and deploy_key not in ("change-me-admin", "change-me"):
            return deploy_key
    except Exception:
        pass
    
    return ""


def fetch_cloud_users(admin_key: str, limit: int = 200) -> List[Dict[str, Any]]:
    """从云端获取用户列表"""
    try:
        # 绕过 SSL 验证（仅用于调试，生产环境不推荐）
        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        
        resp = requests.get(
            f"{CLOUD_MEMBERSHIP_API_BASE}/admin/users",
            headers={
                "X-Admin-Key": admin_key,
                "Accept": "application/json"
            },
            params={"limit": limit},
            timeout=(5, 10),
            verify=False  # 跳过 SSL 证书验证
        )
        
        if not resp.ok:
            print(f"❌ 云端请求失败: {resp.status_code}")
            print(f"   响应内容: {resp.text[:500]}")
            return []
        
        payload = resp.json() or {}
        data = payload.get("data") if isinstance(payload, dict) else None
        
        if not isinstance(data, list):
            print(f"❌ 云端返回数据格式错误，期望 list，实际: {type(data)}")
            return []
        
        return data
    
    except requests.exceptions.Timeout:
        print("❌ 云端请求超时（10 秒）")
        return []
    except requests.exceptions.ConnectionError as e:
        print(f"❌ 无法连接到云端服务: {e}")
        return []
    except Exception as e:
        print(f"❌ 云端请求异常: {e}")
        return []


def print_user_info(user: Dict[str, Any], index: int):
    """打印单个用户的信息"""
    print(f"\n{'='*80}")
    print(f"用户 #{index + 1}")
    print(f"{'='*80}")
    
    # 基础信息
    print(f"ID:            {user.get('id', '(无)')}")
    print(f"用户名:        {user.get('username', '(无)')}")
    print(f"邀请码:        {user.get('invite_code', '(无)')}")
    
    # 公司信息（重点关注）
    print(f"\n【公司信息】")
    print(f"公司名称:      {user.get('company_name', '(无)') or '(空)'}")
    print(f"主营类目:      {user.get('main_category', '(无)') or '(空)'}")
    print(f"已认证:        {user.get('is_verified', '(无)') or '(空)'}")
    print(f"服务年限:      {user.get('service_years', '(无)') or '(空)'}")
    print(f"页面等级:      {user.get('page_level_star', '(无)') or '(空)'}")
    
    # 会员状态
    print(f"\n【会员状态】")
    print(f"试用开始:      {user.get('trial_start_at', '(无)')}")
    print(f"试用到期:      {user.get('trial_end_at', '(无)')}")
    print(f"VIP 到期:      {user.get('vip_expire_at', '(无)')}")
    
    # 积分信息
    print(f"\n【积分余额】")
    print(f"可用积分:      {user.get('points_balance', 0)}")
    print(f"冻结积分:      {user.get('points_frozen', 0)}")
    
    # 访问控制
    control_mode = user.get('control_mode', 'normal')
    if control_mode != 'normal':
        print(f"\n【访问控制】")
        print(f"控制模式:      {control_mode}")
        print(f"控制备注:      {user.get('control_note', '(无)')}")
    
    # 在线状态
    print(f"\n【在线状态】")
    online = user.get('online', 0)
    print(f"当前在线:      {'是' if online == 1 else '否'}")
    print(f"最后活跃:      {user.get('online_last_seen_at', '(无)')}")
    
    # 创建时间
    print(f"\n【账号信息】")
    print(f"创建时间:      {user.get('created_at', '(无)')}")
    
    # 其他字段
    other_keys = set(user.keys()) - {
        'id', 'username', 'invite_code', 'company_name', 'main_category',
        'is_verified', 'service_years', 'page_level_star', 'trial_start_at',
        'trial_end_at', 'vip_expire_at', 'points_balance', 'points_frozen',
        'control_mode', 'control_note', 'online', 'online_last_seen_at', 'created_at',
        'real_name', 'phone', 'control_updated_at'
    }
    if other_keys:
        print(f"\n【其他字段】")
        for key in sorted(other_keys):
            print(f"{key}: {user.get(key)}")


def print_summary(users: List[Dict[str, Any]]):
    """打印汇总统计"""
    print(f"\n{'='*80}")
    print("汇总统计")
    print(f"{'='*80}")
    
    total = len(users)
    print(f"总用户数:      {total}")
    
    if total == 0:
        return
    
    # 统计有公司名称的用户
    with_company = sum(1 for u in users if str(u.get('company_name') or '').strip())
    print(f"有公司名称:    {with_company} ({with_company/total*100:.1f}%)")
    
    # 统计在线用户
    online_count = sum(1 for u in users if u.get('online') == 1)
    print(f"在线用户:      {online_count} ({online_count/total*100:.1f}%)")
    
    # 统计 VIP 用户
    vip_count = sum(1 for u in users if u.get('vip_expire_at'))
    print(f"VIP 用户:      {vip_count} ({vip_count/total*100:.1f}%)")
    
    # 公司名称列表
    companies = [str(u.get('company_name') or '').strip() for u in users if str(u.get('company_name') or '').strip()]
    if companies:
        print(f"\n【公司名称列表】")
        unique_companies = sorted(set(companies))
        for i, company in enumerate(unique_companies, 1):
            count = companies.count(company)
            print(f"{i}. {company} ({count} 个账号)")


def print_fields_structure(users: List[Dict[str, Any]]):
    """打印字段结构"""
    if not users:
        return
    
    print(f"\n{'='*80}")
    print("字段结构分析")
    print(f"{'='*80}")
    
    # 收集所有字段
    all_fields = set()
    for user in users:
        all_fields.update(user.keys())
    
    print(f"总字段数:      {len(all_fields)}")
    print(f"\n字段列表:")
    for i, field in enumerate(sorted(all_fields), 1):
        # 统计该字段有值的用户数
        non_empty = sum(1 for u in users if u.get(field))
        print(f"{i:2d}. {field:25s} - 有值用户: {non_empty}/{len(users)} ({non_empty/len(users)*100:.1f}%)")


def save_to_json(users: List[Dict[str, Any]], filename: str = "cloud_members.json"):
    """保存到 JSON 文件"""
    try:
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(users, f, ensure_ascii=False, indent=2)
        print(f"\n✅ 数据已保存到: {filename}")
    except Exception as e:
        print(f"\n❌ 保存 JSON 失败: {e}")


def main():
    print("=" * 80)
    print("云端会员列表查看工具")
    print("=" * 80)
    print()
    
    # 获取管理员 API Key
    print("【步骤 1】获取管理员 API Key")
    admin_key = get_admin_api_key()
    
    if not admin_key:
        print("❌ 管理员 API Key 未配置")
        print("\n请在以下位置之一配置 admin_api_key:")
        print("  1. 环境变量: ALI_ADMIN_API_KEY")
        print("  2. 配置文件: backend/config.json -> payment.admin_api_key")
        print("  3. 桌面部署: desktop.deploy.json -> admin_api_key")
        return
    
    print(f"✅ Admin Key: {admin_key[:10]}...{admin_key[-10:]}")
    print()
    
    # 获取云端用户列表
    print("【步骤 2】从云端获取用户列表")
    print(f"云端 API: {CLOUD_MEMBERSHIP_API_BASE}/admin/users")
    users = fetch_cloud_users(admin_key, limit=200)
    
    if not users:
        print("\n❌ 未获取到用户数据")
        print("\n可能的原因:")
        print("  1. admin_api_key 无效")
        print("  2. 云端服务不可达")
        print("  3. 云端用户列表为空")
        return
    
    print(f"✅ 成功获取 {len(users)} 个用户")
    print()
    
    # 显示模式选择
    print("【步骤 3】显示数据")
    print("\n请选择显示模式:")
    print("  1. 详细信息（每个用户的完整信息）")
    print("  2. 汇总统计（统计数据 + 公司列表）")
    print("  3. 字段结构（查看所有字段及其覆盖率）")
    print("  4. 保存到 JSON 文件")
    print("  5. 全部显示")
    print()
    
    choice = input("请输入选项（1-5，默认 2）: ").strip() or "2"
    print()
    
    if choice == "1":
        for i, user in enumerate(users):
            print_user_info(user, i)
            if i < len(users) - 1:
                input("\n按回车键继续查看下一个用户...")
    
    elif choice == "2":
        print_summary(users)
    
    elif choice == "3":
        print_fields_structure(users)
    
    elif choice == "4":
        save_to_json(users)
    
    elif choice == "5":
        print_summary(users)
        print_fields_structure(users)
        save_to_json(users)
        
        view_details = input("\n是否查看每个用户的详细信息？(y/N): ").strip().lower()
        if view_details == 'y':
            for i, user in enumerate(users):
                print_user_info(user, i)
                if i < len(users) - 1:
                    cont = input("\n按回车键继续，输入 q 退出: ").strip().lower()
                    if cont == 'q':
                        break
    
    else:
        print("❌ 无效的选项")
        return
    
    print("\n" + "=" * 80)
    print("完成")
    print("=" * 80)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n用户中断")
    except Exception as e:
        print(f"\n❌ 程序异常: {e}")
        import traceback
        traceback.print_exc()

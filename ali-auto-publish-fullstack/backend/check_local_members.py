#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
读取本地会员数据库，查看用户信息
"""
import os
import sys
import json
import sqlite3
from typing import List, Dict, Any

# 添加 app 目录到 Python 路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'app'))


def get_db_path() -> str:
    """获取数据库路径"""
    # 1. 从环境变量读取
    app_data_dir = os.getenv("ALI_APP_DATA_DIR", "").strip()
    if app_data_dir:
        db_path = os.path.join(app_data_dir, "membership.db")
        if os.path.exists(db_path):
            return db_path
    
    # 2. 默认路径
    default_paths = [
        os.path.join(os.path.dirname(__file__), "data", "membership.db"),
        os.path.join(os.path.dirname(__file__), "..", "data", "membership.db"),
        "data/membership.db",
        "../data/membership.db",
    ]
    
    for path in default_paths:
        if os.path.exists(path):
            return os.path.abspath(path)
    
    return ""


def fetch_local_users(db_path: str, limit: int = 200) -> List[Dict[str, Any]]:
    """从本地 SQLite 获取用户列表"""
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        
        rows = cur.execute(
            """
            SELECT u.id, u.username, u.invite_code, u.real_name, u.phone, 
                   u.trial_start_at, u.trial_end_at, u.vip_expire_at, u.created_at,
                   u.company_name, u.main_category, u.is_verified, u.service_years, u.page_level_star,
                   COALESCE(a.balance_real, a.balance, 0) AS points_balance,
                   COALESCE(c.mode, 'normal') AS control_mode,
                   COALESCE(c.note, '') AS control_note,
                   c.updated_at AS control_updated_at,
                   s.last_seen_at AS online_last_seen_at,
                   CASE
                     WHEN s.last_seen_at IS NOT NULL AND s.last_seen_at >= datetime('now', '-5 minutes') THEN 1
                     ELSE 0
                   END AS online
            FROM users u
            LEFT JOIN user_access_controls c ON c.user_id = u.id
            LEFT JOIN user_points_accounts a ON a.user_id = u.id
            LEFT JOIN (
              SELECT user_id, MAX(last_seen_at) AS last_seen_at
              FROM user_sessions
              GROUP BY user_id
            ) s ON s.user_id = u.id
            ORDER BY u.id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        
        conn.close()
        
        return [dict(row) for row in rows]
    
    except sqlite3.Error as e:
        print(f"❌ 数据库查询失败: {e}")
        return []
    except Exception as e:
        print(f"❌ 读取失败: {e}")
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
    print(f"真实姓名:      {user.get('real_name', '(无)') or '(空)'}")
    print(f"电话:          {user.get('phone', '(无)') or '(空)'}")
    
    # 公司信息（重点关注）
    company_name = user.get('company_name', '') or ''
    print(f"\n【公司信息】")
    print(f"公司名称:      {company_name if company_name else '(空)'}")
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
            user_names = [u.get('username') for u in users if str(u.get('company_name') or '').strip() == company]
            print(f"{i}. {company}")
            print(f"   账号数: {count} | 用户名: {', '.join(user_names)}")
    else:
        print(f"\n⚠️  没有用户绑定了公司名称")


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


def save_to_json(users: List[Dict[str, Any]], filename: str = "local_members.json"):
    """保存到 JSON 文件"""
    try:
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(users, f, ensure_ascii=False, indent=2)
        print(f"\n✅ 数据已保存到: {filename}")
    except Exception as e:
        print(f"\n❌ 保存 JSON 失败: {e}")


def main():
    print("=" * 80)
    print("本地会员数据查看工具")
    print("=" * 80)
    print()
    
    # 获取数据库路径
    print("【步骤 1】定位数据库文件")
    db_path = get_db_path()
    
    if not db_path:
        print("❌ 未找到 membership.db 数据库文件")
        print("\n请检查以下位置:")
        print("  - backend/data/membership.db")
        print("  - 环境变量 ALI_APP_DATA_DIR")
        return
    
    print(f"✅ 数据库路径: {db_path}")
    print()
    
    # 读取用户列表
    print("【步骤 2】读取用户列表")
    users = fetch_local_users(db_path, limit=200)
    
    if not users:
        print("\n⚠️  本地数据库中没有用户数据")
        print("\n提示:")
        print("  1. 数据库可能是空的（首次安装）")
        print("  2. 需要先创建管理员账号或注册会员")
        return
    
    print(f"✅ 成功读取 {len(users)} 个用户")
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

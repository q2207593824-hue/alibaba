# -*- coding: utf-8 -*-
from typing import Optional
from fastapi import Header, HTTPException

def require_admin_api_key(
    x_admin_key: Optional[str] = Header(default=None),
    authorization: Optional[str] = Header(default=None),
):
    from app.services.membership_service import verify_admin_api_key, is_admin_bearer_token

    # 优先验证 X-Admin-Key
    if verify_admin_api_key(x_admin_key):
        return

    # 回退：验证 Bearer Token 是否是管理员会话
    token = ""
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    if token and is_admin_bearer_token(token):
        return

    raise HTTPException(status_code=403, detail="管理员权限不足")

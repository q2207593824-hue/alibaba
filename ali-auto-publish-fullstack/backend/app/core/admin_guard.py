# -*- coding: utf-8 -*-
from typing import Optional
from fastapi import Header, HTTPException

def require_admin_api_key(x_admin_key: Optional[str] = Header(default=None)):
    from app.services.membership_service import verify_admin_api_key

    if not verify_admin_api_key(x_admin_key):
        raise HTTPException(status_code=403, detail="管理员权限不足")

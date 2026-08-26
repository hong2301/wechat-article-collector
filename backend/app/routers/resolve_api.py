# -*- coding: utf-8 -*-
"""链接解析公众号(名称+biz) 独立路由"""
from fastapi import APIRouter, HTTPException
from ..services.resolve import resolve_account

router = APIRouter(prefix="/api", tags=["resolve"])


@router.get("/resolve-name")
def resolve_name(link: str):
    result = resolve_account(link)
    if result is None:
        raise HTTPException(422, "无法从链接识别公众号")
    return result

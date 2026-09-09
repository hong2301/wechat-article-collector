# -*- coding: utf-8 -*-
"""链接解析公众号(名称+biz) 独立路由"""
from fastapi import APIRouter, HTTPException
from ..services.resolve import resolve_account
from ..core import logkit

router = APIRouter(prefix="/api", tags=["resolve"])
log = logkit.get_logger("api.resolve")


@router.get("/resolve-name")
def resolve_name(link: str):
    log.info("[resolve-name] 解析链接: %.50s", link)
    result = resolve_account(link)
    if result is None:
        log.warning("[resolve-name] 解析失败: %.50s", link)
        raise HTTPException(422, "无法从链接识别公众号")
    log.info("[resolve-name] -> %s", result.get("name") or "?")
    return result

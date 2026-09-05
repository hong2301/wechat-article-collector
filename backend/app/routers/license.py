# -*- coding: utf-8 -*-
"""卡密授权路由: 状态查询 / 激活验证"""
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from ..services import license as license_svc

router = APIRouter(prefix="/api/license", tags=["license"])


class CardRequest(BaseModel):
    card: str = ""


@router.get("/status")
def license_status():
    """当前授权状态: 客人钥匙(永久) > 已激活(有期限) > 未激活"""
    return license_svc.status()


@router.post("/verify")
def license_verify(p: CardRequest):
    """提交卡密验签激活; 成功写激活文件"""
    r = license_svc.verify_card(p.card)
    if not r["ok"]:
        return JSONResponse({"ok": False, "msg": r.get("msg", "卡密无效")}, status_code=400)
    return {"ok": True, "expire": r.get("expire", ""), "permanent": r.get("permanent", False),
            "warn": r.get("warn", False)}
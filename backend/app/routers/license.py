# -*- coding: utf-8 -*-
"""卡密授权路由: 状态查询 / 激活验证"""
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from ..services import license as license_svc
from ..core import logkit

router = APIRouter(prefix="/api/license", tags=["license"])
log = logkit.get_logger("api.license")


class CardRequest(BaseModel):
    card: str = ""


@router.get("/status")
def license_status():
    """当前授权状态: 客人钥匙(永久) > 已激活(有期限) > 未激活"""
    r = license_svc.status()
    log.info("[license.status] ok=%s", r.get("ok"))
    return r


@router.post("/verify")
def license_verify(p: CardRequest):
    """提交卡密验签激活; 成功写激活文件"""
    log.info("[license.verify] 提交卡密验证(前8位=%.8s)", p.card)
    r = license_svc.verify_card(p.card)
    if not r["ok"]:
        log.warning("[license.verify] 卡密无效: %s", r.get("msg", "?"))
        return JSONResponse({"ok": False, "msg": r.get("msg", "卡密无效")}, status_code=400)
    log.info("[license.verify] 激活成功 expire=%s permanent=%s", r.get("expire"), r.get("permanent"))
    return {"ok": True, "expire": r.get("expire", ""), "permanent": r.get("permanent", False),
            "warn": r.get("warn", False)}
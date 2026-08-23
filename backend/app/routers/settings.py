# -*- coding: utf-8 -*-
"""AI 模型设置路由: 读写数据库 ai_model 表(厂商+一个key+多个模型id)"""
from fastapi import APIRouter
from pydantic import BaseModel

from ..database import get_conn

router = APIRouter(prefix="/api/settings", tags=["settings"])

# 默认可用配置(用户未设置时前端使用)
DEFAULT_API_KEY = "802ffe3f-4bc9-4030-a3f4-cc00409a4d4e"
DEFAULT_MODEL = "doubao-seed-2-0-mini-260428"


class AiSettings(BaseModel):
    provider: str = "doubao"          # 厂商
    api_key: str = ""                 # key(一个)
    models: list[str] = []            # 多个模型id


@router.get("/ai")
def get_ai_settings():
    """返回 {provider, api_key, models:[...]}; 无数据则空"""
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT provider, api_key, model_id FROM ai_model ORDER BY id").fetchall()
    finally:
        conn.close()
    if not rows:
        return {"provider": "doubao", "api_key": "", "models": []}
    first = dict(rows[0])
    models = [dict(r)["model_id"] for r in rows]
    return {"provider": first["provider"], "api_key": first["api_key"],
            "models": models}


@router.post("/ai")
def save_ai_settings(payload: AiSettings):
    """保存: 清空旧记录, 写入 (provider, api_key, 每个model_id) 一行一条"""
    conn = get_conn()
    try:
        conn.execute("DELETE FROM ai_model")
        api_key = payload.api_key or ""
        provider = payload.provider or "doubao"
        models = payload.models or []
        for m in models:
            conn.execute(
                "INSERT INTO ai_model(provider, api_key, model_id) VALUES(?,?,?)",
                (provider, api_key, m))
        conn.commit()
        return {"ok": True, "count": len(models)}
    finally:
        conn.close()

# -*- coding: utf-8 -*-
"""AI 设置路由: 读写 config/ui_state.json 中的豆包 key/模型id"""
import json
import os
from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(prefix="/api/settings", tags=["settings"])

# config 目录(项目根/config), 与老程序共享 ui_state.json
# backend/app/routers/settings.py -> 上溯4级到项目根
_CONFIG_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))))),
    "config")
UI_STATE_FILE = "ui_state.json"


def _load_state():
    path = os.path.join(_CONFIG_DIR, UI_STATE_FILE)
    try:
        os.makedirs(_CONFIG_DIR, exist_ok=True)
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_state(state):
    path = os.path.join(_CONFIG_DIR, UI_STATE_FILE)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


class AiSettings(BaseModel):
    provider: str = "doubao"   # AI厂商, 目前只支持豆包
    api_key: str = ""
    model_id: str = ""


@router.get("/ai")
def get_ai_settings():
    st = _load_state()
    return {
        "provider": st.get("ai_provider") or "doubao",
        "api_key": st.get("doubao_api_key") or "",
        "model_id": st.get("doubao_model_id") or "",
    }


@router.post("/ai")
def save_ai_settings(payload: AiSettings):
    st = _load_state()
    st["ai_provider"] = payload.provider or "doubao"
    st["doubao_api_key"] = payload.api_key or ""
    st["doubao_model_id"] = payload.model_id or ""
    _save_state(st)
    return {"ok": True}
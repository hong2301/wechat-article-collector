# -*- coding: utf-8 -*-
"""设置数据访问层: settings 表(key-value) + ai_model 表(厂商/key/模型id)"""
from ..database import get_conn


def get_setting(key: str) -> str:
    conn = get_conn()
    try:
        r = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return r["value"] if r else ""
    finally:
        conn.close()


def set_setting(key: str, value: str) -> None:
    conn = get_conn()
    try:
        conn.execute("INSERT INTO settings(key,value) VALUES(?,?)"
                     " ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))
        conn.commit()
    finally:
        conn.close()


def get_ai() -> dict:
    """读 AI 配置: {provider, api_key, models:[...]}; 无数据则空"""
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT provider, api_key, model_id FROM ai_model ORDER BY id").fetchall()
    finally:
        conn.close()
    if not rows:
        return {"provider": "doubao", "api_key": "", "models": []}
    first = dict(rows[0])
    return {"provider": first["provider"], "api_key": first["api_key"],
            "models": [dict(r)["model_id"] for r in rows]}


def save_ai(provider: str, api_key: str, models: list) -> int:
    """清空旧记录, 写入 (provider, api_key, 每个model_id) 一行一条; 返回条数"""
    conn = get_conn()
    try:
        conn.execute("DELETE FROM ai_model")
        provider = provider or "doubao"
        api_key = api_key or ""
        models = models or []
        for m in models:
            conn.execute(
                "INSERT INTO ai_model(provider, api_key, model_id) VALUES(?,?,?)",
                (provider, api_key, m))
        conn.commit()
        return len(models)
    finally:
        conn.close()
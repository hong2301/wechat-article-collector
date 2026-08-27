# -*- coding: utf-8 -*-
"""FastAPI 入口"""
import threading
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .database import init_db
from .routers import accounts, resolve_api, points, scrolls, collect, settings, auto_setup
from .services import ocr as ocr_service

app = FastAPI(title="微信公众号采集器后端", version="4.1.3")

# CORS: 允许前端(localhost:3000 / Electron)访问
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup():
    init_db()
    # 打开程序时即预加载 OCR 引擎(线程内, 不阻塞启动)
    threading.Thread(target=ocr_service.init, daemon=True).start()


@app.on_event("shutdown")
def shutdown():
    """后端退出: 停止微信状态SSE推送(generator及时退出, 防Ctrl+C卡连接) + 恢复任务栏"""
    try:
        from .routers import settings as settings_mod
        settings_mod.stop_wx_stream()
    except Exception:
        pass
    try:
        from .services import computer as pc
        pc.show_taskbar()
    except Exception:
        pass


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/ocr/ready")
def ocr_ready():
    """查询 OCR 引擎是否已就绪"""
    return {"ready": ocr_service.get_ocr_engine() is not None}


app.include_router(accounts.router)
app.include_router(resolve_api.router)
app.include_router(points.router)
app.include_router(scrolls.router)
app.include_router(collect.router)
app.include_router(settings.router)
app.include_router(auto_setup.router)

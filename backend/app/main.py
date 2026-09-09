# -*- coding: utf-8 -*-
"""FastAPI 入口"""
import atexit
import logging
import os
import sys
import threading
from fastapi import FastAPI
from fastapi import Request
from fastapi.middleware.cors import CORSMiddleware

from .database import init_db, data_dir
from .routers import accounts, resolve_api, points, scrolls, collect, settings, auto_setup, conflicts, license
from .core import ocr as ocr_service
from .core import logkit


# ===== 后端日志: 统一日志模块(api/run/error/console 四文件 + 异步落盘 + 双路输出) =====
logkit.setup()


app = FastAPI(title="微信公众号采集器后端", version="4.4.1")

# CORS: 允许前端(localhost:3000 / Electron)访问
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# 接口日志中间件: 记 方法 路径 状态 耗时 -> api.log
from starlette.middleware.base import BaseHTTPMiddleware
app.add_middleware(BaseHTTPMiddleware, dispatch=logkit.api_log_middleware)


@app.on_event("startup")
def startup():
    init_db()
    # 打开程序时即预加载 OCR 引擎(线程内, 不阻塞启动)
    threading.Thread(target=ocr_service.init, daemon=True).start()


@app.on_event("startup")
def startup():
    """后端启动: 性能采样线程(资源+耗时窗口聚合)"""
    try:
        from .core import obs
        obs.start_sampler(interval=60)   # 性能采样线程(资源+耗时窗口聚合)
        obs.timed("startup")(lambda: None)()
    except Exception:
        pass


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.post("/api/logs/report")
async def frontend_log_report(request: Request):
    """前端渲染进程崩溃现场上报 -> error.log"""
    try:
        payload = await request.json()
    except Exception:
        payload = "?"
    logkit.handle_frontend_report(payload)
    return {"ok": True}


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
app.include_router(conflicts.router)
app.include_router(license.router)

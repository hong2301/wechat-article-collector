# -*- coding: utf-8 -*-
"""FastAPI 入口"""
import atexit
import logging
import os
import sys
import threading
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .database import init_db, data_dir
from .routers import accounts, resolve_api, points, scrolls, collect, settings, auto_setup
from .core import ocr as ocr_service


# ===== 后端日志: 统一写入 <数据目录>/logs/backend.log (dev/packaged 均在此) =====
def _setup_logging():
    logdir = os.path.join(data_dir(), "logs")
    os.makedirs(logdir, exist_ok=True)
    logfile = os.path.join(logdir, "backend.log")

    # 1) logging 框架(uvicorn access/error、业务 logger 落盘)
    class _Tee:
        """同时写终端与日志文件"""
        def __init__(self, stream, fh):
            self._s = stream
            self._f = fh
        def write(self, data):
            self._s.write(data)
            self._f.write(data)
            self._f.flush()
        def flush(self):
            self._s.flush()
            self._f.flush()

    try:
        _logger_file = open(logfile, "a", encoding="utf-8")
    except Exception:
        _logger_file = None
    if _logger_file is not None:
        # print()/uvicorn 控制台输出也入文件(打包版无控制台时至少落盘)
        sys.stdout = _Tee(sys.__stdout__, _logger_file)
        sys.stderr = _Tee(sys.__stderr__, _logger_file)
        atexit.register(lambda: _logger_file.close())

    root = logging.getLogger()
    if not any(isinstance(h, logging.FileHandler) for h in root.handlers):
        fh = logging.FileHandler(logfile, encoding="utf-8")
        fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        root.addHandler(fh)


_setup_logging()

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
    """后端退出: 恢复任务栏(防采集结束时任务栏仍隐藏/异常退出遗留)"""
    try:
        from .core import computer as pc
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

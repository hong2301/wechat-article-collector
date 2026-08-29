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
LOG_MAX = 10 * 1024 * 1024        # 单文件上限 10MB
LOG_TRIM_RATIO = 0.7              # 超限后保留末尾 70%(删除最旧 30%)


def _setup_logging():
    logdir = os.path.join(data_dir(), "logs")
    os.makedirs(logdir, exist_ok=True)
    logfile = os.path.join(logdir, "backend.log")

    class _Tee:
        """同时写终端与日志文件; 文件超上限时截断(删最旧 30%)"""
        def __init__(self, stream, fh):
            self._s = stream
            self._f = fh
        def isatty(self):
            return False          # 非终端(uvicorn 据此禁用彩色日志)
        def fileno(self):
            return self._f.fileno()
        def _trim(self):
            self._f.flush()
            size = os.fstat(self._f.fileno()).st_size
            if size <= LOG_MAX:
                return
            keep = int(size * LOG_TRIM_RATIO)
            self._f.seek(size - keep)
            tail = self._f.read()
            self._f.seek(0)
            self._f.truncate()
            self._f.write(tail)
            self._f.flush()
        def write(self, data):
            self._s.write(data)
            self._f.write(data)
            self._trim()
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

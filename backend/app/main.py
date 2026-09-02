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
from .routers import accounts, resolve_api, points, scrolls, collect, settings, auto_setup, conflicts
from .core import ocr as ocr_service


# ===== 后端日志: 统一写入 <数据目录>/logs/(dev/packaged 均在此) =====
LOG_MAX = 10 * 1024 * 1024        # 单文件上限 10MB(按份轮转)
LOG_BACKUP = 3                   # 保留最近的 3 份轮转文件


def _setup_logging():
    logdir = os.path.join(data_dir(), "logs")
    os.makedirs(logdir, exist_ok=True)
    logfile = os.path.join(logdir, "backend.log")
    errfile = os.path.join(logdir, "error.log")     # ERROR+ 独立文件(秒定位)

    class _Tee:
        """同时写终端与日志文件(uvicorn 控制台输出也入文件)"""
        def __init__(self, stream, fh):
            self._s = stream
            self._f = fh
        def isatty(self):
            return False          # 非终端(uvicorn 据此禁用彩色日志)
        def fileno(self):
            return self._f.fileno()
        def write(self, data):
            self._s.write(data)
            self._f.write(data)
        def flush(self):
            self._s.flush()
            self._f.flush()

    try:
        from logging.handlers import RotatingFileHandler
        # 主日志: 10MB×3 轮转; console/uvicorn/业务 全量镜像
        _rfh = RotatingFileHandler(logfile, maxBytes=LOG_MAX, backupCount=LOG_BACKUP,
                                   encoding="utf-8")
        _fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(threadName)s %(message)s")
        _rfh.setFormatter(_fmt)
        # ERROR+ 独立文件(error.log, 2MB×2)
        _efh = RotatingFileHandler(errfile, maxBytes=2 * 1024 * 1024, backupCount=2,
                                   encoding="utf-8")
        _efh.setLevel(logging.ERROR)
        _efh.setFormatter(_fmt)
        root = logging.getLogger()
        if not any(isinstance(h, logging.FileHandler) for h in root.handlers):
            root.addHandler(_rfh)
            root.addHandler(_efh)
        else:
            root.handlers[:] = [_rfh, _efh]   # 替换旧 FileHandler/手动 trim
        root.setLevel(logging.INFO)   # info 级日志(点位识别等)也入文件, 便于排查
        # 过滤: uvicorn 访问日志里的健康轮询(wechat-status 每秒一次, 刷屏无信息量)
        class _SlimAccess(logging.Filter):
            def filter(self, record):
                msg = record.getMessage()
                return "wechat-status" not in msg
        _access = logging.getLogger("uvicorn.access")
        _access.addFilter(_SlimAccess())
        # print()/uvicorn 控制台输出也入文件(打包版无控制台时至少落盘)
        try:
            _logger_file = open(logfile, "a", encoding="utf-8")
            sys.stdout = _Tee(sys.__stdout__, _logger_file)
            sys.stderr = _Tee(sys.__stderr__, _logger_file)
            atexit.register(lambda: _logger_file.close())
        except Exception:
            pass
    except Exception as _e:
        print(f"日志初始化失败(降级): {_e}")


_setup_logging()

app = FastAPI(title="微信公众号采集器后端", version="4.2.3")

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

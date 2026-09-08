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
from .routers import accounts, resolve_api, points, scrolls, collect, settings, auto_setup, conflicts, license
from .core import ocr as ocr_service


# ===== 后端日志: 统一写入 <数据目录>/logs/(dev/packaged 均在此) =====
LOG_MAX = 10 * 1024 * 1024        # 单文件上限 10MB(按份轮转)
LOG_BACKUP = 3                   # 保留最近的 3 份轮转文件


def _setup_logging():
    """日志体系(待优化点4落地: 按 logger 名前缀分流到独立文件):
      - api.log      uvicorn.*(接口访问/uvicorn 生命周期) —— 接口层
      - run.log      collect.*/ocr/perf/auto_setup —— 采集/识别函数运行层
      - error.log    ERROR+ 全量汇总(跨上述来源, 秒定位)
      - console.log  print()/裸控制台输出镜像(打包版无终端时兜底落盘)
    reload 双进程(reload=True): reloader 父进程不持有文件句柄, 避免日志轮转
      rename 被另一进程占用而报 WinError 32; 文件日志只由真正 serve 的子进程持有。
    """
    logdir = os.path.join(data_dir(), "logs")
    os.makedirs(logdir, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(threadName)s %(name)s %(message)s")
    root = logging.getLogger()

    # 文件日志归属判定: 打包版(无 reload)/uvicorn spawn 子进程 -> 开文件;
    # dev reload 的 reloader 父进程 -> 只输出终端, 不持有文件句柄
    import multiprocessing as _mp
    _spawn_child = _mp.parent_process() is not None   # 精确识别 multiprocessing spawn 子进程
    _dev_reload = os.environ.get("APP_DEV_RELOAD") == "1"
    _files = (not _dev_reload) or _spawn_child

    class _Prefix(logging.Filter):
        """按 logger name 前缀路由到对应文件"""
        def __init__(self, names):
            self._names = tuple(names)
        def filter(self, rec):
            return any(rec.name == n or rec.name.startswith(n + ".") for n in self._names)

    try:
        from logging.handlers import RotatingFileHandler
        if _files:
            _api_h = RotatingFileHandler(os.path.join(logdir, "api.log"),
                                         maxBytes=LOG_MAX, backupCount=LOG_BACKUP,
                                         encoding="utf-8")
            _api_h.setFormatter(fmt)
            _api_h.addFilter(_Prefix(("uvicorn",)))          # 接口层日志
            _run_h = RotatingFileHandler(os.path.join(logdir, "run.log"),
                                         maxBytes=LOG_MAX, backupCount=LOG_BACKUP,
                                         encoding="utf-8")
            _run_h.setFormatter(fmt)
            _run_h.addFilter(_Prefix(("collect", "ocr", "perf", "auto_setup")))  # 函数运行层
            _err_h = RotatingFileHandler(os.path.join(logdir, "error.log"),
                                         maxBytes=2 * 1024 * 1024, backupCount=2,
                                         encoding="utf-8")
            _err_h.setLevel(logging.ERROR)   # ERROR+ 全量(不过滤), 秒定位
            _err_h.setFormatter(fmt)
            root.handlers[:] = [_api_h, _run_h, _err_h]
        else:
            root.handlers[:] = []
    except Exception as _e:
        print(f"日志初始化失败(降级): {_e}")

    root.setLevel(logging.INFO)   # info 级日志(点位识别等)也入文件, 便于排查

    # 终端可见性: uvicorn/接口日志 -> stderr(dev 终端直接看; 打包版 stderr 被 _Tee 落 console.log)
    try:
        _csh = logging.StreamHandler(sys.stderr)
        _csh.setFormatter(fmt)
        _csh.addFilter(_Prefix(("uvicorn", "")))   # 含无前缀 root 记录
        root.addHandler(_csh)
    except Exception:
        pass

    # uvicorn 访问日志过滤: 健康轮询(wechat-status 每秒一次)不刷屏
    class _SlimAccess(logging.Filter):
        def filter(self, record):
            return "wechat-status" not in record.getMessage()
    try:
        logging.getLogger("uvicorn.access").addFilter(_SlimAccess())
    except Exception:
        pass

    # print()/裸控制台输出镜像 -> console.log(打包版无控制台时至少落盘; reloader 父进程不镜像)
    if _files:
        try:
            _console_fh = open(os.path.join(logdir, "console.log"), "a", encoding="utf-8")

            class _Tee:
                """同时写终端与 console.log"""
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

            sys.stdout = _Tee(sys.__stdout__, _console_fh)
            sys.stderr = _Tee(sys.__stderr__, _console_fh)
            atexit.register(lambda: _console_fh.close())
        except Exception:
            pass


_setup_logging()

app = FastAPI(title="微信公众号采集器后端", version="4.4.1")

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
app.include_router(license.router)

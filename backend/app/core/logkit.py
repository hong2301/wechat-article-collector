# -*- coding: utf-8 -*-
"""统一日志模块(日志重构): 全项目唯一日志入口与文件维护方

设计要点:
  - 单入口: get_logger(name) —— 替代散落各模块的 log.*/echo/tasks_echo/print 混用
  - 三文件(由本模块维护): api.log(接口) / run.log(函数运行) / error.log(ERROR汇总)
  - 唯一出口: 正常函数一律走 logger(消除 print/裸输出), 不再有控制台文件兜底
  - 异步写盘: 日志先入内存队列, 后台线程统一落盘(QueueHandler+QueueListener), 不卡采集主流程
  - 统一格式: 时间 [级别] 线程 模块.函数 消息 —— 一行看出处
  - 双路输出: collect.* 前缀的日志同时进 run.log + 推前端(tasks_echo钩子), 一处写完两处可见
  - 动态级别: set_level() 运行时调节(排查用, 无需重启)
  - 接口日志: api_log_middleware(FastAPI) 记 方法 路径 状态 耗时 来源 -> api.log
  - 前端上报: handle_frontend_report() 收前端崩溃现场 -> error.log
  - reload 双进程: reloader 父进程不持有文件句柄(见 setup 判定), 避免轮转 rename 被占用
"""
import logging
import logging.handlers
import os
import queue
import sys
import threading
import time as _time

from logging.handlers import QueueHandler, QueueListener, RotatingFileHandler

from .robot import tasks_echo          # 前端实时推送(钩子由 rounters/collect 绑定)

_LOG_MAX = 10 * 1024 * 1024            # run/api 单文件上限
_LOG_KEEP = 3
_ERR_MAX = 2 * 1024 * 1024

_FMT = "%(asctime)s [%(levelname)s] %(threadName)s %(module)s.%(funcName)s %(message)s"
_FMT_SSE = "[%(levelname)s] %(message)s"

_started = False
_listener = None                       # QueueListener 后台写盘线程
_lock = threading.Lock()


def get_logger(name):
    """全项目唯一取日志入口; name 建议子域: collect / api / ocr / perf / auto_setup ..."""
    return logging.getLogger(name)


class _PrefixFilter(logging.Filter):
    """按 logger name 前缀路由(空串=无前缀 root 日志)"""
    def __init__(self, names):
        self._names = tuple(names)

    def filter(self, rec):
        return any(rec.name == n or rec.name.startswith(n + ".") for n in self._names)


class _SseHandler(logging.Handler):
    """日志双路输出: collect.* 前缀的日志除落 run.log 外, 同步推前端(tasks_echo 钩子)"""
    def emit(self, record):
        try:
            tasks_echo(self.format(record))
        except Exception:
            pass


def _file_handlers(logdir, fmt):
    """四类文件 handler(run/api 分流; error 全量 ERROR)"""
    run_h = RotatingFileHandler(os.path.join(logdir, "run.log"),
                                maxBytes=_LOG_MAX, backupCount=_LOG_KEEP, encoding="utf-8")
    run_h.setLevel(logging.INFO)
    run_h.setFormatter(fmt)
    run_h.addFilter(_PrefixFilter(("collect", "ocr", "perf", "auto_setup", "")))
    api_h = RotatingFileHandler(os.path.join(logdir, "api.log"),
                                maxBytes=_LOG_MAX, backupCount=_LOG_KEEP, encoding="utf-8")
    api_h.setLevel(logging.INFO)
    api_h.setFormatter(fmt)
    api_h.addFilter(_PrefixFilter(("uvicorn.error", "uvicorn.startup", "api")))   # 请求行由中间件记(避免与 uvicorn.access 重复)
    err_h = RotatingFileHandler(os.path.join(logdir, "error.log"),
                                maxBytes=_ERR_MAX, backupCount=2, encoding="utf-8")
    err_h.setLevel(logging.ERROR)
    err_h.setFormatter(fmt)
    return run_h, api_h, err_h


def setup(enable_files=None):
    """初始化日志体系(幂等)。
    enable_files=None 时自动判定: 打包单进程/reload spawn子进程 -> 开文件;
    dev reload 的 reloader 父进程 -> 只终端不碰文件(避免轮转 rename 冲突)。
    """
    global _started, _listener
    with _lock:
        if _started:
            return
        # 占位: 先标记避免竞态, 失败再重置
        _started = True
    logdir = os.path.join(_data_dir(), "logs")
    try:
        os.makedirs(logdir, exist_ok=True)
    except Exception:
        logdir = ""

    if enable_files is None:
        import multiprocessing as _mp
        spawn_child = _mp.parent_process() is not None
        dev_reload = os.environ.get("APP_DEV_RELOAD") == "1"
        enable_files = (not dev_reload) or spawn_child

    root = logging.getLogger()
    fmt = logging.Formatter(_FMT)
    sse_fmt = logging.Formatter(_FMT_SSE)
    root.setLevel(logging.INFO)
    root.handlers[:] = []

    # 1) 文件链路: Queue -> QueueListener(异步落盘)
    if enable_files and logdir:
        run_h, api_h, err_h = _file_handlers(logdir, fmt)
        q = queue.Queue(-1)
        _listener = QueueListener(q, run_h, api_h, err_h, respect_handler_level=True)
        _listener.start()
        root.addHandler(QueueHandler(q))

    # 2) 终端可见: uvicorn/接口日志 -> stderr(dev 终端; 打包版无终端则丢弃, 以文件为准)
    try:
        csh = logging.StreamHandler(sys.stderr)
        csh.setFormatter(fmt)
        csh.addFilter(_PrefixFilter(("uvicorn", "api", "")))
        root.addHandler(csh)
    except Exception:
        pass

    # 3) 前端双路输出: collect.* 日志推前端
    try:
        sse = _SseHandler()
        sse.setFormatter(sse_fmt)
        sse.addFilter(_PrefixFilter(("collect",)))
        root.addHandler(sse)
    except Exception:
        pass

    # 4) uvicorn.access 健康轮询不刷屏
    class _Slim(logging.Filter):
        def filter(self, rec):
            return "wechat-status" not in rec.getMessage()
    try:
        logging.getLogger("uvicorn.access").addFilter(_Slim())
    except Exception:
        pass



def _data_dir():
    from ..database import data_dir
    return data_dir()


# ================= 动态级别 =================

def set_level(name="", level=logging.INFO):
    """运行时调整某个 logger 级别(为空=root), 排查用无需重启"""
    logging.getLogger(name).setLevel(level)


# ================= 接口日志中间件 =================

# 高频健康轮询端点(前端每秒级轮询, 无日志价值), 跳过记录防止刷屏 api.log
_SKIP_PATHS = ("/api/health", "/api/settings/wechat-status", "/api/ocr/ready")


async def api_log_middleware(request, call_next):
    """记录每个接口: 方法 路径 状态 耗时(ms) 来源 -> api.log(健康轮询端点跳过)"""
    if request.url.path in _SKIP_PATHS:
        return await call_next(request)
    api = get_logger("api.request")
    t0 = _time.perf_counter()
    try:
        resp = await call_next(request)
    except Exception:
        dur = (_time.perf_counter() - t0) * 1000
        api.error("EXC %s %s %.0fms src=%s", request.method, request.url.path,
                  dur, request.client.host if request.client else "?")
        raise
    dur = (_time.perf_counter() - t0) * 1000
    api.info("%s %s -> %d %.0fms src=%s", request.method, request.url.path,
             resp.status_code, dur, request.client.host if request.client else "?")
    return resp


# ================= 前端错误上报 =================

def handle_frontend_report(payload):
    """前端渲染进程崩溃现场 -> error.log(frontend 域)"""
    get_logger("frontend").error("前端上报: %s", str(payload)[:2000])
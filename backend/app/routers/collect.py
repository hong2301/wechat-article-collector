# -*- coding: utf-8 -*-
"""采集流程路由: 接收前端采集设置与公众号数据, 依次执行 tasks 组合函数, SSE 流式返回日志"""
import json
import queue
import threading
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ..services import tasks as tasks_service
from ..services import computer as pc

router = APIRouter(prefix="/api/collect", tags=["collect"])

# 当前采集 worker 线程 id(用于停止时注入异常强制中断)
_worker_tid = {"tid": None}


class CollectStart(BaseModel):
    collect_type: int = 1    # 采集触发类型: 1=公众号点击采集(可扩展枚举)
    name: str = ""           # 公众号名称
    biz: str = ""            # biz
    link: str = ""           # 拼接好的公众号链接(前端拼好再传)
    date_start: str = ""     # 采集开始日期
    date_end: str = ""       # 采集结束日期
    window_split: bool = True  # 窗口分离
    capture_4metrics: bool = False  # 采集4指标
    capture_read: bool = False       # 采集阅读数


def _sse(data: dict):
    """转 SSE data 帧"""
    return "data: " + json.dumps(data, ensure_ascii=False) + "\n\n"


def _collect_generate(payload: CollectStart):
    """采集流程: 在独立线程执行(死循环阻塞不阻断SSE), 日志经队列缓冲流式发送"""
    log_q = queue.Queue()          # 日志队列
    lock = threading.Lock()
    finished = threading.Event()

    # 日志钩子: 往队列放(生成器主循环从队列读并 yield)
    def hook(msg):
        try:
            log_q.put(("log", msg))
        except Exception:
            pass

    def worker():
        _worker_tid["tid"] = threading.get_ident()
        prev_hook = tasks_service.bind_tasks_echo(hook)
        try:
            # 1) 微信窗口初始化(带窗口分离参数)
            ok, text = tasks_service.init_wechat_window(window_split=payload.window_split)
            log_q.put(("log", f"[微信窗口初始化] {'成功' if ok else '失败'} | {text}"))
            if not ok:
                log_q.put(("done", False, "微信窗口初始化失败"))
                return
            # 2) 采集器窗口初始化
            ok, text = tasks_service.init_app_window()
            log_q.put(("log", f"[采集器窗口初始化] {'成功' if ok else '失败'} | {text}"))
            if not ok:
                log_q.put(("done", False, "采集器窗口初始化失败"))
                return
            # 3) 搜一搜窗口初始化(带窗口分离参数)
            ok, text = tasks_service.search_window_init(window_split=payload.window_split)
            log_q.put(("log", f"[搜一搜窗口初始化] {'成功' if ok else '失败'} | {text}"))
            if not ok:
                log_q.put(("done", False, "搜一搜窗口初始化失败"))
                return
            # 4) 搜一搜查询(链接前端已拼好)
            ok, text = tasks_service.search_query(payload.link)
            log_q.put(("log", f"[搜一搜查询] {'成功' if ok else '失败'} | {text}"))
            if not ok:
                log_q.put(("done", False, "搜一搜查询失败"))
                return
            # 5) 文章列表识别循环(死循环, 前端断开/手动停止时结束)
            log_q.put(("log", "进入文章列表识别循环(可手动停止)"))
            ok, text = tasks_service.article_list_wait_stable(
                date_start=payload.date_start, date_end=payload.date_end)
            log_q.put(("log", f"[文章列表识别循环] {'成功' if ok else '失败'} | {text}"))
            log_q.put(("done", True, "采集流程结束"))
        except SystemExit:
            log_q.put(("log", "采集已停止(强制中断)"))
            log_q.put(("done", False, "user_stopped"))
        except Exception as e:
            log_q.put(("log", f"[异常] {e}"))
            log_q.put(("done", False, str(e)))
        finally:
            _worker_tid["tid"] = None
            tasks_service.bind_tasks_echo(prev_hook)
            tasks_service.clear_stop()   # 清除停止信号
            finished.set()

    tasks_service.clear_stop()   # 新任务开始前清除
    msg = (f"任务: {payload.name} | biz={payload.biz} | "
           f"日期 {payload.date_start} ~ {payload.date_end} | "
           f"窗口分离={'开' if payload.window_split else '关'}")
    yield _sse({"type": "log", "msg": "采集启动"})
    yield _sse({"type": "log", "msg": msg})
    yield _sse({"type": "task", "done": 0, "total": 1})
    threading.Thread(target=worker, daemon=True).start()

    # 主循环: 从队列读日志并 yield(worker 线程阻塞跑死循环也不影响)
    while not finished.is_set() or not log_q.empty():
        try:
            item = log_q.get(timeout=0.3)
        except queue.Empty:
            continue
        with lock:
            if item[0] == "log":
                yield _sse({"type": "log", "msg": item[1]})
            elif item[0] == "done":
                yield _sse({"type": "done", "ok": item[1], "reason": item[2]})
        if item[0] == "done":
            break
    # 队列里可能还有残留日志, 清空发送
    while not log_q.empty():
        item = log_q.get_nowait()
        if item[0] == "log":
            yield _sse({"type": "log", "msg": item[1]})


@router.post("/stop")
def collect_stop():
    """前端关闭采集窗口时调用: 强制中断采集线程(立即停止, 集中在此实现)"""
    import ctypes
    tasks_service.request_stop()          # 信号兜底
    tid = _worker_tid.get("tid")
    if tid:
        # 向 worker 线程注入 SystemExit, 立即打断当前执行的任何步骤
        ctypes.pythonapi.PyThreadState_SetAsyncExc(
            ctypes.c_long(tid), ctypes.py_object(SystemExit))
    return {"ok": True}


@router.post("/start")
def collect_start(payload: CollectStart):
    """启动采集; SSE 流式返回日志与进度"""
    pc.enable_dpi_awareness()   # 确保坐标用物理像素(否则DPI缩放下点击偏移)
    # 客户端断开时(生成器被close)请求停止死循环
    generator = _collect_generate(payload)

    def wrap():
        try:
            yield from generator
        finally:
            tasks_service.request_stop()   # 前端断开 -> 停止死循环
    return StreamingResponse(
        wrap(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
# -*- coding: utf-8 -*-
"""采集流程路由: 接收前端采集设置与公众号数据, 依次执行 tasks 组合函数, SSE 流式返回日志"""
import ctypes
import json
import queue
import threading
import time
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ..services import tasks as tasks_service
from ..services import computer as pc

router = APIRouter(prefix="/api/collect", tags=["collect"])

# 当前采集 worker 线程 id(用于停止时注入异常强制中断)
_worker_tid = {"tid": None}

# ---------- ESC 全局监听: 采集时按 ESC = 停止流程 ----------
_esc_hook = {"h": None, "tid": None, "done": False}
_WH_KEYBOARD_LL = 13        # 低层键盘钩子
_VK_ESCAPE = 0x1B
_LLKHF_INJECTED = 0x00000010


class _KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [("vkCode", ctypes.c_ulong), ("scanCode", ctypes.c_ulong),
                ("flags", ctypes.c_ulong), ("time", ctypes.c_ulong),
                ("dwExtraInfo", ctypes.c_void_p)]


def _esc_callback(code, wparam, lparam):
    if code == 0:
        kb = ctypes.cast(lparam, ctypes.POINTER(_KBDLLHOOKSTRUCT)).contents
        if wparam == 0x0100 and kb.vkCode == _VK_ESCAPE and not (kb.flags & _LLKHF_INJECTED):
            _do_stop()
            return 1   # 拦截 ESC
    if _esc_hook["h"]:
        return pc._u32().CallNextHookEx(_esc_hook["h"], code, wparam, lparam)
    return 0


_esc_proc = pc.HOOKPROC(_esc_callback)


def _start_esc_listener():
    """启动 ESC 全局监听(采集开始后): 按 ESC = 停止流程"""
    if _esc_hook["tid"] is not None:
        return
    _esc_hook["done"] = False   # 重置(上次停止过会置True)
    def run():
        _esc_hook["tid"] = threading.get_ident()
        h = pc._u32().SetWindowsHookExW(
            _WH_KEYBOARD_LL, _esc_proc, pc._k32().GetModuleHandleW(None), 0)
        if not h:
            _esc_hook["h"] = None
            _esc_hook["tid"] = None
            return    # 钩子注册失败, 不再尝试
        _esc_hook["h"] = h
        msg = pc.wt.MSG()
        while not _esc_hook["done"] and pc._u32().GetMessageW(ctypes.byref(msg), None, 0, 0) != 0:
            pc._u32().TranslateMessage(ctypes.byref(msg))
            pc._u32().DispatchMessageW(ctypes.byref(msg))
        if h:
            pc._u32().UnhookWindowsHookEx(h)
        _esc_hook["h"] = None
        _esc_hook["tid"] = None
    threading.Thread(target=run, daemon=True).start()


def _stop_esc_listener():
    """停止 ESC 监听(采集结束时)"""
    _esc_hook["done"] = True
    tid = _esc_hook["tid"]
    if tid:
        pc._u32().PostThreadMessageW(tid, pc.WM_QUIT, 0, 0)


def _do_stop():
    """停止采集: 信号兜底 + 向 worker 线程注入异常立即中断"""
    import ctypes
    tasks_service.request_stop()
    tid = _worker_tid.get("tid")
    if tid:
        ctypes.pythonapi.PyThreadState_SetAsyncExc(
            ctypes.c_long(tid), ctypes.py_object(SystemExit))



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
    save_html: bool = False          # 保存文章为本地HTML(含图片)
    save_dir: str = ""              # 保存HTML根目录(空=默认D:/article_data)


class UpdateStart(BaseModel):
    """单篇更新触发: 初始化窗口 -> 搜一搜查询文章链接 -> article_data_collect(collect_type=2)"""
    biz: str = ""            # 公众号 biz
    name: str = ""           # 公众号名称
    link: str = ""           # 文章链接(前端拼好传)
    window_split: bool = True  # 窗口分离
    capture_4metrics: bool = False  # 采集4指标
    capture_read: bool = False       # 采集阅读数
    save_html: bool = False          # 保存文章为本地HTML(含图片)
    save_dir: str = ""              # 保存HTML根目录(空=默认D:/article_data)


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
                date_start=payload.date_start, date_end=payload.date_end,
                biz=payload.biz, capture_4metrics=payload.capture_4metrics,
                capture_read=payload.capture_read, save_html=payload.save_html,
                save_dir=payload.save_dir)
            log_q.put(("log", f"[文章列表识别循环] {'成功' if ok else '失败'} | {text}"))
            log_q.put(("log", "等待后台异步任务完成..."))
            tasks_service.wait_bg_done()
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
           f"窗口分离={'开' if payload.window_split else '关'} | "
           f"4指标={'开' if payload.capture_4metrics else '关'} | "
           f"阅读数={'开' if payload.capture_read else '关'} | "
           f"保存Html={'开' if payload.save_html else '关'}")
    yield _sse({"type": "log", "msg": "采集启动"})
    yield _sse({"type": "log", "msg": msg})
    yield _sse({"type": "task", "done": 0, "total": 1})
    threading.Thread(target=worker, daemon=True).start()

    # 主循环: 从队列读日志并 yield(worker 线程阻塞跑死循环也不影响)
    # 空闲超过5秒发心跳帧, 保持SSE连接不断开
    last_sent = time.monotonic()
    while not finished.is_set() or not log_q.empty():
        try:
            item = log_q.get(timeout=0.3)
        except queue.Empty:
            now = time.monotonic()
            if now - last_sent >= 5:
                yield _sse({"type": "keepalive"})
                last_sent = now
            continue
        last_sent = time.monotonic()
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


def _update_generate(payload: UpdateStart):
    """单篇更新流程: 窗口初始化 -> 搜一搜查询文章链接 -> article_data_collect(collect_type=2)
    独立于采集流程, SSE 流式返回日志"""
    log_q = queue.Queue()
    lock = threading.Lock()
    finished = threading.Event()

    def hook(msg):
        try:
            log_q.put(("log", msg))
        except Exception:
            pass

    def worker():
        _worker_tid["tid"] = threading.get_ident()
        prev_hook = tasks_service.bind_tasks_echo(hook)
        try:
            # 1) 微信窗口初始化
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
            # 3) 搜一搜窗口初始化
            ok, text = tasks_service.search_window_init(window_split=payload.window_split)
            log_q.put(("log", f"[搜一搜窗口初始化] {'成功' if ok else '失败'} | {text}"))
            if not ok:
                log_q.put(("done", False, "搜一搜窗口初始化失败"))
                return
            # 4) 搜一搜查询(文章链接)
            ok, text = tasks_service.search_query(payload.link)
            log_q.put(("log", f"[搜一搜查询] {'成功' if ok else '失败'} | {text}"))
            if not ok:
                log_q.put(("done", False, "搜一搜查询失败"))
                return
            # 5) 文章数据采集(触发类型2=单篇更新)
            log_q.put(("log", "开始更新该文章数据..."))
            ok, text = tasks_service.article_data_collect(
                collect_type=2, capture_4metrics=payload.capture_4metrics,
                capture_read=payload.capture_read, save_html=payload.save_html,
                save_dir=payload.save_dir, biz=payload.biz)
            log_q.put(("log", f"[文章数据更新] {'成功' if ok else '失败'} | {text}"))
            log_q.put(("log", "等待后台异步任务完成..."))
            tasks_service.wait_bg_done()
            log_q.put(("done", True, "更新流程结束"))
        except SystemExit:
            log_q.put(("log", "更新已停止(强制中断)"))
            log_q.put(("done", False, "user_stopped"))
        except Exception as e:
            log_q.put(("log", f"[异常] {e}"))
            log_q.put(("done", False, str(e)))
        finally:
            _worker_tid["tid"] = None
            tasks_service.bind_tasks_echo(prev_hook)
            tasks_service.clear_stop()
            finished.set()

    tasks_service.clear_stop()
    msg = (f"更新: {payload.name} | {payload.link[:50]} | "
           f"窗口分离={'开' if payload.window_split else '关'} | "
           f"4指标={'开' if payload.capture_4metrics else '关'} | "
           f"阅读数={'开' if payload.capture_read else '关'} | "
           f"保存Html={'开' if payload.save_html else '关'}")
    yield _sse({"type": "log", "msg": "更新启动"})
    yield _sse({"type": "log", "msg": msg})
    yield _sse({"type": "task", "done": 0, "total": 1})
    threading.Thread(target=worker, daemon=True).start()

    last_sent = time.monotonic()
    while not finished.is_set() or not log_q.empty():
        try:
            item = log_q.get(timeout=0.3)
        except queue.Empty:
            now = time.monotonic()
            if now - last_sent >= 5:
                yield _sse({"type": "keepalive"})
                last_sent = now
            continue
        last_sent = time.monotonic()
        with lock:
            if item[0] == "log":
                yield _sse({"type": "log", "msg": item[1]})
            elif item[0] == "done":
                yield _sse({"type": "done", "ok": item[1], "reason": item[2]})
        if item[0] == "done":
            break
    while not log_q.empty():
        item = log_q.get_nowait()
        if item[0] == "log":
            yield _sse({"type": "log", "msg": item[1]})


@router.post("/stop")
def collect_stop():
    """前端关闭采集窗口时调用: 强制中断采集线程(立即停止, 集中在此实现)"""
    import ctypes
    _do_stop()          # 复用统一停止(信号+注入异常)
    return {"ok": True}


@router.post("/start")
def collect_start(payload: CollectStart):
    """启动采集; SSE 流式返回日志与进度"""
    pc.enable_dpi_awareness()   # 确保坐标用物理像素(否则DPI缩放下点击偏移)
    _start_esc_listener()       # 采集开始: 监听 ESC(按ESC=停止流程)
    # 客户端断开时(生成器被close)请求停止死循环
    generator = _collect_generate(payload)

    def wrap():
        try:
            yield from generator
        finally:
            tasks_service.request_stop()   # 前端断开 -> 停止死循环
            _stop_esc_listener()           # 结束ESC监听
    return StreamingResponse(
        wrap(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/update")
def collect_update(payload: UpdateStart):
    """单篇更新: 独立流程(窗口初始化->搜一搜查询文章链接->article_data_collect), SSE 返回日志"""
    pc.enable_dpi_awareness()
    _start_esc_listener()
    generator = _update_generate(payload)

    def wrap():
        try:
            yield from generator
        finally:
            tasks_service.request_stop()
            _stop_esc_listener()
    return StreamingResponse(
        wrap(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
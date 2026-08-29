# -*- coding: utf-8 -*-
"""采集流程路由: 接收前端采集设置与公众号数据, 依次执行 tasks 组合函数, SSE 流式返回日志"""
import ctypes
import json
import queue
import threading
import time as _t
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ..services import tasks as tasks_service
from ..core import computer as pc
from ..services import auto_setup as auto_setup_svc

router = APIRouter(prefix="/api/collect", tags=["collect"])

# 当前采集 worker 线程 id(用于停止时注入异常强制中断)
_worker_tid = {"tid": None}

# 运行中的采集任务计数(公众号采集/文章更新/评论采集; 全部归零=任务全部结束)
_task_count = [0]
_task_count_lock = threading.Lock()


def _task_begin():
    with _task_count_lock:
        _task_count[0] += 1


def _task_end():
    with _task_count_lock:
        _task_count[0] = max(0, _task_count[0] - 1)


def _task_running_count():
    with _task_count_lock:
        return _task_count[0]

# ---------- 输入锁定: 采集时人工键盘/鼠标拦截(程序注入放行), ESC=停止 ----------
_input_lock = None
_last_block_notice = [0.0]


def _do_stop():
    """停止采集: 信号兜底 + 向 worker 线程注入异常立即中断"""
    tasks_service.request_stop()
    tid = _worker_tid.get("tid")
    if tid:
        ctypes.pythonapi.PyThreadState_SetAsyncExc(
            ctypes.c_long(tid), ctypes.py_object(SystemExit))


def _notice_input_block():
    """拦截到人工输入: 提示(限流3秒一次)"""
    now = _t.monotonic()
    if now - _last_block_notice[0] < 3.0:
        return
    _last_block_notice[0] = now
    try:
        tasks_service.tasks_echo("[warn] 采集期间禁用鼠标和键盘，请勿操作! 按 ESC 可停止")
    except Exception:
        pass


def _start_esc_listener():
    """启动采集期间输入锁定: 人工键盘/鼠标拦截, 程序注入放行, ESC=停止"""
    from ..core.inputlock import InputLock
    global _input_lock
    if _input_lock is None:
        _input_lock = InputLock()
        _input_lock.on_esc = _do_stop
        _input_lock.on_block = _notice_input_block
    if not _input_lock._started:
        return _input_lock.start()
    return True


def _stop_esc_listener():
    """停止输入锁定(采集结束时)"""
    global _input_lock
    if _input_lock is not None:
        _input_lock.stop()
        _input_lock = None


class CollectStart(BaseModel):
    collect_type: int = 1    # 采集触发类型: 1=公众号点击采集(可扩展枚举)
    name: str = ""           # 公众号名称
    biz: str = ""            # biz
    link: str = ""           # 拼接好的公众号链接(前端拼好再传)
    date_start: str = ""     # 采集开始日期
    date_end: str = ""       # 采集结束日期
    capture_4metrics: bool = False  # 采集4指标
    capture_read: bool = False       # 采集阅读数
    save_html: bool = False          # 保存文章为本地HTML(含图片)
    save_dir: str = ""              # 保存HTML根目录(空=默认D:/article_data)
    max_comments: int | None = None # 文章最大评论采集数(空=无限, 3个全0=不采评论)
    max_level1: int | None = None   # 一级评论采集数(空=无限)
    max_level2: int | None = 0      # 每级二级评论采集数(默认0=不采二级, null=无限)


class UpdateStart(BaseModel):
    """单篇更新触发: 初始化窗口 -> 搜一搜查询文章链接 -> article_data_collect(collect_type=2)"""
    biz: str = ""            # 公众号 biz
    name: str = ""           # 公众号名称
    link: str = ""           # 文章链接(前端拼好传)
    capture_4metrics: bool = False  # 采集4指标
    capture_read: bool = False       # 采集阅读数
    save_html: bool = False          # 保存文章为本地HTML(含图片)
    save_dir: str = ""              # 保存HTML根目录(空=默认D:/article_data)
    max_comments: int | None = None # 文章最大评论采集数(空=无限, 3个全0=不采评论)
    max_level1: int | None = None   # 一级评论采集数(空=无限)
    max_level2: int | None = 0      # 每级二级评论采集数(默认0=不采二级, null=无限)


class CommentStart(BaseModel):
    """评论采集触发: 初始化窗口 -> 搜一搜查询文章链接 -> article_data_collect(带评论参数)"""
    biz: str = ""            # 公众号 biz
    name: str = ""           # 公众号名称
    link: str = ""           # 文章链接
    capture_4metrics: bool = False  # 采集4指标
    capture_read: bool = False       # 采集阅读数
    save_html: bool = False          # 保存文章为本地HTML(含图片)
    save_dir: str = ""              # 保存HTML根目录
    max_comments: int | None = None # 文章最大评论采集数(空=无限)
    max_level1: int | None = None   # 一级评论采集数(空=无限)
    max_level2: int | None = 0      # 每级二级评论采集数(默认0=不采二级, null=无限)


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
        # 互斥: 一键设置进行中则拒绝启动采集
        if auto_setup_svc.locked():
            log_q.put(("log", "一键设置进行中, 无法启动采集"))
            log_q.put(("done", False, "一键设置进行中"))
            return
        _task_begin()
        prev_hook = tasks_service.bind_tasks_echo(hook)
        try:
            # 1) 微信窗口初始化(带窗口分离参数)
            ok, text = tasks_service.init_wechat_window()
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
            ok, text = tasks_service.search_window_init()
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
                save_dir=payload.save_dir,
                max_comments=payload.max_comments, max_level1=payload.max_level1,
                max_level2=payload.max_level2)
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
            _task_end()
            _worker_tid["tid"] = None
            tasks_service.bind_tasks_echo(prev_hook)
            tasks_service.clear_stop()   # 清除停止信号
            finished.set()

    tasks_service.clear_stop()   # 新任务开始前清除
    msg = (f"任务: {payload.name} | biz={payload.biz} | "
           f"日期 {payload.date_start} ~ {payload.date_end} | "
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
        # 互斥: 一键设置进行中则拒绝启动采集
        if auto_setup_svc.locked():
            log_q.put(("log", "一键设置进行中, 无法启动采集"))
            log_q.put(("done", False, "一键设置进行中"))
            return
        _task_begin()
        prev_hook = tasks_service.bind_tasks_echo(hook)
        try:
            # 1) 微信窗口初始化
            ok, text = tasks_service.init_wechat_window()
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
            ok, text = tasks_service.search_window_init()
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
                save_dir=payload.save_dir, biz=payload.biz,
                max_comments=payload.max_comments, max_level1=payload.max_level1,
                max_level2=payload.max_level2)
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
            _task_end()
        finally:
            _worker_tid["tid"] = None
            tasks_service.bind_tasks_echo(prev_hook)
            tasks_service.clear_stop()
            finished.set()

    tasks_service.clear_stop()
    msg = (f"更新: {payload.name} | {payload.link[:50]} | "
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


def _comment_generate(payload: CommentStart):
    """评论采集流程: 窗口初始化 -> 搜一搜查询文章链接 -> article_data_collect(带评论参数)
    独立于采集/更新流程, SSE 流式返回日志"""
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
        # 互斥: 一键设置进行中则拒绝启动采集
        if auto_setup_svc.locked():
            log_q.put(("log", "一键设置进行中, 无法启动采集"))
            log_q.put(("done", False, "一键设置进行中"))
            return
        _task_begin()
        prev_hook = tasks_service.bind_tasks_echo(hook)
        try:
            # 1) 微信窗口初始化
            ok, text = tasks_service.init_wechat_window()
            log_q.put(("log", f"[微信窗口初始化] {'成功' if ok else '失败'} | {text}"))
            if not ok:
                log_q.put(("done", False, "微信窗口初始化失败")); return
            # 2) 采集器窗口初始化
            ok, text = tasks_service.init_app_window()
            log_q.put(("log", f"[采集器窗口初始化] {'成功' if ok else '失败'} | {text}"))
            if not ok:
                log_q.put(("done", False, "采集器窗口初始化失败")); return
            # 3) 搜一搜窗口初始化
            ok, text = tasks_service.search_window_init()
            log_q.put(("log", f"[搜一搜窗口初始化] {'成功' if ok else '失败'} | {text}"))
            if not ok:
                log_q.put(("done", False, "搜一搜窗口初始化失败")); return
            # 4) 搜一搜查询(文章链接)
            ok, text = tasks_service.search_query(payload.link)
            log_q.put(("log", f"[搜一搜查询] {'成功' if ok else '失败'} | {text}"))
            if not ok:
                log_q.put(("done", False, "搜一搜查询失败")); return
            # 5) 文章数据采集(含评论采集, collect_type=2)
            log_q.put(("log", "开始采集该文章评论..."))
            ok, text = tasks_service.article_data_collect(
                collect_type=2, capture_4metrics=payload.capture_4metrics,
                capture_read=payload.capture_read, save_html=payload.save_html,
                save_dir=payload.save_dir, biz=payload.biz,
                max_comments=payload.max_comments, max_level1=payload.max_level1,
                max_level2=payload.max_level2)
            log_q.put(("log", f"[评论采集流程] {'成功' if ok else '失败'} | {text}"))
            log_q.put(("log", "等待后台异步任务完成..."))
            tasks_service.wait_bg_done()
            log_q.put(("done", True, "评论采集流程结束"))
        except SystemExit:
            log_q.put(("log", "评论采集已停止(强制中断)"))
            log_q.put(("done", False, "user_stopped"))
        except Exception as e:
            log_q.put(("log", f"[异常] {e}"))
            _task_end()
            log_q.put(("done", False, str(e)))
        finally:
            _worker_tid["tid"] = None
            tasks_service.bind_tasks_echo(prev_hook)
            tasks_service.clear_stop()
            finished.set()

    tasks_service.clear_stop()
    msg = (f"评论采集: {payload.name} | {payload.link[:50]} | "
           f"文章评论数={payload.max_comments if payload.max_comments is not None else '无限'} | "
           f"一级评论数={payload.max_level1 if payload.max_level1 is not None else '无限'} | "
           f"每级二级评论数={payload.max_level2 if payload.max_level2 else '0'}")
    yield _sse({"type": "log", "msg": "评论采集启动"})
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


@router.post("/comments")
def collect_comments(payload: CommentStart):
    """评论采集: 独立流程(窗口初始化->搜一搜查询文章链接->article_data_collect带评论参数), SSE 返回日志"""
    pc.enable_dpi_awareness()
    _start_esc_listener()
    generator = _comment_generate(payload)

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

@router.get("/task-state")
def task_state():
    """采集任务状态: 正在运行的任务数(公众号采集/文章更新/评论采集)"""
    return {"running_count": _task_running_count(), "running": _task_running_count() > 0}

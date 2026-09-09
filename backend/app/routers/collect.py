# -*- coding: utf-8 -*-
"""采集流程路由: 接收前端采集设置与公众号数据, 依次执行 tasks 组合函数, SSE 流式返回日志"""
import ctypes
import json
import multiprocessing as _mp
import queue
import threading
import time
import time as _t
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ..services import tasks as tasks_service
from ..core import logkit
from ..core import computer as pc
from ..services import auto_setup as auto_setup_svc
from ..collect_worker import run_collect   # 采集子进程入口(spawn target)

router = APIRouter(prefix="/api/collect", tags=["collect"])

log = logkit.get_logger("collect.collect")   # 采集编排/接口业务日志(collect.* 前缀 -> run.log + 前端双路)

# 采集子进程表(kind -> Process): 主进程统一管理生命周期, 停止=terminate
_procs = {}
_stopping = set()   # 主动终止中的 kind(reader 区分"任务终止"vs"管道断开")
_procs_lock = threading.Lock()


# 当前采集 worker 线程 id(旧注入机制, 保留兼容)
_worker_tid = {"tid": None}


def _pipe_reader(proc, conn, log_q, finished, kind):
    """读采集子进程 Pipe: 日志->主进程logger(run.log+SSE双路); done->log_q; 进程死->兜底done"""
    try:
        while True:
            if conn.poll(0.2):
                msg = conn.recv()
                typ = msg.get("type")
                if typ == "log":
                    lv = msg.get("level", 20)
                    txt = msg.get("msg", "")
                    # 按级别转发: 主进程统一 -> run.log + sse handler->前端(ERROR/WARNING 带红黄色)
                    if lv >= 40:
                        log.error(txt)
                    elif lv >= 30:
                        log.warning(txt)
                    else:
                        log.info(txt)
                elif typ == "done":
                    log_q.put(("done", bool(msg.get("ok")), msg.get("reason", "")))
                    break
            elif not proc.is_alive():
                code = proc.exitcode
                if kind in _stopping or code == 2:
                    log_q.put(("done", False, "user_stopped"))
                else:
                    log_q.put(("done", False, f"采集进程退出(code={code})"))
                break
            elif finished.is_set():
                break
            time.sleep(0.05)
    except (EOFError, OSError) as e:
        if kind in _stopping:
            log_q.put(("done", False, "user_stopped"))        # 主动停止 -> 前端显示"任务已终止"
        else:
            log_q.put(("done", False, f"子进程管道断开({type(e).__name__})"))
    finally:
        _task_end()
        with _procs_lock:
            _procs.pop(kind, None)
            _stopping.discard(kind)
        finished.set()

# 运行中的采集任务计数(公众号采集/文章更新/评论采集; 全部归零=任务全部结束)
_task_count = [0]
_task_count_lock = threading.Lock()


def _task_begin():
    with _task_count_lock:
        _task_count[0] += 1
    log.info("[collect.task] begin count=%d", _task_count[0])


def _task_end():
    with _task_count_lock:
        _task_count[0] = max(0, _task_count[0] - 1)
    log.info("[collect.task] end count=%d", _task_count[0])



def _task_running_count():
    with _task_count_lock:
        return _task_count[0]

# ---------- 输入锁定: 采集时人工键盘/鼠标拦截(程序注入放行), ESC=停止 ----------
_input_lock = None
_last_block_notice = [0.0]


def _do_stop():
    """停止采集: 一整个强行终止子进程(terminate); request_stop 保留做全局信号兜底"""
    log.info("[collect.stop] 终止采集子进程")
    try:
        tasks_service.request_stop()
    except Exception:
        pass
    with _procs_lock:
        procs = list(_procs.items())
        _stopping.update(k for k, p in procs if p.is_alive())
    for kind, proc in procs:
        try:
            if proc.is_alive():
                proc.terminate()
                log.info("[collect.stop] %s 子进程已终止 pid=%s", kind, proc.pid)
        except Exception as e:
            log.warning("[collect.stop] %s 终止异常: %s", kind, e)


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
    capture_keyword: bool = False   # 关键词查询开关
    keyword: str = ""               # 要查询的关键词


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
    capture_keyword: bool = False   # 关键词查询开关
    keyword: str = ""               # 要查询的关键词


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
    capture_keyword: bool = False   # 关键词查询开关
    keyword: str = ""               # 要查询的关键词


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

    def start_proc():
        """spawn 采集子进程 + Pipe 读线程(日志回传主进程)"""
        # 互斥: 一键设置进行中则拒绝启动采集
        if auto_setup_svc.locked():
            log_q.put(("log", "一键设置进行中, 无法启动采集"))
            log_q.put(("done", False, "一键设置进行中"))
            return
        ctx = _mp.get_context("spawn")
        parent_conn, child_conn = ctx.Pipe()
        d = payload.model_dump() if hasattr(payload, "model_dump") else dict(payload)
        d["kind"] = "collect"
        proc = ctx.Process(target=run_collect, args=(d, child_conn),
                           name="collect-collect", daemon=True)
        proc.start()
        child_conn.close()
        with _procs_lock:
            _procs["collect"] = proc
        _task_begin()
        threading.Thread(target=_pipe_reader,
                         args=(proc, parent_conn, log_q, finished, "collect"), daemon=True).start()

    prev_hook = tasks_service.bind_tasks_echo(hook)   # 子进程日志: sse handler -> 前端
    tasks_service.clear_stop()
    msg = (f"任务: {payload.name} | biz={payload.biz} | "
           f"日期 {payload.date_start} ~ {payload.date_end} | "
           f"4指标={'开' if payload.capture_4metrics else '关'} | "
           f"阅读数={'开' if payload.capture_read else '关'} | "
           f"保存Html={'开' if payload.save_html else '关'}")
    log.info("采集启动")
    log.info(msg)
    yield _sse({"type": "task", "done": 0, "total": 1})
    start_proc()

    # 主循环: 从队列读日志并 yield(worker 线程阻塞跑死循环也不影响)
    # 空闲超过5秒发心跳帧, 保持SSE连接不断开
    last_sent = time.monotonic()
    try:
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
    finally:
        # 客户端断开/采集器窗口关闭等任意结束: 请求 worker 停止 -> finally 解锁键鼠
        try:
            tasks_service.request_stop()
        except Exception:
            pass
    tasks_service.bind_tasks_echo(prev_hook)   # 任务结束恢复日志钩子



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

    def start_proc():
        """spawn 采集子进程 + Pipe 读线程(日志回传主进程)"""
        # 互斥: 一键设置进行中则拒绝启动采集
        if auto_setup_svc.locked():
            log_q.put(("log", "一键设置进行中, 无法启动采集"))
            log_q.put(("done", False, "一键设置进行中"))
            return
        ctx = _mp.get_context("spawn")
        parent_conn, child_conn = ctx.Pipe()
        d = payload.model_dump() if hasattr(payload, "model_dump") else dict(payload)
        d["kind"] = "update"
        proc = ctx.Process(target=run_collect, args=(d, child_conn),
                           name="collect-update", daemon=True)
        proc.start()
        child_conn.close()
        with _procs_lock:
            _procs["update"] = proc
        _task_begin()
        threading.Thread(target=_pipe_reader,
                         args=(proc, parent_conn, log_q, finished, "update"), daemon=True).start()

    prev_hook = tasks_service.bind_tasks_echo(hook)   # 子进程日志: sse handler -> 前端
    tasks_service.clear_stop()
    msg = (f"更新: {payload.name} | {payload.link[:50]} | "
           f"4指标={'开' if payload.capture_4metrics else '关'} | "
           f"阅读数={'开' if payload.capture_read else '关'} | "
           f"保存Html={'开' if payload.save_html else '关'}")
    log.info("更新启动")
    log.info(msg)
    yield _sse({"type": "task", "done": 0, "total": 1})
    start_proc()

    last_sent = time.monotonic()
    try:
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
    finally:
        # 客户端断开/采集器窗口关闭等任意结束: 请求 worker 停止 -> finally 解锁键鼠
        try:
            tasks_service.request_stop()
        except Exception:
            pass
    tasks_service.bind_tasks_echo(prev_hook)   # 任务结束恢复日志钩子



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

    def start_proc():
        """spawn 采集子进程 + Pipe 读线程(日志回传主进程)"""
        # 互斥: 一键设置进行中则拒绝启动采集
        if auto_setup_svc.locked():
            log_q.put(("log", "一键设置进行中, 无法启动采集"))
            log_q.put(("done", False, "一键设置进行中"))
            return
        ctx = _mp.get_context("spawn")
        parent_conn, child_conn = ctx.Pipe()
        d = payload.model_dump() if hasattr(payload, "model_dump") else dict(payload)
        d["kind"] = "comments"
        proc = ctx.Process(target=run_collect, args=(d, child_conn),
                           name="collect-comments", daemon=True)
        proc.start()
        child_conn.close()
        with _procs_lock:
            _procs["comments"] = proc
        _task_begin()
        threading.Thread(target=_pipe_reader,
                         args=(proc, parent_conn, log_q, finished, "comments"), daemon=True).start()

    prev_hook = tasks_service.bind_tasks_echo(hook)   # 子进程日志: sse handler -> 前端
    tasks_service.clear_stop()
    msg = (f"评论采集: {payload.name} | {payload.link[:50]} | "
           f"文章评论数={payload.max_comments if payload.max_comments is not None else '无限'} | "
           f"一级评论数={payload.max_level1 if payload.max_level1 is not None else '无限'} | "
           f"每级二级评论数={payload.max_level2 if payload.max_level2 else '0'}")
    log.info("评论采集启动")
    log.info(msg)
    yield _sse({"type": "task", "done": 0, "total": 1})
    start_proc()

    last_sent = time.monotonic()
    try:
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
    finally:
        # 客户端断开/采集器窗口关闭等任意结束: 请求 worker 停止 -> finally 解锁键鼠
        try:
            tasks_service.request_stop()
        except Exception:
            pass
    tasks_service.bind_tasks_echo(prev_hook)   # 任务结束恢复日志钩子



@router.post("/stop")
def collect_stop():
    """前端关闭采集窗口时调用: 强制中断采集线程(立即停止, 集中在此实现)"""
    log.info("[collect.stop] 收到停止请求")
    _do_stop()          # 复用统一停止(信号+注入异常)
    return {"ok": True}


@router.post("/start")
def collect_start(payload: CollectStart):
    """启动采集; SSE 流式返回日志与进度"""
    log.info("[collect.start] 类型=%s 公众号=%r keyword=%r 4指标=%s 阅读数=%s 存html=%s",
             payload.collect_type, payload.name, payload.keyword,
             payload.capture_4metrics, payload.capture_read, payload.save_html)
    pc.enable_dpi_awareness()   # 确保坐标用物理像素(否则DPI缩放下点击偏移)
    _start_esc_listener()       # 采集开始: 监听 ESC(按ESC=停止流程)
    # 客户端断开时(生成器被close)请求停止死循环
    generator = _collect_generate(payload)

    def wrap():
        try:
            yield from generator
        finally:
            _do_stop()                     # 前端断开 -> 终止采集子进程(整体强停)
            _stop_esc_listener()           # 结束ESC监听
    return StreamingResponse(
        wrap(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/update")
def collect_update(payload: UpdateStart):
    """单篇更新: 独立流程(窗口初始化->搜一搜查询文章链接->article_data_collect), SSE 返回日志"""
    log.info("[collect.update] link=%.40s 4指标=%s 阅读数=%s 存html=%s",
             payload.link, payload.capture_4metrics, payload.capture_read, payload.save_html)
    pc.enable_dpi_awareness()
    _start_esc_listener()
    generator = _update_generate(payload)

    def wrap():
        try:
            yield from generator
        finally:
            _do_stop()                     # 前端断开 -> 终止采集子进程(整体强停)
            _stop_esc_listener()
    return StreamingResponse(
        wrap(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/comments")
def collect_comments(payload: CommentStart):
    """评论采集: 独立流程(窗口初始化->搜一搜查询文章链接->article_data_collect带评论参数), SSE 返回日志"""
    log.info("[collect.comments] link=%.40s 评论参数 l1=%s l2=%s",
             payload.link, payload.max_level1, payload.max_level2)
    pc.enable_dpi_awareness()
    _start_esc_listener()
    generator = _comment_generate(payload)

    def wrap():
        try:
            yield from generator
        finally:
            _do_stop()                     # 前端断开 -> 终止采集子进程(整体强停)
            _stop_esc_listener()
    return StreamingResponse(
        wrap(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )

@router.get("/task-state")
def task_state():
    """采集任务状态: 正在运行的任务数(公众号采集/文章更新/评论采集)
    前端轮询(秒级) -> 高频, 不记日志避免刷屏"""
    return {"running_count": _task_running_count(), "running": _task_running_count() > 0}

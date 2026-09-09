# -*- coding: utf-8 -*-
"""自动识别流程路由: 点位/滚动自动设置(进程化: 子进程执行, 可整体强停)"""
import json
import os as _os
import threading
import time
import multiprocessing as _mp
from fastapi import APIRouter, HTTPException

from ..services import auto_setup as as_svc
from ..core import logkit
from ..core.computer import enable_dpi_awareness
from ..repositories import points_repo, scrolls_repo
from ..autosetup_worker import run_autosetup

router = APIRouter(prefix="/api/auto-setup", tags=["auto-setup"])
log = logkit.get_logger("api.auto_setup")

# 自动设置子进程表(kind -> Process): 停止=terminate 整体强杀
_as_procs = {}
_as_lock = threading.Lock()


def _as_stop():
    """终止当前自动设置子进程(ESC/前端 stop/SSE断开 统一入口)"""
    with _as_lock:
        procs = list(_as_procs.values())
        _as_procs.clear()
    for p in procs:
        try:
            if p.is_alive():
                p.terminate()
                log.info("[auto-setup.stop] 子进程已终止 pid=%s", p.pid)
        except Exception as e:
            log.warning("[auto-setup.stop] 终止异常: %s", e)


# 统一 DPI 感知(打包版进程默认非 DPI aware, 缩放下坐标偏差)
def _dpi():
    try:
        enable_dpi_awareness()
    except Exception:
        pass


@router.post("/point/{pid}")
def auto_setup_point(pid: int):
    _dpi()
    """执行该点位的自动识别流程(自动设置子进程, 整体可强停), 成功则写回 x/y"""
    row = points_repo.get(pid)
    if not row:
        log.warning("[auto-setup.point] id=%s 不存在", pid)
        raise HTTPException(404, f"点位不存在 id={pid}")
    try:
        if not as_svc.locked():              # 输入锁开着时直接复用(不重复抢)/否则本次开启
            if not as_svc.lock():
                return {"ok": False, "name": row["name"], "error": "采集进行中"}
        as_svc.set_stop_hook(_as_stop)       # ESC -> terminate 自动设置子进程
        ctx = _mp.get_context("spawn")
        parent, child = ctx.Pipe()
        proc = ctx.Process(target=run_autosetup,
                           args=("point", {"pid": pid, "name": row["name"]}, child),
                           name="autosetup-point", daemon=True)
        proc.start()
        child.close()
        with _as_lock:
            _as_procs["point"] = proc
        # 同步等 done(子进程识别完成/被终止)
        result = None
        try:
            while True:
                if parent.poll(1.0):
                    msg = parent.recv()
                    if msg.get("type") == "log":
                        log.info("[auto-setup.point] %s", msg.get("msg", ""))
                    elif msg.get("type") == "done":
                        result = msg
                        break
                elif not proc.is_alive():
                    result = {"ok": False, "reason": "user_stopped"}
                    break
        except (EOFError, OSError):
            result = {"ok": False, "reason": "子进程管道断开"}
        with _as_lock:
            _as_procs.pop("point", None)
        if result and result.get("ok"):
            extra = result.get("extra") or {}
            log.info("[auto-setup.point] %s -> (%s,%s)", extra.get("name"), extra.get("x"), extra.get("y"))
            return {"ok": True, "name": extra.get("name", row["name"]),
                    "x": extra.get("x"), "y": extra.get("y"), "remark": extra.get("remark")}
        reason = (result or {}).get("reason")
        if reason == "user_stopped":
            return {"ok": False, "name": row["name"], "error": "已停止"}
        return {"ok": False, "name": row["name"], "error": reason or "识别失败"}
    finally:
        as_svc.set_stop_hook(None)


@router.post("/scroll/{sid}")
def auto_setup_scroll(sid: int):
    _dpi()
    """获取滚动距离: 按滚动配置对应点位对(文章列表->15/16, 评论区->35/36)计算
    distance = |左下角.y - 左上角.y|(区域高度), 写回 scrolls(纯计算, 无需子进程)"""
    row = scrolls_repo.get(sid)
    if not row:
        raise HTTPException(404, f"滚动配置不存在 id={sid}")
    pair = {
        "文章列表滚动": (15, 16),
        "评论区滚动": (35, 36),
        "公众号查询文章列表滚动距离": (43, 44),
    }.get(row["name"])
    if not pair:
        return {"ok": False, "name": row["name"], "error": f"未配置点位对应: {row['name']}"}
    p1, p2 = pair
    pt1 = points_repo.get_xy(p1)
    pt2 = points_repo.get_xy(p2)
    if not (pt1 and pt2):
        return {"ok": False, "name": row["name"], "error": f"缺少点位{p1}/{p2}, 无法计算"}
    y1s, y2s = str(pt1["y"] or "").strip(), str(pt2["y"] or "").strip()
    if not (y1s.isdigit() and y2s.isdigit()):
        return {"ok": False, "name": row["name"], "error": f"点位{p1}/{p2} 坐标未设置(需先一键设置校准), 无法计算滚动距离"}
    dist = int(abs(int(y2s) - int(y1s)) * 0.95)   # 区域高度(y绝对值差)再小5%(与 id3/5 一致)
    scrolls_repo.set_distance(sid, dist)
    log.info("[auto-setup.scroll] %s distance=%s (点位%s/%s)", row["name"], dist, p1, p2)
    return {"ok": True, "name": row["name"], "distance": dist, "from": f"点位{p1}/{(p2)}"}


@router.post("/run-all")
def auto_setup_run_all(names: str = ""):
    _dpi()
    """一键设置: 自动设置子进程执行(整体/可强停), 进度经 Pipe 转发 SSE"""
    from fastapi.responses import StreamingResponse
    log.info("[auto-setup.run-all] 开始一键设置 names=%r", names)
    as_svc.set_stop_hook(_as_stop)          # ESC -> 主进程 terminate 自动设置子进程

    def gen():
        import queue as _q
        log_q = _q.Queue()
        ctx = _mp.get_context("spawn")
        parent, child = ctx.Pipe()
        proc = ctx.Process(target=run_autosetup, args=("run_all", {"names": names}, child),
                           name="autosetup-run-all", daemon=True)
        proc.start()
        child.close()
        with _as_lock:
            _as_procs["run_all"] = proc

        def reader():
            try:
                while True:
                    if parent.poll(0.2):
                        msg = parent.recv()
                        if msg.get("type") == "log":
                            log_q.put(msg.get("msg", ""))
                        elif msg.get("type") == "done":
                            log_q.put("__done__")
                            break
                    elif not proc.is_alive():
                        log_q.put("__done__")
                        break
                    time.sleep(0.05)
            except (EOFError, OSError):
                log_q.put("__done__")
            finally:
                with _as_lock:
                    _as_procs.pop("run_all", None)
        threading.Thread(target=reader, daemon=True).start()

        # 残留调试文件逻辑保留
        _dbg = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "..", "..", "auto_setup_dbg.log")
        try:
            if _os.path.exists(_dbg):
                _os.remove(_dbg)
        except Exception:
            pass
        try:
            while True:
                item = log_q.get()
                if item == "__done__":
                    break
                try:
                    with open(_dbg, "a", encoding="utf-8") as f:
                        f.write(item + "\n")
                except Exception:
                    pass
                yield "data: " + json.dumps({"msg": item}, ensure_ascii=False) + "\n\n"
            try:
                proc.join(3)
            except Exception:
                pass
        finally:
            _as_stop()                     # 断开/完成统一清理(已完成的空转无害)
            as_svc.set_stop_hook(None)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.post("/lock")
def auto_setup_lock():
    """前端点击一键设置: 开启输入锁定(人工键鼠拦截+提示); 采集进行中则拒绝"""
    if not as_svc.lock():
        log.warning("[auto-setup.lock] 采集进行中, 拒绝一键设置")
        return {"ok": False, "error": "采集进行中，无法开始一键设置"}
    log.info("[auto-setup.lock] 已开启输入锁定")
    return {"ok": True}


@router.post("/unlock")
def auto_setup_unlock():
    """前端任务结束: 停止输入锁定"""
    r = as_svc.unlock()
    log.info("[auto-setup.unlock] 释放锁=%s", r)
    return {"ok": r}


@router.post("/stop")
def auto_setup_stop():
    """立即停止当前点位自动设置(供前端ESC/快速开始调用): terminate 自动设置子进程整体强停"""
    try:
        _as_stop()
        as_svc.set_stop_hook(None)
        log.info("[auto-setup.stop] 已终止自动设置子进程")
        return {"ok": True}
    except Exception:
        log.error("[auto-setup.stop] 停止调用异常")
        return {"ok": False}
# -*- coding: utf-8 -*-
"""采集子进程入口(multiprocessing spawn target)

把采集编排流程从主进程线程搬到独立子进程:
  - 独立内存/状态, 停止=主进程 terminate() 一整个强杀(不依赖内部轮询)
  - 日志经 Pipe 回传主进程(主进程统一落盘 run.log + 转发 SSE, 单一写者)
  - 退出码: 0=正常完成 1=内部失败 2=被终止

kind: collect(公众号/关键词采集) / update(单篇更新, 含评论采集=其它开关全关只开评论参数)
"""
import multiprocessing
import sys


def _send(pipe, typ, **kw):
    """尽力发消息, 失败静默(pipe 可能已关闭)"""
    try:
        pipe.send({"type": typ, **kw})
    except Exception:
        pass


def _log_hook(pipe):
    """编排日志 -> pipe(主进程统一处理)"""
    def hook(msg):
        try:
            pipe.send({"type": "log", "msg": msg})
        except Exception:
            pass
    return hook




def _normal_end(ok, text):
    """正常流程结束判定(不算失败): 无更多文章 / 时间范围终止"""
    if ok:
        return True
    t = text or ""
    return ("无更多文章" in t) or ("日期范围" in t) or ("已过日期范围" in t)


def _do_collect(pipe, payload):
    """公众号/关键词采集编排(原 collect.py worker 主分支)"""
    from .services import tasks as tasks_service
    from .core import robot as robot_mod

    def emit(msg):
        _send(pipe, "log", msg=msg)

    robot_mod.bind_tasks_echo(_log_hook(pipe))   # tasks 内部 tasks_echo 也进管道
    try:
        # 1) 微信窗口初始化(带窗口分离参数)
        ok, text = tasks_service.init_wechat_window()
        emit(f"[微信窗口初始化] {'成功' if ok else '失败'} | {text}")
        if not ok:
            _send(pipe, "done", ok=False, reason="微信窗口初始化失败")
            return 1
        # 2) 采集器窗口初始化
        ok, text = tasks_service.init_app_window()
        emit(f"[采集器窗口初始化] {'成功' if ok else '失败'} | {text}")
        if not ok:
            _send(pipe, "done", ok=False, reason="采集器窗口初始化失败")
            return 1
        # 3) 搜一搜窗口初始化
        ok, text = tasks_service.search_window_init()
        emit(f"[搜一搜窗口初始化] {'成功' if ok else '失败'} | {text}")
        if not ok:
            _send(pipe, "done", ok=False, reason="搜一搜窗口初始化失败")
            return 1
        # 4) 搜一搜查询
        ok, text = tasks_service.search_query(payload.get("link") or "")
        emit(f"[搜一搜查询] {'成功' if ok else '失败'} | {text}")
        if not ok:
            _send(pipe, "done", ok=False, reason="搜一搜查询失败")
            return 1
        # 5) 关键词分支
        _kw = (payload.get("keyword") or "").strip()
        if _kw:
            emit(f"[关键词查询] 分支启动 (关键词={_kw!r})")
            ok, text = tasks_service.gzh_query_page_init(keyword=_kw)
            emit(f"[公众号查询页初始化] {'成功' if ok else '失败'} | {text}")
            if not ok:
                _send(pipe, "done", ok=False, reason="公众号查询页初始化失败")
                return 1
            ok2, text2 = tasks_service.gzh_query_page_article_loop(
                date_start=payload.get("date_start") or "",
                date_end=payload.get("date_end") or "",
                biz=payload.get("biz") or "",
                capture_4metrics=bool(payload.get("capture_4metrics")),
                capture_read=bool(payload.get("capture_read")),
                save_html=bool(payload.get("save_html")),
                save_dir=payload.get("save_dir") or "",
                max_comments=payload.get("max_comments"),
                max_level1=payload.get("max_level1"),
                max_level2=payload.get("max_level2") or 0)
            emit(f"[公众号查询页文章列表循环] 结束 | {text2}")
            tasks_service.wait_bg_done()   # 正常结束前等异步任务全部完成
            _send(pipe, "done", ok=_normal_end(ok2, text2), reason=text2 or "关键词查询流程结束")
            return 0 if _normal_end(ok2, text2) else 1
        # 5b) 旧流程: 文章列表识别循环(死循环, 被终止时整体强杀)
        emit("进入文章列表识别循环(按ESC/停止可整体终止)")
        ok, text = tasks_service.article_list_wait_stable(
            date_start=payload.get("date_start") or "",
            date_end=payload.get("date_end") or "",
            biz=payload.get("biz") or "",
            capture_4metrics=bool(payload.get("capture_4metrics")),
            capture_read=bool(payload.get("capture_read")),
            save_html=bool(payload.get("save_html")),
            save_dir=payload.get("save_dir") or "",
            max_comments=payload.get("max_comments"),
            max_level1=payload.get("max_level1"),
            max_level2=payload.get("max_level2") or 0)
        emit(f"[文章列表识别循环] {'成功' if ok else '失败'} | {text}")
        emit("等待后台异步任务完成...")
        tasks_service.wait_bg_done()   # 正常结束前等异步任务全部完成
        _send(pipe, "done", ok=_normal_end(ok, text), reason=text or "采集流程结束")
        return 0 if _normal_end(ok, text) else 1
    except Exception as e:
        _send(pipe, "log", msg=f"[异常] {e}")
        _send(pipe, "done", ok=False, reason=str(e))
        return 1


def _do_update(pipe, payload):
    """单篇更新编排"""
    from .services import tasks as tasks_service
    from .core import robot as robot_mod
    robot_mod.bind_tasks_echo(_log_hook(pipe))
    try:
        ok, text = tasks_service.init_wechat_window()
        _send(pipe, "log", msg=f"[微信窗口初始化] {'成功' if ok else '失败'} | {text}")
        if not ok:
            _send(pipe, "done", ok=False, reason="微信窗口初始化失败"); return 1
        ok, text = tasks_service.init_app_window()
        _send(pipe, "log", msg=f"[采集器窗口初始化] {'成功' if ok else '失败'} | {text}")
        if not ok:
            _send(pipe, "done", ok=False, reason="采集器窗口初始化失败"); return 1
        ok, text = tasks_service.search_window_init()
        _send(pipe, "log", msg=f"[搜一搜窗口初始化] {'成功' if ok else '失败'} | {text}")
        if not ok:
            _send(pipe, "done", ok=False, reason="搜一搜窗口初始化失败"); return 1
        ok, text = tasks_service.search_query(payload.get("link") or "")
        _send(pipe, "log", msg=f"[搜一搜查询] {'成功' if ok else '失败'} | {text}")
        if not ok:
            _send(pipe, "done", ok=False, reason="搜一搜查询失败"); return 1
        from .services.tasks import article_data_collect
        r = article_data_collect(
            collect_type=2,
            capture_4metrics=bool(payload.get("capture_4metrics")),
            capture_read=bool(payload.get("capture_read")),
            save_html=bool(payload.get("save_html")),
            save_dir=payload.get("save_dir") or "",
            biz=payload.get("biz") or "",
            max_comments=payload.get("max_comments"),
            max_level1=payload.get("max_level1"),
            max_level2=payload.get("max_level2") or 0)
        tasks_service.wait_bg_done()
        _send(pipe, "done", ok=bool(r), reason="更新流程结束" if r else "更新失败")
        return 0 if r else 1
    except Exception as e:
        _send(pipe, "log", msg=f"[异常] {e}")
        _send(pipe, "done", ok=False, reason=str(e))
        return 1


def run_collect(payload: dict, pipe):
    """spawn target: 子进程入口. payload: dict; pipe: multiprocessing Pipe 子端
    子进程启动即预热 OCR 引擎(确保采集识别阶段直接用已就绪引擎, 不在流程中途卡首次加载)"""
    kind = str(payload.get("kind") or "collect")
    _send(pipe, "log", msg=f"[进程] 采集子进程启动 pid={multiprocessing.current_process().pid} kind={kind}")
    try:
        # OCR 核心能力: 子进程启动阶段直接加载(静默, 不进前端日志; 加载错误由 ocr 模块内部记录)
        from .core import ocr as ocr_service
        ocr_service.init()
    except Exception:
        pass
    try:
        try:
            from .core.logkit import setup_child
            setup_child(pipe)   # 子进程日志只有 Pipe 通道(不写文件, 单一写者=主进程)
        except ImportError:
            pass
        if kind == "update":
            code = _do_update(pipe, payload)
        else:
            code = _do_collect(pipe, payload)   # collect / 未知归采集
        _send(pipe, "log", msg=f"[进程] 采集子进程结束 code={code}")
        return code
    except Exception as e:
        _send(pipe, "log", msg=f"[进程] 子进程异常: {e}")
        _send(pipe, "done", ok=False, reason=str(e))
        return 1


def main():
    """调试入口: python -m app.collect_worker <kind> <payload.json> <pipe_fd>"""
    # 正常路径由 multiprocessing spawn 调用, 此处仅便于人工调试
    pass


if __name__ == "__main__":
    main()
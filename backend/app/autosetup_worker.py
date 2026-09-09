# -*- coding: utf-8 -*-
"""自动设置子进程入口(multiprocessing spawn target)

与采集进程化同构: 一键设置/单点位自动设置跑独立子进程
  - 识别流程(run_all_points_stream / run_point_flow)与引擎在子进程内执行
  - 日志/进度经 Pipe 回传主进程(主进程转发 SSE)
  - 停止 = 主进程 terminate() 一整个强杀(不依赖内部优雅退出)
kind: run_all(一键设置全部点位) / point(单点位自动设置)
"""
import multiprocessing


def _send(pipe, typ, **kw):
    try:
        pipe.send({"type": typ, **kw})
    except Exception:
        pass


def run_autosetup(kind: str, payload: dict, pipe):
    """spawn target: 自动设置子进程入口"""
    _send(pipe, "log", msg=f"[进程] 自动设置子进程启动 pid={multiprocessing.current_process().pid} kind={kind}")
    try:
        # 子进程日志只有 Pipe 通道(engine 的 auto_setup logger 消息也回传)
        from .core.logkit import setup_child
        setup_child(pipe)
    except Exception:
        pass
    try:
        from .repositories import points_repo
        if kind == "run_all":
            from .services.autosetup.engine import run_all_points_stream
            names = payload.get("names") or ""
            for msg in run_all_points_stream(names):
                _send(pipe, "log", msg=msg)
                if msg.startswith("[done]"):
                    break
            _send(pipe, "done", ok=True, reason="一键设置结束")
            return 0
        elif kind == "point":
            from .services.autosetup.engine import run_point_flow
            pid = int(payload.get("pid") or 0)
            row = points_repo.get(pid)
            if not row:
                _send(pipe, "log", msg=f"[fail] 点位不存在 id={pid}")
                _send(pipe, "done", ok=False, reason=f"点位不存在 id={pid}")
                return 1
            name = row["name"]
            _send(pipe, "log", msg=f"[step] ⏳ 开始设置: {name}")
            x, y, remark, err = run_point_flow(name)
            if x is None:
                _send(pipe, "log", msg=f"[fail] ✗ {name}: {err or '识别失败'}")
                _send(pipe, "done", ok=False, reason=err or "识别失败")
                return 1
            # 点位9: 非99999(真实识别到坐标)时清除备注; 99999 待定保留备注
            points_repo.set_coords(pid, x, y, remark if x == 99999 else "")
            _send(pipe, "log", msg=f"[ok] ✓ {name} = ({x},{y})")
            _send(pipe, "done", ok=True, reason="",
                  extra={"name": name, "x": x, "y": y, "remark": remark})
            return 0
        else:
            _send(pipe, "done", ok=False, reason=f"未知kind: {kind}")
            return 1
    except Exception as e:
        _send(pipe, "log", msg=f"[进程] 自动设置异常: {e}")
        _send(pipe, "done", ok=False, reason=str(e))
        return 1


def main():
    pass


if __name__ == "__main__":
    main()
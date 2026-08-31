# -*- coding: utf-8 -*-
"""冲突软件检测: 采集/自动设置前检查本机是否有会干扰屏幕操作的软件在运行
(弹截图/遮挡/抢快捷键等), 便于提前提示或直接关闭其进程

数据来源: 数据库 conflict_apps 表(软件名 + 窗口标题数组 + 进程名数组)
返回: 无冲突 True; 有冲突 False + 冲突软件数组(字段与表一致, 另附命中的窗口/进程 pid 便于定位关闭)
"""
import json

from ..database import get_conn


def _rows():
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT id, name, window_titles, process_names FROM conflict_apps ORDER BY id").fetchall()
    finally:
        conn.close()
    out = []
    for rid, name, titles, procs in rows:
        try:
            titles = json.loads(titles or "[]")
        except Exception:
            titles = []
        try:
            procs = json.loads(procs or "[]")
        except Exception:
            procs = []
        out.append({"id": rid, "name": name,
                    "window_titles": titles, "process_names": procs})
    return out


def _match_windows(keywords):
    """窗口标题子串匹配(标题含任一关键词): 返回 [(hwnd, title, pid)]"""
    from ..core import computer as pc
    hits = []
    for h, t, pid, _vis in pc._enum_all_windows():
        if not t:
            continue
        if any(k and k.lower() in t.lower() for k in keywords):
            hits.append((h, t, pid))
    return hits


def _match_processes(procs):
    """进程名匹配(任一进程名在运行): 返回 [pid...]"""
    from ..core import computer as pc
    if not procs:
        return []
    try:
        return pc._pids_by_exe(procs)
    except Exception:
        return []


def check_conflicts():
    """检查本机冲突软件(读取 conflict_apps 表)

    返回: (无冲突?, 冲突软件数组)
      无冲突: (True, [])
      有冲突: (False, [{"id", "name", "window_titles", "process_names",
                        "matched_windows": [(hwnd, title, pid)...],
                        "matched_pids": [pid...]}, ...])
      仅命中窗口无进程时 matched_pids 可为空(反之亦然); 数组中仅含确实命中的条目
    """
    conflict = []
    for row in _rows():
        windows = _match_windows(row["window_titles"])
        pids = _match_processes(row["process_names"])
        if windows or pids:
            entry = dict(row)
            entry["matched_windows"] = windows
            entry["matched_pids"] = pids
            conflict.append(entry)
    return (not conflict, conflict)


def list_conflicts():
    """读取冲突软件表全部条目(供前端展示/编辑): 字段与表一致"""
    return _rows()
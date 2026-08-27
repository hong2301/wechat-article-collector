# -*- coding: utf-8 -*-
"""自动识别流程路由: 触发点位/滚动自动设置(执行对应流程函数, 识别成功写回数据库)

POST /api/auto-setup/point/{pid}    自动设置单个点位(识别后写回 x/y)
POST /api/auto-setup/scroll/{sid}   自动设置单条滚动(识别后写回 distance)
"""
from fastapi import APIRouter, HTTPException

from ..database import get_conn
from ..services import auto_setup as as_svc

router = APIRouter(prefix="/api/auto-setup", tags=["auto-setup"])


@router.post("/point/{pid}")
def auto_setup_point(pid: int):
    """执行该点位的自动识别流程, 成功则写回 x/y"""
    conn = get_conn()
    try:
        row = conn.execute("SELECT id, name FROM points WHERE id=?", (pid,)).fetchone()
    finally:
        conn.close()
    if not row:
        raise HTTPException(404, f"点位不存在 id={pid}")
    name = row["name"]
    x, y, remark, err = as_svc.run_point_flow(name)
    if x is None:
        return {"ok": False, "name": name, "error": err or "识别失败"}
    conn = get_conn()
    try:
        conn.execute("UPDATE points SET x=?, y=?, remark=? WHERE id=?", (x, y, remark, pid))
        conn.commit()
    finally:
        conn.close()
    return {"ok": True, "name": name, "x": x, "y": y, "remark": remark}


@router.post("/scroll/{sid}")
def auto_setup_scroll(sid: int):
    """执行滚动自动识别流程, 成功则写回 distance"""
    conn = get_conn()
    try:
        row = conn.execute("SELECT id, name FROM scrolls WHERE id=?", (sid,)).fetchone()
    finally:
        conn.close()
    if not row:
        raise HTTPException(404, f"滚动配置不存在 id={sid}")
    name = row["name"]
    dist, _unused, err = as_svc.run_scroll_flow(name)
    if dist is None:
        return {"ok": False, "name": name, "error": err or "识别失败"}
    conn = get_conn()
    try:
        conn.execute("UPDATE scrolls SET distance=? WHERE id=?", (dist, sid))
        conn.commit()
    finally:
        conn.close()
    return {"ok": True, "name": name, "distance": dist}

@router.post("/run-all")
def auto_setup_run_all():
    """一键设置: 按依赖顺序执行全部点位自动设置(输入锁定全程, ESC可停)"""
    return as_svc.run_all_points()

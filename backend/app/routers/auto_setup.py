# -*- coding: utf-8 -*-
"""自动识别流程路由: 触发点位/滚动自动设置(执行对应流程函数, 识别成功写回数据库)

POST /api/auto-setup/point/{pid}    自动设置单个点位(识别后写回 x/y)
POST /api/auto-setup/scroll/{sid}   自动设置单条滚动(识别后写回 distance)
"""
import json
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
    # 点位9: 非99999(真实识别到坐标)时清除备注(待定场景99999才保留备注)
    if x != 99999:
        remark = ""
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
    """一键设置: 按依赖顺序执行全部点位(输入锁全程, ESC可停), SSE流式逐点位提示"""
    from fastapi.responses import StreamingResponse

    def gen():
        # 直接迭代真生成器: 每条事件立即转发(不要攒队列!)
        for msg in as_svc.run_all_points_stream():
            yield "data: " + json.dumps({"msg": msg}, ensure_ascii=False) + "\n\n"
            if msg.startswith("[done]"):
                break

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.post("/lock")
def auto_setup_lock():
    """前端点击一键设置: 开启输入锁定(人工键鼠拦截+提示); 采集进行中则拒绝"""
    if not as_svc.lock():
        return {"ok": False, "error": "采集进行中，无法开始一键设置"}
    return {"ok": True}


@router.post("/unlock")
def auto_setup_unlock():
    """前端任务结束: 停止输入锁定"""
    return {"ok": as_svc.unlock()}


# -*- coding: utf-8 -*-
"""自动识别流程路由: 触发点位/滚动自动设置(执行对应流程函数, 识别成功写回数据库)

POST /api/auto-setup/point/{pid}    自动设置单个点位(识别后写回 x/y)
POST /api/auto-setup/scroll/{sid}   自动设置单条滚动(识别后写回 distance)
"""
import json
from fastapi import APIRouter, HTTPException

from ..services import auto_setup as as_svc
from ..services.computer import enable_dpi_awareness
from ..repositories import points_repo, scrolls_repo

router = APIRouter(prefix="/api/auto-setup", tags=["auto-setup"])


# 统一 DPI 感知(打包版进程默认非 DPI aware, 缩放下 GetSystemMetrics 返回虚拟像素导致坐标偏差)
def _dpi():
    try:
        enable_dpi_awareness()
    except Exception:
        pass


@router.post("/point/{pid}")
def auto_setup_point(pid: int):
    _dpi()
    """执行该点位的自动识别流程, 成功则写回 x/y"""
    row = points_repo.get(pid)
    if not row:
        raise HTTPException(404, f"点位不存在 id={pid}")
    name = row["name"]
    x, y, remark, err = as_svc.run_point_flow(name)
    if x is None:
        return {"ok": False, "name": name, "error": err or "识别失败"}
    # 点位9: 非99999(真实识别到坐标)时清除备注; 99999 待定保留备注(set_coords 内部处理)
    points_repo.set_coords(pid, x, y, remark if x == 99999 else "")
    return {"ok": True, "name": name, "x": x, "y": y, "remark": remark}


@router.post("/scroll/{sid}")
def auto_setup_scroll(sid: int):
    _dpi()
    """获取滚动距离: 按滚动配置对应点位对(文章列表->15/16, 评论区->35/36)计算
    distance = |左下角.y - 左上角.y|(区域高度), 写回 scrolls"""
    row = scrolls_repo.get(sid)
    if not row:
        raise HTTPException(404, f"滚动配置不存在 id={sid}")
    # 滚动配置 -> 对应范围点位对
    pair = {
        "文章列表滚动": (15, 16),
        "评论区滚动": (35, 36),
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
    dist = int(abs(int(y2s) - int(y1s)) * 0.95)   # 区域高度(y绝对值差)再小5%
    scrolls_repo.set_distance(sid, dist)
    return {"ok": True, "name": row["name"], "distance": dist, "from": f"点位{p1}/{(p2)}"}

@router.post("/run-all")
def auto_setup_run_all(names: str = ""):
    _dpi()
    """一键设置: 按依赖顺序执行全部点位(names为空)或仅指定点位(逗号分隔, 单点位自动设置用), SSE流式逐点位提示"""
    from fastapi.responses import StreamingResponse

    import os as _os
    _dbg = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "..", "..", "auto_setup_dbg.log")
    try:
        if _os.path.exists(_dbg):
            _os.remove(_dbg)
    except Exception:
        pass

    def gen():
        # 直接迭代真生成器: 每条事件立即转发(不要攒队列!)
        for msg in as_svc.run_all_points_stream(names):
            # 临时调试: 事件写文件
            try:
                with open(_dbg, "a", encoding="utf-8") as f:
                    f.write(msg + "\n")
            except Exception:
                pass
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


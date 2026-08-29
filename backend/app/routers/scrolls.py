# -*- coding: utf-8 -*-
"""滚动(scrolls) CRUD 路由 + 执行滚动"""
import io
import csv
from typing import List
from fastapi import APIRouter, HTTPException, UploadFile, File
from pydantic import BaseModel

from ..models import Scroll, ScrollCreate, ScrollUpdate
from ..repositories import scrolls_repo

router = APIRouter(prefix="/api/scrolls", tags=["scrolls"])


@router.get("", response_model=list[Scroll])
def list_scrolls():
    return scrolls_repo.list_all()


@router.post("", response_model=Scroll, status_code=201)
def create_scroll(payload: ScrollCreate):
    return scrolls_repo.create(payload.name, payload.distance, payload.point_id,
                               payload.direction, payload.remark)


@router.put("/{sid}", response_model=Scroll)
def update_scroll(sid: int, payload: ScrollUpdate):
    if not scrolls_repo.get(sid):
        raise HTTPException(404, "滚动配置不存在")
    return scrolls_repo.update(sid, payload.model_dump(exclude_unset=True))


@router.delete("/{sid}", status_code=204)
def delete_scroll(sid: int):
    if not scrolls_repo.delete(sid):
        raise HTTPException(404, "滚动配置不存在")


# ---------- 导入（CSV/XLSX） ----------
SCROLL_KEYS = {"滚动id", "id"}
SCROLL_NAME_KEYS = {"滚动名称", "名称", "name"}
SCROLL_DIST_KEYS = {"滚动距离", "距离", "distance"}
SCROLL_POINT_KEYS = {"滚动点位id", "点位id", "point_id", "点位"}
SCROLL_DIR_KEYS = {"滚动方向", "方向", "direction"}
SCROLL_REMARK_KEYS = {"备注", "remark"}


def _parse_scroll_file(filename, raw):
    """解析滚动配置文件为 [{id,name,distance,point_id,direction,remark}, ...]; 支持 csv/xlsx"""
    ext = (filename or "").lower().rsplit(".", 1)[-1]
    rows = []
    if ext in ("xlsx", "xlsm"):
        try:
            import openpyxl
            wb = openpyxl.load_workbook(io.BytesIO(raw))
            ws = wb.active
            rows = [[c.value for c in row] for row in ws.iter_rows()]
        except Exception:
            raise HTTPException(400, "xlsx 解析失败，请检查文件格式")
    else:
        try:
            text = raw.decode("utf-8-sig", errors="replace")
        except Exception:
            text = raw.decode("gbk", errors="replace")
        rows = list(csv.reader(io.StringIO(text)))
    if not rows:
        return []
    head = [str(c or "").strip() for c in rows[0]]
    has_head = any(h in SCROLL_KEYS or h in SCROLL_NAME_KEYS or h in SCROLL_POINT_KEYS
                   for h in head)
    data_rows = rows[1:] if has_head else rows
    result = []
    for r in data_rows:
        if not any(str(c or "").strip() for c in r):
            continue
        if has_head:
            d = {}
            for i, h in enumerate(head):
                v = r[i] if i < len(r) else ""
                if h in SCROLL_KEYS:
                    d["id"] = v
                elif h in SCROLL_NAME_KEYS:
                    d["name"] = v
                elif h in SCROLL_DIST_KEYS:
                    d["distance"] = v
                elif h in SCROLL_POINT_KEYS:
                    d["point_id"] = v
                elif h in SCROLL_DIR_KEYS:
                    d["direction"] = v
                elif h in SCROLL_REMARK_KEYS:
                    d["remark"] = v
        else:
            d = {"id": r[0] if len(r) > 0 else "",
                 "name": r[1] if len(r) > 1 else "",
                 "distance": r[2] if len(r) > 2 else "",
                 "point_id": r[3] if len(r) > 3 else "",
                 "direction": r[4] if len(r) > 4 else "",
                 "remark": r[5] if len(r) > 5 else ""}
        if (d.get("name") or d.get("distance") or d.get("point_id")
                or d.get("direction") or d.get("remark") or d.get("id")):
            result.append(d)
    return result


@router.post("/import")
def import_scrolls(file: UploadFile = File(...)):
    """上传滚动配置表格文件, 解析并入点(同 id 存在则更新, 否则新增)"""
    raw = file.file.read() if hasattr(file, "file") else file.read()
    rows = _parse_scroll_file(file.filename or "", raw)
    if not rows:
        raise HTTPException(400, "文件为空或无法解析")
    added, updated = scrolls_repo.import_upsert(rows)
    return {"ok": True, "added": added, "updated": updated, "total": len(rows)}


@router.post("/{sid}/run")
def run_scroll(sid: int):
    """执行滚动: 把鼠标移到滚动点位所在坐标, 按配置方向/距离滚动"""
    from ..services import computer as pc
    s = scrolls_repo.get(sid)
    if not s:
        raise HTTPException(404, "滚动配置不存在")
    pt = scrolls_repo.get_point_xy(s.get("point_id") or 0)
    if not pt:
        return {"ok": False, "reason": "滚动点位不存在或未配置坐标"}

    pc.enable_dpi_awareness()
    try:
        x = int(float(pt["x"]))
        y = int(float(pt["y"]))
        dist = int(float((s.get("distance") or 0)))
        direction = s.get("direction") or "down"
        pc.scroll(x, y, dist, direction=direction)
        return {"ok": True, "x": x, "y": y, "distance": dist, "direction": direction}
    except (TypeError, ValueError):
        return {"ok": False, "reason": "坐标或距离无效"}
    except Exception as e:
        return {"ok": False, "reason": str(e)}
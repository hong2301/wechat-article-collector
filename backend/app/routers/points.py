# -*- coding: utf-8 -*-
"""点位(points) CRUD 路由"""
import io
import csv
from typing import List
from fastapi import APIRouter, HTTPException, UploadFile, File
from pydantic import BaseModel

from ..models import Point, PointCreate, PointUpdate
from ..repositories import points_repo

router = APIRouter(prefix="/api/points", tags=["points"])


@router.get("", response_model=list[Point])
def list_points():
    return points_repo.list_with_sort()


@router.post("", response_model=Point, status_code=201)
def create_point(payload: PointCreate):
    return points_repo.create(payload.name, payload.x, payload.y, payload.remark)


@router.put("/{pid}", response_model=Point)
def update_point(pid: int, payload: PointUpdate):
    if not points_repo.get(pid):
        raise HTTPException(404, "点位不存在")
    return points_repo.update(pid, payload.model_dump(exclude_unset=True))


@router.delete("/{pid}", status_code=204)
def delete_point(pid: int):
    if not points_repo.delete(pid):
        raise HTTPException(404, "点位不存在")


class BatchDelete(BaseModel):
    ids: List[int]


class PreviewPayload(BaseModel):
    x: float
    y: float
    duration: float = 1.0


@router.post("/preview")
def preview_point(payload: PreviewPayload):
    """在屏幕坐标 (x,y) 亮红点预览 duration 秒(默认1)
    返回: {"ok": true}"""
    from ..core import computer as pc
    pc.enable_dpi_awareness()
    pc.preview_point(payload.x, payload.y, duration=payload.duration or 1.0)
    return {"ok": True}


@router.post("/capture")
def capture_point():
    """阻塞采集屏幕坐标: 前端遮罩期间调用;
    左键单击记录(前端轮询preview)、双击确认、右键退出。
    返回: {"x":..,"y":..} 或 {"canceled": true}"""
    from ..core import computer as pc
    pc.enable_dpi_awareness()
    pc.clear_latest_click()
    r = pc.capture_point()
    if r is None:
        return {"canceled": True}
    return {"x": r[0], "y": r[1]}


@router.post("/capture/preview")
def capture_preview():
    """返回最近一次左键单击坐标(用于前端实时预览), 供遮罩期间轮询
    返回: {"x":..,"y":..} 或 {"none": true}"""
    from ..core import computer as pc
    r = pc.get_latest_click()
    if r is None:
        return {"none": True}
    return {"x": r[0], "y": r[1]}


@router.post("/batch-delete")
def batch_delete_points(payload: BatchDelete):
    """批量删除选中点位"""
    ids = payload.ids
    if not ids:
        raise HTTPException(400, "未选择点位")
    return {"ok": True, "deleted": points_repo.delete_many(ids)}


# ---------- 导入（CSV/XLSX） ----------
POINT_KEYS = {"点位id", "点位id", "id", "编号"}
NAME_KEYS = {"点位名称", "名称", "name", "点位名"}
X_KEYS = {"x", "坐标x", "x坐标", "横坐标"}
Y_KEYS = {"y", "坐标y", "y坐标", "纵坐标"}
REMARK_KEYS = {"备注", "remark", "说明"}


def _parse_points_file(filename, raw):
    """解析点位文件为 [{id,name,x,y,remark}, ...]；支持 csv/xlsx"""
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
    head = [str(c or "").strip().lower() for c in rows[0]]
    has_head = any(h in POINT_KEYS or h in NAME_KEYS or h in X_KEYS or h in Y_KEYS
                   for h in [str(c or "").strip() for c in rows[0]])
    data_rows = rows[1:] if has_head else rows
    result = []
    for r in data_rows:
        if not any(str(c or "").strip() for c in r):
            continue
        if has_head:
            d = {}
            for i, h in enumerate(rows[0]):
                v = r[i] if i < len(r) else ""
                hs = str(h or "").strip()
                if hs in POINT_KEYS:
                    d["id"] = v
                elif hs in NAME_KEYS:
                    d["name"] = v
                elif hs in X_KEYS:
                    d["x"] = v
                elif hs in Y_KEYS:
                    d["y"] = v
                elif hs in REMARK_KEYS:
                    d["remark"] = v
        else:
            d = {"id": r[0] if len(r) > 0 else "",
                 "name": r[1] if len(r) > 1 else "",
                 "x": r[2] if len(r) > 2 else "",
                 "y": r[3] if len(r) > 3 else "",
                 "remark": r[4] if len(r) > 4 else ""}
        if (d.get("name") or d.get("x") or d.get("y") or d.get("remark") or d.get("id")):
            result.append(d)
    return result


@router.post("/import")
def import_points(file: UploadFile = File(...)):
    """上传点位表格文件, 解析并入点(同 id 存在则更新, 否则新增)"""
    raw = file.file.read() if hasattr(file, "file") else file.read()
    rows = _parse_points_file(file.filename or "", raw)
    if not rows:
        raise HTTPException(400, "文件为空或无法解析")
    added, updated = points_repo.import_upsert(rows)
    return {"ok": True, "added": added, "updated": updated, "total": len(rows)}
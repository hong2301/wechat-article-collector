# -*- coding: utf-8 -*-
"""点位(points) CRUD 路由"""
import io
import csv
import sqlite3
from typing import List
from fastapi import APIRouter, HTTPException, UploadFile, File
from pydantic import BaseModel

from ..database import get_conn
from ..models import Point, PointCreate, PointUpdate

router = APIRouter(prefix="/api/points", tags=["points"])


def _row_to_dict(row):
    return dict(row)


@router.get("", response_model=list[Point])
def list_points():
    conn = get_conn()
    try:
        rows = conn.execute("SELECT * FROM points ORDER BY id ASC").fetchall()
        return [_row_to_dict(r) for r in rows]
    finally:
        conn.close()


@router.post("", response_model=Point, status_code=201)
def create_point(payload: PointCreate):
    conn = get_conn()
    try:
        cur = conn.execute(
            "INSERT INTO points(name, x, y, remark) VALUES(?,?,?,?)",
            (payload.name, payload.x, payload.y, payload.remark))
        new_id = cur.lastrowid
        conn.commit()
        row = conn.execute("SELECT * FROM points WHERE id=?", (new_id,)).fetchone()
        return dict(row)
    finally:
        conn.close()


@router.put("/{pid}", response_model=Point)
def update_point(pid: int, payload: PointUpdate):
    conn = get_conn()
    try:
        row = conn.execute("SELECT * FROM points WHERE id=?", (pid,)).fetchone()
        if not row:
            raise HTTPException(404, "点位不存在")
        fields = payload.model_dump(exclude_unset=True)
        if fields:
            sets = ", ".join(f"{k}=?" for k in fields)
            conn.execute(f"UPDATE points SET {sets} WHERE id=?", (*fields.values(), pid))
            conn.commit()
        row = conn.execute("SELECT * FROM points WHERE id=?", (pid,)).fetchone()
        return dict(row)
    finally:
        conn.close()


@router.delete("/{pid}", status_code=204)
def delete_point(pid: int):
    conn = get_conn()
    try:
        cur = conn.execute("DELETE FROM points WHERE id=?", (pid,))
        conn.commit()
        if cur.rowcount == 0:
            raise HTTPException(404, "点位不存在")
    finally:
        conn.close()


class BatchDelete(BaseModel):
    ids: List[int]


@router.post("/capture")
def capture_point():
    """阻塞采集屏幕坐标: 前端遮罩期间调用;
    左键单击记录(前端轮询preview)、双击确认、右键退出。
    返回: {"x":..,"y":..} 或 {"canceled": true}"""
    from ..services import computer as pc
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
    from ..services import computer as pc
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
    conn = get_conn()
    try:
        marks = ",".join("?" * len(ids))
        cur = conn.execute(f"DELETE FROM points WHERE id IN ({marks})", ids)
        conn.commit()
        return {"ok": True, "deleted": cur.rowcount}
    finally:
        conn.close()


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
    added = 0
    updated = 0
    conn = get_conn()
    try:
        for d in rows:
            name = str(d.get("name") or "").strip()
            x = str(d.get("x") or "").strip()
            y = str(d.get("y") or "").strip()
            remark = str(d.get("remark") or "").strip()
            pid = d.get("id")
            # 优先按 id 更新/新增; id 缺失则按名称匹配
            if pid is not None and str(pid).strip().isdigit():
                exists = conn.execute("SELECT id FROM points WHERE id=?", (int(pid),)).fetchone()
                if exists:
                    conn.execute("UPDATE points SET name=?, x=?, y=?, remark=? WHERE id=?",
                                 (name, x, y, remark, int(pid)))
                    updated += 1
                else:
                    conn.execute("INSERT INTO points(name, x, y, remark) VALUES(?,?,?,?)",
                                 (name, x, y, remark))
                    added += 1
            elif name:
                exists = conn.execute("SELECT id FROM points WHERE name=?", (name,)).fetchone()
                if exists:
                    conn.execute("UPDATE points SET x=?, y=?, remark=? WHERE id=?", (x, y, remark, exists["id"]))
                    updated += 1
                else:
                    conn.execute("INSERT INTO points(name, x, y, remark) VALUES(?,?,?,?)",
                                 (name, x, y, remark))
                    added += 1
        conn.commit()
        return {"ok": True, "added": added, "updated": updated, "total": len(rows)}
    finally:
        conn.close()
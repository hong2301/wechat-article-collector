# -*- coding: utf-8 -*-
"""滚动(scrolls) CRUD 路由 + 执行滚动"""
import io
import csv
import sqlite3
from typing import List
from fastapi import APIRouter, HTTPException, UploadFile, File
from pydantic import BaseModel

from ..database import get_conn
from ..models import Scroll, ScrollCreate, ScrollUpdate

router = APIRouter(prefix="/api/scrolls", tags=["scrolls"])


def _row_to_dict(row):
    return dict(row)


@router.get("", response_model=list[Scroll])
def list_scrolls():
    conn = get_conn()
    try:
        rows = conn.execute("SELECT * FROM scrolls ORDER BY id ASC").fetchall()
        return [_row_to_dict(r) for r in rows]
    finally:
        conn.close()


@router.post("", response_model=Scroll, status_code=201)
def create_scroll(payload: ScrollCreate):
    conn = get_conn()
    try:
        cur = conn.execute(
            "INSERT INTO scrolls(name, distance, point_id, direction, remark) VALUES(?,?,?,?,?)",
            (payload.name, payload.distance, payload.point_id,
             payload.direction, payload.remark))
        new_id = cur.lastrowid
        conn.commit()
        row = conn.execute("SELECT * FROM scrolls WHERE id=?", (new_id,)).fetchone()
        return dict(row)
    finally:
        conn.close()


@router.put("/{sid}", response_model=Scroll)
def update_scroll(sid: int, payload: ScrollUpdate):
    conn = get_conn()
    try:
        row = conn.execute("SELECT * FROM scrolls WHERE id=?", (sid,)).fetchone()
        if not row:
            raise HTTPException(404, "滚动配置不存在")
        fields = payload.model_dump(exclude_unset=True)
        if fields:
            sets = ", ".join(f"{k}=?" for k in fields)
            conn.execute(f"UPDATE scrolls SET {sets} WHERE id=?", (*fields.values(), sid))
            conn.commit()
        row = conn.execute("SELECT * FROM scrolls WHERE id=?", (sid,)).fetchone()
        return dict(row)
    finally:
        conn.close()


@router.delete("/{sid}", status_code=204)
def delete_scroll(sid: int):
    conn = get_conn()
    try:
        cur = conn.execute("DELETE FROM scrolls WHERE id=?", (sid,))
        conn.commit()
        if cur.rowcount == 0:
            raise HTTPException(404, "滚动配置不存在")
    finally:
        conn.close()


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
    added = 0
    updated = 0
    conn = get_conn()
    try:
        for d in rows:
            name = str(d.get("name") or "").strip()
            distance = str(d.get("distance") or "").strip()
            direction = str(d.get("direction") or "").strip() or "down"
            if direction not in ("up", "down"):
                direction = "down"
            remark = str(d.get("remark") or "").strip()
            pid_raw = str(d.get("point_id") or "")
            point_id = 0
            if pid_raw.isdigit():
                point_id = int(pid_raw)
            sid = d.get("id")
            if sid is not None and str(sid).strip().isdigit():
                exists = conn.execute("SELECT id FROM scrolls WHERE id=?", (int(sid),)).fetchone()
                if exists:
                    conn.execute("UPDATE scrolls SET name=?, distance=?, point_id=?, direction=?, remark=? WHERE id=?",
                                 (name, distance, point_id, direction, remark, int(sid)))
                    updated += 1
                else:
                    conn.execute("INSERT INTO scrolls(name, distance, point_id, direction, remark) VALUES(?,?,?,?,?)",
                                 (name, distance, point_id, direction, remark))
                    added += 1
            elif name:
                exists = conn.execute("SELECT id FROM scrolls WHERE name=?", (name,)).fetchone()
                if exists:
                    conn.execute("UPDATE scrolls SET distance=?, point_id=?, direction=?, remark=? WHERE id=?",
                                 (distance, point_id, direction, remark, exists["id"]))
                    updated += 1
                else:
                    conn.execute("INSERT INTO scrolls(name, distance, point_id, direction, remark) VALUES(?,?,?,?,?)",
                                 (name, distance, point_id, direction, remark))
                    added += 1
        conn.commit()
        return {"ok": True, "added": added, "updated": updated, "total": len(rows)}
    finally:
        conn.close()


@router.post("/{sid}/run")
def run_scroll(sid: int):
    """执行滚动: 把鼠标移到滚动点位所在坐标, 按配置方向/距离滚动"""
    from ..services import computer as pc
    conn = get_conn()
    try:
        row = conn.execute("SELECT * FROM scrolls WHERE id=?", (sid,)).fetchone()
        if not row:
            raise HTTPException(404, "滚动配置不存在")
        s = dict(row)
        # 取滚动点位坐标
        pt = conn.execute("SELECT x, y FROM points WHERE id=?", (s.get("point_id") or 0,)).fetchone()
    finally:
        conn.close()
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
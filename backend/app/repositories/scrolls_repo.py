# -*- coding: utf-8 -*-
"""滚动(scrolls) 数据访问层"""
from ..database import get_conn


def list_all():
    conn = get_conn()
    try:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM scrolls ORDER BY id ASC").fetchall()]
    finally:
        conn.close()


def get(sid: int):
    conn = get_conn()
    try:
        r = conn.execute("SELECT * FROM scrolls WHERE id=?", (sid,)).fetchone()
        return dict(r) if r else None
    finally:
        conn.close()


def get_point_xy(point_id: int):
    """读点位坐标(x,y); 不存在返回 None"""
    conn = get_conn()
    try:
        return conn.execute("SELECT x, y FROM points WHERE id=?", (point_id,)).fetchone()
    finally:
        conn.close()


def create(name, distance, point_id, direction, remark):
    conn = get_conn()
    try:
        cur = conn.execute(
            "INSERT INTO scrolls(name, distance, point_id, direction, remark) VALUES(?,?,?,?,?)",
            (name, distance, point_id, direction, remark))
        conn.commit()
        row = conn.execute("SELECT * FROM scrolls WHERE id=?", (cur.lastrowid,)).fetchone()
        return dict(row)
    finally:
        conn.close()


def update(sid: int, fields: dict):
    conn = get_conn()
    try:
        if fields:
            sets = ", ".join(f"{k}=?" for k in fields)
            conn.execute(f"UPDATE scrolls SET {sets} WHERE id=?", (*fields.values(), sid))
            conn.commit()
        row = conn.execute("SELECT * FROM scrolls WHERE id=?", (sid,)).fetchone()
        return dict(row)
    finally:
        conn.close()


def delete(sid: int) -> bool:
    conn = get_conn()
    try:
        cur = conn.execute("DELETE FROM scrolls WHERE id=?", (sid,))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def set_distance(sid: int, distance) -> None:
    conn = get_conn()
    try:
        conn.execute("UPDATE scrolls SET distance=? WHERE id=?", (distance, sid))
        conn.commit()
    finally:
        conn.close()


def import_upsert(rows: list) -> tuple:
    """导入行集入点(同 id/同名称更新, 否则新增); 行内 direction/point_id 已在此规范化
    返回 (added, updated)"""
    conn = get_conn()
    added = updated = 0
    try:
        for d in rows:
            name = str(d.get("name") or "").strip()
            distance = str(d.get("distance") or "").strip()
            direction = str(d.get("direction") or "").strip() or "down"
            if direction not in ("up", "down"):
                direction = "down"
            remark = str(d.get("remark") or "").strip()
            pid_raw = str(d.get("point_id") or "")
            point_id = int(pid_raw) if pid_raw.isdigit() else 0
            sid = d.get("id")
            if sid is not None and str(sid).strip().isdigit():
                exists = conn.execute("SELECT id FROM scrolls WHERE id=?", (int(sid),)).fetchone()
                if exists:
                    conn.execute(
                        "UPDATE scrolls SET name=?, distance=?, point_id=?, direction=?, remark=? WHERE id=?",
                        (name, distance, point_id, direction, remark, int(sid)))
                    updated += 1
                else:
                    conn.execute(
                        "INSERT INTO scrolls(name, distance, point_id, direction, remark) VALUES(?,?,?,?,?)",
                        (name, distance, point_id, direction, remark))
                    added += 1
            elif name:
                exists = conn.execute("SELECT id FROM scrolls WHERE name=?", (name,)).fetchone()
                if exists:
                    conn.execute(
                        "UPDATE scrolls SET distance=?, point_id=?, direction=?, remark=? WHERE id=?",
                        (distance, point_id, direction, remark, exists["id"]))
                    updated += 1
                else:
                    conn.execute(
                        "INSERT INTO scrolls(name, distance, point_id, direction, remark) VALUES(?,?,?,?,?)",
                        (name, distance, point_id, direction, remark))
                    added += 1
        conn.commit()
        return added, updated
    finally:
        conn.close()
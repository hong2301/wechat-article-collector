# -*- coding: utf-8 -*-
"""点位(points) 数据访问层: 所有 points 相关 SQL 集中于此, 路由只调函数"""
from ..database import get_conn


def list_with_sort():
    """全部点位: 走 sort_config(type='point' 的 sort_order), 未配置按 id 补位末尾"""
    conn = get_conn()
    try:
        return [dict(r) for r in conn.execute("""
            SELECT p.*, COALESCE(s.sort_order, 999999999) so
            FROM points p LEFT JOIN sort_config s ON p.id = s.record_id AND s.type='point'
            ORDER BY so ASC, p.id ASC""").fetchall()]
    finally:
        conn.close()


def get(pid: int):
    """按 id 读单个点位; 不存在返回 None"""
    conn = get_conn()
    try:
        r = conn.execute("SELECT * FROM points WHERE id=?", (pid,)).fetchone()
        return dict(r) if r else None
    finally:
        conn.close()


def get_xy(pid: int):
    """读点位坐标行(x,y); 不存在返回 None"""
    conn = get_conn()
    try:
        return conn.execute("SELECT x, y FROM points WHERE id=?", (pid,)).fetchone()
    finally:
        conn.close()


def set_coords(pid: int, x, y, remark: str = ""):
    """写回点位坐标(自动设置识别结果); 99999 为待定标记时保留原值"""
    conn = get_conn()
    try:
        if x != 99999:
            conn.execute("UPDATE points SET x=?, y=?, remark=? WHERE id=?", (x, y, remark, pid))
        else:
            conn.execute("UPDATE points SET remark=? WHERE id=?", (remark, pid))
        conn.commit()
    finally:
        conn.close()


def create(name: str, x, y, remark: str):
    """新增点位, 返回新行 dict"""
    conn = get_conn()
    try:
        cur = conn.execute(
            "INSERT INTO points(name, x, y, remark) VALUES(?,?,?,?)",
            (name, x, y, remark))
        conn.commit()
        row = conn.execute("SELECT * FROM points WHERE id=?", (cur.lastrowid,)).fetchone()
        return dict(row)
    finally:
        conn.close()


def update(pid: int, fields: dict):
    """按给定字段集更新点位(只更新传入键), 返回更新后行 dict"""
    conn = get_conn()
    try:
        if fields:
            sets = ", ".join(f"{k}=?" for k in fields)
            conn.execute(f"UPDATE points SET {sets} WHERE id=?", (*fields.values(), pid))
            conn.commit()
        row = conn.execute("SELECT * FROM points WHERE id=?", (pid,)).fetchone()
        return dict(row)
    finally:
        conn.close()


def delete(pid: int) -> bool:
    """删除点位; 返回是否真的删到了"""
    conn = get_conn()
    try:
        cur = conn.execute("DELETE FROM points WHERE id=?", (pid,))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def delete_many(ids: list) -> int:
    """批量删除; 返回删除条数"""
    conn = get_conn()
    try:
        marks = ",".join("?" * len(ids))
        cur = conn.execute(f"DELETE FROM points WHERE id IN ({marks})", ids)
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()


def import_upsert(rows: list) -> tuple:
    """按导入行集入点(同 id/同名称更新, 否则新增)
    rows: [{'id','name','x','y','remark'}, ...]
    返回 (added, updated)"""
    conn = get_conn()
    added = updated = 0
    try:
        for d in rows:
            name = str(d.get("name") or "").strip()
            x = str(d.get("x") or "").strip()
            y = str(d.get("y") or "").strip()
            remark = str(d.get("remark") or "").strip()
            pid = d.get("id")
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
                    conn.execute("UPDATE points SET x=?, y=?, remark=? WHERE id=?",
                                 (x, y, remark, exists["id"]))
                    updated += 1
                else:
                    conn.execute("INSERT INTO points(name, x, y, remark) VALUES(?,?,?,?)",
                                 (name, x, y, remark))
                    added += 1
        conn.commit()
        return added, updated
    finally:
        conn.close()
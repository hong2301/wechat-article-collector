# -*- coding: utf-8 -*-
"""公众号(accounts) CRUD 路由"""
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from ..database import get_conn
from ..models import Account, AccountCreate, AccountUpdate
from fastapi import UploadFile, File, Form
from ..services.importer import parse_file
from ..services.resolve import resolve_account

router = APIRouter(prefix="/api/accounts", tags=["accounts"])


def _row_to_dict(row):
    return dict(row)


@router.get("", response_model=list[Account])
def list_accounts():
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT a.* FROM accounts a "
            "LEFT JOIN sort_config s ON a.id = s.record_id "
            "ORDER BY COALESCE(s.sort_order, 999999999), a.id ASC").fetchall()
        # 附文章采集统计
        from ..services.stats import get_account_collect
        result = []
        for r in rows:
            d = _row_to_dict(r)
            st = get_account_collect(biz=d.get("biz") or "", name=d.get("name") or "")
            d["collected_count"] = st["count"]
            result.append(d)
        return result
    finally:
        conn.close()




def _import_stream(rows):
    """解析后的行 -> 逐条入库, 生成器逐条 yield 进度用于 SSE
    each: {"done": 处理数, "total": 总数, "name": 名称, "ok": 是否成功}"""
    total = len(rows)
    done = 0
    for item in rows:
        name = (item.get("name") or "").strip()
        biz = (item.get("biz") or "").strip()
        link = (item.get("link") or "").strip()
        need_full = (not name or not biz) and link   # 需要补全
        full_ok = True
        if need_full:
            r = resolve_account(link)
            if r:
                if not name and r.get("name"):
                    name = r["name"]
                if not biz and r.get("biz"):
                    biz = r["biz"]
                full_ok = True
            else:
                full_ok = False   # 需要补全但识别失败
        ok = True
        if not name:
            ok = False
        elif need_full and not full_ok:
            ok = False   # 需要补全但补全失败 -> 判定失败
        else:
            conn = get_conn()
            try:
                # 导入分配到末尾(最大id+1), 保持文件顺序
                conn.execute(
                    "INSERT INTO accounts(name, biz, status, remark) VALUES(?,?,?,?)",
                    (name, biz, "pending", ""))
                conn.commit()
            except Exception:
                ok = False
            finally:
                conn.close()
        done += 1
        yield {"done": done, "total": total, "name": name, "ok": ok}


def _import_sse(rows):
    """SSE 生成器: 逐条 yield 导入进度"""
    import json as _json
    total = len(rows)
    yield 'event: start' + chr(10) + 'data: ' + _json.dumps({'total': total}) + chr(10) + chr(10)
    for evt in _import_stream(rows):
        yield 'event: progress' + chr(10) + 'data: ' + _json.dumps(evt) + chr(10) + chr(10)
    yield 'event: done' + chr(10) + 'data: {}' + chr(10) + chr(10)

@router.post("/import")
def import_accounts(file: UploadFile = File(...)):
    """上传表格文件, 解析+识别, 流式返回导入进度(SSE)"""
    raw = file.file.read() if hasattr(file, "file") else file.read()
    rows = parse_file(file.filename or "", raw) or []
    return StreamingResponse(_import_sse(rows), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache"})

@router.post("", response_model=Account, status_code=201)
def create_account(payload: AccountCreate):
    conn = get_conn()
    try:
        cur = conn.execute(
            "INSERT INTO accounts(name, biz, status, remark) VALUES(?,?,?,?)",
            (payload.name, payload.biz, payload.status, payload.remark))
        new_id = cur.lastrowid
        conn.commit()
        row = conn.execute(
            "SELECT a.* FROM accounts a WHERE a.id=?", (new_id,)).fetchone()
        return dict(row)
    finally:
        conn.close()


@router.put("/{aid}", response_model=Account)
def update_account(aid: int, payload: AccountUpdate):
    conn = get_conn()
    try:
        row = conn.execute("SELECT * FROM accounts WHERE id=?", (aid,)).fetchone()
        if not row:
            raise HTTPException(404, "账号不存在")
        fields = payload.model_dump(exclude_unset=True)
        if fields:
            sets = ", ".join(f"{k}=?" for k in fields)
            conn.execute(f"UPDATE accounts SET {sets} WHERE id=?",
                         (*fields.values(), aid))
            conn.commit()
        row = conn.execute("SELECT * FROM accounts WHERE id=?", (aid,)).fetchone()
        return dict(row)
    finally:
        conn.close()




from typing import List
from pydantic import BaseModel

class SortPayload(BaseModel):
    ids: List[int]


@router.get("/calendar/{aid}")
def account_calendar(aid: int, year: int = None, month: int = None):
    """单个公众号的采集日历; 指定年/月返回该月每日数量, 否则返回全部daily"""
    import calendar as _cal
    from ..services.stats import get_account_collect
    conn = get_conn()
    try:
        r = conn.execute("SELECT name, biz FROM accounts WHERE id=?", (aid,)).fetchone()
    finally:
        conn.close()
    if not r:
        raise HTTPException(404, "账号不存在")
    st = get_account_collect(biz=r["biz"] or "", name=r["name"] or "")
    daily = st["daily"]
    if year is not None and month is not None:
        # 该月每日(含0)
        _, ndays = _cal.monthrange(year, month)
        m = {f"{year}-{month:02d}-{d:02d}": daily.get(f"{year}-{month:02d}-{d:02d}", 0) for d in range(1, ndays + 1)}
        daily = m
    return {"id": aid, "name": r["name"], "count": st["count"], "daily": daily}

@router.put("/sort")
def sort_accounts(payload: SortPayload):
    """按拖拽后的 id 顺序重写 sort_config, 持久化排序"""
    conn = get_conn()
    try:
        # 先删掉这些 id 的旧排序, 再按顺序写入
        marks = ",".join("?" * len(payload.ids))
        if payload.ids:
            conn.execute(f"DELETE FROM sort_config WHERE record_id IN ({marks})", payload.ids)
            conn.executemany(
                "INSERT OR REPLACE INTO sort_config(record_id, sort_order) VALUES(?,?)",
                [(rid, i + 1) for i, rid in enumerate(payload.ids)])
        conn.commit()
        return {"ok": True, "count": len(payload.ids)}
    finally:
        conn.close()

@router.delete("/clear", status_code=200)
def clear_accounts():
    """清空所有公众号"""
    conn = get_conn()
    try:
        conn.execute("DELETE FROM accounts")
        conn.commit()
        return {"deleted": conn.total_changes}
    finally:
        conn.close()


@router.delete("/{aid}", status_code=204)
def delete_account(aid: int):
    conn = get_conn()
    try:
        cur = conn.execute("DELETE FROM accounts WHERE id=?", (aid,))
        conn.execute("DELETE FROM sort_config WHERE record_id=?", (aid,))
        conn.commit()
        if cur.rowcount == 0:
            raise HTTPException(404, "账号不存在")
    finally:
        conn.close()

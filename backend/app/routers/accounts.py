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
        rows = conn.execute("SELECT * FROM accounts ORDER BY id DESC").fetchall()
        return [_row_to_dict(r) for r in rows]
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
        # 缺名称 或 缺biz 且有链接 -> 用文章链接补全(名称+biz)
        if (not name or not biz) and link:
            r = resolve_account(link)
            if r:
                if not name and r.get("name"):
                    name = r["name"]
                if not biz and r.get("biz"):
                    biz = r["biz"]
        ok = True
        if not name:
            ok = False
        else:
            conn = get_conn()
            try:
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
        conn.commit()
        row = conn.execute("SELECT * FROM accounts WHERE id=?", (cur.lastrowid,)).fetchone()
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
        conn.commit()
        if cur.rowcount == 0:
            raise HTTPException(404, "账号不存在")
    finally:
        conn.close()

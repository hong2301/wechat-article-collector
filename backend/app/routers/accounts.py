# -*- coding: utf-8 -*-
"""公众号(accounts) CRUD 路由"""
import sqlite3
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from ..database import get_conn
from ..models import Account, AccountCreate, AccountUpdate
from fastapi import UploadFile, File, Form
from ..services.importer import parse_file, extract_art_biz
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
        # 附文章采集统计: 实时统计 articles 表每 biz 的文章数(增删即时反映)
        cnt = dict(conn.execute("SELECT biz, COUNT(*) n FROM articles GROUP BY biz").fetchall())
        result = []
        for r in rows:
            d = _row_to_dict(r)
            d["collected_count"] = cnt.get(d.get("biz") or "", 0)
            result.append(d)
        return result
    finally:
        conn.close()




def _import_stream(rows):
    """解析后的行 -> 逐条入库, 生成器逐条 yield 进度用于 SSE
    each: {"done": 处理数, "total": 总数, "name": 名称, "ok": 是否成功}"""
    total = len(rows)
    done = 0
    # 新增(导入)排最前: 从当前最前 order 往前递减分配
    conn0 = get_conn()
    try:
        m = conn0.execute("SELECT MIN(sort_order) m FROM sort_config").fetchone()["m"]
    finally:
        conn0.close()
    new_order = (m if m is not None else 0) - 1
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
                cur = conn.execute(
                    "INSERT INTO accounts(name, biz, status, remark) VALUES(?,?,?,?)",
                    (name, biz, "pending", ""))
                new_id = cur.lastrowid
                conn.execute("INSERT OR REPLACE INTO sort_config(record_id, sort_order) VALUES(?,?)", (new_id, new_order))
                new_order -= 1   # 下一条再往前一位
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
        # 新增排最前
        m = conn.execute("SELECT MIN(sort_order) m FROM sort_config").fetchone()["m"]
        new_order = (m if m is not None else 0) - 1
        conn.execute("INSERT OR REPLACE INTO sort_config(record_id, sort_order) VALUES(?,?)", (new_id, new_order))
        conn.commit()
        row = conn.execute(
            "SELECT a.* FROM accounts a WHERE a.id=?", (new_id,)).fetchone()
        return dict(row)
    except sqlite3.IntegrityError:
        raise HTTPException(400, "biz 代码已存在，不能重复添加")
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
        if "biz" in fields and fields["biz"]:
            dup = conn.execute("SELECT id FROM accounts WHERE biz=? AND id<>?", (fields["biz"], aid)).fetchone()
            if dup:
                raise HTTPException(400, "biz 代码已存在，不能重复")
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



@router.get("/articles-by-biz")
def account_articles_by_biz(biz: str = ""):
    """biz=该公众号返其文章; biz=all或空 返回全部文章(含公众号名)"""
    conn = get_conn()
    try:
        acc = conn.execute("SELECT id, name FROM accounts WHERE biz=?", (biz,)).fetchone() if biz and biz != "all" else None
        if biz and biz != "all":
            rows = conn.execute("SELECT * FROM articles WHERE biz=? ORDER BY date DESC, id DESC", (biz,)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM articles ORDER BY date DESC, id DESC").fetchall()
    finally:
        conn.close()
    name = dict(acc)["name"] if acc else ("全部文章" if (not biz or biz == "all") else "")
    arts = [{"id": d["id"], "title": d["title"], "date": d["date"], "art_biz": d["art_biz"],
             "reads": d["reads"], "likes": d["likes"], "forwards": d["forwards"],
             "favorites": d["favorites"], "comments": d["comments"], "write_time": d["write_time"],
             "original": d["original"], "ip": d["ip"], "acc_name": d["name"] or ""} for d in rows]
    return {"biz": biz, "name": name, "articles": arts}


@router.get("/comments")
def article_comments(art_biz: str = ""):
    """按文章id(art_biz)返回评论列表"""
    if not art_biz:
        raise HTTPException(400, "缺少 art_biz")
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM comments WHERE art_biz=? ORDER BY is_top DESC, time DESC, id ASC",
            (art_biz,)).fetchall()
    finally:
        conn.close()
    arts = [{
        "id": d["id"], "comment_biz": d["comment_biz"], "parent_comment_biz": d["parent_comment_biz"],
        "author": d["author"], "content": d["content"], "time": d["time"], "likes": d["likes"], "ip": d["ip"],
        "is_author": d["is_author"], "is_top": d["is_top"], "is_author_reply": d["is_author_reply"],
        "is_author_like": d["is_author_like"], "is_first": d["is_first"], "level": d["level"],
    } for d in rows]
    return {"art_biz": art_biz, "comments": arts}


@router.delete("/articles-by-biz/{artid}", status_code=204)
def delete_article_by_biz(artid: int, biz: str = ""):
    """删除文章; biz=all/空 按id直接删, 否则限定公众号"""
    conn = get_conn()
    try:
        if biz and biz != "all":
            cur = conn.execute("DELETE FROM articles WHERE id=? AND biz=?", (artid, biz))
        else:
            cur = conn.execute("DELETE FROM articles WHERE id=?", (artid,))
        conn.commit()
        if cur.rowcount == 0:
            raise HTTPException(404, "文章不存在")
    finally:
        conn.close()


class ArticleSave(BaseModel):
    biz: str
    art_biz: str
    title: str = ""
    date: str = ""
    reads: str = ""
    likes: str = ""
    forwards: str = ""
    favorites: str = ""
    comments: str = ""
    original: str = ""
    ip: str = ""


@router.put("/articles-by-biz/save")
def save_article(payload: ArticleSave):
    """用导入文件的数据覆盖/补充某biz+link的已有记录(仅更新文件里非空字段)"""
    p = payload.model_dump()
    art = (p.get("art_biz") or "").strip()
    if not art:
        raise HTTPException(400, "缺少文章id")
    sets = []
    vals = []
    for f in ("title", "date", "reads", "likes", "forwards", "favorites", "comments", "original", "ip"):
        v = (p.get(f) or "").strip()
        if v:
            sets.append(f"{f}=?")
            vals.append(v)
    if not sets:
        return {"ok": True, "updated": 0}
    sets.append("name=(SELECT name FROM accounts WHERE biz=?)")
    vals.append(p["biz"])
    vals.extend([p["biz"], art])
    conn = get_conn()
    try:
        cur = conn.execute(f"UPDATE articles SET {', '.join(sets)} WHERE biz=? AND art_biz=?", vals)
        conn.commit()
        return {"ok": True, "updated": cur.rowcount}
    finally:
        conn.close()


class ArticleCreate(BaseModel):
    biz: str
    link: str
    title: str = ""


@router.post("/articles-by-biz", status_code=201)
def create_article(payload: ArticleCreate):
    """按 biz 新增一篇文章; 输入链接, 存文章id(art_biz)"""
    link = payload.link.strip()
    if not link:
        raise HTTPException(400, "文章链接不能为空")
    art = extract_art_biz(link)
    title = payload.title.strip() or art
    conn = get_conn()
    try:
        acc = conn.execute("SELECT id, name FROM accounts WHERE biz=?", (payload.biz,)).fetchone()
        name = dict(acc)["name"] if acc else ""
        account_id = acc["id"] if acc else None
        cur = conn.execute(
            "INSERT INTO articles (account_id, name, date, title, art_biz, biz) VALUES (?,?,?,?,?,?)",
            (account_id, name, "", title, art, payload.biz),
        )
        conn.commit()
        return {"id": cur.lastrowid, "title": title, "art_biz": art, "biz": payload.biz}
    except sqlite3.IntegrityError:
        raise HTTPException(400, "该文章已存在，不能重复添加")
    finally:
        conn.close()


def _article_import_sse(rows, default_biz):
    """逐行全字段入库, SSE 流式进度"""
    import json as _json
    total = len(rows)
    yield 'event: start' + chr(10) + 'data: ' + _json.dumps({'total': total}) + chr(10) + chr(10)
    done = 0
    skipped = 0
    dups_data = []
    for item in rows:
        ok = True
        is_dup = False
        row_biz = default_biz   # 归属当前页 biz, 忽略表格biz列
        art = extract_art_biz(item.get("link") or "")
        title = (item.get("title") or "").strip() or art
        date = (item.get("date") or "").strip()
        conn = get_conn()
        try:
            acc = conn.execute("SELECT id, name FROM accounts WHERE biz=?", (row_biz,)).fetchone()
            acc_name = dict(acc)["name"] if acc else ""
            account_id = dict(acc)["id"] if acc else None
            ex = conn.execute("SELECT COUNT(*) c FROM articles WHERE biz=? AND art_biz=?", (row_biz, art)).fetchone()
            if ex["c"]:
                ok, is_dup, skipped = False, True, skipped + 1
                dups_data.append({**item, "biz": row_biz, "art_biz": art})
            else:
                conn.execute(
                    "INSERT INTO articles(account_id, name, date, title, art_biz, biz, reads, likes, forwards, favorites, comments, original, ip) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (account_id, acc_name, date, title, art, row_biz,
                     item.get("reads"), item.get("likes"), item.get("forwards"),
                     item.get("favorites"), item.get("comments"), item.get("original"), item.get("ip")))
                conn.commit()
        except Exception:
            ok = False   # 真正失败(入库异常)
        finally:
            conn.close()
        done += 1
        yield 'event: progress' + chr(10) + 'data: ' + _json.dumps({'done': done, 'total': total, 'name': title, 'ok': ok, 'dup': is_dup}) + chr(10) + chr(10)
    yield 'event: done' + chr(10) + 'data: ' + _json.dumps({'skipped': skipped, 'dups': dups_data}) + chr(10) + chr(10)


@router.post("/articles-by-biz/import")
def import_articles(biz: str = "", file: UploadFile = File(...)):
    """上传表格文件, 提取文章链接, 按 biz 批量入库(SSE)"""
    if not biz:
        raise HTTPException(400, "缺少 biz")
    raw = file.file.read() if hasattr(file, "file") else file.read()
    from ..services.importer import parse_article_rows
    try:
        rows = parse_article_rows(file.filename or "", raw)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return StreamingResponse(_article_import_sse(rows, biz), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache"})


def _comment_import_sse(rows, art_biz):
    """逐行入库评论, SSE 进度"""
    import json as _json
    total = len(rows)
    yield 'event: start' + chr(10) + 'data: ' + _json.dumps({'total': total}) + chr(10) + chr(10)
    done = 0
    dup = 0
    for item in rows:
        ok = True
        is_dup = False
        conn = get_conn()
        try:
            cb = (item.get("comment_biz") or "").strip()
            if cb:
                ex = conn.execute("SELECT COUNT(*) c FROM comments WHERE art_biz=? AND comment_biz=?", (art_biz, cb)).fetchone()
                if ex["c"]:
                    ok, is_dup, dup = False, True, dup + 1
            if ok:
                conn.execute(
                    "INSERT INTO comments(comment_biz, parent_comment_biz, art_biz, author, content, time, likes, ip, "
                    "is_author, is_top, is_first, is_author_reply, is_author_like, level) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (item.get("comment_biz"), item.get("parent_comment_biz"), art_biz, item.get("author"), item.get("content"),
                     item.get("time"), item.get("likes"), item.get("ip"), item.get("is_author"), item.get("is_top"),
                     item.get("is_first"), item.get("is_author_reply"), item.get("is_author_like"), item.get("level")))
                conn.commit()
        except Exception:
            ok = False
        finally:
            conn.close()
        done += 1
        yield 'event: progress' + chr(10) + 'data: ' + _json.dumps({'done': done, 'total': total, 'name': item.get("author") or "", 'ok': ok, 'dup': is_dup}) + chr(10) + chr(10)
    yield 'event: done' + chr(10) + 'data: ' + _json.dumps({'dup': dup}) + chr(10) + chr(10)


@router.post("/comments/import")
def import_comments(art_biz: str = "", file: UploadFile = File(...)):
    """上传表格, 识别评论各列入库(SSE)"""
    if not art_biz:
        raise HTTPException(400, "缺少 art_biz")
    raw = file.file.read() if hasattr(file, "file") else file.read()
    from ..services.importer import parse_comment_rows
    try:
        rows = parse_comment_rows(file.filename or "", raw)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return StreamingResponse(_comment_import_sse(rows, art_biz), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache"})


@router.delete("/comments")
def delete_comments(ids: str = "", art_biz: str = ""):
    """按 id 批量删除评论(可选限定art_biz)"""
    id_list = [int(x) for x in (ids or "").split(",") if x.strip().isdigit()]
    if not id_list:
        raise HTTPException(400, "缺少评论id")
    conn = get_conn()
    try:
        marks = ",".join("?" * len(id_list))
        if art_biz:
            cur = conn.execute(f"DELETE FROM comments WHERE art_biz=? AND id IN ({marks})", (art_biz, *id_list))
        else:
            cur = conn.execute(f"DELETE FROM comments WHERE id IN ({marks})", id_list)
        conn.commit()
        return {"ok": True, "deleted": cur.rowcount}
    finally:
        conn.close()


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


@router.get("/{aid}/articles")
def account_articles(aid: int):
    """该公众号的文章列表(从 SQLite articles 表)"""
    conn = get_conn()
    try:
        r = conn.execute("SELECT name, biz FROM accounts WHERE id=?", (aid,)).fetchone()
        if not r:
            raise HTTPException(404, "账号不存在")
        # 按 biz 关联文章(biz 为空时退化为 account_id)
        biz = r["biz"] or ""
        if biz:
            rows = conn.execute("SELECT * FROM articles WHERE biz=? ORDER BY date DESC, id DESC", (biz,)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM articles WHERE account_id=? ORDER BY date DESC, id DESC", (aid,)).fetchall()
    finally:
        conn.close()
    arts = []
    for row in rows:
        d = dict(row)
        arts.append({
            "id": d.get("id"), "title": d.get("title"), "date": d.get("date"),
            "art_biz": d.get("art_biz"), "reads": d.get("reads"), "likes": d.get("likes"),
            "original": d.get("original"), "ip": d.get("ip"),
        })
    return {"id": aid, "name": r["name"], "articles": arts}


@router.delete("/{aid}/articles/{artid}", status_code=204)
def delete_article(aid: int, artid: int):
    """删除某公众号下的一篇文章"""
    conn = get_conn()
    try:
        cur = conn.execute("DELETE FROM articles WHERE id=? AND account_id=?", (artid, aid))
        conn.commit()
        if cur.rowcount == 0:
            raise HTTPException(404, "文章不存在")
    finally:
        conn.close()


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

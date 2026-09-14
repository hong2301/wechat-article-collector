# -*- coding: utf-8 -*-
"""公众号/文章/评论/排序 数据访问层: 集中 accounts / articles / comments / sort_config 相关 SQL"""
from ..database import get_conn
from ..core import logkit

log = logkit.get_logger("repo.accounts")   # 数据层审计日志 -> run.log


# ============ 公众号 accounts ============
def list_accounts(q: str = "") -> list:
    """公众号列表(带 sort_config 排序); q 非空时按 name/biz LIKE 过滤"""
    conn = get_conn()
    try:
        sql = "SELECT a.* FROM accounts a " \
              "LEFT JOIN sort_config s ON a.id = s.record_id AND s.type='account' " \
              "ORDER BY COALESCE(s.sort_order, 999999999), a.id ASC"
        params = []
        if q:
            like = f"%{q.strip()}%"
            sql = f"SELECT * FROM ({sql}) t WHERE t.name LIKE ? OR t.biz LIKE ?"
            params = [like, like]
        return [dict(r) for r in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()


def get(aid: int):
    conn = get_conn()
    try:
        r = conn.execute("SELECT * FROM accounts WHERE id=?", (aid,)).fetchone()
        return dict(r) if r else None
    finally:
        conn.close()


def get_by_biz(biz: str):
    conn = get_conn()
    try:
        return conn.execute("SELECT * FROM accounts WHERE biz=?", (biz,)).fetchone()
    finally:
        conn.close()


def min_sort() -> int:  # type: ignore[return]
    """sort_config(type=account) 最小 sort_order; 无记录返回 None"""
    conn = get_conn()
    try:
        r = conn.execute("SELECT MIN(sort_order) m FROM sort_config WHERE type='account'").fetchone()
        return r["m"]
    finally:
        conn.close()


def create(name: str, biz: str, status: str, remark: str) -> dict:
    """新增公众号并置顶排序; 返回新行 dict"""
    conn = get_conn()
    try:
        cur = conn.execute(
            "INSERT INTO accounts(name, biz, status, remark) VALUES(?,?,?,?)",
            (name, biz, status, remark))
        new_id = cur.lastrowid
        m = conn.execute("SELECT MIN(sort_order) m FROM sort_config WHERE type='account'").fetchone()["m"]
        conn.execute("INSERT OR REPLACE INTO sort_config(record_id, sort_order, type) VALUES(?,?,?)",
                     (new_id, (m if m is not None else 0) - 1, 'account'))
        conn.commit()
        row = conn.execute("SELECT a.* FROM accounts a WHERE a.id=?", (new_id,)).fetchone()
        log.info("[repo] accounts.create id=%s name=%r", new_id, name)
        return dict(row)
    finally:
        conn.close()


def update(aid: int, fields: dict) -> dict:
    conn = get_conn()
    try:
        if fields:
            sets = ", ".join(f"{k}=?" for k in fields)
            conn.execute(f"UPDATE accounts SET {sets} WHERE id=?", (*fields.values(), aid))
            conn.commit()
        row = conn.execute("SELECT * FROM accounts WHERE id=?", (aid,)).fetchone()
        log.info("[repo] accounts.update id=%s fields=%s", aid, list(fields))
        return dict(row)
    finally:
        conn.close()


def get_dup_biz(biz: str, exclude_id: int):
    """查同 biz 其它记录(防重复); 无返回 None"""
    conn = get_conn()
    try:
        return conn.execute("SELECT id FROM accounts WHERE biz=? AND id<>?", (biz, exclude_id)).fetchone()
    finally:
        conn.close()


def delete(aid: int) -> bool:
    """删公众号 + 其排序记录 + 该公众号全部文章及其评论(级联)"""
    conn = get_conn()
    try:
        biz_row = conn.execute("SELECT biz FROM accounts WHERE id=?", (aid,)).fetchone()
        if biz_row and biz_row["biz"]:
            biz = biz_row["biz"]
            arts = conn.execute("SELECT art_biz FROM articles WHERE biz=?", (biz,)).fetchall()
            abizs = [r["art_biz"] for r in arts]
            conn.execute("DELETE FROM articles WHERE biz=?", (biz,))
            if abizs:
                marks = ",".join("?" * len(abizs))
                conn.execute(f"DELETE FROM comments WHERE art_biz IN ({marks})", abizs)
            log.info("[repo] accounts.delete 级联: 公众号biz=%.10s 删除文章%d篇 评论%d条(对应删除)",
                     biz, len(abizs), conn.total_changes)
        cur = conn.execute("DELETE FROM accounts WHERE id=?", (aid,))
        conn.execute("DELETE FROM sort_config WHERE record_id=?", (aid,))
        conn.commit()
        log.info("[repo] accounts.delete id=%s -> %s", aid, cur.rowcount > 0)
        return cur.rowcount > 0
    finally:
        conn.close()


def clear() -> int:
    conn = get_conn()
    try:
        conn.execute("DELETE FROM accounts")
        conn.commit()
        log.warning("[repo] accounts.clear 清空全部公众号(高危)")
        return conn.total_changes
    finally:
        conn.close()


def set_sort(ids: list) -> None:
    """按拖拽后的 id 顺序重写 sort_config(type=account)"""
    conn = get_conn()
    try:
        marks = ",".join("?" * len(ids))
        if ids:
            conn.execute(f"DELETE FROM sort_config WHERE record_id IN ({marks})", ids)
            conn.executemany(
                "INSERT OR REPLACE INTO sort_config(record_id, sort_order, type) VALUES(?,?,?)",
                [(rid, i + 1, 'account') for i, rid in enumerate(ids)])
        conn.commit()
        log.info("[repo] accounts.set_sort 按 %d 个 id 重写排序", len(ids))
    finally:
        conn.close()


# ============ 文章 articles ============
def articles_query(where: list, params: list, order_sql: str) -> list:
    """通用文章查询: where 为片段列表, order_sql 已白名单化"""
    sql = "SELECT * FROM articles"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY " + order_sql + ", id DESC"
    conn = get_conn()
    try:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()


def articles_count_by_biz() -> dict:
    """各公众号文章数 {biz: n}"""
    conn = get_conn()
    try:
        return dict(conn.execute("SELECT biz, COUNT(*) n FROM articles GROUP BY biz").fetchall())
    finally:
        conn.close()


def article_delete(artid: int, biz: str = "") -> bool:
    """删文章; biz 非空且非 all 时限定公众号"""
    conn = get_conn()
    try:
        if biz and biz != "all":
            cur = conn.execute("DELETE FROM articles WHERE id=? AND biz=?", (artid, biz))
        else:
            cur = conn.execute("DELETE FROM articles WHERE id=?", (artid,))
        conn.commit()
        log.info("[repo] articles.delete artid=%s biz=%r -> %s", artid, biz, cur.rowcount > 0)
        return cur.rowcount > 0
    finally:
        conn.close()


def article_update_by_biz_art(biz: str, art_biz: str, sets: list, vals: list) -> int:
    """覆盖/补充某 biz+art_biz 的文章字段; 返回更新数"""
    conn = get_conn()
    try:
        cur = conn.execute(f"UPDATE articles SET {', '.join(sets)} WHERE biz=? AND art_biz=?", vals)
        conn.commit()
        log.info("[repo] articles.update biz=%.10s art=%.16s 行=%d", biz, art_biz, cur.rowcount)
        return cur.rowcount
    finally:
        conn.close()


def article_get(art_biz: str, biz: str = "") -> dict | None:
    """按 art_biz 取文章行(查看文件时补 title/date/name)"""
    conn = get_conn()
    try:
        if biz:
            row = conn.execute("SELECT * FROM articles WHERE biz=? AND art_biz=?",
                               (biz, art_biz)).fetchone()
        else:
            row = conn.execute("SELECT * FROM articles WHERE art_biz=?", (art_biz,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def article_saved_formats(art_biz: str, biz: str = "") -> str:
    """读某文章已保存到本地的文件格式(逗号分隔; 找不到返回空串)"""
    conn = get_conn()
    try:
        if biz:
            row = conn.execute("SELECT saved_formats FROM articles WHERE biz=? AND art_biz=?",
                               (biz, art_biz)).fetchone()
        else:
            row = conn.execute("SELECT saved_formats FROM articles WHERE art_biz=?", (art_biz,)).fetchone()
        return (row[0] or "") if row else ""
    finally:
        conn.close()


def article_merge_saved_formats(art_biz: str, formats, biz: str = "") -> str:
    """合并写入某文章已保存文件格式(下载/扫描文件夹时更新); 返回写入后的值(逗号分隔)"""
    new = []
    for x in (formats or []):
        x = str(x).strip().lower()
        if x == "docx":
            x = "word"          # 统一 word
        if x and x not in new:
            new.append(x)
    conn = get_conn()
    try:
        if biz:
            row = conn.execute("SELECT saved_formats FROM articles WHERE biz=? AND art_biz=?",
                               (biz, art_biz)).fetchone()
        else:
            row = conn.execute("SELECT saved_formats FROM articles WHERE art_biz=?", (art_biz,)).fetchone()
        old = [x for x in ((row[0] or "").split(",") if row else []) if x]
        merged = old + [x for x in new if x not in old]
        val = ",".join(merged)
        if row:
            if biz:
                conn.execute("UPDATE articles SET saved_formats=? WHERE biz=? AND art_biz=?",
                             (val, biz, art_biz))
            else:
                conn.execute("UPDATE articles SET saved_formats=? WHERE art_biz=?", (val, art_biz))
            conn.commit()
            log.info("[repo] articles.saved_formats art=%.16s | %s -> %s", art_biz, ",".join(old), val)
        return val
    finally:
        conn.close()


def article_set_saved_formats(art_biz: str, formats, biz: str = "") -> str:
    """覆盖写入某文章已保存文件格式(以实际扫描为准, 文件删光=清空); 返回写入后的值"""
    new = []
    for x in (formats or []):
        x = str(x).strip().lower()
        if x == "docx":
            x = "word"
        if x and x not in new:
            new.append(x)
    val = ",".join(new)
    conn = get_conn()
    try:
        if biz:
            conn.execute("UPDATE articles SET saved_formats=? WHERE biz=? AND art_biz=?",
                         (val, biz, art_biz))
        else:
            conn.execute("UPDATE articles SET saved_formats=? WHERE art_biz=?", (val, art_biz))
        conn.commit()
        log.info("[repo] articles.saved_formats 覆盖 art=%.16s -> %r", art_biz, val)
        return val
    finally:
        conn.close()


def article_create(account_id, name, date, title, art_biz, biz) -> int:
    conn = get_conn()
    try:
        cur = conn.execute(
            "INSERT INTO articles (account_id, name, date, title, art_biz, biz) VALUES (?,?,?,?,?,?)",
            (account_id, name, date, title, art_biz, biz))
        conn.commit()
        log.info("[repo] articles.create id=%s art=%.16s", cur.lastrowid,
                 art_biz or "")
        return cur.lastrowid if cur.lastrowid else 0
    finally:
        conn.close()


def article_dup_count(biz: str, art_biz: str) -> int:
    conn = get_conn()
    try:
        return conn.execute("SELECT COUNT(*) c FROM articles WHERE biz=? AND art_biz=?",
                            (biz, art_biz)).fetchone()["c"]
    finally:
        conn.close()


def article_insert_full(fields: dict) -> None:
    """全字段插入文章(fields 含 account_id,name,date,title,art_biz,biz,reads,likes,forwards,favorites,comments,original,ip)"""
    ks = list(fields.keys())
    conn = get_conn()
    try:
        conn.execute(
            f"INSERT INTO articles({','.join(ks)}) VALUES({','.join(['?'] * len(ks))})",
            [fields[k] for k in ks])
        conn.commit()
        log.info("[repo] articles.insert_full art=%.16s name=%r", str(fields.get("art_biz") or "")[:16], fields.get("name"))
    finally:
        conn.close()


def articles_by_account(aid: int, biz: str) -> list:
    """公众号文章: biz 非空按 biz, 否则按 account_id"""
    conn = get_conn()
    try:
        if biz:
            return [dict(r) for r in conn.execute(
                "SELECT * FROM articles WHERE biz=? ORDER BY date DESC, id DESC", (biz,)).fetchall()]
        return [dict(r) for r in conn.execute(
            "SELECT * FROM articles WHERE account_id=? ORDER BY date DESC, id DESC", (aid,)).fetchall()]
    finally:
        conn.close()


def article_delete_by_account(artid: int, aid: int) -> bool:
    conn = get_conn()
    try:
        cur = conn.execute("DELETE FROM articles WHERE id=? AND account_id=?", (artid, aid))
        conn.commit()
        log.info("[repo] articles.delete_by_account artid=%s aid=%s -> %s", artid, aid, cur.rowcount > 0)
        return cur.rowcount > 0
    finally:
        conn.close()


# ============ 评论 comments ============
def comments_query(where: list, params: list, order_sql: str) -> list:
    """通用评论查询(where 片段列表, order_sql 白名单化)"""
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM comments WHERE " + " AND ".join(where) +
            " ORDER BY is_top DESC, " + order_sql + ", id ASC", params).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def comments_count_by_art() -> dict:
    """各文章评论数 {art_biz: n}"""
    conn = get_conn()
    try:
        return dict(conn.execute(
            "SELECT art_biz, COUNT(*) n FROM comments GROUP BY art_biz").fetchall())
    finally:
        conn.close()


def comment_dup_count(art_biz: str, comment_biz: str) -> int:
    conn = get_conn()
    try:
        return conn.execute(
            "SELECT COUNT(*) c FROM comments WHERE art_biz=? AND comment_biz=?",
            (art_biz, comment_biz)).fetchone()["c"]
    finally:
        conn.close()


def comment_insert(fields: dict) -> None:
    """插入评论(fields 含 comment_biz,parent_comment_biz,art_biz,author,content,time,likes,ip,
    is_author,is_top,is_first,is_author_reply,is_author_like,level)
    入库前把相对时间(x小时前等)统一转绝对时间, 保证日期筛选可用"""
    from ..core.common import comment_time_to_abs
    _tm = comment_time_to_abs(fields.get("time"))
    if _tm is not None and _tm != fields.get("time"):
        fields = {**fields, "time": _tm}
    ks = list(fields.keys())
    conn = get_conn()
    try:
        conn.execute(
            f"INSERT INTO comments({','.join(ks)}) VALUES({','.join(['?'] * len(ks))})",
            [fields[k] for k in ks])
        conn.commit()
        log.info("[repo] comments.insert art=%.16s author=%r", str(fields.get("art_biz") or "")[:16], fields.get("author"))
    finally:
        conn.close()


def comments_delete(ids: list, art_biz: str = "") -> int:
    conn = get_conn()
    try:
        marks = ",".join("?" * len(ids))
        if art_biz:
            cur = conn.execute(f"DELETE FROM comments WHERE art_biz=? AND id IN ({marks})", (art_biz, *ids))
        else:
            cur = conn.execute(f"DELETE FROM comments WHERE id IN ({marks})", ids)
        conn.commit()
        log.info("[repo] comments.delete %d 条(art=%s)", cur.rowcount, str(art_biz)[:16])
        return cur.rowcount
    finally:
        conn.close()
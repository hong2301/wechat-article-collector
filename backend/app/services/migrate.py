# -*- coding: utf-8 -*-
"""把 data/collected.csv 迁移到 SQLite articles 表(按公众号名称匹配 account_id)"""
import csv
import os

from ..database import get_conn


def _collected_path():
    return os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))), "data", "collected.csv")


def migrate_collected():
    path = _collected_path()
    if not os.path.isfile(path):
        return 0
    conn = get_conn()
    try:
        # 公众号名称 -> (account_id, biz)
        acc = {r["name"]: (r["id"], r["biz"]) for r in conn.execute("SELECT id,name,biz FROM accounts").fetchall()}
        with open(path, encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            n = 0
            for r in reader:
                name = (r.get("公众号名称") or "").strip()
                aid, biz = acc.get(name, (None, ""))
                conn.execute(
                    "INSERT INTO articles(account_id, biz, name, date, title, link, reads, likes, forwards, favorites, comments, write_time, original, ip) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (aid, biz, name, (r.get("日期") or ""), (r.get("标题") or ""), (r.get("链接") or ""),
                     (r.get("阅读") or ""), (r.get("点赞") or ""), (r.get("转发") or ""),
                     (r.get("喜欢") or ""), (r.get("评论") or ""), (r.get("写入时间") or ""),
                     (r.get("是否原创") or ""), (r.get("IP属地") or "")))
                n += 1
            conn.commit()
            return n
    finally:
        conn.close()


if __name__ == "__main__":
    n = migrate_collected()
    print(f"迁移完成: {n} 篇文章写入 SQLite")

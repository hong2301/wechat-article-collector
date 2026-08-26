# -*- coding: utf-8 -*-
"""文章采集统计: 从 collected.csv + accounts 生成 每公众号采集数 + 每日日历数据"""
import csv
import os
from collections import defaultdict

from ..database import get_conn, DB_PATH


def _collected_path():
    return os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))), "data", "collected.csv")


def load_collected():
    """读 collected.csv -> 每行 dict; 补 biz 列(按公众号名称匹配 accounts)"""
    path = _collected_path()
    if not os.path.isfile(path):
        return []
    conn = get_conn()
    try:
        accts = {r["name"]: r["biz"] for r in conn.execute("SELECT name,biz FROM accounts WHERE biz != ''").fetchall()}
    finally:
        conn.close()
    rows = []
    with open(path, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            r["biz"] = accts.get(r.get("公众号名称") or "", "")
            rows.append(r)
    return rows


def account_stats():
    """按公众号聚合: {name_or_biz: {"count": n, "daily": {date: n}}}"""
    rows = load_collected()
    by = defaultdict(lambda: {"count": 0, "daily": defaultdict(int)})
    for r in rows:
        key = r["biz"] or r.get("公众号名称") or ""
        if not key:
            continue
        d = (r.get("日期") or "")[:10]
        by[key]["count"] += 1
        if d:
            by[key]["daily"][d] += 1
    # daily 转普通 dict
    return {k: {"count": v["count"], "daily": dict(v["daily"])} for k, v in by.items()}


def account_articles(biz="", name=""):
    """该公众号的文章列表(collected.csv, 按biz优先/名称匹配)"""
    rows = load_collected()
    out = []
    for r in rows:
        # 匹配: biz 相同, 或名称相同
        if (biz and r.get("biz") == biz) or (not biz and name and r.get("公众号名称") == name) or (biz == r.get("biz")):
            out.append({
                "title": r.get("标题") or "",
                "date": r.get("日期") or "",
                "link": r.get("链接") or "",
                "reads": r.get("阅读") or "",
                "likes": r.get("点赞") or "",
            })
    return out


def get_account_collect(account_id=None, biz="", name=""):
    """单个公众号的采集统计; 优先按 biz, 其次按名称"""
    stats = account_stats()
    if biz and biz in stats:
        return stats[biz]
    if name and name in stats:
        return stats[name]
    return {"count": 0, "daily": {}}

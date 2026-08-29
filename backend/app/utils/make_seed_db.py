# -*- coding: utf-8 -*-
"""生成打包用种子空数据库: 点位设置+滚动设置+AI模型(无key) 保留, 其他表全空

用法:
    python backend/app/services/make_seed_db.py

输出: backend/assets/collector_seed.db
用途: 打包/新装机时缺库则从种子库复制
"""
import os
import shutil
import sqlite3

_BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
SRC = os.path.join(_BASE, "data", "collector.db")
OUT_DIR = os.path.join(_BASE, "backend", "assets")
OUT = os.path.join(OUT_DIR, "collector_seed.db")

KEEP_TABLES = ["points", "scrolls", "ai_model"]
CLEAR_TABLES = ["accounts", "sort_config", "articles", "comments"]


def make(src, out):
    os.makedirs(os.path.dirname(out), exist_ok=True)
    shutil.copy(src, out)
    conn = sqlite3.connect(out)
    try:
        for t in CLEAR_TABLES:
            conn.execute(f"DELETE FROM {t}")
        conn.execute("UPDATE ai_model SET api_key=''")
        conn.commit()
        chk = {}
        for t in sorted(conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()):
            chk[t[0]] = conn.execute(f"SELECT COUNT(*) FROM {t[0]}").fetchone()[0]
        print("tables:", chk)
        empty_keys = conn.execute("SELECT COUNT(*) FROM ai_model WHERE api_key<>''").fetchone()[0]
        print("ai_model 非空key数:", empty_keys)
    finally:
        conn.close()
    print("seed ->", out, os.path.getsize(out), "bytes")


if __name__ == "__main__":
    if not os.path.isfile(SRC):
        print("! 找不到开发机数据库:", SRC)
        raise SystemExit(1)
    make(SRC, OUT)
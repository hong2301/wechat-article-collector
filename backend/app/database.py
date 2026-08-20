# -*- coding: utf-8 -*-
"""SQLite 数据库连接 + 建表
单文件: data/collector.db; 后续多表(设置/文章/评论等)在这里扩展"""
import os
import sqlite3

_BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DB_PATH = os.path.join(_BASE, "data", "collector.db")


def get_conn():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    conn = get_conn()
    try:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS accounts (
            id      INTEGER PRIMARY KEY AUTOINCREMENT,
            name    TEXT NOT NULL,
            biz     TEXT DEFAULT '',
            status  TEXT DEFAULT 'pending',
            remark  TEXT DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS sort_config (
            record_id   INTEGER PRIMARY KEY,
            sort_order  INTEGER NOT NULL,
            UNIQUE(sort_order)
        );
        """)
        conn.commit()
        # 迁移: 旧表 link -> biz
        cols = [r[1] for r in conn.execute("PRAGMA table_info(accounts)").fetchall()]
        if "link" in cols and "biz" not in cols:
            conn.execute("ALTER TABLE accounts RENAME COLUMN link TO biz")
            conn.commit()
            print("migrate: accounts.link -> biz")
    finally:
        conn.close()

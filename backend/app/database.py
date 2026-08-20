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
        CREATE TABLE IF NOT EXISTS articles (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id   INTEGER,
            biz          TEXT DEFAULT '',
            name         TEXT DEFAULT '',
            date         TEXT DEFAULT '',
            title        TEXT DEFAULT '',
            link         TEXT DEFAULT '',
            reads        TEXT DEFAULT '',
            likes        TEXT DEFAULT '',
            forwards     TEXT DEFAULT '',
            favorites    TEXT DEFAULT '',
            comments     TEXT DEFAULT '',
            write_time   TEXT DEFAULT '',
            shot         TEXT DEFAULT '',
            read_shot    TEXT DEFAULT '',
            original     TEXT DEFAULT '',
            ip           TEXT DEFAULT ''
        );
        """)
        # biz 唯一(同 biz 不允许重复公众号)
        try:
            conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_accounts_biz ON accounts(biz)")
            conn.commit()
        except Exception:
            pass
        conn.commit()
        # 迁移: articles 补 biz 列
        _acols = [r[1] for r in conn.execute("PRAGMA table_info(articles)").fetchall()]
        if "biz" not in _acols:
            conn.execute("ALTER TABLE articles ADD COLUMN biz TEXT DEFAULT ''")
            conn.commit()
        # 迁移: 旧表 link -> biz
        cols = [r[1] for r in conn.execute("PRAGMA table_info(accounts)").fetchall()]
        if "link" in cols and "biz" not in cols:
            conn.execute("ALTER TABLE accounts RENAME COLUMN link TO biz")
            conn.commit()
            print("migrate: accounts.link -> biz")
    finally:
        conn.close()

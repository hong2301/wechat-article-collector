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
            art_biz      TEXT DEFAULT '',
            reads        TEXT DEFAULT '',
            likes        TEXT DEFAULT '',
            forwards     TEXT DEFAULT '',
            favorites    TEXT DEFAULT '',
            comments     TEXT DEFAULT '',
            write_time   TEXT DEFAULT '',
            original     TEXT DEFAULT '',
            ip           TEXT DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS comments (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            comment_biz      TEXT DEFAULT '',
            parent_comment_biz TEXT DEFAULT '',
            art_biz          TEXT DEFAULT '',
            author           TEXT DEFAULT '',
            content          TEXT DEFAULT '',
            time             TEXT DEFAULT '',
            likes            TEXT DEFAULT '',
            ip               TEXT DEFAULT '',
            is_author        INTEGER DEFAULT 0,
            is_top           INTEGER DEFAULT 0,
            is_author_reply  INTEGER DEFAULT 0,
            is_author_like   INTEGER DEFAULT 0,
            is_first         INTEGER DEFAULT 0,
            level            INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS points (
            id      INTEGER PRIMARY KEY AUTOINCREMENT,
            name    TEXT DEFAULT '',
            x       TEXT DEFAULT '',
            y       TEXT DEFAULT '',
            remark  TEXT DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS scrolls (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT DEFAULT '',
            distance    TEXT DEFAULT '',
            point_id    INTEGER DEFAULT 0,
            direction   TEXT DEFAULT 'down',
            remark      TEXT DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS ai_model (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            provider    TEXT DEFAULT 'doubao',
            api_key     TEXT DEFAULT '',
            model_id    TEXT DEFAULT ''
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
        # 迁移: articles.link -> art_biz (文章id, 清空旧数据)
        _newacols = [r[1] for r in conn.execute("PRAGMA table_info(articles)").fetchall()]
        if "link" in _newacols and "art_biz" not in _newacols:
            conn.execute("DELETE FROM articles")   # 清空文章表(用户要求)
            try:
                conn.execute("DROP INDEX IF EXISTS idx_articles_biz_link")
            except Exception:
                pass
            conn.execute("ALTER TABLE articles RENAME COLUMN link TO art_biz")
            conn.commit()
            print("migrate: articles.link -> art_biz (清空)")
        # 迁移: comments 补 is_first 列
        _ccols = [r[1] for r in conn.execute("PRAGMA table_info(comments)").fetchall()]
        if _ccols and "is_first" not in _ccols:
            conn.execute("ALTER TABLE comments ADD COLUMN is_first INTEGER DEFAULT 0")
            conn.commit()
        # 文章唯一: 同biz下 art_biz(文章id) 唯一
        try:
            conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_articles_biz_art ON articles(biz, art_biz) WHERE art_biz IS NOT NULL AND art_biz<>''")
            conn.commit()
        except Exception as e:
            print("articles unique index:", e)
    finally:
        conn.close()

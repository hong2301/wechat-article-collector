# -*- coding: utf-8 -*-
import json
"""SQLite 数据库连接 + 建表
单文件: data/collector.db; 后续多表(设置/文章/评论等)在这里扩展"""
import os
import sqlite3

_BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# 数据目录: 优先环境变量(打包版由 Electron 指定 exe 旁 data/), 开发时回退项目根 data/
_DATA_DIR = os.environ.get("WECHAT_COLLECTOR_DATA_DIR") or os.path.join(_BASE, "data")
DB_PATH = os.path.join(_DATA_DIR, "collector.db")


def data_dir():
    """数据根目录(数据库所在): 打包=exe旁data, 开发=项目根data"""
    return _DATA_DIR


def default_html_dir():
    """保存HTML的默认根目录(开发/打包统一放在数据目录下): <data>/article_data"""
    return os.path.join(_DATA_DIR, "article_data")


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
            type        TEXT DEFAULT 'account',
            UNIQUE(type, sort_order)
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
            ip           TEXT DEFAULT '',
            comment_recog TEXT DEFAULT '0'
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
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            name          TEXT DEFAULT '',
            x             TEXT DEFAULT '',
            y             TEXT DEFAULT '',
            remark        TEXT DEFAULT '',
            depend_points TEXT DEFAULT '[]'
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
        CREATE TABLE IF NOT EXISTS settings (
            key   TEXT PRIMARY KEY,
            value TEXT DEFAULT ''
        );
        """)
        # 冲突软件表: 采集/自动设置期间可能干扰屏幕的其他软件(窗口标题/进程名称均可多个)
        conn.execute("""
        CREATE TABLE IF NOT EXISTS conflict_apps (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            name          TEXT NOT NULL,
            window_titles TEXT DEFAULT '[]',     -- JSON 数组: 窗口标题(子串匹配)
            process_names TEXT DEFAULT '[]'      -- JSON 数组: 进程名(不区分大小写)
        );
        """)
        # 种子: 已知可能干扰采集的软件(幂等, 用户可改)
        _seed_conflicts = [
            ("有道翻译", ["有道翻译", "有道词典", "有道", "youdao"], ["youdao-dict.exe", "youdao-dictangel.exe", "youdaodict.exe"]),
            ("企业微信", ["企业微信", "WeCom"], ["WXWork.exe"]),
        ]
        for _nm, _titles, _procs in _seed_conflicts:
            _cnt = conn.execute("SELECT COUNT(*) FROM conflict_apps WHERE name=?", (_nm,)).fetchone()[0]
            if _cnt == 0:
                conn.execute("INSERT INTO conflict_apps(name, window_titles, process_names) VALUES(?,?,?)",
                             (_nm, json.dumps(_titles, ensure_ascii=False), json.dumps(_procs, ensure_ascii=False)))
        conn.commit()
        # biz 唯一(同 biz 不允许重复公众号)
        try:
            conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_accounts_biz ON accounts(biz)")
            conn.commit()
        except Exception:
            pass
        conn.commit()
        # 迁移: 删除点位 28/29(复制链接左上/右下) - 采集与自动设置已不再依赖
        try:
            _del = conn.execute("DELETE FROM points WHERE name IN ('复制链接左上','复制链接右下')").rowcount
            if _del:
                print(f"migrate: 删除点位 28/29({_del} 行)")
            conn.execute("DELETE FROM sort_config WHERE type='point' AND record_id IN (28,29)")
            # 点位27 依赖更新: 移除 28/29
            conn.execute("UPDATE points SET depend_points='[11,12,9,14,18]' WHERE name='点击复制链接'")
            conn.commit()
        except Exception as _e:
            print(f"migrate: 删除点位28/29失败: {_e}")
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
        # 迁移: points 补 depend_points 列(依赖点位数组, 前端不展示)
        _pcols = [r[1] for r in conn.execute("PRAGMA table_info(points)").fetchall()]
        if _pcols and "depend_points" not in _pcols:
            conn.execute("ALTER TABLE points ADD COLUMN depend_points TEXT DEFAULT '[]'")
            conn.commit()
            print("migrate: points.depend_points")
        # 迁移: sort_config 加 type 列(account/point 共用排序表, 唯一(type, sort_order))
        _scols = [r[1] for r in conn.execute("PRAGMA table_info(sort_config)").fetchall()]
        if _scols and "type" not in _scols:
            conn.execute("CREATE TABLE sort_config_new (record_id INTEGER PRIMARY KEY, sort_order INTEGER NOT NULL, type TEXT DEFAULT 'account', UNIQUE(type, sort_order))")
            conn.execute("INSERT INTO sort_config_new (record_id, sort_order, type) SELECT record_id, sort_order, 'account' FROM sort_config")
            conn.execute("DROP TABLE sort_config")
            conn.execute("ALTER TABLE sort_config_new RENAME TO sort_config")
            conn.commit()
        # 文章唯一: 同biz下 art_biz(文章id) 唯一
        try:
            conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_articles_biz_art ON articles(biz, art_biz) WHERE art_biz IS NOT NULL AND art_biz<>''")
            conn.commit()
        except Exception as e:
            print("articles unique index:", e)
    finally:
        conn.close()

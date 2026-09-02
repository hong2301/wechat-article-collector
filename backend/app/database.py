# -*- coding: utf-8 -*-
import json
"""SQLite 数据库连接 + 建表
单文件: data/collector.db; 后续多表(设置/文章/评论等)在这里扩展"""
import os
import sqlite3
import sys

_BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# 打包版数据目录: 固定 D:/wechat-collector_data(安装目录外, 更新/重装不覆盖用户数据)
#   dev: 环境变量优先, 否则项目根 data/; 打包(PyInstaller sys.frozen): D:/wechat-collector_data(无D盘回退 exe 旁 data)
_PACKAGED_DATA = "D:/wechat-collector_data"


def _data_dir():
    env = os.environ.get("WECHAT_COLLECTOR_DATA_DIR")
    if env:
        return env
    if getattr(sys, "frozen", False):
        try:
            os.makedirs(_PACKAGED_DATA, exist_ok=True)
        except Exception:
            return os.path.join(os.path.dirname(sys.executable), "data")   # 无D盘回退 exe 旁 data
        return _PACKAGED_DATA
    return os.path.join(_BASE, "data")


_DATA_DIR = _data_dir()
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


def is_packaged():
    """正式(打包)版判定: 环境变量 WECHAT_PACKAGED=1 显式设置(入口 run_packaged.py 设), 兼容 PyInstaller sys.frozen"""
    if os.environ.get("WECHAT_PACKAGED") == "1":
        return True
    return bool(getattr(sys, "frozen", False))


def _seed_path():
    """随包固化 seed 库: 打包版=安装目录 data/collector.db(build 时模板库复制所得, 用户库在 D:/xxx_data), 开发=scripts/template_collector.db"""
    if is_packaged():
        _exe_parent = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(sys.executable))))
        cand = os.path.join(_exe_parent, "data", "collector.db")
        return cand if os.path.exists(cand) else None
    cand = os.path.join(_BASE, "scripts", "template_collector.db")
    return cand if os.path.exists(cand) else None


def _backup_db():
    """升级前自动备份用户库 -> <数据目录>/backup/collector_<ts>.db, 保留最近 5 份"""
    try:
        if not os.path.exists(DB_PATH):
            return
        import shutil, time
        bdir = os.path.join(_DATA_DIR, "backup")
        os.makedirs(bdir, exist_ok=True)
        dst = os.path.join(bdir, "collector_" + time.strftime("%Y%m%d_%H%M%S") + ".db")
        shutil.copy2(DB_PATH, dst)
        olds = sorted([f for f in os.listdir(bdir) if f.startswith("collector_")])
        for f in olds[:-5]:
            try:
                os.remove(os.path.join(bdir, f))
            except Exception:
                pass
        print(f"[db] 已备份用户库 -> {dst}")
    except Exception as e:
        print(f"[db] 备份失败(忽略): {e}")


def _merge_seed(conn):
    """从随包 seed 合并固化表到用户库(幂等 INSERT OR IGNORE, 不动用户数据)"""
    src = _seed_path()
    if not src:
        return 0
    merged = 0
    sc = None
    try:
        sc = sqlite3.connect(src)
        sc.row_factory = sqlite3.Row
        for table in ("points", "scrolls", "ai_model", "conflict_apps"):
            try:
                scur = sc.execute(f"SELECT * FROM {table}").fetchall()
                ucols = [r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]
                cols = [r[1] for r in sc.execute(f"PRAGMA table_info({table})").fetchall()]
                common = [c for c in ucols if c in cols]
                if not common:
                    continue
                sel = ", ".join('"' + c + '"' for c in common)
                ph = ", ".join("?" for _ in common)
                for r in scur:
                    try:
                        cur = conn.execute(
                            "INSERT OR IGNORE INTO " + table + "(" + sel + ") VALUES(" + ph + ")",
                            [r[c] for c in common])
                        merged += cur.rowcount
                    except Exception:
                        pass
            except Exception as e:
                print(f"[db] seed 合并 {table} 跳过: {e}")
        # settings: 只补缺失 key, 不覆盖已有
        try:
            for r in sc.execute("SELECT key, value FROM settings"):
                if conn.execute("SELECT 1 FROM settings WHERE key=?", (r["key"],)).fetchone() is None:
                    conn.execute("INSERT INTO settings(key,value) VALUES(?,?)", (r["key"], r["value"]))
                    merged += 1
        except Exception:
            pass
    except Exception as e:
        print(f"[db] seed 合并失败(忽略): {e}")
    finally:
        if sc is not None:
            try:
                sc.close()
            except Exception:
                pass
    return merged


def init_db():
    conn = get_conn()
    # 升级前自动备份(库已存在且迁移会变化时)
    try:
        if os.path.exists(DB_PATH):
            _r = conn.execute("SELECT value FROM settings WHERE key='schema_version'").fetchone()
            _prev = _r[0] if _r else None
            if _prev != "4":
                _backup_db()
    except Exception:
        pass
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
        # 固化 seed 合并(幂等补齐, 不动用户数据) + 记录 schema 版本
        try:
            _m = _merge_seed(conn)
            if _m:
                print(f"[db] seed 合并完成: 补齐 {_m} 条固化数据")
            conn.execute("INSERT INTO settings(key,value) VALUES('schema_version','4')"
                         " ON CONFLICT(key) DO UPDATE SET value=excluded.value")
            conn.commit()
        except Exception as e:
            print(f"[db] seed 合并/版本记录失败(忽略): {e}")
    finally:
        conn.close()

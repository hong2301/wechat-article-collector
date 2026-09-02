# -*- coding: utf-8 -*-
"""打包前置: 把开发库(data/collector.db)的微信版本号同步到模板库(scripts/template_collector.db)
build.js 复制模板库进 release 前调用, 保证打包版开箱版本号 = 当前开发维护的值。
dev 库无 settings.wechat_version 时保持模板库原有值(不写坏)。
程序版本不落库: 前后端统一从根 package.json 读取(单一来源)。"""
import os
import sqlite3

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEV_DB = os.path.join(ROOT, "data", "collector.db")
TPL_DB = os.path.join(ROOT, "scripts", "template_collector.db")
KEY = "wechat_version"


def _read_version(db):
    try:
        conn = sqlite3.connect(db)
        try:
            r = conn.execute("SELECT value FROM settings WHERE key=?", (KEY,)).fetchone()
            return r[0] if r else ""
        finally:
            conn.close()
    except Exception:
        return ""


def _write_version(db, value):
    conn = sqlite3.connect(db)
    try:
        conn.executescript(
            "CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT DEFAULT '');")
        conn.execute("INSERT INTO settings(key,value) VALUES(?,?)"
                     " ON CONFLICT(key) DO UPDATE SET value=excluded.value", (KEY, value))
        conn.commit()
    finally:
        conn.close()


def main():
    if not os.path.exists(TPL_DB):
        print("跳过: 模板库不存在", TPL_DB)
        return
    src = _read_version(DEV_DB)
    if not src:
        print("dev 库无微信版本号, 保持模板库原值(跳过同步)")
        return
    _write_version(TPL_DB, src)
    print(f"✔ 已同步模板库 wechat_version = {src}")


if __name__ == "__main__":
    main()
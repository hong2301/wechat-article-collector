# -*- coding: utf-8 -*-
"""生成交付用模板数据库(空库但保留默认配置)

保留: 点位名称/备注、滚动配置(名称/关联点位/方向)、AI模型(服务商/模型id)
清空: 点位 xy 坐标、滚动距离、AI api_key
其余表(账号/文章/评论)为空。

用法:
  python scripts/make_template_db.py [输出目录]   (默认 ./data)
"""
import os
import shutil
import sqlite3
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND_DIR = os.path.join(ROOT, "backend")

# ---- 默认配置种子数据 ----
POINTS = [
    (9,  "微信窗口初始化不合法时窗口分离按钮"),
    (11, "点击微信左上角搜索输入框"),
    (12, "微信左上角搜索网络"),
    (13, "点击搜索网络后的窗口分离按钮"),
    (14, "搜一搜窗口查询按钮"),
    (15, "文章列表左上角"),
    (16, "文章列表右下角"),
    (18, "文章右上角3点"),
    (19, "文章底部数据栏左上"),
    (20, "文章底部数据栏右下"),
    (21, "阅读数左上"),
    (22, "阅读数右下"),
    (23, "搜索按钮2"),
    (24, "评论按钮"),
    (25, "评论区左上"),
    (26, "评论区右下"),
    (27, "点击复制链接"),
    (28, "复制链接左上"),
    (29, "复制链接右下"),
    (30, "4指标区域左上"),
    (31, "4指标区域右下"),
    (32, "阅读数左上"),
    (33, "阅读数右下"),
    (34, "评论按钮"),
    (35, "评论区左上"),
    (36, "评论区右下"),
]

SCROLLS = [
    (3,  "文章列表滚动", 15, "down"),
    (5,  "评论区滚动",   35, "down"),
    (8,  "1",             9, "down"),
]

AI_MODELS = [
    (5, "doubao", "doubao-seed-2-0-mini-260428"),
]


def main():
    out_dir = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "data")
    out_dir = os.path.abspath(out_dir)
    os.makedirs(out_dir, exist_ok=True)

    # 用后端建表逻辑生成 schema(与代码永远同步)
    os.environ["WECHAT_COLLECTOR_DATA_DIR"] = out_dir
    sys.path.insert(0, BACKEND_DIR)
    from app import database
    db_path = database.DB_PATH
    database.init_db()

    conn = sqlite3.connect(db_path)
    try:
        for pid, name in POINTS:
            conn.execute(
                "INSERT INTO points (id, name, x, y, remark) VALUES (?,?,?,?,?)",
                (pid, name, "", "", ""),
            )
        for sid, name, point_id, direction in SCROLLS:
            conn.execute(
                "INSERT INTO scrolls (id, name, distance, point_id, direction, remark) VALUES (?,?,?,?,?,?)",
                (sid, name, "", point_id, direction, ""),
            )
        for aid, provider, model_id in AI_MODELS:
            conn.execute(
                "INSERT INTO ai_model (id, provider, api_key, model_id) VALUES (?,?,?,?)",
                (aid, provider, "", model_id),
            )
        conn.commit()
    finally:
        conn.close()

    print(f"[make_template_db] 模板库已生成: {db_path}")
    return db_path


if __name__ == "__main__":
    main()
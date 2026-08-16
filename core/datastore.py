# -*- coding: utf-8 -*-
"""core.datastore: 数据层(input.csv / points.csv / ui_state.json / collected.csv)
依赖: core.paths(路径+常量), core.utils(log/_log_lock)
"""
import csv
import json
import os
import re
import time
from datetime import date, timedelta, datetime

from .paths import *
from .utils import log, _log_lock


def load_raw_input_rows():
    """读取 input.csv 所有行 -> [(idx, url, 公众号名称, 状态), ...]（含 url 为空的新增行）"""
    rows = []
    if not os.path.isfile(_input_path()):
        return rows
    with open(_input_path(), encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            try:
                idx = int(row.get("索引"))
            except (TypeError, ValueError):
                continue
            rows.append((idx,
                         (row.get("url") or "").strip(),
                         (row.get("公众号名称") or "").strip(),
                         (row.get("状态") or "pending").strip()))
    rows.sort(key=lambda r: r[0])
    return rows



def load_input_rows():
    """有效行（url 非空）-> [(idx, url, 公众号名称, 状态), ...]，采集逻辑用"""
    return [r for r in load_raw_input_rows() if r[1]]



def write_input_csv(rows):
    """把 [(idx, url, 公众号名称, 状态), ...] 整体写回 input.csv"""
    with open(_input_path(), "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["索引", "url", "公众号名称", "状态"])
        for idx, url, name, st in rows:
            w.writerow([idx, url, name, st])



def update_input_status(idx, status):
    """按索引列更新 input.csv 中某行的状态列"""
    path = _input_path()
    try:
        with open(path, encoding="utf-8-sig", newline="") as f:
            rows = list(csv.reader(f))
        if len(rows) < 2:
            return
        header = rows[0]
        if "状态" not in header:
            return
        col = header.index("状态")
        for r in rows[1:]:
            if len(r) > 0 and r[0].strip() == str(idx):
                if len(r) <= col:
                    r.extend([""] * (col - len(r) + 1))
                r[col] = status
                break
        with open(path, "w", encoding="utf-8-sig", newline="") as f:
            csv.writer(f).writerows(rows)
    except Exception as e:
        log(f"更新状态失败: {e}")


# ================= 数据层（comments.csv 评论） =================

def append_comments(article_url, comment_list):
    """写入评论到 data/comments.csv
    comment_list: [{"名称","地区","时间","点赞数量","正文","层级(1/2)",
                    "是否置顶","是否作者回复","是否作者点赞",...}, ...]
    父级评论ID / 回复数量 在此函数内计算
    返回: 写入条数（0 表示全部重复或失败）"""
    if not article_url or not comment_list:
        return 0
    path = os.path.join(_data_dir(), COMMENTS_CSV)
    try:
        with _log_lock:
            os.makedirs(_data_dir(), exist_ok=True)
            # 读已有评论(去重用)
            existing = []
            if os.path.isfile(path):
                with open(path, encoding="utf-8-sig", newline="") as f:
                    for row in csv.DictReader(f):
                        existing.append(row.get("评论ID", ""))

            # ---- 计算评论ID ----
            def _cid(name, loc, t, likes, text, level):
                raw = f"{name}|{loc}|{t}|{likes}|{text}|{level}"
                import hashlib
                return hashlib.md5(raw.encode("utf-8")).hexdigest()[:16]

            # ---- 计算父级评论ID ----
            l1_id = ""       # 当前所属一级评论ID
            id_map = {}      # 名称 -> 评论ID(用于二级"回复某某"找父级)
            for c in comment_list:
                name = c.get("名称", "")
                loc = c.get("地区", "")
                t = c.get("时间", "")
                likes = str(c.get("点赞数量", "0"))
                text = c.get("正文", "")
                level = c.get("层级", 1)
                pinned = c.get("是否置顶", "否")
                author_reply = c.get("是否作者回复", "否")
                author_like = c.get("是否作者点赞", "否")
                reply_text = c.get("回复文本", "")

                cid = _cid(name, loc, t, likes, text, level)
                c["评论ID"] = cid
                id_map[name] = cid

                if level == 1:
                    l1_id = cid
                    c["父级评论ID"] = ""
                else:
                    # 二级: "回复某某" -> 父级=某某的ID; 否则父级=所属一级
                    target = ""
                    if reply_text and reply_text.startswith("回复"):
                        # "回复某某某：" -> 提取某某某
                        m = re.match(r"回复(.{1,20})[：:]", reply_text)
                        if m:
                            target = m.group(1)
                    if target and target in id_map:
                        c["父级评论ID"] = id_map[target]
                    else:
                        c["父级评论ID"] = l1_id

            # ---- 回复数量: 统计每条评论被多少二级回复 ----
            reply_count_map = {}
            for c in comment_list:
                parent_id = c.get("父级评论ID", "")
                if parent_id:
                    reply_count_map[parent_id] = reply_count_map.get(parent_id, 0) + 1
            for c in comment_list:
                c["回复数量"] = str(reply_count_map.get(c["评论ID"], 0))

            # ---- 去重 + 写入 ----
            new_count = 0
            rows_to_write = []
            for c in comment_list:
                if c["评论ID"] in existing:
                    continue
                rows_to_write.append({
                    "文章链接": article_url,
                    "名称": c.get("名称", ""),
                    "地区": c.get("地区", ""),
                    "时间": c.get("时间", ""),
                    "点赞数量": c.get("点赞数量", "0"),
                    "正文": c.get("正文", ""),
                    "层级": str(c.get("层级", 1)),
                    "是否置顶": c.get("是否置顶", "否"),
                    "是否作者回复": c.get("是否作者回复", "否"),
                    "是否作者点赞": c.get("是否作者点赞", "否"),
                    "评论ID": c["评论ID"],
                    "父级评论ID": c.get("父级评论ID", ""),
                    "回复数量": c.get("回复数量", "0"),
                })
                existing.append(c["评论ID"])
                new_count += 1

            if not rows_to_write:
                return 0

            write_header = not os.path.isfile(path) or os.path.getsize(path) == 0
            with open(path, "a", encoding="utf-8-sig", newline="") as f:
                w = csv.DictWriter(f, fieldnames=COMMENTS_HEADER)
                if write_header:
                    w.writeheader()
                for row in rows_to_write:
                    w.writerow(row)
            return new_count
    except Exception as e:
        log(f"写入评论CSV失败: {e}")
        return 0


def delete_comments(article_url):
    """删除 data/comments.csv 中某文章链接的所有评论(误采集清理用)
    返回: 删除条数"""
    if not article_url:
        return 0
    path = os.path.join(_data_dir(), COMMENTS_CSV)
    if not os.path.isfile(path):
        return 0
    try:
        with _log_lock:
            with open(path, encoding="utf-8-sig", newline="") as f:
                rows = list(csv.reader(f))
            if len(rows) < 2:
                return 0
            keep = [rows[0]]
            deleted = 0
            url = article_url.strip()
            for r in rows[1:]:
                if len(r) > 0 and r[0].strip() == url:
                    deleted += 1
                else:
                    keep.append(r)
            if deleted:
                with open(path, "w", encoding="utf-8-sig", newline="") as f:
                    csv.writer(f).writerows(keep)
            return deleted
    except Exception as e:
        log(f"删除评论失败: {e}")
        return 0


# ================= 数据层（points.csv） =================

def append_collected(gzh, pub_time, title, link,
                   reads=-1, likes=-1, forwards=-1, favorites=-1, comments=-1,
                   write_time=None, shot="", read_shot="", original="", ip=""):
    """追加一条采集记录到 data/collected.csv（线程安全，不做重复检查）
    互动数据列（阅读/点赞/转发/喜欢/评论）默认 -1（未采集到），后续采集逻辑可传入；
    write_time = 点击时间点位的时间（精确到秒），不传则用当前时间
    返回: "add"=已写入 / "error"=写入失败"""
    path = _collected_path()
    link = (link or "").strip()
    if not link:
        return "skip"
    try:
        with _log_lock:
            # 检查表头是否最新（兼容旧版），非最新则整体重写（旧行缺列补默认值）
            header = None
            if os.path.isfile(path):
                with open(path, encoding="utf-8-sig", newline="") as f:
                    reader = csv.DictReader(f)
                    header = list(reader.fieldnames or [])
            now = write_time or time.strftime("%Y-%m-%d %H:%M:%S")
            new_row = {
                "公众号名称": gzh, "日期": pub_time or "", "标题": title or "",
                "链接": link, "阅读": reads, "点赞": likes, "转发": forwards,
                "喜欢": favorites, "评论": comments, "写入时间": now,
                "互动截图": shot or "",
                "阅读截图": read_shot or "",
                "是否原创": original or "",
                "IP属地": ip or "",
            }
            if header != COLLECTED_HEADER or not os.path.isfile(path):
                rows = []
                if os.path.isfile(path):
                    with open(path, encoding="utf-8-sig", newline="") as f:
                        reader = csv.DictReader(f)
                        rows = [dict(r) for r in reader]
                rows.append(new_row)
                with open(path, "w", encoding="utf-8-sig", newline="") as f:
                    w = csv.DictWriter(f, fieldnames=COLLECTED_HEADER)
                    w.writeheader()
                    for r in rows:
                        row = {}
                        for k in COLLECTED_HEADER:
                            v = r.get(k)
                            if v is None:
                                v = 0 if k in ("阅读", "点赞", "转发", "喜欢", "评论") else ""
                            row[k] = v
                        w.writerow(row)
            else:
                with open(path, "a", encoding="utf-8-sig", newline="") as f:
                    w = csv.DictWriter(f, fieldnames=COLLECTED_HEADER)
                    w.writerow(new_row)
            return "add"
    except Exception as e:
        log(f"写入采集记录失败: {e}")
        return "error"



def load_points():
    """读取 config/points.csv -> [(id, 点位名称, x, y), ...] 按 id 排序"""
    rows = []
    if not os.path.isfile(_points_path()):
        return rows
    with open(_points_path(), encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            try:
                idx = int(row.get("id"))
            except (TypeError, ValueError):
                continue
            rows.append((idx,
                         (row.get("点位名称") or "").strip(),
                         (row.get("x") or "").strip(),
                         (row.get("y") or "").strip()))
    rows.sort(key=lambda r: r[0])
    return rows



def write_points(rows):
    """把 [(id, 点位名称, x, y), ...] 写回 points.csv"""
    with open(_points_path(), "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["id", "点位名称", "x", "y"])
        for idx, name, x, y in rows:
            w.writerow([idx, name, x, y])


# ================= 界面设置记忆 =================

def load_ui_state():
    """读取界面设置记忆，无则返回 {}"""
    path = os.path.join(_config_dir(), UI_STATE_FILE)
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        log(f"读取界面记忆失败: {e}")
        return {}



def save_ui_state(state):
    """保存界面设置记忆"""
    path = os.path.join(_config_dir(), UI_STATE_FILE)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception as e:
        log(f"保存界面记忆失败: {e}")



def parse_date(s):
    """解析 YYYY-MM-DD -> date，失败返回 None"""
    try:
        return datetime.strptime((s or "").strip(), "%Y-%m-%d").date()
    except Exception:
        return None



def time_range_desc(radio, cstart, cend):
    """把时间范围选择转成中文描述（含实际日期区间）"""
    today = date.today()
    if radio == "today":
        return f"当天（{today:%Y-%m-%d}）"
    if radio == "week":
        return f"近一周（{today - timedelta(days=7)} ~ {today}）"
    if radio == "month":
        return f"近一个月（{today - timedelta(days=30)} ~ {today}）"
    if radio == "year":
        return f"近一年（{today - timedelta(days=365)} ~ {today}）"
    if radio == CUSTOM:
        return f"自定义（{cstart} ~ {cend}）"
    return "全部"


__all__ = ["load_raw_input_rows", "load_input_rows", "write_input_csv",
           "update_input_status", "append_collected", "append_comments",
           "delete_comments",
           "load_points", "write_points",
           "load_ui_state", "save_ui_state", "parse_date", "time_range_desc"]

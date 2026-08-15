# -*- coding: utf-8 -*-
"""core.datastore: 数据层(input.csv / points.csv / ui_state.json / collected.csv)
依赖: core.paths(路径+常量), core.utils(log/_log_lock)
"""
import csv
import json
import os
import re
import time
from datetime import date, timedelta

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


# ================= 数据层（points.csv） =================

def append_collected(gzh, pub_time, title, link,
                   reads=-1, likes=-1, forwards=-1, favorites=-1, comments=-1,
                   write_time=None, shot="", read_shot=""):
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
    except Exception:
        return {}



def save_ui_state(state):
    """保存界面设置记忆"""
    path = os.path.join(_config_dir(), UI_STATE_FILE)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception:
        pass



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
           "update_input_status", "append_collected", "load_points", "write_points",
           "load_ui_state", "save_ui_state", "parse_date", "time_range_desc"]

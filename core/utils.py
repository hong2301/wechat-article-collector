# -*- coding: utf-8 -*-
"""core.utils: 日志 / 通用工具(日期解析, 文件名清洗, 文章抓取)
依赖: core.paths
"""
import os
import re
import threading
import time
from datetime import date, datetime, timedelta

from .paths import _script_root, LOG_FILE

# 日志相关全局(GUI 会设置 UI_LOG_HOOK 指向主界面日志回调)
UI_LOG_HOOK = None
CONSOLE_PRINT = True
_log_lock = threading.Lock()


def log(msg):
    """记录日志：控制台打印 + 写入 LOG_FILE（每行带时间戳）"""
    if CONSOLE_PRINT:
        try:
            print(msg, flush=True)
        except Exception:
            pass
    try:
        with _log_lock:
            with open(os.path.join(_script_root(), LOG_FILE), "a", encoding="utf-8") as f:
                f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n")
    except Exception:
        pass
    hook = UI_LOG_HOOK
    if hook is not None:
        try:
            hook(msg)
        except Exception:
            pass


def clean_filename(name):
    """文件名清洗：斜杠/点等特殊字符转为 _"""
    return re.sub(r'[\/:*?"<>|.]', "_", str(name)).strip()


_WEEKDAY_CN = {"一": 0, "二": 1, "三": 2, "四": 3, "五": 4, "六": 5, "日": 6, "天": 6}


def resolve_article_date(text, today=None):
    """把 OCR 识别到的时间文本解析为绝对日期(date)，按当前时间推断；失败返回 None
    支持: 今天/昨天/前天、x天前、星期X/周X/礼拜X、YYYY-MM-DD、X月X日、MM-DD"""
    today = today or date.today()
    text = str(text).strip()
    m = re.search(r"(\d{4})[-/. ](\d{1,2})[-/. ](\d{1,2})", text)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            pass
    if "今天" in text:
        return today
    if "昨天" in text:
        return today - timedelta(days=1)
    if "前天" in text:
        return today - timedelta(days=2)
    m = re.search(r"(\d+)\s*天前", text)
    if m:
        return today - timedelta(days=int(m.group(1)))
    m = re.search(r"(?:星期|周|礼拜)([一二三四五六日天])", text)
    if m:
        wd = _WEEKDAY_CN[m.group(1)]
        delta = (today.weekday() - wd) % 7
        return today - timedelta(days=delta)
    m = re.search(r"(\d{1,2})月(\d{1,2})日?", text)
    if m:
        try:
            d = date(today.year, int(m.group(1)), int(m.group(2)))
        except ValueError:
            return None
        if d > today:
            d = date(today.year - 1, int(m.group(1)), int(m.group(2)))
        return d
    m = re.search(r"(\d{1,2})[-/](\d{1,2})", text)
    if m:
        try:
            d = date(today.year, int(m.group(1)), int(m.group(2)))
        except ValueError:
            return None
        if d > today:
            d = date(today.year - 1, int(m.group(1)), int(m.group(2)))
        return d
    return None


_CT_RE = re.compile(r"var\s+ct\s*=\s*['\"]?(\d+)")
_PUBLISH_TIME_RE = re.compile(r"(?:var\s+publish_time\s*=\s*['\"]?)(\d+)")


def fetch_article(url, save_path=None):
    """抓取微信文章：返回 (标题, 发布时间 str 或 None)；save_path 给定时保存完整 HTML
    失败返回 None"""
    try:
        import requests
        headers = {
            "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                           "AppleWebKit/537.36 (KHTML, like Gecko) "
                           "Chrome/120.0 Safari/537.36"),
            "Referer": "https://mp.weixin.qq.com/",
        }
        resp = requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
        html = resp.text
        title = None
        m = re.search(r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)', html)
        if m:
            title = m.group(1)
        if not title:
            m = re.search(r"<title>([^<]+)</title>", html, re.S)
            if m:
                title = m.group(1).strip()
        if title:
            title = re.sub(r"\s+", " ", title).strip()
        pub_time = None
        m = _CT_RE.search(html) or _PUBLISH_TIME_RE.search(html)
        if m:
            try:
                ts = int(m.group(1))
                pub_time = datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")
            except Exception:
                pass
        if save_path:
            with open(save_path, "w", encoding="utf-8") as f:
                f.write(html)
        # 是否原创: copyright_logo 标签含"原创"
        original = ""
        m = re.search(r'id="copyright_logo"[^>]*>([^<]*)<', html)
        if m and "原创" in m.group(1):
            original = "原创"
        else:
            original = "非原创"
        # IP属地: JS 变量 ip_wording, 拼接 国家+省+市 全部非空字段(尽可能全)
        ip_location = ""
        m = re.search(r"ip_wording\s*:\s*\{(.*?)\}", html, re.S)
        if m:
            _parts = []
            for _k in ("country_name", "province_name", "city_name"):
                _mm = re.search(_k + r"\s*:\s*'([^']*)'", m.group(1))
                if _mm and _mm.group(1):
                    _parts.append(_mm.group(1))
            ip_location = "".join(_parts)
        if not ip_location:
            m = re.search(r'id="js_ip_wording"[^>]*>([^<]*)<', html)
            if m:
                ip_location = m.group(1).strip()
        return title, pub_time, original, ip_location
    except Exception as e:
        log(f"抓取文章失败: {e}")
        return None


__all__ = ["UI_LOG_HOOK", "CONSOLE_PRINT", "log", "clean_filename",
           "resolve_article_date", "fetch_article"]

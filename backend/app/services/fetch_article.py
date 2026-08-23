# -*- coding: utf-8 -*-
"""文章元信息抓取: 输入微信文章链接, 返回 (标题, 发布时间, 是否原创, IP属地)
来自旧程序 core/utils.py 的 fetch_article, 新后端独立版本(不依赖老目录)"""
import re
from datetime import datetime

_CT_RE = re.compile(r"var\s+ct\s*=\s*['\"]?(\d+)")
_PUBLISH_TIME_RE = re.compile(r"(?:var\s+publish_time\s*=\s*['\"]?)(\d+)")


def fetch_article(url, save_path=None):
    """抓取微信文章：返回 (标题, 发布时间 str 或 None, 是否原创, IP属地)
    save_path 给定时保存完整 HTML；失败返回 None"""
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
    except Exception:
        return None
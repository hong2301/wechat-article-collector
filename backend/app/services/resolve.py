# -*- coding: utf-8 -*-
"""从文章链接解析 公众号名称 + biz
必须带完整浏览器 header(含 Accept), 否则微信返回反爬验证页"""
import re
import requests

_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/120.0.0.0 Safari/537.36"),
    "Referer": "https://mp.weixin.qq.com/",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9",
}


def _clean(name):
    name = (name or "").strip()
    # 过滤误命中(属性名/空)
    if not name or len(name) < 2 or "data-" in name.lower() or "miniprogram" in name.lower():
        return None
    return name


def resolve_account(article_url, timeout=15):
    """输入文章链接, 返回 {"name": 公众号名称, "biz": biz} 或 None"""
    if not article_url or "mp.weixin.qq.com" not in article_url:
        return None
    try:
        html = requests.get(article_url, headers=_HEADERS, timeout=timeout).text
    except Exception:
        return None
    # 反爬检测
    if "verify.html" in html or "PAGE_MID='mmbizwap" in html:
        return None

    # biz
    biz = None
    m = re.search(r"biz:\s*[\"']([A-Za-z0-9=+/_-]+)[\"']", html)
    if not m:
        m = re.search(r"var\s+biz\s*=\s*[\"']([A-Za-z0-9=+/_-]+)[\"']", html)
    if m:
        biz = m.group(1)

    # 公众号名称
    name = None
    patterns = [
        r"nick_name\s*:\s*[\"']([^\"']+)[\"']",
        r"var\s+nickname\s*=\s*[\"']([^\"']+)[\"']",
        r"js_name\s*=\s*[\"']([^\"']+)[\"']",
        r'name="profile_nickname"[^>]*>([^<]+)<',
        r"nickname\s*[:=]\s*[\"']([^\"']{2,30})[\"']",
    ]
    for p in patterns:
        m = re.search(p, html)
        n = _clean(m.group(1)) if m else None
        if n:
            name = n
            break

    return {"name": name, "biz": biz}

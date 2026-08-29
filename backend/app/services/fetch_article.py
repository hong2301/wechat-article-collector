# -*- coding: utf-8 -*-
"""文章元信息抓取: 输入微信文章链接, 提取 标题/发布时间/是否原创/IP属地/公众号名
import hashlib
import os
来自旧程序 core/utils.py 的 fetch_article, 新后端独立版本(不依赖老目录)。

核心:
  fetch_article(url)          兼容旧接口: 返回 (标题, 发布时间, 是否原创, IP属地)
  fetch_article_full(url)     完整数据 dict(含公众号名/标题/日期/原创/ip/html)
  save_article_html(link)     独立保存本地HTML(公众号分类目录, 含图片), 只需链接
"""
import re
from datetime import datetime

from ..database import default_html_dir

_CT_RE = re.compile(r"var\s+ct\s*=\s*['\"]?(\d+)")
_PUBLISH_TIME_RE = re.compile(r"(?:var\s+publish_time\s*=\s*['\"]?)(\d+)")


def _headers():
    return {
        "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/120.0 Safari/537.36"),
        "Referer": "https://mp.weixin.qq.com/",
    }


def _request_and_parse(url):
    """请求微信文章并解析元数据, 返回 dict:
    {title, pub_time(YYYY-MM-DD HH:MM), original, ip, site_name, html}
    失败返回 None"""
    try:
        import requests
        resp = requests.get(url, headers=_headers(), timeout=15)
        resp.raise_for_status()
        html = resp.text
        # 标题: og:title -> <title>
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
        # 发布时间: var ct / publish_time 时间戳
        pub_time = None
        m = _CT_RE.search(html) or _PUBLISH_TIME_RE.search(html)
        if m:
            try:
                ts = int(m.group(1))
                pub_time = datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")
            except Exception:
                pass
        # 公众号名: js_name 节点(最可靠) -> var nickname -> og:site_name/author 兜底
        site_name = ""
        m = re.search(r'<a[^>]+id="js_name"[^>]*>\s*([^<]+?)\s*</a>', html)
        if m:
            site_name = m.group(1).strip()
        if not site_name:
            m = re.search(r'var\s+nickname\s*=\s*htmlDecode\("([^"]+)"\)', html)
            if m:
                site_name = m.group(1).strip()
        if not site_name:
            m = re.search(r'<meta[^>]+property=["\']og:site_name["\'][^>]+content=["\']([^"\']+)', html)
            if m:
                site_name = m.group(1).strip()
        if not site_name:
            m = re.search(r'<meta[^>]+name=["\']author["\'][^>]+content=["\']([^"\']+)', html)
            if m:
                site_name = m.group(1).strip()
        # 是否原创: copyright_logo 标签含"原创"
        original = ""
        m = re.search(r'id="copyright_logo"[^>]*>([^<]*)<', html)
        original = "原创" if (m and "原创" in m.group(1)) else "非原创"
        # IP属地: JS 变量 ip_wording, 拼接 国家+省+市 (尽可能全)
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
        return {"title": title, "pub_time": pub_time, "original": original,
                "ip": ip_location, "site_name": site_name, "html": html}
    except Exception:
        return None


def fetch_article(url, save_path=None):
    """抓取微信文章: 返回 (标题, 发布时间 str 或 None, 是否原创, IP属地)
    save_path 给定时保存完整 HTML; 失败返回 None"""
    data = _request_and_parse(url)
    if data is None:
        return None
    if save_path:
        with open(save_path, "w", encoding="utf-8") as f:
            f.write(data["html"])
    return data["title"], data["pub_time"], data["original"], data["ip"]


def fetch_article_full(url):
    """完整抓取: 返回 dict {title, pub_time, original, ip, site_name, html}
    失败返回 None (独立用, 一次请求拿全量数据)"""
    return _request_and_parse(url)


def clean_filename(name):
    """文件名清洗: 斜杠/点等特殊字符转为 _"""
    return re.sub(r'[\/:*?"<>|.]', "_", str(name)).strip()


def localize_article_images(html_path, timeout=20):
    """把微信文章HTML里的图片下载到本地并改写src, 实现离线可看
    图片存入 html 同目录下的 images/ 文件夹; 返回处理成功的图片数"""
    if not os.path.isfile(html_path):
        return 0
    try:
        import requests
        with open(html_path, encoding="utf-8") as f:
            html = f.read()
        imgs = re.findall(r'(?:data-src|src)="([^"]+)"', html)
        if not imgs:
            return 0
        img_dir = os.path.join(os.path.dirname(html_path), "images")
        os.makedirs(img_dir, exist_ok=True)
        headers = {"User-Agent": "Mozilla/5.0",
                   "Referer": "https://mp.weixin.qq.com/"}
        n = 0
        for u in imgs:
            try:
                r = requests.get(u, headers=headers, timeout=timeout)
                if r.status_code != 200:
                    continue
                ext = os.path.splitext(u.split("?")[0])[1]
                if not ext or len(ext) > 5:
                    ext = ".jpg"
                _h = hashlib.md5(u.encode()).hexdigest()[:8]
                _fname = _h + ext
                with open(os.path.join(img_dir, _fname), "wb") as f:
                    f.write(r.content)
                html = html.replace(u, "images/" + _fname)
                n += 1
            except Exception:
                continue
        if n:
            # 把 data-src 复制到 src(离线时JS懒加载不执行, 需静态可见)
            html = re.sub(
                r'<img\s+([^>]*?)data-src="([^"]+)"([^>]*?)>',
                lambda m: (
                    m.group(0) if re.search(r"src\s*=", m.group(1) + m.group(3))
                    else '<img %(a)ssrc="%(d)s" data-src="%(d)s"%(c)s>' % {
                        "a": m.group(1), "d": m.group(2), "c": m.group(3)}
                ), html)
            with open(html_path, "w", encoding="utf-8") as f:
                f.write(html)
        return n
    except Exception:
        return 0


def save_article_html(link, account_name="", base_dir=None):
    """抓取文章并保存为本地HTML(含图片本地化), 按公众号分类存目录。
    只是链接即可: 公众号名/标题/日期都从链接抓取的数据里提取(account_name可选覆盖)。
    目录: <base_dir>/<公众号名>/<日期>_<标题>/<日期>_<标题>.html + images/
    参数:
      link         微信文章链接
      account_name 公众号名称(可选; 空则从链接抓取数据提取)
      base_dir     根目录(默认 <数据目录>/article_data)
    返回: (保存路径 或 None, 说明文本)
    """
    base_dir = base_dir or default_html_dir()
    try:
        data = fetch_article_full(link)
        if not data:
            return None, "文章抓取失败"
        title = data.get("title")
        if not title:
            return None, "文章标题获取失败(可能被微信风控)"
        pub_time = data.get("pub_time") or ""
        # 公众号分类目录: 外部传入优先, 空则用抓取到的公众号名
        name = account_name or data.get("site_name") or "未知公众号"
        _stem = clean_filename(title)
        _date = pub_time[:10]
        _folder = f"{_date}_{_stem}" if _date else _stem
        acc_dir = os.path.join(base_dir, clean_filename(name))
        art_dir = os.path.join(acc_dir, _folder)
        os.makedirs(art_dir, exist_ok=True)
        html_path = os.path.join(art_dir, _folder + ".html")
        # 写入已抓取的 html(不再二次请求)
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(data["html"])
        img_n = localize_article_images(html_path)
        return html_path, f"已保存: {html_path} (图片{img_n}张)"
    except Exception as e:
        return None, f"保存HTML失败: {e}"
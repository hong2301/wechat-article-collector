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


def clean_filename(name):
    """文件名清洗: 斜杠/点等特殊字符转为 _"""
    return re.sub(r'[\/:*?"<>|.]', "_", str(name)).strip()


def localize_article_images(html_path, timeout=20):
    """把微信文章HTML里的图片下载到本地并改写src, 实现离线可看
    图片存入 html 同目录下的 images/ 文件夹; 返回处理成功的图片数"""
    import os
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
        import hashlib
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
    目录: <base_dir>/<公众号名>/<日期>_<标题>/<日期>_<标题>.html + images/
    参数:
      link         微信文章链接
      account_name 公众号名称(用作分类目录; 空则尝试从链接/抓取结果推断)
      base_dir     根目录(默认 D:/article_data)
    返回: (保存路径 或 None, 说明文本)
    """
    import os
    base_dir = base_dir or "D:/article_data"
    try:
        meta = fetch_article(link)
        if not meta:
            return None, "文章抓取失败"
        title, pub_time, _orig, _ip = meta
        if not title:
            return None, "文章标题获取失败(可能被微信风控)"
        _stem = clean_filename(title or "untitled")
        _date = (pub_time or "")[:10]
        _folder = f"{_date}_{_stem}" if _date else _stem
        # 公众号分类目录
        if not account_name:
            account_name = _extract_account_name(link) or "未知公众号"
        acc_dir = os.path.join(base_dir, clean_filename(account_name))
        art_dir = os.path.join(acc_dir, _folder)
        os.makedirs(art_dir, exist_ok=True)
        html_path = os.path.join(art_dir, _folder + ".html")
        if not fetch_article(link, html_path):
            return None, "HTML 保存失败"
        img_n = localize_article_images(html_path)
        return html_path, f"已保存: {html_path} (图片{img_n}张)"
    except Exception as e:
        return None, f"保存HTML失败: {e}"


def _extract_account_name(link):
    """从文章链接推断公众号名称(meta og:site_name?) 失败返回 None"""
    try:
        import requests
        headers = {"User-Agent": "Mozilla/5.0", "Referer": "https://mp.weixin.qq.com/"}
        html = requests.get(link, headers=headers, timeout=15).text
        m = re.search(r'<meta[^>]+property=["\']og:site_name["\'][^>]+content=["\']([^"\']+)', html)
        if m:
            return m.group(1).strip()
        m = re.search(r'<meta[^>]+name=["\']author["\'][^>]+content=["\']([^"\']+)', html)
        if m:
            return m.group(1).strip()
    except Exception:
        pass
    return None
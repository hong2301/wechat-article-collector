# -*- coding: utf-8 -*-
from ..core import logkit

log = logkit.get_logger("collect.fetch")   # 网络抓取失败日志

import hashlib
import html as html_lib
import os
"""文章元信息抓取: 输入微信文章链接, 提取 标题/发布时间/是否原创/IP属地/公众号名
来自旧程序 core/utils.py 的 fetch_article, 新后端独立版本(不依赖老目录)。

核心:
  fetch_article(url)          兼容旧接口: 返回 (标题, 发布时间, 是否原创, IP属地)
  fetch_article_full(url)     完整数据 dict(含公众号名/标题/日期/原创/ip/html)
  save_article_html(link)     独立保存本地HTML(公众号分类目录, 含图片), 只需链接
"""
import re
import shutil
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
    except Exception as e:
        log.warning("[fetch] 文章解析失败 %.60s: %s", url, e)
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
    - 图片存入 html 同目录 images/; 全局缓存(asset_cache, 按URL hash) + 并发下载
    - 顺带把协议相对 URL(//xxx) 补全为 https:// (file:// 下必需)
    返回: 处理成功的图片数"""
    if not os.path.isfile(html_path):
        return 0
    try:
        import requests
        from concurrent.futures import ThreadPoolExecutor
        html = open(html_path, encoding="utf-8").read()
        # file:// 下协议相对 URL(//xxx) 会变成 file://xxx 全部失效 -> 补全为 https://
        html = html.replace('"//', '"https://').replace("'//", "'https://").replace("(//", "(https://")
        # 收集: img属性(src/data-src) + JS字符串里的微信图片URL(https与JSON转义形态都覆盖)
        _urls = list(re.findall(r'(?:data-src|src)="([^"]+)"', html))
        for _m in re.finditer(r'https?:[^"\'<>]+', html):
            _u0 = _m.group(0)
            if _u0 not in _urls:
                _urls.append(_u0)
        imgs = []
        for _u in _urls:
            _uu = _u
            if chr(92) + "/" in _uu:
                _uu = _uu.replace(chr(92) + "/", "/")     # JS JSON 转义 \/ -> /
            if "res.wx.qq.com" in _uu and not _uu.lower().endswith((".jpg", ".jpeg", ".png", ".gif", ".webp")):
                continue            # 微信静态资源(js/css)绝不处理
            if ("mmbiz" in _uu or "wx_fmt=" in _uu
                    or _uu.lower().endswith((".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"))) and _u not in imgs:
                imgs.append(_u)      # 保留原文形态(JS里可能带 \/ 转义), 替换用原文
        if not imgs:
            return 0
        img_dir = os.path.join(os.path.dirname(html_path), "images")
        os.makedirs(img_dir, exist_ok=True)
        cache = os.path.join(default_html_dir(), "..", "asset_cache")
        try:
            os.makedirs(cache, exist_ok=True)
        except Exception:
            cache = img_dir
        headers = {"User-Agent": "Mozilla/5.0",
                   "Referer": "https://mp.weixin.qq.com/"}

        def _ext_of(u):
            e = os.path.splitext(u.split("?")[0])[1].lower()
            if not e or len(e) > 5:
                m = re.search(r"wx_fmt=([a-zA-Z]+)", u)
                e = "." + m.group(1).lower() if m else ".jpg"
            return e

        def _one(u):
            """下载单张(缓存优先); 返回 (原文URL, 文件名, 是否成功)"""
            fu = u.replace(chr(92) + "/", "/")
            if fu.startswith("//"):
                fu = "https:" + fu
            fn = hashlib.md5(u.encode()).hexdigest()[:8] + _ext_of(fu)
            fp = os.path.join(img_dir, fn)
            if os.path.isfile(fp):
                return (u, fn, True)
            src = os.path.join(cache, fn)
            if os.path.isfile(src):
                try:
                    shutil.copy2(src, fp)
                    return (u, fn, True)
                except Exception:
                    pass
            try:
                r = requests.get(fu, headers=headers, timeout=timeout)
                if r.status_code != 200:
                    return (u, fn, False)
                if not (r.headers.get("Content-Type") or "").lower().startswith("image"):
                    return (u, fn, False)
                with open(src, "wb") as f:
                    f.write(r.content)
                shutil.copy2(src, fp)
                return (u, fn, True)
            except Exception as e:
                log.debug("[fetch] 图片下载失败 %s: %s", u[:70], e)
                return (u, fn, False)

        todo = [u for u in imgs if not u.startswith("images/")]
        seen = set()
        jobs = []
        for u in todo:
            if u in seen:
                continue
            seen.add(u)
            jobs.append(u)
        with ThreadPoolExecutor(max_workers=8) as ex:
            results = list(ex.map(_one, jobs))
        n = 0
        fail = 0
        for u, fn, ok in results:
            if ok:
                html = html.replace(u, "images/" + fn)
                n += 1
            else:
                fail += 1
        if n:
            # data-src 强制覆盖到 src(style 里可能有 src= 字样导致误判已有; 本地化后 data-src 必是本地文件)
            def _copy_src(m):
                a, d, c = m.group(1), m.group(2), m.group(3)
                if d.startswith(("images/", "assets/", "./")):
                    return '<img %(a)ssrc="%(d)s" data-src="%(d)s"%(c)s>' % {
                        "a": a, "d": d, "c": c}
                return m.group(0)
            html = re.sub(r'<img\s+([^>]*?)data-src="([^"]+)"([^>]*?)>', _copy_src, html)
            with open(html_path, "w", encoding="utf-8") as f:
                f.write(html)
        if fail:
            log.info("[fetch] 图片本地化: 成功%d张, 失败%d张 (共%d)", n, fail, n + fail)
        return n
    except Exception as e:
        log.warning("[fetch] 图片本地化异常: %s", e)
        return 0


def localize_static_resources(html_path, timeout=20):
    """把微信静态资源(res.wx.qq.com 的 JS/CSS/图片/字体等)下载到本地 assets/, 实现完全离线打开
    - 仅处理静态资源域名且无查询参数的 URL; 接口类(带?)跳过; 图片已由 images/ 阶段替换
    - 全局缓存 + 并发下载
    返回: 处理成功的资源数"""
    if not os.path.isfile(html_path):
        return 0
    try:
        import requests
        from concurrent.futures import ThreadPoolExecutor
        html = open(html_path, encoding="utf-8").read()
        assets = os.path.join(os.path.dirname(html_path), "assets")
        os.makedirs(assets, exist_ok=True)
        cache = os.path.join(default_html_dir(), "..", "asset_cache")
        try:
            os.makedirs(cache, exist_ok=True)
        except Exception:
            cache = assets
        headers = {"User-Agent": "Mozilla/5.0",
                   "Referer": "https://mp.weixin.qq.com/"}
        urls = re.findall(r'https?://[^"\s<>]+', html)
        targets = []
        seen = set()
        for u in urls:
            u = u.rstrip(",.;)")
            if "?" in u:
                continue                    # 接口/动态请求 -> 不下载(离线失败也不影响渲染)
            if "res.wx.qq.com" not in u or "mp.weixin.qq.com" in u:
                continue                    # 只处理微信静态资源域(渲染必需的 JS/CSS/字体/图)
            if u in seen:
                continue
            seen.add(u)
            targets.append(u)
        if not targets:
            return 0

        def _ext_of(u):
            e = os.path.splitext(u.split("?")[0])[1].lower()
            return e if (e and len(e) <= 8) else ".bin"

        def _one(u):
            fn = hashlib.md5(u.encode()).hexdigest()[:10] + _ext_of(u)
            fp = os.path.join(assets, fn)
            if os.path.isfile(fp):
                return (u, fn, True)
            src = os.path.join(cache, fn)
            if os.path.isfile(src):
                try:
                    shutil.copy2(src, fp)
                    return (u, fn, True)
                except Exception:
                    pass
            try:
                fu = u.replace(chr(92) + "/", "/")     # JS JSON 转义 \/ -> /
                r = requests.get(fu, headers=headers, timeout=timeout)
                if r.status_code != 200:
                    return (u, fn, False)
                ct = (r.headers.get("Content-Type") or "").lower()
                if not ct.startswith(("image", "text", "application", "font", "audio")):
                    return (u, fn, False)
                with open(src, "wb") as f:
                    f.write(r.content)
                shutil.copy2(src, fp)
                return (u, fn, True)
            except Exception as e:
                log.debug("[fetch] 静态资源下载失败 %s: %s", u[:70], e)
                return (u, fn, False)

        with ThreadPoolExecutor(max_workers=8) as ex:
            results = list(ex.map(_one, targets))
        n = 0
        fail = 0
        for u, fn, ok in results:
            if ok:
                html = html.replace(u, "assets/" + fn)
                n += 1
            else:
                fail += 1
        if n:
            with open(html_path, "w", encoding="utf-8") as f:
                f.write(html)
            log.info("[fetch] 静态资源本地化: 成功%d个, 失败%d个 -> assets/", n, fail)
        return n
    except Exception as e:
        log.warning("[fetch] 静态资源本地化异常: %s", e)
        return 0


def offline_placeholder(html_path):
    """残留外链 URL 全量消杀 -> 打开 html 零外网请求(手写扫描, 零正则零字面转义):
    - mp.weixin.qq.com / res.wx.qq.com -> 本地回环(快速失败, 不发外网)
    - mmbiz.qpic.cn(残留=下载失败) -> data:1px 占位(JS 转义形态 https:\/\/ 也覆盖)"""
    if not os.path.isfile(html_path):
        return
    try:
        html = open(html_path, encoding="utf-8").read()
        orig = html
        _lo = "https://127.0.0.1/offline/"
        _px = "data:image/gif;base64,R0lGODlhAQABAAAAACw="
        html = html.replace("https://mp.weixin.qq.com/", _lo)
        html = html.replace("https://res.wx.qq.com/", _lo)
        html = html.replace("http://mp.weixin.qq.com/", _lo)
        html = html.replace("http://mmbiz.qpic.cn/", _px)
        html = html.replace("https://wx.qlogo.cn/", _px)
        html = html.replace("https://wxsnsdythumb.wxs.qq.com/", _px)
        html = html.replace("https://badjs.weixinbridge.com/", _lo)
        html = html.replace("http://wx.qlogo.cn/", _px)
        html = html.replace("http://ad.wx.com:12638/", _lo)
        html = html.replace("http://wxsnsdythumb.wxs.qq.com/", _px)
        html = html.replace("http://badjs.weixinbridge.com/", _lo)
        html = html.replace("https://ad.wx.com:12638/", _lo)
        html = html.replace("https://open.weixin.qq.com/", _lo)
        _bs = chr(92)
        # mmbiz 整 URL 扫描删除(正常与 JS 转义两种前缀)
        for _pfx in ("https://mmbiz.qpic.cn/", "https:" + _bs + "/" + _bs + "/mmbiz.qpic.cn" + _bs + "/"):
            i = 0
            n = len(html)
            out = []
            while i < n:
                k = html.find("mmbiz.qpic.cn" + _bs + "/" if _bs + "/" in _pfx else "mmbiz.qpic.cn/", i)
                if k == -1:
                    out.append(html[i:])
                    break
                s0 = k - len(_pfx)
                if s0 >= 0 and html[s0:k] == _pfx:
                    out.append(html[i:s0] + _px)
                else:
                    out.append(html[i:k])
                # 找 URL 结束(引号/空白/尖括号)
                j = n
                for ch in (chr(34), chr(39), chr(32), chr(60), chr(62), chr(10), chr(13)):
                    p = html.find(ch, k)
                    if p != -1 and p < j:
                        j = p
                i = j if j < n else n
            html = "".join(out)
        if html != orig:
            with open(html_path, "w", encoding="utf-8") as f:
                f.write(html)
            log.info("[fetch] 残留URL消杀完成")
        # ---- 扩展到 assets/*.js|css 内容(微信JS内置上报/接口也在里面) ----
        orig2 = html
        _bs2 = chr(92)
        _asi = os.path.join(os.path.dirname(html_path), "assets")
        if os.path.isdir(_asi):
            for _fn in os.listdir(_asi):
                if not _fn.endswith((".js", ".css")):
                    continue
                _fp = os.path.join(_asi, _fn)
                try:
                    _tx = open(_fp, encoding="utf-8", errors="ignore").read()
                except Exception:
                    continue
                _o = _tx
                _tx = _tx.replace("https://badjs.weixinbridge.com/", _lo)
                _tx = _tx.replace("http://badjs.weixinbridge.com/", _lo)
                _tx = _tx.replace("https://mp.weixin.qq.com/mp/", _lo)
                _tx = _tx.replace("https://open.weixin.qq.com/", _lo)
                _tx = _tx.replace(_bs2 + "/mp" + _bs2 + "/", _bs2 + "/offline" + _bs2 + "/")  # 转义 \/mp\/
                _tx = _tx.replace('"/mp/', '"/offline/').replace("'/mp/", "'/offline/")
                if _tx != _o:
                    with open(_fp, "w", encoding="utf-8") as f:
                        f.write(_tx)
        # html 里的根相对 /mp/ 接口(JS字符串) -> 本地回环
        html = html.replace('"/mp/', '"/offline/').replace("'/mp/", "'/offline/")
        html = html.replace(_bs2 + "/mp" + _bs2 + "/", _bs2 + "/offline" + _bs2 + "/")
        if html != orig2:
            with open(html_path, "w", encoding="utf-8") as f:
                f.write(html)
    except Exception as e:
        log.warning("[fetch] 残留URL消杀异常: %s", e)


def save_article_html(link, account_name="", base_dir=None, formats=None):
    """抓取文章并保存为本地HTML(含图片本地化), 按公众号分类存目录。
    只是链接即可: 公众号名/标题/日期都从链接抓取的数据里提取(account_name可选覆盖)。
    目录: <base_dir>/<公众号名>/<日期>_<标题>/<日期>_<标题>.html + images/
    参数:
      link         微信文章链接
      account_name 公众号名称(可选; 空则从链接抓取数据提取)
      base_dir     根目录(默认 <数据目录>/article_data)
      formats      保存格式列表 ["html","pdf","txt","md","word"];
                   None/空 = 仅 html(兼容旧行为); html 是中间产物, 其他格式由它转换
                   未选 html 时: 转换完成后删除 html + images/(md 选了则保留 mdimgs)
    返回: (主路径 或 None, 说明文本)  # 结构不变
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
        _img_exts = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".svg", ".ico")
        img_n = 0
        static_n = 0
        # 完全离线本地化: 原始html + 图片(images/) + 静态资源(assets/) 全下载并改写引用
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(data["html"])
        img_n = localize_article_images(html_path)
        static_n = localize_static_resources(html_path)
        offline_placeholder(html_path)      # 残留接口URL -> 本地占位(彻底无外网请求)
        # ---- 多格式转换: html 是中间产物 ----
        fmts = [str(x).strip().lower() for x in (formats or []) if str(x).strip()]
        keep_html = (not fmts) or ("html" in fmts)
        others = [x for x in fmts if x != "html"]
        conv = {}
        if others:
            from .article_formats import convert_html, cleanup_html
            conv = convert_html(html_path, others)
            if not keep_html:
                cleanup_html(html_path, keep_md_imgs=("md" in others))
        # 主路径: 选html=html路径; 否则第一个格式的产物路径
        if keep_html:
            main = html_path
        else:
            main = conv.get(others[0]) if others else None
        made = (["html"] if keep_html else []) + [f for f in others if f in conv]
        info = f"已保存: {main} | 格式: {','.join(made)} (图片{img_n}张, 资源{static_n}个)"
        return main, info
    except Exception as e:
        return None, f"保存HTML失败: {e}"
# -*- coding: utf-8 -*-
"""设置/系统控制路由: AI 模型、微信版本确认、任务栏、微信启动/登录检测"""
import logging

import os
import subprocess
import ctypes.wintypes as wt
import time as _time
import ctypes
from fastapi import APIRouter
from pydantic import BaseModel

from ..database import default_html_dir
from ..core import computer as pc
from ..core import logkit
from ..version_info import APP_VERSION, WECHAT_VERSION  # 硬编码版本(构建时由 .env 注入)
from ..services import wechat_check as wx_check
from ..repositories import settings_repo

router = APIRouter(prefix="/api/settings", tags=["settings"])
log = logkit.get_logger("api.settings")   # 接口业务日志 -> api.log


class AiSettings(BaseModel):
    provider: str = "doubao"          # 厂商
    api_key: str = ""                 # key(一个)
    models: list[str] = []            # 多个模型id


@router.get("/wechat-version")
def get_wechat_version():
    """读微信基准版本(硬编码内置, 不再存数据库)"""
    log.info("[settings.wechat-version] 返回 %s", WECHAT_VERSION)
    return {"version": WECHAT_VERSION}


@router.get("/wechat-check")
def wechat_check_api():
    """微信版本确认: 读本地版本 + 网络试探更高版本(内置硬编码基准)
    返回 {db, local, online}"""
    r = wx_check.check(WECHAT_VERSION)
    log.info("[settings.wechat-check] local=%s online=%s", r.get("local"), r.get("online"))
    return r


@router.get("/ai")
def get_ai_settings():
    log.info("[settings.ai] 读取AI配置")
    return settings_repo.get_ai()


@router.post("/ai")
def save_ai_settings(payload: AiSettings):
    """保存: 清空旧记录, 写入 (provider, api_key, 每个model_id) 一行一条"""
    n = settings_repo.save_ai(payload.provider, payload.api_key, payload.models)
    log.info("[settings.ai] 保存 provider=%s models=%s (api_key不落日志)", payload.provider, payload.models)
    return {"ok": True, "count": n}


@router.get("/save-dir")
def get_save_dir():
    """读取存储路径(settings 表 save_dir)"""
    from ..repositories.settings_repo import get_setting
    d = get_setting("save_dir")
    log.info("[settings.save-dir] 读取: %r", d)
    return {"dir": d}


@router.post("/save-dir")
def save_dir_api(payload: dict = None):
    """保存存储路径到数据库(settings 表 save_dir)"""
    from ..repositories.settings_repo import set_setting
    p = payload or {}
    d = (p.get("dir") or "").strip()
    set_setting("save_dir", d)
    log.info("[settings.save-dir] 保存: %r", d)
    return {"ok": True, "dir": d}


@router.post("/open-downloads")
def open_downloads(sub: str = ""):
    """打开文章下载文件夹(默认 <数据目录>/article_data), sub给定公众号名则打开对应子文件夹
    不存在则创建"""
    d = default_html_dir()
    if sub:
        d = os.path.join(d, sub)
    try:
        os.makedirs(d, exist_ok=True)
        os.startfile(d)
        log.info("[settings.open-downloads] 打开: %s", d)
        return {"ok": True, "dir": d}
    except Exception as e:
        log.error("[settings.open-downloads] %s 打开失败: %s", d, e)
        return {"ok": False, "error": str(e)}


@router.post("/article-files")
def article_files(payload: dict = None):
    """查看某文章已保存的文件: 打开其文件夹, 扫描实际格式(有变化则更新 articles.saved_formats)
    payload: {art_biz, biz?, name?, title?, date?}  (name/title/date 缺省从库补齐)
    返回: {ok, dir, formats: [...], saved_formats, changed}"""
    from ..repositories import accounts_repo
    from ..services.fetch_article import clean_filename, default_html_dir
    p = payload or {}
    art_biz = (p.get("art_biz") or "").strip()
    if not art_biz:
        log.warning("[settings.article-files] 缺少 art_biz")
        return {"ok": False, "error": "缺少 art_biz"}
    biz = (p.get("biz") or "").strip()
    name = (p.get("name") or "").strip()
    title = (p.get("title") or "").strip()
    date = (p.get("date") or "").strip()
    row = None
    if not (name and title and date):
        row = accounts_repo.article_get(art_biz, biz)
        if row:
            name = name or (row.get("name") or "")
            title = title or (row.get("title") or "")
            date = date or (row.get("date") or "")
    if not (name and title):
        log.warning("[settings.article-files] 无法定位文件夹 art=%.16s name=%r title=%r", art_biz, name, title)
        return {"ok": False, "error": "无法定位文章文件夹(缺少公众号名/标题)"}
    folder = f"{date[:10]}_{clean_filename(title)}" if date else clean_filename(title)
    d = os.path.join(default_html_dir(), clean_filename(name), folder)
    if not os.path.isdir(d):
        log.info("[settings.article-files] 尚未保存 art=%.16s dir=%s", art_biz, d)
        return {"ok": False, "error": "该文章还没有保存过本地文件"}
    # 扫描顶层文件格式(不含 images/mdimgs 子目录)
    _ext = {".html": "html", ".pdf": "pdf", ".txt": "txt", ".md": "md", ".docx": "word", ".doc": "word"}
    _order = ["html", "pdf", "txt", "md", "word"]
    found = []
    try:
        for fn in os.listdir(d):
            if not os.path.isfile(os.path.join(d, fn)):
                continue
            fmt = _ext.get(os.path.splitext(fn)[1].lower())
            if fmt and fmt not in found:
                found.append(fmt)
    except Exception as e:
        log.error("[settings.article-files] 扫描失败 %s: %s", d, e)
        return {"ok": False, "error": f"扫描失败: {e}"}
    found.sort(key=lambda x: _order.index(x) if x in _order else 99)
    old = (row.get("saved_formats") or "") if row else accounts_repo.article_saved_formats(art_biz, biz)
    # 以实际扫描为准覆盖写(文件删光也清空); 无变化则不写
    if ",".join(found) != (old or ""):
        saved = accounts_repo.article_set_saved_formats(art_biz, found, biz)
        changed = True
    else:
        saved = old
        changed = False
    try:
        os.startfile(d)
    except Exception as e:
        log.error("[settings.article-files] 打开失败 %s: %s", d, e)
        return {"ok": False, "error": f"打开文件夹失败: {e}"}
    log.info("[settings.article-files] art=%.16s dir=%s 格式=%s 变化=%s", art_biz, d, found, changed)
    return {"ok": True, "dir": d, "formats": found, "saved_formats": saved, "changed": changed}


@router.post("/pick-dir")
def pick_dir(current: str = ""):
    """弹系统文件夹选择器(initialdir=当前保存路径), 返回选中的目录; 取消返回空"""
    import tkinter as tk
    from tkinter import filedialog
    if not current or not os.path.isdir(current):
        current = default_html_dir()
    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    try:
        chosen = filedialog.askdirectory(initialdir=current, title="选择保存HTML的根目录")
    finally:
        root.destroy()
    log.info("[settings.pick-dir] %s -> %s", current, chosen or "(取消)")
    return {"ok": True, "dir": chosen or ""}


@router.post("/save-article-html")
def save_article_html_api(payload: dict = None):
    """保存单篇文章(公众号分类目录, 含图片);
    payload: {link, account_name, base_dir, formats=["html","pdf","txt","md","word"]}
    formats 为空/缺省 = 仅 html(兼容旧行为)"""
    from ..services.fetch_article import save_article_html
    p = payload or {}
    link = (p.get("link") or "").strip()
    fmts = p.get("formats")
    fmts = [str(x) for x in fmts if str(x).strip()] if isinstance(fmts, list) and fmts else None
    if not link:
        log.warning("[settings.save-article-html] 缺少链接")
        return {"ok": False, "error": "缺少链接"}
    path, info = save_article_html(link, account_name=(p.get("account_name") or ""),
                                   base_dir=(p.get("base_dir") or None), formats=fmts)
    if path:
        log.info("[settings.save-article-html] 保存成功 account=%s formats=%s link=%.40s",
                 p.get("account_name") or "", fmts or ["html"], link)
        # 文章"文件保存"列: 下载时更新(合并已有)
        saved = ""
        _art = (p.get("art_biz") or "").strip()
        if _art:
            from ..repositories import accounts_repo
            saved = accounts_repo.article_merge_saved_formats(_art, fmts or ["html"], (p.get("biz") or "").strip())
        return {"ok": True, "path": path, "info": info, "saved_formats": saved}
    log.warning("[settings.save-article-html] 保存失败: %.60s", info)
    return {"ok": False, "error": info}






@router.post("/launch-wechat")
def launch_wechat():
    """未登录时点击微信图标: 启动微信程序(登录窗口)"""
    candidates = [
        r"D:\Weixin\Weixin.exe",
        r"C:\Program Files\Tencent\WeChat\Weixin.exe",
        r"C:\Program Files (x86)\Tencent\WeChat\Weixin.exe",
        r"D:\Program Files\Tencent\WeChat\Weixin.exe",
    ]
    for p in candidates:
        if os.path.isfile(p):
            try:
                subprocess.Popen([p], close_fds=True)
                log.info("[settings.launch-wechat] 启动微信: %s", p)
                return {"ok": True, "path": p}
            except Exception as e:
                log.error("[settings.launch-wechat] %s 启动失败: %s", p, e)
                return {"ok": False, "error": f"启动失败: {e}"}
    log.warning("[settings.launch-wechat] 未找到微信安装路径")
    return {"ok": False, "error": "未找到微信安装路径"}




def _wx_win_width_check():
    """窗口宽度判定: 找可见的微信主窗口(进程 weixin.exe 且标题含'微信')移到左半屏,
    量宽(≥半屏90%=已登录主窗, 登录窗被微信限小)"""
    from ..services import tasks as tasks_svc
    u32 = pc._u32()
    sw = u32.GetSystemMetrics(pc.SM_CXSCREEN)
    sh = u32.GetSystemMetrics(pc.SM_CYSCREEN)
    half = sw // 2
    logged = False
    # 只认微信主窗口: weixin.exe 且标题含"微信"(排除设置/聊天窗等)
    wins = pc.find_windows(exe=tasks_svc.WECHAT_MAIN, visible_only=True)
    wins = [w for w in wins if (w[1] or "").strip() == "微信" or "微信" in (w[1] or "")]
    logging.getLogger().info(f"[wxcheck] 可见微信窗口数={len(wins)} 半屏宽={half}")
    for hwnd, _t, _p, _vis in wins:
        pc.move_window(hwnd, 0, 0, half, sh)
        _time.sleep(0.3)
        r = wt.RECT()
        u32.GetWindowRect(hwnd, ctypes.byref(r))
        logging.getLogger().info(f"[wxcheck] 移动后宽={r.right - r.left} (需>={half * 0.9:.0f})")
        if r.right - r.left >= half * 0.9:
            logged = True
    logging.getLogger().info(f"[wxcheck] 判定 logged={logged}")
    return logged




def _detect_wx_status():
    from ..services import tasks as tasks_svc
    main = pc._pids_by_exe([tasks_svc.WECHAT_MAIN])
    if not main:
        _wx_confirm[0] = False
        return {"running": False, "logged_in": False}
    if _wx_confirm[0]:
        return {"running": True, "logged_in": True}
    now = _time.time()
    if _wx_last_win_check[0] == 0 or now - _wx_last_win_check[0] >= _WX_WIN_CHECK_INTERVAL:
        _wx_last_win_check[0] = now
        _wx_confirm[0] = _wx_win_width_check()
    return {"running": True, "logged_in": _wx_confirm[0]}


# ---- 微信登录状态: GET 实时计算(前端1s轮询; 无长连接, Ctrl+C 秒退优雅) ----
_wx_confirm = [False]
_wx_last_win_check = [0.0]
_WX_WIN_CHECK_INTERVAL = 1.0      # 未确认登录时每1秒窗口移动+量宽; 确认后纯进程检测零打扰


@router.get("/app-version")
def app_version():
    """程序版本: 硬编码内置常量(构建时由根 .env APP_VERSION 注入, 打包/开发一致)"""
    log.info("[settings.app-version] 返回 %s", APP_VERSION)
    return {"version": APP_VERSION}


@router.get("/wechat-status")
def wechat_status():
    """微信登录状态(前端1s轮询): 实时计算"""
    return _detect_wx_status()
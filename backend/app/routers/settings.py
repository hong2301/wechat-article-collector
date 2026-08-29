# -*- coding: utf-8 -*-
"""设置/系统控制路由: AI 模型、微信版本确认、任务栏、微信启动/登录检测"""
import os
import subprocess
import ctypes.wintypes as wt
import time as _time
import ctypes
from fastapi import APIRouter
from pydantic import BaseModel

from ..database import default_html_dir
from ..core import computer as pc
from ..services import wechat_check as wx_check
from ..repositories import settings_repo

router = APIRouter(prefix="/api/settings", tags=["settings"])


class AiSettings(BaseModel):
    provider: str = "doubao"          # 厂商
    api_key: str = ""                 # key(一个)
    models: list[str] = []            # 多个模型id


class WechatVersion(BaseModel):
    version: str = ""                 # 微信基准版本号


@router.get("/wechat-version")
def get_wechat_version():
    """读微信基准版本(数据库存储值); 未设置返回空"""
    return {"version": settings_repo.get_setting("wechat_version")}


@router.get("/wechat-check")
def wechat_check_api():
    """微信版本确认: 读本地版本 + 网络试探更高版本(数据库版本为准)
    返回 {db, local, online}"""
    return wx_check.check(settings_repo.get_setting("wechat_version"))


@router.post("/wechat-version")
def save_wechat_version(p: WechatVersion):
    """保存微信基准版本"""
    v = (p.version or "").strip()
    if not v:
        return {"ok": False, "error": "版本号不能为空"}
    settings_repo.set_setting("wechat_version", v)
    return {"ok": True, "version": v}


@router.get("/ai")
def get_ai_settings():
    return settings_repo.get_ai()


@router.post("/ai")
def save_ai_settings(payload: AiSettings):
    """保存: 清空旧记录, 写入 (provider, api_key, 每个model_id) 一行一条"""
    n = settings_repo.save_ai(payload.provider, payload.api_key, payload.models)
    return {"ok": True, "count": n}


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
        return {"ok": True, "dir": d}
    except Exception as e:
        return {"ok": False, "error": str(e)}


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
    return {"ok": True, "dir": chosen or ""}


@router.post("/save-article-html")
def save_article_html_api(payload: dict = None):
    """保存单篇文章为本地HTML(公众号分类目录, 含图片); payload: {link, account_name, base_dir}"""
    from ..services.fetch_article import save_article_html
    p = payload or {}
    link = (p.get("link") or "").strip()
    if not link:
        return {"ok": False, "error": "缺少链接"}
    path, info = save_article_html(link, account_name=(p.get("account_name") or ""),
                                   base_dir=(p.get("base_dir") or None))
    if path:
        return {"ok": True, "path": path, "info": info}
    return {"ok": False, "error": info}


class TaskbarAction(BaseModel):
    action: str = "hide"   # hide / show


@router.post("/taskbar")
def taskbar_control(p: TaskbarAction):
    """隐藏/恢复 Windows 任务栏(采集开始隐藏, 全部任务结束恢复); 幂等"""
    if p.action == "hide":
        return {"ok": pc.hide_taskbar()}
    if p.action == "show":
        return {"ok": pc.show_taskbar()}
    return {"ok": False, "error": "action 只能是 hide/show"}





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
                return {"ok": True, "path": p}
            except Exception as e:
                return {"ok": False, "error": f"启动失败: {e}"}
    return {"ok": False, "error": "未找到微信安装路径"}




def _wx_win_width_check():
    """窗口宽度判定: 将可见微信窗口移到左半屏, 量宽(≥半屏90%=已登录主窗, 登录窗被微信限小)"""
    from ..services import tasks as tasks_svc
    u32 = pc._u32()
    sw = u32.GetSystemMetrics(pc.SM_CXSCREEN)
    sh = u32.GetSystemMetrics(pc.SM_CYSCREEN)
    half = sw // 2
    logged = False
    wins = pc.find_windows(exe=tasks_svc.WECHAT_MAIN, visible_only=True)
    print(f"[wxcheck] 可见微信窗口数={len(wins)} 半屏宽={half}", flush=True)
    for hwnd, _t, _p, _vis in wins:
        pc.move_window(hwnd, 0, 0, half, sh)
        _time.sleep(0.3)
        r = wt.RECT()
        u32.GetWindowRect(hwnd, ctypes.byref(r))
        print(f"[wxcheck] 移动后宽={r.right - r.left} (需>={half * 0.9:.0f})", flush=True)
        if r.right - r.left >= half * 0.9:
            logged = True
    print(f"[wxcheck] 判定 logged={logged}", flush=True)
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


@router.get("/wechat-status")
def wechat_status():
    """微信登录状态(前端1s轮询): 实时计算"""
    return _detect_wx_status()
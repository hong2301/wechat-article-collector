# -*- coding: utf-8 -*-
"""AI 模型设置路由: 读写数据库 ai_model 表(厂商+一个key+多个模型id)
+ 系统控制: 任务栏隐藏/恢复(采集时隐藏, 全部结束恢复)"""
from fastapi import APIRouter, Request
from pydantic import BaseModel

from ..database import get_conn, default_html_dir
from ..services import computer as pc

router = APIRouter(prefix="/api/settings", tags=["settings"])

# 默认可用配置(用户未设置时前端使用)
DEFAULT_API_KEY = "802ffe3f-4bc9-4030-a3f4-cc00409a4d4e"
DEFAULT_MODEL = "doubao-seed-2-0-mini-260428"


class AiSettings(BaseModel):
    provider: str = "doubao"          # 厂商
    api_key: str = ""                 # key(一个)
    models: list[str] = []            # 多个模型id


@router.get("/ai")
def get_ai_settings():
    """返回 {provider, api_key, models:[...]}; 无数据则空"""
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT provider, api_key, model_id FROM ai_model ORDER BY id").fetchall()
    finally:
        conn.close()
    if not rows:
        return {"provider": "doubao", "api_key": "", "models": []}
    first = dict(rows[0])
    models = [dict(r)["model_id"] for r in rows]
    return {"provider": first["provider"], "api_key": first["api_key"],
            "models": models}


@router.post("/ai")
def save_ai_settings(payload: AiSettings):
    """保存: 清空旧记录, 写入 (provider, api_key, 每个model_id) 一行一条"""
    conn = get_conn()
    try:
        conn.execute("DELETE FROM ai_model")
        api_key = payload.api_key or ""
        provider = payload.provider or "doubao"
        models = payload.models or []
        for m in models:
            conn.execute(
                "INSERT INTO ai_model(provider, api_key, model_id) VALUES(?,?,?)",
                (provider, api_key, m))
        conn.commit()
        return {"ok": True, "count": len(models)}
    finally:
        conn.close()


@router.post("/open-downloads")
def open_downloads(sub: str = ""):
    """打开文章下载文件夹(默认 <数据目录>/article_data), sub给定公众号名则打开对应子文件夹
    不存在则创建"""
    import os
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
    import os
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
    import os
    import subprocess
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


# 微信登录确认态: 确认过登录后只做进程监控(不再操作窗口)
_wx_confirm = [False]          # 是否已通过窗口宽度验证登录
_wx_last_win_check = [0.0]     # 上次窗口验证时间(未确认时降频到30s一次, 避免频繁移动窗口)
_WX_WIN_CHECK_INTERVAL = 30.0


def _wx_win_width_check():
    """窗口宽度判定: 将可见微信窗口移到左半屏, 量宽(≥半屏90%=已登录主窗, 登录窗被微信限小)"""
    import time as _time
    import ctypes
    import ctypes.wintypes as wt
    from ..services import tasks as tasks_svc
    u32 = pc._u32()
    sw = u32.GetSystemMetrics(pc.SM_CXSCREEN)
    sh = u32.GetSystemMetrics(pc.SM_CYSCREEN)
    half = sw // 2
    logged = False
    for hwnd, _t, _p, _vis in pc.find_windows(exe=tasks_svc.WECHAT_MAIN, visible_only=True):
        pc.move_window(hwnd, 0, 0, half, sh)
        _time.sleep(0.3)
        r = wt.RECT()
        u32.GetWindowRect(hwnd, ctypes.byref(r))
        if r.right - r.left >= half * 0.9:
            logged = True
    return logged


@router.get("/wechat-status")
def wechat_status():
    """微信登录状态(前端状态灯轮询):
    - 已确认登录: 只监控 Weixin 主进程是否还在(不再操作窗口/不管可见)
    - 未确认: 每 30s 才做一次窗口宽度判定(登录后转为进程监控)"""
    import time as _time
    from ..services import tasks as tasks_svc
    main = pc._pids_by_exe([tasks_svc.WECHAT_MAIN])
    if not main:
        _wx_confirm[0] = False                 # 主进程消失 -> 失效, 下次需重新窗口验证
        return {"running": False, "logged_in": False}
    if _wx_confirm[0]:
        return {"running": True, "logged_in": True}
    # 未确认: 降频窗口判定(30s一次)
    now = _time.time()
    if now - _wx_last_win_check[0] >= _WX_WIN_CHECK_INTERVAL:
        _wx_last_win_check[0] = now
        _wx_confirm[0] = _wx_win_width_check()
    return {"running": True, "logged_in": _wx_confirm[0]}

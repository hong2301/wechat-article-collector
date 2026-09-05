# -*- coding: utf-8 -*-
"""微信版本确认: 读本地微信版本 + 网络试探是否存在更高版本
- local: 读本地 Weixin.exe 文件版本(ctypes 调 version.dll, 无第三方依赖)
- online: 以数据库版本前3段+1 试探微信官网更新页(200=存在该版本, 404=没有)
"""
import ctypes
import os
import subprocess
import urllib.request
from ctypes import wintypes

# 微信 exe 候选进程名(新版 Weixin, 旧版 WeChat)
_PROC_NAMES = ("Weixin.exe", "WeChat.exe")

# 常见安装路径兜底
_PATHS = (
    "D:\\Weixin\\Weixin.exe",
    "C:\\Program Files\\Tencent\\WeChat\\WeChat.exe",
    "C:\\Program Files (x86)\\Tencent\\WeChat\\WeChat.exe",
    "C:\\Program Files\\Tencent\\Weixin\\Weixin.exe",
    "C:\\Program Files (x86)\\Tencent\\Weixin\\Weixin.exe",
    "C:\\Program Files\\Tencent\\WeChat\\Weixin.exe",
    "C:\\Program Files (x86)\\Tencent\\WeChat\\Weixin.exe",
)

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")


class VS_FIXEDFILEINFO(ctypes.Structure):
    _fields_ = [
        ("dwSignature", wintypes.DWORD),
        ("dwStrucVersion", wintypes.DWORD),
        ("dwFileVersionMS", wintypes.DWORD),
        ("dwFileVersionLS", wintypes.DWORD),
        ("dwProductVersionMS", wintypes.DWORD),
        ("dwProductVersionLS", wintypes.DWORD),
        ("dwFileFlagsMask", wintypes.DWORD),
        ("dwFileFlags", wintypes.DWORD),
        ("dwFileOS", wintypes.DWORD),
        ("dwFileType", wintypes.DWORD),
        ("dwFileSubtype", wintypes.DWORD),
        ("dwFileDateMS", wintypes.DWORD),
        ("dwFileDateLS", wintypes.DWORD),
    ]


def find_wechat_path():
    """定位微信 exe: 优先从正在运行的进程拿路径, 否则常见安装路径"""
    try:
        cmd = ("(Get-Process " + ",".join(p[:-4] for p in _PROC_NAMES) +
               " -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty Path)")
        out = subprocess.run(["powershell", "-NoProfile", "-Command", cmd],
                             capture_output=True, text=True, timeout=10)
        p = (out.stdout or "").strip().strip('"')
        if p and os.path.isfile(p) and p.lower().endswith(".exe"):
            return p
    except Exception:
        pass
    for p in _PATHS:
        if os.path.isfile(p):
            return p
    return ""


def read_file_version(path):
    """读取 exe 文件版本(a.b.c.d); 失败返回空串"""
    if not path or not os.path.isfile(path):
        return ""
    try:
        size = ctypes.windll.version.GetFileVersionInfoSizeW(path, None)
        if size <= 0:
            return ""
        buf = ctypes.create_string_buffer(size)
        if not ctypes.windll.version.GetFileVersionInfoW(path, 0, size, buf):
            return ""
        info_ptr = ctypes.c_void_p()
        info_len = wintypes.UINT(0)
        if not ctypes.windll.version.VerQueryValueW(buf, "\\", ctypes.byref(info_ptr), ctypes.byref(info_len)):
            return ""
        fi = ctypes.cast(info_ptr, ctypes.POINTER(VS_FIXEDFILEINFO)).contents
        hi = fi.dwFileVersionMS
        lo = fi.dwFileVersionLS
        return "%d.%d.%d.%d" % (hi >> 16, hi & 0xFFFF, lo >> 16, lo & 0xFFFF)
    except Exception:
        return ""


def local_version():
    """读本地微信版本号; 找不到/失败返回空串"""
    return read_file_version(find_wechat_path())


def _online_exists(ver):
    """试探微信官网更新页某版本是否存在: 200=存在, 否则不存在"""
    url = f"https://weixin.qq.com/updates?platform=windows&version={ver}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _UA})
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status == 200
    except Exception:
        return False


def online_latest(db_version):
    """以数据库版本前3段+1 试探更高版本是否存在; 存在返回该版本, 否则空串
    例: db=4.1.13.12 -> 试探 4.1.14; 200 则返回 '4.1.14'"""
    parts = [p for p in str(db_version).split(".") if p.isdigit()]
    if len(parts) < 3 or parts[0] == "0":
        return ""
    base = f"{parts[0]}.{parts[1]}.{int(parts[2]) + 1}"
    return base if _online_exists(base) else ""


def check(db_version):
    """确认函数: 返回 {db, local, online}
    - db:     数据库记录的微信基准版本(原样)
    - local:  本地微信实际版本(空=未找到微信)
    - online: 网络存在的最新版本(空=当前第3段无更高版)"""
    return {
        "db": db_version,
        "local": local_version(),
        "online": online_latest(db_version),
    }
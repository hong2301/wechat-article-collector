# -*- coding: utf-8 -*-
"""
微信公众号OCR采集器 - 启动控制台（Windows，纯标准库实现）

界面布局:
    左侧 控制区(600)   : 控制台日志 + 采集控制（索引范围/时间范围/最大数量/开始/进度）
    右侧 任务区(1000)  : input 数据表格（每行可编辑、操作列删除、底部重置/新增）

用法:
    python main.py                  -> 正常模式（GUI）
    python main.py --ui-shot 图.png  -> 截图自检（1.5秒后截全屏并退出）

依赖:
    pip install rapidocr_onnxruntime requests Pillow

输入: input.csv  ->  索引,url,公众号名称,状态
记忆: ui_state.json（索引范围/时间范围/自定义日期/最大采集数量 自动保存）
"""

import calendar as _cal
import csv
import ctypes
import ctypes.wintypes as wt
import json
import os
import queue
import re
import sys
import threading
import time
import tkinter as tk
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta
from tkinter import messagebox, scrolledtext, ttk

APP_NAME = "微信公众号OCR采集器"
VERSION = "V1.1.7"
WECHAT_VERSION = "4.1.11.24"    # 依赖: 微信 PC 版版本

UI_LOG_HOOK = None          # GUI 日志回调
CONSOLE_PRINT = True        # 是否同时打印控制台

CONFIG_DIR = "config"
INPUT_CSV = "input.csv"
UI_STATE_FILE = "ui_state.json"
DATA_DIR = "data"   # 数据根目录（文章HTML + collected.csv）
COLLECTED_CSV = "collected.csv"   # 采集记录（公众号/日期/标题/链接/阅读/点赞/转发/喜欢/评论/写入时间）
COLLECTED_HEADER = ["公众号名称", "日期", "标题", "链接", "阅读", "点赞", "转发", "喜欢", "评论", "写入时间", "互动截图", "阅读截图"]

# ---------------- 时间范围选项 ----------------
TIME_OPTIONS = (
    ("all", "全部"),
    ("today", "当天"),
    ("week", "近一周"),
    ("month", "近一个月"),
    ("year", "近一年"),
    ("custom", "自定义"),
)
CUSTOM = "custom"


LOG_FILE = os.path.join(CONFIG_DIR, "log.txt")
_log_lock = threading.Lock()


def log(msg):
    """记录日志：控制台打印 + 写入 config/log.txt（每行带时间戳），GUI 控制台不带时间"""
    if CONSOLE_PRINT:
        try:
            print(msg, flush=True)
        except Exception:
            pass
    # 写入 config/log.txt（线程安全，带时间戳）
    try:
        with _log_lock:
            with open(os.path.join(_script_dir(), LOG_FILE), "a", encoding="utf-8") as f:
                f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n")
    except Exception:
        pass
    hook = UI_LOG_HOOK
    if hook is not None:
        try:
            hook(msg)
        except Exception:
            pass


def enable_dpi_awareness():
    """让坐标使用物理像素，避免 DPI 缩放导致点位偏移"""
    try:
        ctypes.WinDLL("shcore").SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.WinDLL("user32").SetProcessDPIAware()
        except Exception:
            pass


# ================= Win32 窗口操作（微信窗口查找/前置/半屏） =================
user32 = None
kernel32 = None

SW_RESTORE = 9
SW_HIDE = 0
SW_SHOW = 5
SM_CXSCREEN = 0
SM_CYSCREEN = 1
SWP_NOZORDER = 0x0004
SWP_FRAMECHANGED = 0x0020
SWP_NOMOVE = 0x0002
SWP_NOSIZE = 0x0001
SWP_SHOWWINDOW = 0x0040
SWP_NOACTIVATE = 0x0010
HWND_TOP = 0
HWND_TOPMOST = -1
HWND_NOTOPMOST = -2
VK_MENU = 0x12
KEYEVENTF_KEYUP = 0x0002
TH32CS_SNAPPROCESS = 0x00000002
WECHAT_MAIN_EXES = ("wechat.exe", "weixin.exe")
WH_KEYBOARD_LL = 13
WM_KEYDOWN = 0x0100
VK_ESCAPE = 0x1B
WM_MOUSEMOVE = 0x0200
WM_QUIT = 0x0012
WH_MOUSE_LL = 14
LLMHF_INJECTED = 0x00000001   # 鼠标消息注入标志（SendInput/mouse_event 产生）
LLKHF_INJECTED = 0x00000010   # 键盘消息注入标志（SendInput 产生）
WM_LBUTTONDOWN = 0x0201
WM_RBUTTONDOWN = 0x0204
SM_CXDOUBLECLK = 36
SM_CYDOUBLECLK = 37
HOOKPROC = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_int, wt.WPARAM, wt.LPARAM)


class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class MSLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [("pt", POINT), ("mouseData", wt.DWORD), ("flags", wt.DWORD),
                ("time", wt.DWORD), ("dwExtraInfo", ctypes.POINTER(wt.ULONG))]


# ---- 模拟输入（SendInput / mouse_event）结构 ----
class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wt.WORD), ("wScan", wt.WORD), ("dwFlags", wt.DWORD),
                ("time", wt.DWORD), ("dwExtraInfo", ctypes.POINTER(wt.ULONG))]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", ctypes.c_long), ("dy", ctypes.c_long),
                ("mouseData", wt.DWORD), ("dwFlags", wt.DWORD),
                ("time", wt.DWORD), ("dwExtraInfo", ctypes.POINTER(wt.ULONG))]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT)]


class INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", wt.DWORD), ("u", _INPUTUNION)]


INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_WHEEL = 0x0800
WHEEL_DELTA = 120
VK_CONTROL = 0x11
VK_SHIFT = 0x10
VK_RETURN = 0x0D
VK_DELETE = 0x2E


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [("vkCode", wt.DWORD), ("scanCode", wt.DWORD),
                ("flags", wt.DWORD), ("time", wt.DWORD),
                ("dwExtraInfo", ctypes.POINTER(wt.ULONG))]

WNDENUMPROC = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wt.DWORD),
        ("cntUsage", wt.DWORD),
        ("th32ProcessID", wt.DWORD),
        ("th32DefaultHeapID", ctypes.POINTER(wt.ULONG)),
        ("th32ModuleID", wt.DWORD),
        ("cntThreads", wt.DWORD),
        ("th32ParentProcessID", wt.DWORD),
        ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", wt.DWORD),
        ("szExeFile", ctypes.c_wchar * 260),
    ]


def _u32():
    global user32
    if user32 is None:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.EnumWindows.argtypes = [WNDENUMPROC, wt.LPARAM]
        user32.EnumWindows.restype = wt.BOOL
        user32.GetWindowThreadProcessId.argtypes = [wt.HWND, ctypes.POINTER(wt.DWORD)]
        user32.GetWindowThreadProcessId.restype = wt.DWORD
        user32.GetWindowTextW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
        user32.GetWindowTextW.restype = ctypes.c_int
        user32.IsWindowVisible.argtypes = [wt.HWND]
        user32.IsWindowVisible.restype = wt.BOOL
        user32.ShowWindow.argtypes = [wt.HWND, ctypes.c_int]
        user32.ShowWindow.restype = wt.BOOL
        user32.SetForegroundWindow.argtypes = [wt.HWND]
        user32.SetForegroundWindow.restype = wt.BOOL
        user32.SetWindowPos.argtypes = [wt.HWND, wt.HWND, ctypes.c_int, ctypes.c_int,
                                        ctypes.c_int, ctypes.c_int, wt.UINT]
        user32.SetWindowPos.restype = wt.BOOL
        user32.GetWindowRect.argtypes = [wt.HWND, ctypes.POINTER(wt.RECT)]
        user32.GetWindowRect.restype = wt.BOOL
        user32.GetSystemMetrics.argtypes = [ctypes.c_int]
        user32.GetSystemMetrics.restype = ctypes.c_int
        user32.keybd_event.argtypes = [wt.BYTE, wt.BYTE, wt.DWORD, ctypes.POINTER(wt.ULONG)]
        user32.keybd_event.restype = None
        user32.SetWindowsHookExW.argtypes = [ctypes.c_int, HOOKPROC, wt.HINSTANCE, wt.DWORD]
        user32.SetWindowsHookExW.restype = ctypes.c_void_p
        user32.CallNextHookEx.argtypes = [ctypes.c_void_p, ctypes.c_int, wt.WPARAM, wt.LPARAM]
        user32.CallNextHookEx.restype = ctypes.c_long
        user32.UnhookWindowsHookEx.argtypes = [ctypes.c_void_p]
        user32.UnhookWindowsHookEx.restype = wt.BOOL
        user32.GetMessageW.argtypes = [ctypes.POINTER(wt.MSG), wt.HWND, wt.UINT, wt.UINT]
        user32.GetMessageW.restype = wt.BOOL
        user32.TranslateMessage.argtypes = [ctypes.POINTER(wt.MSG)]
        user32.TranslateMessage.restype = wt.BOOL
        user32.DispatchMessageW.argtypes = [ctypes.POINTER(wt.MSG)]
        user32.DispatchMessageW.restype = ctypes.c_long
        user32.GetDoubleClickTime.argtypes = []
        user32.GetDoubleClickTime.restype = wt.UINT
        user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
        user32.SetCursorPos.restype = wt.BOOL
        user32.mouse_event.argtypes = [wt.DWORD, wt.DWORD, wt.DWORD, wt.DWORD,
                                       ctypes.POINTER(wt.ULONG)]
        user32.mouse_event.restype = None
        user32.SendInput.argtypes = [wt.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
        user32.SendInput.restype = wt.UINT
        user32.GetForegroundWindow.argtypes = []
        user32.GetForegroundWindow.restype = wt.HWND
        user32.OpenClipboard.argtypes = [wt.HWND]
        user32.OpenClipboard.restype = wt.BOOL
        user32.EmptyClipboard.argtypes = []
        user32.EmptyClipboard.restype = wt.BOOL
        user32.CloseClipboard.argtypes = []
        user32.CloseClipboard.restype = wt.BOOL
        user32.SetClipboardData.argtypes = [wt.UINT, wt.HANDLE]
        user32.SetClipboardData.restype = wt.HANDLE
        user32.GetClipboardData.argtypes = [wt.UINT]
        user32.GetClipboardData.restype = wt.HANDLE
        user32.FindWindowW.argtypes = [wt.LPCWSTR, wt.LPCWSTR]
        user32.FindWindowW.restype = wt.HWND
    return user32


def _k32():
    global kernel32
    if kernel32 is None:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateToolhelp32Snapshot.argtypes = [wt.DWORD, wt.DWORD]
        kernel32.CreateToolhelp32Snapshot.restype = wt.HANDLE
        kernel32.Process32FirstW.argtypes = [wt.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
        kernel32.Process32FirstW.restype = wt.BOOL
        kernel32.Process32NextW.argtypes = [wt.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
        kernel32.Process32NextW.restype = wt.BOOL
        kernel32.CloseHandle.argtypes = [wt.HANDLE]
        kernel32.CloseHandle.restype = wt.BOOL
        kernel32.GetModuleHandleW.argtypes = [wt.LPCWSTR]
        kernel32.GetModuleHandleW.restype = wt.HINSTANCE
        kernel32.GlobalAlloc.argtypes = [wt.UINT, ctypes.c_size_t]
        kernel32.GlobalAlloc.restype = wt.HGLOBAL
        kernel32.GlobalLock.argtypes = [wt.HGLOBAL]
        kernel32.GlobalLock.restype = ctypes.c_void_p
        kernel32.GlobalUnlock.argtypes = [wt.HGLOBAL]
        kernel32.GlobalUnlock.restype = wt.BOOL
        kernel32.GlobalSize.argtypes = [wt.HGLOBAL]
        kernel32.GlobalSize.restype = ctypes.c_size_t
    return kernel32


def get_top_windows():
    """返回 [(hwnd, title, pid), ...]：所有可见且带标题的顶层窗口"""
    u32 = _u32()
    result = []

    def callback(hwnd, lparam):
        if u32.IsWindowVisible(hwnd):
            buf = ctypes.create_unicode_buffer(256)
            if u32.GetWindowTextW(hwnd, buf, 256) > 0:
                pid = wt.DWORD()
                u32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                result.append((hwnd, buf.value, pid.value))
        return True

    u32.EnumWindows(WNDENUMPROC(callback), 0)
    return result


def get_wechat_pids():
    """返回所有微信主进程(wechat/weixin)的 pid 集合"""
    k32 = _k32()
    INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
    snap = k32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snap in (None, 0, INVALID_HANDLE_VALUE):
        return set()
    pids = set()
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        if k32.Process32FirstW(snap, ctypes.byref(entry)):
            while True:
                if entry.szExeFile.lower() in WECHAT_MAIN_EXES:
                    pids.add(entry.th32ProcessID)
                if not k32.Process32NextW(snap, ctypes.byref(entry)):
                    break
    finally:
        k32.CloseHandle(snap)
    return pids


def find_wechat_window():
    """查找微信主窗口：只按属主进程(wechat/weixin)判定，无兜底
    返回 (hwnd, title, pid) 或 None"""
    u32 = _u32()
    pids = get_wechat_pids()
    if not pids:
        return None
    wins = get_top_windows()
    return next((w for w in wins if w[2] in pids), None)


def _force_foreground(hwnd):
    """绕过 Windows 前台锁定，把窗口强制带到最顶层"""
    u32 = _u32()
    # 1) 临时置顶：强制 Z 序到所有窗口之上
    u32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0,
                     SWP_NOMOVE | SWP_NOSIZE)
    # 2) 模拟一次 ALT 键，解除前台锁定
    u32.keybd_event(VK_MENU, 0, 0, None)
    u32.keybd_event(VK_MENU, 0, KEYEVENTF_KEYUP, None)
    u32.SetForegroundWindow(hwnd)
    # 3) 取消置顶（窗口保持最上，但不再有置顶标志）
    u32.SetWindowPos(hwnd, HWND_NOTOPMOST, 0, 0, 0, 0,
                     SWP_NOMOVE | SWP_NOSIZE)
    time.sleep(0.15)


# ================= ESC 键全局监听（按 ESC 立即停止） =================
class EscListener:
    """全局键盘钩子：监听 ESC 键，按下时设置 stop_event（采集立即停止）"""

    def __init__(self):
        self.stop_event = threading.Event()
        self.hook = None
        self.hook_ready = threading.Event()
        self._started = False
        self._ok = False
        self._block_keys = False   # 采集中是否拦截所有用户键盘输入（True 时仅放行 ESC 和注入输入）
        self.on_block = None       # 拦截用户键盘输入时的回调（子线程调用）
        self._proc = HOOKPROC(self._callback)

    def _callback(self, code, wparam, lparam):
        if code == 0:
            kb = ctypes.cast(lparam, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
            if kb.flags & LLKHF_INJECTED:
                # 程序自己的输入（SendInput）放行
                return _u32().CallNextHookEx(self.hook, code, wparam, lparam)
            if kb.vkCode == VK_ESCAPE:
                self.stop_event.set()
                # 拦截 ESC，不传给前台窗口（避免微信收到 ESC 后关闭）
                return 1
            if self._block_keys:
                # 采集中：拦截用户其他键盘输入
                cb = self.on_block
                if cb is not None:
                    try:
                        cb()
                    except Exception:
                        pass
                return 1
        return _u32().CallNextHookEx(self.hook, code, wparam, lparam)

    def _hook_thread(self):
        # 低层键盘钩子必须在带消息循环的线程上安装
        h = _u32().SetWindowsHookExW(WH_KEYBOARD_LL, self._proc,
                                     _k32().GetModuleHandleW(None), 0)
        if not h:
            self.hook_ready.set()
            return
        self.hook = h
        self.hook_ready.set()
        msg = wt.MSG()
        while _u32().GetMessageW(ctypes.byref(msg), None, 0, 0) != 0:
            _u32().TranslateMessage(ctypes.byref(msg))
            _u32().DispatchMessageW(ctypes.byref(msg))
        _u32().UnhookWindowsHookEx(h)

    def start(self):
        """启动监听（幂等：只启动一次），返回是否成功"""
        if self._started:
            return self._ok
        self._started = True
        threading.Thread(target=self._hook_thread, daemon=True).start()
        self._ok = self.hook_ready.wait(3)
        return self._ok


# ================= 鼠标锁定（采集中防误操作） =================
class MouseLock:
    """全局鼠标钩子：采集中锁定鼠标。
    拦截所有用户鼠标输入（移动/左键/右键/滚轮）；
    程序自己的输入（SetCursorPos 不产生消息、mouse_event 带注入标志）不受影响。"""

    def __init__(self):
        self.hook = None
        self.hook_ready = threading.Event()
        self._started = False
        self._ok = False
        self._tid = None
        self.on_block = None       # 拦截用户鼠标输入时的回调（子线程调用）
        self._proc = HOOKPROC(self._callback)

    def _callback(self, code, wparam, lparam):
        if code == 0:
            ms = ctypes.cast(lparam, ctypes.POINTER(MSLLHOOKSTRUCT)).contents
            if not (ms.flags & LLMHF_INJECTED):
                # 用户鼠标输入（移动/点击/滚轮）全部拦截
                cb = self.on_block
                if cb is not None:
                    try:
                        cb()
                    except Exception:
                        pass
                return 1
        return _u32().CallNextHookEx(self.hook, code, wparam, lparam)

    def _hook_thread(self):
        # 低层钩子必须在带消息循环的线程上安装
        self._tid = threading.get_ident()
        h = _u32().SetWindowsHookExW(WH_MOUSE_LL, self._proc,
                                     _k32().GetModuleHandleW(None), 0)
        if not h:
            self.hook_ready.set()
            return
        self.hook = h
        self.hook_ready.set()
        msg = wt.MSG()
        while _u32().GetMessageW(ctypes.byref(msg), None, 0, 0) != 0:
            _u32().TranslateMessage(ctypes.byref(msg))
            _u32().DispatchMessageW(ctypes.byref(msg))
        _u32().UnhookWindowsHookEx(h)
        self.hook = None

    def start(self):
        """启动鼠标锁定（幂等），返回是否成功"""
        if self._started:
            return self._ok
        self._started = True
        threading.Thread(target=self._hook_thread, daemon=True).start()
        self._ok = self.hook_ready.wait(3)
        return self._ok

    def stop(self):
        """停止鼠标锁定：向钩子线程投递 WM_QUIT 结束消息循环"""
        if self.hook and self._tid:
            _u32().PostThreadMessageW(self._tid, WM_QUIT, 0, 0)
        self._started = False


# ================= 鼠标坐标采集（点位修改用） =================
class MousePointCollector:
    """采集单个屏幕坐标：左键单击预览、双击确认(取单击值)、右键暂停/恢复"""

    def __init__(self):
        self.q = queue.Queue()
        self.hook = None
        self.hook_ready = threading.Event()
        self._proc = HOOKPROC(self._callback)

    def _callback(self, code, wparam, lparam):
        if code == 0:
            ms = ctypes.cast(lparam, ctypes.POINTER(MSLLHOOKSTRUCT)).contents
            now = time.monotonic()
            if wparam == WM_LBUTTONDOWN:
                self.q.put(("left", ms.pt.x, ms.pt.y, now))
            elif wparam == WM_RBUTTONDOWN:
                self.q.put(("right", ms.pt.x, ms.pt.y, now))
        return _u32().CallNextHookEx(self.hook, code, wparam, lparam)

    def _hook_thread(self):
        # 低层钩子必须在带消息循环的线程上安装
        h = _u32().SetWindowsHookExW(WH_MOUSE_LL, self._proc,
                                     _k32().GetModuleHandleW(None), 0)
        if not h:
            self.hook_ready.set()
            return
        self.hook = h
        self.hook_ready.set()
        msg = wt.MSG()
        while _u32().GetMessageW(ctypes.byref(msg), None, 0, 0) != 0:
            _u32().TranslateMessage(ctypes.byref(msg))
            _u32().DispatchMessageW(ctypes.byref(msg))
        _u32().UnhookWindowsHookEx(h)

    def run(self):
        """阻塞采集一个坐标；返回 (x, y) 或 None(失败/取消)"""
        threading.Thread(target=self._hook_thread, daemon=True).start()
        if not self.hook_ready.wait(3):
            log("坐标采集: 鼠标钩子安装超时")
            return None
        if not self.hook:
            log("坐标采集: 安装鼠标钩子失败")
            return None
        dbl_ms = _u32().GetDoubleClickTime()
        dbl_cx = _u32().GetSystemMetrics(SM_CXDOUBLECLK)
        dbl_cy = _u32().GetSystemMetrics(SM_CYDOUBLECLK)
        last_x = last_y = last_t = None
        paused = False
        log("坐标采集: 左键单击预览 / 双击确认(取单击值) / 右键暂停恢复")
        while True:
            try:
                kind, x, y, evt_t = self.q.get(timeout=0.2)
            except queue.Empty:
                continue
            if kind == "right":
                paused = not paused
                log("坐标采集: 已暂停（可移动窗口），右键恢复" if paused
                    else "坐标采集: 已恢复")
                continue
            if paused:
                continue
            # 双击：与上次左键按下在双击时间和距离内，取单击值
            if (last_x is not None
                    and (evt_t - last_t) * 1000 <= dbl_ms
                    and abs(x - last_x) <= dbl_cx
                    and abs(y - last_y) <= dbl_cy):
                log(f"坐标采集: 已确认 ({last_x}, {last_y})")
                return last_x, last_y
            last_x, last_y, last_t = x, y, evt_t
            log(f"坐标采集: 单击预览 x={x} y={y}（再单击微调，双击确认）")


def find_taskbar():
    """查找 Windows 任务栏窗口句柄（找不到返回 None）"""
    return _u32().FindWindowW("Shell_TrayWnd", None)


def hide_taskbar():
    """隐藏底部任务栏；返回是否成功"""
    hwnd = find_taskbar()
    if not hwnd:
        return False
    _u32().ShowWindow(hwnd, SW_HIDE)
    return True


def show_taskbar():
    """恢复显示任务栏（程序退出时调用）"""
    hwnd = find_taskbar()
    if hwnd:
        _u32().ShowWindow(hwnd, SW_SHOW)


def snap_wechat_left(hwnd):
    """前置微信窗口并靠左半边屏幕；已就位则仅前置（返回 False）
    容差判断 + 设置后复查，防止窗口拒绝第一次移动"""
    u32 = _u32()
    u32.ShowWindow(hwnd, SW_RESTORE)
    time.sleep(0.1)
    sw = u32.GetSystemMetrics(SM_CXSCREEN)
    sh = u32.GetSystemMetrics(SM_CYSCREEN)
    target_w, target_h = sw // 2, sh
    rect = wt.RECT()
    u32.GetWindowRect(hwnd, ctypes.byref(rect))
    # 已就位判断（容忍边框/取整误差）
    if (abs(rect.left) <= 2 and abs(rect.top) <= 2
            and abs((rect.right - rect.left) - target_w) <= 8
            and abs((rect.bottom - rect.top) - target_h) <= 8):
        _force_foreground(hwnd)
        return False
    # 移动窗口到左半边
    u32.SetWindowPos(hwnd, HWND_TOP, 0, 0, target_w, target_h,
                     SWP_SHOWWINDOW | SWP_NOACTIVATE)
    time.sleep(0.2)
    # 复查：若未生效再设置一次（部分窗口会拒绝首次移动）
    u32.GetWindowRect(hwnd, ctypes.byref(rect))
    if (abs(rect.left) > 2 or abs((rect.right - rect.left) - target_w) > 8):
        u32.SetWindowPos(hwnd, HWND_TOP, 0, 0, target_w, target_h,
                         SWP_SHOWWINDOW | SWP_NOACTIVATE)
        time.sleep(0.2)
    _force_foreground(hwnd)
    return True


# ================= 模拟输入（SendInput / mouse_event，参考旧项目） =================
def mouse_click(x, y):
    """移动鼠标到 (x,y) 并左键单击，点击后统一等待 0.3 秒"""
    u32 = _u32()
    u32.SetCursorPos(int(x), int(y))
    time.sleep(0.08)
    u32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, None)
    u32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, None)
    time.sleep(0.3)


def scroll_down_at(x, y, pixels, px_per_tick=120):
    """鼠标移动到 (x,y) 后向下滚动 pixels 像素（滚轮，每格约滚动 px_per_tick 像素）"""
    u32 = _u32()
    u32.SetCursorPos(int(x), int(y))
    time.sleep(0.1)
    ticks = max(1, int(pixels / px_per_tick))
    for _ in range(ticks):
        u32.mouse_event(MOUSEEVENTF_WHEEL, 0, 0, -WHEEL_DELTA, None)  # 负值=向下
        time.sleep(0.05)


def scroll_up_at(x, y, pixels, px_per_tick=120):
    """鼠标移动到 (x,y) 后向上滚动 pixels 像素（往回翻页用）"""
    u32 = _u32()
    u32.SetCursorPos(int(x), int(y))
    time.sleep(0.1)
    ticks = max(1, int(pixels / px_per_tick))
    for _ in range(ticks):
        u32.mouse_event(MOUSEEVENTF_WHEEL, 0, 0, WHEEL_DELTA, None)  # 正值=向上
        time.sleep(0.05)


def type_text(text, char_delay=0.012):
    """用 SendInput 逐字符输入文本（UNICODE 方式，支持任意字符）"""
    text = str(text)
    n = len(text)
    arr = (INPUT * (n * 2))()
    for i, ch in enumerate(text):
        d = KEYBDINPUT()
        d.wVk = 0
        d.wScan = ord(ch)
        d.dwFlags = KEYEVENTF_UNICODE
        u = _INPUTUNION()
        u.ki = d
        arr[i * 2].type = INPUT_KEYBOARD
        arr[i * 2].u = u

        d2 = KEYBDINPUT()
        d2.wVk = 0
        d2.wScan = ord(ch)
        d2.dwFlags = KEYEVENTF_UNICODE | KEYEVENTF_KEYUP
        u2 = _INPUTUNION()
        u2.ki = d2
        arr[i * 2 + 1].type = INPUT_KEYBOARD
        arr[i * 2 + 1].u = u2
    _u32().SendInput(len(arr), arr, ctypes.sizeof(INPUT))
    if char_delay:
        time.sleep(char_delay * n)


def ctrl_key(letter):
    """发送 Ctrl+字母 组合键"""
    u32 = _u32()
    vk = ord(letter.upper())
    u32.keybd_event(VK_CONTROL, 0, 0, None)
    time.sleep(0.04)
    u32.keybd_event(vk, 0, 0, None)
    time.sleep(0.04)
    u32.keybd_event(vk, 0, KEYEVENTF_KEYUP, None)
    u32.keybd_event(VK_CONTROL, 0, KEYEVENTF_KEYUP, None)
    time.sleep(0.1)


def ctrl_shift_key(letter):
    """发送 Ctrl+Shift+字母 组合键（如关闭/切换窗口的 Ctrl+Shift+W）"""
    u32 = _u32()
    vk = ord(letter.upper())
    u32.keybd_event(VK_CONTROL, 0, 0, None)
    u32.keybd_event(VK_SHIFT, 0, 0, None)
    time.sleep(0.04)
    u32.keybd_event(vk, 0, 0, None)
    time.sleep(0.04)
    u32.keybd_event(vk, 0, KEYEVENTF_KEYUP, None)
    u32.keybd_event(VK_SHIFT, 0, KEYEVENTF_KEYUP, None)
    u32.keybd_event(VK_CONTROL, 0, KEYEVENTF_KEYUP, None)
    time.sleep(0.1)


def key_press(vk):
    """发送单个按键（如 Delete）"""
    u32 = _u32()
    u32.keybd_event(vk, 0, 0, None)
    time.sleep(0.03)
    u32.keybd_event(vk, 0, KEYEVENTF_KEYUP, None)
    time.sleep(0.1)


def get_foreground_window_info():
    """获取当前前台窗口的 (hwnd, title, pid)，无则 None"""
    u32 = _u32()
    hwnd = u32.GetForegroundWindow()
    if not hwnd:
        return None
    buf = ctypes.create_unicode_buffer(256)
    u32.GetWindowTextW(hwnd, buf, 256)
    pid = wt.DWORD()
    u32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return (hwnd, buf.value, pid.value)


# ================= 剪贴板（写） =================
CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002
GMEM_ZEROINIT = 0x0040


# ================= OCR（rapidocr_onnxruntime，参考旧项目） =================
_ocr_engine = None
_ocr_lock = threading.Lock()

# 时间格式正则（按时间从近到远）:
#   星期几/周X/礼拜X、今天/昨天/前天、x天前/x小时前/x分钟前
#   年月日 2026-08-05（非今年）、月日 8月21日 或 08-05（今年）
TIME_PATTERNS = (
    r"星期[一二三四五六日天]|周[一二三四五六日]|礼拜[一二三四五六日天]",
    r"今天|昨天|前天",
    r"\d+\s*天前",
    r"\d+\s*小时前",
    r"\d+\s*分钟前",
    r"\d{4}[-/. ]\d{1,2}[-/. ]\d{1,2}",   # 2026-08-05 / 2026/8/5
    r"\d{1,2}月\d{1,2}日?",                # 8月21日 / 8月21
    r"\d{1,2}[-/]\d{1,2}",                  # 08-05 / 8/5（今年月日）
)
TIME_RE = re.compile("|".join(f"({p})" for p in TIME_PATTERNS))


# 星期汉字 -> 0-6（周一=0）
_WEEKDAY_CN = {"一": 0, "二": 1, "三": 2, "四": 3, "五": 4, "六": 5, "日": 6, "天": 6}


def resolve_article_date(text, today=None):
    """把 OCR 识别到的时间文本解析为绝对日期(date)，按当前时间推断；失败返回 None
    支持: 今天/昨天/前天、x天前、星期X/周X/礼拜X、YYYY-MM-DD、X月X日、MM-DD"""
    today = today or date.today()
    text = str(text).strip()
    # 绝对日期 YYYY[-/.]M[-/.]D
    m = re.search(r"(\d{4})[-/. ](\d{1,2})[-/. ](\d{1,2})", text)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            pass
    # 今天 / 昨天 / 前天
    if "今天" in text:
        return today
    if "昨天" in text:
        return today - timedelta(days=1)
    if "前天" in text:
        return today - timedelta(days=2)
    # x天前
    m = re.search(r"(\d+)\s*天前", text)
    if m:
        return today - timedelta(days=int(m.group(1)))
    # 星期X / 周X / 礼拜X：最近的那个星期几（今天或之前）
    m = re.search(r"(?:星期|周|礼拜)([一二三四五六日天])", text)
    if m:
        wd = _WEEKDAY_CN[m.group(1)]
        delta = (today.weekday() - wd) % 7
        return today - timedelta(days=delta)
    # X月X日（默认今年；若晚于今天则视为去年）
    m = re.search(r"(\d{1,2})月(\d{1,2})日?", text)
    if m:
        try:
            d = date(today.year, int(m.group(1)), int(m.group(2)))
        except ValueError:
            return None
        if d > today:
            d = date(today.year - 1, int(m.group(1)), int(m.group(2)))
        return d
    # MM-DD / M/D（默认今年；若晚于今天则视为去年）
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


def get_ocr_engine():
    """懒加载 OCR 引擎（RapidOCR，线程安全）"""
    global _ocr_engine
    with _ocr_lock:
        if _ocr_engine is None:
            from rapidocr_onnxruntime import RapidOCR
            log("正在加载 OCR 引擎 ...")
            _ocr_engine = RapidOCR()
            log("OCR 引擎加载完成")
        return _ocr_engine


def screenshot_region(box, path):
    """截取屏幕指定区域并保存；box=(x1,y1,x2,y2)，返回 PIL 图"""
    from PIL import ImageGrab
    img = ImageGrab.grab(bbox=(int(box[0]), int(box[1]), int(box[2]), int(box[3])))
    img.save(path)
    return img


def _text_brightness(crop):
    """计算裁剪区域内文字像素的平均亮度(0-255, 排除白色背景)；无文字返回 255"""
    try:
        crop = crop.convert("L")
        px = list(crop.getdata())
        text_px = [p for p in px if p < 235]   # 排除接近背景的白色
        if not text_px:
            return 255.0
        return sum(text_px) / len(text_px)
    except Exception:
        return 255.0


def ocr_region(box):
    """对屏幕区域 box=(x1,y1,x2,y2) 做 OCR，返回 [(中心x, 中心y, 文本, score, sbox, brightness), ...]
    坐标已换算为屏幕坐标（OCR 结果 + 截图区域偏移）
    brightness: 文字区域平均亮度(深色标题≈25, 灰色时间文本≈160)"""
    from PIL import Image
    engine = get_ocr_engine()
    # 截图到内存
    from PIL import ImageGrab
    img = ImageGrab.grab(bbox=(int(box[0]), int(box[1]), int(box[2]), int(box[3])))
    import io as _io
    buf = _io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    result, _ = engine(buf.read())
    ox, oy = int(box[0]), int(box[1])   # 截图区域偏移
    items = []
    if result:
        for box_pts, text, score in result:
            xs = [p[0] for p in box_pts]
            ys = [p[1] for p in box_pts]
            cx = int(sum(xs) / len(xs)) + ox   # 中心 x + 偏移
            cy = int(sum(ys) / len(ys)) + oy
            # 保留整个文本框（4 个点，已换算为屏幕绝对坐标）
            sbox = [(int(p[0]) + ox, int(p[1]) + oy) for p in box_pts]
            # 按文字框从截图裁剪, 计算文字亮度
            try:
                crop = img.crop((min(xs), min(ys), max(xs), max(ys)))
                brightness = _text_brightness(crop)
            except Exception:
                brightness = 255.0
            items.append((cx, cy, text, score, sbox, brightness))
    return items


def capture_region_base64(box, scale=None, quality=70):
    """截取屏幕区域 box=(x1,y1,x2,y2) 并转为 base64 JPEG 字符串；失败返回 None
    scale: 缩放比例(<1 缩小, 如 0.75), None=不缩放; quality: JPEG 质量(默认70)"""
    try:
        import io
        import base64
        from PIL import ImageGrab
        from PIL import Image as _PILImage
        img = ImageGrab.grab(bbox=(int(box[0]), int(box[1]), int(box[2]), int(box[3])))
        if scale and scale < 1.0:
            w, h = img.size
            img = img.resize((max(1, int(w * scale)), max(1, int(h * scale))), _PILImage.LANCZOS)
        if img.mode != "RGB":
            img = img.convert("RGB")
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=quality, optimize=True)
        return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode("ascii")
    except Exception as e:
        log(f"截图失败(box={box}, scale={scale}): {e}")
        return None


def find_time_items(items):
    """从 OCR 结果中筛选包含时间的条目，返回 [(中心x, 中心y, 文本), ...]
    按文字颜色过滤：只保留灰色文字(时间文本, 亮度>=100), 深色标题(亮度<100)排除；
    点击时的 x 由点位12（文章x轴线）决定，y 用本结果中心 y"""
    found = []
    for cx, cy, text, score, sbox, brightness in items:
        if TIME_RE.search(text):
            if brightness >= 100:
                found.append((cx, cy, text))
            else:
                log(f"颜色过滤: 排除深色[{text}] 亮度={brightness:.0f}")
    return found


def extract_reads(text):
    """从时间点位文本中提取阅读数，提取不到返回 -1
    如: '星期四阅读821赞4' -> 821，'昨天 阅读 117' -> 117，'昨天' -> -1"""
    m = re.search(r"阅读\s*(\d+)", text or "")
    return int(m.group(1)) if m else -1


def extract_likes(text):
    """从时间点位文本中提取点赞数，提取不到返回 -1
    如: '星期四阅读821赞4' -> 4，'昨天 阅读 117 赞 6' -> 6，'昨天' -> -1"""
    m = re.search(r"赞\s*(\d+)", text or "")
    return int(m.group(1)) if m else -1


def set_clipboard_text(text):
    """把文本写入剪贴板（Win32，线程安全）；成功返回 True"""
    u32 = _u32()
    k32 = _k32()
    if not u32.OpenClipboard(None):
        return False
    try:
        u32.EmptyClipboard()
        data = (str(text) + "\x00").encode("utf-16-le")
        h = k32.GlobalAlloc(GMEM_MOVEABLE | GMEM_ZEROINIT, len(data))
        if not h:
            return False
        p = k32.GlobalLock(h)
        if not p:
            return False
        try:
            ctypes.memmove(p, data, len(data))
        finally:
            k32.GlobalUnlock(h)
        u32.SetClipboardData(CF_UNICODETEXT, h)
        return True
    finally:
        u32.CloseClipboard()


def clear_clipboard():
    """清空剪贴板；成功返回 True"""
    u32 = _u32()
    if not u32.OpenClipboard(None):
        return False
    try:
        u32.EmptyClipboard()
        return True
    finally:
        u32.CloseClipboard()


def read_clipboard_text():
    """读取剪贴板文本，失败返回 None（Win32，线程安全）"""
    u32 = _u32()
    k32 = _k32()
    if not u32.OpenClipboard(None):
        return None
    try:
        h = u32.GetClipboardData(CF_UNICODETEXT)
        if not h:
            return None
        p = k32.GlobalLock(h)
        if not p:
            return None
        try:
            size = k32.GlobalSize(h)
            buf = ctypes.create_string_buffer(size)
            ctypes.memmove(buf, p, size)
            return buf.raw.decode("utf-16-le", errors="replace").rstrip("\x00")
        finally:
            k32.GlobalUnlock(h)
    finally:
        u32.CloseClipboard()


# ================= 抓取文章（标题/时间/保存 HTML） =================
import re as _re
_CT_RE = re.compile(r"var\s+ct\s*=\s*['\"]?(\d+)")
_PUBLISH_TIME_RE = re.compile(r"(?:var\s+publish_time\s*=\s*['\"]?)(\d+)")


def clean_filename(name):
    """文件名清洗：斜杠/点等特殊字符转为 _"""
    return re.sub(r'[\\/:*?"<>|.]', "_", str(name)).strip()


def fetch_article(url, save_path=None):
    """抓取微信文章：返回 (标题, 发布时间 str 或 None)；save_path 给定时保存完整 HTML（含图片）
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
        # 标题：og:title 优先，其次 <title>
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
        # 时间：ct 时间戳（秒）优先，其次 publish_time
        pub_time = None
        m = _CT_RE.search(html) or _PUBLISH_TIME_RE.search(html)
        if m:
            try:
                ts = int(m.group(1))
                pub_time = datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")
            except Exception:
                pass
        # 保存完整 HTML（图片为外链，HTML 内 img 引用原图）
        if save_path:
            with open(save_path, "w", encoding="utf-8") as f:
                f.write(html)
        return title, pub_time
    except Exception as e:
        log(f"抓取文章失败: {e}")
        return None


def _script_dir():
    """程序所在目录：打包后为 exe 所在目录，开发时为脚本目录"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


# ================= 数据层（input.csv） =================
def _config_dir():
    """配置文件目录（input.csv / ui_state.json）"""
    return os.path.join(_script_dir(), CONFIG_DIR)


def _input_path():
    return os.path.join(_config_dir(), INPUT_CSV)


def load_raw_input_rows():
    """读取 input.csv 所有行 -> [(idx, url, 公众号名称, 状态), ...]（含 url 为空的新增行）"""
    rows = []
    if not os.path.isfile(_input_path()):
        return rows
    with open(_input_path(), encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            try:
                idx = int(row.get("索引"))
            except (TypeError, ValueError):
                continue
            rows.append((idx,
                         (row.get("url") or "").strip(),
                         (row.get("公众号名称") or "").strip(),
                         (row.get("状态") or "pending").strip()))
    rows.sort(key=lambda r: r[0])
    return rows


def load_input_rows():
    """有效行（url 非空）-> [(idx, url, 公众号名称, 状态), ...]，采集逻辑用"""
    return [r for r in load_raw_input_rows() if r[1]]


def write_input_csv(rows):
    """把 [(idx, url, 公众号名称, 状态), ...] 整体写回 input.csv"""
    with open(_input_path(), "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["索引", "url", "公众号名称", "状态"])
        for idx, url, name, st in rows:
            w.writerow([idx, url, name, st])


def update_input_status(idx, status):
    """按索引列更新 input.csv 中某行的状态列"""
    path = _input_path()
    try:
        with open(path, encoding="utf-8-sig", newline="") as f:
            rows = list(csv.reader(f))
        if len(rows) < 2:
            return
        header = rows[0]
        if "状态" not in header:
            return
        col = header.index("状态")
        for r in rows[1:]:
            if len(r) > 0 and r[0].strip() == str(idx):
                if len(r) <= col:
                    r.extend([""] * (col - len(r) + 1))
                r[col] = status
                break
        with open(path, "w", encoding="utf-8-sig", newline="") as f:
            csv.writer(f).writerows(rows)
    except Exception as e:
        log(f"更新状态失败: {e}")


# ================= 数据层（points.csv） =================
def _points_path():
    return os.path.join(_config_dir(), "points.csv")


def _data_dir():
    """数据目录（文章HTML + collected.csv）"""
    return os.path.join(_script_dir(), DATA_DIR)


def _collected_path():
    return os.path.join(_data_dir(), COLLECTED_CSV)


def append_collected(gzh, pub_time, title, link,
                   reads=-1, likes=-1, forwards=-1, favorites=-1, comments=-1,
                   write_time=None, shot="", read_shot=""):
    """追加一条采集记录到 data/collected.csv（线程安全，不做重复检查）
    互动数据列（阅读/点赞/转发/喜欢/评论）默认 -1（未采集到），后续采集逻辑可传入；
    write_time = 点击时间点位的时间（精确到秒），不传则用当前时间
    返回: "add"=已写入 / "error"=写入失败"""
    path = _collected_path()
    link = (link or "").strip()
    if not link:
        return "skip"
    try:
        with _log_lock:
            # 检查表头是否最新（兼容旧版），非最新则整体重写（旧行缺列补默认值）
            header = None
            if os.path.isfile(path):
                with open(path, encoding="utf-8-sig", newline="") as f:
                    reader = csv.DictReader(f)
                    header = list(reader.fieldnames or [])
            now = write_time or time.strftime("%Y-%m-%d %H:%M:%S")
            new_row = {
                "公众号名称": gzh, "日期": pub_time or "", "标题": title or "",
                "链接": link, "阅读": reads, "点赞": likes, "转发": forwards,
                "喜欢": favorites, "评论": comments, "写入时间": now,
                "互动截图": shot or "",
                "阅读截图": read_shot or "",
            }
            if header != COLLECTED_HEADER or not os.path.isfile(path):
                rows = []
                if os.path.isfile(path):
                    with open(path, encoding="utf-8-sig", newline="") as f:
                        reader = csv.DictReader(f)
                        rows = [dict(r) for r in reader]
                rows.append(new_row)
                with open(path, "w", encoding="utf-8-sig", newline="") as f:
                    w = csv.DictWriter(f, fieldnames=COLLECTED_HEADER)
                    w.writeheader()
                    for r in rows:
                        row = {}
                        for k in COLLECTED_HEADER:
                            v = r.get(k)
                            if v is None:
                                v = 0 if k in ("阅读", "点赞", "转发", "喜欢", "评论") else ""
                            row[k] = v
                        w.writerow(row)
            else:
                with open(path, "a", encoding="utf-8-sig", newline="") as f:
                    w = csv.DictWriter(f, fieldnames=COLLECTED_HEADER)
                    w.writerow(new_row)
            return "add"
    except Exception as e:
        log(f"写入采集记录失败: {e}")
        return "error"


def load_points():
    """读取 config/points.csv -> [(id, 点位名称, x, y), ...] 按 id 排序"""
    rows = []
    if not os.path.isfile(_points_path()):
        return rows
    with open(_points_path(), encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            try:
                idx = int(row.get("id"))
            except (TypeError, ValueError):
                continue
            rows.append((idx,
                         (row.get("点位名称") or "").strip(),
                         (row.get("x") or "").strip(),
                         (row.get("y") or "").strip()))
    rows.sort(key=lambda r: r[0])
    return rows


def write_points(rows):
    """把 [(id, 点位名称, x, y), ...] 写回 points.csv"""
    with open(_points_path(), "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["id", "点位名称", "x", "y"])
        for idx, name, x, y in rows:
            w.writerow([idx, name, x, y])


# ================= 界面设置记忆 =================
def load_ui_state():
    """读取界面设置记忆，无则返回 {}"""
    path = os.path.join(_config_dir(), UI_STATE_FILE)
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_ui_state(state):
    """保存界面设置记忆"""
    path = os.path.join(_config_dir(), UI_STATE_FILE)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def parse_date(s):
    """解析 YYYY-MM-DD -> date，失败返回 None"""
    try:
        return datetime.strptime((s or "").strip(), "%Y-%m-%d").date()
    except Exception:
        return None


def time_range_desc(radio, cstart, cend):
    """把时间范围选择转成中文描述（含实际日期区间）"""
    today = date.today()
    if radio == "today":
        return f"当天（{today:%Y-%m-%d}）"
    if radio == "week":
        return f"近一周（{today - timedelta(days=7)} ~ {today}）"
    if radio == "month":
        return f"近一个月（{today - timedelta(days=30)} ~ {today}）"
    if radio == "year":
        return f"近一年（{today - timedelta(days=365)} ~ {today}）"
    if radio == CUSTOM:
        return f"自定义（{cstart} ~ {cend}）"
    return "全部"


# ================= 日历选择器（纯标准库） =================
class DatePicker:
    """弹出式日历：点击日期写入 StringVar（YYYY-MM-DD）"""

    WEEK_HEAD = ("一", "二", "三", "四", "五", "六", "日")

    def __init__(self, master, var, title="选择日期"):
        self.master = master
        self.var = var
        self.title = title
        self.win = None
        self.year = None
        self.month = None
        self._sel = None

    def pick(self):
        """弹出日历窗口"""
        today = date.today()
        d = parse_date(self.var.get())
        self.year, self.month = (d.year, d.month) if d else (today.year, today.month)
        self._sel = d or today

        win = tk.Toplevel(self.master)
        win.title(self.title)
        win.resizable(False, False)
        win.grab_set()                       # 模态
        self.win = win

        # 顶部导航：◀ 年月 ▶
        nav = tk.Frame(win)
        nav.pack(fill=tk.X, padx=6, pady=4)
        tk.Button(nav, text="◀", width=3, command=self._prev).pack(side=tk.LEFT)
        self.title_var = tk.StringVar()
        tk.Label(nav, textvariable=self.title_var,
                 font=("Microsoft YaHei UI", 11, "bold")).pack(side=tk.LEFT, expand=True)
        tk.Button(nav, text="▶", width=3, command=self._next).pack(side=tk.LEFT)

        # 星期头
        head = tk.Frame(win)
        head.pack(fill=tk.X, padx=6)
        for i, w in enumerate(self.WEEK_HEAD):
            tk.Label(head, text=w, width=4,
                     font=("Microsoft YaHei UI", 9, "bold")).grid(row=0, column=i, pady=2)

        self.grid = tk.Frame(win)
        self.grid.pack(fill=tk.BOTH, padx=6, pady=4)
        self._render()

        # 定位到主窗口附近
        win.update_idletasks()
        try:
            wx, wy = self.master.winfo_rootx(), self.master.winfo_rooty()
            win.geometry(f"+{wx + 30}+{wy + 30}")
        except Exception:
            pass

    def _prev(self):
        self.year, self.month = (self.year - 1, 12) if self.month == 1 \
            else (self.year, self.month - 1)
        self._render()

    def _next(self):
        self.year, self.month = (self.year + 1, 1) if self.month == 12 \
            else (self.year, self.month + 1)
        self._render()

    def _render(self):
        self.title_var.set(f"{self.year}年 {self.month:02d}月")
        for w in self.grid.winfo_children():
            w.destroy()
        first_wd = _cal.weekday(self.year, self.month, 1)      # 周一=0
        days = _cal.monthrange(self.year, self.month)[1]
        today = date.today()
        for d in range(1, days + 1):
            col = (first_wd + d - 1) % 7
            row = (first_wd + d - 1) // 7 + 1
            day = date(self.year, self.month, d)
            is_today = day == today
            is_sel = day == self._sel
            txt = f"[{d}]" if (is_today and is_sel) else str(d)
            bg = "#1565c0" if is_today else ("#fff3c4" if is_sel else "#f0f0f0")
            fg = "white" if is_today else "black"
            tk.Button(self.grid, text=txt, width=4, bg=bg, fg=fg,
                      font=("Microsoft YaHei UI", 9), relief=tk.RAISED,
                      command=lambda dd=d: self._choose(dd)).grid(
                          row=row, column=col, padx=1, pady=1)

    def _choose(self, d):
        self.var.set(f"{self.year:04d}-{self.month:02d}-{d:02d}")
        self.win.destroy()


# ================= 点位设置弹窗 =================
class PointsDialog(tk.Toplevel):
    """点位管理弹窗：列表来自 config/points.csv（id/点位名称/x/y/操作）
    名称列可双击修改；id/x/y 只读（x/y 只能通过"修改"按钮编辑）
    操作列为"修改/删除"蓝色下划线按钮；底部新增"""

    FONT = ("Microsoft YaHei UI", 10)
    LINK = ("Microsoft YaHei UI", 9, "underline")   # 操作按钮样式（下划线）

    def __init__(self, master, app=None):
        super().__init__(master)
        self.app = app
        self.title("点位设置")
        self.geometry("690x520")
        self.minsize(560, 420)
        self.transient(master)
        self.grab_set()          # 模态
        self.rows = load_points()
        self._build()
        self._refresh()
        # 居中
        self.update_idletasks()
        x = (self.winfo_screenwidth() - 690) // 2
        y = (self.winfo_screenheight() - 520) // 2
        self.geometry(f"+{x}+{y}")

    def _build(self):
        # ---- 表头（固定不滚动，pack 固定列宽与行对齐；字体与行一致保证列宽像素相同） ----
        head = tk.Frame(self)
        head.pack(side=tk.TOP, fill=tk.X, padx=6, pady=(6, 2))
        tk.Label(head, text="id", width=5, anchor="center",
                 font=self.FONT).pack(side=tk.LEFT, padx=2)
        tk.Label(head, text="点位名称", width=22, anchor="w",
                 font=self.FONT).pack(side=tk.LEFT, padx=2)
        tk.Label(head, text="x", width=8, anchor="center",
                 font=self.FONT).pack(side=tk.LEFT, padx=2)
        tk.Label(head, text="y", width=8, anchor="center",
                 font=self.FONT).pack(side=tk.LEFT, padx=2)
        tk.Label(head, text="操作", width=14, anchor="center",
                 font=self.FONT).pack(side=tk.LEFT, padx=2)

        # ---- 可滚动列表区 ----
        wrap = tk.Frame(self)
        wrap.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=6)
        self.canvas = tk.Canvas(wrap, highlightthickness=0)
        vsb = ttk.Scrollbar(wrap, orient="vertical", command=self.canvas.yview)
        self.inner = tk.Frame(self.canvas)
        self.inner.bind("<Configure>",
                        lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.canvas.bind("<Enter>", lambda e: self.canvas.bind_all(
            "<MouseWheel>", lambda ev: self.canvas.yview_scroll(int(-ev.delta / 120), "units")))
        self.canvas.bind("<Leave>", lambda e: self.canvas.unbind_all("<MouseWheel>"))

        # ---- 底部按钮 ----
        bar = tk.Frame(self)
        bar.pack(fill=tk.X, padx=6, pady=(0, 8))
        tk.Button(bar, text="关闭", width=10, font=("Microsoft YaHei UI", 10),
                  command=self.destroy).pack(side=tk.RIGHT, padx=4)
        tk.Button(bar, text="新增", width=10, font=("Microsoft YaHei UI", 10),
                  command=self._add).pack(side=tk.RIGHT, padx=4)

    # ---------- 行渲染 ----------
    def _refresh(self):
        for w in self.inner.winfo_children():
            w.destroy()
        self.row_widgets = {}
        for pos, (idx, name, x, y) in enumerate(self.rows):
            self._add_row(pos, idx, name, x, y)

    def _add_row(self, pos, idx, name, x, y):
        row = tk.Frame(self.inner)
        row.pack(fill=tk.X, pady=1)
        # 名称超长截断显示（保持列宽固定，保证与表头对齐）
        shown = name if len(name) <= 22 else name[:22] + "…"
        tk.Label(row, text=str(idx), width=5, anchor="center",
                 font=self.FONT).pack(side=tk.LEFT, padx=2)
        name_lbl = tk.Label(row, text=shown, width=22, anchor="w", font=self.FONT)
        name_lbl.pack(side=tk.LEFT, padx=2)
        name_lbl.bind("<Double-1>",
                      lambda e, p=pos: self._edit_name(p, name_lbl))
        tk.Label(row, text=str(x or ""), width=8, anchor="center",
                 font=self.FONT).pack(side=tk.LEFT, padx=2)
        tk.Label(row, text=str(y or ""), width=8, anchor="center",
                 font=self.FONT).pack(side=tk.LEFT, padx=2)
        # 操作列：修改 / 删除（蓝色下划线按钮样式）
        edit_btn = tk.Label(row, text="修改", width=4, fg="#1565c0",
                            font=self.LINK, cursor="hand2")
        edit_btn.pack(side=tk.LEFT, padx=4)
        edit_btn.bind("<Button-1>", lambda e, p=pos: self._edit_row(p))
        del_btn = tk.Label(row, text="删除", width=4, fg="#1565c0",
                           font=self.LINK, cursor="hand2")
        del_btn.pack(side=tk.LEFT, padx=4)
        del_btn.bind("<Button-1>", lambda e, p=pos: self._delete_row(p))
        self.row_widgets[pos] = row

    # ---------- 名称列双击编辑 ----------
    def _edit_name(self, pos, lbl):
        idx, name, x, y = self.rows[pos]
        row = self.row_widgets.get(pos)
        if row is None:
            return
        # 记录名称 Label 位置，用 Entry 覆盖（place 与 pack 不冲突）
        px, py = lbl.winfo_x(), lbl.winfo_y()
        pw, ph = lbl.winfo_width(), lbl.winfo_height()
        lbl.destroy()
        e = tk.Entry(row, font=self.FONT)
        e.place(x=px, y=py, width=pw, height=ph)
        e.insert(0, name)
        e.insert(0, name)
        e.focus_set()
        e.select_range(0, "end")
        state = {"done": False}

        def commit(_ev=None):
            if state["done"]:
                return
            state["done"] = True
            try:
                v = e.get().strip()
            except Exception:
                v = ""
            e.destroy()
            if v and v != name:
                self.rows[pos] = (idx, v, x, y)
                self._save("已修改点位名称")
            else:
                self._refresh()

        def cancel(_ev=None):
            state["done"] = True
            e.destroy()
            self._refresh()

        e.bind("<Return>", commit)
        e.bind("<FocusOut>", commit)
        e.bind("<Escape>", cancel)

    # ---------- 修改点位：鼠标采集坐标 ----------
    def _edit_row(self, pos):
        """修改点位：弹窗保持显示，释放模态后鼠标采集坐标
        左键单击预览 / 双击确认(取单击值) / 右键暂停恢复"""
        if pos >= len(self.rows):
            return
        idx, name, x, y = self.rows[pos]
        log(f"开始采集点位 [{idx}] {name} 的坐标...")
        log("坐标采集: 左键单击预览 / 双击确认(取单击值) / 右键暂停恢复")
        try:
            self.grab_release()      # 释放模态，允许点击目标窗口
        except Exception:
            pass
        self._collect_pos = pos
        self._result_q = queue.Queue()
        threading.Thread(target=self._collect_worker, args=(pos,), daemon=True).start()
        self.after(50, self._poll_collect_result)

    def _collect_worker(self, pos):
        """后台线程：采集坐标（阻塞直到确认）"""
        c = MousePointCollector()
        result = c.run()
        try:
            self._result_q.put(result)
        except Exception:
            pass

    def _poll_collect_result(self):
        """主线程轮询采集结果：恢复模态并写回点位"""
        try:
            result = self._result_q.get_nowait()
        except queue.Empty:
            self.after(50, self._poll_collect_result)
            return
        except Exception:
            return
        try:
            self.grab_set()          # 恢复模态
        except Exception:
            pass
        if result:
            pos = self._collect_pos
            if 0 <= pos < len(self.rows):
                idx, name, x, y = self.rows[pos]
                self.rows[pos] = (idx, name, result[0], result[1])
                self._save("已更新点位坐标")
        else:
            log("坐标采集取消，点位未修改")
    # ---------- 删除 / 新增 ----------
    def _delete_row(self, pos):
        if pos >= len(self.rows):
            return
        idx, name, x, y = self.rows[pos]
        if messagebox.askyesno("删除确认",
                               f"确定删除点位 [{idx}] {name}？", parent=self):
            self.rows.pop(pos)
            self._save("已删除点位")

    def _add(self):
        if self.rows:
            new_idx = max(r[0] for r in self.rows) + 1
        else:
            new_idx = 1
        self.rows.append((new_idx, "新点位", "", ""))
        self._save("已新增点位，双击名称改名，点修改填 x/y")
        self.inner.update_idletasks()
        self.canvas.yview_moveto(1.0)      # 滚动到底部

    def _save(self, msg, close_dlg=None):
        write_points(self.rows)
        self._refresh()
        log(msg)
        if close_dlg:
            close_dlg.destroy()


# ================= 主界面 =================
class App:
    def __init__(self, root):
        self.root = root
        self.root.title(APP_NAME if not VERSION else f"{APP_NAME} {VERSION}")
        # 默认窗口尺寸自适应：屏幕不够大时按屏幕缩（不写死，兼容小屏）
        _sw = root.winfo_screenwidth()
        _sh = root.winfo_screenheight()
        self.win_w = min(1240, max(900, _sw - 20))
        self.win_h = min(700, max(560, _sh - 60))
        self.min_w = min(1160, max(900, _sw - 20))
        self.min_h = min(600, max(520, _sh - 60))
        self.root.geometry(f"{self.win_w}x{self.win_h}")
        self.root.minsize(self.min_w, self.min_h)

        self.ui = load_ui_state()
        self.busy = False
        self.last_error = ""
        self.esc = EscListener()
        self.mouse_lock = MouseLock()
        self.stop_event = self.esc.stop_event
        # 拦截用户输入时触发右上角提示
        self._hint_win = None
        self._hint_after_id = None
        self.esc.on_block = self._queue_lock_hint
        self.mouse_lock.on_block = self._queue_lock_hint
        self.ui_queue = queue.Queue()   # 子线程 -> 主线程 UI 消息队列

        self._build_ui()
        self.reload_input()
        global UI_LOG_HOOK
        UI_LOG_HOOK = self.append_log

        self.root.protocol("WM_DELETE_WINDOW", self.on_exit)

    # ---------- 界面构建 ----------
    def _build_ui(self):
        root = self.root

        # ---- 顶部：状态栏 ----
        self.status_var = tk.StringVar(value="正在初始化...")
        tk.Label(root, textvariable=self.status_var,
                 font=("Microsoft YaHei UI", 12, "bold"),
                 anchor="w", padx=14, pady=8).pack(side=tk.TOP, fill=tk.X)

        # ---- 中部：左控制区(600) + 右任务区(1000) ----
        mid = tk.Frame(root)
        mid.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=14, pady=(0, 4))

        # ================= 左侧：控制区（600） =================
        left = tk.Frame(mid, width=600)
        left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        left.pack_propagate(False)

        # 1) 采集控制面板（顶部）
        ctrl = tk.LabelFrame(left, text=" 采集控制 ", font=("Microsoft YaHei UI", 10))
        ctrl.pack(side=tk.TOP, fill=tk.X)

        # 索引范围
        row1 = tk.Frame(ctrl)
        row1.pack(fill=tk.X, padx=10, pady=(6, 2))
        tk.Label(row1, text="索引范围:", font=("Microsoft YaHei UI", 10)).pack(side=tk.LEFT)
        self.idx_start_var = tk.StringVar(value=str(self.ui.get("idx_start", 0)))
        self.idx_end_var = tk.StringVar(value=str(self.ui.get("idx_end", 0)))
        tk.Entry(row1, textvariable=self.idx_start_var, width=6,
                 font=("Microsoft YaHei UI", 10)).pack(side=tk.LEFT, padx=4)
        tk.Label(row1, text=" 到 ", font=("Microsoft YaHei UI", 10)).pack(side=tk.LEFT)
        tk.Entry(row1, textvariable=self.idx_end_var, width=6,
                 font=("Microsoft YaHei UI", 10)).pack(side=tk.LEFT, padx=4)
        self.total_label = tk.Label(row1, text="", font=("Microsoft YaHei UI", 9),
                                    fg="#888888")
        self.total_label.pack(side=tk.LEFT)

        # 时间范围（单选，非自定义选项一行横排）
        row2 = tk.Frame(ctrl)
        row2.pack(fill=tk.X, padx=10, pady=2)
        tk.Label(row2, text="时间范围:", font=("Microsoft YaHei UI", 10)).pack(side=tk.LEFT)
        tframe = tk.Frame(row2)
        tframe.pack(side=tk.LEFT, padx=4)
        saved_tr = self.ui.get("time_range", "all")
        if saved_tr not in [k for k, _ in TIME_OPTIONS]:
            saved_tr = "all"
        self.time_var = tk.StringVar(value=saved_tr)
        for i, (key, label) in enumerate(TIME_OPTIONS[:-1]):   # 前5个（不含自定义）
            tk.Radiobutton(tframe, text=label, value=key, variable=self.time_var,
                           font=("Microsoft YaHei UI", 9),
                           anchor="w").grid(row=0, column=i, sticky="w", padx=3)

        # 自定义：单独一行（radio + 开始/结束日期选择器）
        row3 = tk.Frame(ctrl)
        row3.pack(fill=tk.X, padx=10, pady=2)
        tk.Radiobutton(row3, text="自定义", value=CUSTOM, variable=self.time_var,
                       font=("Microsoft YaHei UI", 9),
                       anchor="w").pack(side=tk.LEFT)
        today = date.today()
        self.custom_start_var = tk.StringVar(
            value=str(self.ui.get("custom_start", f"{today:%Y-%m-%d}")))
        self.custom_end_var = tk.StringVar(
            value=str(self.ui.get("custom_end", f"{today:%Y-%m-%d}")))
        self.entry_start = tk.Entry(row3, textvariable=self.custom_start_var, width=11,
                                    font=("Microsoft YaHei UI", 9))
        self.entry_start.pack(side=tk.LEFT, padx=(6, 0))
        tk.Button(row3, text="日历", width=5, font=("Microsoft YaHei UI", 9),
                  command=lambda: DatePicker(row3, self.custom_start_var,
                                             "选择开始日期").pick()).pack(side=tk.LEFT, padx=2)
        tk.Label(row3, text=" ~ ", font=("Microsoft YaHei UI", 9)).pack(side=tk.LEFT)
        self.entry_end = tk.Entry(row3, textvariable=self.custom_end_var, width=11,
                                  font=("Microsoft YaHei UI", 9))
        self.entry_end.pack(side=tk.LEFT, padx=(0, 0))
        tk.Button(row3, text="日历", width=5, font=("Microsoft YaHei UI", 9),
                  command=lambda: DatePicker(row3, self.custom_end_var,
                                             "选择结束日期").pick()).pack(side=tk.LEFT, padx=2)

        # 最大采集数量
        row4 = tk.Frame(ctrl)
        row4.pack(fill=tk.X, padx=10, pady=2)
        tk.Label(row4, text="每公众号最大采集数量:", font=("Microsoft YaHei UI", 10)).pack(side=tk.LEFT)
        self.max_count_var = tk.StringVar(
            value=str(self.ui.get("max_count", "") or ""))
        tk.Spinbox(row4, from_=1, to=9999, textvariable=self.max_count_var, width=6,
                   font=("Microsoft YaHei UI", 10)).pack(side=tk.LEFT, padx=4)
        # tk.Spinbox 会把空字符串变量自动写成默认值(from_)，创建后显式恢复
        self.max_count_var.set(str(self.ui.get("max_count", "") or ""))
        tk.Label(row4, text="(空 = 无限)", font=("Microsoft YaHei UI", 9),
                 fg="#888888").pack(side=tk.LEFT)
        # 窗口分离开关：开启时点击点位2后额外点击点位11
        self.window_split_var = tk.BooleanVar(
            value=bool(self.ui.get("window_split", False)))
        tk.Checkbutton(row4, text="窗口分离", variable=self.window_split_var,
                       font=("Microsoft YaHei UI", 10)).pack(side=tk.LEFT, padx=(12, 0))

        # 采集开关
        row5 = tk.Frame(ctrl)
        row5.pack(fill=tk.X, padx=10, pady=(6, 2))
        self.capture_read_var = tk.BooleanVar(
            value=bool(self.ui.get("capture_read", False)))
        tk.Checkbutton(row5, text="采集阅读数", variable=self.capture_read_var,
                       font=("Microsoft YaHei UI", 10)).pack(side=tk.LEFT)
        self.capture_4metrics_var = tk.BooleanVar(
            value=bool(self.ui.get("capture_4metrics", False)))
        tk.Checkbutton(row5, text="采集4指标", variable=self.capture_4metrics_var,
                       font=("Microsoft YaHei UI", 10)).pack(side=tk.LEFT, padx=(12, 0))

        # 开始按钮 + 点位设置（同一栏，点位设置靠右小按钮）
        # 滚动距离 + 测试滚动 配置（紧凑排左）
        scroll_bar = tk.Frame(ctrl)
        scroll_bar.pack(fill=tk.X, padx=10, pady=(6, 2))
        tk.Label(scroll_bar, text="滚动距离:",
                 font=("Microsoft YaHei UI", 9)).pack(side=tk.LEFT)
        # 默认 = 屏幕高度 70%（若无记忆）
        _def_scroll = int(_u32().GetSystemMetrics(SM_CYSCREEN) * 0.7)
        saved_scroll = str(self.ui.get("scroll_px", _def_scroll))
        self.scroll_px_var = tk.StringVar(value=saved_scroll)
        tk.Spinbox(scroll_bar, from_=0, to=5000, increment=50,
                   textvariable=self.scroll_px_var, width=5,
                   font=("Microsoft YaHei UI", 9)).pack(side=tk.LEFT, padx=(3, 0))
        tk.Label(scroll_bar, text="px",
                 font=("Microsoft YaHei UI", 8), fg="#888888").pack(side=tk.LEFT, padx=1)
        # 测试滚动按钮（跟滚动距离一组）
        self.btn_scroll_test = tk.Button(scroll_bar, text="测试滚动", width=8,
                                         font=("Microsoft YaHei UI", 9),
                                         command=self.on_scroll_test)
        self.btn_scroll_test.pack(side=tk.LEFT, padx=4)
        btn_bar = tk.Frame(ctrl)
        btn_bar.pack(fill=tk.X, padx=10, pady=(4, 6))
        self.btn_points = tk.Button(btn_bar, text="点位设置", width=10,
                                    font=("Microsoft YaHei UI", 12),
                                    command=self.open_points_dialog)
        self.btn_points.pack(side=tk.RIGHT, padx=(10, 0))
        self.btn_start = tk.Button(btn_bar, text="开始", width=16,
                                   font=("Microsoft YaHei UI", 12, "bold"),
                                   bg="#1565c0", fg="white",
                                   activebackground="#0d47a1", activeforeground="white",
                                   command=self.on_start)
        self.btn_start.pack(side=tk.LEFT, fill=tk.X, expand=True)

        # 进度区（开始按钮下面）
        self.progress_var = tk.StringVar(value="进度: 待开始")
        tk.Label(ctrl, textvariable=self.progress_var,
                 font=("Microsoft YaHei UI", 10, "bold"),
                 fg="#1565c0", anchor="w").pack(fill=tk.X, padx=10, pady=(0, 2))
        self.pbar = ttk.Progressbar(ctrl, maximum=100)
        self.pbar.pack(fill=tk.X, padx=10, pady=(0, 8))

        # 2) 控制台（日志）（下面，占剩余空间）
        log_box = tk.LabelFrame(left, text=" 控制台（日志） ", font=("Microsoft YaHei UI", 10))
        log_box.pack(side=tk.TOP, fill=tk.BOTH, expand=True, pady=(6, 0))
        self.text = scrolledtext.ScrolledText(
            log_box, state="disabled", wrap="word",
            font=("Microsoft YaHei UI", 10),
            relief=tk.GROOVE, borderwidth=1)
        self.text.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)

        # ================= 右侧：任务区（600） =================
        right = tk.Frame(mid, width=600)
        right.pack(side=tk.RIGHT, fill=tk.BOTH, expand=False, padx=(10, 0))
        right.pack_propagate(False)

        task = tk.LabelFrame(right, text=" 任务区（input 数据，双击单元格编辑） ",
                             font=("Microsoft YaHei UI", 10))
        task.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        # 表格：索引 | 链接 | 公众号名称 | 状态 | 操作
        cols = ("idx", "url", "name", "status", "op")
        self.tree = ttk.Treeview(task, columns=cols, show="headings")
        self.tree.heading("idx", text="索引")
        self.tree.heading("url", text="链接")
        self.tree.heading("name", text="公众号名称")
        self.tree.heading("status", text="状态")
        self.tree.heading("op", text="操作")
        self.tree.column("idx", width=45, anchor="center", stretch=False)
        self.tree.column("url", width=230, anchor="w", stretch=True)
        self.tree.column("name", width=150, anchor="w", stretch=False)
        self.tree.column("status", width=130, anchor="w", stretch=False)
        self.tree.column("op", width=40, anchor="center", stretch=False)
        vsb = ttk.Scrollbar(task, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)

        # 双击编辑 / 单击操作列删除
        self.tree.bind("<Double-1>", self._on_tree_double_click)
        self.tree.bind("<Button-1>", self._on_tree_click)

        # 底部按钮：重置 / 新增
        btns = tk.Frame(task)
        btns.pack(fill=tk.X, padx=6, pady=(0, 6))
        self.btn_reset = tk.Button(btns, text="重置", width=10,
                                   font=("Microsoft YaHei UI", 10),
                                   command=self.on_reset)
        self.btn_reset.pack(side=tk.RIGHT, padx=4)
        self.btn_add = tk.Button(btns, text="新增", width=10,
                                 font=("Microsoft YaHei UI", 10),
                                 command=self.on_add)
        self.btn_add.pack(side=tk.RIGHT, padx=4)

        # ---- 底部：微信版本（靠右） ----
        bottom = tk.Frame(root)
        bottom.pack(side=tk.BOTTOM, fill=tk.X, padx=14, pady=4)
        tk.Label(bottom, text=f"微信 PC 版 {WECHAT_VERSION}",
                 font=("Microsoft YaHei UI", 9),
                 fg="#888888", anchor="e").pack(side=tk.RIGHT)

        # 设置记忆：任何变更自动保存
        for v in (self.idx_start_var, self.idx_end_var, self.time_var,
                  self.custom_start_var, self.custom_end_var, self.max_count_var,
                  self.scroll_px_var):
            v.trace_add("write", lambda *a: self._save_state())

        # 时间范围变更时启用/禁用自定义日期行
        self.time_var.trace_add("write", lambda *a: self._update_custom_state())
        self._update_custom_state()

        # 快捷键：回车 = 点击开始（焦点在输入框时不触发）
        root.bind("<Return>", self._on_return_key)

        # 窗口居中（按实际尺寸）
        root.update_idletasks()
        x = (root.winfo_screenwidth() - self.win_w) // 2
        y = (root.winfo_screenheight() - self.win_h) // 2
        root.geometry(f"+{x}+{y}")

    # ---------- 任务区数据 ----------
    def _update_title(self):
        """大标题同步 input 情况：有效链接数 / 待处理数"""
        try:
            total = len(self.input_rows)
            todo = sum(1 for _, _, _, st in self.input_rows
                       if st in ("pending", "null") or "error" in st)
            self.status_var.set(f"有效链接 {total} 个（待处理 {todo} 个）")
        except Exception:
            pass

    def reload_input(self, msg=None):
        """从 input.csv 重新加载：刷新表格 + 同步有效行 + 更新索引上限"""
        self.rows_all = load_raw_input_rows()
        self.input_rows = load_input_rows()
        self._refresh_tree()
        total = len(self.input_rows)
        self.total_label.config(text=f"有效链接 {total} 个")
        self._update_title()   # 大标题同步 input 情况
        try:
            cur_end = int(self.idx_end_var.get())
        except ValueError:
            cur_end = 0
        if self.ui.get("idx_end") is None or msg is None:
            self.idx_end_var.set(str(max(total - 1, 0)))
        if msg:
            log(msg)

    def _refresh_tree(self):
        """按 rows_all 刷新表格内容"""
        self.tree.delete(*self.tree.get_children())
        for pos, (idx, url, name, st) in enumerate(self.rows_all):
            tag = ""
            if st == "pending":
                tag = "pending"
            elif "error" in st:
                tag = "error"
            self.tree.insert("", "end", iid=str(pos),
                             values=(idx, url, name, st, "删除"), tags=(tag,))
        self.tree.tag_configure("pending", background="#fff8e1")
        self.tree.tag_configure("error", background="#ffebee")

    def _save_input(self, log_msg):
        """rows_all 写回 input.csv 并刷新；自动修正：链接已填写但状态为 null 的行改为 pending"""
        auto = 0
        for i, (idx, url, name, st) in enumerate(self.rows_all):
            if st == "null" and url:
                self.rows_all[i] = (idx, url, name, "pending")
                auto += 1
        write_input_csv(self.rows_all)
        self.reload_input(log_msg)
        if auto:
            log(f"状态修正: {auto} 个已填写链接但状态为 null 的行自动改为 pending")

    # ---------- 任务区交互：编辑 / 删除 / 重置 / 新增 ----------
    def _on_tree_click(self, event):
        """单击：命中操作列则删除该行"""
        rowid = self.tree.identify_row(event.y)
        col = self.tree.identify_column(event.x)
        if not rowid or col == "#5":        # 操作列
            self._delete_row(rowid)

    def _on_tree_double_click(self, event):
        """双击：编辑单元格（索引列只读）"""
        rowid = self.tree.identify_row(event.y)
        col = self.tree.identify_column(event.x)
        if not rowid or not col:
            return
        col_idx = int(col.replace("#", "")) - 1
        if col_idx == 0:                    # 索引只读
            return
        if col_idx == 4:                    # 操作列
            self._delete_row(rowid)
            return
        bbox = self.tree.bbox(rowid, col)
        if not bbox:
            return
        x, y, w, h = bbox
        values = self.tree.item(rowid, "values")
        e = tk.Entry(self.tree)
        e.place(x=x, y=y, width=w, height=h)
        e.insert(0, str(values[col_idx]))
        e.focus_set()
        e.select_range(0, "end")
        state = {"committed": False}
        e.bind("<Return>", lambda ev: self._commit_edit(rowid, col_idx, e, state))
        e.bind("<Escape>", lambda ev: (setattr(state, "committed", True), e.destroy()))
        e.bind("<FocusOut>", lambda ev: self._commit_edit(rowid, col_idx, e, state))

    def _commit_edit(self, rowid, col_idx, entry, state):
        """提交单元格编辑：写回内存并落盘"""
        if state.get("committed"):
            return
        state["committed"] = True
        try:
            new_val = entry.get().strip()
        except Exception:
            return
        entry.destroy()
        pos = int(rowid)
        if pos >= len(self.rows_all):
            return
        row = list(self.rows_all[pos])
        old_val = row[col_idx]
        row[col_idx] = new_val
        self.rows_all[pos] = tuple(row)
        if new_val != old_val:
            self._save_input(f"已修改: [{row[0]}] 列[{col_idx}] {old_val[:30]} -> {new_val[:30]}")

    def _delete_row(self, rowid):
        """删除表格行（带确认）"""
        if not rowid:
            return
        pos = int(rowid)
        if pos >= len(self.rows_all):
            return
        idx, url, name, st = self.rows_all[pos]
        if not messagebox.askyesno("删除确认", f"确定删除第 {idx} 行？\n{name or url[:50] or '(空)'}"):
            return
        self.rows_all.pop(pos)
        self._save_input(f"已删除: [{idx}] {name}")

    def on_reset(self):
        """重置：把所有行状态改为 pending，然后重新加载 input.csv"""
        if not messagebox.askyesno("重置确认",
                                   "将所有链接状态重置为 pending（待采集）？\n链接为空的行状态设为 null，\n该操作会覆盖现有状态(done/error/null)。"):
            return
        rows = load_raw_input_rows()
        rows = [(idx, url, name, "pending" if url else "null")
                for idx, url, name, _st in rows]
        write_input_csv(rows)
        self.reload_input("已重置: 有链接的改为 pending，链接为空的改为 null，并重新加载 input.csv")

    def on_add(self):
        """新增：追加一行空记录（双击编辑）"""
        if not self.rows_all:
            new_idx = 0
        else:
            new_idx = max(r[0] for r in self.rows_all) + 1
        self.rows_all.append((new_idx, "", "", "null"))
        self._save_input(f"已新增空行 [索引 {new_idx}]，双击链接/名称列填写内容，状态默认 null")

    # ---------- 控制区逻辑 ----------
    def _on_return_key(self, event):
        """回车 = 点击开始（避免焦点在输入框时误触）"""
        try:
            w = self.root.focus_get()
            if isinstance(w, (tk.Entry, tk.Spinbox)):
                return
        except Exception:
            pass
        self.on_start()

    def _update_custom_state(self):
        """自定义时间范围选中时启用日期选择，否则禁用"""
        st = tk.NORMAL if self.time_var.get() == CUSTOM else tk.DISABLED
        for w in (self.entry_start, self.entry_end):
            try:
                w.config(state=st)
            except Exception:
                pass

    def open_points_dialog(self):
        """打开点位设置弹窗"""
        PointsDialog(self.root)

    def on_scroll_test(self):
        """测试滚动：鼠标移到点位7，按配置的滚动距离向下滚动（人工已打开文章列表时用）"""
        pts = {p[0]: p for p in load_points()}
        p7 = pts.get(7)
        if not p7:
            log("错误: 缺少点位7，无法测试滚动")
            return
        try:
            px = int(float(self.scroll_px_var.get()))
        except ValueError:
            log("滚动距离格式错误，请输入数字")
            return
        if px <= 0:
            log("滚动距离应大于 0")
            return
        log(f"测试滚动: 鼠标移到点位7({p7[2]},{p7[3]}) 向下滚动 {px}px")
        scroll_down_at(int(p7[2]), int(p7[3]), px)

    def append_log(self, msg):
        """日志：放入队列，由主线程轮询写入控制台（子线程安全）"""
        try:
            self.ui_queue.put(("log", msg))
        except Exception:
            pass

    def _poll_ui_queue(self):
        """主线程轮询处理 UI 队列（日志/进度/窗口操作/采集结束）"""
        try:
            while True:
                item = self.ui_queue.get_nowait()
                kind = item[0]
                if kind == "log":
                    self.text.configure(state="normal")
                    self.text.insert("end", item[1] + "\n")
                    self.text.see("end")
                    self.text.configure(state="disabled")
                elif kind == "progress":
                    self.progress_var.set(item[1])
                    self.pbar.config(value=item[2])
                elif kind == "snap":
                    self._snap_main_right()
                elif kind == "refresh_input":
                    self.reload_input("")      # 静默刷新任务区（状态已更新）
                elif kind == "lock_hint":
                    self._show_lock_hint()
                elif kind == "finish":
                    self._finish_collection(item[1], item[2], item[3])
        except queue.Empty:
            pass
        except Exception:
            pass
        try:
            self.root.after(50, self._poll_ui_queue)
        except Exception:
            pass

    def _queue_lock_hint(self):
        """钩子子线程调用：往 UI 队列放提示消息（主线程显示弹窗）"""
        try:
            self.ui_queue.put(("lock_hint",))
        except Exception:
            pass

    def _show_lock_hint(self):
        """右上角提示弹窗：显示当前正在采集、输入已禁用，1 秒后自动消失"""
        try:
            # 已有弹窗：直接重置消失计时，不重建（避免鼠标移动高频重建）
            if self._hint_win is not None:
                try:
                    self._hint_win.after_cancel(self._hint_after_id)
                except Exception:
                    pass
                try:
                    self._hint_win.after(1000, lambda: self._close_lock_hint(self._hint_win))
                except Exception:
                    pass
                return
            win = tk.Toplevel(self.root)
            win.overrideredirect(True)          # 无边框
            win.attributes("-topmost", True)    # 置顶
            win.attributes("-alpha", 0.95)      # 略透明
            sw = win.winfo_screenwidth()
            w, h = 420, 120
            x, y = sw - w - 16, 16              # 右上角
            win.geometry(f"{w}x{h}+{x}+{y}")
            frame = tk.Frame(win, bg="#fff3cd", highlightthickness=1,
                             highlightbackground="#e0a800")
            frame.pack(fill="both", expand=True)
            tk.Label(frame, text="⚠ 当前正常进行采集任务",
                     font=("微软雅黑", 13, "bold"),
                     bg="#fff3cd", fg="#856404").pack(pady=(12, 4))
            tk.Label(frame, text="鼠标和键盘操作已禁用\n可按 ESC 结束采集进程",
                     font=("微软雅黑", 11),
                     bg="#fff3cd", fg="#856404").pack(pady=(0, 12))
            self._hint_win = win
            self._hint_after_id = win.after(1000, lambda: self._close_lock_hint(win))
        except Exception:
            pass

    def _close_lock_hint(self, win):
        """关闭提示弹窗"""
        try:
            if self._hint_win is win:
                self._hint_win = None
            win.destroy()
        except Exception:
            pass

    def _save_state(self, *_a):
        save_ui_state({
            "idx_start": self.idx_start_var.get(),
            "idx_end": self.idx_end_var.get(),
            "time_range": self.time_var.get(),
            "custom_start": self.custom_start_var.get(),
            "custom_end": self.custom_end_var.get(),
            "max_count": self.max_count_var.get(),
            "scroll_px": self.scroll_px_var.get(),
            "window_split": self.window_split_var.get(),
            "capture_read": self.capture_read_var.get(),
            "capture_4metrics": self.capture_4metrics_var.get(),
        })

    # ---------- 窗口布局（采集时微信左半屏 / main 右半屏） ----------
    def _snap_main_right(self):
        """main 窗口靠右半边屏幕（采集时与微信并排）"""
        try:
            sw = self.root.winfo_screenwidth()
            sh = self.root.winfo_screenheight()
            self.root.minsize(200, 200)
            self.root.geometry(f"{sw // 2}x{sh}+{sw // 2}+0")
        except Exception:
            pass

    def _restore_main(self):
        """恢复 main 窗口到默认大小并居中（预留，当前停止后保持右半屏不调用）"""
        try:
            self.root.minsize(self.min_w, self.min_h)
            self.root.geometry(f"{self.win_w}x{self.win_h}")
            sw = self.root.winfo_screenwidth()
            sh = self.root.winfo_screenheight()
            self.root.geometry(f"+{(sw - self.win_w) // 2}+{(sh - self.win_h) // 2}")
        except Exception:
            pass

    # ---------- 启动 ----------
    def start(self):
        # 启动 UI 队列轮询（主线程定时处理子线程消息）
        self.root.after(50, self._poll_ui_queue)
        # 隐藏任务栏（采集时屏幕全高）；退出时由 atexit 恢复
        if hide_taskbar():
            log("已隐藏任务栏（程序退出时自动恢复）")
        total = len(self.input_rows)
        todo = sum(1 for _, _, _, st in self.input_rows
                   if st in ("pending", "null") or "error" in st)
        self.idx_end_var.set(str(max(total - 1, 0)))
        self.status_var.set(f"已加载 {total} 个公众号（待处理 {todo} 个）")
        log(f"{APP_NAME} 已启动")
        log(f"已加载 {CONFIG_DIR}/{INPUT_CSV}: {total} 个有效公众号（pending/null/error 共 {todo} 个）")
        log(f"微信 PC 版: {WECHAT_VERSION}（程序版本 {VERSION}）")
        log(f"记忆设置已读取: 时间范围[{dict(TIME_OPTIONS).get(self.time_var.get(), '?')}] "
            f"最大数量[{self.max_count_var.get() or '无限'}] "
            f"窗口分离[{('开' if self.window_split_var.get() else '关')}] "
            f"采集阅读[{('开' if self.capture_read_var.get() else '关')}] "
            f"采集4指标[{('开' if self.capture_4metrics_var.get() else '关')}]")
        log("右侧任务区可编辑 input 数据（双击单元格修改，操作列删除，底部重置/新增）")
        log("请在左侧采集控制设置索引范围、时间范围、最大数量后点击【开始】（或按回车）")
        if not self.input_rows:
            log("警告: input.csv 中没有有效链接，请先在任务区新增或填写数据")

    # ---------- 开始按钮（状态机；采集动作当前为模拟，待接入真实流程） ----------
    def _resolve_time_range(self, tr, cstart, cend):
        """把时间范围选择解析为 (起始date, 结束date)；不限返回 None"""
        today = date.today()
        if tr == "today":
            return (today, today)
        if tr == "week":
            return (today - timedelta(days=7), today)
        if tr == "month":
            return (today - timedelta(days=30), today)
        if tr == "year":
            return (today - timedelta(days=365), today)
        if tr == CUSTOM:
            ds, de = parse_date(cstart), parse_date(cend)
            if ds and de and ds <= de:
                return (ds, de)
        return None

    def on_start(self):
        if self.busy:
            log("收到停止请求，正在停止 ...")
            self.stop_event.set()
            try:
                self.btn_start.config(state=tk.DISABLED, text="停止中...")
            except Exception:
                pass
            return
        total = len(self.input_rows)
        if total == 0:
            log("input.csv 中没有有效链接")
            return
        try:
            s = int(self.idx_start_var.get())
            e = int(self.idx_end_var.get())
        except ValueError:
            log("索引格式错误，请输入数字")
            return
        s = max(0, min(s, total - 1))
        e = max(0, min(e, total - 1))
        if s > e:
            log("起始索引大于结束索引")
            return

        # 时间范围校验（自定义需开始 + 结束日期）
        tr = self.time_var.get()
        cstart = self.custom_start_var.get().strip()
        cend = self.custom_end_var.get().strip()
        if tr == CUSTOM:
            ds, de = parse_date(cstart), parse_date(cend)
            if not ds or not de:
                log("自定义日期格式错误，应为 YYYY-MM-DD")
                return
            if ds > de:
                log("开始日期晚于结束日期")
                return

        # 最大采集数量（空 = 无限）
        mc = self.max_count_var.get().strip()
        if mc:
            try:
                max_count = int(float(mc))
            except ValueError:
                log("最大采集数量格式错误，应为数字或留空(无限)")
                return
            if max_count < 1:
                max_count = None
        else:
            max_count = None

        # 解析时间范围为日期区间（None = 不限）
        time_range_dates = self._resolve_time_range(tr, cstart, cend)
        # 固定下载目录（不按开始时间分目录，一批任务可多次进行）
        self.session_dir = os.path.join(_data_dir(), "下载")
        self.max_count_setting = max_count
        self.time_range_dates = time_range_dates
        self.is_custom_mode = (tr == CUSTOM)   # 自定义时间范围模式标志
        log(f"文章保存目录: {self.session_dir}")
        rows = self.input_rows[s:e + 1]
        todo = [r for r in rows if r[3] in ("pending", "null") or "error" in r[3]]
        desc = time_range_desc(tr, cstart, cend)
        log("=" * 46)
        log(f"即将采集: 索引 {s}-{e}，共 {len(rows)} 个公众号，待处理 {len(todo)} 个")
        log(f"时间范围: {desc}")
        log(f"每公众号最大采集数量: {'无限' if max_count is None else max_count}")
        if not todo:
            log("范围内没有待处理(pending/null/error)的链接，无需采集")
            return
        log("待处理列表:")
        for idx, url, name, st in todo:
            log(f"  [{idx}] {name}  ({st})")

        # 微信窗口检查：找不到则暂停并提示，按钮保持【开始】
        wx = find_wechat_window()
        if wx is None:
            log("错误: 未找到微信窗口，暂停采集")
            messagebox.showwarning(
                "微信未找到",
                "未找到微信窗口。\n\n请先启动微信后再点击【开始】。")
            return
        log(f"已找到微信窗口: [{wx[1]}] (PID={wx[2]})")
        # 启动 ESC 键监听（采集中按 ESC 立即停止；幂等）
        if self.esc.start():
            log("ESC 键监听已启用（采集中按 ESC 可立即停止）")
        else:
            log("警告: ESC 键监听启动失败")
        # 锁定鼠标移动（防止误操作干扰采集；程序 SetCursorPos 不受影响）
        if self.mouse_lock.start():
            log("鼠标已锁定（移动/点击/滚轮禁用）")
        else:
            log("警告: 鼠标锁定启动失败")
        # 锁定键盘输入（仅放行 ESC 和程序自己的输入）
        self.esc._block_keys = True
        log("键盘已锁定（仅 ESC 可用）")
        # 立即前置微信并靠左半边屏幕（已就位则跳过）
        moved = snap_wechat_left(wx[0])
        log(f"微信窗口: 前置并靠左半屏{'（已就位，跳过）' if not moved else ''}")

        # 进入运行状态
        self.busy = True
        self.stop_event.clear()
        try:
            self.btn_start.config(state=tk.NORMAL, text="结束")
        except Exception:
            pass
        self._set_progress(f"进度: 0/{len(todo)} 开始采集")
        # main 窗口靠右半边屏幕（主线程执行）
        self._snap_main_right()
        threading.Thread(target=self._run_collection,
                         args=(todo, desc, max_count, wx), daemon=True).start()

    def _run_collection(self, todo, desc, max_count, wx):
        """采集线程：遍历任务，每个任务执行点位操作流程"""
        total = len(todo)
        done_n = 0
        try:
            for n, (idx, url, name, st) in enumerate(todo):
                if self.stop_event.is_set():
                    log("已停止：中止后续链接")
                    break
                log(f"【{n + 1}/{total}】[{idx}] {name}  {url[:45]}{'...' if len(url) > 45 else ''}")
                # main 界面靠右半边屏幕（通过队列交给主线程处理）
                self.ui_queue.put(("snap",))
                ok = self._process_task(idx, url, name, wx)
                if self.stop_event.is_set():
                    log("已停止：中止后续链接")
                    break
                if ok:
                    update_input_status(idx, "done")
                    log(f"任务 {idx} 完成，状态=done")
                    done_n += 1
                else:
                    update_input_status(idx, f"error:{self.last_error or '流程失败'}")
                    log(f"任务 {idx} 失败，状态=error: {self.last_error}")
                # 通知主线程刷新任务区（状态已写入 input.csv）
                self.ui_queue.put(("refresh_input",))
                self._set_progress(f"进度: {n + 1}/{total}（{name}）",
                                   (n + 1) / total * 100)
        except Exception as e:
            log(f"采集线程异常: {e}")
        finally:
            # 解锁鼠标和键盘（防止采集结束后仍被锁定）
            self.mouse_lock.stop()
            self.esc._block_keys = False
            log("鼠标/键盘已解锁")
            self.ui_queue.put(("finish", self.stop_event.is_set(), total, done_n))

    def _sleep(self, seconds):
        """可中断 sleep：分段检查停止信号。被停止返回 True，正常结束返回 False"""
        end = time.time() + seconds
        while time.time() < end:
            if self.stop_event.is_set():
                return True
            time.sleep(min(0.2, max(0.01, end - time.time())))
        return False

    def _process_task(self, idx, url, name, wx):
        """单个任务流程：
        1) 聚焦微信窗口，检查是否左半屏，不是则移动并等待0.5秒
        2) 点击点位1 -> 等0.5秒 -> 输入1 -> 删除 -> 点击点位2
        3) Ctrl+Shift+W
        4) 再次：点位1 -> 输入1 -> 删除 -> 点位2（触发新窗口）
        5) 新窗口调整到左半屏并聚焦（位置没错则仅聚焦）
        6) 点击点位3 -> 全选删除 -> 输入任务链接（模仿旧项目输入）-> 按回车
        7) 等待5秒 -> 点击点位4"""
        # 1) 聚焦微信并确保左半屏
        if wx:
            moved = snap_wechat_left(wx[0])
            if moved:
                log(f"微信窗口: 已移动到左半屏 [{wx[1]}]，等待0.3秒")
                if self._sleep(0.3):
                    log("已停止：中止当前任务")
                    return False
            else:
                log(f"微信窗口: 已在左半屏 [{wx[1]}]，不动")
        # 加载点位
        pts = {p[0]: p for p in load_points()}
        p1 = pts.get(1)
        p2 = pts.get(2)
        p11 = pts.get(11)
        window_split = self.window_split_var.get()
        if not p1 or not p2:
            log("错误: 缺少点位1或点位2，任务失败")
            self.last_error = "缺少点位1/2"
            return False
        # 2) 点击点位1（搜索框）-> 输入1 -> 删除 -> 点击点位2
        log(f"点击点位1({p1[2]},{p1[3]}) {p1[1]}")
        mouse_click(p1[2], p1[3])
        log("输入 1")
        type_text("1")
        if self._sleep(0.3):
            log("已停止：中止当前任务")
            return False
        log("删除")
        ctrl_key("A")          # 全选（光标在末尾时 Delete 删不掉，先全选）
        if self._sleep(0.15):
            log("已停止：中止当前任务")
            return False
        key_press(VK_DELETE)
        if self._sleep(0.3):
            log("已停止：中止当前任务")
            return False
        log(f"点击点位2({p2[2]},{p2[3]}) {p2[1]}")
        mouse_click(p2[2], p2[3])
        if self._sleep(0.5):  # 点击点位2后等待 0.5 秒
            log("已停止：中止当前任务")
            return False
        # 窗口分离开启：点击点位2后额外点击点位11
        if window_split:
            if not p11:
                log("错误: 缺少点位11（窗口分离已开启），任务失败")
                self.last_error = "缺少点位11"
                return False
            try:
                px11, py11 = int(p11[2]), int(p11[3])
            except (TypeError, ValueError):
                px11 = py11 = 0
            if px11 <= 0 and py11 <= 0:
                log("错误: 点位11坐标未采集（窗口分离已开启），任务失败")
                self.last_error = "缺少点位11"
                return False
            log(f"点击点位11({px11},{py11}) {p11[1]}")
            mouse_click(px11, py11)
            if self._sleep(0.3):
                log("已停止：中止当前任务")
                return False
        # 3) Ctrl+Shift+W
        log("触发 Ctrl+Shift+W")
        ctrl_shift_key("W")
        if self._sleep(0.8):
            log("已停止：中止当前任务")
            return False
        # 4) 再次：点位1 -> 输入1 -> 删除 -> 点位2（触发新窗口）
        log(f"点击点位1({p1[2]},{p1[3]}) {p1[1]}")
        mouse_click(p1[2], p1[3])
        log("输入 1")
        type_text("1")
        if self._sleep(0.3):
            log("已停止：中止当前任务")
            return False
        log("删除")
        ctrl_key("A")
        if self._sleep(0.15):
            log("已停止：中止当前任务")
            return False
        key_press(VK_DELETE)
        if self._sleep(0.3):
            log("已停止：中止当前任务")
            return False
        log(f"点击点位2({p2[2]},{p2[3]}) {p2[1]}")
        mouse_click(p2[2], p2[3])
        if self._sleep(0.5):  # 点击点位2后等待 0.5 秒
            log("已停止：中止当前任务")
            return False
        # 窗口分离开启：点击点位2后额外点击点位11
        if window_split:
            if not p11:
                log("错误: 缺少点位11（窗口分离已开启），任务失败")
                self.last_error = "缺少点位11"
                return False
            try:
                px11, py11 = int(p11[2]), int(p11[3])
            except (TypeError, ValueError):
                px11 = py11 = 0
            if px11 <= 0 and py11 <= 0:
                log("错误: 点位11坐标未采集（窗口分离已开启），任务失败")
                self.last_error = "缺少点位11"
                return False
            log(f"点击点位11({px11},{py11}) {p11[1]}")
            mouse_click(px11, py11)
            if self._sleep(0.3):
                log("已停止：中止当前任务")
                return False
        # 5) 新窗口：调整到左半屏并聚焦（已就位则仅聚焦）
        new_win = get_foreground_window_info()
        if new_win:
            moved = snap_wechat_left(new_win[0])
            log(f"新窗口: 调整左半屏并聚焦{'（已就位，仅聚焦）' if not moved else ''} [{new_win[1]}]")
        else:
            log("警告: 未获取到新窗口")
        # 6) 点击点位3 -> 全选删除 -> 输入任务链接（模仿旧项目输入）
        p3 = pts.get(3)
        if not p3:
            log("错误: 缺少点位3，无法输入链接")
            self.last_error = "缺少点位3"
            return False
        log(f"点击点位3({p3[2]},{p3[3]}) {p3[1]}")
        mouse_click(p3[2], p3[3])
        ctrl_key("A")          # 全选
        if self._sleep(0.15):
            log("已停止：中止当前任务")
            return False
        key_press(VK_DELETE)    # 清空
        if self._sleep(0.15):
            log("已停止：中止当前任务")
            return False
        log(f"输入任务链接(剪贴板粘贴): {url}")
        if not set_clipboard_text(url):
            log("错误: 剪贴板写入失败，改用逐字输入")
            type_text(url)
        else:
            ctrl_key("V")       # 粘贴
        if self._sleep(0.3):
            log("已停止：中止当前任务")
            return False
        log("按回车")
        key_press(VK_RETURN)
        log("等待 5 秒加载...")
        if self._sleep(5):
            log("已停止：中止当前任务")
            return False
        # 7) 点击点位4
        p4 = pts.get(4)
        if not p4:
            log("错误: 缺少点位4，任务失败")
            self.last_error = "缺少点位4"
            return False
        log(f"点击点位4({p4[2]},{p4[3]}) {p4[1]}")
        mouse_click(p4[2], p4[3])
        # 点击作者名称后等待 5 秒
        if self._sleep(5):
            log("已停止：中止当前任务")
            return False
        # 8) 文章列表页：OCR 采集循环
        return self._collect_articles(pts, name)

    def _check_fetch_results(self):
        """检查后台抓取线程结果，处理写入记录和时间范围检测
        返回 True 表示需要停止（达到停止条件）"""
        if not hasattr(self, "_pending_futures") or not self._pending_futures:
            return False
        stop_needed = False
        finished = []
        for future, link, name in self._pending_futures:
            if not future.done():
                continue
            finished.append((future, link, name))
            try:
                r = future.result()
                if r.get("error"):
                    log(f"后台抓取失败: {link} - {r.get('error')}")
                    continue
                title = r.get("title") or ""
                pub_time = r.get("pub_time") or ""
                save_path = r.get("save_path")
                log(f"后台抓取完成: 标题[{title}] 时间[{pub_time}] 保存[{save_path or '未保存'}]")
                # 写入采集记录（单点一次性写入，互动数据一起带入）
                rec = append_collected(name, pub_time, title, link,
                                       reads=r.get("reads", -1), likes=r.get("likes", -1),
                                       forwards=r.get("forwards", -1),
                                       favorites=r.get("favorites", -1),
                                       comments=r.get("comments", -1),
                                       write_time=r.get("write_time"),
                                       shot=r.get("shot") or "",
                                       read_shot=r.get("read_shot") or "")
                if rec == "skip":
                    log(f"采集记录已存在，跳过写入: {link}")
                elif rec == "error":
                    log("采集记录写入失败")
                # 记录一次文章获取成功
                self.collected_count = getattr(self, "collected_count", 0) + 1
                # 时间范围检测（延后判定）
                if pub_time and getattr(self, "time_range_dates", None):
                    try:
                        d = date.fromisoformat(pub_time[:10])
                        start_d, end_d = self.time_range_dates
                        if d < start_d or d > end_d:
                            self._time_out_count = getattr(self, "_time_out_count", 0) + 1
                            if self._time_out_count > 2:
                                log(f"文章时间 {pub_time} 不在范围内({start_d}~{end_d})，已超2篇容错")
                                stop_needed = True
                            else:
                                log(f"文章时间 {pub_time} 不在范围内（置顶旧文章，容忍 {self._time_out_count}/2）")
                    except Exception:
                        pass
                # 最大下载数量检测
                mc = getattr(self, "max_count_setting", None)
                if mc and self.collected_count >= mc:
                    log(f"已达到最大下载数量 {mc}")
                    stop_needed = True
            except Exception as e:
                log(f"处理后台结果异常: {e}")
        # 移除已完成的任务
        for item in finished:
            self._pending_futures.remove(item)
        return stop_needed

    def _wait_all_fetches(self):
        """等待所有后台抓取线程完成"""
        if not hasattr(self, "_pending_futures"):
            return
        log(f"等待 {len(self._pending_futures)} 个后台抓取任务完成...")
        for future, link, name in self._pending_futures:
            try:
                future.result(timeout=30)  # 最多等30秒
            except Exception:
                pass
        # 最后检查一次结果（先检查再清空，避免丢失最后一批结果）
        self._check_fetch_results()
        self._pending_futures.clear()

    # ---------- 文章采集循环（OCR） ----------
    def _collect_articles(self, pts, name):
        """文章列表循环采集：
        循环: OCR识别卡片 -> 依次点击(5秒后文章操作) -> 全部点完 -> 滚动 -> 再OCR
        停止条件: 无卡片 / 达到最大数量 / 文章时间超出范围"""
        # 本任务成功下载计数
        self.collected_count = 0
        self._time_out_count = 0   # 时间范围外容错计数（置顶旧文章最多2篇）
        self._exit_loop = False
        self._found_start = False  # 自定义模式：是否已找到范围开始点
        # 等待文章列表加载（由 OCR 识别过程自然加载，无需额外等待）
        p5 = pts.get(5)
        p7 = pts.get(7)
        p12 = pts.get(12)
        if not p5 or not p7:
            log("错误: 缺少点位5/7（截图区域），任务失败")
            self.last_error = "缺少点位5/7"
            return False
        if not p12:
            log("错误: 缺少点位12（文章x轴线），任务失败")
            self.last_error = "缺少点位12"
            return False
        p12_x = int(p12[2])
        # 由两个对角点确定截图区域（自动归一化顺序）
        x1, y1 = int(p5[2]), int(p5[3])
        x2, y2 = int(p7[2]), int(p7[3])
        box = (min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2))
        # 滚动距离：优先用界面配置，无配置则默认屏幕高度 70%
        try:
            scroll_px = int(float(getattr(self, "scroll_px_var").get()))
        except (AttributeError, ValueError):
            scroll_px = int(_u32().GetSystemMetrics(SM_CYSCREEN) * 0.7)
        if scroll_px <= 0:
            scroll_px = int(_u32().GetSystemMetrics(SM_CYSCREEN) * 0.7)
        log(f"文章列表 OCR 区域: {box}，滚动距离 {scroll_px}px")
        loop_n = 0
        while True:
            if self.stop_event.is_set():
                log("已停止：中止文章采集")
                break
            if self._exit_loop:
                break
            # 检查后台抓取线程结果（延后判定停止条件）
            if self._check_fetch_results():
                log("后台任务触发停止条件，走完当前任务后停止")
                self._exit_loop = True
                break
            loop_n += 1
            log(f"--- 列表循环 {loop_n}：OCR 识别中 ---")
            # 识别文章卡片：最多 5 次机会（列表可能还在加载）
            cards = []
            for attempt in range(1, 6):
                if self.stop_event.is_set():
                    log("已停止：中止文章采集")
                    break
                try:
                    items = ocr_region(box)
                except Exception as e:
                    log(f"OCR 失败: {e}")
                    self.last_error = f"OCR 失败: {e}"
                    return False
                cards = find_time_items(items)
                if cards:
                    break
                log(f"OCR 未识别到文章卡片，重试 {attempt}/5...")
            if not cards:
                log("错误: OCR 未识别到文章卡片（列表页异常），任务失败")
                self.last_error = "未识别到文章卡片"
                return False
            log(f"识别到 {len(cards)} 个文章卡片（含时间）")
            # ---- 遍历卡片：统一逻辑，自定义模式额外做时间范围判断/跳过 ----
            is_custom = getattr(self, "is_custom_mode", False)
            tr_dates = getattr(self, "time_range_dates", None)
            start_d = end_d = None
            pinned_count = 0
            page_has_in_range = False
            _today = date.today()
            if is_custom and tr_dates:
                start_d, end_d = tr_dates
                # 置顶识别：仅第一页前3个点位，出现旧->新回升说明有置顶（最多2篇）
                if loop_n == 1:
                    for i in range(1, min(3, len(cards))):
                        dp = resolve_article_date(cards[i - 1][2], _today)
                        dc = resolve_article_date(cards[i][2], _today)
                        if dp and dc and dc > dp:
                            pinned_count = i
                            break
                if pinned_count:
                    log(f"识别到 {pinned_count} 个置顶文章（时间跳变），置顶不计入范围定位")
            # 统一按 y 从上到下遍历
            for n, card in enumerate(sorted(cards, key=lambda c: c[1])):
                if self.stop_event.is_set():
                    log("已停止：中止文章采集")
                    break
                cx, cy, text = card
                # 自定义模式：解析日期并判断范围，范围外跳过
                d = None
                if is_custom and tr_dates:
                    d = resolve_article_date(text, _today)
                    is_pinned = n < pinned_count
                    in_range = d is not None and start_d <= d <= end_d
                    if in_range:
                        if not is_pinned:
                            self._found_start = True
                            page_has_in_range = True
                    else:
                        tag = "置顶" if is_pinned else ""
                        log(f"跳过卡片 ({cx},{cy}) 时间[{text}] 日期[{d or '无法解析'}] 不在范围 {start_d}~{end_d}{('（' + tag + '）') if tag else ''}")
                        continue
                click_time = time.strftime("%Y-%m-%d %H:%M:%S")  # 点击时间点位的时间
                reads = extract_reads(text)   # 列表页识别到的阅读数(-1=未识别到)
                likes = extract_likes(text)   # 列表页识别到的点赞数(-1=未识别到)
                if is_custom and tr_dates:
                    log(f"点击文章卡片 {n + 1}/{len(cards)} (x=点位12:{p12_x}, y={cy}) 时间[{text}] 阅读[{reads}] 赞[{likes}] 日期[{d}]")
                else:
                    log(f"点击文章卡片 {n + 1}/{len(cards)} (x=点位12:{p12_x}, y={cy}) 时间[{text}] 阅读[{reads}] 赞[{likes}]")
                mouse_click(p12_x, cy)
                r = self._collect_article_link(pts, name, click_time, reads, likes)
                if r is False:
                    log("文章操作失败，任务标记 error")
                    return False
                if r == "stop":
                    log("达到停止条件，退出文章采集循环")
                    self._exit_loop = True
                    break
                log("Ctrl+W 关闭文章")
                ctrl_key("W")
                if self._sleep(0.5):  # 关闭标签页后等待 0.5 秒
                    log("已停止：中止文章采集")
                    break
                # 每处理完一张卡片检查后台结果（及时写入CSV）
                if self._check_fetch_results():
                    log("后台任务触发停止条件，退出文章采集循环")
                    self._exit_loop = True
                    break
            # 自定义模式停止判定：已找到开始点，但本页无任何正常范围内点位 -> 范围结束
            if is_custom and tr_dates and self._found_start and not page_has_in_range:
                log("已找到范围结束点（本页无范围内点位），结束文章采集")
                break
            # 全部点击完毕：滚动前先检查后台结果（可能已触发停止条件）
            if self._check_fetch_results():
                log("后台任务触发停止条件，不再滚动，结束文章采集")
                self._exit_loop = True
                break
            if self._exit_loop:  # 达到停止条件则不滚动
                break
            log(f"全部点击完毕，移动鼠标到点位7({p7[2]},{p7[3]}) 向下滚动 {scroll_px}px")
            scroll_down_at(int(p7[2]), int(p7[3]), scroll_px)
            log("等待 1 秒列表刷新...")
            if self._sleep(1):
                log("已停止：中止当前任务")
                break
        # 汇总本次任务收集的文章链接
        if getattr(self, "collected_links", None):
            log(f"本任务共收集 {len(self.collected_links)} 个文章链接:")
            for n, link in enumerate(self.collected_links, 1):
                log(f"  [{n}] {link}")
        # 等待所有后台抓取任务完成
        self._wait_all_fetches()
        return True

    def _collect_article_link(self, pts, name, click_time=None, reads=-1, likes=-1):
        """正式文章操作：3次尝试复制链接（点位8 -> OCR找复制链接 -> 点击 -> 检查剪贴板）
        -> fetch_article 抓取标题/时间并保存 HTML
        click_time: 点击时间点位的时间（写入 CSV 用）
        reads/likes: 列表页 OCR 提取的阅读/点赞数（-1=未识别到，写入 CSV 用）
        返回: True=成功继续 / "stop"=达到停止条件退出循环 / False=失败(error)"""
        p8 = pts.get(8)
        p9 = pts.get(9)
        p10 = pts.get(10)
        p13 = pts.get(13)
        p14 = pts.get(14)
        if not p8 or not p9 or not p10:
            log("错误: 缺少点位8/9/10，任务失败")
            self.last_error = "缺少点位8/9/10"
            return False
        box = (min(int(p9[2]), int(p10[2])), min(int(p9[3]), int(p10[3])),
               max(int(p9[2]), int(p10[2])), max(int(p9[3]), int(p10[3])))
        # 复制链接：最多尝试 3 次
        link = None
        for attempt in range(1, 4):
            if self.stop_event.is_set():
                log("已停止：中止当前任务")
                return False
            log(f"--- 复制链接尝试 {attempt}/3 ---")
            log(f"点击点位8({p8[2]},{p8[3]}) {p8[1]}")
            mouse_click(int(p8[2]), int(p8[3]))
            # OCR 找"复制链接"（识别到说明文章已加载）
            target = None
            for ocr_try in range(3):  # 最多重试3次OCR
                if self.stop_event.is_set():
                    log("已停止：中止当前任务")
                    return False
                log(f"OCR 识别复制链接区域: {box}")
                try:
                    items = ocr_region(box)
                except Exception as e:
                    log(f"OCR 失败: {e}")
                    self.last_error = f"OCR 失败: {e}"
                    return False
                target = next((it for it in items if "复制链接" in it[2] or "复制" in it[2]), None)
                if target:
                    break
                log(f"未识别到'复制链接'，重试OCR...({ocr_try + 1}/3)")
            if not target:
                log(f"尝试{attempt}: 未识别到'复制链接'")
                continue
            tx, ty = target[0], target[1]
            log(f"找到'复制链接' ({tx},{ty}) [{target[2]}]，点击")
            # 点击前清空剪贴板，确保检测到的一定是新复制的链接
            clear_clipboard()
            if self._sleep(0.5):
                log("已停止：中止当前任务")
                return False
            before = read_clipboard_text()
            mouse_click(tx, ty)
            # 初始化截图变量(闭包捕获引用, 后续赋值会同步到闭包)
            shot_b64 = None
            read_shot_b64 = None
            # 点击"复制链接"后：截图底部互动栏区域(点位13/14) -> base64
            capture_4m = getattr(self, "capture_4metrics_var", None)
            if p13 and p14 and capture_4m and capture_4m.get():
                try:
                    bx1, by1 = int(p13[2]), int(p13[3])
                    bx2, by2 = int(p14[2]), int(p14[3])
                    if bx1 > 0 and by1 > 0 and bx2 > 0 and by2 > 0:
                        shot_b64 = capture_region_base64(
                            (min(bx1, bx2), min(by1, by2), max(bx1, bx2), max(by1, by2)),
                            scale=1.0)
                        log(f"底部互动栏截图完成 (base64 {len(shot_b64) if shot_b64 else 0} B)")
                except Exception as e:
                    log(f"互动栏截图失败: {e}")
            # 轮询等待剪贴板更新（最多 10 秒，每 0.5 秒查一次 = 20 次）
            deadline = time.time() + 10
            while time.time() < deadline:
                if self._sleep(0.5):
                    log("已停止：中止当前任务")
                    return False
                cur = read_clipboard_text()
                if cur and cur != before and "mp.weixin.qq.com" in cur:
                    link = cur
                    break
            if link:
                break
            log(f"尝试{attempt}: 剪贴板未更新为文章链接")
        if not link:
            log("错误: 3次尝试复制链接均失败，任务失败")
            self.last_error = "复制链接失败(3次)"
            return False
        if not hasattr(self, "collected_links"):
            self.collected_links = []
        self.collected_links.append(link)
        log(f"已复制文章链接: {link}")
        # ---- 异步抓取文章：标题/时间 + 保存 HTML（后台执行，不阻塞主流程） ----
        def _fetch_task(link, name, shot_b64, read_shot_b64):
            """后台抓取任务：抓取标题/时间 + 保存 HTML + 互动数据
            返回统一 dict：title/pub_time/save_path/error + 互动数据(默认0)"""

            def _ok(**kw):
                base = {"title": "", "pub_time": "", "save_path": None, "error": None,
                        "reads": -1, "likes": -1, "forwards": -1,
                        "favorites": -1, "comments": -1, "shot": "", "read_shot": ""}
                base.update(kw)
                return base

            def _err(msg):
                return {"title": "", "pub_time": "", "save_path": None, "error": msg,
                        "reads": -1, "likes": -1, "forwards": -1,
                        "favorites": -1, "comments": -1, "shot": "", "read_shot": ""}

            try:
                save_dir = os.path.join(self.session_dir, clean_filename(name))
                os.makedirs(save_dir, exist_ok=True)
            except Exception:
                save_dir = None
            save_path = None
            if save_dir:
                fetched = fetch_article(link, save_path=None)
                if fetched is None:
                    return _err("标题/时间获取失败")
                title, pub_time = fetched
                _stem = clean_filename(title or "untitled")
                _date = (pub_time or "")[:10]
                _fname = f"{_date}_{_stem}.html" if _date else f"{_stem}.html"
                save_path = os.path.join(save_dir, _fname)
                fetched2 = fetch_article(link, save_path)
                if fetched2 is None:
                    return _err("HTML 保存失败")
            else:
                fetched = fetch_article(link)
                if fetched is None:
                    return _err("抓取失败")
                title, pub_time = fetched
            # TODO(采集逻辑): 后续如需转发/喜欢/评论, 在 _ok 中填入对应字段
            return _ok(title=title, pub_time=pub_time, save_path=save_path,
                       write_time=click_time, reads=reads, likes=likes,
                       shot=shot_b64, read_shot=read_shot_b64)
        # 提交到线程池异步执行
        # ---- 采集阅读数：滚动到底 → Ctrl+W关闭 → 搜索链接 → 输入回车 ----
        capture_r = getattr(self, "capture_read_var", None)
        if capture_r and capture_r.get():
            p15 = pts.get(15)
            p17 = pts.get(17)
            if p15:
                try:
                    px15, py15 = int(p15[2]), int(p15[3])
                    log(f"采集阅读数：移动鼠标到点位15({px15},{py15})")
                    _u32().SetCursorPos(px15, py15)
                    time.sleep(0.05)
                    # 连续3次快速滚动，每次10000px，总耗时<0.5秒
                    for _round in range(3):
                        ticks = 10000 // 120
                        for _ in range(ticks):
                            _u32().mouse_event(MOUSEEVENTF_WHEEL, 0, 0, -WHEEL_DELTA, None)
                        log(f"采集阅读数：第{_round+1}/3次快速滚动完成")
                        time.sleep(0.05)
                except Exception as e:
                    log(f"采集阅读数滚动失败: {e}")
            if p15:
                p16 = pts.get(16)
                # 等0.5秒 → Ctrl+W关闭标签 → 等0.5秒
                if self._sleep(0.5):
                    log("已停止：中止当前任务")
                    return False
                log("采集阅读数：Ctrl+W 关闭标签页")
                ctrl_key("W")
                if self._sleep(0.5):
                    log("已停止：中止当前任务")
                    return False
                if p17:
                    px17, py17 = int(p17[2]), int(p17[3])
                    log(f"采集阅读数：点击点位17({px17},{py17}) 搜索按钮")
                    mouse_click(px17, py17)
                    ctrl_key("A")          # 全选
                    if self._sleep(0.15):
                        log("已停止：中止当前任务")
                        return False
                    key_press(VK_DELETE)    # 清空
                    if self._sleep(0.15):
                        log("已停止：中止当前任务")
                        return False
                    log("采集阅读数：输入链接")
                    if not set_clipboard_text(link):
                        type_text(link)
                    else:
                        ctrl_key("V")       # 粘贴
                    if self._sleep(0.15):
                        log("已停止：中止当前任务")
                        return False
                    log("采集阅读数：按回车")
                    key_press(VK_RETURN)
                    if self._sleep(5):
                        log("已停止：中止当前任务")
                        return False
                    # 等2秒加载 → 截图点位15/16区域(阅读数) → base64
                    if self._sleep(2):
                        log("已停止：中止当前任务")
                        return False
                    p16 = pts.get(16)
                    try:
                        bx1, by1 = int(p15[2]), int(p15[3])
                        bx2, by2 = int(p15[2]), int(p15[3])
                        if p16:
                            bx2, by2 = int(p16[2]), int(p16[3])
                        if bx1 > 0 and by1 > 0 and bx2 > 0 and by2 > 0:
                            read_shot_b64 = capture_region_base64(
                                (min(bx1, bx2), min(by1, by2), max(bx1, bx2), max(by1, by2)),
                                scale=0.75)
                            log(f"阅读数截图完成 (base64 {len(read_shot_b64) if read_shot_b64 else 0} B)")
                    except Exception as e:
                        log(f"阅读数截图失败: {e}")

        # 提交到线程池异步执行(截图数据已就绪, 参数传递避免闭包时序问题)
        if not hasattr(self, "_fetch_executor"):
            self._fetch_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="fetch")
        if not hasattr(self, "_pending_futures"):
            self._pending_futures = []
        future = self._fetch_executor.submit(_fetch_task, link, name, shot_b64, read_shot_b64)
        self._pending_futures.append((future, link, name))
        # 不等待结果，直接返回继续处理下一个卡片
        return True

    def _finish_collection(self, stopped, total, done_n):
        """采集结束：恢复按钮/进度状态（main 保持右半屏，不恢复居中）"""
        self.busy = False
        try:
            self.btn_start.config(state=tk.NORMAL, text="开始")
        except Exception:
            pass
        if stopped:
            self._set_progress(f"进度: 已停止（完成 {done_n}/{total}）",
                               done_n / total * 100 if total else 0)
            log(f"已停止（完成 {done_n}/{total}）")
        else:
            self._set_progress(f"进度: 完成（{done_n}/{total}）", 100)
            log(f"完成: {done_n}/{total} 个（框架阶段为模拟，待接入真实采集流程）")

    def _set_progress(self, text, value=None):
        """进度更新：放入队列，主线程处理（子线程安全）"""
        try:
            self.ui_queue.put(("progress", text, value or 0))
        except Exception:
            pass

    # ---------- 关闭 ----------
    def on_exit(self):
        self._save_state()
        show_taskbar()              # 恢复任务栏
        log(f"退出（设置已记忆 -> {UI_STATE_FILE}）")
        self.root.destroy()


# ================= 入口 =================
# ================= 依赖自检 =================
REQUIRED_PACKAGES = [
    ("rapidocr_onnxruntime", "rapidocr_onnxruntime"),
    ("requests", "requests"),
    ("PIL", "Pillow"),
]


def check_dependencies():
    """启动时检查必需依赖是否安装，缺少则给出安装命令并退出"""
    missing = []
    for module_name, pip_name in REQUIRED_PACKAGES:
        try:
            __import__(module_name)
        except ImportError:
            missing.append(pip_name)
    if missing:
        print("=" * 50)
        print("[错误] 缺少以下依赖，请先安装：")
        print("=" * 50)
        print(f"\npip install {" ".join(missing)}\n")
        print("=" * 50)
        sys.exit(1)


def main():
    check_dependencies()
    try:
        ctypes.WinDLL("kernel32").SetConsoleOutputCP(65001)
    except Exception:
        pass
    enable_dpi_awareness()
    # 任何退出路径都恢复任务栏（含异常退出）
    import atexit
    atexit.register(show_taskbar)
    root = tk.Tk()
    app = App(root)

    if "--ui-shot" in sys.argv:
        # 截图自检（调试用）：1.5 秒后前置窗口截图并退出
        i = sys.argv.index("--ui-shot")
        shot_path = sys.argv[i + 1] if len(sys.argv) > i + 1 else "_ui.png"
        root.after(1500, lambda: (app.start(),
                                  root.attributes("-topmost", True),
                                  root.lift(),
                                  root.after(400, lambda: (
                                      _grab_screen(shot_path), root.destroy()))))
    else:
        root.after(100, app.start)
    root.mainloop()


def _grab_screen(path):
    from PIL import ImageGrab
    ImageGrab.grab().save(path)
    print(f"截图已保存 -> {path}")


if __name__ == "__main__":
    main()

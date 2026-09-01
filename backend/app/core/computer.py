# -*- coding: utf-8 -*-
from . import obs
import queue as _queue
import base64
import io
import os
import tempfile
from PIL import Image, ImageGrab
"""backend.app.services.computer: 电脑交互原语模块

把 main.py / core.win32util / core.image_ocr 中分散的"电脑交互"方法统一整理，
封装为可复用的模块，供采集流程（以及未来新增流程）多次调用。
本模块自包含，仅依赖标准库 + Pillow（截图），不依赖其它业务模块。

涵盖功能（按类划分）:
    窗口查询   : 查找微信窗口 / 顶层窗口列表 / 前台窗口信息
    窗口控制   : 强制前置 / 靠左半屏 / 隐藏·恢复任务栏
    鼠标       : 移动 / 左键单击 / 滚轮向上·向下滚动
    键盘       : 文本输入 / Ctrl 组合键 / Ctrl+Shift 组合键 / 单键
    剪贴板     : 读取文本 / 写入文本 / 清空
    截图       : 屏幕区域截图（保存到系统缓存 / 转 base64）

线程说明:
    * 输入模拟（SendInput / keybd_event / mouse_event）可在任意线程调用。
"""

import ctypes
import queue
import threading
import time
from ctypes import wintypes as wt

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------
SW_RESTORE = 9
SW_HIDE = 0
SW_SHOW = 5
SWP_NOZORDER = 0x0004
SWP_FRAMECHANGED = 0x0020
SWP_NOMOVE = 0x0002
SWP_NOSIZE = 0x0001
SWP_SHOWWINDOW = 0x0040
SWP_NOACTIVATE = 0x0010
HWND_TOP = 0
HWND_TOPMOST = -1
HWND_NOTOPMOST = -2

SM_CXSCREEN = 0
SM_CYSCREEN = 1

VK_MENU = 0x12
VK_CONTROL = 0x11
VK_SHIFT = 0x10
VK_RETURN = 0x0D
VK_DELETE = 0x2E

KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
INPUT_KEYBOARD = 1
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_WHEEL = 0x0800
WHEEL_DELTA = 120

CF_UNICODETEXT = 13

WM_KEYDOWN = 0x0100
WM_LBUTTONDOWN = 0x0201
WM_RBUTTONDOWN = 0x0204
WM_QUIT = 0x0012
WH_MOUSE_LL = 14
SM_CXDOUBLECLK = 36
SM_CYDOUBLECLK = 37

TH32CS_SNAPPROCESS = 0x00000002
WECHAT_MAIN_EXES = ("wechat.exe", "weixin.exe")

WNDENUMPROC = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
HOOKPROC = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_int, wt.WPARAM, wt.LPARAM)


# ---------------------------------------------------------------------------
# Win32 / 结构体
# ---------------------------------------------------------------------------
class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class MSLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [("pt", POINT), ("mouseData", wt.DWORD), ("flags", wt.DWORD),
                ("time", wt.DWORD), ("dwExtraInfo", ctypes.POINTER(wt.ULONG))]


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


# ---------------------------------------------------------------------------
# 底层 user32 / kernel32 初始化（懒加载）
# ---------------------------------------------------------------------------
_user32 = None
_kernel32 = None


def _u32():
    global _user32
    if _user32 is None:
        u = ctypes.WinDLL("user32", use_last_error=True)
        u.EnumWindows.argtypes = [WNDENUMPROC, wt.LPARAM]
        u.EnumWindows.restype = wt.BOOL
        u.GetWindowThreadProcessId.argtypes = [wt.HWND, ctypes.POINTER(wt.DWORD)]
        u.GetWindowThreadProcessId.restype = wt.DWORD
        u.GetWindowTextW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
        u.GetWindowTextW.restype = ctypes.c_int
        u.IsWindowVisible.argtypes = [wt.HWND]
        u.IsWindowVisible.restype = wt.BOOL
        u.ShowWindow.argtypes = [wt.HWND, ctypes.c_int]
        u.ShowWindow.restype = wt.BOOL
        u.SetForegroundWindow.argtypes = [wt.HWND]
        u.SetForegroundWindow.restype = wt.BOOL
        u.SetWindowPos.argtypes = [wt.HWND, wt.HWND, ctypes.c_int, ctypes.c_int,
                                   ctypes.c_int, ctypes.c_int, wt.UINT]
        u.SetWindowPos.restype = wt.BOOL
        u.GetWindowRect.argtypes = [wt.HWND, ctypes.POINTER(wt.RECT)]
        u.GetWindowRect.restype = wt.BOOL
        u.GetSystemMetrics.argtypes = [ctypes.c_int]
        u.GetSystemMetrics.restype = ctypes.c_int
        u.keybd_event.argtypes = [wt.BYTE, wt.BYTE, wt.DWORD, ctypes.POINTER(wt.ULONG)]
        u.keybd_event.restype = None
        u.SetWindowsHookExW.argtypes = [ctypes.c_int, HOOKPROC, wt.HINSTANCE, wt.DWORD]
        u.SetWindowsHookExW.restype = ctypes.c_void_p
        u.CallNextHookEx.argtypes = [ctypes.c_void_p, ctypes.c_int, wt.WPARAM, wt.LPARAM]
        u.CallNextHookEx.restype = ctypes.c_long
        u.UnhookWindowsHookEx.argtypes = [ctypes.c_void_p]
        u.UnhookWindowsHookEx.restype = wt.BOOL
        u.GetMessageW.argtypes = [ctypes.POINTER(wt.MSG), wt.HWND, wt.UINT, wt.UINT]
        u.GetMessageW.restype = wt.BOOL
        u.TranslateMessage.argtypes = [ctypes.POINTER(wt.MSG)]
        u.TranslateMessage.restype = wt.BOOL
        u.DispatchMessageW.argtypes = [ctypes.POINTER(wt.MSG)]
        u.DispatchMessageW.restype = ctypes.c_long
        u.GetDoubleClickTime.argtypes = []
        u.GetDoubleClickTime.restype = wt.UINT
        u.PostThreadMessageW.argtypes = [wt.DWORD, wt.UINT, wt.WPARAM, wt.LPARAM]
        u.PostThreadMessageW.restype = wt.BOOL
        u.RegisterClassExW.argtypes = [ctypes.c_void_p]
        u.RegisterClassExW.restype = wt.ATOM
        u.CreateWindowExW.argtypes = [wt.DWORD, wt.LPCWSTR, wt.LPCWSTR, wt.DWORD,
                                      ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                      wt.HWND, wt.HMENU, wt.HINSTANCE, wt.LPVOID]
        u.CreateWindowExW.restype = wt.HWND
        u.DefWindowProcW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
        u.DefWindowProcW.restype = ctypes.c_long
        u.DestroyWindow.argtypes = [wt.HWND]
        u.DestroyWindow.restype = wt.BOOL
        u.UnregisterClassW.argtypes = [wt.LPCWSTR, wt.HINSTANCE]
        u.UnregisterClassW.restype = wt.BOOL
        u.GetDC.argtypes = [wt.HWND]
        u.GetDC.restype = wt.HDC
        u.ReleaseDC.argtypes = [wt.HWND, wt.HDC]
        u.ReleaseDC.restype = ctypes.c_int
        u.FillRect.argtypes = [wt.HDC, ctypes.POINTER(wt.RECT), wt.HBRUSH]
        u.FillRect.restype = ctypes.c_int
        u.SetLayeredWindowAttributes.argtypes = [wt.HWND, wt.COLORREF, wt.BYTE, wt.DWORD]
        u.SetLayeredWindowAttributes.restype = wt.BOOL
        u.GetClassNameW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
        u.GetClassNameW.restype = ctypes.c_int
        u.IsWindow.argtypes = [wt.HWND]
        u.IsWindow.restype = wt.BOOL
        u.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
        u.SetCursorPos.restype = wt.BOOL
        u.mouse_event.argtypes = [wt.DWORD, wt.DWORD, wt.DWORD, wt.DWORD,
                                  ctypes.POINTER(wt.ULONG)]
        u.mouse_event.restype = None
        u.SendInput.argtypes = [wt.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
        u.SendInput.restype = wt.UINT
        u.GetForegroundWindow.argtypes = []
        u.GetForegroundWindow.restype = wt.HWND
        u.OpenClipboard.argtypes = [wt.HWND]
        u.OpenClipboard.restype = wt.BOOL
        u.EmptyClipboard.argtypes = []
        u.EmptyClipboard.restype = wt.BOOL
        u.CloseClipboard.argtypes = []
        u.CloseClipboard.restype = wt.BOOL
        u.SetClipboardData.argtypes = [wt.UINT, wt.HANDLE]
        u.SetClipboardData.restype = wt.HANDLE
        u.GetClipboardData.argtypes = [wt.UINT]
        u.GetClipboardData.restype = wt.HANDLE
        u.FindWindowW.argtypes = [wt.LPCWSTR, wt.LPCWSTR]
        u.FindWindowW.restype = wt.HWND
        _user32 = u
    return _user32


def _k32():
    global _kernel32
    if _kernel32 is None:
        k = ctypes.WinDLL("kernel32", use_last_error=True)
        k.CreateToolhelp32Snapshot.argtypes = [wt.DWORD, wt.DWORD]
        k.CreateToolhelp32Snapshot.restype = wt.HANDLE
        k.Process32FirstW.argtypes = [wt.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
        k.Process32FirstW.restype = wt.BOOL
        k.Process32NextW.argtypes = [wt.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
        k.Process32NextW.restype = wt.BOOL
        k.CloseHandle.argtypes = [wt.HANDLE]
        k.CloseHandle.restype = wt.BOOL
        k.GetModuleHandleW.argtypes = [wt.LPCWSTR]
        k.GetModuleHandleW.restype = wt.HINSTANCE
        k.GlobalAlloc.argtypes = [wt.UINT, ctypes.c_size_t]
        k.GlobalAlloc.restype = wt.HGLOBAL
        k.GlobalLock.argtypes = [wt.HGLOBAL]
        k.GlobalLock.restype = ctypes.c_void_p
        k.GlobalUnlock.argtypes = [wt.HGLOBAL]
        k.GlobalUnlock.restype = wt.BOOL
        k.GlobalSize.argtypes = [wt.HGLOBAL]
        k.GlobalSize.restype = ctypes.c_size_t
        _kernel32 = k
    return _kernel32


def enable_dpi_awareness():
    """让坐标使用物理像素，避免 DPI 缩放导致点位偏移"""
    try:
        ctypes.WinDLL("shcore").SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.WinDLL("user32").SetProcessDPIAware()
        except Exception:
            pass


# ===========================================================================
# 窗口查询
# ===========================================================================
def _enum_all_windows():
    """内部: 枚举所有顶层窗口(含隐藏/最小化/托盘)
    返回 [(hwnd, title, pid, visible), ...]"""
    u32 = _u32()
    result = []

    def callback(hwnd, lparam):
        buf = ctypes.create_unicode_buffer(512)
        u32.GetWindowTextW(hwnd, buf, 512)
        pid = wt.DWORD()
        u32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        result.append((hwnd, buf.value, pid.value, bool(u32.IsWindowVisible(hwnd))))
        return True

    u32.EnumWindows(WNDENUMPROC(callback), 0)
    return result


def _pids_by_exe(exe_names):
    """内部: 按可执行文件名集合(如 {'wechat.exe'})返回 pid 集合;
    exe_names=None 时返回空集合"""
    if not exe_names:
        return set()
    k32 = _k32()
    INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
    snap = k32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snap in (None, 0, INVALID_HANDLE_VALUE):
        return set()
    want = {n.lower() for n in exe_names}
    pids = set()
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        if k32.Process32FirstW(snap, ctypes.byref(entry)):
            while True:
                if entry.szExeFile.lower() in want:
                    pids.add(entry.th32ProcessID)
                if not k32.Process32NextW(snap, ctypes.byref(entry)):
                    break
    finally:
        k32.CloseHandle(snap)
    return pids


def find_windows(title=None, exe=None, visible_only=False):
    """【窗口查询】通用枚举查找窗口(含隐藏/托盘)，返回窗口列表(空列表=未找到)。
    参数:
      title        标题精确匹配(如 '微信')，None=不过滤
      exe          进程可执行文件名(如 'wechat.exe')，不区分大小写，None=不过滤
      visible_only True=只返回可见窗口；False(默认)=含隐藏/托盘窗口
    返回: [(hwnd, title, pid, visible), ...] 按枚举顺序
    示例:
      find_windows(exe='wechat.exe')          全部微信进程窗口
      find_windows(title='微信')merged 找标题为'微信'的窗口
      find_windows(exe='wechat.exe', visible_only=True)  可见微信窗口"""
    pids = _pids_by_exe([exe]) if exe else None
    title = str(title) if title is not None else None
    out = []
    for h, t, pid, vis in _enum_all_windows():
        if pids is not None and pid not in pids:
            continue
        if title is not None and t != title:
            continue
        if visible_only and not vis:
            continue
        out.append((h, t, pid, vis))
    return out


# ===========================================================================
# 窗口控制
# ===========================================================================
def _force_foreground(hwnd):
    """内部: 绕过 Windows 前台锁定，把窗口强制带到最顶层"""
    u32 = _u32()
    u32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE)
    _si_key(VK_MENU)
    _si_key(VK_MENU, keyup=True)
    u32.SetForegroundWindow(hwnd)
    u32.SetWindowPos(hwnd, HWND_NOTOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE)
    time.sleep(0.15)


def show_window(hwnd):
    """【窗口唤出】恢复并前置指定窗口(通用，含从托盘/最小化唤出)；返回 True"""
    u32 = _u32()
    u32.ShowWindow(hwnd, SW_RESTORE)
    time.sleep(0.1)
    u32.ShowWindow(hwnd, SW_SHOW)
    time.sleep(0.1)
    _force_foreground(hwnd)
    return True


WM_CLOSE = 0x0010


def close_window(hwnd):
    """【关闭指定窗口】发送 WM_CLOSE 消息触发正常关闭流程(通用)；返回 True
    Note: 对最小化到托盘的应用可能只是隐藏，未必退出进程"""
    _u32().PostMessageW(wt.HWND(hwnd), WM_CLOSE, 0, 0)
    return True


def move_window(hwnd, x, y, width=None, height=None):
    """【窗口移动】把窗口移到指定位置/大小并前置。
    参数:
      hwnd         窗口句柄
      x, y         目标左上角坐标
      width,height 目标宽高；None 表示保持当前尺寸
    返回 True（若想返回是否发生移动可忽略）
    """
    u32 = _u32()
    u32.ShowWindow(hwnd, SW_RESTORE)
    time.sleep(0.1)
    x, y = int(x), int(y)
    if width is None or height is None:
        rect = wt.RECT()
        u32.GetWindowRect(hwnd, ctypes.byref(rect))
        width = width if width is not None else (rect.right - rect.left)
        height = height if height is not None else (rect.bottom - rect.top)
    # 移动并调整尺寸（保留大小不变时传当前宽高）
    u32.SetWindowPos(hwnd, HWND_TOP, x, y, int(width), int(height),
                     SWP_SHOWWINDOW | SWP_NOACTIVATE)
    time.sleep(0.2)
    # 复查：若未生效再设置一次（部分窗口会拒绝首次移动）
    rect = wt.RECT()
    u32.GetWindowRect(hwnd, ctypes.byref(rect))
    if (abs(rect.left - x) > 2 or abs(rect.top - y) > 2):
        u32.SetWindowPos(hwnd, HWND_TOP, x, y, int(width), int(height),
                         SWP_SHOWWINDOW | SWP_NOACTIVATE)
        time.sleep(0.2)
    _force_foreground(hwnd)
    return True


# ===========================================================================
# 鼠标：移动 / 左键单击 / 滚动
# ===========================================================================
def mouse_click(x, y, button="left", wait_before=0, wait_after=0,
               show_feedback=True, hold_ms=80):
    """【左/右键点击】（不支持中键）
    参数:
      x, y          点击坐标
      button        点击类型: 'left'(默认) / 'right'
      wait_before   点击前等待秒数(默认 0)
      wait_after    点击后等待秒数(默认 0)
      show_feedback 是否在点击点显示红色反馈点 0.5 秒(默认 True)
      hold_ms       按住时长(按下到抬起间隔, 毫秒; 默认 80, 模拟人手按压)
    返回: (点击的x, 点击的y)
    """
    if wait_before:
        time.sleep(wait_before)
    u32 = _u32()
    x, y = int(x), int(y)
    u32.SetCursorPos(x, y)
    time.sleep(0.05)                    # 移动到位后的微小停顿
    down = MOUSEEVENTF_RIGHTDOWN if button == "right" else MOUSEEVENTF_LEFTDOWN
    up = MOUSEEVENTF_RIGHTUP if button == "right" else MOUSEEVENTF_LEFTUP
    u32.mouse_event(down, 0, 0, 0, None)
    if hold_ms:
        time.sleep(hold_ms / 1000.0)    # 按住时长(模拟人手按压)
    u32.mouse_event(up, 0, 0, 0, None)
    if show_feedback:
                flash_red_dot(x, y)            # 点击完成后显示红点(不抢点击焦点, 仅作位置反馈)
    if wait_after:
        time.sleep(wait_after)
    return x, y


def preview_point(x, y, duration=1):
    """【点位预览】在指定屏幕坐标亮一个红点 duration 秒（默认 1 秒）。
    用于确认点位位置；后台线程显示, 不阻塞调用。
    参数:
      x, y          屏幕坐标
      duration      红点显示时长(秒, 默认 1)
    返回: None
    """
    flash_red_dot(x, y, duration=duration)


def capture_point():
    """【坐标采集】阻塞等待用户在屏幕上选定一个坐标。
    交互: 左键单击红点预览 / 双击确认(取单击值) / 右键退出。
    返回: (x, y) 确认坐标, 或 None(右键退出/失败)。
    注意: 阻塞当前线程直到用户双击或右键。
    """
    u32 = _u32()
    q = _queue.Queue()
    hook_ready = threading.Event()
    hook_holder = {"h": None, "tid": None}

    def callback(code, wparam, lparam):
        if code == 0:
            ms = ctypes.cast(lparam, ctypes.POINTER(MSLLHOOKSTRUCT)).contents
            now = time.monotonic()
            if wparam == WM_LBUTTONDOWN:
                q.put(("left", ms.pt.x, ms.pt.y, now))
            elif wparam == WM_RBUTTONDOWN:
                q.put(("right", ms.pt.x, ms.pt.y, now))
        return u32.CallNextHookEx(hook_holder["h"], code, wparam, lparam)

    proc = HOOKPROC(callback)

    def hook_thread():
        hook_holder["tid"] = threading.get_ident()
        h = u32.SetWindowsHookExW(WH_MOUSE_LL, proc,
                                  _k32().GetModuleHandleW(None), 0)
        if not h:
            hook_ready.set()
            return
        hook_holder["h"] = h
        hook_ready.set()
        msg = wt.MSG()
        while u32.GetMessageW(ctypes.byref(msg), None, 0, 0) != 0:
            u32.TranslateMessage(ctypes.byref(msg))
            u32.DispatchMessageW(ctypes.byref(msg))
        u32.UnhookWindowsHookEx(h)
        hook_holder["h"] = None

    threading.Thread(target=hook_thread, daemon=True).start()
    if not hook_ready.wait(3):
        return None
    if not hook_holder["h"]:
        return None

    dbl_ms = u32.GetDoubleClickTime()
    dbl_cx = u32.GetSystemMetrics(SM_CXDOUBLECLK)
    dbl_cy = u32.GetSystemMetrics(SM_CYDOUBLECLK)
    last_x = last_y = last_t = None
    try:
        while True:
            try:
                kind, x, y, evt_t = q.get(timeout=0.2)
            except _queue.Empty:
                continue
            if kind == "right":
                return None                    # 右键退出
            # 双击: 与上次左键按下在双击时间和距离内, 取单击值
            if (last_x is not None
                    and (evt_t - last_t) * 1000 <= dbl_ms
                    and abs(x - last_x) <= dbl_cx
                    and abs(y - last_y) <= dbl_cy):
                return last_x, last_y
            last_x, last_y, last_t = x, y, evt_t
            # 单击: 记录, 通过全局 latest 供前端轮询预览(不显示红点)
            _set_latest_click(x, y)
    finally:
        # 终止钩子线程: 向钩子线程投递 WM_QUIT(不能发当前线程id)
        tid = hook_holder.get("tid")
        if tid:
            try:
                u32.PostThreadMessageW(tid, WM_QUIT, 0, 0)
            except Exception:
                pass


# 最近一次单击坐标(供前端轮询预览)
_latest_click = None
_latest_click_lock = threading.Lock()


def _set_latest_click(x, y):
    global _latest_click
    with _latest_click_lock:
        _latest_click = (int(x), int(y))


def get_latest_click():
    """返回最近一次左键单击的屏幕坐标 (x, y) 或 None
    用于选点流程中前端实时预览单击值。"""
    with _latest_click_lock:
        return _latest_click


def clear_latest_click():
    """清空最近单击坐标。"""
    global _latest_click
    with _latest_click_lock:
        _latest_click = None


def flash_red_dot(x, y, radius=10, duration=0.5):
    """【红点预览】独立工具: 在屏幕坐标 (x,y) 显示一个红色圆点 duration 秒(后台线程, 不阻塞)。
    入口统一: mouse_click/scroll/preview_point 都经此触发。
    实现(含用完即销毁修复): 每任务临时线程, 显示完 win.quit 强制退出 mainloop 再 win.destroy,
    线程自然结束零残留(修复旧版每次滚动/点击创建 tkinter 线程且 mainloop 不退出导致的线程爆炸)"""
    def worker():
        win = None
        try:
            import tkinter as tk
            win = tk.Tk()
            win.overrideredirect(True)          # 无边框
            win.attributes("-topmost", True)    # 置顶
            win.attributes("-alpha", 0.9)       # 略透明
            win.geometry(f"+{int(x) - radius - 2}+{int(y) - radius - 2}")
            c = tk.Canvas(win, width=radius * 2 + 4, height=radius * 2 + 4,
                          highlightthickness=0, bg="white")
            c.pack()
            c.create_oval(2, 2, radius * 2 + 2, radius * 2 + 2,
                          fill="#e53935", outline="#b71c1c", width=2)
            win.update()
            win.after(int(duration * 1000), win.destroy)        # 到时销毁窗口
            win.after(int(duration * 1000) + 600, win.quit)     # 保险: 强制退出 mainloop
            win.mainloop()
        except Exception:
            pass
        finally:
            try:
                if win is not None:
                    win.destroy()               # 用完即销毁
            except Exception:
                pass
    threading.Thread(target=worker, daemon=True).start()


def scroll(x, y, pixels, direction="down", wait_before=0, wait_after=0,
           show_feedback=True, duration=0.2):
    """【滚轮滚动】（滚轮不分左右键，只分方向）
    参数:
      x, y          滚动时鼠标停靠坐标
      pixels        滚动距离（像素，>0）
      direction     方向: 'down'(默认, 向下滚) / 'up'(向上滚)
      wait_before   滚动前等待秒数(默认 0)
      wait_after    滚动后等待秒数(默认 0)
      show_feedback 是否在坐标点显示红色反馈点 0.5 秒(默认 True)
      duration      滚动完成时长(秒, 默认0.2): 整个滚动在此时间内完成
    """
    if wait_before:
        time.sleep(wait_before)
    u32 = _u32()
    u32.SetCursorPos(int(x), int(y))
    time.sleep(0.05)                    # 移动到位后的微小停顿
    sign = -1 if direction == "down" else 1   # 负值=向下, 正值=向上
    ticks = max(1, int(pixels / WHEEL_DELTA)) if pixels else 0
    # 每格间隔 = 总时长 / 格数(整个滚动在 duration 秒内完成; 至少给 0.005 保证生效)
    step = max(0.005, (duration or 0.5) / ticks) if ticks else 0
    for _ in range(ticks):
        u32.mouse_event(MOUSEEVENTF_WHEEL, 0, 0, sign * WHEEL_DELTA, None)
        if step:
            time.sleep(step)
    if show_feedback:
        flash_red_dot(x, y)            # 滚动完成后显示红点(不阻塞/不抢滚动焦点)
    if wait_after:
        time.sleep(wait_after)


# ===========================================================================
# 键盘：文本 / 组合键 / 单键
# ===========================================================================
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


def _si_key(vk, keyup=False):
    """SendInput 发送单键(带注入标志, 采集钩子据此放行程序输入)"""
    d = KEYBDINPUT()
    d.wVk = vk
    d.wScan = 0
    d.dwFlags = KEYEVENTF_KEYUP if keyup else 0
    u = _INPUTUNION(); u.ki = d
    arr = (INPUT * 1)()
    arr[0].type = INPUT_KEYBOARD
    arr[0].u = u
    _u32().SendInput(1, arr, ctypes.sizeof(INPUT))


def ctrl_key(letter):
    """发送 Ctrl+字母 组合键"""
    vk = ord(letter.upper())
    _si_key(VK_CONTROL)
    time.sleep(0.04)
    _si_key(vk)
    time.sleep(0.04)
    _si_key(vk, keyup=True)
    _si_key(VK_CONTROL, keyup=True)
    time.sleep(0.1)


def ctrl_shift_key(letter):
    """发送 Ctrl+Shift+字母 组合键（如关闭/切换窗口的 Ctrl+Shift+W）"""
    vk = ord(letter.upper())
    _si_key(VK_CONTROL)
    _si_key(VK_SHIFT)
    time.sleep(0.04)
    _si_key(vk)
    time.sleep(0.04)
    _si_key(vk, keyup=True)
    _si_key(VK_SHIFT, keyup=True)
    _si_key(VK_CONTROL, keyup=True)
    time.sleep(0.1)


def key_press(vk):
    """发送单个按键（如 Delete/VK_RETURN）"""
    _si_key(vk)
    time.sleep(0.03)
    _si_key(vk, keyup=True)
    time.sleep(0.1)


# ===========================================================================
# 剪贴板：读 / 写 / 清空
# ===========================================================================
@obs.timed("clip_read")
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


@obs.timed("clip_write")
def set_clipboard_text(text):
    """把文本写入剪贴板（Win32，线程安全）；成功返回 True"""
    u32 = _u32()
    k32 = _k32()
    if not u32.OpenClipboard(None):
        return False
    try:
        u32.EmptyClipboard()
        data = (str(text) + "\x00").encode("utf-16-le")
        GMEM_MOVEABLE = 0x0002
        GMEM_ZEROINIT = 0x0040
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


# ===========================================================================
# 系统截图热键防护: 采集期间禁用 Win+Shift+S / PrintScreen(与任务栏隐藏同步)
# ===========================================================================
_snip_hook = None            # 低层键盘钩子句柄
_snip_ready = False          # 钩子线程已就绪(消息循环在跑)
_VK_SNAPSHOT = 0x2C          # PrintScreen
_VK_LWIN, _VK_RWIN = 0x5B, 0x5C
_VK_SHIFT = 0x10
_WM_KEYDOWN = 0x0100
_WH_KEYBOARD_LL = 13
_HOOKPROC = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_int, ctypes.wintypes.WPARAM, ctypes.wintypes.LPARAM)
_kbd_lock = threading.Lock()


@_HOOKPROC
def _ll_kbd_proc(nCode, wParam, lParam):
    """低层键盘钩子: 吞掉 PrintScreen 与 Win(+Shift)+S 截图热键"""
    if nCode == 0 and wParam in (_WM_KEYDOWN, 0x0104):   # WM_KEYDOWN / WM_SYSKEYDOWN
        try:
            class _KBDLL(ctypes.Structure):
                _fields_ = [("vkCode", ctypes.c_ulong), ("scanCode", ctypes.c_ulong),
                            ("flags", ctypes.c_ulong), ("time", ctypes.c_ulong),
                            ("dwExtraInfo", ctypes.c_ulong)]
            kb = _KBDLL.from_address(lParam)
            vk = kb.vkCode
            if vk == _VK_SNAPSHOT:
                return 1                                # 吞 PrintScreen(含 Alt+PrtSc)
            if vk in (ord('S'), ord('W'), ord('K')) and (
                    _u32().GetAsyncKeyState(_VK_LWIN) & 0x8000 or
                    _u32().GetAsyncKeyState(_VK_RWIN) & 0x8000):
                return 1                                # 吞 Win+S / Win+Shift+S / Win+K
            _alt = _u32().GetAsyncKeyState(VK_MENU) & 0x8000
            _ctl = _u32().GetAsyncKeyState(VK_CONTROL) & 0x8000
            if _alt and _ctl and vk in (ord('D'), ord('Y'), ord('O'),
                                        ord('S'), ord('X'), ord('Z')):
                return 1                                # 吞 Ctrl+Alt+D/Y/O/S/X/Z(有道词典/翻译截图翻译取词等)
            if _alt and vk in (ord('A'), ord('X'), ord('D'), ord('Z'), ord('S')):
                return 1                                # 吞 Alt+A/X/D/Z/S(微信/有道等全局截图热键)
        except Exception:
            pass
    return _u32().CallNextHookEx(_snip_hook, nCode, wParam, lParam)


def _snip_hook_thread():
    """钩子线程: 跑消息循环保持钩子存活(daemon, 进程退出自动结束)"""
    global _snip_ready
    _snip_ready = True
    msg = ctypes.wintypes.MSG()
    while _u32().GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
        _u32().TranslateMessage(ctypes.byref(msg))
        _u32().DispatchMessageW(ctypes.byref(msg))


def disable_snipping():
    """禁用系统截图热键(PrintScreen / Win+Shift+S), 返回是否成功; 幂等"""
    global _snip_hook, _snip_ready
    with _kbd_lock:
        if _snip_hook:                       # 已禁用, 幂等
            return True
        try:
            import winreg
            k = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Control Panel\Keyboard",
                               0, winreg.KEY_SET_VALUE)
            try:
                winreg.SetValueEx(k, "PrintScreenKeyForSnippingEnabled", 0,
                                  winreg.REG_SZ, "0")   # PrtScn 直开截图关闭(新Win)
            finally:
                winreg.CloseKey(k)
        except Exception:
            pass
        try:
            _hook = _u32().SetWindowsHookExW(_WH_KEYBOARD_LL, _ll_kbd_proc,
                                             None, 0)   # 全局钩子, 回调在当前线程
        except Exception:
            _hook = None
        if not _hook:
            return False
        _snip_hook = _hook
        threading.Thread(target=_snip_hook_thread, daemon=True).start()
        return True


def enable_snipping():
    """恢复系统截图热键; 幂等"""
    global _snip_hook
    with _kbd_lock:
        if _snip_hook:
            try:
                _u32().UnhookWindowsHookEx(_snip_hook)
            except Exception:
                pass
            _snip_hook = None
        try:
            import winreg
            k = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Control Panel\Keyboard",
                               0, winreg.KEY_SET_VALUE)
            try:
                winreg.DeleteValue(k, "PrintScreenKeyForSnippingEnabled")
            except FileNotFoundError:
                pass
            finally:
                winreg.CloseKey(k)
        except Exception:
            pass
        return True


def hide_taskbar():
    """【机制已停用】不再隐藏任务栏(no-op): 任务栏隐藏/恢复会改 WorkArea/RECT,
    截图坐标与实际渲染不一致(报告高1039但渲染1080, OCR目标落入任务栏区), 彻底去除"""
    return True


def shot_abs(shot, bbox, x, y, h=None):
    """图像相对坐标 -> 屏幕绝对坐标(DPI按比例换算, 不写死1:1像素比)
    参数:
      shot PIL图(截图); bbox=(x1,y1,x2,y2) 该截图对应的屏幕区域
      x, y 图中相对坐标(如OCR结果/矩形)
      h    可选: 传入高度时同步按y比例换算
    返回 (ax, ay) 或 h给出时 (ax, ay, ah)
    背景: Windows 系统缩放(125%/150%)下 ImageGrab 返回图尺寸≠bbox像素,
    直接"起点+相对"会偏; 此处按 图尺寸/bbox尺寸 比例换算, 缩放100%时比例=1无影响"""
    x1, y1, x2, y2 = bbox
    _w, _h2 = shot.width, shot.height
    sx = (x2 - x1) / _w if _w else 1.0
    sy = (y2 - y1) / _h2 if _h2 else 1.0
    ax = x1 + int(x * sx)
    ay = y1 + int(y * sy)
    if h is None:
        return ax, ay
    return ax, ay, int(h * sy)


def wechat_rect():
    """微信主窗口(Weixin.exe)外接矩形, 4 条边各内缩 5px
    返回 (x1, y1, x2, y2) 或 None; 点位自动设置基于窗口坐标使用(微信离屏幕边缘有缝隙)"""
    try:
        wins = find_windows(exe="Weixin.exe", visible_only=True)  # 直接进程名, 避免循环导入
        if not wins:
            return None
        r = ctypes.wintypes.RECT()
        _u32().GetWindowRect(wins[0][0], ctypes.byref(r))
        return (r.left + 5, r.top + 5, r.right - 5, r.bottom - 5)
    except Exception:
        return None


def work_area():
    """系统工作区(不含任务栏)矩形: (x1,y1,x2,y2); 任务栏在底时 bottom=任务栏上沿
    移动窗口用工作区高度, 避免窗口盖住任务栏"""
    try:
        r = ctypes.wintypes.RECT()
        _u32().SystemParametersInfoW(0x0030, 0, ctypes.byref(r), 0)  # SPI_GETWORKAREA
        return (r.left, r.top, r.right, r.bottom)
    except Exception:
        return None


def _find_taskbar():
    """Windows 任务栏窗口句柄(Shell_TrayWnd)"""
    return _u32().FindWindowW("Shell_TrayWnd", None)


def hide_taskbar():
    """【机制已停用】不再隐藏任务栏(no-op): 任务栏隐藏/恢复会改 WorkArea/RECT,
    截图坐标与实际渲染不一致(报告高1039但渲染1080, OCR目标落入任务栏区), 彻底去除"""
    return True


def show_taskbar():
    """【机制已停用】与 hide_taskbar 对称的 no-op(见上)"""
    return True


# ===========================================================================
# 截图：屏幕区域截图（存文件 / 转 base64 / 5参数截图）
# ===========================================================================
@obs.timed("shot")
def screenshot(x1, y1, x2, y2, img_format="png", as_base64=False):
    """【截图】截取屏幕区域，保存到系统缓存目录并返回文件路径。
    参数:
      x1, y1, x2, y2  截取区域左上角(x1,y1) 到 右下角(x2,y2)
      img_format      图片格式: 'png'(默认) / 'jpg' / 'bmp' / 'webp'
      as_base64       True 时内部读取图片并转为带前缀的 base64 一并返回
    返回 (文件路径, base64或None):
      base64 形如 'data:image/png;base64,xxxx'；
      截图或转码失败时路径为 None
    """
    try:
        # 截图前隐藏鼠标(可靠: 光标从屏幕消失, 避免入镜), 完成后恢复
        try:
            _u32().ShowCursor(False)
        except Exception:
            pass
        try:
            fmt = str(img_format).lower().lstrip(".")
            if fmt == "jpeg":
                fmt = "jpg"
            if fmt not in ("png", "jpg", "bmp", "webp"):
                fmt = "png"
            img = ImageGrab.grab(bbox=(int(x1), int(y1), int(x2), int(y2)))
            if fmt == "jpg":

                img = img.convert("RGB")
            # 写死保存到系统缓存目录(临时目录), 文件名固定, 每次截图直接覆盖
            fname = f"shot.{fmt}"
            path = os.path.join(tempfile.gettempdir(), fname)
            img.save(path, format=("jpeg" if fmt == "jpg" else fmt))
        finally:
            # 恢复鼠标可见
            try:
                _u32().ShowCursor(True)
            except Exception:
                pass
        if not as_base64:
            return path, None
        # 读取图片并转带前缀的 base64
        with open(path, "rb") as f:
            raw = f.read()
        b64 = "data:image/%s;base64,%s" % (fmt, base64.b64encode(raw).decode("ascii"))
        return path, b64
    except Exception:
        return None, None


__all__ = [
    # 常量
    "VK_RETURN", "VK_DELETE", "VK_CONTROL", "VK_SHIFT",
    # 基础
    "enable_dpi_awareness",
    # 窗口
    "find_windows", "show_window", "close_window", "move_window",
    "hide_taskbar", "show_taskbar", "disable_snipping", "enable_snipping",
    "shot_abs",
    "wechat_rect",
    # 鼠标
    "mouse_click", "scroll", "preview_point", "capture_point",
    "get_latest_click", "clear_latest_click",
    # 键盘
    "type_text", "ctrl_key", "ctrl_shift_key", "key_press",
    # 剪贴板
    "read_clipboard_text", "set_clipboard_text", "clear_clipboard",
    # 截图
    "screenshot",
]

def process_working_set(pid):
    """进程工作集内存(字节), 用于找微信主窗口(内存最大者); 失败返回 0"""
    import ctypes
    from ctypes import wintypes as _wt
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    h = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return 0

    class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
        _fields_ = [("cb", _wt.DWORD),
                    ("PageFaultCount", _wt.DWORD),
                    ("PeakWorkingSetSize", ctypes.c_size_t),
                    ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t),
                    ("PeakPagefileUsage", ctypes.c_size_t)]
    try:
        pmc = PROCESS_MEMORY_COUNTERS()
        pmc.cb = ctypes.sizeof(PROCESS_MEMORY_COUNTERS)
        ok = ctypes.windll.psapi.GetProcessMemoryInfo(h, ctypes.byref(pmc), pmc.cb)
        return pmc.WorkingSetSize if ok else 0
    finally:
        ctypes.windll.kernel32.CloseHandle(h)

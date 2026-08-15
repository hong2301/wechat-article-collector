# -*- coding: utf-8 -*-
"""core.win32util: Win32 键鼠/窗口/剪贴板/低层钩子
依赖: core.utils(log)
"""
import ctypes
import queue
import threading
import time
from ctypes import wintypes as wt

from .utils import log


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


__all__ = ['CF_UNICODETEXT', 'EscListener', 'GMEM_MOVEABLE', 'GMEM_ZEROINIT', 'HOOKPROC', 'HWND_NOTOPMOST', 'HWND_TOP', 'HWND_TOPMOST', 'INPUT', 'INPUT_KEYBOARD', 'KBDLLHOOKSTRUCT', 'KEYBDINPUT', 'KEYEVENTF_KEYUP', 'KEYEVENTF_UNICODE', 'LLKHF_INJECTED', 'LLMHF_INJECTED', 'MOUSEEVENTF_LEFTDOWN', 'MOUSEEVENTF_LEFTUP', 'MOUSEEVENTF_WHEEL', 'MOUSEINPUT', 'MSLLHOOKSTRUCT', 'MouseLock', 'MousePointCollector', 'POINT', 'PROCESSENTRY32W', 'SM_CXDOUBLECLK', 'SM_CXSCREEN', 'SM_CYDOUBLECLK', 'SM_CYSCREEN', 'SWP_FRAMECHANGED', 'SWP_NOACTIVATE', 'SWP_NOMOVE', 'SWP_NOSIZE', 'SWP_NOZORDER', 'SWP_SHOWWINDOW', 'SW_HIDE', 'SW_RESTORE', 'SW_SHOW', 'TH32CS_SNAPPROCESS', 'VK_CONTROL', 'VK_DELETE', 'VK_ESCAPE', 'VK_MENU', 'VK_RETURN', 'VK_SHIFT', 'WECHAT_MAIN_EXES', 'WHEEL_DELTA', 'WH_KEYBOARD_LL', 'WH_MOUSE_LL', 'WM_KEYDOWN', 'WM_LBUTTONDOWN', 'WM_MOUSEMOVE', 'WM_QUIT', 'WM_RBUTTONDOWN', 'WNDENUMPROC', '_INPUTUNION', '_force_foreground', '_k32', '_u32', 'clear_clipboard', 'ctrl_key', 'ctrl_shift_key', 'enable_dpi_awareness', 'find_taskbar', 'find_wechat_window', 'get_foreground_window_info', 'get_top_windows', 'get_wechat_pids', 'hide_taskbar', 'key_press', 'mouse_click', 'read_clipboard_text', 'scroll_down_at', 'scroll_up_at', 'set_clipboard_text', 'show_taskbar', 'snap_wechat_left', 'type_text']

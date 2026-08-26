# -*- coding: utf-8 -*-
"""采集期间输入锁定: 监听ESC停止 + 拦截人工鼠标/键盘(程序注入放行)
移植自旧程序 core/win32util.py 的 EscListener + MouseLock, 新后端独立版"""
import ctypes
import threading
from ctypes import wintypes as wt

from . import computer as pc

WH_KEYBOARD_LL = 13
WH_MOUSE_LL = 14
LLKHF_INJECTED = 0x10
LLMHF_INJECTED = 0x01
VK_ESCAPE = 0x1B
WM_MOUSEMOVE = 0x0200


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [("vkCode", ctypes.c_ulong), ("scanCode", ctypes.c_ulong),
                ("flags", ctypes.c_ulong), ("time", ctypes.c_ulong),
                ("dwExtraInfo", ctypes.c_void_p)]


class MSLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [("pt", wt.POINT), ("mouseData", ctypes.c_ulong),
                ("flags", ctypes.c_ulong), ("time", ctypes.c_ulong),
                ("dwExtraInfo", ctypes.c_void_p)]


class InputLock:
    """采集期间输入锁定: 全局键盘+鼠标低层钩子
    - 程序自己的输入(SendInput/mouse_event 注入标志)放行
    - 人工输入拦截: ESC=触发停止回调; 其他键/鼠标点击滚轮=拦截+on_block提示
    - 鼠标移动: 拦截但不提示(环境噪声)
    """

    def __init__(self):
        self.hook_kb = None
        self.hook_ms = None
        self.hook_ready = threading.Event()
        self._started = False
        self._ok = False
        self._tid = None
        self.on_esc = None       # ESC 回调(触发停止)
        self.on_block = None     # 拦截人工输入回调(提示)
        self._kb_proc = pc.HOOKPROC(self._kb_callback)
        self._ms_proc = pc.HOOKPROC(self._ms_callback)

    def _kb_callback(self, code, wparam, lparam):
        if code == 0:
            kb = ctypes.cast(lparam, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
            if kb.flags & LLKHF_INJECTED:
                # 程序自己的输入放行
                return pc._u32().CallNextHookEx(self.hook_kb, code, wparam, lparam)
            if kb.vkCode == VK_ESCAPE and wparam == 0x0100:
                cb = self.on_esc
                if cb is not None:
                    try:
                        cb()
                    except Exception:
                        pass
                return 1   # 拦截 ESC 不传给前台
            # 人工其他键: 拦截 + 提示
            cb = self.on_block
            if cb is not None:
                try:
                    cb()
                except Exception:
                    pass
            return 1
        return pc._u32().CallNextHookEx(self.hook_kb, code, wparam, lparam)

    def _ms_callback(self, code, wparam, lparam):
        if code == 0:
            ms = ctypes.cast(lparam, ctypes.POINTER(MSLLHOOKSTRUCT)).contents
            if not (ms.flags & LLMHF_INJECTED):
                # 人工鼠标(含移动)一律拦截 + 提示
                cb = self.on_block
                if cb is not None:
                    try:
                        cb()
                    except Exception:
                        pass
                return 1
        return pc._u32().CallNextHookEx(self.hook_ms, code, wparam, lparam)

    def _hook_thread(self):
        self._tid = threading.get_ident()
        h_kb = pc._u32().SetWindowsHookExW(
            WH_KEYBOARD_LL, self._kb_proc, pc._k32().GetModuleHandleW(None), 0)
        h_ms = 0
        if h_kb:
            try:
                h_ms = pc._u32().SetWindowsHookExW(
                    WH_MOUSE_LL, self._ms_proc, pc._k32().GetModuleHandleW(None), 0)
            except Exception:
                h_ms = 0
        if not h_kb:
            self.hook_ready.set()
            return
        self.hook_kb = h_kb
        self.hook_ms = h_ms
        self.hook_ready.set()
        msg = wt.MSG()
        while pc._u32().GetMessageW(ctypes.byref(msg), None, 0, 0) != 0:
            pc._u32().TranslateMessage(ctypes.byref(msg))
            pc._u32().DispatchMessageW(ctypes.byref(msg))
        if h_ms:
            pc._u32().UnhookWindowsHookEx(h_ms)
        pc._u32().UnhookWindowsHookEx(h_kb)
        self.hook_kb = None
        self.hook_ms = None

    def start(self):
        """启动输入锁定(幂等), 返回是否成功"""
        if self._started:
            return self._ok
        self._started = True
        threading.Thread(target=self._hook_thread, daemon=True).start()
        self._ok = self.hook_ready.wait(3)
        return self._ok

    def stop(self):
        """停止输入锁定"""
        if self.hook_kb and self._tid:
            pc._u32().PostThreadMessageW(self._tid, pc.WM_QUIT, 0, 0)
        self._started = False
# -*- coding: utf-8 -*-
"""微信窗口探测/模拟脚本(自包含, 双击或 python 运行, 不依赖采集器代码)

功能:
  1) 列出微信所有窗口(两种进程: Weixin.exe 主程序 / WeChatAppEx.exe 容器)
     表格: 进程名 | 可见 | 占用内存 | 窗口句柄 | 标题
  2) 模拟 init_wechat_window 第0步逻辑(DRY-RUN 不真正关闭):
     "保留内存占用最大的微信主窗口, 其余将关闭" 输出保留/关闭清单

用法:
  python scripts/wx_window_probe.py           普通: 打印窗口列表
  python scripts/wx_window_probe.py --sim     打印列表 + 模拟关闭(不执行)
"""
import ctypes
import sys
from ctypes import wintypes as wt

WECHAT_MAIN = "Weixin.exe"
WECHAT_APPEX = "WeChatAppEx.exe"

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_VM_READ = 0x0010
SYNCHRONIZE = 0x00100000


class MEMORY_COUNTERS(ctypes.Structure):
    _fields_ = [("cb", wt.DWORD),
                ("PageFaultCount", wt.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t)]


def enum_windows():
    """所有顶层窗口: [(hwnd, pid)]"""
    out = []
    WNDENUMPROC = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)

    @WNDENUMPROC
    def cb(hwnd, lparam):
        out.append(hwnd)
        return True

    ctypes.windll.user32.EnumWindows(cb, 0)
    wins = []
    for hwnd in out:
        pid = wt.DWORD()
        ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        wins.append((hwnd, pid.value))
    return wins


def proc_name(pid):
    """进程 exe 名(带 .exe); 失败返回 ''"""
    h = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(260)
        size = wt.DWORD(260)
        if ctypes.windll.kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
            return buf.value.rsplit("\\", 1)[-1].lower()
    finally:
        ctypes.windll.kernel32.CloseHandle(h)
    return ""


def working_set(pid):
    h = ctypes.windll.kernel32.OpenProcess(
        PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, pid)
    if not h:
        return 0
    try:
        pmc = MEMORY_COUNTERS()
        pmc.cb = ctypes.sizeof(MEMORY_COUNTERS)
        if ctypes.windll.psapi.GetProcessMemoryInfo(h, ctypes.byref(pmc), pmc.cb):
            return pmc.WorkingSetSize
    finally:
        ctypes.windll.kernel32.CloseHandle(h)
    return 0


def is_visible(hwnd):
    return bool(ctypes.windll.user32.IsWindowVisible(hwnd))


def window_title(hwnd):
    n = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
    if n <= 0:
        return ""
    buf = ctypes.create_unicode_buffer(n + 1)
    ctypes.windll.user32.GetWindowTextW(hwnd, buf, n + 1)
    return buf.value


def collect(visible_only=False):
    rows = []
    for hwnd, pid in enum_windows():
        name = proc_name(pid)
        if name not in (WECHAT_MAIN.lower(), WECHAT_APPEX.lower()):
            continue
        vis = is_visible(hwnd)
        if visible_only and not vis:
            continue
        rows.append((name, vis, working_set(pid), hwnd, window_title(hwnd)))
    return rows


def print_table(rows):
    print("+---------------------+--------+-----------+-----------+----------------------------------+")
    print("| 进程名              | 可见   | 占用内存  | 句柄      | 标题                             |")
    print("+---------------------+--------+-----------+-----------+----------------------------------+")
    for name, vis, mem, hwnd, title in rows:
        print("| {:<19} | {:<6} | {:>7.1f}MB | {:<9} | {:<30} |".format(
            name, "可见" if vis else "隐藏", mem / 1048576, hex(hwnd), title[:30]))
    print("+---------------------+--------+-----------+-----------+----------------------------------+")
    print("共 {} 个窗口".format(len(rows)))


def sim_close(rows):
    """模拟 init_wechat_window 第0步: 可见窗口按内存最大保留, 其余'将关闭'"""
    print("\n>>> 模拟 [保留内存最大主窗口, 关闭其余](DRY-RUN, 不会真的关闭) <<<")
    visible = [r for r in rows if r[1]]
    if len(visible) <= 1:
        print("可见微信窗口 {} 个(≤1), 无需关闭".format(len(visible)))
        return
    keep = max(visible, key=lambda r: r[2])
    print("将保留: {:>1} `{:<12} ({:.1f}MB, 句柄 {})".format(
        keep[0], keep[4][:12], keep[2] / 1048576, hex(keep[3])))
    print("将关闭:")
    for r in visible:
        if r[3] != keep[3]:
            print("    - {} `{:<12} ({:.1f}MB, 句柄 {})".format(
                r[0], r[4][:12], r[2] / 1048576, hex(r[3])))


def main():
    all_rows = collect()
    print_table(all_rows)
    if len(sys.argv) > 1 and sys.argv[1] == "--sim":
        visible_only = [r for r in all_rows if r[1]]
        sim_close(visible_only)


if __name__ == "__main__":
    main()
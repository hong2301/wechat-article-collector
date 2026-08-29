# -*- coding: utf-8 -*-
"""任务子包: 窗口初始化(微信 / 搜一搜 / 查询 / 采集器)
各函数为采集与自动设置共用的窗口就位逻辑"""
import ctypes
import hashlib
import threading
import time
from ctypes import wintypes as wt

from ...core import computer as pc
from ...core.common import _read_point  # noqa: F401
from ...database import get_conn

WECHAT_MAIN = "Weixin.exe"          # 微信主界面进程
WECHAT_APPEX = "WeChatAppEx.exe"    # 微信小程序/外部App容器进程

# 采集器(前端)相关
APP_TITLE = "微信公众号采集器"      # 前端窗口标题(打包后名称)
APP_EXE = "electron.exe"           # 前端壳进程


def init_wechat_window():
    """微信窗口初始化: 确保 WeChatAppEx 被关闭、Weixin 存在且在左半屏。
    自动判断窗口分离: 微信宽度/位置不合法(≠左半屏)时点击点位9(窗口分离按钮)后重跑
    步骤:
      1) 找 WeChatAppEx.exe 窗口, 有则直接关闭, 无则跳过
      2) 找 Weixin.exe 窗口, 无则唤出
      3) 保证已有 Weixin.exe 窗口
      4) 移动到屏幕左半边, 并校验是否就位
      5) 宽度/位置不合法 -> 点击点位9(触发窗口布局)后重跑一次
    返回: (成功?, 说明文本)。
    """
    logs = []

    def once():
        # 单次初始化; 返回 (成功?, 本回文本)
        _logs = []
        # 1) 关闭 WeChatAppEx(仅可见窗口)
        appex = pc.find_windows(exe=WECHAT_APPEX, visible_only=True)
        for hwnd, _t, _p, _v in appex:
            pc.close_window(hwnd)
            _logs.append(f"已关闭 WeChatAppEx 窗口 #{hwnd}")
        if not appex:
            _logs.append("无可见 WeChatAppEx 窗口, 跳过")

        # 2) 找 Weixin, 无则唤出
        weixin = pc.find_windows(exe=WECHAT_MAIN)
        if not weixin:
            found = pc.find_windows(exe=WECHAT_MAIN, visible_only=False)
            if not found:
                _logs.append("未找到 Weixin.exe 窗口")
                return False, "未找到 Weixin 窗口"
            pc.show_window(found[0][0])
            _logs.append(f"已唤出 Weixin 窗口 #{found[0][0]}")
            weixin = pc.find_windows(exe=WECHAT_MAIN)
        else:
            _logs.append(f"Weixin 窗口已存在 #{weixin[0][0]}")
        if not weixin:
            return False, "Weixin 窗口仍未识别"

        hwnd = weixin[0][0]
        u32_sm = pc._u32()
        sw = u32_sm.GetSystemMetrics(pc.SM_CXSCREEN)
        sh = u32_sm.GetSystemMetrics(pc.SM_CYSCREEN)
        pc.move_window(hwnd, 0, 0, sw // 2, sh)

        # 4) 校验是否就位左半屏
        r = wt.RECT()
        pc._u32().GetWindowRect(hwnd, ctypes.byref(r))
        if abs(r.left) > 2 or abs((r.right - r.left) - sw // 2) > 0:
            return False, "Weixin 未就位左半屏(宽度或位置不合法)"
        return True, "Weixin 窗口已就位左半屏"

    # 第一次
    ok, info = once()
    logs.append(info)
    if ok:
        return True, "; ".join(logs)

    # 宽度/位置不合法: 点击点位9(窗口分离按钮, 触发官方布局)后重跑一次
    try:
        row = None
        conn = get_conn()
        try:
            row = conn.execute(
                "SELECT id, name, x, y FROM points WHERE id=9").fetchone()
        finally:
            conn.close()
        px = py = None
        if row:
            try:
                px = int(float(row["x"]))
                py = int(float(row["y"]))
            except (TypeError, ValueError):
                px = py = None
        if px is not None:
            logs.append(f"尝试点击点位9({px},{py})")
            pc.mouse_click(px, py)
            time.sleep(0.2)      # 点击点位9后等待, 让窗口布局生效
        else:
            logs.append("无点位9, 跳过点击")
    except Exception:
        logs.append("读取点位9失败")

    ok2, info2 = once()
    logs.append(info2)
    return ok2, "; ".join(logs)


def search_window_init():
    """搜一搜窗口初始化(坐标采集流程)。
    前提: 必须满足微信窗口初始化 + 采集器窗口初始化成功的结果
    自动判断窗口分离: 点完点位12后, 若微信主窗口宽度≠屏幕一半: 移微信到左半屏→等0.3s→点击点位9
    步骤:
      0) 前置判定: Weixin可见且在左半屏 + 采集器可见且在右半屏; 不符合直接返回 False
      1) 点击点位11(搜索框) → 等0.2s → 输入1 → 等0.1s → 全选删除 → 等0.2s
      2) 点击点位12(搜索网络) → 等0.5s
      2b) 判断微信主窗口宽度: ≠屏幕一半 -> 移微信到左半屏 → 等0.3s → 点击点位9(窗口分离按钮)
      3) 查找可见 WeChatAppEx 窗口 ...
    """
    logs = []

    # 0) 前置判定: 微信初始化(Weixin左半屏) + 采集器初始化(采集器右半屏)必须已满足
    u32_sm = pc._u32()
    sw = u32_sm.GetSystemMetrics(pc.SM_CXSCREEN)
    sh = u32_sm.GetSystemMetrics(pc.SM_CYSCREEN)
    half = sw // 2

    weixin = pc.find_windows(exe=WECHAT_MAIN, visible_only=True)
    if not weixin:
        logs.append("前置不满足: 无可见 Weixin 窗口(微信窗口初始化未完成)")
        return False, "; ".join(logs)
    r = wt.RECT()
    pc._u32().GetWindowRect(weixin[0][0], ctypes.byref(r))
    if abs(r.left) > 2 or abs((r.right - r.left) - half) > 0:
        logs.append("前置不满足: Weixin 不在左半屏(微信窗口初始化未完成)")
        return False, "; ".join(logs)

    appwin = pc.find_windows(title=APP_TITLE, visible_only=True)
    if not appwin:
        appwin = pc.find_windows(exe=APP_EXE, visible_only=True)
    if not appwin:
        logs.append("前置不满足: 未找到采集器窗口(采集器窗口初始化未完成)")
        return False, "; ".join(logs)
    r2 = wt.RECT()
    pc._u32().GetWindowRect(appwin[0][0], ctypes.byref(r2))
    if abs(r2.left - half) > 2 or abs((r2.right - r2.left) - half) > 0:
        logs.append("前置不满足: 采集器不在右半屏(采集器窗口初始化未完成)")
        return False, "; ".join(logs)
    logs.append("前置满足: 微信左半屏 + 采集器右半屏")

    # 1) 点位11: 点击 → 输入1 → 全选删除
    p11 = _read_point(11)
    if p11:
        pc.mouse_click(p11[0], p11[1])
        logs.append(f"点击点位11({p11[0]},{p11[1]})")
        time.sleep(0.1)
        pc.type_text("1")
        time.sleep(0.1)
        pc.ctrl_key("A")
        time.sleep(0.1)
        pc.key_press(pc.VK_DELETE)
        time.sleep(0.2)
    else:
        logs.append("缺少点位11")
        return False, "; ".join(logs)

    # 2) 点位12: 点击搜索网络
    p12 = _read_point(12)
    if p12:
        pc.mouse_click(p12[0], p12[1])
        logs.append(f"点击点位12({p12[0]},{p12[1]})")
        time.sleep(0.2)
    else:
        logs.append("缺少点位12")
        return False, "; ".join(logs)

    # 2b) 自动判断窗口分离: 微信主窗口宽度≠屏幕一半则: 移微信到左半屏 -> 等0.3s -> 点击点位9(窗口分离按钮)
    u32_probe = pc._u32()
    sw_probe = u32_probe.GetSystemMetrics(pc.SM_CXSCREEN)
    wx_rect = wt.RECT()
    pc._u32().GetWindowRect(weixin[0][0], ctypes.byref(wx_rect))
    if abs((wx_rect.right - wx_rect.left) - sw_probe // 2) > 0:
        # 先把微信主窗口移到左半屏, 稳定 0.3s 后点击分离按钮
        pc.move_window(weixin[0][0], 0, 0, sw_probe // 2, wx_rect.bottom - wx_rect.top)
        time.sleep(0.3)
        p9 = _read_point(9)
        if p9:
            pc.mouse_click(p9[0], p9[1])
            logs.append(f"点击点位9({p9[0]},{p9[1]})")
            time.sleep(1.0)          # 分离后等独立窗口完全创建
        else:
            logs.append("缺少点位9")
            return False, "; ".join(logs)
    else:
        logs.append("微信窗口已分离, 跳过分离按钮")

    # 3) 查找可见 WeChatAppEx 窗口, 并移到左半屏
    appex = pc.find_windows(exe=WECHAT_APPEX, visible_only=True)
    if not appex:
        logs.append("未找到可见 WeChatAppEx 窗口")
        return False, "; ".join(logs)

    hwnd = appex[0][0]
    u32_sm = pc._u32()
    sw = u32_sm.GetSystemMetrics(pc.SM_CXSCREEN)
    sh = u32_sm.GetSystemMetrics(pc.SM_CYSCREEN)
    # 分离后: 把搜一搜窗口移到左半屏(确保位置统一)
    pc.move_window(hwnd, 0, 0, sw // 2, sh)
    time.sleep(0.5)

    def check():
        r = wt.RECT()
        pc._u32().GetWindowRect(hwnd, ctypes.byref(r))
        return abs(r.left) <= 2 and abs((r.right - r.left) - sw // 2) <= 0

    # 3a) 已在左半屏 -> 完成
    if check():
        logs.append("WeChatAppEx 已在左半屏")
        return True, "; ".join(logs)

    # 3b) 不在左半屏 -> 移动到左半边
    pc.move_window(hwnd, 0, 0, sw // 2, sh)
    logs.append("WeChatAppEx 已移到左半屏")
    if check():
        return True, "; ".join(logs)

    logs.append("WeChatAppEx 未就位左半屏")
    return False, "; ".join(logs)


def search_query(link=""):
    """搜一搜窗口查询。
    前提: 搜一搜窗口初始化(search_window_init)成功。
    参数:
      link 要搜索/输入的链接
    步骤:
      1) 检查可见 WeChatAppEx 窗口是否在左半屏; 不在/无则返回 False
      2) 点击点位14(查询输入框) → 等0.1s → 输入链接 → 等0.1s → 回车
    返回: (成功?, 说明文本)
    """
    logs = []

    # 1) 检查可见 WeChatAppEx 在左半屏
    appex = pc.find_windows(exe=WECHAT_APPEX, visible_only=True)
    if not appex:
        logs.append("未找到可见 WeChatAppEx 窗口")
        return False, "; ".join(logs)
    u32_sm = pc._u32()
    sw = u32_sm.GetSystemMetrics(pc.SM_CXSCREEN)
    r = wt.RECT()
    pc._u32().GetWindowRect(appex[0][0], ctypes.byref(r))
    if abs(r.left) > 2 or abs((r.right - r.left) - sw // 2) > 0:
        logs.append("WeChatAppEx 不在左半屏")
        return False, "; ".join(logs)
    logs.append("WeChatAppEx 已在左半屏")

    # 2) 点击点位14 → 剪贴板粘贴链接 → 回车
    p14 = _read_point(14)
    if not p14:
        logs.append("缺少点位14")
        return False, "; ".join(logs)
    pc.mouse_click(p14[0], p14[1])
    logs.append(f"点击点位14({p14[0]},{p14[1]})")
    time.sleep(0.1)
    if not pc.set_clipboard_text(link):
        logs.append("剪贴板写入失败")
        return False, "; ".join(logs)
    pc.ctrl_key("V")       # 粘贴
    logs.append("剪贴板粘贴链接")
    time.sleep(0.3)
    pc.key_press(pc.VK_RETURN)
    logs.append("按回车")
    return True, "; ".join(logs)


def init_app_window():
    """采集器窗口初始化: 确保前端窗口(微信公众号采集器)在右半屏。
    前提: 调用本函数前窗口已被唤起(本函数不负责唤起)。
    步骤:
      1) 查找"微信公众号采集器"窗口；找不到则返回 False
      2) 检测是否在屏幕右半边；是则返回 True
      3) 否则移动到右半边，返回 True
    失败(找不到窗口/移动异常)返回 False。
    返回: (成功?, 说明文本)。
    """
    logs = []

    # 1) 查找前端窗口(按标题, 可能是 electron 或其它壳进程)
    wins = pc.find_windows(title=APP_TITLE, visible_only=True)
    if not wins:
        # 兜底: 按 electron 进程找
        wins = pc.find_windows(exe=APP_EXE, visible_only=True)
    if not wins:
        logs.append("未找到采集器窗口")
        return False, "; ".join(logs)

    hwnd = wins[0][0]
    u32 = pc._u32()
    sw = u32.GetSystemMetrics(pc.SM_CXSCREEN)
    sh = u32.GetSystemMetrics(pc.SM_CYSCREEN)
    half = sw // 2

    # 2) 检测是否已在右半边(左边缘≈半屏且宽度≈半屏)
    r = wt.RECT()
    u32.GetWindowRect(hwnd, ctypes.byref(r))
    if abs(r.left - half) <= 2 and abs((r.right - r.left) - half) <= 0:
        logs.append("采集器窗口已在右半屏")
        return True, "; ".join(logs)

    # 3) 移动到右半边
    pc.move_window(hwnd, half, 0, half, sh)
    logs.append("采集器窗口已移到右半屏")
    return True, "; ".join(logs)



# -*- coding: utf-8 -*-
"""backend.app.services.tasks: 任务组合模块

用途: 把 computer(电脑交互原语) 等底层模块按业务步骤组合成"任务函数"。

规则:
  * 本模块只放组合逻辑, 不放新的 Win32/输入原语(那些在 computer.py)。
  * 新增任务函数前需先经过确认。
"""

import time

from . import computer as pc


# 微信相关进程名（对应两个可见微信主窗口的宿主进程）
WECHAT_MAIN = "Weixin.exe"          # 微信主界面进程
WECHAT_APPEX = "WeChatAppEx.exe"    # 微信小程序/外部App容器进程


def init_wechat_window():
    """微信窗口初始化: 确保 WeChatAppEx 被关闭、Weixin 存在且在左半屏。
    步骤:
      1) 找 WeChatAppEx.exe 窗口, 有则直接关闭, 无则跳过
      2) 找 Weixin.exe 窗口, 无则唤出
      3) 保证已有 Weixin.exe 窗口
      4) 移动到屏幕左半边, 并校验是否就位
    返回: (成功?, 说明文本)。
      成功(Weixin 在左半边)返回 (True, 文本);
      不合法情况(如宽度无法设为半屏)返回 (False, 文本), 交由后续流程处理。
    """
    import ctypes
    from ctypes import wintypes as wt
    logs = []

    # 1) 关闭 WeChatAppEx(仅可见窗口)
    appex = pc.find_windows(exe=WECHAT_APPEX, visible_only=True)
    for hwnd, _t, _p, _v in appex:
        pc.close_window(hwnd)
        logs.append(f"已关闭 WeChatAppEx 窗口 #{hwnd}")
    if not appex:
        logs.append("无可见 WeChatAppEx 窗口, 跳过")

    # 2) 找 Weixin, 无则唤出
    weixin = pc.find_windows(exe=WECHAT_MAIN)
    if not weixin:
        found = pc.find_windows(exe=WECHAT_MAIN, visible_only=False)
        if not found:
            logs.append("未找到 Weixin.exe 窗口")
            return False, "; ".join(logs)
        pc.show_window(found[0][0])
        logs.append(f"已唤出 Weixin 窗口 #{found[0][0]}")
        weixin = pc.find_windows(exe=WECHAT_MAIN)
    else:
        logs.append(f"Weixin 窗口已存在 #{weixin[0][0]}")
    if not weixin:
        logs.append("Weixin.exe 窗口仍未识别")
        return False, "; ".join(logs)

    hwnd = weixin[0][0]

    # 3) 移到屏幕左半边(用通用 move_window 计算左半位置并按需移动)
    u32_sm = pc._u32()   # 内部取屏幕尺寸用
    sw = u32_sm.GetSystemMetrics(pc.SM_CXSCREEN)
    sh = u32_sm.GetSystemMetrics(pc.SM_CYSCREEN)
    pc.move_window(hwnd, 0, 0, sw // 2, sh)

    # 4) 校验是否就位左半屏(贴左边缘且宽度等于半屏); 不合法则返回 False
    r = wt.RECT()
    pc._u32().GetWindowRect(hwnd, ctypes.byref(r))
    if abs(r.left) > 2 or abs((r.right - r.left) - sw // 2) > 0:
        logs.append("Weixin 未就位左半屏(宽度或位置不合法)")
        return False, "; ".join(logs)

    logs.append("Weixin 窗口已就位左半屏")
    return True, "; ".join(logs)


__all__ = ["init_wechat_window"]

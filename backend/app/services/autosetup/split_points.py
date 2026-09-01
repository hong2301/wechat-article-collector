# -*- coding: utf-8 -*-
import ctypes
from ctypes import wintypes as _wt
import time as _time
"""点位自动设置: 分离/查询类点位 9(窗口分离按钮) 14(搜一搜查询按钮)
横向探测类: 初始化(不点点位9) + 横向点击找目标"""
from ...database import get_conn as _get_conn
from .engine import POINT_FLOWS, flow_point, log   # noqa: F401


# 点位 9: 微信窗口初始化不合法时窗口分离按钮
# 流程(简化): 微信窗口初始化(无点9) -> 采集器窗口初始化 -> 搜一搜窗口初始化(无点9)
#   -> 横向探测: 从微信主窗口最右边、y=点位11的y 向左点击, 步长每轮减半:
#      点击后微信主窗口宽度变小 => 点中分离按钮, 记录坐标成功
#   -> 若搜一搜本身是独立窗口 => 无需此点位(99999待定)
# 注意: 正在设置点位9, 两个初始化函数都不能点击点位9(库里坐标可能脏/未设置)
#   故复制自 tasks.init_wechat_window / search_window_init 并删除点击点位9的代码块
# ---------------------------------------------------------------------------
def _init_wechat_no_p9():
    """点位9专用: 微信窗口初始化(不点击点位9)
    复制自 tasks.init_wechat_window, 删除了'宽度/位置不合法时点击点位9后重跑'分支"""

    from ...services import tasks as tasks_svc
    from ...core import computer as pc

    logs = []
    # 1) 关闭 WeChatAppEx(仅可见窗口)
    appex = pc.find_windows(exe=tasks_svc.WECHAT_APPEX, visible_only=True)
    for hwnd, *_r in appex:
        pc.close_window(hwnd)
    if not appex:
        logs.append("无可见 WeChatAppEx 窗口, 跳过")
    # 2) 找 Weixin, 无则唤出
    weixin = pc.find_windows(exe=tasks_svc.WECHAT_MAIN)
    if not weixin:
        found = pc.find_windows(exe=tasks_svc.WECHAT_MAIN, visible_only=False)
        if not found:
            logs.append("未找到 Weixin.exe 窗口")
            return False, "未找到 Weixin 窗口"
        pc.show_window(found[0][0])
        logs.append(f"已唤出 Weixin 窗口 #{found[0][0]}")
        weixin = pc.find_windows(exe=tasks_svc.WECHAT_MAIN)
    else:
        logs.append(f"Weixin 窗口已存在 #{weixin[0][0]}")
    if not weixin:
        return False, "Weixin 窗口仍未识别"
    hwnd = weixin[0][0]
    u32_sm = pc._u32()
    sw = u32_sm.GetSystemMetrics(pc.SM_CXSCREEN)
    sh = u32_sm.GetSystemMetrics(pc.SM_CYSCREEN)
    pc.move_window(hwnd, 0, 0, sw // 2, sh)
    # 3) 校验左半屏(不再点击点位9重跑, 留待横向探测识别分离按钮)
    r = _wt.RECT()
    pc._u32().GetWindowRect(hwnd, ctypes.byref(r))
    return True, "Weixin 窗口已左移"


def _search_window_init_no_p9():
    """点位9专用: 搜一搜窗口初始化(不点击点位9)
    复制自 tasks.search_window_init, 删除了 2b 步'点击点位9(分离按钮)' 代码块"""

    from ...services import tasks as tasks_svc
    from ...core import computer as pc

    logs = []
    # 0) 前置判定: 微信左半屏 + 采集器右半屏
    u32_sm = pc._u32()
    sw = u32_sm.GetSystemMetrics(pc.SM_CXSCREEN)
    sh = u32_sm.GetSystemMetrics(pc.SM_CYSCREEN)
    half = sw // 2
    weixin = pc.find_windows(exe=tasks_svc.WECHAT_MAIN, visible_only=True)
    if not weixin:
        logs.append("前置不满足: 无可见 Weixin 窗口")
        return False, "; ".join(logs)
    r = _wt.RECT()
    pc._u32().GetWindowRect(weixin[0][0], ctypes.byref(r))
    appwin = pc.find_windows(title=tasks_svc.APP_TITLE, visible_only=True)
    if not appwin:
        appwin = pc.find_windows(exe=tasks_svc.APP_EXE, visible_only=True)
    if not appwin:
        logs.append("前置不满足: 未找到采集器窗口")
        return False, "; ".join(logs)
    r2 = _wt.RECT()
    pc._u32().GetWindowRect(appwin[0][0], ctypes.byref(r2))
    if abs(r2.left - half) > 2 or abs((r2.right - r2.left) - half) > 0:
        logs.append("前置不满足: 采集器不在右半屏")
        return False, "; ".join(logs)
    logs.append("前置满足: 微信左移 + 采集器右半屏")
    # 1) 点位11: 点击 -> 输入1 -> 全选删除
    p11 = tasks_svc._read_point(11)
    if p11:
        pc.mouse_click(p11[0], p11[1])
        logs.append(f"点击点位11({p11[0]},{p11[1]})")
        _time.sleep(0.1)
        pc.type_text("1")
        _time.sleep(0.1)
        pc.ctrl_key("A")
        _time.sleep(0.1)
        pc.key_press(pc.VK_DELETE)
        _time.sleep(0.2)
    else:
        logs.append("缺少点位11")
        return False, "; ".join(logs)
    # 2) 点位12: 点击搜索网络
    p12 = tasks_svc._read_point(12)
    if p12:
        pc.mouse_click(p12[0], p12[1])
        logs.append(f"点击点位12({p12[0]},{p12[1]})")
        _time.sleep(0.2)
    else:
        logs.append("缺少点位12")
        return False, "; ".join(logs)
    # 2b) 自动判断窗口分离: 宽度≠半屏则移微信左半屏(不点击点位9, 正在设置)
    u32_probe = pc._u32()
    sw_probe = u32_probe.GetSystemMetrics(pc.SM_CXSCREEN)
    wx_rect = _wt.RECT()
    pc._u32().GetWindowRect(weixin[0][0], ctypes.byref(wx_rect))
    if abs((wx_rect.right - wx_rect.left) - sw_probe // 2) > 0:
        pc.move_window(weixin[0][0], 0, 0, sw_probe // 2, wx_rect.bottom - wx_rect.top)
        _time.sleep(0.3)
        logs.append("微信宽度≠半屏(嵌入状态), 点位9设置中不点击分离按钮")
    else:
        logs.append("微信窗口已分离, 跳过分离按钮")
    # 3) 查找可见 WeChatAppEx 窗口, 并移到左半屏
    appex = pc.find_windows(exe=tasks_svc.WECHAT_APPEX, visible_only=True)
    if not appex:
        logs.append("未找到可见 WeChatAppEx 窗口(可能仍为嵌入模式, 待点位9分离)")
        return False, "; ".join(logs)
    hwnd2 = appex[0][0]
    u32_sm2 = pc._u32()
    sw2 = u32_sm2.GetSystemMetrics(pc.SM_CXSCREEN)
    sh2 = u32_sm2.GetSystemMetrics(pc.SM_CYSCREEN)
    pc.move_window(hwnd2, 0, 0, sw2 // 2, sh2)
    _time.sleep(0.5)

    def check():
        rr = _wt.RECT()
        pc._u32().GetWindowRect(hwnd2, ctypes.byref(rr))
        return abs(rr.left) <= 2 and abs((rr.right - rr.left) - sw2 // 2) <= 0

    if check():
        logs.append("WeChatAppEx 已在左半屏")
        return True, "; ".join(logs)
    pc.move_window(hwnd2, 0, 0, sw2 // 2, sh2)
    logs.append("WeChatAppEx 已移到左半屏")
    if check():
        return True, "; ".join(logs)
    logs.append("WeChatAppEx 未就位左半屏")
    return False, "; ".join(logs)


def _p9_probe(ctx, weixin_hwnd):
    """横向探测: 从微信主窗口最右边、y=点位11的y 向左点击; 点击后主窗口变窄即命中"""
    from ...services import tasks as tasks_svc
    from ...core import computer as _pc

    p11 = tasks_svc._read_point(11)
    if not p11:
        log.warning("点位9 缺点位11")
        return None
    u32 = _pc._u32()
    rect = ctypes.wintypes.RECT()
    u32.GetWindowRect(weixin_hwnd, ctypes.byref(rect))
    x_right = rect.right - 5 - 1      # 探测原点: 微信窗口右缘内缩5px
    x_left = rect.left + 5
    w0 = rect.right - rect.left        # 主窗口宽度(命中判据: 点击后变窄)
    sy = int(p11[1])                    # y 直接用点位11的y
    # 初始步长 = 点位11.x 到微信主窗口最左边 / 10(第1轮), 后续轮次依次减半
    base_step = max(1, (int(p11[0]) - x_left) // 10)
    for round_idx in range(3):
        divide = 1 << round_idx         # 每轮减半: 1, 2, 4, 8
        step = max(1, base_step // divide)
        log.info(f"点位9 第{round_idx+1}轮: y={sy} 右缘={x_right} 宽度={w0} 步长={step} (基准={base_step})")
        i = 0
        while True:
            cx = x_right - i * step
            if cx < rect.left:
                break
            ctx.click(cx, sy, wait_after=0.8)
            rnow = ctypes.wintypes.RECT()
            u32.GetWindowRect(weixin_hwnd, ctypes.byref(rnow))
            if (rnow.right - rnow.left) < w0 - 2:
                log.info(f"点位9 第{round_idx+1}轮点击({cx},{sy}) 分离成功 (宽 {w0}->{rnow.right-rnow.left})")
                return cx, sy
            i += 1
        log.warning(f"点位9 第{round_idx+1}轮未命中")
    return None


@flow_point("微信窗口初始化不合法时窗口分离按钮")
def _flow_point9_split_button(ctx):
    # 依赖点位(与库 depend_points 同步): [11, 12]
    from ...services import tasks as tasks_svc
    from ...core import computer as _pc

    log.info("点位9 ①微信窗口初始化(无点位9)...")
    ok_wx, _t = _init_wechat_no_p9()
    if not ok_wx:
        log.warning(f"点位9 微信窗口初始化失败: {_t}")
        return None, None
    log.info(f"点位9 ①微信窗口就位 ✓ ({_t[:40]})")
    log.info("点位9 ②采集器窗口初始化...")
    ok_ap, _t = tasks_svc.init_app_window()
    if not ok_ap:
        log.warning(f"点位9 采集器窗口初始化失败: {_t}")
        return None, None
    log.info(f"点位9 ②采集器就位 ✓ ({_t[:40]})")
    log.info("点位9 ③搜一搜窗口初始化(无点位9)...")
    _ok_sw, _t = _search_window_init_no_p9()
    log.info(f"点位9 ③搜一搜初始化: {'成功' if _ok_sw else '失败(嵌入模式可继续)'} | {_t[:60]}")
    _time.sleep(0.3)
    log.info("点位9 ④检查搜一搜是否已独立...")
    weixin = _pc.find_windows(exe=tasks_svc.WECHAT_MAIN, visible_only=True)
    if not weixin:
        log.warning("点位9 ④未找到微信主窗口")
        return None, None
    if _pc.find_windows(exe=tasks_svc.WECHAT_APPEX, visible_only=True):
        log.info("点位9 ④搜一搜窗口已独立, 无需分离按钮(99999)")
        return (99999, 99999, "搜一搜窗口独立，无需此点位")
    # 5) 横向探测: 从微信最右边、y=点位11的y 向左点击
    res = _p9_probe(ctx, weixin[0][0])
    if res is not None:
        return res
    return None, None


# ---------------------------------------------------------------------------

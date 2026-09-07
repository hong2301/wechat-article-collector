# -*- coding: utf-8 -*-
"""关键词查询流程模块(公众号查询页分支)。

分支位置: 采集流程在 article_list_wait_stable 之前分流——
  关键词参数为空  -> 走原 logic(article_list_wait_stable)
  关键词不为空    -> 走本模块流程
"""
import ctypes
import hashlib
import time as _time

from ...core import computer as pc
from ...core.common import wait_page_stable, _read_point
from .wx_window import WECHAT_APPEX

SW_APPEX = WECHAT_APPEX


def gzh_query_page_init(keyword: str = ""):
    """公众号查询页初始化(关键词查询分支第一步)。

    前提(文字记录, 本函数内部不做判定): 必须在【搜一搜窗口查询公众号成功】之后调用,
    即已通过搜一搜查询到公众号并进入其查询页(依赖 search_query 流程的产物)。

    参数:
      keyword  要查询的关键词(输入到公众号查询页搜索框)

    步骤:
      1. 页面稳定检测: 检测范围 = 搜一搜窗口的上半部分
         (基于搜一搜窗口坐标, 不基于屏幕; x=窗口全宽, y=窗口顶~窗口高一半)
         60 次机会, 连续 30 次截图相同即判稳定
      2. 稳定后点击点位41(公众号查询确认/列表, 点位已预置)
      3. 点击后等待0.3s, 剪贴板粘贴关键词(参考 search_query 输入法)
      4. 输入完等待0.2s, 按回车
      5. 回车后再次页面稳定检测(同样搜一搜窗口上半, 60次/连续30次)
      6. 稳定后点击点位42(查询结果列表/确认)

    返回: (成功?, 说明文本)
    """
    logs = []

    # 1) 基于搜一搜窗口取矩形
    appex = pc.find_windows(exe=SW_APPEX, visible_only=True)
    if not appex:
        logs.append("未找到搜一搜窗口(WeChatAppEx)")
        return False, "; ".join(logs)
    r = ctypes.wintypes.RECT()
    pc._u32().GetWindowRect(appex[0][0], ctypes.byref(r))
    win_x1, win_y1 = r.left, r.top
    win_half_y = r.top + (r.bottom - r.top) // 2      # 窗口上半部分底线
    win_x2, win_y2 = r.right, win_half_y

    # 2) 页面稳定检测(60次机会, 连续30次相同判稳定)
    ok, info = wait_page_stable(win_x1, win_y1, win_x2, win_y2,
                                same_need=30, timeout=60, interval=0.1)
    logs.append(f"查询页稳定检测: {'稳定' if ok else '未稳定'} | {info}")
    if not ok:
        logs.append("查询页60次内未达30次连续稳定")
        return False, "; ".join(logs)

    # 3) 稳定后点击点位41
    p41 = _read_point(41)
    if not p41:
        logs.append("缺少点位41(公众号查询确认)")
        return False, "; ".join(logs)
    pc.mouse_click(p41[0], p41[1])
    logs.append(f"已点击点位41({p41[0]},{p41[1]})")

    # 4) 点击后等待0.3s, 剪贴板粘贴关键词(参考 search_query 输入法)
    _time.sleep(0.3)
    if not pc.set_clipboard_text(keyword):
        logs.append("剪贴板写入关键词失败")
        return False, "; ".join(logs)
    pc.ctrl_key("V")
    logs.append(f"已粘贴关键词: {keyword}")

    # 5) 输入完等待0.2s, 按回车
    _time.sleep(0.2)
    pc.key_press(pc.VK_RETURN)
    logs.append("关键词输入完成, 已按回车")

    # 6) 回车后再次页面稳定检测(搜一搜窗口上半, 60次/连续30次)
    ok2, info2 = wait_page_stable(win_x1, win_y1, win_x2, win_y2,
                                  same_need=30, timeout=60, interval=0.1)
    logs.append(f"查询结果稳定检测: {'稳定' if ok2 else '未稳定'} | {info2}")
    if not ok2:
        logs.append("查询结果60次内未达30次连续稳定")
        return False, "; ".join(logs)

    # 7) 稳定后点击点位42(查询结果列表/确认)
    p42 = _read_point(42)
    if not p42:
        logs.append("缺少点位42(查询结果)")
        return False, "; ".join(logs)
    pc.mouse_click(p42[0], p42[1])
    logs.append(f"已点击点位42({p42[0]},{p42[1]})")
    return True, "; ".join(logs)
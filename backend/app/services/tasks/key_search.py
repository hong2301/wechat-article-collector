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


def gzh_query_page_init():
    """公众号查询页初始化(关键词查询分支第一步)。

    前提(文字记录, 本函数内部不做判定): 必须在【搜一搜窗口查询公众号成功】之后调用,
    即已通过搜一搜查询到公众号并进入其查询页(依赖 search_query 流程的产物)。

    步骤:
      1. 页面稳定检测: 检测范围 = 搜一搜窗口的上半部分
         (基于搜一搜窗口坐标, 不基于屏幕; x=窗口全宽, y=窗口顶~窗口高一半)
         60 次机会, 连续 30 次截图相同即判稳定
      2. 稳定后点击点位41(公众号查询确认/列表, 点位已预置)

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
    return True, "; ".join(logs)
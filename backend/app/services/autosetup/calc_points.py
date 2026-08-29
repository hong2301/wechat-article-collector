# -*- coding: utf-8 -*-
"""点位自动设置: 纯计算类点位 28/29(复制链接区域) 32/33(阅读数区域)
import ctypes
不操作窗口, 依赖对应点位坐标直接计算"""
from ...database import get_conn as _get_conn
from .engine import POINT_FLOWS, log   # noqa: F401  (POINT_FLOWS 用于注册)


# ---------------------------------------------------------------------------
# 点位 21/22: 阅读数左/右下 (同一自动设置, 依赖点位19已设值, 纯计算不操作窗口)
# ---------------------------------------------------------------------------
def _calc_reads_box(self_name):
    """32/33 纯计算: 阅读数区域(依赖4指标区域左上)
    依赖点位(与库 depend_points 同步): [30]"""
    def fn(ctx):
        from ...core import computer as _pc2
        conn = _get_conn()
        try:
            p19 = conn.execute(
                "SELECT x, y FROM points WHERE name=?", ("4指标区域左上",)).fetchone()
        finally:
            conn.close()
        if not p19 or not str(p19["x"] or "").strip() or not str(p19["y"] or "").strip():
            log.warning("点位21/22 缺少点位19")
            return None, None
        x19, y19 = int(float(p19["x"])), int(float(p19["y"]))
        u32_ = _pc2._u32()
        sh_ = u32_.GetSystemMetrics(_pc2.SM_CYSCREEN)
        x21, y21 = 0, sh_ // 2       # 21: 微信最左边x=0, 屏幕中点y
        x22, y22 = x19, y19          # 22: 直接赋值点位19
        conn = _get_conn()
        try:
            conn.execute("UPDATE points SET x=?, y=? WHERE name=?", (x21, y21, "阅读数左上"))
            conn.execute("UPDATE points SET x=?, y=? WHERE name=?", (x22, y22, "阅读数右下"))
            conn.commit()
        finally:
            conn.close()
        if self_name == "阅读数左上":
            return x21, y21
        return x22, y22
    return fn


POINT_FLOWS["阅读数左上"] = _calc_reads_box("阅读数左上")
POINT_FLOWS["阅读数右下"] = _calc_reads_box("阅读数右下")


# ---------------------------------------------------------------------------
# 点位 28/29: 复制链接左上/右下 (同一流程, 一起设置)
# 流程: 微信就位 -> 搜一搜初始化(点11/12/9) -> 等0.5s
#   -> 截图"屏幕中间这一块再上下取上"(x∈[w/3,2w/3], y∈[0,h/2])
#   -> 点击点位18(右上角3点弹出菜单) -> 等1s -> 再截图同一块
#   -> 对比变化区域外接矩形 = 复制链接菜单区: 28=左上, 29=右下 双写
# ---------------------------------------------------------------------------
def _flow_copy_link_find(ctx):
    """纯计算: 28/29 = 左半屏右上部分, 无需任何窗口操作
    依赖点位(与库 depend_points 同步): []"""
    from ...core import computer as _pcc
    u32_ = _pcc._u32()
    sw_ = u32_.GetSystemMetrics(_pcc.SM_CXSCREEN)
    sh_ = u32_.GetSystemMetrics(_pcc.SM_CYSCREEN)
    x_left, y_top = sw_ // 4, 0
    x_right, y_bot = sw_ // 2, sh_ // 2
    log.info(f"点位28/29 设定左半屏右上: ({x_left},{y_top})-({x_right},{y_bot})")
    return x_left, y_top, x_right, y_bot


def _copy_link_entry(self_name):
    def fn(ctx):
        res = _flow_copy_link_find(ctx)
        if res is None:
            return None, None
        ax1, ay1, ax2, ay2 = res
        conn = _get_conn()
        try:
            conn.execute("UPDATE points SET x=?, y=? WHERE name=?", (ax1, ay1, "复制链接左上"))
            conn.execute("UPDATE points SET x=?, y=? WHERE name=?", (ax2, ay2, "复制链接右下"))
            conn.commit()
        finally:
            conn.close()
        if self_name == "复制链接左上":
            return ax1, ay1
        return ax2, ay2
    return fn


POINT_FLOWS["复制链接左上"] = _copy_link_entry("复制链接左上")
POINT_FLOWS["复制链接右下"] = _copy_link_entry("复制链接右下")

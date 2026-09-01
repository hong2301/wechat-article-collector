# -*- coding: utf-8 -*-
import ctypes
"""点位自动设置: 纯计算类点位(阅读数区域)
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

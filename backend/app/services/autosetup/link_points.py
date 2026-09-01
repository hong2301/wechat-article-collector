# -*- coding: utf-8 -*-
"""点位自动设置: 列表/链接类点位 15/16(文章列表) 18(右上角3点) 27(点击复制链接)"""
import ctypes
import time as _time
from PIL import Image, ImageGrab
import numpy as np
from ...database import get_conn as _get_conn
from .engine import POINT_FLOWS, flow_point, log   # noqa: F401


# 点位 15/16: 文章列表左上角 / 文章列表右下角 (同一流程, 一次得到两个坐标)
# 依赖: 11/12/9/14 全部前置点位
# 流程: 微信就位 -> 搜一搜初始化(点11+12+9分离) -> 搜一搜查询测试公众号
#   -> 等5s加载 -> 左半屏截图 -> 移到左半屏中间滚500px -> 再截图
#   -> 对比两张图变化区域得文章列表矩形(左上=15, 右下=16), 同时写入两个点位
# ---------------------------------------------------------------------------
TEST_BIZ = "MzA4OTQ5NTk2Mw=="
# 搜一搜查询用完整公众号链接(与采集主流程一致: profile_ext?action=home&__biz=<biz>)
TEST_BIZ_QUERY = "https://mp.weixin.qq.com/mp/profile_ext?action=home&__biz=" + TEST_BIZ


def _flow_articles_list_full(ctx, self_name, rx1, ry1, rx2, ry2):
    """识别已经由 _flow_articles_list_find 完成; 此处按当前点位名返回对应坐标(避免路由覆写错位)"""
    if self_name == "文章列表左上角":
        return rx1, ry1
    return rx2, ry2


def _flow_articles_list_find(ctx):
    """15/16 共同识别: 找到文章列表矩形并写入两个点位; 返回 (rx1,ry1,rx2,ry2) 或 None
    依赖点位(与库 depend_points 同步): [11, 12, 9, 14]"""
    from ...services import tasks as tasks_svc
    from ...core import computer as _pc

    # 完整调用: 微信窗口初始化 + 搜一搜窗口初始化
    log.info("点位15/16 ①微信窗口初始化...")
    ok_wx, txt_wx = tasks_svc.init_wechat_window()
    if not ok_wx:
        log.warning(f"点位15/16 微信窗口初始化失败: {txt_wx}")
        return None
    log.info(f"点位15/16 ①微信就位 ✓ {txt_wx[:40]}")
    log.info("点位15/16 ②采集器窗口初始化...")
    ok_ap, txt_ap = tasks_svc.init_app_window()
    if not ok_ap:
        log.warning(f"点位15/16 采集器窗口初始化失败: {txt_ap}")
        return None
    log.info(f"点位15/16 ②采集器就位 ✓ {txt_ap[:40]}")
    log.info("点位15/16 ③搜一搜窗口初始化...")
    ok_sw, txt_sw = tasks_svc.search_window_init()
    if not ok_sw:
        log.warning(f"点位15/16 搜一搜窗口初始化失败: {txt_sw}")
        return None
    log.info(f"点位15/16 ③搜一搜就位 ✓ {txt_sw[:60]}")
    wr = _pc.wechat_rect()                    # 微信窗口(内缩1%)为基准
    if not wr:
        log.warning("点位15/16 未找到微信窗口")
        return None
    _w, _h = wr[2] - wr[0], wr[3] - wr[1]

    # 搜一搜查询测试公众号
    log.info("点位15/16 ④查询测试公众号...")
    ok_q, _txt = tasks_svc.search_query(TEST_BIZ_QUERY)
    if not ok_q:
        log.warning("点位15/16 ④搜一搜查询失败: " + _txt)
        return None
    log.info(f"点位15/16 ④查询成功 ✓ {_txt[:60]}")
    _time.sleep(5.0)                        # 等加载

    # 先下滚1000 -> 截图1; 再下滚1000 -> 截图2; 对比得出列表区
    _pc.scroll(wr[0] + _w // 4, wr[1] + _h // 2, 1000, direction="down", wait_after=0.8)
    img1 = np.array(ImageGrab.grab(bbox=(wr[0], wr[1], wr[2], wr[3])).convert("RGB"))
    _pc.scroll(wr[0] + _w // 4, wr[1] + _h // 2, 1000, direction="down", wait_after=0.8)
    img2 = np.array(ImageGrab.grab(bbox=(wr[0], wr[1], wr[2], wr[3])).convert("RGB"))

    # 对比: 变化区域的外接矩形 = 文章列表区(相对截图 -> 加窗口偏移为绝对)
    diff = np.abs(img2.astype(int) - img1.astype(int)).sum(axis=2)
    mask = diff > 40
    ys, xs = np.where(mask)
    if len(xs) < 50:
        log.warning(f"点位15/16 变化区域过小({len(xs)}px), 文章列表未加载?")
        return None
    _img1 = Image.fromarray(img1)              # img1 已是 RGB ndarray(不需要 convert)
    bbox = (wr[0], wr[1], wr[2], wr[3])
    rx1 = pc.shot_abs(_img1, bbox, int(xs.min()), int(ys.min()))[0]
    ry1 = pc.shot_abs(_img1, bbox, int(xs.min()), int(ys.min()))[1]
    rx2 = pc.shot_abs(_img1, bbox, int(xs.max()), int(ys.max()))[0]
    ry2 = pc.shot_abs(_img1, bbox, int(xs.max()), int(ys.max()))[1]
    log.info(f"点位15/16 文章列表矩形: ({rx1},{ry1})-({rx2},{ry2})")

    return rx1, ry1, rx2, ry2


def _articles_list_entry(self_name):
    """包装: 识别矩形(含写库15/16) -> 按当前点位名返回坐标"""
    def fn(ctx):
        res = _flow_articles_list_find(ctx)
        if res is None:
            return None, None
        rx1, ry1, rx2, ry2 = res
        conn = _get_conn()
        try:
            # 16.x = 14.x 与 16.x 的中点; 15.x 向右移 10px
            p14 = conn.execute(
                "SELECT x FROM points WHERE name=?", ("搜一搜窗口查询按钮",)).fetchone()
            if p14 and str(p14["x"] or "").strip():
                p14x = int(float(p14["x"]))
                rx2 = (p14x + rx2) // 2
            rx1 = rx1 + 10
            conn.execute("UPDATE points SET x=?, y=? WHERE name=?", (rx1, ry1, "文章列表左上角"))
            conn.execute("UPDATE points SET x=?, y=? WHERE name=?", (rx2, ry2, "文章列表右下角"))
            conn.commit()
        finally:
            conn.close()
        return _flow_articles_list_full(ctx, self_name, rx1, ry1, rx2, ry2)
    return fn


POINT_FLOWS["文章列表左上角"] = _articles_list_entry("文章列表左上角")
POINT_FLOWS["文章列表右下角"] = _articles_list_entry("文章列表右下角")


# ---------------------------------------------------------------------------
# 点位 18: 文章右上角3点
# 依赖点位(与库 depend_points 同步): [11, 12, 9, 14]
# 流程: 初始化(微信/采集器/搜一搜) -> 从搜一搜窗口最右边向左探测:
#   原点 x=搜一搜窗口最右边, y=搜一搜按钮(点位14)的y
#   步长 = (搜一搜按钮.x - 搜一搜窗口左边) / 30, 每轮减半
#   识别: 先截图 -> 点击 -> 截图对比(第一下等3s, 其余0.5s):
#     有变化记为第1次变化, 继续动; 数到第4次变化后原地再点击确认:
#       点击后窗口无变化 => 目标点位; 有变化 => 步长过大
#     扫过搜一搜按钮位置仍未凑满4次变化 => 步长过大

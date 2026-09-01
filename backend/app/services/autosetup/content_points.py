# -*- coding: utf-8 -*-
from PIL import Image, ImageGrab
from ...core import computer as pc
import time as _time
from PIL import ImageGrab
import numpy as np
"""点位自动设置: 文章内容区点位 30/31(4指标) 34(评论按钮) 35/36(评论区)
依赖前置点位搜索出文章后 OCR/截图识别"""
from ...database import get_conn as _get_conn
from .engine import POINT_FLOWS, flow_point, log   # noqa: F401  (POINT_FLOWS 注册 / flow_point 装饰器)


ARTICLE_LINK_DEMO = "https://mp.weixin.qq.com/s/X7fAdvvZ-Gq_2SW19OKfVw"

# 30/31(4指标区域)专用演示链接(用户指定换为新的)
ARTICLE_LINK_DEMO_BAR = "https://mp.weixin.qq.com/s/LrmG9G4qXeo8A0xDAcMX3Q"


def _flow_article_bar_find(ctx):
    """30/31 共同识别: 找文章底栏(4指标区域)写入两个点位
    依赖点位(与库 depend_points 同步): [11, 12, 9, 14]"""
    from ...services import tasks as tasks_svc
    from ...core import computer as _pc

    # 完整调用: 微信窗口初始化 + 搜一搜窗口初始化
    ok_wx, txt_wx = tasks_svc.init_wechat_window()
    if not ok_wx:
        log.warning(f"点位30/31 微信窗口初始化失败: {txt_wx}")
        return None
    ok_ap, txt_ap = tasks_svc.init_app_window()
    if not ok_ap:
        log.warning(f"点位30/31 采集器窗口初始化失败: {txt_ap}")
        return None

    ok_sw, txt_sw = tasks_svc.search_window_init()
    if not ok_sw:
        log.warning(f"点位30/31 搜一搜窗口初始化失败: {txt_sw}")
        return None
    wr = _pc.wechat_rect()                    # 微信窗口(内缩1%)为基准
    if not wr:
        log.warning("点位30/31 未找到微信窗口")
        return None
    _w, _h = wr[2] - wr[0], wr[3] - wr[1]

    ok_q, _txt = tasks_svc.search_query(ARTICLE_LINK_DEMO_BAR)   # 仅30/31用新链接
    if not ok_q:
        return None
    _time.sleep(5.0)

    # 截微信窗口最下2/10, OCR找"关注"box(1/10窄条OCR不稳; 关注按钮在最底部)
    y0_1, y1_1 = wr[1] + _h * 8 // 10, wr[3]
    shot = ImageGrab.grab(bbox=(wr[0], y0_1, wr[2], y1_1)).convert("RGB")
    hit = None
    for cx, cy, text, score, sbox, _br in ctx.ocr_box(shot):
        if "关注" in text:
            ys = [p[1] for p in sbox]
            h = max(ys) - min(ys)
            hit = (wr[0] + int(cx), y0_1 + int(cy), h)   # 截图起点为窗口: 加x偏移
            break
    if not hit:
        return None
    cx_abs, cy_abs, box_h = hit

    # 高度上下扩大120%
    H = box_h * 1.2
    y_top = int(cy_abs - H / 2)
    y_bot = int(cy_abs + H / 2)
    x_left = wr[0] + _w // 4        # 窗口内 x 1/4(原左半屏 x 中点语义)
    x_right = wr[2]                 # 窗口右缘(原屏幕中线语义)
    return x_left, y_top, x_right, y_bot


def _article_bar_entry(self_name):
    def fn(ctx):
        res = _flow_article_bar_find(ctx)
        if res is None:
            return None, None
        x_left, y_top, x_right, y_bot = res
        conn = _get_conn()
        try:
            conn.execute("UPDATE points SET x=?, y=? WHERE name=?", (x_left, y_top, "4指标区域左上"))
            conn.execute("UPDATE points SET x=?, y=? WHERE name=?", (x_right, y_bot, "4指标区域右下"))
            conn.commit()
        finally:
            conn.close()
        if self_name == "4指标区域左上":
            return x_left, y_top
        return x_right, y_bot
    return fn


POINT_FLOWS["4指标区域左上"] = _article_bar_entry("4指标区域左上")
POINT_FLOWS["4指标区域右下"] = _article_bar_entry("4指标区域右下")



# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------


# 点位 34: 评论按钮
# 流程: 微信+搜一搜完整调用 -> 搜一搜查询文章链接 -> 等1s
#   -> 从屏幕中线往左点击, y=30/31 y中点, 步长=(屏幕中线-31.x)/5(每轮减半):
#     点击后截[30,31]区域: 有变化且有红色=>步长太大点过(重来减半);
#     有变化无红色=>命中评论按钮, 记录
# ---------------------------------------------------------------------------
def _diff_red(img1, img2):
    """[30,31]区域变化率 + 变化区域是否含红色"""
    d = np.abs(img2.astype(int) - img1.astype(int)).sum(axis=2)
    changed = (d > 15).mean()
    if changed <= 0.001:
        return changed, False
    # 红色检测: 变化像素中红色(R明显高于G/B)
    mask = d > 15
    r, g, b = img2.astype(int)[..., 0], img2.astype(int)[..., 1], img2.astype(int)[..., 2]
    red_mask = (r > 120) & (r - g > 50) & (r - b > 50) & mask
    return float(changed), bool(red_mask.any())


@flow_point("评论按钮")
def _flow_point34_comment(ctx):
    # 依赖点位(与库 depend_points 同步): [11, 12, 9, 14, 30, 31]
    from ...services import tasks as tasks_svc
    from ...core import computer as _pc

    ok_wx, txt_wx = tasks_svc.init_wechat_window()
    if not ok_wx:
        log.warning(f"点位34 微信窗口初始化失败: {txt_wx}")
        return None, None
    ok_ap, txt_ap = tasks_svc.init_app_window()
    if not ok_ap:
        log.warning(f"点位34 采集器窗口初始化失败: {txt_ap}")
        return None, None

    ok_sw, txt_sw = tasks_svc.search_window_init()
    if not ok_sw:
        log.warning(f"点位34 搜一搜初始化失败: {txt_sw}")
        return None, None
    ok_q, txt_q = tasks_svc.search_query(ARTICLE_LINK_DEMO)
    if not ok_q:
        log.warning(f"点位34 查询文章链接失败: {txt_q}")
        return None, None

    p30 = tasks_svc._read_point(30)
    p31 = tasks_svc._read_point(31)
    if not p30 or not p31:
        log.warning("点位34 缺30/31")
        return None, None
    wr = _pc.wechat_rect()                    # 微信窗口(内缩1%)为基准
    if not wr:
        log.warning("点位34 未找到微信窗口")
        return None, None
    # [30,31]页面稳定检测(50次/连续30相同)后再截图基准
    ok_st, info_st = tasks_svc.wait_page_stable(p30[0], p30[1], p31[0], p31[1],
                                                same_need=30, timeout=50, interval=0.1)
    if not ok_st:
        log.warning(f"点位34 [30,31]未稳定: {info_st}")
    else:
        log.info(f"点位34 [30,31]稳定: {info_st}")

    sy = (p30[1] + p31[1]) // 2
    mid_x = wr[2]
    raw_step = max(1, (mid_x - p30[0]) // 10)   # 步长=(屏幕中线-30.x)/10
    box = (p30[0], p30[1], p31[0], p31[1])
    _pc._u32().ShowCursor(False)                       # 隐藏光标(防光标入镜误判)
    baseline = np.array(ImageGrab.grab(bbox=box).convert("RGB"))   # 初始基准图(稳定后)
    _pc._u32().ShowCursor(True)
    # 调试: 保存基准图到桌面
    try:
        Image.fromarray(baseline).save("C:/Users/86150/Desktop/_p34_base.png")
    except Exception as e:
        log.warning(f"基准图保存失败: {e}")

    for round_i in range(3):
        step = max(1, raw_step // (1 << round_i))
        log.info(f"点位34 第{round_i+1}轮: y={sy} 起点={mid_x} 步长={step}")
        x = mid_x
        while x > p30[0]:
            ctx.click(x, sy, wait_after=0.8)   # 点击后等红点反馈消失再截图
            _pc._u32().ShowCursor(False)
            after = np.array(ImageGrab.grab(bbox=box).convert("RGB"))   # 隐藏光标截图
            _pc._u32().ShowCursor(True)
            # 调试: 保存本次点击后图到桌面
            try:
                Image.fromarray(after).save(f"C:/Users/86150/Desktop/_p34_click_{x}_{sy}.png")
            except Exception:
                pass
            # 与初始基准对比(评论按钮点击后变化>50%, 阈值15%过滤点击副作用~0.2%)
            d = np.abs(after.astype(int) - baseline.astype(int)).sum(axis=2)
            changed = (d > 15).mean()
            if changed <= 0.15:
                x -= step
                continue
            r, g, b = after.astype(int)[..., 0], after.astype(int)[..., 1], after.astype(int)[..., 2]
            red = bool(((r > 120) & (r - g > 50) & (r - b > 50) & (d > 15)).any())
            if red:
                log.warning(f"点位34 ({x},{sy}) 变化且红色 chr={changed:.3f} => 步长过大重试")
                break
            log.info(f"点位34 命中评论按钮: ({x},{sy})")
            return x, sy
    log.warning("点位34 多轮未命中")
    return None, None


# ---------------------------------------------------------------------------
# 点位 35/36: 评论区左上/右下 (共用前置打开评论区, 识别逻辑各自独立)
# 前置: 采集器窗口初始化->微信窗口初始化->搜一搜窗口初始化->查询文章链接
#   -> 检测[30,31]稳定 -> 点34(评论按钮)打开评论区 -> 等评论区区域稳定
# 36(右下): 滚动对比变化区域外接矩形 右下角(原逻辑不变)
# 35(左上): 截微信窗口上一半 -> OCR找"留言"(黑字白底) -> box左上角 = 目标点位
# ---------------------------------------------------------------------------
def _comment_area_prep(ctx):
    """35/36 共用前置: 打开评论区并等页面稳定; 返回 (wr, 评论区区域) 或 None"""
    from ...services import tasks as tasks_svc
    from ...core import computer as _pc
    ok_ap, txt_ap = tasks_svc.init_app_window()
    if not ok_ap:
        log.warning("点位35/36 采集器窗口初始化失败: " + str(txt_ap))
        return None
    ok_wx, txt_wx = tasks_svc.init_wechat_window()
    if not ok_wx:
        log.warning("点位35/36 微信窗口初始化失败: " + str(txt_wx))
        return None
    ok_sw, txt_sw = tasks_svc.search_window_init()
    if not ok_sw:
        log.warning("点位35/36 搜一搜窗口初始化失败: " + str(txt_sw))
        return None
    ok_q, txt_q = tasks_svc.search_query(ARTICLE_LINK_DEMO)
    if not ok_q:
        log.warning("点位35/36 查询文章链接失败: " + str(txt_q))
        return None
    p30 = tasks_svc._read_point(30)
    p31 = tasks_svc._read_point(31)
    if not p30 or not p31:
        log.warning("点位35/36 缺30/31")
        return None
    ok_st, info_st = tasks_svc.wait_page_stable(p30[0], p30[1], p31[0], p31[1],
                                                same_need=30, timeout=50, interval=0.1)
    if not ok_st:
        log.warning(f"点位35/36 4指标区域未稳定: {info_st}")
    else:
        log.info(f"点位35/36 4指标区域稳定: {info_st}")
    p34 = tasks_svc._read_point(34)
    if not p34:
        log.warning("点位35/36 缺34")
        return None
    ctx.click(p34[0], p34[1], wait_after=1.0)
    wr = _pc.wechat_rect()
    if not wr:
        log.warning("点位35/36 未找到微信窗口")
        return None
    _w36, _h36 = wr[2] - wr[0], wr[3] - wr[1]
    rx1, ry1, rx2, ry2 = wr[0] + _w36 // 4, wr[1], wr[2], wr[3]
    ok_st2, info_st2 = tasks_svc.wait_page_stable(rx1, ry1, rx2, ry2,
                                                  same_need=30, timeout=50, interval=0.1)
    if not ok_st2:
        log.warning(f"点位35/36 评论区区域未稳定: {info_st2}")
    else:
        log.info(f"点位35/36 评论区区域稳定: {info_st2}")
    return (wr, rx1, ry1, rx2, ry2)


def _flow_comment_area_find(ctx):
    """点位36专用: 点34打开评论区后滚动对比识别评论区矩形右下角(原逻辑不变)"""
    from ...core import computer as _pc
    prep = _comment_area_prep(ctx)
    if not prep:
        return None
    wr, rx1, ry1, rx2, ry2 = prep
    _pc._u32().ShowCursor(False)
    img1 = np.array(ImageGrab.grab(bbox=(rx1, ry1, rx2, ry2)).convert("RGB"))
    _pc._u32().ShowCursor(True)
    _pc.scroll((rx1 + rx2) // 2, (ry1 + ry2) // 2, 500, direction="down", wait_after=1.0)
    _pc._u32().ShowCursor(False)
    img2 = np.array(ImageGrab.grab(bbox=(rx1, ry1, rx2, ry2)).convert("RGB"))
    _pc._u32().ShowCursor(True)
    d = np.abs(img2.astype(int) - img1.astype(int)).sum(axis=2)
    mask = d > 40
    ys, xs = np.where(mask)
    if len(xs) < 50:
        log.warning(f"点位36 变化区域过小({len(xs)}px)")
        return None
    gx1, gy1, gx2, gy2 = int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())
    ax1, ay1 = rx1 + gx1, ry1 + gy1
    ax2, ay2 = rx1 + gx2, ry1 + gy2
    log.info(f"点位36 评论区矩形: ({ax1},{ay1})-({ax2},{ay2})")
    return ax1, ay1, ax2, ay2


def _flow_comment_left_find(ctx):
    """点位35专用: 截微信窗口上一半 -> OCR找"留言"(黑字白底) -> box左上角 = 目标点位"""
    from ...core import computer as _pc
    prep = _comment_area_prep(ctx)
    if not prep:
        return None
    wr, _rx1, _ry1, _rx2, _ry2 = prep
    _w, _h = wr[2] - wr[0], wr[3] - wr[1]
    # 截微信窗口上一半
    img = ImageGrab.grab(bbox=(wr[0], wr[1], wr[2], wr[1] + _h // 2)).convert("RGB")
    for cx, cy, text, _score, sbox, _br in ctx.ocr_box(img):
        if not text or "留言" not in text:
            continue
        # 颜色判据: 黑字白底(前两主色 含黑且含白)
        cols = ocr_service.color_sort(img, region=(
            min(p[0] for p in sbox), min(p[1] for p in sbox),
            max(p[0] for p in sbox), max(p[1] for p in sbox)))
        colset = {c for _, _, c in cols[:2]}
        if not cols or not ({"黑", "白"}.issubset(colset)):
            log.info(f"点位35 文本命中但颜色不符({cols}): {text}")
            continue
        # box 左上角 = 目标点位(截图起点为窗口左上, 加偏移)
        bx, by = wr[0] + int(min(p[0] for p in sbox)), wr[1] + int(min(p[1] for p in sbox))
        log.info(f"点位35 识别'留言'成功: ({bx},{by}) 颜色排序={[c for _,_,c in (cols or [])][:3]}")
        return bx, by
    log.warning("点位35 未识别到黑字白底的'留言'")
    return None


def _comment_area_entry(self_name):
    def fn(ctx):
        res = _flow_comment_area_find(ctx)
        if res is None:
            return None, None
        _ax1, _ay1, ax2, ay2 = res
        # 点位36(评论区右下): x 改为微信窗口右缘
        _wr36 = pc.wechat_rect()
        ax2 = _wr36[2] if _wr36 else ax2
        conn = _get_conn()
        try:
            conn.execute("UPDATE points SET x=?, y=? WHERE name=?", (ax2, ay2, "评论区右下"))
            conn.commit()
        finally:
            conn.close()
        return ax2, ay2
    return fn


def _comment_left_entry(self_name):
    def fn(ctx):
        res = _flow_comment_left_find(ctx)
        if res is None:
            return None, None
        bx, by = res
        conn = _get_conn()
        try:
            conn.execute("UPDATE points SET x=?, y=? WHERE name=?", (bx, by, "评论区左上"))
            conn.commit()
        finally:
            conn.close()
        return bx, by
    return fn


POINT_FLOWS["评论区左上"] = _comment_left_entry("评论区左上")
POINT_FLOWS["评论区右下"] = _comment_area_entry("评论区右下")
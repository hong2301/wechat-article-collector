# -*- coding: utf-8 -*-
"""点位自动设置: 基础 OCR 点位 11(搜索框) 12(搜索网络)"""
from ...core import ocr as ocr_service
from ...core import computer as pc
import ctypes
import time as _time
from PIL import Image
import numpy as np
from .engine import POINT_FLOWS, flow_point, log, _ensure_wechat   # noqa: F401



from .engine import _ensure_wechat  # noqa: F401


@flow_point("微信左上角搜索网络")
def _flow_point12_search_network(ctx):
    # 依赖点位(与库 depend_points 同步): [11]
    from ...services import tasks as tasks_svc

    # 1) 微信窗口就位(左半屏): 优先采集初始化, 失败则手动摆正
    if not _ensure_wechat():
        return None, None

    # 2) 严格按采集点位11动作: 点击搜索框 -> 输入1 -> 全选删除(激活并展开下拉)
    p11 = tasks_svc._read_point(11)
    if not p11:
        return None, None
    ctx.click(p11[0], p11[1], wait_after=0.2)
    pc.type_text("1")
    _time.sleep(0.1)
    pc.ctrl_key("A")
    _time.sleep(0.1)
    pc.key_press(pc.VK_DELETE)
    _time.sleep(0.8)

    # 3) (采集此处点击点位12, 自动设置改为:) 截图微信窗口左上1/4区域 -> OCR找"搜索网络结果"
    wr = pc.wechat_rect()
    if not wr:
        log.warning("点位12 未找到微信窗口")
        return None, None
    _w, _h = wr[2] - wr[0], wr[3] - wr[1]
    for attempt in range(3):
        img = Image.open(pc.screenshot(wr[0], wr[1], wr[0] + _w // 4, wr[1] + _h // 4)[0]).convert("RGB")
        for cx, cy, text, score, sbox, _bright in ctx.ocr_box(img):
            _cx_abs, _cy_abs = wr[0] + int(cx), wr[1] + int(cy)
            if "网络结果" not in text:
                continue
            # 校验: 文字框 RGB 频率排序, 前两主色应为"暗色字+白底"(黑/灰字白底, 不管顺序)
            cols = ocr_service.color_sort(img, region=(
                min(p[0] for p in sbox), min(p[1] for p in sbox),
                max(p[0] for p in sbox), max(p[1] for p in sbox)))
            colset = {c for _, _, c in cols[:2]}
            if not cols or "白" not in colset or not ({"黑", "灰"} & colset):
                log.info(f"点位12 文本命中但颜色不符({cols}): {text}")
                continue
            log.info(f"点位12 识别成功: 文本={text} box=({_cx_abs},{_cy_abs}) 颜色排序={cols}")
            return _cx_abs, _cy_abs
        if attempt == 1:
            # 兜底: 重复点位11动作(下拉未弹出时)
            ctx.click(p11[0], p11[1], wait_after=0.2)
            pc.type_text("1")
            _time.sleep(0.1)
            pc.ctrl_key("A")
            _time.sleep(0.1)
            pc.key_press(pc.VK_DELETE)
            _time.sleep(0.8)
        else:
            _time.sleep(1.0)
    log.warning("点位12 未识别到黑字白底的'搜索网络结果'")
    return None, None


# ---------------------------------------------------------------------------
# 点位 11: 点击微信左上角搜索输入框
# 流程: 截图屏幕左上1/16 -> OCR找"搜索"文本 -> 校验灰字白底 -> 中心坐标即输入框位置
# ---------------------------------------------------------------------------
@flow_point("点击微信左上角搜索输入框")
def _flow_point11_search_box(ctx):
    # 依赖点位(与库 depend_points 同步): []
    from ...services import tasks as tasks_svc

    # 微信窗口就位(左半屏): 优先采集初始化, 失败则手动摆正
    if not _ensure_wechat():
        return None, None

    wr = pc.wechat_rect()                    # 微信窗口(4边各内缩1%): 基准用窗口而非屏幕
    if not wr:
        log.warning("点位11 未找到微信窗口")
        return None, None
    _w, _h = wr[2] - wr[0], wr[3] - wr[1]
    x1, y1, x2, y2 = wr[0], wr[1], wr[0] + _w // 4, wr[1] + _h // 4   # 窗口内左上 1/4×1/4
    img = Image.open(pc.screenshot(x1, y1, x2, y2)[0]).convert("RGB")

    items = ctx.ocr_box(img)                       # [(cx,cy,text,score,sbox,brightness)]
    for cx, cy, text, score, sbox, _bright in items:
        if "搜索" not in text:
            continue
        # 颜色校验: 文字框 RGB 频率排序, 前两主色应为{灰,白}(灰字白底, 不管顺序)
        cols = ocr_service.color_sort(img, region=(
            min(p[0] for p in sbox), min(p[1] for p in sbox),
            max(p[0] for p in sbox), max(p[1] for p in sbox)))
        colset = {c for _, _, c in cols[:2]}
        if not cols or not {"灰", "白"}.issubset(colset):
            log.info(f"点位11 文本命中但颜色不符({cols}): {text}")
            continue
        # 截图起点为窗口左上(x1,y1): 相对坐标转窗口内缩后绝对坐标
        _ex, _ey = x1 + int(cx), y1 + int(cy)
        log.info(f"点位11 识别成功: 文本={text} box=({_ex},{_ey}) 颜色排序={cols}")
        return _ex, _ey
    log.warning("点位11 未识别到白底灰字的'搜索'输入框")
    return None, None


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# 点位 14: 搜一搜窗口查询按钮 (依赖 11/12/9)
# 流程: 微信初始化 -> 初始化搜一搜(点11+输入1+全选删除+点12, 无独立窗则点9分离)
#   -> 截图左半屏最上1/10, OCR"搜一搜"取中心y
#   -> 从左半屏右边的中线(sw*3//8)往左点击, 步长=(sw*3//8-搜一搜x)/20:
#      点击后截图对比有变化=>命中查询按钮(成功);
#      搜一搜窗口被关闭=>步长过大(点到关闭), 整轮重来步长减半
# ---------------------------------------------------------------------------
@flow_point("搜一搜窗口查询按钮")
def _flow_point14_query_button(ctx):
    # 依赖点位(与库 depend_points 同步): [11, 12, 9]
    from ...services import tasks as tasks_svc
    from ...core import computer as _pc

    # 新探测逻辑: 原点=搜一搜文本box右上角, 向右扫, 步长=box中心x/10, 上限3sw/8,
    # 截图x∈[box.max_x,3sw/8], y∈[0,box.top]; 2次变化后点击, 窗口未关=命中, 关闭=步长过大减半重试
    for round_idx in range(3):
        if not _ensure_wechat():
            return None, None
        ok_sw, txt_sw = tasks_svc.search_window_init()
        if not ok_sw:
            log.warning(f"点位14 搜一搜窗口初始化失败: {txt_sw}")
            return None, None

        wr = _pc.wechat_rect()                    # 微信窗口(内缩1%)为基准
        if not wr:
            log.warning("点位14 未找到微信窗口")
            return None, None
        _w, _h = wr[2] - wr[0], wr[3] - wr[1]
        x2 = wr[2]                                   # 窗口右缘(=左半屏右缘)
        y_top = wr[1] + _h * 2 // 10                 # 最上 2/10
        img0 = Image.open(pc.screenshot(wr[0], wr[1], wr[2], wr[3])[0]).convert("RGB")
        box = None
        for _cx, cy, text, _score, sbox, _br in ctx.ocr_box(img0):
            if "搜一搜" in text and cy <= y_top - wr[1]:
                box = sbox
                break
        if not box:
            log.warning("点位14 未识别到'搜一搜'文本")
            return None, None

        xs = [p[0] for p in box]; ys = [p[1] for p in box]
        ox = wr[0] + max(xs)                       # 原点 x = box最右(绝对)
        oy = wr[1] + (min(ys) + max(ys)) // 2      # 原点 y = box中点(绝对)
        mid_x = wr[0] + int(sum(xs) / len(xs))     # box中心x(绝对)
        limit_x = wr[0] + _w * 3 // 8              # 上限: 窗口内 x 3/8(原3sw/8语义)
        shot_box = (ox, wr[1], limit_x, oy)        # 截图范围: x∈[ox,limit_x], y∈[窗口顶,oy]

        def snap():
            return np.array(Image.open(pc.screenshot(*shot_box)[0]).convert("RGB"))

        def changed(a, b):
            return (np.abs(a.astype(int) - b.astype(int)).sum(axis=2) > 15).mean()

        divide = 1 << round_idx
        step = max(1, mid_x // 10 // divide)   # 步长 = box中心x/10, 每轮减半
        log.info(f"点位14 第{round_idx+1}轮: 原点=({ox},{oy}) 步长={step} 上限x={limit_x} 截图{shot_box}")
        base0 = snap()       # 初始基准(未hover)
        base1 = None         # 首次变化后的基准(变化时保存)
        changes = 0
        cx = ox
        while cx < limit_x:
            _pc._u32().SetCursorPos(cx, oy)
            _time.sleep(0.5)
            cur = snap()
            if base1 is None:
                # 首次变化判定: 与初始基准比
                if changed(cur, base0) > 0.001:
                    changes = 1
                    base1 = cur          # 保存变化后的图作为新基准
                    log.info(f"点位14 第{round_idx+1}轮 ({cx},{oy}) 第1次变化(已存基准)")
            else:
                # 已出现首次变化: 对比"初始基准"与"变化基准"两张
                c0 = changed(cur, base0)
                c1 = changed(cur, base1)
                if c0 > 0.001 and c1 > 0.001:
                    # 与两张都不同 -> 新的变化状态(非恢复初始, 非停留在原状态)
                    changes += 1
                    base1 = cur
                    log.info(f"点位14 第{round_idx+1}轮 ({cx},{oy}) 第{changes}次变化(已存基准)")
                    if changes >= 2:
                        log.info(f"点位14 第{round_idx+1}轮 ({cx},{oy}) 第2次变化 => 准备点击")
                        # 2次变化后点击; 窗口未关=>命中, 关闭=>步长过大减半重试
                        ctx.click(cx, oy, wait_after=0.5)
                        if _pc.find_windows(exe=tasks_svc.WECHAT_APPEX, visible_only=True):
                            log.info(f"点位14 第{round_idx+1}轮 ({cx},{oy}) 点击后搜一搜未关 => 命中")
                            return cx, oy, ""
                        log.warning(f"点位14 第{round_idx+1}轮 ({cx},{oy}) 点击后搜一搜被关闭, 步长过大重试")
                        break
                # 与初始相同=恢复初始(不计); 与变化基准相同=仍在原状态(不计)
            if (cx - ox) % (step * 5) < step:
                log.info(f"点位14 第{round_idx+1}轮 进度 x={cx}/{limit_x}")
            cx += step
        else:
            log.warning("点位14 扫过上限x仍未达2次变化, 步长过大重试")
    log.warning("点位14 多轮未命中")
    return None, None


# ---------------------------------------------------------------------------
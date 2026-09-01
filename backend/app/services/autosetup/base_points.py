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

    # 3) (采集此处点击点位12, 自动设置改为:) 截图左上1/16 -> OCR找"搜索网络结果"
    sw = ctypes.windll.user32.GetSystemMetrics(0)
    sh = ctypes.windll.user32.GetSystemMetrics(1)
    for attempt in range(3):
        img = Image.open(pc.screenshot(0, 0, sw // 4, sh // 4)[0]).convert("RGB")
        for cx, cy, text, score, sbox, _bright in ctx.ocr_box(img):
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
            log.info(f"点位12 识别成功: 文本={text} box=({cx},{cy}) 颜色排序={cols}")
            return cx, cy
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

    sw = ctypes.windll.user32.GetSystemMetrics(0)
    sh = ctypes.windll.user32.GetSystemMetrics(1)
    x1, y1, x2, y2 = 0, 0, sw // 4, sh // 4      # 屏幕左上 1/16(微信左半屏的左上角)
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
        # 截图起点为 (0,0), 相对坐标即绝对坐标
        log.info(f"点位11 识别成功: 文本={text} box=({cx},{cy}) 颜色排序={cols}")
        return cx, cy
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

        u32 = _pc._u32()
        sw = u32.GetSystemMetrics(_pc.SM_CXSCREEN)
        sh = u32.GetSystemMetrics(_pc.SM_CYSCREEN)
        x2 = sw // 2
        y_top = max(80, sh * 2 // 10)          # 最上 2/10(1/10 太窄OCR不出/不稳)
        img0 = Image.open(pc.screenshot(0, 0, x2, sh)[0]).convert("RGB")
        box = None
        for _cx, cy, text, _score, sbox, _br in ctx.ocr_box(img0):
            if "搜一搜" in text and cy <= y_top:
                box = sbox
                break
        if not box:
            log.warning("点位14 未识别到'搜一搜'文本")
            return None, None

        xs = [p[0] for p in box]; ys = [p[1] for p in box]
        ox = max(xs)                       # 原点 x = box 最右
        oy = min(ys)                       # 原点 y = box 最上
        mid_x = int(sum(xs) / len(xs))
        limit_x = sw * 3 // 8              # 上限: 左半屏右半部分的中线 x
        shot_box = (ox, 0, limit_x, oy)    # 截图范围: x∈[ox,limit_x], y∈[0,oy]

        def snap():
            return np.array(Image.open(pc.screenshot(*shot_box)[0]).convert("RGB"))

        def changed(a, b):
            return (np.abs(a.astype(int) - b.astype(int)).sum(axis=2) > 15).mean()

        divide = 1 << round_idx
        step = max(1, mid_x // 10 // divide)   # 步长 = box中心x/10, 每轮减半
        log.info(f"点位14 第{round_idx+1}轮: 原点=({ox},{oy}) 步长={step} 上限x={limit_x} 截图{shot_box}")
        prev = snap()
        changes = 0
        cx = ox
        while cx < limit_x:
            _pc._u32().SetCursorPos(cx, oy)
            _time.sleep(0.5)
            cur = snap()
            if changed(cur, prev) > 0.001:
                changes += 1
                log.info(f"点位14 第{round_idx+1}轮 ({cx},{oy}) 第{changes}次变化")
                if changes >= 2:
                    # 2次变化后点击; 窗口未关=>命中, 关闭=>步长过大减半重试
                    ctx.click(cx, oy, wait_after=0.5)
                    if _pc.find_windows(exe=tasks_svc.WECHAT_APPEX, visible_only=True):
                        log.info(f"点位14 第{round_idx+1}轮 ({cx},{oy}) 点击后搜一搜未关 => 命中")
                        return cx, oy, ""
                    log.warning(f"点位14 第{round_idx+1}轮 ({cx},{oy}) 点击后搜一搜被关闭, 步长过大重试")
                    break
            prev = cur
            cx += step
        else:
            log.warning("点位14 扫过上限x仍未达2次变化, 步长过大重试")
    log.warning("点位14 多轮未命中")
    return None, None


# ---------------------------------------------------------------------------
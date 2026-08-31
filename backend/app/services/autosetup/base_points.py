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

    for round_idx in range(3):
        if not _ensure_wechat():
            return None, None
        # 搜一搜完整初始化: 点11+输入1+全选删除+点12+自动分离判断+AppEx移左半屏
        ok_sw, txt_sw = tasks_svc.search_window_init()
        if not ok_sw:
            log.warning(f"点位14 搜一搜窗口初始化失败: {txt_sw}")
            return None, None

        # 截左半屏 OCR 找"搜一搜"(窄条1/10 OCR不稳, 用全左半屏图+限定y在最上1/10)
        u32 = _pc._u32()
        sw = u32.GetSystemMetrics(_pc.SM_CXSCREEN)
        sh = u32.GetSystemMetrics(_pc.SM_CYSCREEN)
        x2 = sw // 2
        y_top = max(80, sh * 2 // 10)          # 最上 2/10(1/10 太窄OCR不出/不稳)
        img0 = Image.open(pc.screenshot(0, 0, x2, sh)[0]).convert("RGB")
        hit = None
        for cx, cy, text, score, sbox, _br in ctx.ocr_box(img0):
            if "搜一搜" in text and cy <= y_top:
                hit = (int(cx), int(cy))
                break
        if not hit:
            log.warning("点位14 未识别到最上1/10的'搜一搜'")
            return None, None
        sx, sy = hit[0], hit[1]

        # 从左半屏右边的中线(sw*3//8)往左点击; 步长=(sw*3//8 - sx)/20 / 本轮减半
        start_x = sw * 3 // 8
        divide = 1 << round_idx
        step = max(1, int((start_x - sx) / 20 / divide))
        log.info(f"点位14 第{round_idx+1}轮: y={sy} 起点={start_x} 搜一搜x={sx} 步长={step}")
        i = 0
        while True:
            cx = start_x - i * step
            if cx <= sx:
                break
            before = np.array(Image.open(pc.screenshot(0, 0, x2, sh)[0]).convert("RGB"))
            ctx.click(cx, sy, wait_after=0.7)
            after = np.array(Image.open(pc.screenshot(0, 0, x2, sh)[0]).convert("RGB"))
            # 搜一搜窗口被关闭 => 步长太大过了查询按钮, 整轮重来
            if not _pc.find_windows(exe=tasks_svc.WECHAT_APPEX, visible_only=True):
                log.warning(f"点位14 第{round_idx+1}轮 ({cx},{sy}) 搜一搜被关闭, 步长过大重试")
                break
            # 只要有变化即成功(用户实测: 一点变化就命中), 仅排除纯噪声(>0.001)
            changed = (np.abs(after.astype(int) - before.astype(int)).sum(axis=2) > 15).mean()
            if changed > 0.001:
                log.info(f"点位14 第{round_idx+1}轮 ({cx},{sy}) 截图变化率={changed:.4f} => 命中查询按钮")
                return cx, sy, ""
            i += 1
    log.warning("点位14 多轮未命中")
    return None, None


# ---------------------------------------------------------------------------
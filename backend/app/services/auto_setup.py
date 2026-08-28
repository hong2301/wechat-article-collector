# -*- coding: utf-8 -*-
"""自动识别流程(auto_setup): 人工预设流程 + OCR + AI 视觉识别 -> 自动设置点位坐标/滚动距离

设计: 每个点位/每条滚动配置 匹配一个流程函数(代码模板式)
  POINT_FLOWS[点位名称] = fn(ctx) -> (x, y)      识别成功后由路由写回 points 表
  SCROLL_FLOWS[滚动名称] = fn(ctx) -> distance    识别成功后由路由写回 scrolls 表

流程函数可用的能力(通过 FlowContext):
  ctx.click(x, y)         鼠标点击
  ctx.scroll(...)         滚动
  ctx.shot(x1,y1,x2,y2)   区域截图 -> base64
  ctx.ocr(b64)            rapidocr 本地文字识别(初筛)
  ctx.locate(b64, desc)   AI(AI视觉) 在截图中定位目标 -> (x, y) 相对截图坐标
  ctx.abs_loc(b64, box, desc) 定位并换算成屏幕绝对坐标

示例流程函数见 _flow_demo(未接入真实点位), 各点位按此模板逐个实现。
"""
import logging
import time

from ..services import computer as pc
from ..services import ocr as ocr_service
from ..database import get_conn as _get_conn

log = logging.getLogger("auto_setup")

# ---------------------------------------------------------------------------
# 流程函数注册表: {name: fn}  (前置依赖由前端 POINT_DEPS 维护)
# ---------------------------------------------------------------------------
POINT_FLOWS = {}
SCROLL_FLOWS = {}


# ---------------------------------------------------------------------------
# 流程上下文: 给流程函数的能力包装(统一封装, 函数里只写"业务步骤")
# ---------------------------------------------------------------------------
class FlowContext:
    def __init__(self, attach: bool = True):
        self.attach = attach   # 是否前置微信窗口(默认 True, 自动设置需要操作屏幕)

    def click(self, x, y, wait_after=0.6):
        """模拟点击(坐标可用既有点位值, 或流程中临时定位)"""
        pc.mouse_click(x, y, wait_after=wait_after)
        return self

    def scroll(self, x, y, pixels, direction="down"):
        pc.scroll(x, y, pixels, direction=direction)
        time.sleep(0.4)
        return self

    def shot(self, x1, y1, x2, y2):
        """区域截图 -> base64(AI 识别输入)"""
        return pc.screenshot(x1, y1, x2, y2, as_base64=True)

    def ocr(self, b64):
        """本地 OCR 初筛: 返回 [(text, x, y, w, h), ...]"""
        from ..services import ocr as _ocr
        return _ocr.ocr(b64) if _ocr.get_ocr_engine() else []

    def ocr_box(self, pil_img):
        """本地 OCR: 输入 PIL 图片, 返回 [(cx, cy, text, score, sbox, brightness), ...]"""
        return ocr_service.ocr(pil_img)

    def locate(self, shot_b64, desc, box=None):
        """豆包视觉: 在截图中定位目标 -> (x, y) 相对截图 或 (None, None)
        需要 ai_model 表已配置 key(未配置返回 None, 流程回退人工)"""
        from ..services.doubao_api import doubao_locate
        from ..database import get_conn
        conn = get_conn()
        try:
            row = conn.execute("SELECT api_key, model_id FROM ai_model LIMIT 1").fetchone()
        finally:
            conn.close()
        if not row or not (row["api_key"] or "").strip():
            log.warning("AI 未配置 key, 无法自动定位")
            return None, None
        try:
            return doubao_locate(shot_b64, desc, row["api_key"], row["model_id"] or "")
        except Exception as e:
            log.warning("AI 定位失败: %s", e)
            return None, None

    def abs_loc(self, box, desc, x1, y1, x2, y2):
        """定位并换算为屏幕绝对坐标: 截图区域左上角 + 相对坐标"""
        shot = self.shot(x1, y1, x2, y2)
        rx, ry = self.locate(shot, desc)
        if rx is None or ry is None:
            return None, None
        return x1 + int(rx), y1 + int(ry)


def flow_point(name):
    """装饰器: 注册点位流程函数(名称须与 points.name 一致)"""
    def deco(fn):
        POINT_FLOWS[name] = fn
        return fn
    return deco


def flow_scroll(name):
    def deco(fn):
        SCROLL_FLOWS[name] = fn
        return fn
    return deco


# ---------------------------------------------------------------------------
# 点位 12: 微信左上角搜索网络 (依赖点位11已设值)
# 流程: 同点位11初始化 -> 截图左上1/16 -> OCR找"搜索网络结果" -> 黑字白底校验
# ---------------------------------------------------------------------------
@flow_point("微信左上角搜索网络")
def _flow_point12_search_network(ctx):
    import ctypes
    import time as _time
    from PIL import Image, ImageGrab
    from ..services import tasks as tasks_svc

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
    for attempt in range(4):
        img = ImageGrab.grab(bbox=(0, 0, sw // 4, sh // 4)).convert("RGB")
        for cx, cy, text, score, sbox, _bright in ctx.ocr_box(img):
            if "网络结果" not in text:
                continue
            # 校验: 黑字(深色像素近似黑灰) + 白底
            crop = img.crop((min(p[0] for p in sbox), min(p[1] for p in sbox),
                             max(p[0] for p in sbox), max(p[1] for p in sbox)))
            dark = [px_ for px_ in crop.convert("RGB").getdata() if sum(px_) < 400]
            if not dark:
                continue
            r = sum(p[0] for p in dark)/len(dark); g = sum(p[1] for p in dark)/len(dark); b = sum(p[2] for p in dark)/len(dark)
            avg, spread = (r+g+b)/3, max(r,g,b)-min(r,g,b)
            if not (avg < 100 and spread < 60):
                continue
            px = list(crop.convert("L").getdata())
            if sum(1 for v in px if v > 235)/max(1, len(px)) < 0.5:
                continue
            log.info(f"点位12 识别成功: 文本={text} box=({cx},{cy}) 黑字avg={avg:.0f}")
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
# 点位 9: 微信窗口初始化不合法时窗口分离按钮
# 流程(多轮, 每轮步长减半):
#   微信初始化 -> 复刻搜一搜前段(点11+输入1+全选删除+点12) -> 检测独立窗口:
#     出现 => 99999,99999 待定
#     未出现(嵌入) => 九宫格区域OCR"搜一搜"(黑字白底)取中心y;
#       从微信主窗口最右边、y=该y 左移点击, 步长=右缘到搜一搜距离/10(每轮再减半):
#       - 点击后独立窗口出现 => 记录坐标为点位9 成功
#       - 点击后微信宽度变小 => 点到了关闭按钮(已过分离按钮, 步长过大)
#         => 本轮作废, 重新完整流程且步长减半
#----------------------------------------------------------------------------
def _p9_round(round_idx, ctx):
    import ctypes
    import time as _time
    from PIL import ImageGrab
    from ..services import tasks as tasks_svc
    from ..services import computer as _pc

    # 1) 微信窗口就位
    if not _ensure_wechat():
        return None
    # 2) 复刻搜一搜前段: 点11 -> 输入1 -> 全选删除 -> 点12
    p11 = tasks_svc._read_point(11)
    p12 = tasks_svc._read_point(12)
    if not p11 or not p12:
        return None
    ctx.click(p11[0], p11[1], wait_after=0.2)
    _pc.type_text("1"); _time.sleep(0.1); _pc.ctrl_key("A"); _time.sleep(0.1)
    _pc.key_press(_pc.VK_DELETE); _time.sleep(0.2)
    ctx.click(p12[0], p12[1], wait_after=0.8)
    # 3) 独立窗口 => 无需分离: 确认当前微信不需要窗口分离按钮, 置99999待定+说明备注
    if _pc.find_windows(exe=tasks_svc.WECHAT_APPEX, visible_only=True):
        return (99999, 99999, "当前微信搜一搜窗口独立，无需此点位")
    # 4) 嵌入模式: 先把微信主窗口移到左半屏, 再截图 OCR
    weixin = _pc.find_windows(exe=tasks_svc.WECHAT_MAIN, visible_only=True)
    if not weixin:
        return None
    u32 = _pc._u32()
    sw = u32.GetSystemMetrics(_pc.SM_CXSCREEN)
    sh = u32.GetSystemMetrics(_pc.SM_CYSCREEN)
    _pc.move_window(weixin[0][0], 0, 0, sw // 2, sh)   # 微信主窗口移到左半屏
    _time.sleep(0.8)
    x1, x2 = sw // 3, sw * 2 // 3
    y1, y2 = 0, sh // 9
    img = ImageGrab.grab(bbox=(x1, y1, x2, y2)).convert("RGB")
    hit = None
    for cx, cy, text, score, sbox, _br in ctx.ocr_box(img):
        if "搜一搜" not in text:
            continue
        crop = img.crop((min(p[0] for p in sbox), min(p[1] for p in sbox),
                         max(p[0] for p in sbox), max(p[1] for p in sbox)))
        dark = [pp for pp in crop.convert("RGB").getdata() if sum(pp) < 400]
        if not dark:
            continue
        r = sum(p[0] for p in dark)/len(dark); g = sum(p[1] for p in dark)/len(dark); b = sum(p[2] for p in dark)/len(dark)
        if not ((r+g+b)/3 < 100 and max(r,g,b)-min(r,g,b) < 60):
            continue
        pl = list(crop.convert("L").getdata())
        if sum(1 for v in pl if v > 235)/max(1, len(pl)) < 0.5:
            continue
        hit = (int(cx), int(cy))
        break
    if not hit:
        log.warning("点位9 未识别到'搜一搜'(黑字白底)")
        return None
    sx, sy = x1 + hit[0], y1 + hit[1]

    # 5) 从微信右缘左移探测; 记录点击前宽度(用于检测点到关闭按钮?
    rect = ctypes.wintypes.RECT()
    u32.GetWindowRect(weixin[0][0], ctypes.byref(rect))
    x_right = rect.right - 1
    w0 = rect.right - rect.left
    divide = 1 << round_idx              # 每轮减半: 1, 2, 4
    step = max(1, int((x_right - sx) / 10 / divide))
    log.info(f"点位9 第{round_idx+1}轮: y={sy} 右缘={x_right} 宽度={w0} 步长={step}")
    i = 0
    while True:
        cx = x_right - i * step
        if cx < sx:
            break
        ctx.click(cx, sy, wait_after=0.8)
        # 检查: 微信主窗口宽度变小 = 点中了分离按钮(唯一判据)
        rnow = ctypes.wintypes.RECT()
        u32.GetWindowRect(weixin[0][0], ctypes.byref(rnow))
        if (rnow.right - rnow.left) < w0 - 2:
            log.info(f"点位9 第{round_idx+1}轮点击({cx},{sy}) 分离成功 (宽 {w0}->{rnow.right-rnow.left})")
            return cx, sy
        i += 1
    log.warning(f"点位9 第{round_idx+1}轮未命中")
    return None


@flow_point("微信窗口初始化不合法时窗口分离按钮")
def _flow_point9_split_button(ctx):
    for round_idx in range(4):
        res = _p9_round(round_idx, ctx)
        if res is not None:
            return res
    return None, None


# ---------------------------------------------------------------------------
# 点位 11: 点击微信左上角搜索输入框
# 流程: 截图屏幕左上1/16 -> OCR找"搜索"文本 -> 校验灰字白底 -> 中心坐标即输入框位置
# ---------------------------------------------------------------------------
@flow_point("点击微信左上角搜索输入框")
def _flow_point11_search_box(ctx):
    import ctypes
    from PIL import Image, ImageGrab
    from ..services import tasks as tasks_svc

    # 微信窗口就位(左半屏): 优先采集初始化, 失败则手动摆正
    if not _ensure_wechat():
        return None, None

    sw = ctypes.windll.user32.GetSystemMetrics(0)
    sh = ctypes.windll.user32.GetSystemMetrics(1)
    x1, y1, x2, y2 = 0, 0, sw // 4, sh // 4      # 屏幕左上 1/16(微信左半屏的左上角)
    img = ImageGrab.grab(bbox=(x1, y1, x2, y2)).convert("RGB")

    items = ctx.ocr_box(img)                       # [(cx,cy,text,score,sbox,brightness)]
    for cx, cy, text, score, sbox, _bright in items:
        if "搜索" not in text:
            continue
        # 校验1: 文字主色为灰色(灰字); box 传空偏移即可(仅绕过守卫, sbox已相对截图)
        gray = ocr_service._region_grayish(sbox, box=(0, 0, 0, 0), img=img)
        if not gray:
            continue
        # 校验2: 背景为白色(框区域大多数像素 >235)
        crop = img.crop((min(p[0] for p in sbox), min(p[1] for p in sbox),
                         max(p[0] for p in sbox), max(p[1] for p in sbox)))
        px = list(crop.convert("L").getdata())
        white_ratio = sum(1 for v in px if v > 235) / max(1, len(px))
        if white_ratio < 0.5:
            continue
        # 截图起点为 (0,0), 相对坐标即绝对坐标
        log.info(f"点位11 识别成功: 文本={text} box=({cx},{cy}) gray={gray} 白底占比={white_ratio:.2f}")
        return cx, cy
    log.warning("点位11 未识别到白底灰字的'搜索'输入框")
    return None, None


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# 点位 14: 搜一搜窗口查询按钮 (依赖 11/12/9)
# 流程: 微信初始化 -> 初始化搜一搜(点11+输入1+全选删除+点12, 无独立窗则点9分离)
#   -> 截图左半屏最上1/10, OCR"搜一搜"取中心y
#   -> 从左半屏一半x(sw//4)往左点击, 步长=(sw//4-搜一搜x)/20:
#      点击后截图对比有变化=>命中查询按钮(成功);
#      搜一搜窗口被关闭=>步长过大(点到关闭), 整轮重来步长减半
# ---------------------------------------------------------------------------
@flow_point("搜一搜窗口查询按钮")
def _flow_point14_query_button(ctx):
    import ctypes
    import time as _time
    from PIL import Image, ImageGrab
    import numpy as np
    from ..services import tasks as tasks_svc
    from ..services import computer as _pc

    for round_idx in range(4):
        if not _ensure_wechat():
            return None, None
        # 搜一搜前段: 点11 -> 输入1 -> 全选删除 -> 点12
        p11 = tasks_svc._read_point(11)
        p12 = tasks_svc._read_point(12)
        if not p11 or not p12:
            return None, None
        ctx.click(p11[0], p11[1], wait_after=0.2)
        _pc.type_text("1"); _time.sleep(0.1); _pc.ctrl_key("A"); _time.sleep(0.1)
        _pc.key_press(_pc.VK_DELETE); _time.sleep(0.2)
        ctx.click(p12[0], p12[1], wait_after=0.8)
        # 无独立搜一搜窗口 -> 先移微信主窗口到左半屏, 等0.3s 再点9分离
        if not _pc.find_windows(exe=tasks_svc.WECHAT_APPEX, visible_only=True):
            p9 = tasks_svc._read_point(9)
            if not p9:
                return None, None
            u32_ = _pc._u32()
            sw_ = u32_.GetSystemMetrics(_pc.SM_CXSCREEN)
            sh_ = u32_.GetSystemMetrics(_pc.SM_CYSCREEN)
            wx = _pc.find_windows(exe=tasks_svc.WECHAT_MAIN, visible_only=True)
            if wx:
                _pc.move_window(wx[0][0], 0, 0, sw_ // 2, sh_)
                _time.sleep(0.3)
            ctx.click(p9[0], p9[1], wait_after=0.8)

        # 截左半屏 OCR 找"搜一搜"(窄条1/10 OCR不稳, 用全左半屏图+限定y在最上1/10)
        u32 = _pc._u32()
        sw = u32.GetSystemMetrics(_pc.SM_CXSCREEN)
        sh = u32.GetSystemMetrics(_pc.SM_CYSCREEN)
        x2 = sw // 2
        y_top = max(80, sh * 2 // 10)          # 最上 2/10(1/10 太窄OCR不出/不稳)
        img0 = ImageGrab.grab(bbox=(0, 0, x2, sh)).convert("RGB")
        hit = None
        for cx, cy, text, score, sbox, _br in ctx.ocr_box(img0):
            if "搜一搜" in text and cy <= y_top:
                hit = (int(cx), int(cy))
                break
        if not hit:
            log.warning("点位14 未识别到最上1/10的'搜一搜'")
            return None, None
        sx, sy = hit[0], hit[1]

        # 从左半屏一半x(sw//4)往左点击; 步长=(sw//4 - sx)/20 / 本轮减半
        start_x = sw // 4
        divide = 1 << round_idx
        step = max(1, int((start_x - sx) / 20 / divide))
        log.info(f"点位14 第{round_idx+1}轮: y={sy} 起点={start_x} 搜一搜x={sx} 步长={step}")
        i = 0
        while True:
            cx = start_x - i * step
            if cx <= sx:
                break
            before = np.array(ImageGrab.grab(bbox=(0, 0, x2, sh)).convert("RGB"))
            ctx.click(cx, sy, wait_after=0.7)
            after = np.array(ImageGrab.grab(bbox=(0, 0, x2, sh)).convert("RGB"))
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
    """15/16 共同识别: 找到文章列表矩形并写入两个点位; 返回 (rx1,ry1,rx2,ry2) 或 None"""
    import ctypes
    import time as _time
    from PIL import ImageGrab
    import numpy as np
    from ..services import tasks as tasks_svc
    from ..services import computer as _pc

    # 完整调用: 微信窗口初始化 + 搜一搜窗口初始化
    ok_wx, txt_wx = tasks_svc.init_wechat_window()
    if not ok_wx:
        log.warning(f"点位15/16 微信窗口初始化失败: {txt_wx}")
        return None
    ok_ap, txt_ap = tasks_svc.init_app_window()
    if not ok_ap:
        log.warning(f"点位15/16 采集器窗口初始化失败: {txt_ap}")
        return None

    ok_sw, txt_sw = tasks_svc.search_window_init()
    if not ok_sw:
        log.warning(f"点位15/16 搜一搜窗口初始化失败: {txt_sw}")
        return None
    u32_ = _pc._u32()
    sw_ = u32_.GetSystemMetrics(_pc.SM_CXSCREEN)
    sh_ = u32_.GetSystemMetrics(_pc.SM_CYSCREEN)

    # 搜一搜查询测试公众号
    ok_q, _txt = tasks_svc.search_query(TEST_BIZ_QUERY)
    if not ok_q:
        log.warning("点位15/16 搜一搜查询失败: " + _txt)
        return None
    _time.sleep(5.0)                        # 等加载

    # 先下滚1000 -> 截图1; 再下滚500 -> 截图2; 对比得出列表区
    _pc.scroll(sw_ // 4, sh_ // 2, 1000, direction="down", wait_after=0.8)
    img1 = np.array(ImageGrab.grab(bbox=(0, 0, sw_ // 2, sh_)).convert("RGB"))
    _pc.scroll(sw_ // 4, sh_ // 2, 500, direction="down", wait_after=0.8)
    img2 = np.array(ImageGrab.grab(bbox=(0, 0, sw_ // 2, sh_)).convert("RGB"))

    # 对比: 变化区域的外接矩形 = 文章列表区
    diff = np.abs(img2.astype(int) - img1.astype(int)).sum(axis=2)
    mask = diff > 40
    ys, xs = np.where(mask)
    if len(xs) < 50:
        log.warning(f"点位15/16 变化区域过小({len(xs)}px), 文章列表未加载?")
        return None
    rx1, ry1, rx2, ry2 = int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())
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
# 点位 18: 文章右上角3点 (依赖前面全部 11/12/9/14/15/16)
# 流程: 与点位14相同(微信就位->点11/12/9分离)但到OCR搜一搜那步不用,
#   以点位14为原点往右偏移20px起, 向右步长点击(步长=14到屏幕中线/15):
#     截图有变化 -> 命中记录; 无变化或窗口变大(点了全屏键, 步长跳过) ->
#     搜一搜窗口恢复左半屏, 再往回(左)点击, 步长=原1/5
# ---------------------------------------------------------------------------
@flow_point("文章右上角3点")
def _flow_point18_three_dots(ctx):
    import ctypes
    import time as _time
    from PIL import ImageGrab
    import numpy as np
    from ..services import tasks as tasks_svc
    from ..services import computer as _pc

    # 完整调用: 微信窗口初始化 + 搜一搜窗口初始化
    ok_wx, txt_wx = tasks_svc.init_wechat_window()
    if not ok_wx:
        log.warning(f"点位18 微信窗口初始化失败: {txt_wx}")
        return None, None
    ok_ap, txt_ap = tasks_svc.init_app_window()
    if not ok_ap:
        log.warning(f"点位18 采集器窗口初始化失败: {txt_ap}")
        return None, None

    ok_sw, txt_sw = tasks_svc.search_window_init()
    if not ok_sw:
        log.warning(f"点位18 搜一搜窗口初始化失败: {txt_sw}")
        return None, None
    p14 = tasks_svc._read_point(14)
    if not p14:
        return None, None
    u32_ = _pc._u32()
    sw_ = u32_.GetSystemMetrics(_pc.SM_CXSCREEN)
    sh_ = u32_.GetSystemMetrics(_pc.SM_CYSCREEN)

    base_y = p14[1]
    x0 = p14[0] + 20                      # 以14为原点右偏20px
    mid_x = sw_ // 2                       # 屏幕中线(左半屏右缘)
    half_w = sw_ // 2
    raw_step = max(1, int((mid_x - p14[0]) / 15))

    def click_and_check(cx, step_now):
        # 点击前/后截图对比; 返回 (变化率, 搜一搜窗口是否仍可见)
        before = np.array(ImageGrab.grab(bbox=(0, 0, half_w, sh_)).convert("RGB"))
        ctx.click(cx, base_y, wait_after=0.7)
        appex_now = _pc.find_windows(exe=tasks_svc.WECHAT_APPEX, visible_only=True)
        hidden = not appex_now       # 3点右边是最小化键: 点过头(步长过大)窗口会被最小化=>不可见
        after = np.array(ImageGrab.grab(bbox=(0, 0, half_w, sh_)).convert("RGB"))
        changed = (np.abs(after.astype(int) - before.astype(int)).sum(axis=2) > 15).mean()
        return changed, hidden

    # 右向探测: 从 x0 向右, 步长 raw_step
    i = 0
    while True:
        cx = x0 + i * raw_step
        if cx > mid_x:
            break
        changed, hidden = click_and_check(cx, raw_step)
        if changed > 0.001:
            log.info(f"点位18 右向({cx},{base_y}) 变化率={changed:.4f} => 命中")
            return cx, base_y
        if hidden:
            # 窗口被最小化(点到最小化键, 步长过大跳过3点) -> 恢复窗口+左半屏, 往回(左)点击 步长1/5
            log.warning(f"点位18 右向({cx},{base_y}) 搜一搜窗口不可见, 恢复后往左(步长{raw_step//5})")
            appex_all = _pc.find_windows(exe=tasks_svc.WECHAT_APPEX, visible_only=False)
            if appex_all:
                _pc.show_window(appex_all[0][0])
                _pc.move_window(appex_all[0][0], 0, 0, half_w, sh_)
                _time.sleep(0.5)
            small = max(1, raw_step // 5)
            j = 0
            while True:
                cx2 = mid_x - j * small
                if cx2 <= p14[0]:
                    break
                changed2, _hidden2 = click_and_check(cx2, small)
                if changed2 > 0.001:
                    log.info(f"点位18 左回({cx2},{base_y}) 变化率={changed2:.4f} => 命中")
                    return cx2, base_y
                j += 1
            break
        i += 1
    log.warning("点位18 探测未命中")
    return None, None
def run_point_flow(name: str, attach: bool = True):
    """执行点位自动设置流程 -> (x, y, remark, err); 流程函数可返回 (x,y) 或 (x,y,remark)"""
    fn = POINT_FLOWS.get(name)
    if not fn:
        return None, None, "", f"未找到点位流程: {name}"
    if attach:
        _attach_wechat()
    try:
        res = fn(FlowContext())
        if res is None:
            return None, None, "", f"识别失败: {name}"
        if len(res) >= 3:
            x, y, remark = res[0], res[1], res[2] or ""
        else:
            x, y, remark = res[0], res[1], ""
        if x is None or y is None:
            return None, None, "", f"识别失败(AI 定位不到目标): {name}"
        return x, y, remark, ""
    except Exception as e:
        return None, None, "", f"流程异常: {e}"


def run_scroll_flow(name: str, attach: bool = True):
    fn = SCROLL_FLOWS.get(name)
    if not fn:
        return None, None, f"未找到滚动流程: {name}"
    if attach:
        _attach_wechat()
    try:
        dist = fn(FlowContext())
        if dist is None:
            return None, None, f"识别失败: {name}"
        return dist, "", None
    except Exception as e:
        return None, None, f"流程异常: {e}"


def _attach_wechat():
    """前置微信窗口到前台(自动设置需要操作屏幕)"""
    from ..services import computer as _pc
    from ..services import tasks as _tasks
    hwnd = _pc.find_windows(exe=_tasks.WECHAT_MAIN, visible_only=True)
    if not hwnd:
        log.warning("未找到微信窗口, 请先打开微信")
        return
    try:
        _pc.show_window(hwnd)
        time.sleep(0.6)
    except Exception:
        pass


def _ensure_wechat():
    """微信窗口就位(左半屏标准布局): 优先走采集的 init_wechat_window,
    失败(窗口位置/宽度不合法)则手动移动摆正, 保证后续截图/点击坐标可靠"""
    from ..services import tasks as _tasks
    from ..services import computer as _pc
    ok, _txt = _tasks.init_wechat_window()
    if ok:
        return True
    import ctypes
    hwnd = _pc.find_windows(exe=_tasks.WECHAT_MAIN, visible_only=True)
    if not hwnd:
        return False
    u32 = _pc._u32()
    sw = u32.GetSystemMetrics(_pc.SM_CXSCREEN)
    sh = u32.GetSystemMetrics(_pc.SM_CYSCREEN)
    try:
        _pc.show_window(hwnd[0][0])
        _pc.move_window(hwnd[0][0], 0, 0, sw // 2, sh)
        time.sleep(0.8)
        return True
    except Exception:
        return False

# ---------------------------------------------------------------------------
# 流程: 微信就位->搜一搜初始化(点11/12/9)->搜一搜查询单篇文章链接
#   -> 等5s -> 截左半屏最下1/10 -> OCR找"关注"(box取其高) -> 中心Y+高×1.2 定数据栏高
#   -> 宽度=左半屏x中点(sw/4)到屏幕中线(sw/2) -> 左上=30, 右下=31 双写
# ---------------------------------------------------------------------------
ARTICLE_LINK_DEMO = "https://mp.weixin.qq.com/s/X7fAdvvZ-Gq_2SW19OKfVw"


def _flow_article_bar_find(ctx):
    import ctypes
    import time as _time
    from PIL import ImageGrab
    from ..services import tasks as tasks_svc
    from ..services import computer as _pc

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
    u32_ = _pc._u32()
    sw_ = u32_.GetSystemMetrics(_pc.SM_CXSCREEN)
    sh_ = u32_.GetSystemMetrics(_pc.SM_CYSCREEN)

    ok_q, _txt = tasks_svc.search_query(ARTICLE_LINK_DEMO)
    if not ok_q:
        return None
    _time.sleep(5.0)

    # 截左半屏最下2/10, OCR找"关注"box(1/10窄条OCR不稳; 关注按钮在最底部)
    y0_1, y1_1 = sh_ * 8 // 10, sh_
    shot = ImageGrab.grab(bbox=(0, y0_1, sw_ // 2, y1_1)).convert("RGB")
    hit = None
    for cx, cy, text, score, sbox, _br in ctx.ocr_box(shot):
        if "关注" in text:
            ys = [p[1] for p in sbox]
            h = max(ys) - min(ys)
            hit = (int(cx), y0_1 + int(cy), h)
            break
    if not hit:
        return None
    cx_abs, cy_abs, box_h = hit

    # 高度上下扩大120%
    H = box_h * 1.2
    y_top = int(cy_abs - H / 2)
    y_bot = int(cy_abs + H / 2)
    x_left = sw_ // 4        # 左半屏 x 中点
    x_right = sw_ // 2       # 屏幕中线
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
# 点位 21/22: 阅读数左/右下 (同一自动设置, 依赖点位19已设值, 纯计算不操作窗口)
# ---------------------------------------------------------------------------
def _calc_reads_box(self_name):
    def fn(ctx):
        import ctypes
        from ..services import computer as _pc2
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
    """纯计算: 28/29 = 左半屏右上部分, 无需任何窗口操作"""
    from ..services import computer as _pcc
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


# ---------------------------------------------------------------------------
# 点位 27: 点击复制链接 (依赖28/29区域)
# 流程: 微信就位 -> 完整调用init+search_window_init -> 搜一搜查询文章链接
#   -> 等1s -> 点18(3点弹菜单) -> 等0.5s -> 截[28,29]区域 -> OCR找"复制"文字按钮
#   -> 按钮中心坐标 = 点位27
# ---------------------------------------------------------------------------
ARTICLE_LINK_DEMO_27 = ARTICLE_LINK_DEMO


@flow_point("点击复制链接")
def _flow_point27_copy(ctx):
    import time as _time
    from PIL import Image, ImageGrab
    from ..services import tasks as tasks_svc
    from ..services import computer as _pc

    ok_wx, txt_wx = tasks_svc.init_wechat_window()
    if not ok_wx:
        return None, None
    ok_ap, txt_ap = tasks_svc.init_app_window()
    if not ok_ap:
        log.warning(f"点位27 采集器窗口初始化失败: {txt_ap}")
        return None, None

    ok_sw, txt_sw = tasks_svc.search_window_init()
    if not ok_sw:
        return None, None
    ok_q, txt_q = tasks_svc.search_query(ARTICLE_LINK_DEMO_27)
    if not ok_q:
        log.warning(f"点位27 查询文章链接失败: {txt_q}")
        return None, None
    _time.sleep(1.0)

    p18 = tasks_svc._read_point(18)
    p28 = tasks_svc._read_point(28)
    p29 = tasks_svc._read_point(29)
    if not p18 or not p28 or not p29:
        log.warning(f"点位27 缺前置(18{bool(p18)} 28{bool(p28)} 29{bool(p29)})")
        return None, None
    ctx.click(p18[0], p18[1], wait_after=0.5)      # 弹菜单

    # 截[28,29]区域 OCR
    img = ImageGrab.grab(bbox=(p28[0], p28[1], p29[0], p29[1])).convert("RGB")
    hit = None
    for cx, cy, text, score, sbox, _br in ctx.ocr_box(img):
        if "复制" in text:
            hit = (int(cx), int(cy))
            break
    if not hit:
        log.warning("点位27 未识别到'复制'字样")
        return None, None
    ax, ay = p28[0] + hit[0], p28[1] + hit[1]
    log.info(f"点位27 识别复制按钮: ({ax},{ay})")
    return ax, ay


# ---------------------------------------------------------------------------
# 点位 34: 评论按钮
# 流程: 微信+搜一搜完整调用 -> 搜一搜查询文章链接 -> 等1s
#   -> 从屏幕中线往左点击, y=30/31 y中点, 步长=(屏幕中线-31.x)/5(每轮减半):
#     点击后截[30,31]区域: 有变化且有红色=>步长太大点过(重来减半);
#     有变化无红色=>命中评论按钮, 记录
# ---------------------------------------------------------------------------
def _diff_red(img1, img2):
    """[30,31]区域变化率 + 变化区域是否含红色"""
    import numpy as np
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
    import time as _time
    from PIL import Image, ImageGrab
    import numpy as np
    from ..services import tasks as tasks_svc
    from ..services import computer as _pc

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
    u32_ = _pc._u32()
    sw_ = u32_.GetSystemMetrics(_pc.SM_CXSCREEN)
    sh_ = u32_.GetSystemMetrics(_pc.SM_CYSCREEN)
    # [30,31]页面稳定检测(50次/连续30相同)后再截图基准
    ok_st, info_st = tasks_svc.wait_page_stable(p30[0], p30[1], p31[0], p31[1],
                                                same_need=30, timeout=50, interval=0.1)
    if not ok_st:
        log.warning(f"点位34 [30,31]未稳定: {info_st}")
    else:
        log.info(f"点位34 [30,31]稳定: {info_st}")

    sy = (p30[1] + p31[1]) // 2
    mid_x = sw_ // 2
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

    for round_i in range(6):
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
# 点位 35/36: 评论区左上/右下 (同一流程, 一起设置)
# 流程: 采集器窗口初始化->微信窗口初始化->搜一搜窗口初始化->查询文章链接
#   -> 检测[30,31]稳定 -> 点34(评论按钮)打开评论区
#   -> 左半屏右半屏稳定检测 -> 截图 -> 移区域中点向下滚500 -> 截图
#   -> 对比变化区域外接矩形 = 评论区: 35=左上, 36=右下 双写
# ---------------------------------------------------------------------------
def _flow_comment_area_find(ctx):
    import ctypes
    import time as _time
    from PIL import Image, ImageGrab
    import numpy as np
    from ..services import tasks as tasks_svc
    from ..services import computer as _pc

    ok_ap, txt_ap = tasks_svc.init_app_window()
    if not ok_ap:
        log.warning(f"点位35/36 采集器窗口初始化失败: {txt_ap}")
        return None
    ok_wx, txt_wx = tasks_svc.init_wechat_window()
    if not ok_wx:
        log.warning(f"点位35/36 微信窗口初始化失败: {txt_wx}")
        return None
    ok_sw, txt_sw = tasks_svc.search_window_init()
    if not ok_sw:
        log.warning(f"点位35/36 搜一搜窗口初始化失败: {txt_sw}")
        return None
    ok_q, txt_q = tasks_svc.search_query(ARTICLE_LINK_DEMO)
    if not ok_q:
        log.warning(f"点位35/36 查询文章链接失败: {txt_q}")
        return None

    # 检测[30,31]稳定
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
    # 点34评论按钮打开评论区
    p34 = tasks_svc._read_point(34)
    if not p34:
        log.warning("点位35/36 缺34")
        return None
    ctx.click(p34[0], p34[1], wait_after=1.0)

    # 左半屏右半屏区域: x∈[sw/4, sw/2], y∈[0, sh]
    u32_ = _pc._u32()
    sw_ = u32_.GetSystemMetrics(_pc.SM_CXSCREEN)
    sh_ = u32_.GetSystemMetrics(_pc.SM_CYSCREEN)
    rx1, ry1, rx2, ry2 = sw_ // 4, 0, sw_ // 2, sh_
    ok_st2, info_st2 = tasks_svc.wait_page_stable(rx1, ry1, rx2, ry2,
                                                  same_need=30, timeout=50, interval=0.1)
    if not ok_st2:
        log.warning(f"点位35/36 评论区区域未稳定: {info_st2}")
    else:
        log.info(f"点位35/36 评论区区域稳定: {info_st2}")
    _pc._u32().ShowCursor(False)
    img1 = np.array(ImageGrab.grab(bbox=(rx1, ry1, rx2, ry2)).convert("RGB"))
    _pc._u32().ShowCursor(True)
    # 移动到区域中点向下滚500
    _pc.scroll((rx1 + rx2) // 2, (ry1 + ry2) // 2, 500, direction="down", wait_after=1.0)
    _pc._u32().ShowCursor(False)
    img2 = np.array(ImageGrab.grab(bbox=(rx1, ry1, rx2, ry2)).convert("RGB"))
    _pc._u32().ShowCursor(True)

    d = np.abs(img2.astype(int) - img1.astype(int)).sum(axis=2)
    mask = d > 40
    ys, xs = np.where(mask)
    if len(xs) < 50:
        log.warning(f"点位35/36 变化区域过小({len(xs)}px)")
        return None
    gx1, gy1, gx2, gy2 = int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())
    ax1, ay1 = rx1 + gx1, ry1 + gy1
    ax2, ay2 = rx1 + gx2, ry1 + gy2
    log.info(f"点位35/36 评论区矩形: ({ax1},{ay1})-({ax2},{ay2})")
    return ax1, ay1, ax2, ay2


def _comment_area_entry(self_name):
    def fn(ctx):
        res = _flow_comment_area_find(ctx)
        if res is None:
            return None, None
        ax1, ay1, ax2, ay2 = res
        conn = _get_conn()
        try:
            conn.execute("UPDATE points SET x=?, y=? WHERE name=?", (ax1, ay1, "评论区左上"))
            conn.execute("UPDATE points SET x=?, y=? WHERE name=?", (ax2, ay2, "评论区右下"))
            conn.commit()
        finally:
            conn.close()
        if self_name == "评论区左上":
            return ax1, ay1
        return ax2, ay2
    return fn


POINT_FLOWS["评论区左上"] = _comment_area_entry("评论区左上")
POINT_FLOWS["评论区右下"] = _comment_area_entry("评论区右下")


# ---------------------------------------------------------------------------
# 点位 39: 搜一搜窗口第一个标签页关闭按钮
# 流程: 采集器/微信/搜一搜初始化 -> 从点位14(搜一搜按钮)位置往左点击
#   步长=(14.x-屏幕左0)/15(每轮减半): 每点一下检测搜一搜窗口是否不存在
#   (存在=未点到关闭; 不存在=点到关闭按钮=>记录当前坐标)
#   若扫到屏幕左边仍存在 => 步长太大跳过了, 重新全流程步长减半
# ---------------------------------------------------------------------------
@flow_point("搜一搜窗口第一个标签页关闭按钮")
def _flow_point39_close_tab(ctx):
    import time as _time
    from ..services import tasks as tasks_svc
    from ..services import computer as _pc

    for round_i in range(6):
        ok_ap, txt_ap = tasks_svc.init_app_window()
        if not ok_ap:
            log.warning(f"点位39 采集器窗口初始化失败: {txt_ap}")
            return None, None
        ok_wx, txt_wx = tasks_svc.init_wechat_window()
        if not ok_wx:
            log.warning(f"点位39 微信窗口初始化失败: {txt_wx}")
            return None, None
        ok_sw, txt_sw = tasks_svc.search_window_init()
        if not ok_sw:
            log.warning(f"点位39 搜一搜窗口初始化失败: {txt_sw}")
            return None, None

        p14 = tasks_svc._read_point(14)
        if not p14:
            log.warning("点位39 缺14")
            return None, None
        raw_step = max(1, p14[0] // 15)          # 步长=(14.x-0)/15(不变)
        step = max(1, raw_step // (1 << round_i)) # 每轮减半
        log.info(f"点位39 第{round_i+1}轮: 起点x=0 步长={step}")
        x = 0
        while True:
            # 超过了搜一搜按钮(14.x)窗口仍存在 => 步长过大跳过了, 重来减半
            if x > p14[0]:
                log.warning(f"点位39 第{round_i+1}轮经过14.x仍存在, 步长过大重来")
                break
            ctx.click(x, p14[1], wait_after=0.8)
            if not _pc.find_windows(exe=tasks_svc.WECHAT_APPEX, visible_only=True):
                log.info(f"点位39 命中关闭按钮: ({x},{p14[1]})")
                return x, p14[1]
            x += step
    log.warning("点位39 多轮未命中")
    return None, None


# ---------------------------------------------------------------------------
# 一键设置: 输入锁定(同采集: 拦截人工键鼠+提示, ESC停止) + 按依赖序执行全部点位
# ---------------------------------------------------------------------------
_input_lock = None
_stop_requested = [False]
_last_block_notice = [0.0]


def _notice_block():
    """拦截人工输入提示(限流3s)"""
    import time as _t
    now = _t.monotonic()
    if now - _last_block_notice[0] < 3.0:
        return
    _last_block_notice[0] = now
    try:
        from ..services import tasks as tasks_svc
        tasks_svc.tasks_echo("[warn] 自动设置期间禁用鼠标和键盘，请勿操作! 按 ESC 可停止")
    except Exception:
        pass


def _on_esc():
    _stop_requested[0] = True
    try:
        from ..services import tasks as tasks_svc
        tasks_svc.tasks_echo("[warn] 已请求停止: 完成当前点位后停止")
    except Exception:
        pass


_lock_notices = []      # 拦截提示队列(lock 产生, run-all 流消费)


def _notice_block_push():
    """拦截提示 -> 写入队列(供一键设置流读取)"""
    import time as _t
    now = _t.monotonic()
    if now - _last_block_notice[0] < 3.0:
        return
    _last_block_notice[0] = now
    _lock_notices.append("[warn] 自动设置期间禁用鼠标和键盘，请勿操作! 按 ESC 可停止")


def locked():
    """一键设置输入锁是否开着"""
    return _input_lock is not None and _input_lock._started


def lock():
    """前端点击一键设置: 开启输入锁定(人工键鼠拦截+提示, ESC设置停止标记)
    互斥: 采集进行中则拒绝开启"""
    global _input_lock
    try:
        from ..routers import collect as collect_mod
        if collect_mod._task_running_count() > 0:
            return False
    except Exception:
        pass
    from ..services.inputlock import InputLock
    if _input_lock is None:
        _input_lock = InputLock()
        _input_lock.on_esc = _on_esc
        _input_lock.on_block = _notice_block_push
    _stop_requested[0] = False
    if not _input_lock._started:
        return _input_lock.start()
    return True


def unlock():
    """任务结束: 停止输入锁定 + 清标记 + 清提示队列"""
    global _input_lock
    _stop_requested[0] = False
    _lock_notices.clear()
    if _input_lock is not None:
        _input_lock.stop()
        _input_lock = None
    return True


def drain_lock_notices():
    """取走锁产生的提示消息(供 run-all 流逐条发出)"""
    out = list(_lock_notices)
    _lock_notices.clear()
    return out


def locking_enter():
    """启动输入锁定(同采集); 已是第一次则再次 start 幂等"""
    global _input_lock
    from ..services.inputlock import InputLock
    if _input_lock is None:
        _input_lock = InputLock()
        _input_lock.on_esc = _on_esc
        _input_lock.on_block = _notice_block
    _stop_requested[0] = False
    if not _input_lock._started:
        return _input_lock.start()
    return True


def locking_exit():
    """结束输入锁定 + 清停止标记"""
    global _input_lock
    _stop_requested[0] = False
    if _input_lock is not None:
        _input_lock.stop()
        _input_lock = None


def stop_requested():
    return _stop_requested[0]


POINT_ORDER = [
    "点击微信左上角搜索输入框", "微信左上角搜索网络",
    "微信窗口初始化不合法时窗口分离按钮", "搜一搜窗口查询按钮",
    "文章列表左上角", "文章列表右下角", "文章右上角3点",
    "点击复制链接", "复制链接左上", "复制链接右下",
    "4指标区域左上", "4指标区域右下", "阅读数左上", "阅读数右下",
    "评论按钮", "评论区左上", "评论区右下",
    "搜一搜窗口第一个标签页关闭按钮",
]


def run_all_points_stream():
    """流式一键设置: 逐点位 yield 事件(step/progress/ok/fail/warn/done), 前端边收边渲染
    关键: 必须边执行边 yield(真生成器), 路由逐条转发; 攒到队列尾部一次性返回会导致前端收不到实时事件"""
    yield "[step] 一键设置开始: 按依赖顺序执行全部点位"

    ok_n = fail_n = done = 0
    total = len(POINT_ORDER)
    stopped = False
    try:
        for name in POINT_ORDER:
            # 锁(前端开的)产生的拦截提示实时转发
            for nmsg in drain_lock_notices():
                yield nmsg
            if stop_requested():
                yield "[warn] 已请求停止"
                stopped = True
                break
            yield f"[step] ⏳ 开始设置: {name}"
            try:
                x, y, _rem, errtxt = run_point_flow(name, attach=not _is_pure_calc(name))
            except Exception as e:
                x = None; errtxt = f"异常: {e}"
            done += 1
            # 进度优先: 每个点位完成立即 yield [progress] done/total
            yield f"[progress] {done}/{total}"
            if x is not None:
                ok_n += 1
                yield f"[ok] ✓ {name} = ({x},{y})"
            else:
                fail_n += 1
                yield f"[fail] ✗ {name}: {errtxt}"
    finally:
        unlock()   # 兜底: 无论前端是否正常 unlock, run-all 结束即释放(幂等)
    for nmsg in drain_lock_notices():
        yield nmsg
    yield f"[done] 一键设置完成: 成功 {ok_n} / 失败 {fail_n}" + (" (已停止)" if stopped else "")


def _is_pure_calc(name):
    """纯计算点位(28/29等)不 attach 微信窗口"""
    return name in ("复制链接左上", "复制链接右下")

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
    # 3) 独立窗口 => 无需分离
    if _pc.find_windows(exe=tasks_svc.WECHAT_APPEX, visible_only=True):
        return (99999, 99999, "待定: 当前微信已独立搜一搜窗口, 无需窗口分离")
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
        # 检查1: 独立窗口出现 => 成功
        if _pc.find_windows(exe=tasks_svc.WECHAT_APPEX, visible_only=True):
            log.info(f"点位9 第{round_idx+1}轮点击({cx},{sy}) 分离成功")
            return (cx, sy, f"自动识别(第{round_idx+1}轮)")
        # 检查2: 微信宽度变小 => 点到关闭按钮, 已过分离按钮 -> 整轮重来(步长减半)
        rnow = ctypes.wintypes.RECT()
        u32.GetWindowRect(weixin[0][0], ctypes.byref(rnow))
        if rnow.right - rnow.left < w0 - 2:
            log.warning(f"点位9 第{round_idx+1}轮 ({cx},{sy}) 触发宽度变小({w0}->{rnow.right-rnow.left}) => 点到关闭按钮, 重试减半步长")
            return None
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
# 示例流程(结构示范): 搜一搜窗口查询按钮
# 真实实现时: 按微信界面实际布局调用现有点位(搜索框/搜索网络结果) + 截图 + AI 定位
# ---------------------------------------------------------------------------
@flow_point("搜一搜窗口查询按钮")
def _flow_search_button(ctx):
    """点击微信左上搜索框 -> 回车展开搜一搜 -> 截图顶栏 -> AI 定位查询按钮"""
    ctx.click(141, 69, wait_after=1.2)          # 点位11: 微信左上角搜索输入框
    # 此处可按需输入搜索词扩展示例: ctx.type_text("一个公众号")
    # 截图搜一搜窗口顶部栏(暂用示例区域, 实际以窗口布局为准)
    box = (400, 20, 480, 60)
    shot = ctx.shot(*box)
    rx, ry = ctx.locate(shot, "搜一搜窗口中的『查询/搜索』按钮")
    if rx is None:
        return None, None
    return box[0] + int(rx), box[1] + int(ry)


# ---------------------------------------------------------------------------
# 执行入口: 按名称执行流程(路由调用)
# ---------------------------------------------------------------------------
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
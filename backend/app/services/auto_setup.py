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


# ---------------------------------------------------------------------------
# 流程函数注册表: {name: {"fn": fn, "depends": [依赖点位名称]}}
# ---------------------------------------------------------------------------
POINT_FLOWS = {}
SCROLL_FLOWS = {}


def flow_point(name, depends=None):
    """装饰器: 注册点位流程函数(名称须与 points.name 一致); depends=前置点位名列表"""
    def deco(fn):
        POINT_FLOWS[name] = {"fn": fn, "depends": depends or []}
        return fn
    return deco


def flow_scroll(name, depends=None):
    def deco(fn):
        SCROLL_FLOWS[name] = {"fn": fn, "depends": depends or []}
        return fn
    return deco


def missing_point_deps(name: str):
    """返回缺失的前置点位名称列表(前置点位无值时自动设置不可用)"""
    meta = POINT_FLOWS.get(name)
    if not meta or not meta["depends"]:
        return []
    from ..database import get_conn
    conn = get_conn()
    try:
        missing = []
        for d in meta["depends"]:
            row = conn.execute("SELECT x, y FROM points WHERE name=?", (d,)).fetchone()
            if not row or not str(row["x"] or "").strip() or not str(row["y"] or "").strip():
                missing.append(d)
        return missing
    finally:
        conn.close()


def all_point_deps():
    """全部已注册点位流程的依赖状态: {点位名: [缺失前置名,...]}"""
    return {name: missing_point_deps(name) for name in POINT_FLOWS}


# ---------------------------------------------------------------------------
# 点位 12: 微信左上角搜索网络 (依赖点位11已设值)
# 流程: 同点位11初始化 -> 截图左上1/16 -> OCR找"搜索网络结果" -> 黑字白底校验
# ---------------------------------------------------------------------------
@flow_point("微信左上角搜索网络", depends=["点击微信左上角搜索输入框"])
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
    """执行点位自动设置流程 -> (x, y) 或 (None, None)"""
    meta = POINT_FLOWS.get(name)
    if not meta:
        return None, None, f"未找到点位流程: {name}"
    if attach:
        _attach_wechat()
    try:
        x, y = meta["fn"](FlowContext())
        if x is None or y is None:
            return None, None, f"识别失败(AI 定位不到目标): {name}"
        return x, y, ""
    except Exception as e:
        return None, None, f"流程异常: {e}"


def run_scroll_flow(name: str, attach: bool = True):
    meta = SCROLL_FLOWS.get(name)
    if not meta:
        return None, None, f"未找到滚动流程: {name}"
    if attach:
        _attach_wechat()
    try:
        dist = meta["fn"](FlowContext())
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
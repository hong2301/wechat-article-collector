# -*- coding: utf-8 -*-
"""自动识别流程(auto_setup): 人工预设流程 + OCR + AI 视觉识别 -> 自动设置点位坐标/滚动距离

设计: 每个点位/每条滚动配置 匹配一个流程函数(代码模板式)
  POINT_FLOWS[点位名称] = fn(ctx) -> (x, y)      识别成功后由路由写回 points 表

流程函数可用的能力(通过 FlowContext):
  ctx.click(x, y)         鼠标点击
  ctx.scroll(...)         滚动
  ctx.shot(x1,y1,x2,y2)   区域截图 -> base64
  ctx.ocr(b64)            rapidocr 本地文字识别(初筛)
  ctx.locate(b64, desc)   AI(AI视觉) 在截图中定位目标 -> (x, y) 相对截图坐标
  ctx.abs_loc(b64, box, desc) 定位并换算成屏幕绝对坐标

示例流程函数见 _flow_demo(未接入真实点位), 各点位按此模板逐个实现。
"""
# ---------- imports ----------
from PIL import Image, ImageGrab
import ctypes
import numpy as np
import threading
import time
import logging
import time as _t
import time as _time

from ...core import computer as pc
from ...core import ocr as ocr_service
from ...database import get_conn as _get_conn

log = logging.getLogger("auto_setup")

# ---------------------------------------------------------------------------
# 流程函数注册表: {name: fn}  (前置依赖由前端 POINT_DEPS 维护)
# ---------------------------------------------------------------------------
POINT_FLOWS = {}


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
        from ...core import ocr as _ocr
        return _ocr.ocr(b64) if _ocr.get_ocr_engine() else []

    def ocr_box(self, pil_img):
        """本地 OCR: 输入 PIL 图片, 返回 [(cx, cy, text, score, sbox, brightness), ...]"""
        return ocr_service.ocr(pil_img)

    def locate(self, shot_b64, desc, box=None):
        """豆包视觉: 在截图中定位目标 -> (x, y) 相对截图 或 (None, None)
        需要 ai_model 表已配置 key(未配置返回 None, 流程回退人工)"""
        from ...services.doubao_api import doubao_locate
        from ...database import get_conn
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


# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
@flow_point("文章右上角3点")
def _flow_point18_three_dots(ctx):
    from ...services import tasks as tasks_svc
    from ...core import computer as _pc

    def attempt():
        """一次完整探测(初始化窗口+几何+横向扫描) -> (x,y) 命中; None 需完全重来"""
        # 完整调用: 微信窗口初始化 + 采集器 + 搜一搜窗口初始化
        ok_wx, txt_wx = tasks_svc.init_wechat_window()
        if not ok_wx:
            log.warning(f"点位18 微信窗口初始化失败: {txt_wx}")
            return None
        ok_ap, txt_ap = tasks_svc.init_app_window()
        if not ok_ap:
            log.warning(f"点位18 采集器窗口初始化失败: {txt_ap}")
            return None
        ok_sw, txt_sw = tasks_svc.search_window_init()
        if not ok_sw:
            log.warning(f"点位18 搜一搜窗口初始化失败: {txt_sw}")
            return None
        p14 = tasks_svc._read_point(14)          # 搜一搜按钮(查询)
        if not p14:
            log.warning("点位18 无点位14, 需完全重来")
            return None
        appex = _pc.find_windows(exe=tasks_svc.WECHAT_APPEX, visible_only=True)
        if not appex:
            log.warning("点位18 未找到可见搜一搜窗口, 需完全重来")
            return None
        r_ap = ctypes.wintypes.RECT()
        _pc._u32().GetWindowRect(appex[0][0], ctypes.byref(r_ap))
        x_left = r_ap.left                      # 搜一搜窗口左边
        x_right = r_ap.right - 1                # 搜一搜窗口最右边(探测原点)
        u32_ = _pc._u32()
        sw_ = u32_.GetSystemMetrics(_pc.SM_CXSCREEN)
        half_w = sw_ // 2
        base_y = int(p14[1])                      # y = 搜一搜按钮的y
        raw_step = max(1, (int(p14[0]) - x_left) // 30)   # 搜索按钮到窗口左边 / 30

        def snap():
            # 截图范围: 宽=左半屏中线(sw/4) 到 屏幕中线(sw/2); 高=搜一搜按钮y×2
            return np.array(ImageGrab.grab(
                bbox=(half_w // 2, 0, half_w, base_y * 2)).convert("RGB"))

        def changed(a, b):
            return (np.abs(a.astype(int) - b.astype(int)).sum(axis=2) > 15).mean()

        prev = snap()
        changes = 0
        cx = x_right
        while cx > half_w // 2:   # 扫过左半屏中线(sw/4)仍无目标 => 需完全重来
            # 横向探测: 移动鼠标(不点击)触发 hover 变化
            _pc._u32().SetCursorPos(cx, base_y)
            # 每次移动后等 5s 让 hover 变化稳定
            _time.sleep(5.0)
            cur = snap()
            if changed(cur, prev) > 0.001:
                changes += 1
                if changes == 1:
                    # 第一次变化: 停3秒等界面稳定, 再截图作为变化基准
                    _time.sleep(3.0)
                    cur = snap()
                log.info(f"点位18 探测({cx},{base_y}) 第{changes}次变化 步长={raw_step}")
                if changes >= 4:
                    # 第4次: 连续点击两次(间隔0.5s), 然后判定搜一搜窗口是否在左半屏:
                    #   在左半屏 => 目标点位; 不在(切走/收起) => 步长过大需完全重来
                    ctx.click(cx, base_y)
                    _time.sleep(0.5)
                    ctx.click(cx, base_y)
                    _time.sleep(0.5)
                    appex_now = _pc.find_windows(exe=tasks_svc.WECHAT_APPEX, visible_only=True)
                    if not appex_now:
                        log.warning(f"点位18 第{changes}次后搜一搜窗口不可见, 步长过大, 需完全重来")
                        return None
                    r_chk = ctypes.wintypes.RECT()
                    _pc._u32().GetWindowRect(appex_now[0][0], ctypes.byref(r_chk))
                    if abs(r_chk.left) <= 2:
                        log.info(f"点位18 ({cx},{base_y}) 搜一搜仍在左半屏 => 命中")
                        return cx, base_y
                    log.warning(f"点位18 第{changes}次后搜一搜不在左半屏, 步长过大, 需完全重来")
                    return None
            prev = cur
            cx -= raw_step
        # while 正常结束(已过左半屏中线)仍未凑满4次变化 => 步长过大
        log.warning("点位18 扫过左半屏中线仍未达4次变化, 需完全重来")
        return None

    # 完全重试: 每次从窗口初始化+几何重建开始(不循环部分逻辑)
    for attempt_idx in range(3):
        got = attempt()
        if got:
            return got
    log.warning("点位18 3次完全重试均未命中(步长过大或扫过中线)")
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
            return None, None, "", f"识别失败: {name}"
        return x, y, remark, ""
    except Exception as e:
        return None, None, "", f"流程异常: {e}"


def _attach_wechat():
    """前置微信窗口到前台(自动设置需要操作屏幕)"""
    from ...core import computer as _pc
    from ...services import tasks as _tasks
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
    from ...services import tasks as _tasks
    from ...core import computer as _pc
    ok, _txt = _tasks.init_wechat_window()
    if ok:
        return True
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


def _point_order_from_db():
    """点位执行顺序: 基于 sort_config(type='point') 数据库排序, 未配置的点按 id 补位末尾
    (与 /api/points 列表排序一致, 前端拖拽调整后一键设置同步生效)"""
    from ...database import get_conn as _gc
    conn = _gc()
    try:
        rows = conn.execute("""
            SELECT p.name FROM points p
            LEFT JOIN sort_config s ON p.id = s.record_id AND s.type='point'
            ORDER BY COALESCE(s.sort_order, 999999999) ASC, p.id ASC""").fetchall()
        return [r["name"] for r in rows if r["name"]]
    finally:
        conn.close()


def run_all_points_stream(names: str = ""):
    """流式一键设置: 逐点位 yield 事件(step/progress/ok/fail/warn/done), 前端边收边渲染
    关键: 必须边执行边 yield(真生成器), 路由逐条转发; 攒到队列尾部一次性返回会导致前端收不到实时事件
    names: 逗号分隔点位名(空=全部); 单点位自动设置传单个名
    执行顺序: 基于数据库 sort_config(type='point'), 不再硬编码"""
    db_order = _point_order_from_db()
    if names:
        want = set(names.split(","))
        order = [n for n in db_order if n in want]
    else:
        order = db_order
    yield f"[step] 一键设置开始: 共 {len(order)} 个点位({'全部' if not names else '指定'})"

    global _flow_tid
    _flow_tid = threading.get_ident()   # 记录执行线程, ESC 注入 StopFlow 整流程放弃
    ok_n = fail_n = done = 0
    total = len(order)
    stopped = False
    try:
        for name in order:
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
                # 写库(与 /point/{pid} 一致): 99999 保留备注, 其余清备注
                try:
                    conn = _get_conn()
                    try:
                        conn.execute("UPDATE points SET x=?, y=?, remark=? WHERE name=?",
                                     (x, y, (_rem if x == 99999 else ""), name))
                        conn.commit()
                    finally:
                        conn.close()
                except Exception as _e2:
                    log.warning(f"点位写库失败 {name}: {_e2}")
                yield f"[ok] ✓ {name} = ({x},{y})"
            else:
                fail_n += 1
                yield f"[fail] ✗ {name}: {errtxt}"
                # 任一点位失败: 立即停止后续点位(可单独重试失败点位)
                stopped = True
                yield "[warn] 点位识别失败, 一键设置已停止, 可单独重试该点位"
                break
    except StopFlow:
        # ESC 注入: 当前点位整流程直接放弃, 正常收尾
        stopped = True
        try:
            yield "[warn] 已停止: 点位已放弃"
        except Exception:
            pass
    finally:
        _flow_tid = None
        unlock()   # 兜底: 无论前端是否正常 unlock, run-all 结束即释放(幂等)
    for nmsg in drain_lock_notices():
        yield nmsg
    yield f"[done] 一键设置完成: 成功 {ok_n} / 失败 {fail_n}" + (" (已停止)" if stopped else "")


def _is_pure_calc(name):
    """纯计算点位(28/29等)不 attach 微信窗口"""
    return name in ("复制链接左上", "复制链接右下")



# ---------------------------------------------------------------------------
# 一键设置: 输入锁定(同采集: 拦截人工键鼠+提示, ESC停止) + 按依赖序执行全部点位
# ---------------------------------------------------------------------------
_input_lock = None
_stop_requested = [False]
_last_block_notice = [0.0]


class StopFlow(BaseException):
    """停止信号异常(BaseException): ESC 时注入执行线程, 点位流程任意深处直接中断,
    无需在各探测循环埋退出点; run_all 流捕获后正常收尾"""
    pass


_flow_tid = None    # 当前 run-all 执行线程 id(供 ESC 注入 StopFlow)


def _notice_block():
    """拦截人工输入提示(限流3s)"""
    now = _t.monotonic()
    if now - _last_block_notice[0] < 3.0:
        return
    _last_block_notice[0] = now
    try:
        from ...services import tasks as tasks_svc
        tasks_svc.tasks_echo("[warn] 自动设置期间禁用鼠标和键盘，请勿操作! 按 ESC 可停止")
    except Exception:
        pass


def _on_esc():
    _stop_requested[0] = True
    # 向 run-all 执行线程注入 StopFlow: 无论点位流程在哪一步, 整流程直接放弃
    tid = _flow_tid
    if tid:
        try:
            ctypes.pythonapi.PyThreadState_SetAsyncExc(
                ctypes.c_long(tid), ctypes.py_object(StopFlow))
        except Exception:
            pass
    try:
        from ...services import tasks as tasks_svc
        tasks_svc.tasks_echo("[warn] 已请求停止: 当前点位将立即放弃")
    except Exception:
        pass


_lock_notices = []      # 拦截提示队列(lock 产生, run-all 流消费)


def _notice_block_push():
    """拦截提示 -> 写入队列(供一键设置流读取)"""
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
        from ...routers import collect as collect_mod
        if collect_mod._task_running_count() > 0:
            return False
    except Exception:
        pass
    from ...core.inputlock import InputLock
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


def stop_requested():
    return _stop_requested[0]

# 点位 27: 点击复制链接 (依赖28/29区域)
# 流程: 微信就位 -> 完整调用init+search_window_init -> 搜一搜查询文章链接
#   -> 等1s -> 点18(3点弹菜单) -> 等0.5s -> 截[28,29]区域 -> OCR找"复制"文字按钮
#   -> 按钮中心坐标 = 点位27

ARTICLE_LINK_DEMO_27 = "https://mp.weixin.qq.com/s/X7fAdvvZ-Gq_2SW19OKfVw"  # 与 content_points.ARTICLE_LINK_DEMO 相同(搜一搜演示文章)


@flow_point("点击复制链接")
def _flow_point27_copy(ctx):
    # 依赖点位(与库 depend_points 同步): [11, 12, 9, 14, 18, 28, 29]
    from ...services import tasks as tasks_svc
    from ...core import computer as _pc

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
    _time.sleep(3.0)                        # 等3秒加载(文章内容/菜单可用)

    p18 = tasks_svc._read_point(18)
    p28 = tasks_svc._read_point(28)
    p29 = tasks_svc._read_point(29)
    if not p18 or not p28 or not p29:
        log.warning(f"点位27 缺前置(18{bool(p18)} 28{bool(p28)} 29{bool(p29)})")
        return None, None

    # 参考 tasks 文章采集的复制链接循环: 3次机会, 点18弹菜单 -> 截图[28,29]OCR检"复制"
    for _try in range(1, 4):
        ctx.click(p18[0], p18[1], wait_after=0.5)      # 点18弹菜单, 等0.5s菜单弹出
        img = ImageGrab.grab(bbox=(p28[0], p28[1], p29[0], p29[1])).convert("RGB")
        hit = None
        for cx, cy, text, score, sbox, _br in ctx.ocr_box(img):
            if "复制" in text:
                hit = (int(cx), int(cy))
                break
        if hit:
            ax, ay = p28[0] + hit[0], p28[1] + hit[1]
            log.info(f"点位27 第{_try}次 识别复制按钮: ({ax},{ay})")
            return ax, ay
        # 未检测到"复制": 再点一次18弹菜单, 等0.5s后进入下一次尝试
        log.warning(f"点位27 第{_try}次未识别到'复制', 再次点18重试")
        ctx.click(p18[0], p18[1], wait_after=0.5)
    log.warning("点位27 3次均未识别到'复制'字样")
    return None, None


# ---------------------------------------------------------------------------

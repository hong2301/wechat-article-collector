# -*- coding: utf-8 -*-
"""关键词查询流程模块(公众号查询页分支)。

分支位置: 采集流程在 article_list_wait_stable 之前分流——
  关键词参数为空  -> 走原 logic(article_list_wait_stable)
  关键词不为空    -> 走本模块流程
"""
import ctypes
import re
import time as _time

from PIL import Image

from ...core import computer as pc
from ...core import ocr as ocr_service
from ...core.common import wait_page_stable, _read_point
from ...services.tasks.wx_window import WECHAT_APPEX  # noqa: F401 (re-export)
from .wx_window import WECHAT_APPEX

# ---------------------------------------------------------------------------
# 文章点位结构特征
# ---------------------------------------------------------------------------
# 阅读量部分格式固定: "阅读" + 数字(可含千分位逗号)
_READ_RE = re.compile(r"阅读\s*([\d,，]+)")
# 时间部分多格式(全部):
#   yyyy/mm/dd | yyyy/m/dd | yyyy/mm | yyyy | m/dd | m/d | d
#   n个月前 | n天前 | n小时前
_TIME_RE = re.compile(
    r"(?:"
    r"\d{4}[\/\-]\d{1,2}[\/\-]\d{1,2}"   # 2025/3/3
    r"|20\d{2}[\/\-]\d{1,2}"             # 2025/3
    r"|20\d{2}"                          # 2025
    r"|\d{1,2}[\/\-]\d{1,2}"             # 3/5
    r"|\d{1,2}"                          # 5
    r"|\d+[个]?月[前|]?"                 # (n个月前另设, 见下)
    r"|\d+个月前|\d+天前|\d+小时前"      # 相对时间
    r")"
)
# 时间与阅读之间必有空白(OCR 可能识别为半角空格/全角空格/多个空格)
_SEP_RE = re.compile(r"[\s\u3000　]+")


def _match_article_struct(text: str):
    """校验文章点位结构: 时间 + 空白 + 阅读量。返回 (时间串, 阅读数字) 或 None。
    结构特征: 时间部分格式多变(见 _TIME_RE), 阅读部分固定 '阅读'+数字,
    两者之间是若干空白(半角/全角空格)。"""
    if not text:
        return None
    # 时间与阅读之间必有空白(OCR 可能识别为半角/全角空格/多个空格, 也可能连读无空格)
    m = re.match(
        r"^(?P<time>.+?)[\s\u3000　]*(?P<read>阅读[\s\u3000　]*[\d,，]+)$",
        text.strip())
    if not m:
        return None
    time_txt = m.group("time").strip()
    read_txt = m.group("read").strip()
    # 时间部分必须符合任一格式
    if not _TIME_RE.fullmatch(time_txt):
        return None
    rm = _READ_RE.search(read_txt)
    if not rm:
        return None
    return time_txt, rm.group(1)


def _extract_article_points(ocr_items, shot_path, region):
    """从 OCR 结果提取文章点位列表(内部函数)。
    判定条件(全部满足):
      1) 文本含 '阅读'
      2) 颜色: 灰字白底(截图区域颜色判定)
      3) 结构: 时间 + 空白 + 阅读量(时间格式多变, 阅读固定)
    返回: [{cx, cy, text, time, reads, box}, ...] 按屏幕绝对坐标
    """
    points = []
    try:
        _im = Image.open(shot_path)
        items = ocr_items
    except Exception:
        items = []
        _im = None
    for it in items:
        if not it or len(it) < 6:
            continue
        cx, cy, text, score, sbox, brightness = it
        if not text or "阅读" not in text:
            continue
        # 结构校验(时间+空白+阅读)
        m = _match_article_struct(text)
        if not m:
            continue
        time_txt, reads = m
        # 颜色: 灰字白底(该 bbox 区域颜色)
        if _im is not None and sbox:
            try:
                cols = ocr_service.color_sort(_im, region=(
                    min(p[0] for p in sbox), min(p[1] for p in sbox),
                    max(p[0] for p in sbox), max(p[1] for p in sbox)))
            except Exception:
                cols = []
            colset = {c for _, _, c in cols[:2]}
            if not cols or "白" not in colset or not ({"灰"} & colset):
                continue   # 非灰字白底 -> 排除
        # 点击坐标: sbox 相对截图 -> 屏幕绝对(DPI 按比例)
        try:
            _cx0, _cy0 = ocr_service.ocr_abs(_im, region,
                                             min(p[0] for p in sbox), min(p[1] for p in sbox))
            _cx1, _cy1 = ocr_service.ocr_abs(_im, region,
                                             max(p[0] for p in sbox), max(p[1] for p in sbox))
            click_x, click_y = (_cx0 + _cx1) // 2, (_cy0 + _cy1) // 2
        except Exception:
            click_x, click_y = cx, cy
        points.append({
            "cx": click_x, "cy": click_y,
            "text": text.strip(),
            "time": time_txt,
            "reads": reads,
            "box": sbox,
        })
    return points


def gzh_query_page_article_loop():
    """公众号查询页文章列表循环(关键词查询分支第二步)。

    前提(文字记录, 本函数内部不做判定): 须在 gzh_query_page_init 成功(点击点位42,
    已进入公众号查询页文章列表)之后调用。

    流程: while 死循环(刻意安排, 结束条件后续补充):
      1) 点位43/44 区域稳定性检测: 60次机会, 连续30次相同判稳定
      2) 截图点位43/44 区域
      3) OCR 得到文本结果
      4) 内部函数提取文章点位(文本含'阅读' + 灰字白底 + 时间/阅读量结构)
      5) 输出文章点位列表

    返回: (成功?, 说明文本) —— 死循环一般由外部停止信号/异常打断
    """
    from ...core.robot import stop_requested, request_stop
    logs = []

    p43 = _read_point(43)
    p44 = _read_point(44)
    if not p43 or not p44:
        logs.append("缺少点位43/44")
        return False, "; ".join(logs)
    x1, y1 = p43
    x2, y2 = p44
    region = (x1, y1, x2, y2)

    loop_n = 0
    while True:
        loop_n += 1
        # 外部停止信号(前端断开/手动停止) -> 退出死循环
        if stop_requested():
            logs.append(f"第{loop_n}轮收到停止信号, 退出循环")
            break

        # 1) 点位43/44 稳定性检测(60次/连续30次)
        ok, info = wait_page_stable(x1, y1, x2, y2, same_need=30, timeout=60, interval=0.1)
        if not ok:
            logs.append(f"第{loop_n}轮点位43/44未稳定(60次内未达30次连续): {info}")
            return False, "; ".join(logs)

        # 2) 截图
        shot_path, _b64 = pc.screenshot(x1, y1, x2, y2, img_format="png")
        if not shot_path:
            logs.append(f"第{loop_n}轮截图失败")
            return False, "; ".join(logs)

        # 3) OCR
        try:
            items = ocr_service.ocr(Image.open(shot_path))
        except Exception as e:
            logs.append(f"第{loop_n}轮OCR失败: {e}")
            return False, "; ".join(logs)

        # 4) 提取文章点位(内部函数)
        points = _extract_article_points(items, shot_path, region)

        # 5) 输出文章点位列表
        logs.append(f"第{loop_n}轮识别文章点位 {len(points)} 个")
        for pt in points:
            logs.append(f"  文章: {pt['time']} | {pt['text']} | 阅读{pt['reads']} @({pt['cx']},{pt['cy']})")

        # 死循环(刻意安排, 结束条件后续补充): 本轮结束直接下一轮
        _time.sleep(0.1)

    return True, "; ".join(logs)


def gzh_query_page_init(keyword: str = ""):
    """公众号查询页初始化(关键词查询分支第一步)。

    前提(文字记录, 本函数内部不做判定): 必须在【搜一搜窗口查询公众号成功】之后调用,
    即已通过搜一搜查询到公众号并进入其查询页(依赖 search_query 流程的产物)。

    参数:
      keyword  要查询的关键词(输入到公众号查询页搜索框)

    步骤:
      1. 页面稳定检测: 检测范围 = 搜一搜窗口的上半部分
         (基于搜一搜窗口坐标, 不基于屏幕; x=窗口全宽, y=窗口顶~窗口高一半)
         60 次机会, 连续 30 次截图相同即判稳定
      2. 稳定后点击点位41(公众号查询确认/列表, 点位已预置)
      3. 点击后等待0.3s, 剪贴板粘贴关键词(参考 search_query 输入法)
      4. 输入完等待0.2s, 按回车
      5. 回车后再次页面稳定检测(同样搜一搜窗口上半, 60次/连续30次)
      6. 稳定后点击点位42(查询结果列表/确认)

    返回: (成功?, 说明文本)
    """
    logs = []

    # 1) 基于搜一搜窗口取矩形
    appex = pc.find_windows(exe=SW_APPEX, visible_only=True)
    if not appex:
        logs.append("未找到搜一搜窗口(WeChatAppEx)")
        return False, "; ".join(logs)
    r = ctypes.wintypes.RECT()
    pc._u32().GetWindowRect(appex[0][0], ctypes.byref(r))
    win_x1, win_y1 = r.left, r.top
    win_half_y = r.top + (r.bottom - r.top) // 2      # 窗口上半部分底线
    win_x2, win_y2 = r.right, win_half_y

    # 2) 页面稳定检测(60次机会, 连续30次相同判稳定)
    ok, info = wait_page_stable(win_x1, win_y1, win_x2, win_y2,
                                same_need=30, timeout=60, interval=0.1)
    logs.append(f"查询页稳定检测: {'稳定' if ok else '未稳定'} | {info}")
    if not ok:
        logs.append("查询页60次内未达30次连续稳定")
        return False, "; ".join(logs)

    # 3) 稳定后点击点位41
    p41 = _read_point(41)
    if not p41:
        logs.append("缺少点位41(公众号查询确认)")
        return False, "; ".join(logs)
    pc.mouse_click(p41[0], p41[1])
    logs.append(f"已点击点位41({p41[0]},{p41[1]})")

    # 4) 点击后等待0.3s, 剪贴板粘贴关键词(参考 search_query 输入法)
    _time.sleep(0.3)
    if not pc.set_clipboard_text(keyword):
        logs.append("剪贴板写入关键词失败")
        return False, "; ".join(logs)
    pc.ctrl_key("V")
    logs.append(f"已粘贴关键词: {keyword}")

    # 5) 输入完等待0.2s, 按回车
    _time.sleep(0.2)
    pc.key_press(pc.VK_RETURN)
    logs.append("关键词输入完成, 已按回车")

    # 6) 回车后再次页面稳定检测(搜一搜窗口上半, 60次/连续30次)
    ok2, info2 = wait_page_stable(win_x1, win_y1, win_x2, win_y2,
                                  same_need=30, timeout=60, interval=0.1)
    logs.append(f"查询结果稳定检测: {'稳定' if ok2 else '未稳定'} | {info2}")
    if not ok2:
        logs.append("查询结果60次内未达30次连续稳定")
        return False, "; ".join(logs)

    # 7) 稳定后点击点位42(查询结果列表/确认)
    p42 = _read_point(42)
    if not p42:
        logs.append("缺少点位42(查询结果)")
        return False, "; ".join(logs)
    pc.mouse_click(p42[0], p42[1])
    logs.append(f"已点击点位42({p42[0]},{p42[1]})")
    return True, "; ".join(logs)
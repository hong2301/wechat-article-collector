# -*- coding: utf-8 -*-
"""关键词查询流程模块(公众号查询页分支)。

分支位置: 采集流程在 article_list_wait_stable 之前分流——
  关键词参数为空  -> 走原 logic(article_list_wait_stable)
  关键词不为空    -> 走本模块流程
"""
import ctypes
import hashlib
import logging
import re
import time as _time

from PIL import Image

from ...core import computer as pc
from ...core import ocr as ocr_service
from ...core.common import wait_page_stable, _read_point
from ...database import get_conn
from .article_collect import article_data_collect, reset_session_links

log = logging.getLogger("collect.keysearch")   # 对接 main.py 已配的 root handler -> data/logs/backend.log
from ...services.tasks.wx_window import WECHAT_APPEX  # noqa: F401 (re-export)
from .wx_window import WECHAT_APPEX

# ---------------------------------------------------------------------------
# 文章点位结构特征
# ---------------------------------------------------------------------------
# 阅读量部分格式固定: "阅读" + 数字(可含千分位逗号)
_READ_RE = re.compile(r"阅读\s*([\d,，]+)")


def _extract_article_points(ocr_items, shot_path, region):
    """从 OCR 结果提取文章点位列表(内部函数)。
    判定条件(满足其一):
      A) 文本含 '阅读' + 数字(格式: 阅读+数字) -> 灰字白底
      B) 文本含 '最近读过'(被读过的文章无'阅读', 显示'最近读过') -> 不做颜色判定
    返回: [{cx, cy, text, time, reads, box}, ...] 按屏幕绝对坐标;
          点击 x 取点位43(x1=region起点), 即列表最左缘整行点击
    """
    points = []
    try:
        _im = Image.open(shot_path)
        items = ocr_items
    except Exception:
        items = []
        _im = None
    log.info("[kw-extract] 开始提取: region=%s items=%d", region, len(items))
    for it in items:
        if not it or len(it) < 6:
            continue
        cx, cy, text, score, sbox, brightness = it
        if not text:
            continue
        # 文本识别: A=含'最近读过'(被读过文章, 无'阅读'); B=含'阅读'+数字
        rm = None
        recent = False
        if "最近读过" in text:
            recent = True
        else:
            if "阅读" not in text:
                log.info("[kw-extract] 不含'阅读/最近读过'(跳过): %r", text)
                continue
            rm = _READ_RE.search(text)
            if not rm:
                log.info("[kw-extract] 含'阅读'但无数字(跳过): %r", text)
                continue
        reads = rm.group(1) if rm else None   # '最近读过'型无数字 -> reads=None(走阅读数采集)
        # 颜色: 按类型要求 B=灰字白底('阅读'+数字); A=白底+(蓝或彩)('最近读过',
        #   蓝色 OCR 判定不稳, 高饱和蓝常被归为'彩', 故'彩'白底也算命中)
        if _im is not None and sbox:
            try:
                cols = ocr_service.color_sort(_im, region=(
                    min(p[0] for p in sbox), min(p[1] for p in sbox),
                    max(p[0] for p in sbox), max(p[1] for p in sbox)))
            except Exception as e:
                log.info("[kw-extract] 颜色判定异常: %r err=%s", text, e)
                cols = []
            colset = {c for _, _, c in cols[:2]}
            if not cols:
                log.info("[kw-extract] 颜色判定无结果(跳过): %r", text)
                continue
            if recent:
                pass   # 最近读过: 不做颜色判定(文本本身已唯一标识)
            else:
                if "白" not in colset or "灰" not in colset:
                    log.info("[kw-extract] 阅读颜色不符(需要白+灰, 实际%s, 跳过): %r",
                             sorted(colset), text)
                    continue
        # 点击坐标: x 取点位43(region起点x=列表最左缘整行), y 取该行 sbox 左上角
        try:
            _cy0 = ocr_service.ocr_abs(_im, region, 0,
                                       min(p[1] for p in sbox))[1]
            click_x = region[0]   # 点位43的x
            click_y = _cy0
        except Exception:
            click_x, click_y = region[0], cy
        log.info("[kw-extract] 命中%s: %r -> 阅读=%s @(%s,%s)",
                 '(最近读过)' if recent else '', text, reads, click_x, click_y)
        points.append({
            "cx": click_x, "cy": click_y,
            "text": text.strip(),
            "time": None,
            "reads": reads,
            "box": sbox,
        })
    return points


def gzh_query_page_article_loop(date_start="", date_end="", biz="",
                                capture_4metrics=False, capture_read=False,
                                save_html=False, save_dir="",
                                max_comments=None, max_level1=None, max_level2=0):
    """公众号查询页文章列表循环(关键词查询分支第二步)。

    前提(文字记录, 本函数内部不做判定): 须在 gzh_query_page_init 成功(点击点位42,
    已进入公众号查询页文章列表)之后调用。

    参数: date_start/date_end/biz/采集开关/保存参数/评论参数 与 article_list_wait_stable 一致。
    流程: while 循环(点击采集后滚动, 连续3轮截图相同结束):
      1) 点位43/44 区域稳定性检测: 60次机会, 连续30次相同判稳定
      2) 截图点位43/44 区域(+md5 连续相同判定)
      3) OCR 得到文本结果
      4) 内部函数提取文章点位(文本含'阅读'+数字 + 灰字白底)
      5) 遍历文章点位: 点击 -> 等0.3s -> article_data_collect(collect_type=1)
      6) 向下滚动(滚动 id10) + 鼠标移点位18

    返回: (成功?, 说明文本) —— 死循环一般由外部停止信号/异常打断
    """
    reset_session_links()   # 新任务: 清空本次会话已采链接集合
    from ...core.robot import stop_requested, request_stop, tasks_echo
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
    prev_shot_hash = None   # 与 article_list 同法: 独立截图md5比较, 连续相同判定到底
    same_shot = 0

    def echo(msg):
        """本轮日志: 存 logs 并实时转发到前端"""
        logs.append(msg)
        tasks_echo(msg)

    while True:
        loop_n += 1
        # 外部停止信号(前端断开/手动停止) -> 退出死循环
        if stop_requested():
            echo(f"第{loop_n}轮收到停止信号, 退出循环")
            break

        # 1) 点位43/44 稳定性检测(60次/连续30次)
        ok, info = wait_page_stable(x1, y1, x2, y2, same_need=30, timeout=60, interval=0.1)
        log.info("[kw-loop] 第%d轮稳定检测: 区域=(%s,%s,%s,%s) %s",
                 loop_n, x1, y1, x2, y2, '稳定' if ok else '未稳定:'+info)
        if not ok:
            echo(f"第{loop_n}轮点位43/44未稳定(60次内未达30次连续): {info}")
            return False, "; ".join(logs)

        # 2) 截图
        shot_path, _b64 = pc.screenshot(x1, y1, x2, y2, img_format="png")
        if not shot_path:
            echo(f"第{loop_n}轮截图失败")
            return False, "; ".join(logs)
        log.info("[kw-loop] 第%d轮截图: %s", loop_n, shot_path)
        # 截图后立刻算 md5(临时文件会被覆盖), 供连续相同判定
        try:
            with open(shot_path, "rb") as _f:
                cur_shot_hash = hashlib.md5(_f.read()).hexdigest()
        except Exception:
            cur_shot_hash = None
        if prev_shot_hash == cur_shot_hash:
            same_shot += 1
        else:
            same_shot = 1
        prev_shot_hash = cur_shot_hash

        # 结束条件: 连续3轮截图完全相同 -> 到底, 结束 while
        if same_shot >= 5:
            echo(f"第{loop_n}轮: 连续5次列表截图相同, 判定无更多文章, 停止")
            log.info("[kw-loop] 第%d轮连续5次截图相同, 退出循环", loop_n)
            return True, "无更多文章"

        # 截图与上次相同(第2次确认): 跳过本轮 OCR/提取/输出(点位已拿), 直接滚动
        if same_shot >= 2:
            echo(f"第{loop_n}轮截图与上次相同, 跳过本轮OCR/提取/输出, 直接滚动")
            log.info("[kw-loop] 第%d轮截图相同, 跳过提取/输出", loop_n)
        else:
            # 3) OCR
            try:
                items = ocr_service.ocr(Image.open(shot_path))
            except Exception as e:
                echo(f"第{loop_n}轮OCR失败: {e}")
                log.exception("[kw-loop] 第%d轮OCR异常", loop_n)
                return False, "; ".join(logs)
            log.info("[kw-loop] 第%d轮 OCR items=%d", loop_n, len(items))
            for _i, _it in enumerate(items):
                if _it and len(_it) > 2 and _it[2]:
                    log.info("[kw-loop]    OCR[%d]: %r", _i, _it[2])

            # 4) 提取文章点位(内部函数)
            points = _extract_article_points(items, shot_path, region)

            # 5) 输出文章点位列表
            echo(f"第{loop_n}轮识别文章点位 {len(points)} 个")
            log.info("[kw-loop] 第%d轮提取结果: %d 个文章点位", loop_n, len(points))
            for pt in points:
                echo(f"  文章: 阅读{pt['reads']} | {pt['text']} @({pt['cx']},{pt['cy']})")

            # 5b) 遍历文章点位: 点击 -> 等待0.3s -> article_data_collect(collect_type=1)
            #     (参考 article_list: 点击后采集, 无日期范围等时间判断)
            for seq, pt in enumerate(points, 1):
                echo(f"  点击文章[{seq}] {pt['text']!r} 阅读{pt['reads']} @({pt['cx']},{pt['cy']})")
                pc.mouse_click(pt["cx"], pt["cy"])
                _time.sleep(0.3)
                ok_c, text_c = article_data_collect(
                    collect_type=1, capture_4metrics=capture_4metrics,
                    capture_read=capture_read, save_html=save_html,
                    save_dir=save_dir, biz=biz,
                    list_reads=pt["reads"], list_likes=None,
                    max_comments=max_comments, max_level1=max_level1,
                    max_level2=max_level2)
                echo(f"  文章[{seq}]数据采集: {'成功' if ok_c else '失败'} | {text_c}")
                _time.sleep(0.5)   # 采集完成间隔

        # 6) 向下滚动(滚动 id10, 锚点=点位43, 距离=|43.y-44.y|*0.95)
        try:
            conn = get_conn()
            try:
                row = conn.execute("SELECT distance, direction FROM scrolls WHERE id=10").fetchone()
            finally:
                conn.close()
            s_dist = int(float(row["distance"])) if row and row["distance"] else 0
            s_dir = row["direction"] if row and row["direction"] else "down"
        except Exception:
            s_dist, s_dir = 0, "down"
        # 第2次起连续截图相同时: 滚动前先反向回滚一半距离, 排除"假到底"
        # (页面未刷新/加载动画未触发造成截图不变), 回滚再滚下来可能触发新内容
        if same_shot >= 2 and s_dist > 0:
            back_dir = "up" if s_dir == "down" else "down"
            back_dist = max(1, int(s_dist / 2))
            pc.scroll(p43[0], p43[1], back_dist, direction=back_dir)
            echo(f"第{loop_n}轮: 截图第{same_shot}次相同, 先向{back_dir}回滚 {back_dist}px 再继续")
        if s_dist > 0:
            pc.scroll(p43[0], p43[1], s_dist, direction=s_dir)
            echo(f"第{loop_n}轮末尾: 在点位43({p43[0]},{p43[1]})向{s_dir}滚动 {s_dist}px")
        else:
            echo("滚动配置10无效, 跳过滚动")

        # 7) 滚动后鼠标移到点位18
        p18 = _read_point(18)
        if p18:
            pc._u32().SetCursorPos(p18[0], p18[1])
            echo(f"第{loop_n}轮滚动后鼠标已移到点位18({p18[0]},{p18[1]})")
        else:
            echo("第{loop_n}轮缺少点位18, 未移动鼠标")

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
    appex = pc.find_windows(exe=WECHAT_APPEX, visible_only=True)
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
# -*- coding: utf-8 -*-
"""任务子包: 评论采集(展开回复/豆包AI识别/主采集循环)"""
import io as _io, base64
import io as _io, base64
import re as _re
from PIL import Image as _PIL
import ctypes
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from ...core import computer as pc
from ...core import ocr as ocr_service
from ...core.common import (_read_point, _finish, _save_reads,
                            _extract_read_from_items, wait_page_stable)
from ...core.robot import (request_stop, clear_stop, stop_requested,
                           bind_tasks_echo, tasks_echo)
from ...services.doubao_api import recognize_interact as doubao_recognize_interact
from .helpers import (_submit_bg, _done_bg, wait_bg_done)
from .wx_window import (init_wechat_window, search_window_init, search_query,
                        WECHAT_MAIN, WECHAT_APPEX)

_comment_stats = {}
_comment_stats_lock = threading.Lock()


def _expand_reply_buttons(x1, y1, x2, y2, max_rounds=3):
    """展开评论区更多回复: while循环(最多max_rounds次)
    每轮: 截图35/36找'更多回复/N条回复'灰字按钮 -> 点第一个 -> 35/36稳定检测(30次/连续10次)
    找不到按钮或超过轮数 -> 退出返回 True(有兜底, 最终必返True)"""
    for rnd in range(1, max_rounds + 1):
        shot, _b = pc.screenshot(x1, y1, x2, y2, img_format="png")
        if not shot:
            tasks_echo("评论采集: 展开回复截图失败, 继续下一轮")
            continue
        items = ocr_service.ocr(_PIL.open(shot).convert("RGB"))
        btn = None
        for cx, cy, text, score, sbox, brightness in items:
            t = (text or "").strip()
            if "条回复" in t or "更多回复" in t:
                try:
                    if 100 < brightness < 210:
                        btn = (x1 + int(sum(p[0] for p in sbox) / len(sbox)),
                               y1 + int(sum(p[1] for p in sbox) / len(sbox)), t)
                        break
                except Exception:
                    continue
        if not btn:
            # 没有更多回复按钮: 退出循环
            tasks_echo(f"评论采集: 第{rnd}轮未发现更多回复按钮, 结束展开")
            return True
        bx, by, txt = btn
        tasks_echo(f"评论采集: 点击'更多回复'按钮 {txt!r} @({bx},{by})")
        pc.mouse_click(bx, by)
        # 点击后: 35/36页面稳定检测(30次, 连续10次相同)
        ok_stable, info = wait_page_stable(
            x1, y1, x2, y2, same_need=10, timeout=30, interval=0.1)
        tasks_echo(f"评论采集: 展开后稳定={ok_stable}({info})")
        if not ok_stable:
            tasks_echo("评论采集: 展开后未稳定, 仍继续下一轮...")
    tasks_echo(f"评论采集: 展开回复超过{max_rounds}轮, 结束")
    return True


def _bg_ai_comments(shot_b64s, art_biz, max_level1, max_level2, shot_x=None):
    """后台合成任务: 豆包识别评论(多图base64拼接) + OCR识别层级 -> 写评论表(异步)"""
    from ...database import get_conn
    tag = f"评论#{art_biz[:10]}"
    try:
        api_key = ""
        try:
            conn = get_conn()
            try:
                row = conn.execute("SELECT api_key FROM ai_model ORDER BY id LIMIT 1").fetchone()
                api_key = (row["api_key"] or "") if row else ""
            finally:
                conn.close()
        except Exception:
            pass
        if isinstance(shot_b64s, str):
            shot_b64s = [shot_b64s]
        shot_b64s = [b for b in shot_b64s if b]
        if not shot_b64s or not api_key:
            tasks_echo(f"[async:{tag}] 无AI配置或截图失败, 评论识别跳过")
            return
        # 多图(上一轮+本轮)拼接为一张完整图
        from ...core.common import merge_comment_shots
        if len(shot_b64s) >= 2:
            merged_img = merge_comment_shots(shot_b64s[0], shot_b64s[1])
        else:
            merged_img = None
        if merged_img is not None:
            _buf = _io.BytesIO(); merged_img.save(_buf, format="PNG")
            shot_b64s = [_buf.getvalue()]
            _buf2 = _io.BytesIO(); merged_img.save(_buf2, format="WEBP", lossless=True, method=6)
            _ai_b64 = "data:image/webp;base64," + base64.b64encode(_buf2.getvalue()).decode()
        else:
            _ai_b64 = shot_b64s[0]
        from ...services.doubao_api import doubao_extract_comments as _dec

        def _ocr_levels():
            try:
                name_rows = []
                _sb = shot_b64s[0].split(",", 1)[1] if "," in shot_b64s[0] else shot_b64s[0]
                img = _PIL.open(_io.BytesIO(base64.b64decode(_sb))).convert("RGB")
                items = ocr_service.ocr(img)
                for cx, cy, text, score, sbox, brightness in items:
                    if _re.search(r"昨天|前天|\d+天前|\d+小时前|\d+分钟前|\d+月\d+日|今天", text or "") and len((text or "").strip()) < 30:
                        x0 = min(p[0] for p in sbox); y0 = min(p[1] for p in sbox)
                        name_rows.append((y0, x0, text))
                if not name_rows:
                    return []
                name_rows.sort()
                if shot_x is not None:
                    return [2 if x0 > 20 else 1 for _, x0, _ in name_rows]
                min_x = min(r[1] for r in name_rows)
                return [2 if (r[1] - min_x) > 15 else 1 for r in name_rows]
            except Exception:
                return []
        with ThreadPoolExecutor(max_workers=2) as ex:
            f_ai = ex.submit(_dec, _ai_b64, api_key)
            f_ocr = ex.submit(_ocr_levels)
            comments = f_ai.result(timeout=60) or []
            levels = f_ocr.result() or []
        for i, c in enumerate(comments):
            if i < len(levels):
                c["层级"] = levels[i]
        if not comments:
            tasks_echo(f"[async:{tag}] 豆包未识别到评论")
            _save_debug_shot_b64(shot_b64s[0], "豆包", tag)
            return
        if max_level1 is not None and max_level1 > 0:
            comments = comments[:max_level1]
        if max_level2 is not None and max_level2 >= 0:
            comments = [c for c in comments if int(c.get("层级", 1) or 1) == 1 or max_level2 > 0]
        if not comments:
            tasks_echo(f"[async:{tag}] 无符合数量上限的评论")
            _save_debug_shot_b64(shot_b64s[0], "豆包", tag)
            return
        from ...core.common import save_comments
        wrote = save_comments(art_biz, comments)
        tasks_echo(f"[async:{tag}] 识别评论{len(comments)}条, 写入{wrote}条")
        # 更新采集计数(一级/二级/总数)
        with _comment_stats_lock:
            st = _comment_stats.setdefault(art_biz, {"l1": 0, "l2": 0, "total": 0})
            for c in comments:
                st["total"] += 1
                if int(c.get("层级", 1) or 1) == 2:
                    st["l2"] += 1
                else:
                    st["l1"] += 1
            _total = st["total"]
        # 识别数持久化到 articles.comment_recog
        try:
            conn = get_conn()
            try:
                conn.execute("UPDATE articles SET comment_recog=? WHERE art_biz=?",
                             (str(_total), art_biz))
                conn.commit()
            finally:
                conn.close()
        except Exception:
            pass
    except Exception as e:
        tasks_echo(f"[async:{tag}] 评论识别异常: {e}")


def _collect_comments(collect_type, link, art, biz,
                      max_comments=None, max_level1=None, max_level2=0):
    """采集评论: 死循环(停止逻辑后补)。每轮:
    1) 点点位34(评论按钮) -> 点位35/36稳定检测(60次/连续20) -> 截图
    2) 展开'更多回复'按钮循环(点第一个直到没有)
    3) 最后截图 -> 提交后台合成任务(AI识别+OCR层级+写库, 不等待)
    4) 滚动配置id=5 -> 下一轮
    参数: max_comments/max_level1/max_level2 同上"""
    _mc = "无限" if max_comments is None else str(max_comments)
    _m1 = "无限" if max_level1 is None else str(max_level1)
    _m2 = "无限" if max_level2 is None else str(max_level2)
    tasks_echo(f"评论采集: 开始(文章评论数={_mc}, 一级评论数={_m1}, 每级二级评论数={_m2})")
    p34 = _read_point(34)   # 评论按钮
    p35 = _read_point(35)   # 评论区左上
    p36 = _read_point(36)   # 评论区右下
    p30 = _read_point(30)   # 4指标区域左上(含评论按钮=第4值)
    p31 = _read_point(31)   # 4指标区域右下
    if not (p34 and p35 and p36):
        tasks_echo("评论采集: 缺少点位34/35/36, 跳过")
        return
    # 点评论按钮前: 4指标区域(30/31)页面稳定检测(评论按钮即该区第4值留言), 逻辑同采集4指标
    if p30 and p31:
        ok_stable, info = wait_page_stable(
            p30[0], p30[1], p31[0], p31[1], same_need=15, timeout=50, interval=0.1)
        tasks_echo(f"评论采集: 4指标区域稳定={ok_stable}({info})")
        if not ok_stable:
            tasks_echo("评论采集: 4指标区域未稳定, 仍继续...")
        # 截图4指标区域 OCR 找"写留言": 有则说明无评论, 直接退出
        try:
            _sp, _ = pc.screenshot(p30[0], p30[1], p31[0], p31[1], img_format="png")
            if _sp:
                _items = ocr_service.ocr(Image.open(_sp))
                if any("写留言" in (it[2] or "") for it in _items):
                    tasks_echo("评论采集: 检测到'写留言'(无评论), 退出")
                    return
                tasks_echo("评论采集: 4指标区域无'写留言'(有评论或需进评论区)")
        except Exception as e:
            tasks_echo(f"评论采集: 写留言OCR检测失败: {e}")
    # 点击评论按钮进入评论区
    pc.mouse_click(p34[0], p34[1])
    tasks_echo(f"评论采集: 点击评论按钮({p34[0]},{p34[1]})")
    time.sleep(0.5)

    loop_n = 0
    prev_b64 = None      # 上一轮截图(与本轮拼接读取, 避免截断误判)
    prev_shot_sign = None   # 上一轮截图签名(连续相同即可判定无更多评论)
    same_shot_count = 0     # 连续相同截图轮数
    while True:
        loop_n += 1
        ok_stable, info = wait_page_stable(
            p35[0], p35[1], p36[0], p36[1], same_need=10, timeout=60, interval=0.1)
        tasks_echo(f"评论采集第{loop_n}轮: 评论区稳定={ok_stable}({info})")
        if not ok_stable:
            tasks_echo("评论采集: 评论区未稳定, 继续尝试...")

        _expand_reply_buttons(p35[0], p35[1], p36[0], p36[1])
        # 展开后: 重新截图识别(转base64即时传递, 避免shot.png被后续覆盖)
        _path, shot_b64 = pc.screenshot(p35[0], p35[1], p36[0], p36[1], img_format="png", as_base64=True)
        if shot_b64:
            # 兜底判断: 截图与上一轮相同(连续3次无变化 = 无更多评论), 滚动后判断处处理
            _sign = shot_b64[-500:]   # 取尾部签名(内容变化时随之变化)
            if prev_shot_sign == _sign:
                same_shot_count += 1
            else:
                same_shot_count = 1
            prev_shot_sign = _sign
            # 多图拼接: [上一轮, 本轮] 一起给AI(评论跨图截断时拼接读取)
            _sub = [prev_b64, shot_b64] if prev_b64 else [shot_b64]
            _submit_bg(_bg_ai_comments, _sub, art,
                       max_level1, max_level2, shot_x=p35[0])
            tasks_echo(f"评论采集第{loop_n}轮: 评论识别后台进行中...")
            prev_b64 = shot_b64

        try:
            from ...database import get_conn
            conn = get_conn()
            try:
                row = conn.execute("SELECT distance, direction FROM scrolls WHERE id=5").fetchone()
            finally:
                conn.close()
            s_dist = int(float(row["distance"])) if row else 0
            s_dir = row["direction"] if row else "down"
        except Exception:
            s_dist, s_dir = 0, "down"

        # ---- 停止条件判断(滚动前) ----
        with _comment_stats_lock:
            st = _comment_stats.get(art, {"l1": 0, "l2": 0, "total": 0})
            _l1, _l2, _total = st["l1"], st["l2"], st["total"]
        # 1) 设置上限(优先级: 一级 -> 二级 -> 文章总数)
        _hit = None
        if max_level1 is not None and max_level1 > 0 and _l1 >= max_level1:
            _hit = f"一级评论数已达上限({_l1}/{max_level1})"
        elif max_level2 is not None and max_level2 > 0 and _l2 >= max_level2:
            _hit = f"每级二级评论数已达上限({_l2}/{max_level2})"
        elif max_comments is not None and max_comments > 0 and _total >= max_comments:
            _hit = f"文章评论数已达上限({_total}/{max_comments})"
        if _hit:
            tasks_echo(f"评论采集: {_hit}, 停止")
            break
        # 2) 兜底: 连续3次准备采集的截图相同 = 无更多评论
        if same_shot_count >= 3:
            tasks_echo(f"评论采集: 连续3次截图相同({same_shot_count}/3), 无更多评论, 停止")
            break

        if s_dist > 0:
            pc.scroll(p35[0], p35[1], s_dist, direction=s_dir)
            tasks_echo(f"评论采集第{loop_n}轮: 滚动评论区 {s_dist}px")
            time.sleep(0.5)



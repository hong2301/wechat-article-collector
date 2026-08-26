# -*- coding: utf-8 -*-
"""backend.app.services.common: tasks 主函数共用的辅助工具

包含: 点位读取 / 页面稳定检测 / 阅读数识别 / 阅读数写库 / 采集统一退出
只依赖 computer / ocr / database, 不依赖 tasks 主函数。
"""
import hashlib
import time

from . import computer as pc
from ..database import get_conn
from .ocr import _region_grayish, extract_reads
from .robot import tasks_echo


def wait_page_stable(x1, y1, x2, y2, same_need=15, timeout=30, interval=0.1):
    """通用页面稳定判断: 对指定区域反复截图, 连续多次完全相同判页面稳定。
    参数:
      x1,y1,x2,y2  截图区域(屏幕坐标)
      same_need    连续相同多少次判稳定(默认15)
      timeout      最多截图次数(默认30, 超时判失败)
      interval     每次截图间隔(默认0.1s)
    返回: (稳定?, 说明文本)
    """
    logs = []
    same_streak = 0       # 连续相同次数
    prev_hash = None
    for i in range(1, timeout + 1):
        path, _b64 = pc.screenshot(x1, y1, x2, y2, img_format="webp")
        if not path:
            logs.append(f"截图失败(第{i}次)")
            return False, "; ".join(logs)
        try:
            with open(path, "rb") as f:
                cur_hash = hashlib.md5(f.read()).hexdigest()
        except Exception:
            logs.append(f"读取截图失败(第{i}次)")
            return False, "; ".join(logs)
        if prev_hash is not None and cur_hash == prev_hash:
            same_streak += 1
            if same_streak >= same_need:
                logs.append(f"页面稳定: 连续{i}次截图相同")
                return True, "; ".join(logs)
        else:
            same_streak = 0
        prev_hash = cur_hash
        if interval:
            time.sleep(interval)
    logs.append(f"页面未稳定: {timeout}次机会用完")
    return False, "; ".join(logs)


def _read_point(pid):
    """内部: 读取点位坐标 (x, y); 无/无效返回 None"""
    try:
        conn = get_conn()
        try:
            row = conn.execute(
                "SELECT x, y FROM points WHERE id=?", (int(pid),)).fetchone()
        finally:
            conn.close()
        if not row:
            return None
        try:
            return int(float(row["x"])), int(float(row["y"]))
        except (TypeError, ValueError):
            return None
    except Exception:
        return None


def _extract_read_from_items(items, box, img=None):
    """从OCR结果中提取阅读数: 文本含'阅读'+数字, 且该文本区域灰字颜色校验通过。
    img 给定时基于该图像素取色(异步识别屏幕已流转, 不能用ImageGrab), 否则抓当前屏幕
    返回: 阅读数(int) 或 None
    """
    ox, oy = box
    items = list(items or [])
    for i, (cx, cy, text, score, sbox, brightness) in enumerate(items):
        if "阅读" in (text or ""):
            gray = _region_grayish(sbox, (ox, oy), img)
            if gray is False:
                continue   # 颜色不是灰色系 -> 排除
            # 优先: 本段提取数字(阅读 730 / 阅读730)
            r = extract_reads(text)
            if r is not None:
                return r
            # 兜底: 与本文本 y 相近(±15px)的后续段找数字
            for _cx2, _cy2, _t2, _s2, _sbox2, _b2 in items[i + 1:]:
                if abs(_cy2 - cy) <= 15:
                    r2 = extract_reads(_t2)
                    if r2 is not None:
                        return r2
                else:
                    break
    return None


def _save_reads(biz, art, reads, logs=None):
    """更新文章表 reads 字段(按 biz+art_biz 匹配); 日志实时输出或收集(logs可选)"""
    def _out(msg):
        if logs is not None:
            logs.append(msg)
        else:
            tasks_echo(msg)
    try:
        conn = get_conn()
        try:
            conn.execute("UPDATE articles SET reads=? WHERE biz=? AND art_biz=?",
                         (reads, biz, art))
            conn.commit()
            _out(f"阅读数已写入(art={art}): {reads}")
        finally:
            conn.close()
    except Exception as e:
        _out(f"阅读数写入失败: {e}")


def _finish(logs, copy_seen, ok, reason):
    """统一退出: copy_seen表明打开过文章页需Ctrl+W; 返回 (是否成功, 文本)"""
    if copy_seen:
        try:
            pc.ctrl_key("W")
        except Exception:
            pass
        logs.append("已检测过复制字样, Ctrl+W 关闭文章页")
    text = "; ".join(logs)
    if reason:
        text = reason if not text else f"{reason} | {text}"
    return ok, text


def merge_comment_shots(top_b64, bot_b64):
    """拼接两张相邻评论区截图(上下重叠)为完整一张
    top=上方图, bot=下方图(滚动后); 找重叠行k后拼 top + bot[k:]
    返回 PIL Image 或 None"""
    try:
        import io, base64
        from PIL import Image
        def _img(b):
            sb = b.split(",", 1)[1] if "," in b else b
            return Image.open(io.BytesIO(base64.b64decode(sb))).convert("RGB")
        top = _img(top_b64); bot = _img(bot_b64)
        if top.size[0] != bot.size[0]:
            return None
        import numpy as np
        t = np.array(top); b = np.array(bot)
        best_k, best_diff = 1, 1e18
        max_k = min(300, t.shape[0], b.shape[0])
        for k in range(1, max_k):
            d = float(np.abs(t[-k:, :, :].astype(int) - b[:k, :, :].astype(int)).mean())
            if d < best_diff:
                best_diff, best_k = d, k
        if best_diff > 20:
            merged = np.vstack([t, b])          # 无明显重叠: 直接叠加
        else:
            merged = np.vstack([t, b[best_k:]])  # 去重叠拼接
        return Image.fromarray(merged)
    except Exception:
        return None


# 评论文本清洗: 生成biz前去除标点/空格 + 排除易错词(按需维护)
_COMMENT_EXCLUDE_CHARS = {
    # 常见 OCR 易错/无意义单字, 按需增补
    "一", "的", "了", "是", "不", "在", "有", "和",
    "。", "，", "、", "！", "？", "：", "；", "\"", "'",
    "（", "）", "《", "》", "【", "】", "·", "—", "…", "-",
    " ", "\u3000",  # 空格/全角空格
}


def clean_comment_text(text):
    """清洗评论文本(供生成biz): 去除标点/空格/易错词
    排除词由 _COMMENT_EXCLUDE_CHARS 记录, 可按需增补"""
    t = str(text or "")
    return "".join(ch for ch in t if ch not in _COMMENT_EXCLUDE_CHARS)


def calc_comment_id(name, loc, t, likes, text, level):
    """计算评论ID: 清洗后 作者|正文|时间 -> md5 前16位(点赞变化不影响, 防重复)"""
    import hashlib
    raw = f"{clean_comment_text(name)}|{clean_comment_text(text)}|{t}"
    return hashlib.md5(raw.encode("utf-8")).hexdigest()[:16]


def save_comments(art_biz, comment_list):
    """写入评论到 comments 表(批量), 计算 comment_biz/parent_comment_biz
    comment_list: [{名称,地区,时间,点赞数量,正文,层级,是否置顶,是否作者回复,是否作者点赞,回复文本}, ...]
    返回: 写入条数"""
    if not art_biz or not comment_list:
        return 0
    try:
        from ..database import get_conn
        l1_id = ""       # 当前所属一级评论ID
        id_map = {}      # 名称 -> 评论ID(二级"回复某某"找父级)
        fresh = []
        for c in comment_list:
            name = c.get("名称", "")
            loc = c.get("地区", "")
            t = c.get("时间", "")
            likes = str(c.get("点赞数量", "0"))
            text = c.get("正文", "")
            level = int(c.get("层级", 1) or 1)
            # 评论时间转 yyyy/mm/dd(如"7月13日" -> "2026/07/13")
            from .ocr import resolve_date
            _d = resolve_date(t) if isinstance(t, str) and t.strip() else None
            t = _d.strftime("%Y/%m/%d") if _d else (t or "")
            if cid := calc_comment_id(name, loc, t, likes, text, level):
                # 层级/父级ID
                if level == 1:
                    l1_id = cid
                parent = l1_id if level == 2 else ""
                # 根据"回复某某"找父级(若有回复文本"回复XX：")
                rtxt = c.get("回复文本", "") or ""
                if level == 1 and rtxt.startswith("回复"):
                    parent = id_map.get(rtxt.replace("回复", "", 1).split("：")[0].strip(), "")
                id_map[name] = cid
                fresh.append({
                    "comment_biz": cid, "parent_comment_biz": parent, "art_biz": art_biz,
                    "author": name, "content": text, "time": t, "likes": likes, "ip": loc,
                    "is_author": 1 if c.get("是否作者") == "是" else 0,
                    "is_top": 1 if c.get("是否置顶") == "是" else 0,
                    "is_author_reply": 1 if c.get("是否作者回复") == "是" else 0,
                    "is_author_like": 1 if c.get("是否作者点赞") == "是" else 0,
                    "level": level, "is_first": 1 if c.get("是否首评") == "是" else 0,
                })
        if not fresh:
            return 0
        conn = get_conn()
        try:
            # 已存在的评论跳过(按 comment_biz 去重)
            for c in fresh:
                exists = conn.execute(
                    "SELECT id FROM comments WHERE comment_biz=? AND art_biz=?",
                    (c["comment_biz"], art_biz)).fetchone()
                if exists:
                    continue
                conn.execute(
                    "INSERT INTO comments(comment_biz, parent_comment_biz, art_biz, author, content, "
                    "time, likes, ip, is_author, is_top, is_author_reply, is_author_like, level, is_first) "
                    "VALUES(:comment_biz,:parent_comment_biz,:art_biz,:author,:content,:time,:likes,:ip,"
                    ":is_author,:is_top,:is_author_reply,:is_author_like,:level,:is_first)", c)
            conn.commit()
        finally:
            conn.close()
        return len(fresh)
    except Exception:
        return 0
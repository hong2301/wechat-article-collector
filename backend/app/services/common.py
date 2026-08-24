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


def _extract_read_from_items(items, box):
    """从OCR结果中提取阅读数: 文本含'阅读'+数字, 且该文本区域灰字颜色校验通过。
    返回: 阅读数(int) 或 None
    """
    ox, oy = box
    items = list(items or [])
    for i, (cx, cy, text, score, sbox, brightness) in enumerate(items):
        if "阅读" in (text or ""):
            gray = _region_grayish(sbox, (ox, oy))
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
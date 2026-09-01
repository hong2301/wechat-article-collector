# -*- coding: utf-8 -*-
from . import obs
"""backend.app.services.ocr: OCR 识别模块（精简版）

参考原 main.py 使用的 RapidOCR 方案，只保留识别能力。
依赖: rapidocr_onnxruntime + Pillow

能力:
  init()   初始化/预加载 OCR 引擎(幂等)
  ocr(img) 输入 PIL 图片, 输出 OCR 识别结果(原始数据)
  classify_items(items, box)
           对 OCR 原始数据按 y 排序识别时间/文章点位
"""

import io
import re
import threading
from datetime import date, timedelta

_ocr_engine = None
_ocr_lock = threading.Lock()

# 时间格式正则（参考原 main 实现）
TIME_PATTERNS = (
    r"星期[一二三四五六日天]|周[一二三四五六日]|礼拜[一二三四五六日天]",
    r"今天|昨天|前天",
    r"\d+\s*天前",
    r"\d+\s*小时前",
    r"\d+\s*分钟前",
    r"\d{4}[-/. ]\d{1,2}[-/. ]\d{1,2}",
    r"\d{1,2}月\d{1,2}日?",
    r"\d{1,2}[-/]\d{1,2}",
)
TIME_RE = re.compile("|".join(f"({p})" for p in TIME_PATTERNS))

TIME_BRIGHT_MIN = 140   # 时间点位文字最小亮度

_WEEKDAY_CN = {"一": 0, "二": 1, "三": 2, "四": 3, "五": 4, "六": 5, "日": 6, "天": 6}


def init():
    """OCR 初始化: 预加载引擎(幂等, 可多次调用)。
    用于程序启动时预热, 避免首次识别卡顿。返回 True=就绪"""
    try:
        print("OCR: 正在加载识别引擎 ...", flush=True)
        get_ocr_engine()
        print("OCR: 识别引擎加载完成", flush=True)
        return True
    except Exception as e:
        print(f"OCR: 引擎加载失败: {e}", flush=True)
        return False


def get_ocr_engine():
    """懒加载 OCR 引擎（RapidOCR，线程安全）"""
    global _ocr_engine
    with _ocr_lock:
        if _ocr_engine is None:
            from rapidocr_onnxruntime import RapidOCR
            _ocr_engine = RapidOCR()
        return _ocr_engine


@obs.timed("ocr")
def ocr(img):
    """输入 PIL 图片, 输出 OCR 识别结果。
    返回: [(中心x, 中心y, 文本, score, sbox, brightness), ...]
      - 坐标为图片内相对坐标
      - sbox 为文本框四点坐标
      - brightness 为文字区域平均亮度(0-255)
    失败返回 []"""
    try:
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)
        engine = get_ocr_engine()
        with _ocr_lock:            # onnxruntime Session 非线程安全
            result, _ = engine(buf.read())
        items = []
        if result:
            for box_pts, text, score in result:
                xs = [p[0] for p in box_pts]
                ys = [p[1] for p in box_pts]
                cx = int(sum(xs) / len(xs))
                cy = int(sum(ys) / len(ys))
                sbox = [(int(p[0]), int(p[1])) for p in box_pts]
                try:
                    crop = img.crop((min(xs), min(ys), max(xs), max(ys)))
                    brightness = _text_brightness(crop)
                except Exception:
                    brightness = 255.0
                items.append((cx, cy, text, score, sbox, brightness))
        return items
    except Exception:
        return []


def _text_brightness(crop):
    """计算裁剪区域内文字像素的平均亮度(0-255, 排除白色背景)；无文字返回 255"""
    try:
        crop = crop.convert("L")
        px = list(crop.getdata())
        text_px = [p for p in px if p < 235]   # 排除接近背景的白色
        if not text_px:
            return 255.0
        return sum(text_px) / len(text_px)
    except Exception:
        return 255.0


def extract_reads(text):
    """从文本中提取阅读数, 提取不到返回 None
    如: '阅读730赞8' -> 730, '昨天 阅读 117' -> 117, '阅读10万+' -> 100000"""
    m = re.search(r"阅读\s*(\d+(?:\.\d+)?)\s*万" , text or "")
    if m:
        return int(float(m.group(1)) * 10000)
    m = re.search(r"阅读\s*(\d+)", text or "")
    return int(m.group(1)) if m else None


def extract_likes(text):
    """从文本中提取点赞数, 提取不到返回 None
    如: '阅读730赞8' -> 8, '昨天 阅读 117 赞 6' -> 6"""
    m = re.search(r"赞\s*(\d+)", text or "")
    return int(m.group(1)) if m else None


def resolve_date(text, today=None):
    """把 OCR 识别到的时间文本解析为绝对日期(date), 按当前时间推断; 失败返回 None
    支持: 今天/昨天/前天、x天前、星期X/周X/礼拜X、YYYY-MM-DD、X月X日、MM-DD"""
    today = today or date.today()
    text = str(text).strip()
    m = re.search(r"(\d{4})[-/. ](\d{1,2})[-/. ](\d{1,2})", text)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            pass
    m = re.search(r"(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日?", text)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            pass
    if "今天" in text:
        return today
    if "昨天" in text:
        return today - timedelta(days=1)
    if "前天" in text:
        return today - timedelta(days=2)
    m = re.search(r"(\d+)\s*天前", text)
    if m:
        return today - timedelta(days=int(m.group(1)))
    m = re.search(r"(?:星期|周|礼拜)([一二三四五六日天])", text)
    if m:
        wd = _WEEKDAY_CN[m.group(1)]
        delta = (today.weekday() - wd) % 7
        return today - timedelta(days=delta)
    m = re.search(r"(\d{1,2})月(\d{1,2})日?", text)
    if m:
        try:
            d = date(today.year, int(m.group(1)), int(m.group(2)))
        except ValueError:
            return None
        if d > today:
            d = date(today.year - 1, int(m.group(1)), int(m.group(2)))
        return d
    m = re.search(r"(\d{1,2})[-/](\d{1,2})", text)
    if m:
        try:
            d = date(today.year, int(m.group(1)), int(m.group(2)))
        except ValueError:
            return None
        if d > today:
            d = date(today.year - 1, int(m.group(1)), int(m.group(2)))
        return d
    return None


def classify_items(items, box=None):
    """对 OCR 原始数据分类识别时间/文章点位。
    参数:
      items  ocr() 的原始返回: [(cx, cy, text, score, sbox, brightness)]
             sbox 为相对截图坐标; box=(截图区域左上x,左上y) 用于换算屏幕绝对坐标
      box   截图区域左上角 (x1,y1); None 时灰字校验跳过
    返回: [(顺序, 点位类型, 点位文本, 点位box坐标, data), ...] 按 y 从上到下
      点位类型: 'time'(时间点位) / 'article'(文章点位, 含'阅读'+数字 或 '付费')
      点位box坐标: [(x1,y1),(x2,y2)...] 屏幕绝对坐标(四角)
      data: 统一JSON对象(dict), 3个字段
        time   时间点位: 标准日期 'yyyy/mm/dd'(精度天); 其他情况 None
        reads  文章点位: 阅读数(int); 提取不到 None
        likes  文章点位: 点赞数(int); 提取不到 None
    """
    ox, oy = int(box[0]), int(box[1]) if box else (0, 0)
    ordered = []
    for cx, cy, text, score, sbox, brightness in (items or []):
        has_time = TIME_RE.search(text or "")
        m_read = re.search(r"阅读\s*\d+", text or "")    # '阅读'+数字
        m_pay = "付费" in (text or "")                    # '付费'(可能无阅读)
        if has_time and not m_read:
            # 时间点位: 浅灰白文字(亮度>=140) + 灰字灰底校验
            if brightness < TIME_BRIGHT_MIN:
                continue                      # 深色 -> 非时间点位
            cols = gray_on_gray(sbox, box)
            if cols is False:
                continue                      # 非灰字灰底 -> 非时间点位
            d = resolve_date(text)
            data = {"time": d.strftime("%Y/%m/%d") if d else None,
                    "reads": None, "likes": None}
            ordered.append((cy, "time", text,
                            [(int(p[0]) + ox, int(p[1]) + oy) for p in sbox],
                            data))
        elif m_read or m_pay:
            data = {"time": None,
                    "reads": extract_reads(text),
                    "likes": extract_likes(text)}
            ordered.append((cy, "article", text,
                            [(int(p[0]) + ox, int(p[1]) + oy) for p in sbox],
                            data))
    ordered.sort(key=lambda r: r[0])   # 按 y 排序(从上到下)
    return [(i + 1, typ, text, sbox, data)
            for i, (_y, typ, text, sbox, data) in enumerate(ordered)]


__all__ = ["init", "ocr", "classify_items",
           "extract_reads", "extract_likes", "resolve_date"]

def _name_color(rgb):
    """按常见色系把 (r,g,b) 归名(自然语言): 白/黑/灰/蓝/红/绿/黄/紫/彩"""
    r, g, b = rgb
    span = max(rgb) - min(rgb)
    if span < 40:                       # 无彩色系
        avg = (r + g + b) // 3
        if avg >= 205:
            return "白"
        if avg <= 55:
            return "黑"
        return "灰"
    if r >= 150 and r - g > 60 and r - b > 60:
        return "红"
    if b >= 150 and b - r > 60 and b - g > 60:
        return "蓝"
    if g >= 150 and g - r > 60 and g - b > 60:
        return "绿"
    if r >= 140 and b >= 140 and r - g > 60 and b - g > 60:
        return "紫"
    if r >= 150 and g >= 150 and r - b > 60 and g - b > 60:
        return "黄"
    return "彩"


def color_sort(img, region=None, top=4, merge=True):
    """按 RGB 出现频率对图片主色排序, 每项带色系名称(判定留给调用方)

    参数:
      img    PIL Image
      region 可选 (x1, y1, x2, y2); None=整图
      top    返回前 top 名
      merge  True(默认) 同色系合并: 每种色系一条(rgb=加权平均, count=求和)
             例: 灰字白底 -> [(灰均值, 灰像素数, '灰'), (白均值, 白像素数, '白'), ...]
             False 输出未合并的量化桶(可能同色系多档, 如多个深浅不同的灰)

    返回: [(rgb, count, 色系名称), ...] 从多到少
    """
    if region is not None:
        img = img.crop(region)
    if img.width < 4 or img.height < 4:
        return []
    small = img.convert("RGB").resize((30, 30))            # 降采样, 主色占比更稳
    counts = {}
    for px in small.getdata():
        q = ((px[0] // 40) * 40, (px[1] // 40) * 40, (px[2] // 40) * 40)
        counts[q] = counts.get(q, 0) + 1
    buckets = sorted(counts.items(), key=lambda kv: -kv[1])[:top]
    if not merge:
        return [(rgb, c, _name_color(rgb)) for rgb, c in buckets]
    # 合并同色系: rgb 按 count 加权平均, count 求和, 按合并后 count 降序
    merged = {}
    for rgb, c in buckets:
        name = _name_color(rgb)
        if name not in merged:
            merged[name] = [0, 0, 0, 0]          # r,g,b,count
        w = merged[name]
        w[0] += rgb[0] * c; w[1] += rgb[1] * c; w[2] += rgb[2] * c
        w[3] += c
    out = []
    for name, w in merged.items():
        rgb_avg = (w[0] // w[3], w[1] // w[3], w[2] // w[3])
        out.append((rgb_avg, w[3], name))
    out.sort(key=lambda t: -t[1])
    return out[:top]


def gray_on_gray(sbox, box=None):
    """时间点位判定: 文字框前两主色应为【灰 + 浅色/白】(灰字浅底), 前两主色均在{灰,白}内且至少一个灰
    兼容 灰字白底 / 白字灰底 / 灰字灰底; 黑字白底(文章点位特征)不误收
    与 classify_items 配套; sbox 相对截图坐标 + box 区域左上角 -> 屏幕绝对区域
    返回 True/False; 取色失败返回 None(不阻断, 语义同原 _region_grayish)
    """
    if not sbox or len(sbox) < 4 or box is None:
        return None
    try:
        from PIL import ImageGrab
        full = ImageGrab.grab().convert("RGB")
        cols = color_sort(full, region=(
            box[0] + min(p[0] for p in sbox), box[1] + min(p[1] for p in sbox),
            box[0] + max(p[0] for p in sbox), box[1] + max(p[1] for p in sbox)))
    except Exception:
        return None
    if not cols:
        return None
    colset = {c for _, _, c in cols[:2]}
    return bool(colset.issubset({"灰", "白"}) and colset & {"灰"})

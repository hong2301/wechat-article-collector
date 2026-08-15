# -*- coding: utf-8 -*-
"""core.image_ocr: OCR / 截图 / 文字亮度颜色 / WebP 转码
依赖: core.utils(log), PIL, rapidocr(runtime)
"""
import re
import threading

from .utils import log


# ================= OCR（rapidocr_onnxruntime，参考旧项目） =================
_ocr_engine = None
_ocr_lock = threading.Lock()

# 时间格式正则（按时间从近到远）:
#   星期几/周X/礼拜X、今天/昨天/前天、x天前/x小时前/x分钟前
#   年月日 2026-08-05（非今年）、月日 8月21日 或 08-05（今年）
TIME_PATTERNS = (
    r"星期[一二三四五六日天]|周[一二三四五六日]|礼拜[一二三四五六日天]",
    r"今天|昨天|前天",
    r"\d+\s*天前",
    r"\d+\s*小时前",
    r"\d+\s*分钟前",
    r"\d{4}[-/. ]\d{1,2}[-/. ]\d{1,2}",   # 2026-08-05 / 2026/8/5
    r"\d{1,2}月\d{1,2}日?",                # 8月21日 / 8月21
    r"\d{1,2}[-/]\d{1,2}",                  # 08-05 / 8/5（今年月日）
)
TIME_RE = re.compile("|".join(f"({p})" for p in TIME_PATTERNS))


# 星期汉字 -> 0-6（周一=0）



def get_ocr_engine():
    """懒加载 OCR 引擎（RapidOCR，线程安全）"""
    global _ocr_engine
    with _ocr_lock:
        if _ocr_engine is None:
            from rapidocr_onnxruntime import RapidOCR
            log("正在加载 OCR 引擎 ...")
            _ocr_engine = RapidOCR()
            log("OCR 引擎加载完成")
        return _ocr_engine


def screenshot_region(box, path):
    """截取屏幕指定区域并保存；box=(x1,y1,x2,y2)，返回 PIL 图"""
    from PIL import ImageGrab
    img = ImageGrab.grab(bbox=(int(box[0]), int(box[1]), int(box[2]), int(box[3])))
    img.save(path)
    return img


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


def ocr_region(box):
    """对屏幕区域 box=(x1,y1,x2,y2) 做 OCR，返回 [(中心x, 中心y, 文本, score, sbox, brightness), ...]
    坐标已换算为屏幕坐标（OCR 结果 + 截图区域偏移）
    brightness: 文字区域平均亮度(深色标题≈25, 灰色时间文本≈160)"""
    from PIL import Image
    engine = get_ocr_engine()
    # 截图到内存
    from PIL import ImageGrab
    img = ImageGrab.grab(bbox=(int(box[0]), int(box[1]), int(box[2]), int(box[3])))
    import io as _io
    buf = _io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    result, _ = engine(buf.read())
    ox, oy = int(box[0]), int(box[1])   # 截图区域偏移
    items = []
    if result:
        for box_pts, text, score in result:
            xs = [p[0] for p in box_pts]
            ys = [p[1] for p in box_pts]
            cx = int(sum(xs) / len(xs)) + ox   # 中心 x + 偏移
            cy = int(sum(ys) / len(ys)) + oy
            # 保留整个文本框（4 个点，已换算为屏幕绝对坐标）
            sbox = [(int(p[0]) + ox, int(p[1]) + oy) for p in box_pts]
            # 按文字框从截图裁剪, 计算文字亮度
            try:
                crop = img.crop((min(xs), min(ys), max(xs), max(ys)))
                brightness = _text_brightness(crop)
            except Exception:
                brightness = 255.0
            items.append((cx, cy, text, score, sbox, brightness))
    return items


def _pil_to_b64(img, scale=None, quality=None):
    """PIL 图片转 base64 WebP（无损，最小体积且最清晰）；失败返回 None"""
    try:
        import io
        import base64
        from PIL import Image as _PILImage
        if scale and scale < 1.0:
            w, h = img.size
            img = img.resize((max(1, int(w * scale)), max(1, int(h * scale))), _PILImage.LANCZOS)
        if img.mode != "RGB":
            img = img.convert("RGB")
        buf = io.BytesIO()
        img.save(buf, format="WEBP", lossless=True, method=6)
        return "data:image/webp;base64," + base64.b64encode(buf.getvalue()).decode("ascii")
    except Exception:
        return None


def capture_region_base64(box, scale=None, quality=70):
    """截取屏幕区域 box=(x1,y1,x2,y2) 并转为 base64 WebP(无损最小)字符串；失败返回 None
    scale: 缩放比例(<1 缩小, 如 0.75), None=不缩放"""
    try:
        from PIL import ImageGrab
        img = ImageGrab.grab(bbox=(int(box[0]), int(box[1]), int(box[2]), int(box[3])))
        return _pil_to_b64(img, scale=scale, quality=quality)
    except Exception as e:
        log(f"截图失败(box={box}, scale={scale}): {e}")
        return None


def ocr_img(img):
    """对 PIL 图片做 OCR，返回 [(中心x, 中心y, 文本, score, sbox, brightness), ...]
    sbox 为图片内相对坐标; brightness 为文字区域亮度(深色标题<100, 灰色时间文本>=100)"""
    try:
        import io as _io
        buf = _io.BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)
        result, _ = get_ocr_engine()(buf.read())
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


def find_read_in_img(img):
    """在图片中找包含'阅读'的字段，返回 (中心x, 中心y, 文本, 亮度) 或 None"""
    for cx, cy, text, score, sbox, brightness in ocr_img(img):
        if "阅读" in text:
            return (cx, cy, text, brightness)
    return None


def find_time_items(items):
    """从 OCR 结果中筛选包含时间的条目，返回 [(中心x, 中心y, 文本), ...]
    按文字颜色过滤：只保留灰色文字(时间文本, 亮度>=100), 深色标题(亮度<100)排除；
    点击时的 x 由点位12（文章x轴线）决定，y 用本结果中心 y"""
    found = []
    for cx, cy, text, score, sbox, brightness in items:
        if TIME_RE.search(text):
            if brightness >= 100:
                found.append((cx, cy, text))
            else:
                log(f"颜色过滤: 排除深色[{text}] 亮度={brightness:.0f}")
    return found


def extract_reads(text):
    """从时间点位文本中提取阅读数，提取不到返回 -1
    如: '星期四阅读821赞4' -> 821，'昨天 阅读 117' -> 117，'昨天' -> -1"""
    m = re.search(r"阅读\s*(\d+)", text or "")
    return int(m.group(1)) if m else -1


def extract_likes(text):
    """从时间点位文本中提取点赞数，提取不到返回 -1
    如: '星期四阅读821赞4' -> 4，'昨天 阅读 117 赞 6' -> 6，'昨天' -> -1"""
    m = re.search(r"赞\s*(\d+)", text or "")
    return int(m.group(1)) if m else -1



__all__ = ["TIME_PATTERNS", "TIME_RE", "_ocr_engine", "_ocr_lock",
           "get_ocr_engine", "screenshot_region", "_text_brightness", "ocr_region",
           "_pil_to_b64", "capture_region_base64", "ocr_img", "find_read_in_img",
           "find_time_items", "extract_reads", "extract_likes"]

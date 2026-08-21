# -*- coding: utf-8 -*-
"""backend.app.services.ocr: OCR 识别模块（精简版）

参考原 main.py 使用的 RapidOCR 方案，只保留识别能力。
依赖: rapidocr_onnxruntime + Pillow

能力:
  init()   初始化/预加载 OCR 引擎(幂等)
  ocr(img) 输入 PIL 图片, 输出 OCR 识别结果
"""

import io
import threading

_ocr_engine = None
_ocr_lock = threading.Lock()


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


__all__ = ["init", "ocr"]
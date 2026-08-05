# -*- coding: utf-8 -*-
"""
OCR 文章采集循环测试脚本
直接调用 main.py 的 OCR 识别与采集循环逻辑，不打开 GUI、不真实点击屏幕。
用法: python test_ocr.py
"""

import threading
import time

import main


class MockApp:
    """模拟 App 上下文（只提供 _collect_articles 用到的 stop_event / _sleep）"""

    def __init__(self):
        self.stop_event = threading.Event()
        self.calls = []

    def _sleep(self, seconds):
        """记录请求的等待时长，加速返回"""
        self.calls.append(("sleep", seconds))
        time.sleep(0.01)
        return False


def test_ocr_region():
    """测试1：用点位5/7圈出的区域做真实截屏 OCR，识别时间卡片"""
    pts = {p[0]: p for p in main.load_points()}
    p5, p7 = pts.get(5), pts.get(7)
    if not p5 or not p7:
        print("[测试1] 缺少点位5/7，无法测试 OCR 区域")
        return None
    x1, y1 = int(p5[2]), int(p5[3])
    x2, y2 = int(p7[2]), int(p7[3])
    box = (min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2))
    print(f"[测试1] 截图区域: {box}")
    items = main.ocr_region(box)
    print(f"[测试1] OCR 条目数: {len(items)}")
    cards = main.find_time_items(items)
    print(f"[测试1] 识别到时间卡片: {len(cards)} 个")
    for cx, cy, text in cards:
        print(f"    (中心 {cx},{cy}) {text}")
    return box, cards


def test_collect_loop():
    """测试2：直接调用 main.App._collect_articles（mock 点击），验证循环配对"""
    print("\n[测试2] 文章采集循环（mock 点击，不真实操作屏幕）")
    mock = MockApp()
    main.mouse_click = lambda x, y: mock.calls.append(("CLICK", x, y))
    main.ctrl_key = lambda l: mock.calls.append(("CTRL", l))
    pts = {p[0]: p for p in main.load_points()}
    ok = main.App._collect_articles(mock, pts)
    clicks = [c for c in mock.calls if c[0] == "CLICK"]
    ctrls = [c for c in mock.calls if c[0] == "CTRL"]
    sleeps = [c[1] for c in mock.calls if c[0] == "sleep"]
    print(f"[测试2] 返回: {ok}")
    print(f"[测试2] 点击 {len(clicks)} 次 / Ctrl+W {len(ctrls)} 次 / 配对: {len(clicks) == len(ctrls)}")
    print(f"[测试2] 点击后等待5秒: {5 in sleeps}")
    print("[测试2] 操作序列:")
    for c in mock.calls:
        print("    ", c)


if __name__ == "__main__":
    main.enable_dpi_awareness()
    test_ocr_region()
    test_collect_loop()

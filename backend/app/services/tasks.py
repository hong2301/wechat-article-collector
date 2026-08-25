# -*- coding: utf-8 -*-
"""backend.app.services.tasks: 任务组合模块

用途: 把 computer(电脑交互原语) 等底层模块按业务步骤组合成"任务函数"。

规则:
  * 本模块只放组合逻辑, 不放新的 Win32/输入原语(那些在 computer.py)。
  * 新增任务函数前需先经过确认。
  * 辅助工具在 common.py, 运行状态在 robot.py, 主函数集中在本模块。
"""

import ctypes
import hashlib
from concurrent.futures import ThreadPoolExecutor
from ctypes import wintypes as wt
from datetime import datetime
import threading
import time
import requests as _requests
from PIL import Image

from . import computer as pc
from . import ocr as ocr_service
from .common import (_read_point, _finish, _save_reads,
                     _extract_read_from_items, wait_page_stable)
from .robot import (request_stop, clear_stop, stop_requested,
                    bind_tasks_echo, tasks_echo)
from ..database import get_conn
from .doubao_api import recognize_interact as doubao_recognize_interact
from .importer import extract_art_biz
from .fetch_article import fetch_article, save_article_html

# 模块加载时启用 DPI 感知(进程级, 幂等): 确保所有点位坐标用物理像素, 避免缩放偏移
pc.enable_dpi_awareness()

WECHAT_MAIN = "Weixin.exe"          # 微信主界面进程
WECHAT_APPEX = "WeChatAppEx.exe"    # 微信小程序/外部App容器进程

# 采集器(前端)相关
APP_TITLE = "微信公众号采集器"      # 前端窗口标题(打包后名称)
APP_EXE = "electron.exe"           # 前端壳进程

# 后台异步执行器: 网络类任务(元信息抓取/保存HTML)丢线程池, 不阻塞主采集流程
_bg_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="bg")
_bg_futures = []          # 已提交的后台 future 集合(完成后移除)
_bg_futures_lock = threading.Lock()


def _submit_bg(fn, *args, **kwargs):
    """提交后台任务并记录 future(供 wait_bg_done 等待); 完成后自动移除"""
    f = _bg_executor.submit(fn, *args, **kwargs)
    with _bg_futures_lock:
        _bg_futures.append(f)
    f.add_done_callback(lambda _f: _done_bg(_f))
    return f


def _done_bg(f):
    with _bg_futures_lock:
        try:
            _bg_futures.remove(f)
        except ValueError:
            pass


def wait_bg_done(timeout=120):
    """等待本次所有后台异步任务完成(自动停止时调用, 确保写表/保存Html/4指标/阅读数OCR收尾)
    主动停止不调用; 只等已提交的 future, executor 保持可复用(不 shutdown)"""
    from concurrent.futures import wait
    with _bg_futures_lock:
        fs = list(_bg_futures)
    if fs:
        try:
            wait(fs, timeout=timeout)
        except Exception:
            pass


def init_wechat_window(window_split=False):
    """微信窗口初始化: 确保 WeChatAppEx 被关闭、Weixin 存在且在左半屏。
    参数:
      window_split 是否窗口分离(默认否); 仅在 True 时允许"宽度不合法→点击点位9重跑"
    步骤:
      1) 找 WeChatAppEx.exe 窗口, 有则直接关闭, 无则跳过
      2) 找 Weixin.exe 窗口, 无则唤出
      3) 保证已有 Weixin.exe 窗口
      4) 移动到屏幕左半边, 并校验是否就位
      5) 若宽度/位置不合法: window_split=True 时点击点位9(触发窗口布局)后重跑;
         否则直接返回 False
    返回: (成功?, 说明文本)。
      成功(Weixin 在左半边)返回 (True, 文本);
      失败返回 (False, 文本), 交由后续流程处理。
    """
    logs = []

    def once():
        # 单次初始化; 返回 (成功?, 本回文本)
        _logs = []
        # 1) 关闭 WeChatAppEx(仅可见窗口)
        appex = pc.find_windows(exe=WECHAT_APPEX, visible_only=True)
        for hwnd, _t, _p, _v in appex:
            pc.close_window(hwnd)
            _logs.append(f"已关闭 WeChatAppEx 窗口 #{hwnd}")
        if not appex:
            _logs.append("无可见 WeChatAppEx 窗口, 跳过")

        # 2) 找 Weixin, 无则唤出
        weixin = pc.find_windows(exe=WECHAT_MAIN)
        if not weixin:
            found = pc.find_windows(exe=WECHAT_MAIN, visible_only=False)
            if not found:
                _logs.append("未找到 Weixin.exe 窗口")
                return False, "未找到 Weixin 窗口"
            pc.show_window(found[0][0])
            _logs.append(f"已唤出 Weixin 窗口 #{found[0][0]}")
            weixin = pc.find_windows(exe=WECHAT_MAIN)
        else:
            _logs.append(f"Weixin 窗口已存在 #{weixin[0][0]}")
        if not weixin:
            return False, "Weixin 窗口仍未识别"

        hwnd = weixin[0][0]
        u32_sm = pc._u32()
        sw = u32_sm.GetSystemMetrics(pc.SM_CXSCREEN)
        sh = u32_sm.GetSystemMetrics(pc.SM_CYSCREEN)
        pc.move_window(hwnd, 0, 0, sw // 2, sh)

        # 4) 校验是否就位左半屏
        r = wt.RECT()
        pc._u32().GetWindowRect(hwnd, ctypes.byref(r))
        if abs(r.left) > 2 or abs((r.right - r.left) - sw // 2) > 0:
            return False, "Weixin 未就位左半屏(宽度或位置不合法)"
        return True, "Weixin 窗口已就位左半屏"

    # 第一次
    ok, info = once()
    logs.append(info)
    if ok:
        return True, "; ".join(logs)

    # 宽度/位置不合法: 仅 window_split=True 时才点击点位9后重跑, 否则直接 Fail
    if not window_split:
        return False, "; ".join(logs)

    try:
        conn = get_conn()
        try:
            row = conn.execute(
                "SELECT id, name, x, y FROM points WHERE id=9").fetchone()
        finally:
            conn.close()
        px = py = None
        if row:
            try:
                px = int(float(row["x"]))
                py = int(float(row["y"]))
            except (TypeError, ValueError):
                px = py = None
        if px is not None:
            logs.append(f"尝试点击点位9({px},{py})")
            pc.mouse_click(px, py)
            time.sleep(0.2)      # 点击点位9后等待, 让窗口布局生效
        else:
            logs.append("无点位9, 跳过点击")
    except Exception:
        logs.append("读取点位9失败")

    ok2, info2 = once()
    logs.append(info2)
    return ok2, "; ".join(logs)


def search_window_init(window_split=False):
    """搜一搜窗口初始化(坐标采集流程)。
    前提: 必须满足微信窗口初始化 + 采集器窗口初始化成功的结果
    参数:
      window_split 是否窗口分离(默认否); 为真时点击点位12后插入: 等0.3s → 点击点位13
    步骤:
      0) 前置判定: Weixin可见且在左半屏 + 采集器可见且在右半屏; 不符合直接返回 False
      1) 点击点位11(搜索框) → 等0.2s → 输入1 → 等0.1s → 全选删除 → 等0.2s
      2) 点击点位12(搜索网络) → 等0.5s
      2b)(window_split) 等0.3s → 点击点位13(窗口分离按钮)
      3) 查找可见 WeChatAppEx 窗口
         - 无 → 失败返回 False
         - 有 → 检查是否在屏幕左半边
             - 是 → 完成返回 True
             - 否 → 移动到左半边 → 再检查 → 合格 True / 不合格 False
    返回: (成功?, 说明文本)
    """
    logs = []

    # 0) 前置判定: 微信初始化(Weixin左半屏) + 采集器初始化(采集器右半屏)必须已满足
    u32_sm = pc._u32()
    sw = u32_sm.GetSystemMetrics(pc.SM_CXSCREEN)
    sh = u32_sm.GetSystemMetrics(pc.SM_CYSCREEN)
    half = sw // 2

    weixin = pc.find_windows(exe=WECHAT_MAIN, visible_only=True)
    if not weixin:
        logs.append("前置不满足: 无可见 Weixin 窗口(微信窗口初始化未完成)")
        return False, "; ".join(logs)
    r = wt.RECT()
    pc._u32().GetWindowRect(weixin[0][0], ctypes.byref(r))
    if abs(r.left) > 2 or abs((r.right - r.left) - half) > 0:
        logs.append("前置不满足: Weixin 不在左半屏(微信窗口初始化未完成)")
        return False, "; ".join(logs)

    appwin = pc.find_windows(title=APP_TITLE, visible_only=True)
    if not appwin:
        appwin = pc.find_windows(exe=APP_EXE, visible_only=True)
    if not appwin:
        logs.append("前置不满足: 未找到采集器窗口(采集器窗口初始化未完成)")
        return False, "; ".join(logs)
    r2 = wt.RECT()
    pc._u32().GetWindowRect(appwin[0][0], ctypes.byref(r2))
    if abs(r2.left - half) > 2 or abs((r2.right - r2.left) - half) > 0:
        logs.append("前置不满足: 采集器不在右半屏(采集器窗口初始化未完成)")
        return False, "; ".join(logs)
    logs.append("前置满足: 微信左半屏 + 采集器右半屏")

    # 1) 点位11: 点击 → 输入1 → 全选删除
    p11 = _read_point(11)
    if p11:
        pc.mouse_click(p11[0], p11[1])
        logs.append(f"点击点位11({p11[0]},{p11[1]})")
        time.sleep(0.1)
        pc.type_text("1")
        time.sleep(0.1)
        pc.ctrl_key("A")
        time.sleep(0.1)
        pc.key_press(pc.VK_DELETE)
        time.sleep(0.2)
    else:
        logs.append("缺少点位11")
        return False, "; ".join(logs)

    # 2) 点位12: 点击搜索网络
    p12 = _read_point(12)
    if p12:
        pc.mouse_click(p12[0], p12[1])
        logs.append(f"点击点位12({p12[0]},{p12[1]})")
        time.sleep(0.2)
    else:
        logs.append("缺少点位12")
        return False, "; ".join(logs)

    # 2b) 窗口分离: 点击点位13
    if window_split:
        p13 = _read_point(13)
        if p13:
            pc.mouse_click(p13[0], p13[1])
            logs.append(f"点击点位13({p13[0]},{p13[1]})")
            time.sleep(0.3)
        else:
            logs.append("缺少点位13")
            return False, "; ".join(logs)

    # 3) 查找可见 WeChatAppEx 窗口
    appex = pc.find_windows(exe=WECHAT_APPEX, visible_only=True)
    if not appex:
        logs.append("未找到可见 WeChatAppEx 窗口")
        return False, "; ".join(logs)

    hwnd = appex[0][0]
    u32_sm = pc._u32()
    sw = u32_sm.GetSystemMetrics(pc.SM_CXSCREEN)
    sh = u32_sm.GetSystemMetrics(pc.SM_CYSCREEN)

    def check():
        r = wt.RECT()
        pc._u32().GetWindowRect(hwnd, ctypes.byref(r))
        return abs(r.left) <= 2 and abs((r.right - r.left) - sw // 2) <= 0

    # 3a) 已在左半屏 -> 完成
    if check():
        logs.append("WeChatAppEx 已在左半屏")
        return True, "; ".join(logs)

    # 3b) 不在左半屏 -> 移动到左半边
    pc.move_window(hwnd, 0, 0, sw // 2, sh)
    logs.append("WeChatAppEx 已移到左半屏")
    if check():
        return True, "; ".join(logs)

    logs.append("WeChatAppEx 未就位左半屏")
    return False, "; ".join(logs)


def search_query(link=""):
    """搜一搜窗口查询。
    前提: 搜一搜窗口初始化(search_window_init)成功。
    参数:
      link 要搜索/输入的链接
    步骤:
      1) 检查可见 WeChatAppEx 窗口是否在左半屏; 不在/无则返回 False
      2) 点击点位14(查询输入框) → 等0.1s → 输入链接 → 等0.1s → 回车
    返回: (成功?, 说明文本)
    """
    logs = []

    # 1) 检查可见 WeChatAppEx 在左半屏
    appex = pc.find_windows(exe=WECHAT_APPEX, visible_only=True)
    if not appex:
        logs.append("未找到可见 WeChatAppEx 窗口")
        return False, "; ".join(logs)
    u32_sm = pc._u32()
    sw = u32_sm.GetSystemMetrics(pc.SM_CXSCREEN)
    r = wt.RECT()
    pc._u32().GetWindowRect(appex[0][0], ctypes.byref(r))
    if abs(r.left) > 2 or abs((r.right - r.left) - sw // 2) > 0:
        logs.append("WeChatAppEx 不在左半屏")
        return False, "; ".join(logs)
    logs.append("WeChatAppEx 已在左半屏")

    # 2) 点击点位14 → 剪贴板粘贴链接 → 回车
    p14 = _read_point(14)
    if not p14:
        logs.append("缺少点位14")
        return False, "; ".join(logs)
    pc.mouse_click(p14[0], p14[1])
    logs.append(f"点击点位14({p14[0]},{p14[1]})")
    time.sleep(0.1)
    if not pc.set_clipboard_text(link):
        logs.append("剪贴板写入失败")
        return False, "; ".join(logs)
    pc.ctrl_key("V")       # 粘贴
    logs.append("剪贴板粘贴链接")
    time.sleep(0.3)
    pc.key_press(pc.VK_RETURN)
    logs.append("按回车")
    return True, "; ".join(logs)


def article_list_wait_stable(date_start="", date_end="", biz="",
                             capture_4metrics=False, capture_read=False,
                             save_html=False, save_dir=""):
    """文章列表识别循环: 进入 while 循环, 每次循环第一步检查页面稳定。
    前提: 搜一搜查询(search_query)已加载出公众号链接(本函数不判定, 但依赖其结果)。
    参数:
      date_start, date_end 采集时间范围(YYYY-MM-DD); 空字符串=全部(不限)
      biz              所属公众号 biz 代码(点击文章后数据采集用)
      capture_4metrics 是否采集4指标
      capture_read     是否采集阅读数量
      save_html        是否保存文章为本地HTML(含图片)
      save_dir         保存HTML根目录(空=默认D:/article_data)
    逻辑:
      while 循环(目前为占位, 后续补结束条件):
        1) 检查点位15-16区域页面是否稳定(失败不退出, 有兜底)
        2) 截图+OCR+分类得到 classified
        3) 截断处理: 若 classified 第一个点位不是时间点位,
           从上一轮的 classified 末尾向前找第一个时间点位借来, 插入本轮顶部(序号0)
           (第一轮无上一轮, 跳过)
        4) 日志输出本轮点位详细(序号/类型/文本/data)
    返回: (成功?, 说明文本)
    """
    logs = []

    p15 = _read_point(15)
    p16 = _read_point(16)
    if not p15 or not p16:
        logs.append("缺少点位15/16")
        return False, "; ".join(logs)
    x1, y1 = p15
    x2, y2 = p16
    logs.append(f"列表区域({x1},{y1})-({x2},{y2})")

    # 循环前: 页面稳定判断(100次机会, 每0.1s, 连续20次相同算稳定)
    ok0, info0 = wait_page_stable(x1, y1, x2, y2, same_need=20, timeout=100, interval=0.1)
    if not ok0:
        logs.append(f"初始页面未稳定(20次未达成): {info0}")
        return False, "; ".join(logs)
    logs.append(f"初始页面稳定: {info0}")

    # 稳定后: 截图点位15-16 => OCR => 识别"文章"标记(灰色系深色文字)并点击
    try:
        shot_path, _b64 = pc.screenshot(x1, y1, x2, y2, img_format="png")
        items = ocr_service.ocr(Image.open(shot_path))
        clicked = False
        for cx, cy, text, score, sbox, brightness in items:
            if not text or not text.strip():
                continue
            # 文章标记: 灰色系深色文字 且 文本含"文章"
            if "文章" not in text:
                continue
            gray = ocr_service._region_grayish(sbox, (x1, y1))
            if gray is True:
                # 点击坐标: sbox是截图内相对坐标, 加区域左上角(x1,y1)偏移成屏幕坐标, 取box中心
                xs = [p[0] + x1 for p in sbox]
                ys = [p[1] + y1 for p in sbox]
                click_x = int(sum(xs) / len(xs))
                click_y = int(sum(ys) / len(ys))
                logs.append(f"识别文章标记: {text!r} @({click_x},{click_y})")
                tasks_echo(f"识别文章标记: {text!r} @({click_x},{click_y})")
                pc.mouse_click(click_x, click_y)
                clicked = True
                break
        if not clicked:
            logs.append("未识别到文章标记(灰字), 跳过点击")
            tasks_echo("未识别到文章标记(灰字), 跳过点击")
    except Exception as e:
        logs.append(f"文章标记识别失败: {e}")

    # while 循环(停止条件: 连续3次截图相同 = 无更多文章)
    prev_classified = None   # 上一轮的 classified(用于截断借时间)
    prev_shot_hash = None    # 上一轮截图md5(无更多文章判定)
    same_shot = 0            # 连续相同截图次数
    date_out_count = 0       # 连续在日期范围之后次数(有日期范围时)
    loop_n = 0

    def echo(msg):
        """本轮日志: 存 logs 并实时转发(打印 + 后端钩子)"""
        logs.append(msg)
        tasks_echo(msg)

    while True:
        if stop_requested():
            echo("收到停止请求, 退出识别循环")
            break
        loop_n += 1
        echo(f"--- 列表循环 {loop_n} ---")

        # 每次循环第一步: 页面稳定判断(失败不退出, 有兜底; 连续10次相同)
        ok, info = wait_page_stable(x1, y1, x2, y2, same_need=10)
        if ok:
            echo(f"第{loop_n}轮页面稳定: {info}")
        else:
            echo(f"第{loop_n}轮页面未稳定(继续, 用兜底): {info} ")

        # 流程一: 截图 -> OCR(得到原始识别数据)
        shot_path, _b64 = pc.screenshot(x1, y1, x2, y2, img_format="png")
        if not shot_path:
            echo(f"第{loop_n}轮截图失败")
            return False, f"第{loop_n}轮截图失败"
        try:
            img = Image.open(shot_path)
            items = ocr_service.ocr(img)
        except Exception as e:
            echo(f"第{loop_n}轮OCR失败: {e}")
            return False, f"第{loop_n}轮OCR失败: {e}"

        # 流程一点五: 检测"余下"加载更多按钮(灰底蓝字) -> 有则点击后重新截图+OCR
        try:
            btn = None
            for cx, cy, text, score, sbox, brightness in items:
                if not text or "余下" not in text:
                    continue
                if ocr_service.text_color(sbox, (x1, y1)) == "blue":
                    xs = [p[0] + x1 for p in sbox]
                    ys = [p[1] + y1 for p in sbox]
                    btn = (int(sum(xs) / len(xs)), int(sum(ys) / len(ys)), text)
                    break
            if btn:
                echo(f"识别到'余下'加载更多按钮: {btn[2]!r} @({btn[0]},{btn[1]}), 点击后重新截图")
                pc.mouse_click(btn[0], btn[1])
                time.sleep(0.3)
                # 点击后: 重新截图+OCR(替换本轮items, 继续下面的分类)
                shot_path2, _b64 = pc.screenshot(x1, y1, x2, y2, img_format="png")
                if shot_path2:
                    items = ocr_service.ocr(Image.open(shot_path2))
                    echo("余下按钮点击后已重新截图OCR")
        except Exception as e:
            echo(f"第{loop_n}轮余下按钮检测失败: {e}")

        # 流程二: 分类 -> 截断借时间 -> 配对时间
        try:
            classified = ocr_service.classify_items(items, box=(x1, y1))
        except Exception as e:
            echo(f"第{loop_n}轮分类失败: {e}")
            return False, f"第{loop_n}轮分类失败: {e}"

        # 截断处理: 本轮第一个点位不是时间点位 -> 向上一轮末尾借时间点位(序号0)
        if classified and prev_classified is not None and classified[0][1] != "time":
            borrowed = None
            # 从上一轮 classify 末尾往前找第一个时间点位
            for p in reversed(prev_classified):
                if p[1] == "time":
                    borrowed = p
                    break
            if borrowed is not None:
                # 把借来的时间点位以序号0插入本轮顶部
                borrowed_item = (0, borrowed[1], borrowed[2], borrowed[3], borrowed[4])
                classified.insert(0, borrowed_item)
                echo("截断: 从上一轮借时间点位插入本轮顶部(序号0)")

        # 配对时间: 按顺序遍历, 每个文章点位填入其前面最近的时间点位日期
        cur_t = None
        for p in classified:
            if p[1] == "time" and p[4].get("time"):
                cur_t = p[4]["time"]
            elif p[1] == "article":
                p[4]["time"] = cur_t   # 填配对时间(可能是None, 即无可用时间)

        # 日志输出本轮点位详细
        n_time = sum(1 for p in classified if p[1] == "time")
        n_article = sum(1 for p in classified if p[1] == "article")
        echo(f"第{loop_n}轮识别点位 {len(classified)} 个"
             f"(时间{n_time}/文章{n_article})")
        for seq, ptyp, ptxt, _pbox, pdata in classified:
            if ptyp == "time":
                echo(f"  时间点位[{seq}] {ptxt!r} 日期={pdata.get('time')}")
            else:
                echo(f"  文章点位[{seq}] {ptxt!r}"
                     f" 阅读={pdata.get('reads')} 赞={pdata.get('likes')}"
                     f" 配对时间={pdata.get('time')}")

        prev_classified = classified

        # 遍历文章点位: 时间在日期范围内(或时间为空=不确定) -> 点击文章点位
        # 点击坐标: (box最小x, box中心y), 用电脑控制模块 mouse_click
        s_d = date_start.replace("-", "/") if date_start else None
        e_d = date_end.replace("-", "/") if date_end else None
        for seq, ptyp, ptxt, pbox, pdata in classified:
            if ptyp != "article":
                continue
            t = pdata.get("time")
            should_click = False
            if not t:
                should_click = True              # 时间为空(不确定) -> 点击
            elif s_d and t < s_d or e_d and t > e_d:
                should_click = False             # 时间在范围外 -> 跳过
            else:
                should_click = True              # 在范围内 -> 点击
            if not should_click:
                echo(f"  跳过文章[{seq}] {ptxt!r} 时间{t} 不在范围")
                continue
            # box 四点取 最小x + 中心y(按y序文章中心)
            xs = [p[0] for p in pbox]
            ys = [p[1] for p in pbox]
            click_x = min(xs)
            click_y = int(sum(ys) / len(ys))
            echo(f"  点击文章[{seq}] {ptxt!r} 时间{t} @({click_x},{click_y})")
            pc.mouse_click(click_x, click_y)
            time.sleep(0.3)   # 点击后等待页面响应

            # 点击后: 采集该文章数据(获取链接+写文章表)
            ok_c, text_c = article_data_collect(
                collect_type=1, capture_4metrics=capture_4metrics,
                capture_read=capture_read, save_html=save_html, save_dir=save_dir, biz=biz,
                list_reads=pdata.get("reads"), list_likes=pdata.get("likes"))
            echo(f"  文章数据采集: {'成功' if ok_c else '失败'} | {text_c}")
            time.sleep(0.5)   # 采集完成间隔

        # 日期范围判断(有日期范围时才启用; 全部=空串跳过, 靠三次OCR兜底) 放在三次OCR相同判断上面
        if date_start or date_end:
            # 收集本轮 time 点位的标准日期(yyyy/mm/dd), 去除 None;
            # 排除序号0(=截断借来, 属于上一张图, 不参与本轮判定)
            times = [p[4].get("time") for p in classified
                     if p[0] != 0 and p[1] == "time" and p[4].get("time")]
            # 范围起止转 yyyy/mm/dd 便于字符串比较
            s = date_start.replace("-", "/") if date_start else None
            e = date_end.replace("-", "/") if date_end else None
            if times and any(not (s and t < s) and not (e and t > e) for t in times):
                # 存在范围内 -> 重置计数, 继续
                date_out_count = 0
                echo(f"第{loop_n}轮: 存在范围内文章, 继续")
            elif times:
                # 全不在范围内: 时间若比范围早(已滚过范围) -> 累计停止
                if any(s and t < s for t in times):
                    date_out_count = date_out_count + 1
                    echo(f"第{loop_n}轮: 时间点位已过日期范围(比范围早)({date_out_count}/2)")
                    if date_out_count >= 2:
                        echo("连续2次已过日期范围, 停止")
                        return False, "连续2次已过日期范围"
                else:
                    # 时间比范围晚(顶部还有更新的, 未滚到范围) -> 继续滚动
                    date_out_count = 0
                    echo(f"第{loop_n}轮: 时间点位在日期范围之后(未到范围), 继续")
            else:
                date_out_count = 0       # 本轮无时间点位, 不判定, 重置

        # 停止条件: 连续3轮OCR列表截图完全相同 -> 无更多文章, 停止(返回True)
        # 注意: 独立重新截图列表区域, 避免被各采集步骤的截图覆盖污染
        cur_shot_hash = None
        try:
            _sp, _ = pc.screenshot(x1, y1, x2, y2, img_format="png")
            if _sp:
                with open(_sp, "rb") as _f:
                    cur_shot_hash = hashlib.md5(_f.read()).hexdigest()
        except Exception:
            cur_shot_hash = None
        if prev_shot_hash == cur_shot_hash:
            same_shot = same_shot + 1
        else:
            same_shot = 1
        prev_shot_hash = cur_shot_hash
        if same_shot >= 3:
            echo(f"第{loop_n}轮: 连续3次列表截图相同, 判定无更多文章, 停止")
            return True, "无更多文章"

        # 滚动: 鼠标移到点位15, 触发滚动配置 id=3(向下)
        try:
            conn = get_conn()
            try:
                row = conn.execute("SELECT distance, direction FROM scrolls WHERE id=3").fetchone()
            finally:
                conn.close()
            s_dist = int(float(row["distance"])) if row else 0
            s_dir = row["direction"] if row else "down"
        except Exception:
            s_dist, s_dir = 0, "down"
        if s_dist > 0:
            pc.scroll(x1, y1, s_dist, direction=s_dir)
            echo(f"第{loop_n}轮末尾: 在点位15({x1},{y1})向下滚动 {s_dist}px")
        else:
            echo("滚动配置3无效, 跳过滚动")

    return True, "; ".join(logs)


def init_app_window():
    """采集器窗口初始化: 确保前端窗口(微信公众号采集器)在右半屏。
    前提: 调用本函数前窗口已被唤起(本函数不负责唤起)。
    步骤:
      1) 查找"微信公众号采集器"窗口；找不到则返回 False
      2) 检测是否在屏幕右半边；是则返回 True
      3) 否则移动到右半边，返回 True
    失败(找不到窗口/移动异常)返回 False。
    返回: (成功?, 说明文本)。
    """
    logs = []

    # 1) 查找前端窗口(按标题, 可能是 electron 或其它壳进程)
    wins = pc.find_windows(title=APP_TITLE, visible_only=True)
    if not wins:
        # 兜底: 按 electron 进程找
        wins = pc.find_windows(exe=APP_EXE, visible_only=True)
    if not wins:
        logs.append("未找到采集器窗口")
        return False, "; ".join(logs)

    hwnd = wins[0][0]
    u32 = pc._u32()
    sw = u32.GetSystemMetrics(pc.SM_CXSCREEN)
    sh = u32.GetSystemMetrics(pc.SM_CYSCREEN)
    half = sw // 2

    # 2) 检测是否已在右半边(左边缘≈半屏且宽度≈半屏)
    r = wt.RECT()
    u32.GetWindowRect(hwnd, ctypes.byref(r))
    if abs(r.left - half) <= 2 and abs((r.right - r.left) - half) <= 0:
        logs.append("采集器窗口已在右半屏")
        return True, "; ".join(logs)

    # 3) 移动到右半边
    pc.move_window(hwnd, half, 0, half, sh)
    logs.append("采集器窗口已移到右半屏")
    return True, "; ".join(logs)


def _save_article_base(link, biz, list_reads=None, list_likes=None):
    """步骤2: 写文章表(完整同步逻辑, 被整体异步提交)
    先抓元信息(标题/时间/原创/ip) -> 带元信息写表; 抓取失败仅写链接
    返回 (new_id, name, art, 文本); 失败 new_id=None"""
    logs = []
    try:
        art = extract_art_biz(link)
        tag = f"元数据#{art[:10]}"
        tasks_echo(f"[async:{tag}] 正在采集...")
        # 抓取文章元信息(网络请求, 失败不阻断, 失败仅写链接)
        meta = None
        try:
            meta = fetch_article(link)
        except Exception as e:
            logs.append(f"元信息抓取失败: {e}")
        if meta:
            a_title, a_date, a_original, a_ip = meta
            logs.append(f"元信息: {a_title} | {a_date or '无时间'} | {a_original} | {a_ip or '无ip'}")
        else:
            a_title, a_date, a_original, a_ip = "", "", "", ""
            logs.append("元信息抓取失败, 仅写入链接")

        conn = get_conn()
        try:
            acc = conn.execute("SELECT id, name FROM accounts WHERE biz=?", (biz,)).fetchone()
            account_id = acc["id"] if acc else None
            name = acc["name"] if acc else ""
            # 检查是否已存在(同biz+art_biz唯一), 存在则复用/跳过新增
            exists = conn.execute(
                "SELECT id FROM articles WHERE biz=? AND art_biz=?",
                (biz, art)).fetchone()
            if exists:
                new_id = exists["id"]
                # 已存在: 有元信息时补全缺失字段, 每次都刷新写入时间
                wt = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                if meta:
                    conn.execute(
                        "UPDATE articles SET title=?, date=?, original=?, ip=?, write_time=? WHERE id=?",
                        (a_title, a_date, a_original, a_ip, wt, new_id))
                    logs.append(f"文章已存在, 更新元信息 id={new_id}")
                else:
                    conn.execute("UPDATE articles SET write_time=? WHERE id=?", (wt, new_id))
                    logs.append(f"文章已存在, 复用 id={new_id}")
            else:
                wt = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                cur = conn.execute(
                    "INSERT INTO articles(account_id, name, date, title, original, ip, art_biz, biz, write_time) "
                    "VALUES(?,?,?,?,?,?,?,?,?)",
                    (account_id, name, a_date, a_title, a_original, a_ip, art, biz, wt))
                new_id = cur.lastrowid
                logs.append(f"已写入文章表 id={new_id}")
            conn.commit()
        finally:
            conn.close()
    except Exception as e:
        logs.append(f"写入文章表失败: {e}")
        return None, "", "", "; ".join(logs)

    # 列表页识别到的阅读数/点赞先更新
    if list_reads is not None or list_likes is not None:
        try:
            conn = get_conn()
            try:
                if list_reads is not None and list_likes is not None:
                    conn.execute("UPDATE articles SET reads=?, likes=? WHERE id=?",
                                 (list_reads, list_likes, new_id))
                    logs.append(f"列表阅读/赞: {list_reads}/{list_likes} 已写入 id={new_id}")
                elif list_reads is not None:
                    conn.execute("UPDATE articles SET reads=? WHERE id=?", (list_reads, new_id))
                    logs.append(f"列表阅读: {list_reads} 已写入 id={new_id}")
                else:
                    conn.execute("UPDATE articles SET likes=? WHERE id=?", (list_likes, new_id))
                    logs.append(f"列表赞: {list_likes} 已写入 id={new_id}")
                conn.commit()
            finally:
                conn.close()
        except Exception as e:
            logs.append(f"列表阅读/赞写入失败: {e}")

    tasks_echo(f"[async:{tag}] 采集完成, 文章已写入 id={new_id}")
    return new_id, name, art, "; ".join(logs)


def _save_html_block(link, name="", tag="", base_dir=None):
    """步骤3: 保存文章为本地HTML(公众号分类目录, 含图片本地化) - 独立流程
    后台异步执行(save_article_html 内含网络请求), 完成后回调日志"""
    if not tag:
        try:
            tag = f"保存Html#{extract_art_biz(link)[:10]}"
        except Exception:
            tag = "保存Html"
    tasks_echo(f"[async:{tag}] 正在保存...")
    try:
        html_path, info = save_article_html(link, account_name=name, base_dir=base_dir)
        ok_txt = "成功: " + info if html_path else "失败: " + info
        tasks_echo(f"[async:{tag}] {ok_txt}")
    except Exception as e:
        tasks_echo(f"[async:{tag}] 异常: {e}")

def _bg_ai_metrics(shot_b64, api_key, model, biz, art):
    """后台线程任务: 豆包识图4指标(网络请求) -> 更新文章数据
    成功写指标值(按biz+art_biz匹配)"""
    tag = f"4指标#{art[:10]}"
    try:
        metrics = None
        if shot_b64 and api_key and model:
            tasks_echo(f"[async:{tag}] 正在豆包识图...")
            metrics = doubao_recognize_interact(shot_b64, api_key, model)
            if metrics is not None:
                tasks_echo(f"[async:{tag}] 点赞{metrics[0]} 转发{metrics[1]} 喜欢{metrics[2]} 留言{metrics[3]}")
            else:
                tasks_echo(f"[async:{tag}] 识图失败")
        else:
            tasks_echo(f"[async:{tag}] 未配置AI模型或截图失败")

        # 更新文章数据: 成功写指标值
        data = {"biz": biz, "art_biz": art}
        if metrics is not None:
            data.update({
                "likes": str(metrics[0]), "forwards": str(metrics[1]),
                "favorites": str(metrics[2]), "comments": str(metrics[3]),
            })
        r = _requests.put(
            "http://127.0.0.1:8000/api/accounts/articles-by-biz/save",
            json=data, timeout=15,
        )
        if r.status_code == 200:
            tasks_echo(f"[async:{tag}] 数据已更新")
        else:
            tasks_echo(f"[async:{tag}] 更新失败: HTTP {r.status_code}")
    except Exception as e:
        tasks_echo(f"[async:{tag}] 异常: {e}")


def _collect_metrics(biz, art):
    """4指标采集: 截图30/31区域(主线程) -> 豆包识图异步提交(网络, 不阻塞)
    截图后立即返回, 识图与更新由后台线程完成"""
    # 实时输出: 每步直接 tasks_echo
    p30 = _read_point(30)   # 4指标区域左上
    p31 = _read_point(31)   # 4指标区域右下
    shot_b64 = None
    if p30 and p31:
        # 页面稳定判断(30/31区域, 50次机会, 连续15次相同判稳定; 不稳定也继续执行)
        ok_stable, info = wait_page_stable(
            p30[0], p30[1], p31[0], p31[1], same_need=15, timeout=50, interval=0.1)
        tasks_echo(f"4指标: 页面稳定={ok_stable}({info})")
        try:
            shot_path, shot_b64 = pc.screenshot(
                p30[0], p30[1], p31[0], p31[1], img_format="png", as_base64=True)
            if not shot_b64:
                tasks_echo("4指标区域截图失败")
                shot_b64 = None
        except Exception as e:
            tasks_echo(f"4指标区域截图失败: {e}")
            shot_b64 = None
    else:
        tasks_echo("缺少点位30/31(4指标区域), 跳过4指标")
        shot_b64 = None

    # 从 ai_model 表取 key + 模型; 未配置则跳过识图只留截图
    api_key = ""
    model = ""
    try:
        conn = get_conn()
        try:
            row = conn.execute(
                "SELECT api_key, model_id FROM ai_model ORDER BY id LIMIT 1").fetchone()
            if row:
                api_key = row["api_key"] or ""
                model = row["model_id"] or ""
        finally:
            conn.close()
    except Exception:
        pass

    # 豆包识图+写表整体异步提交(网络耗时, 不阻塞主流程)
    _submit_bg(_bg_ai_metrics, shot_b64, api_key, model, biz, art)


def _bg_reads_ocr(png_path, box, biz, art):
    """后台线程任务: 阅读数截图OCR识别(耗时) -> 识别到写文章表
    独立异步执行, 不阻塞主流程; 日志实时转发"""
    tag = f"阅读数#{art[:10]}"
    try:
        img = Image.open(png_path).convert("RGB")
        items = ocr_service.ocr(img)
        reads = _extract_read_from_items(items, box, img=img)
        if reads is not None:
            tasks_echo(f"[async:{tag}] 识别到阅读数 {reads}")
            _save_reads(biz, art, reads)
        else:
            tasks_echo(f"[async:{tag}] OCR未找到'阅读'+数字或颜色不符")
    except Exception as e:
        tasks_echo(f"[async:{tag}] 阅读数OCR异常: {e}")


def _collect_reads(collect_type, link, biz, art):
    """采集阅读数: 滚到底->Ctrl+W->搜一搜按钮->粘贴链接->回车->稳定检测OCR识别
    写库按 biz+art_biz 匹配, 不依赖写表结果; 列表页已识别到阅读数时主函数跳过高不此调用"""
    # 实时输出: 每步直接 tasks_echo
    p15 = _read_point(15)
    # 搜一搜按钮点位: 类型1=点位23(公众号采集), 类型2=点位14(单篇更新)
    p_sou = _read_point(23) if collect_type == 1 else _read_point(14)
    _tag_n = 23 if collect_type == 1 else 14
    if not p15 or not p_sou:
        tasks_echo(f"[warn] 阅读数: 缺少点位15={bool(p15)}/{_tag_n}={bool(p_sou)}, 跳过阅读数采集")
        return
    # 1) 鼠标移到文章列表左上(点位15), 向下滚动5000px(0.5s内完成)
    pc.scroll(p15[0], p15[1], 50000, direction="down", duration=0.5)
    tasks_echo("阅读数: 在点位15滚动5000px")
    time.sleep(0.5)
    # 2) Ctrl+W 关闭当前页
    pc.ctrl_key("W")
    tasks_echo("阅读数: Ctrl+W 关闭")
    time.sleep(0.8)
    # 3) 点击搜一搜按钮(类型1=点位23 / 类型2=点位14), 等0.2s
    if collect_type in (1, 2):
        pc.mouse_click(p_sou[0], p_sou[1])
        tasks_echo(f"阅读数: 点击搜一搜按钮(点位{_tag_n})({p_sou[0]},{p_sou[1]})")
        time.sleep(0.2)
        # 4) 剪贴板粘贴复制的链接(与搜一搜查询一致), 等0.2s, 回车
        pc.set_clipboard_text(link)
        pc.ctrl_key("V")
        tasks_echo("阅读数: 剪贴板粘贴链接")
        time.sleep(0.2)
        pc.key_press(pc.VK_RETURN)
        tasks_echo("阅读数: 按回车")
        # 回车后: 页面稳定检测(点位32/33区域, 50次机会, 连续20次相同) -> OCR提取阅读数
        p32 = _read_point(32)
        p33 = _read_point(33)
        if not (p32 and p33):
            tasks_echo("缺少点位32/33(阅读数区域), 跳过阅读数识别")
        else:
            ok_stable, info = wait_page_stable(
                p32[0], p32[1], p33[0], p33[1], same_need=20, timeout=50, interval=0.1)
            if not ok_stable:
                # 未稳定也继续: 页面可能仍在加载/动, 不等稳定直接截图识别
                tasks_echo(f"阅读数: 结果页未稳定({info}), 继续尝试识别...")
            # 稳定或未稳定: 都截图 -> OCR识别丢后台异步, 识别到写文章表
            png_path, b64 = pc.screenshot(
                p32[0], p32[1], p33[0], p33[1], img_format="png", as_base64=True)
            if not b64:
                tasks_echo("阅读数: 稳定后截图失败")
            else:
                tasks_echo("阅读数: 截图完成, OCR识别后台进行...")
                _submit_bg(_bg_reads_ocr, png_path, (p32[0], p32[1]), biz, art)


def _save_debug_shot(shot_path, folder, tag):
    """调试: 复制截图文件到桌面文件夹(如 豆包/), 带时间戳防覆盖"""
    try:
        import os, shutil, time as _t
        dst_dir = os.path.join(os.path.expanduser("~/Desktop"), folder)
        os.makedirs(dst_dir, exist_ok=True)
        name = f"{_t.strftime('%H%M%S')}_{tag.replace('#','_')}.png"
        shutil.copy(shot_path, os.path.join(dst_dir, name))
        tasks_echo(f"[async:{tag}] 调试截图已存桌面/{folder}/{name}")
    except Exception:
        pass


def _save_debug_shot_b64(shot_b64, folder, tag):
    """调试: 把base64截图写入桌面文件夹(如 豆包/), 带时间戳防覆盖"""
    try:
        import os, base64, time as _t
        dst_dir = os.path.join(os.path.expanduser("~/Desktop"), folder)
        os.makedirs(dst_dir, exist_ok=True)
        name = f"{_t.strftime('%H%M%S')}_{tag.replace('#','_')}.png"
        sb = shot_b64.split(",", 1)[1] if "," in shot_b64 else shot_b64
        with open(os.path.join(dst_dir, name), "wb") as f:
            f.write(base64.b64decode(sb))
        tasks_echo(f"[async:{tag}] 调试截图已存桌面/{folder}/{name}")
    except Exception:
        pass


def _expand_reply_buttons(x1, y1, x2, y2, max_rounds=3):
    """展开评论区更多回复: while循环(最多max_rounds次)
    每轮: 截图35/36找'更多回复/N条回复'灰字按钮 -> 点第一个 -> 35/36稳定检测(30次/连续10次)
    找不到按钮或超过轮数 -> 退出返回 True(有兜底, 最终必返True)"""
    from PIL import Image as _PIL
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
    from concurrent.futures import ThreadPoolExecutor
    from PIL import Image as _PIL
    from ..database import get_conn
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
        from .common import merge_comment_shots
        if len(shot_b64s) >= 2:
            merged_img = merge_comment_shots(shot_b64s[0], shot_b64s[1])
        else:
            merged_img = None
        if merged_img is not None:
            import io as _io, base64
            _buf = _io.BytesIO(); merged_img.save(_buf, format="PNG")
            shot_b64s = [_buf.getvalue()]
            _buf2 = _io.BytesIO(); merged_img.save(_buf2, format="WEBP", lossless=True, method=6)
            _ai_b64 = "data:image/webp;base64," + base64.b64encode(_buf2.getvalue()).decode()
        else:
            _ai_b64 = shot_b64s[0]
        from .doubao_api import doubao_extract_comments as _dec

        def _ocr_levels():
            try:
                import io as _io, base64
                import re as _re
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
        from .common import save_comments
        wrote = save_comments(art_biz, comments)
        tasks_echo(f"[async:{tag}] 识别评论{len(comments)}条, 写入{wrote}条")
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
    pc.mouse_click(p34[0], p34[1])
    tasks_echo(f"评论采集: 点击评论按钮({p34[0]},{p34[1]})")
    time.sleep(0.5)

    loop_n = 0
    prev_b64 = None   # 上一轮截图(与本轮拼接读取, 避免截断误判)
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
            # 多图拼接: [上一轮, 本轮] 一起给AI(评论跨图截断时拼接读取)
            _sub = [prev_b64, shot_b64] if prev_b64 else [shot_b64]
            _submit_bg(_bg_ai_comments, _sub, art,
                       max_level1, max_level2, shot_x=p35[0])
            tasks_echo(f"评论采集第{loop_n}轮: 评论识别后台进行中...")
            prev_b64 = shot_b64

        try:
            from ..database import get_conn
            conn = get_conn()
            try:
                row = conn.execute("SELECT distance, direction FROM scrolls WHERE id=5").fetchone()
            finally:
                conn.close()
            s_dist = int(float(row["distance"])) if row else 0
            s_dir = row["direction"] if row else "down"
        except Exception:
            s_dist, s_dir = 0, "down"
        if s_dist > 0:
            pc.scroll(p35[0], p35[1], s_dist, direction=s_dir)
            tasks_echo(f"评论采集第{loop_n}轮: 滚动评论区 {s_dist}px")
            time.sleep(0.5)


def article_data_collect(collect_type=0, capture_4metrics=False, capture_read=False,
                         save_html=False, save_dir="", biz="", list_reads=None, list_likes=None,
                         capture_comments=False, max_comments=None, max_level1=None, max_level2=0):
    """文章数据采集(编排主函数, 各块拆分到 _save_article_base
    /_collect_metrics/_collect_reads/_collect_comments; 复制链接逻辑留本函数)。
    参数:
      collect_type / capture_4metrics / capture_read / save_html / save_dir
      biz / list_reads / list_likes 同前
      capture_comments 是否采集评论
      max_comments     文章最大评论采集数(None=无限)
      max_level1       一级评论采集数(None=无限)
      max_level2       每级二级评论采集数(0=不采二级, None=无限)
    流程: 复制链接 -> 提取art_biz -> 写表(异步) -> 保存Html(异步)
    -> 4指标 -> 阅读数 -> 评论(需阅读数点位); 统一出口 _finish(Ctrl+W)。
    异步设计: 写表/保存Html/豆包识图/阅读数OCR 丢线程池, 主流程不阻塞网络耗时。
    """
    logs = []
    copy_seen = False   # 标志: 是否检测到过"复制"字样

    def step(msg):
        """步骤日志: 实时转发(带[step]标记) + 入汇总"""
        logs.append(msg)
        tasks_echo(f"[step] {msg}")

    if collect_type == 0:
        step("触发类型不确定, 无法采集")
        return _finish(logs, copy_seen, False, "触发类型不确定, 无法采集")

    # 1) 获取复制链接(2次机会): 点18(3点菜单) -> OCR检测复制字样 -> 点27 -> 读剪贴板60次
    p18 = _read_point(18)   # 文章右上角3点
    p27 = _read_point(27)   # 点击复制链接
    p28 = _read_point(28)   # 复制链接区域左上
    p29 = _read_point(29)   # 复制链接区域右下
    if not p18 or not p27:
        step("缺少点位18/27(3点/复制链接)")
        return _finish(logs, copy_seen, False, "缺少点位18/27(3点/复制链接)")
    link = None
    for _try in range(1, 3):
        step(f"--- 复制链接 第{_try}次 ---")
        copy_seen = False   # 每次循环重置, 避免沿用上次残留
        pc.clear_clipboard()
        step(f"点击点位18(3点)({p18[0]},{p18[1]})")
        pc.mouse_click(p18[0], p18[1])
        time.sleep(0.5)   # 等菜单弹出, 否则截图时菜单未出现会误判无复制
        # 截图点位28-29区域, OCR 检测是否有"复制"字样
        if p28 and p29:
            try:
                shot_path, _b64 = pc.screenshot(p28[0], p28[1], p29[0], p29[1],
                                                img_format="png")
                if shot_path:
                    ocr_items = ocr_service.ocr(Image.open(shot_path))
                    copy_seen = any("复制" in (it[2] or "") for it in ocr_items)
                    step("OCR检测到复制字样" if copy_seen else "OCR未检测到复制字样")
            except Exception as e:
                step(f"复制链接OCR检测失败: {e}")
        if copy_seen:
            # 检测到"复制": 点击复制链接(点位27), 读剪贴板60次
            step(f"点击点位27(复制链接)({p27[0]},{p27[1]})")
            pc.mouse_click(p27[0], p27[1])
            for _i in range(1, 60):
                time.sleep(0.1)
                v = pc.read_clipboard_text()
                if v:
                    link = v
                    break
            step(f"已复制链接: {link[:60]}" if link else "未读取到剪贴板链接")
        else:
            # 未检测到"复制": 再点击点位18, 等0.2秒
            step(f"再次点击点位18(3点)({p18[0]},{p18[1]}), 等0.2s")
            pc.mouse_click(p18[0], p18[1])
            time.sleep(0.5)
            pc.clear_clipboard()
        if link:
            break   # 已拿到链接, 跳出
    if not link:
        step("2次复制链接均未获取到, 本轮结束")
        return _finish(logs, copy_seen, False, "未获取到链接")

    # art_biz 同步提取(供 4指标/阅读数 使用, 不依赖写表)
    art = extract_art_biz(link)
    if not art:
        step("链接提取art_biz失败")
        return _finish(logs, copy_seen, False, "链接提取art_biz失败")

    # 2) 写文章表(完整流程: 抓元信息->写表, 整体异步提交, 不阻塞后续)
    _submit_bg(_save_article_base, link, biz, list_reads, list_likes)

    # 3) 保存Html(独立流程, 并行异步)
    if save_html:
        _submit_bg(_save_html_block, link, base_dir=save_dir)  # 开始/完成日志由后台函数输出

    # 4) 4指标(开启时)
    if capture_4metrics:
        tasks_echo("[step] 正在采集4指标...")
        _collect_metrics(biz, art)

    # 5) 采集阅读数(开启且列表无阅读数时)
    if capture_read and list_reads is None:
        tasks_echo("[step] 正在采集阅读数...")
        _collect_reads(collect_type, link, biz, art)

    # 6) 采集评论(开启时, 在阅读数之后)
    if capture_comments:
        tasks_echo("[step] 正在采集评论...")
        _collect_comments(collect_type, link, art, biz,
                          max_comments=max_comments, max_level1=max_level1, max_level2=max_level2)

    # 细节已实时输出, 最终只返回状态摘要
    return _finish([], copy_seen, True, "采集完成")
__all__ = ["init_wechat_window", "search_window_init", "search_query",
           "article_list_wait_stable", "init_app_window",
           "article_data_collect",
           "request_stop", "clear_stop", "stop_requested",
           "bind_tasks_echo", "tasks_echo"]

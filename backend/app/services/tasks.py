# -*- coding: utf-8 -*-
"""backend.app.services.tasks: 任务组合模块

用途: 把 computer(电脑交互原语) 等底层模块按业务步骤组合成"任务函数"。

规则:
  * 本模块只放组合逻辑, 不放新的 Win32/输入原语(那些在 computer.py)。
  * 新增任务函数前需先经过确认。
"""

import threading
import time

from . import computer as pc

# 模块加载时启用 DPI 感知(进程级, 幂等): 确保所有点位坐标用物理像素, 避免缩放偏移
pc.enable_dpi_awareness()

# 实时日志钩子(后端采集接口注入后, article_list_wait_stable 的 echo 会同时转发)
_tasks_log_hook = None

# 全局停止信号: 前端断开/手动停止时置位, 死循环检测后退出
_stop_requested = threading.Event()


def request_stop():
    """请求停止死循环(前端关闭采集时调用)"""
    _stop_requested.set()


def clear_stop():
    """清除停止信号(新一次采集开始时调用)"""
    _stop_requested.clear()


def stop_requested():
    """是否收到停止请求"""
    return _stop_requested.is_set()



def bind_tasks_echo(fn):
    """绑定实时日志回调; 返回旧回调(用于恢复)。fn=None 清除"""
    global _tasks_log_hook
    old = _tasks_log_hook
    _tasks_log_hook = fn
    return old


def tasks_echo(msg):
    """实时输出日志: 打印 + 转发到钩子(若有)"""
    try:
        print(msg, flush=True)
    except Exception:
        pass
    hook = _tasks_log_hook
    if hook is not None:
        try:
            hook(msg)
        except Exception:
            pass


# 微信相关进程名（对应两个可见微信主窗口的宿主进程）
WECHAT_MAIN = "Weixin.exe"          # 微信主界面进程
WECHAT_APPEX = "WeChatAppEx.exe"    # 微信小程序/外部App容器进程

# 采集器(前端)相关
APP_TITLE = "微信公众号采集器"      # 前端窗口标题(打包后名称)
APP_EXE = "electron.exe"           # 前端壳进程


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
    import ctypes
    from ctypes import wintypes as wt
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
        from ..database import get_conn
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

    # 1) 关闭 WeChatAppEx(仅可见窗口)
    appex = pc.find_windows(exe=WECHAT_APPEX, visible_only=True)
    for hwnd, _t, _p, _v in appex:
        pc.close_window(hwnd)
        logs.append(f"已关闭 WeChatAppEx 窗口 #{hwnd}")
    if not appex:
        logs.append("无可见 WeChatAppEx 窗口, 跳过")

    # 2) 找 Weixin, 无则唤出
    weixin = pc.find_windows(exe=WECHAT_MAIN)
    if not weixin:
        found = pc.find_windows(exe=WECHAT_MAIN, visible_only=False)
        if not found:
            logs.append("未找到 Weixin.exe 窗口")
            return False, "; ".join(logs)
        pc.show_window(found[0][0])
        logs.append(f"已唤出 Weixin 窗口 #{found[0][0]}")
        weixin = pc.find_windows(exe=WECHAT_MAIN)
    else:
        logs.append(f"Weixin 窗口已存在 #{weixin[0][0]}")
    if not weixin:
        logs.append("Weixin.exe 窗口仍未识别")
        return False, "; ".join(logs)

    hwnd = weixin[0][0]

    # 3) 移到屏幕左半边(用通用 move_window 计算左半位置并按需移动)
    u32_sm = pc._u32()   # 内部取屏幕尺寸用
    sw = u32_sm.GetSystemMetrics(pc.SM_CXSCREEN)
    sh = u32_sm.GetSystemMetrics(pc.SM_CYSCREEN)
    pc.move_window(hwnd, 0, 0, sw // 2, sh)

    # 4) 校验是否就位左半屏(贴左边缘且宽度等于半屏); 不合法则返回 False
    r = wt.RECT()
    pc._u32().GetWindowRect(hwnd, ctypes.byref(r))
    if abs(r.left) > 2 or abs((r.right - r.left) - sw // 2) > 0:
        logs.append("Weixin 未就位左半屏(宽度或位置不合法)")
        return False, "; ".join(logs)

    logs.append("Weixin 窗口已就位左半屏")
    return True, "; ".join(logs)


def _read_point(pid):
    """内部: 读取点位坐标 (x, y); 无/无效返回 None"""
    try:
        from ..database import get_conn
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
    import ctypes
    from ctypes import wintypes as wt
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
    import ctypes
    from ctypes import wintypes as wt
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


def wait_page_stable(x1, y1, x2, y2, same_need=15, timeout=30, interval=0.1):
    """通用页面稳定判断: 对指定区域反复截图, 连续多次完全相同判页面稳定。
    参数:
      x1,y1,x2,y2  截图区域(屏幕坐标)
      same_need    连续相同多少次判稳定(默认15)
      timeout      最多截图次数(默认30, 超时判失败)
      interval     每次截图间隔(默认0.1s)
    返回: (稳定?, 说明文本)
    """
    import hashlib
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


def article_list_wait_stable(date_start="", date_end="", biz="",
                             capture_4metrics=False, capture_read=False):
    """文章列表识别循环: 进入 while 循环, 每次循环第一步检查页面稳定。
    前提: 搜一搜查询(search_query)已加载出公众号链接(本函数不判定, 但依赖其结果)。
    参数:
      date_start, date_end 采集时间范围(YYYY-MM-DD); 空字符串=全部(不限)
      biz              所属公众号 biz 代码(点击文章后数据采集用)
      capture_4metrics 是否采集4指标
      capture_read     是否采集阅读数量
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

    # 循环前: 页面稳定判断(100次机会, 每0.1s, 连续30次相同算稳定)
    ok0, info0 = wait_page_stable(x1, y1, x2, y2, same_need=30, timeout=100, interval=0.1)
    if not ok0:
        logs.append(f"初始页面未稳定(30次未达成): {info0}")
        return False, "; ".join(logs)
    logs.append(f"初始页面稳定: {info0}")

    # 稳定后点击点位17
    p17 = _read_point(17)
    if p17:
        pc.mouse_click(p17[0], p17[1])
        echo_line = f"点击点位17({p17[0]},{p17[1]})"
        logs.append(echo_line)
        tasks_echo(echo_line)
    else:
        logs.append("缺少点位17")

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

        # 每次循环第一步: 页面稳定判断(失败不退出, 有兜底)
        ok, info = wait_page_stable(x1, y1, x2, y2)
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
            from PIL import Image
            from . import ocr as ocr_service
            img = Image.open(shot_path)
            items = ocr_service.ocr(img)
        except Exception as e:
            echo(f"第{loop_n}轮OCR失败: {e}")
            return False, f"第{loop_n}轮OCR失败: {e}"

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

            # 点击后: 采集该文章数据(获取链接+写文章表)
            ok_c, text_c = article_data_collect(
                collect_type=1, capture_4metrics=capture_4metrics,
                capture_read=capture_read, biz=biz)
            echo(f"  文章数据采集: {'成功' if ok_c else '失败'} | {text_c}")

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
                # 全不在范围内: 优先看是否有时间点位在范围之后
                if any(e and t > e for t in times):
                    date_out_count = date_out_count + 1
                    echo(f"第{loop_n}轮: 时间点位在日期范围之后({date_out_count}/3)")
                    if date_out_count >= 3:
                        echo("连续3次无日期范围文章, 停止")
                        return False, "连续3次无日期范围文章"
                else:
                    # 有在范围之前(范围还没到) -> 多滚动几次就会出现, 重置计数继续
                    date_out_count = 0
                    echo(f"第{loop_n}轮: 时间点位在日期范围之前(未到范围), 继续")
            else:
                date_out_count = 0       # 本轮无时间点位, 不判定, 重置

        # 停止条件: 连续3次OCR截图完全相同 -> 无更多文章, 停止(返回True)
        import hashlib as _hashlib
        cur_shot_hash = None
        try:
            with open(shot_path, "rb") as _f:
                cur_shot_hash = _hashlib.md5(_f.read()).hexdigest()
        except Exception:
            cur_shot_hash = None
        if prev_shot_hash == cur_shot_hash:
            same_shot = same_shot + 1
        else:
            same_shot = 1
        prev_shot_hash = cur_shot_hash
        if same_shot >= 3:
            echo(f"第{loop_n}轮: 连续3次截图相同, 判定无更多文章, 停止")
            return True, "无更多文章"

        # 滚动: 鼠标移到点位15, 触发滚动配置 id=3(向下)
        try:
            from ..database import get_conn
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
    import ctypes
    from ctypes import wintypes as wt
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


def article_data_collect(collect_type=0, capture_4metrics=False, capture_read=False,
                         biz=""):
    """文章数据采集。
    参数:
      collect_type     采集触发类型(0=未知/默认; 1=公众号点击采集; 可扩展)
      capture_4metrics 是否采集4指标
      capture_read     是否采集阅读数量
      biz              所属公众号 biz 代码
    逻辑:
      1) 检查触发类型; 为0(不确定)直接返回 False
      2) 获取复制链接
      3) 拿到链接后写入文章表(文章id+公众号biz)
    """
    logs = []
    from .doubao_api import recognize_interact as doubao_recognize_interact
    if collect_type == 0:
        logs.append("触发类型不确定, 无法采集")
        return False, "; ".join(logs)
    # 非0 -> 第一步: 获取复制链接流程
    p18 = _read_point(18)   # 文章右上角3点
    p27 = _read_point(27)   # 点击复制链接
    if not p18 or not p27:
        logs.append("缺少点位18/27(3点/复制链接)")
        return False, "; ".join(logs)
    # 1) 复制链接流程: 清空剪贴板; 循环(最多2次) 点18(等0.2s)->点27->读60次
    pc.clear_clipboard()
    link = None
    for attempt in (1, 2):
        logs.append(f"复制链接 第{attempt}次尝试: 点击点位18(3点)({p18[0]},{p18[1]})")
        pc.mouse_click(p18[0], p18[1])          # 点3点
        time.sleep(0.2)
        pc.mouse_click(p27[0], p27[1])          # 点复制链接
        for _i in range(1, 61):
            time.sleep(0.1)
            v = pc.read_clipboard_text()
            if v:
                link = v
                break
        if link:
            logs.append(f"第{attempt}次尝试成功, 链接: {link[:60]}")
            break
    if not link:
        logs.append("未获取到复制链接")
        return False, "; ".join(logs)
    logs.append("获取复制链接成功")
    # 3) 写入文章表: 文章id(art_biz) + 公众号biz
    try:
        from ..database import get_conn
        from .importer import extract_art_biz
        art = extract_art_biz(link)
        conn = get_conn()
        try:
            acc = conn.execute("SELECT id, name FROM accounts WHERE biz=?", (biz,)).fetchone()
            account_id = acc["id"] if acc else None
            name = acc["name"] if acc else ""
            cur = conn.execute(
                "INSERT INTO articles(account_id, name, date, title, art_biz, biz) "
                "VALUES(?,?,?,'',?,?)",
                (account_id, name, "", art, biz))
            conn.commit()
            new_id = cur.lastrowid
        finally:
            conn.close()
        logs.append(f"已写入文章表 id={new_id} art_biz={art}")
    except Exception as e:
        logs.append(f"写入文章表失败: {e}")
        return False, "; ".join(logs)

    # 4指标采集(开启时): 截图30/31区域 -> 豆包识图(1次) -> 更新文章数据
    # 成功写指标值; 失败仍写截图base64(shot列)到文章表, 不中断流程
    if capture_4metrics:
        p30 = _read_point(30)   # 4指标区域左上
        p31 = _read_point(31)   # 4指标区域右下
        if p30 and p31:
            try:
                shot_path, shot_b64 = pc.screenshot(
                    p30[0], p30[1], p31[0], p31[1], img_format="png", as_base64=True)
                if not shot_b64:
                    logs.append("4指标区域截图失败")
                    shot_b64 = None
            except Exception as e:
                logs.append(f"4指标区域截图失败: {e}")
                shot_b64 = None
        else:
            logs.append("缺少点位30/31(4指标区域), 跳过4指标")
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

        metrics = None
        import requests as _requests
        if shot_b64 and api_key and model:
            logs.append("豆包识图...")
            metrics = doubao_recognize_interact(shot_b64, api_key, model)
            if metrics is not None:
                logs.append(f"豆包识图成功: 点赞{metrics[0]} 转发{metrics[1]} 喜欢{metrics[2]} 留言{metrics[3]}")
            else:
                logs.append("豆包识图失败, 仅保存4指标截图base64")
        else:
            logs.append("未配置AI模型或截图失败, 仅保存截图base64(如有)")

        # 更新文章数据: 成功写指标值; 失败只带 shot(base64)
        data = {"biz": biz, "art_biz": art}
        if metrics is not None:
            data.update({
                "likes": str(metrics[0]), "forwards": str(metrics[1]),
                "favorites": str(metrics[2]), "comments": str(metrics[3]),
            })
        if shot_b64:
            data["shot"] = shot_b64
        try:
            r = _requests.put(
                "http://127.0.0.1:8000/api/accounts/articles-by-biz/save",
                json=data, timeout=15,
            )
            if r.status_code == 200:
                logs.append(f"已更新文章数据(art_biz={art})")
            else:
                logs.append(f"更新文章数据失败: HTTP {r.status_code}")
        except Exception as e:
            logs.append(f"更新文章数据失败: {e}")

    # 采集阅读数(开启时, 在4指标之后): 滚到底->Ctrl+W->搜一搜按钮->输入链接->回车
    if capture_read:
        # 1) 鼠标移到文章列表左上(点位15), 向下滚动500000px(0.5s内完成)
        p15 = _read_point(15)
        if p15:
            pc.scroll(p15[0], p15[1], 500000, direction="down", duration=0.5)
            logs.append(f"阅读数: 在点位15滚动500000px")
            time.sleep(0.5)
        else:
            logs.append("缺少点位15, 跳过滚动")
        # 2) Ctrl+W 关闭当前页
        pc.ctrl_key("W")
        logs.append("阅读数: Ctrl+W 关闭")
        # 3) 采集类型1: 点击搜一搜按钮(点位23), 等0.2s
        if collect_type == 1:
            p23 = _read_point(23)
            if p23:
                pc.mouse_click(p23[0], p23[1])
                logs.append(f"阅读数: 点击搜一搜按钮(点位23)({p23[0]},{p23[1]})")
                time.sleep(0.2)
            else:
                logs.append("缺少点位23(搜一搜按钮)")
            # 4) 剪贴板粘贴复制的链接(与搜一搜查询一致), 等0.2s, 回车
            if pc.set_clipboard_text(link):
                pc.ctrl_key("V")
                logs.append("阅读数: 剪贴板粘贴链接")
            else:
                logs.append("阅读数: 剪贴板写入失败")
                pc.type_text(link)
                logs.append("阅读数: 改用逐字输入")
            time.sleep(0.2)
            pc.key_press(pc.VK_RETURN)
            logs.append("阅读数: 按回车")

    # TODO: 后续流程(阅读数截图等分支待描述)
    return True, "; ".join(logs)


__all__ = ["init_wechat_window", "search_window_init", "search_query",
           "article_list_wait_stable", "init_app_window",
           "article_data_collect"]

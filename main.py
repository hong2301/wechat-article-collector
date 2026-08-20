# -*- coding: utf-8 -*-
"""
微信公众号OCR采集器 - 启动控制台（Windows，纯标准库实现）

界面布局:
    左侧 控制区(600)   : 控制台日志 + 采集控制（索引范围/时间范围/最大数量/开始/进度）
    右侧 任务区(1000)  : input 数据表格（每行可编辑、操作列删除、底部重置/新增）

用法:
    python main.py                  -> 正常模式（GUI）
    python main.py --ui-shot 图.png  -> 截图自检（1.5秒后截全屏并退出）

依赖:
    pip install rapidocr_onnxruntime requests Pillow

输入: input.csv  ->  索引,url,公众号名称,状态
记忆: ui_state.json（索引范围/时间范围/自定义日期/最大采集数量 自动保存）
"""

import calendar as _cal
import csv
import ctypes
import ctypes.wintypes as wt
import json
import os
import queue
import re
import sys
import threading
import time
import tkinter as tk
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta
from tkinter import messagebox, scrolledtext, ttk
import core.utils as _utils
from core.paths import *
from core.utils import *
from core.doubao_api import (doubao_recognize_interact, doubao_extract_comments,
                                DoubaoQuotaError)
from core.image_ocr import *
from core.datastore import *
from core.win32util import *

# ---------------- 时间设置(可配置主要时间点: 内部名 -> (显示标签, 默认值)) ----------------
TIME_SETTINGS = {
    "win_pos":        ("微信窗口就位(秒)", 0.3),
    "search_bar":     ("点击搜索栏后", 0.3),
    "type_pause":     ("输入/删除后", 0.15),
    "result_click":   ("点击搜索结果后", 0.3),
    "switch_window":  ("切换窗口后", 0.5),
    "new_win_ready":  ("新窗口就位", 0.8),
    "search_wait":    ("搜索后等列表", 5.0),
    "author_timeout": ("作者检测超时", 15.0),
    "author_poll":    ("作者轮询间隔", 0.1),
    "article_load":   ("点击文章后等待", 1.0),
    "clipboard_wait": ("复制链接剪贴板缓冲", 0.5),
    "clipboard_poll": ("复制链接轮询间隔", 0.1),
    "scroll_after":   ("文章列表滚动后", 1.0),
    "close_after":    ("关闭文章后", 0.5),
    "reply_load":     ("评论二级加载", 0.8),
    "comment_scroll": ("评论区滚动后", 0.8),
    "read_load":      ("阅读数加载等待", 2.0),
}

# ---------------- 时间范围选项 ----------------
TIME_OPTIONS = (
    ("all", "全部"),
    ("today", "当天"),
    ("week", "近一周"),
    ("month", "近一个月"),
    ("year", "近一年"),
    ("custom", "自定义"),
)


_log_lock = threading.Lock()

# ---------- 采集流程参数(可调) ----------
SCROLL_READ_PX = 10000      # 采集阅读数时每次快速滚动像素
SCROLL_READ_ROUNDS = 3      # 快速滚动次数
WHEEL_TICK_PX = 120         # 滚轮每格带动像素
FAST_SCROLL_SLEEP = 0.05    # 快速滚动 tick 间间隔(秒)
READ_LOAD_WAIT = 2          # 按回车后等加载再截图(秒)




class DatePicker:
    """弹出式日历：点击日期写入 StringVar（YYYY-MM-DD）"""

    WEEK_HEAD = ("一", "二", "三", "四", "五", "六", "日")

    def __init__(self, master, var, title="选择日期"):
        self.master = master
        self.var = var
        self.title = title
        self.win = None
        self.year = None
        self.month = None
        self._sel = None

    def pick(self):
        """弹出日历窗口"""
        today = date.today()
        d = parse_date(self.var.get())
        self.year, self.month = (d.year, d.month) if d else (today.year, today.month)
        self._sel = d or today

        win = tk.Toplevel(self.master)
        win.title(self.title)
        win.resizable(False, False)
        win.grab_set()                       # 模态
        self.win = win

        # 顶部导航：◀ 年月 ▶
        nav = tk.Frame(win)
        nav.pack(fill=tk.X, padx=6, pady=4)
        tk.Button(nav, text="◀", width=3, command=self._prev).pack(side=tk.LEFT)
        self.title_var = tk.StringVar()
        tk.Label(nav, textvariable=self.title_var,
                 font=("Microsoft YaHei UI", 11, "bold")).pack(side=tk.LEFT, expand=True)
        tk.Button(nav, text="▶", width=3, command=self._next).pack(side=tk.LEFT)

        # 星期头
        head = tk.Frame(win)
        head.pack(fill=tk.X, padx=6)
        for i, w in enumerate(self.WEEK_HEAD):
            tk.Label(head, text=w, width=4,
                     font=("Microsoft YaHei UI", 9, "bold")).grid(row=0, column=i, pady=2)

        self.grid = tk.Frame(win)
        self.grid.pack(fill=tk.BOTH, padx=6, pady=4)
        self._render()

        # 定位到主窗口附近
        win.update_idletasks()
        try:
            wx, wy = self.master.winfo_rootx(), self.master.winfo_rooty()
            win.geometry(f"+{wx + 30}+{wy + 30}")
        except Exception:
            pass

    def _prev(self):
        self.year, self.month = (self.year - 1, 12) if self.month == 1 \
            else (self.year, self.month - 1)
        self._render()

    def _next(self):
        self.year, self.month = (self.year + 1, 1) if self.month == 12 \
            else (self.year, self.month + 1)
        self._render()

    def _render(self):
        self.title_var.set(f"{self.year}年 {self.month:02d}月")
        for w in self.grid.winfo_children():
            w.destroy()
        first_wd = _cal.weekday(self.year, self.month, 1)      # 周一=0
        days = _cal.monthrange(self.year, self.month)[1]
        today = date.today()
        for d in range(1, days + 1):
            col = (first_wd + d - 1) % 7
            row = (first_wd + d - 1) // 7 + 1
            day = date(self.year, self.month, d)
            is_today = day == today
            is_sel = day == self._sel
            txt = f"[{d}]" if (is_today and is_sel) else str(d)
            bg = "#1565c0" if is_today else ("#fff3c4" if is_sel else "#f0f0f0")
            fg = "white" if is_today else "black"
            tk.Button(self.grid, text=txt, width=4, bg=bg, fg=fg,
                      font=("Microsoft YaHei UI", 9), relief=tk.RAISED,
                      command=lambda dd=d: self._choose(dd)).grid(
                          row=row, column=col, padx=1, pady=1)

    def _choose(self, d):
        self.var.set(f"{self.year:04d}-{self.month:02d}-{d:02d}")
        self.win.destroy()


# ================= 点位设置弹窗 =================
class PointsDialog(tk.Toplevel):
    """点位管理弹窗：列表来自 config/points.csv（id/点位名称/x/y/操作）
    名称列可双击修改；id/x/y 只读（x/y 只能通过"修改"按钮编辑）
    操作列为"修改/删除"蓝色下划线按钮；底部新增"""

    FONT = ("Microsoft YaHei UI", 10)
    LINK = ("Microsoft YaHei UI", 9, "underline")   # 操作按钮样式（下划线）

    def __init__(self, master, app=None):
        super().__init__(master)
        self.app = app
        self.title("点位设置")
        self.geometry("690x520")
        self.minsize(560, 420)
        self.transient(master)
        self.grab_set()          # 模态
        self.rows = load_points()
        self._build()
        self._refresh()
        # 居中
        self.update_idletasks()
        x = (self.winfo_screenwidth() - 690) // 2
        y = (self.winfo_screenheight() - 520) // 2
        self.geometry(f"+{x}+{y}")

    def _build(self):
        # ---- 表头（固定不滚动，pack 固定列宽与行对齐；字体与行一致保证列宽像素相同） ----
        head = tk.Frame(self)
        head.pack(side=tk.TOP, fill=tk.X, padx=6, pady=(6, 2))
        tk.Label(head, text="id", width=5, anchor="center",
                 font=self.FONT).pack(side=tk.LEFT, padx=2)
        tk.Label(head, text="点位名称", width=22, anchor="w",
                 font=self.FONT).pack(side=tk.LEFT, padx=2)
        tk.Label(head, text="x", width=8, anchor="center",
                 font=self.FONT).pack(side=tk.LEFT, padx=2)
        tk.Label(head, text="y", width=8, anchor="center",
                 font=self.FONT).pack(side=tk.LEFT, padx=2)
        tk.Label(head, text="操作", width=20, anchor="center",
                 font=self.FONT).pack(side=tk.LEFT, padx=2)

        # ---- 可滚动列表区 ----
        wrap = tk.Frame(self)
        wrap.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=6)
        self.canvas = tk.Canvas(wrap, highlightthickness=0)
        vsb = ttk.Scrollbar(wrap, orient="vertical", command=self.canvas.yview)
        self.inner = tk.Frame(self.canvas)
        self.inner.bind("<Configure>",
                        lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.canvas.bind("<Enter>", lambda e: self.canvas.bind_all(
            "<MouseWheel>", lambda ev: self.canvas.yview_scroll(int(-ev.delta / 120), "units")))
        self.canvas.bind("<Leave>", lambda e: self.canvas.unbind_all("<MouseWheel>"))

        # ---- 底部按钮 ----
        bar = tk.Frame(self)
        bar.pack(fill=tk.X, padx=6, pady=(0, 8))
        tk.Button(bar, text="关闭", width=10, font=("Microsoft YaHei UI", 10),
                  command=self.destroy).pack(side=tk.RIGHT, padx=4)
        tk.Button(bar, text="新增", width=10, font=("Microsoft YaHei UI", 10),
                  command=self._add).pack(side=tk.RIGHT, padx=4)

    # ---------- 行渲染 ----------
    def _refresh(self):
        for w in self.inner.winfo_children():
            w.destroy()
        self.row_widgets = {}
        for pos, (idx, name, x, y) in enumerate(self.rows):
            self._add_row(pos, idx, name, x, y)

    def _add_row(self, pos, idx, name, x, y):
        row = tk.Frame(self.inner)
        row.pack(fill=tk.X, pady=1)
        # 名称超长截断显示（保持列宽固定，保证与表头对齐）
        shown = name if len(name) <= 22 else name[:22] + "…"
        tk.Label(row, text=str(idx), width=5, anchor="center",
                 font=self.FONT).pack(side=tk.LEFT, padx=2)
        name_lbl = tk.Label(row, text=shown, width=22, anchor="w", font=self.FONT)
        name_lbl.pack(side=tk.LEFT, padx=2)
        name_lbl.bind("<Double-1>",
                      lambda e, p=pos: self._edit_name(p, name_lbl))
        tk.Label(row, text=str(x or ""), width=8, anchor="center",
                 font=self.FONT).pack(side=tk.LEFT, padx=2)
        tk.Label(row, text=str(y or ""), width=8, anchor="center",
                 font=self.FONT).pack(side=tk.LEFT, padx=2)
        # 操作列：预览 / 修改 / 删除（蓝色下划线按钮样式）
        prev_btn = tk.Label(row, text="预览", width=4, fg="#c62828",
                            font=self.LINK, cursor="hand2")
        prev_btn.pack(side=tk.LEFT, padx=4)
        prev_btn.bind("<Button-1>", lambda e, p=pos: self._preview(p))
        edit_btn = tk.Label(row, text="修改", width=4, fg="#1565c0",
                            font=self.LINK, cursor="hand2")
        edit_btn.pack(side=tk.LEFT, padx=4)
        edit_btn.bind("<Button-1>", lambda e, p=pos: self._edit_row(p))
        del_btn = tk.Label(row, text="删除", width=4, fg="#1565c0",
                           font=self.LINK, cursor="hand2")
        del_btn.pack(side=tk.LEFT, padx=4)
        del_btn.bind("<Button-1>", lambda e, p=pos: self._delete_row(p))
        self.row_widgets[pos] = row

    # ---------- 名称列双击编辑 ----------
    def _edit_name(self, pos, lbl):
        idx, name, x, y = self.rows[pos]
        row = self.row_widgets.get(pos)
        if row is None:
            return
        # 记录名称 Label 位置，用 Entry 覆盖（place 与 pack 不冲突）
        px, py = lbl.winfo_x(), lbl.winfo_y()
        pw, ph = lbl.winfo_width(), lbl.winfo_height()
        lbl.destroy()
        e = tk.Entry(row, font=self.FONT)
        e.place(x=px, y=py, width=pw, height=ph)
        e.insert(0, name)
        e.insert(0, name)
        e.focus_set()
        e.select_range(0, "end")
        state = {"done": False}

        def commit(_ev=None):
            if state["done"]:
                return
            state["done"] = True
            try:
                v = e.get().strip()
            except Exception:
                v = ""
            e.destroy()
            if v and v != name:
                self.rows[pos] = (idx, v, x, y)
                self._save("已修改点位名称")
            else:
                self._refresh()

        def cancel(_ev=None):
            state["done"] = True
            e.destroy()
            self._refresh()

        e.bind("<Return>", commit)
        e.bind("<FocusOut>", commit)
        e.bind("<Escape>", cancel)

    # ---------- 修改点位：鼠标采集坐标 ----------
    def _edit_row(self, pos):
        """修改点位：弹窗保持显示，释放模态后鼠标采集坐标
        左键单击预览 / 双击确认(取单击值) / 右键暂停恢复"""
        if pos >= len(self.rows):
            return
        idx, name, x, y = self.rows[pos]
        log(f"开始采集点位 [{idx}] {name} 的坐标...")
        log("坐标采集: 左键单击预览 / 双击确认(取单击值) / 右键暂停恢复")
        try:
            self.grab_release()      # 释放模态，允许点击目标窗口
        except Exception:
            pass
        self._collect_pos = pos
        self._result_q = queue.Queue()
        threading.Thread(target=self._collect_worker, args=(pos,), daemon=True).start()
        self.after(50, self._poll_collect_result)

    def _collect_worker(self, pos):
        """后台线程：采集坐标（阻塞直到确认）"""
        c = MousePointCollector()
        result = c.run()
        try:
            self._result_q.put(result)
        except Exception:
            pass

    def _poll_collect_result(self):
        """主线程轮询采集结果：恢复模态并写回点位"""
        try:
            result = self._result_q.get_nowait()
        except queue.Empty:
            self.after(50, self._poll_collect_result)
            return
        except Exception:
            return
        try:
            self.grab_set()          # 恢复模态
        except Exception:
            pass
        if result:
            pos = self._collect_pos
            if 0 <= pos < len(self.rows):
                idx, name, x, y = self.rows[pos]
                self.rows[pos] = (idx, name, result[0], result[1])
                self._save("已更新点位坐标")
        else:
            log("坐标采集取消，点位未修改")
    # ---------- 删除 / 新增 ----------
    def _preview(self, pos):
        """预览: 在屏幕对应坐标亮起红点(直径约20px), 持续1秒自动消失"""
        if pos >= len(self.rows):
            return
        idx, name, x, y = self.rows[pos]
        try:
            px, py = int(float(x)), int(float(y))
        except (TypeError, ValueError):
            messagebox.showwarning("坐标无效",
                                   f"点位 [{idx}] {name} 的坐标无效，请先【修改】采集", parent=self)
            return
        r = 10   # 红点半径
        ov = tk.Toplevel(self)
        ov.title("")
        ov.overrideredirect(True)              # 无边框
        ov.attributes("-topmost", True)        # 置顶
        ov.attributes("-alpha", 0.9)           # 半透明
        ov.geometry(f"+{px - r - 2}+{py - r - 2}")
        c = tk.Canvas(ov, width=r * 2 + 4, height=r * 2 + 4,
                      highlightthickness=0, bg="white")
        c.pack()
        c.create_oval(2, 2, r * 2 + 2, r * 2 + 2, fill="#e53935", outline="#b71c1c", width=2)
        try:
            ov.attributes("-toolwindow", True)
        except Exception:
            pass
        log(f"预览点位 [{idx}] {name} 坐标({px},{py})")
        self.after(1000, ov.destroy)   # 1秒后消失

    def _delete_row(self, pos):
        if pos >= len(self.rows):
            return
        idx, name, x, y = self.rows[pos]
        if messagebox.askyesno("删除确认",
                               f"确定删除点位 [{idx}] {name}？", parent=self):
            self.rows.pop(pos)
            self._save("已删除点位")

    def _add(self):
        if self.rows:
            new_idx = max(r[0] for r in self.rows) + 1
        else:
            new_idx = 1
        self.rows.append((new_idx, "新点位", "", ""))
        self._save("已新增点位，双击名称改名，点修改填 x/y")
        self.inner.update_idletasks()
        self.canvas.yview_moveto(1.0)      # 滚动到底部

    def _save(self, msg, close_dlg=None):
        write_points(self.rows)
        self._refresh()
        log(msg)
        if close_dlg:
            close_dlg.destroy()


# ================= 主界面 =================
# ================= 时间设置弹窗(两列多行: 标签 + 数字选择器) =================
class TimeDialog(tk.Toplevel):
    FONT = ("Microsoft YaHei UI", 10)

    def __init__(self, master, app=None):
        super().__init__(master)
        self.app = app
        self.title("时间设置")
        self.geometry("620x640")
        self.transient(master)
        self.grab_set()
        # 当前配置(副本), 确定时才写回到 app 并保存
        self.cfg = dict(app.time_cfg) if app else {}
        self.spins = {}
        wrap = tk.Frame(self)
        wrap.pack(fill=tk.BOTH, expand=True, padx=12, pady=10)
        inner = tk.Frame(wrap)
        inner.pack(fill=tk.BOTH, expand=True)
        keys = list(TIME_SETTINGS.keys())
        # 两列: 左列0..N/2, 右列N/2..
        half = (len(keys) + 1) // 2
        for col, klist in enumerate((keys[:half], keys[half:])):
            colf = tk.Frame(inner)
            colf.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=6)
            for i, k in enumerate(klist):
                lab, default = TIME_SETTINGS[k]
                row = tk.Frame(colf)
                row.pack(fill=tk.X, pady=3)
                tk.Label(row, text=lab, font=self.FONT, width=16, anchor="w"
                         ).pack(side=tk.LEFT)
                sv = tk.StringVar(value=str(self.cfg.get(k, default)))
                sp = tk.Spinbox(row, from_=0.0, to=60.0, increment=0.1,
                                textvariable=sv, width=7, font=self.FONT)
                sp.pack(side=tk.LEFT, padx=2)
                self.spins[k] = (sv, sp)
                tk.Label(row, text="秒", font=("Microsoft YaHei UI", 8),
                         fg="#888").pack(side=tk.LEFT)
        bar = tk.Frame(self)
        bar.pack(fill=tk.X, padx=12, pady=(0, 10))
        tk.Button(bar, text="恢复默认", width=10, font=self.FONT,
                  command=self._reset_default).pack(side=tk.LEFT)
        tk.Button(bar, text="取消", width=8, font=self.FONT,
                  command=self.destroy).pack(side=tk.RIGHT, padx=4)
        tk.Button(bar, text="确定", width=8, font=self.FONT,
                  command=self._save).pack(side=tk.RIGHT, padx=4)

    def _reset_default(self):
        for k, (_lab, default) in TIME_SETTINGS.items():
            if k in self.spins:
                self.spins[k][0].set(str(default))

    def _save(self):
        for k, (sv, _sp) in self.spins.items():
            try:
                self.cfg[k] = float(sv.get())
            except ValueError:
                pass
        if self.app:
            self.app.time_cfg = dict(self.cfg)
            self.app._save_timing()   # 保存到 ui_state
        self.destroy()


class StopSignal(BaseException):
    """采集停止信号：按 ESC 时抛出, 由最外层统一捕获结束采集
    继承 BaseException 而非 Exception, 避免被各处 except Exception 误捕获"""


def _log_tag(msg):
    """按日志内容返回控制台颜色 tag: err红/ok绿/warn橙/head蓝/默认灰
    判定顺序: head(分隔) → warn(警告/未命中) → err(失败) → ok(成功)"""
    m = str(msg)
    if m.strip().startswith(("=", "-", "═", "─")):
        return "head"
    if any(k in m for k in ("警告", "跳过", "未识别", "未找到", "已停止", "中止", "重试")):
        return "warn"
    if any(k in m for k in ("错误", "失败", "异常", "Error", "error:")):
        return "err"
    if any(k in m for k in ("完成", "成功", "已复制", "已启动", "加载完成", "识别到 ")):
        return "ok"
    return "def"


class App:
    def __init__(self, root):
        self.root = root
        self.root.title(APP_NAME if not VERSION else f"{APP_NAME} {VERSION}")
        # 默认窗口尺寸自适应：屏幕不够大时按屏幕缩（不写死，兼容小屏）
        _sw = root.winfo_screenwidth()
        _sh = root.winfo_screenheight()
        self.win_w = min(1240, max(900, _sw - 20))
        self.win_h = min(700, max(560, _sh - 60))
        self.min_w = min(1160, max(900, _sw - 20))
        self.min_h = min(600, max(520, _sh - 60))
        self.root.geometry(f"{self.win_w}x{self.win_h}")
        self.root.minsize(self.min_w, self.min_h)

        self.ui = load_ui_state()
        self.busy = False
        self.last_error = ""
        self._quota_error = False   # 豆包无额度标志(确认后停止后续调用)
        # 时间设置(可配置), 合并默认值
        self.time_cfg = {}
        for _k, (_lab, _def) in TIME_SETTINGS.items():
            try:
                self.time_cfg[_k] = float(self.ui.get("timing", {}).get(_k, _def))
            except (TypeError, ValueError):
                self.time_cfg[_k] = float(_def)
        self._abort_all = False     # 停止全部任务标志(评论采集致命错误)
        self._api_fail_streak = 0   # 豆包连续失败计数
        self._api_disabled = False  # 豆包连续失败3次后本批次禁用
        self.esc = EscListener()
        self.mouse_lock = MouseLock()
        self.stop_event = self.esc.stop_event
        # 拦截用户输入时触发右上角提示
        self._hint_win = None
        self._hint_after_id = None
        self.esc.on_block = self._queue_lock_hint
        self.mouse_lock.on_block = self._queue_lock_hint
        self.ui_queue = queue.Queue()   # 子线程 -> 主线程 UI 消息队列
        # 采集运行时状态(统一初始化, 避免各处 hasattr/getattr 防御)
        self._fetch_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="fetch")
        self._pending_futures = []
        self.collected_links = []
        self.collected_count = 0
        self._time_out_count = 0

        self._build_ui()
        self.reload_input()
        _utils.UI_LOG_HOOK = self.append_log

        self.root.protocol("WM_DELETE_WINDOW", self.on_exit)

    # ---------- 界面构建 ----------
    def _build_ui(self):
        root = self.root

        # ---- 顶部：状态栏 ----
        self.status_var = tk.StringVar(value="正在初始化...")
        tk.Label(root, textvariable=self.status_var,
                 font=("Microsoft YaHei UI", 12, "bold"),
                 anchor="w", padx=14, pady=8).pack(side=tk.TOP, fill=tk.X)

        # ---- 中部：左控制区(600) + 右任务区(1000) ----
        mid = tk.Frame(root)
        mid.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=14, pady=(0, 4))

        # ================= 左侧：控制区（600） =================
        left = tk.Frame(mid, width=600)
        left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        left.pack_propagate(False)

        # 1) 采集控制面板（顶部）
        ctrl = tk.LabelFrame(left, text=" 采集控制 ", font=("Microsoft YaHei UI", 10))
        ctrl.pack(side=tk.TOP, fill=tk.X)

        # 索引范围
        row1 = tk.Frame(ctrl)
        row1.pack(fill=tk.X, padx=10, pady=(6, 2))
        tk.Label(row1, text="索引范围:", font=("Microsoft YaHei UI", 10)).pack(side=tk.LEFT)
        self.idx_start_var = tk.StringVar(value=str(self.ui.get("idx_start", 0)))
        self.idx_end_var = tk.StringVar(value=str(self.ui.get("idx_end", 0)))
        tk.Entry(row1, textvariable=self.idx_start_var, width=6,
                 font=("Microsoft YaHei UI", 10)).pack(side=tk.LEFT, padx=4)
        tk.Label(row1, text=" 到 ", font=("Microsoft YaHei UI", 10)).pack(side=tk.LEFT)
        tk.Entry(row1, textvariable=self.idx_end_var, width=6,
                 font=("Microsoft YaHei UI", 10)).pack(side=tk.LEFT, padx=4)
        self.total_label = tk.Label(row1, text="", font=("Microsoft YaHei UI", 9),
                                    fg="#888888")
        self.total_label.pack(side=tk.LEFT)

        # 时间范围（单选，非自定义选项一行横排）
        row2 = tk.Frame(ctrl)
        row2.pack(fill=tk.X, padx=10, pady=2)
        tk.Label(row2, text="时间范围:", font=("Microsoft YaHei UI", 10)).pack(side=tk.LEFT)
        tframe = tk.Frame(row2)
        tframe.pack(side=tk.LEFT, padx=4)
        saved_tr = self.ui.get("time_range", "all")
        if saved_tr not in [k for k, _ in TIME_OPTIONS]:
            saved_tr = "all"
        self.time_var = tk.StringVar(value=saved_tr)
        for i, (key, label) in enumerate(TIME_OPTIONS[:-1]):   # 前5个（不含自定义）
            tk.Radiobutton(tframe, text=label, value=key, variable=self.time_var,
                           font=("Microsoft YaHei UI", 9),
                           anchor="w").grid(row=0, column=i, sticky="w", padx=3)

        # 自定义：单独一行（radio + 开始/结束日期选择器）
        row3 = tk.Frame(ctrl)
        row3.pack(fill=tk.X, padx=10, pady=2)
        tk.Radiobutton(row3, text="自定义", value=CUSTOM, variable=self.time_var,
                       font=("Microsoft YaHei UI", 9),
                       anchor="w").pack(side=tk.LEFT)
        today = date.today()
        # 自定义日期不记忆, 每次默认近3天
        self.custom_start_var = tk.StringVar(
            value=f"{(today - timedelta(days=3)):%Y-%m-%d}")
        self.custom_end_var = tk.StringVar(
            value=f"{today:%Y-%m-%d}")
        self.entry_start = tk.Entry(row3, textvariable=self.custom_start_var, width=11,
                                    font=("Microsoft YaHei UI", 9))
        self.entry_start.pack(side=tk.LEFT, padx=(6, 0))
        tk.Button(row3, text="日历", width=5, font=("Microsoft YaHei UI", 9),
                  command=lambda: DatePicker(row3, self.custom_start_var,
                                             "选择开始日期").pick()).pack(side=tk.LEFT, padx=2)
        tk.Label(row3, text=" ~ ", font=("Microsoft YaHei UI", 9)).pack(side=tk.LEFT)
        self.entry_end = tk.Entry(row3, textvariable=self.custom_end_var, width=11,
                                  font=("Microsoft YaHei UI", 9))
        self.entry_end.pack(side=tk.LEFT, padx=(0, 0))
        tk.Button(row3, text="日历", width=5, font=("Microsoft YaHei UI", 9),
                  command=lambda: DatePicker(row3, self.custom_end_var,
                                             "选择结束日期").pick()).pack(side=tk.LEFT, padx=2)

        # 最大采集数量
        row4 = tk.Frame(ctrl)
        row4.pack(fill=tk.X, padx=10, pady=2)
        tk.Label(row4, text="每公众号最大文章采集数量:", font=("Microsoft YaHei UI", 10)).pack(side=tk.LEFT)
        self.max_count_var = tk.StringVar(
            value=str(self.ui.get("max_count", "") or ""))
        tk.Spinbox(row4, from_=1, to=9999, textvariable=self.max_count_var, width=6,
                   font=("Microsoft YaHei UI", 10)).pack(side=tk.LEFT, padx=4)
        # tk.Spinbox 会把空字符串变量自动写成默认值(from_)，创建后显式恢复
        self.max_count_var.set(str(self.ui.get("max_count", "") or ""))
        tk.Label(row4, text="(空 = 无限)", font=("Microsoft YaHei UI", 9),
                 fg="#888888").pack(side=tk.LEFT)
        # 窗口分离开关：开启时点击点位2后额外点击点位11
        self.window_split_var = tk.BooleanVar(
            value=bool(self.ui.get("window_split", False)))
        tk.Checkbutton(row4, text="窗口分离", variable=self.window_split_var,
                       font=("Microsoft YaHei UI", 10)).pack(side=tk.LEFT, padx=(12, 0))

        # 采集开关
        row5 = tk.Frame(ctrl)
        row5.pack(fill=tk.X, padx=10, pady=(6, 2))
        self.capture_read_var = tk.BooleanVar(
            value=bool(self.ui.get("capture_read", False)))
        tk.Checkbutton(row5, text="采集阅读数", variable=self.capture_read_var,
                       font=("Microsoft YaHei UI", 10)).pack(side=tk.LEFT)
        self.capture_4metrics_var = tk.BooleanVar(
            value=bool(self.ui.get("capture_4metrics", False)))
        self.capture_4metrics_chk = tk.Checkbutton(row5, text="采集4指标",
                                                   variable=self.capture_4metrics_var,
                                                   font=("Microsoft YaHei UI", 10))
        self.capture_4metrics_chk.pack(side=tk.LEFT, padx=(12, 0))

        # 评论采集配置
        row5b = tk.Frame(ctrl)
        row5b.pack(fill=tk.X, padx=10, pady=(6, 2))
        tk.Label(row5b, text="一级评论采集数量:", font=("Microsoft YaHei UI", 9)
                 ).pack(side=tk.LEFT)
        _saved_l1 = str(self.ui.get("max_l1", 0) or "")   # 空=无限, 0=不采
        self.max_l1_var = tk.StringVar(value="")
        self.max_l1_spin = tk.Spinbox(row5b, from_=0, to=9999, textvariable=self.max_l1_var, width=5,
                                      font=("Microsoft YaHei UI", 10))
        self.max_l1_var.set(_saved_l1)   # Spinbox创建会回填0, 创建后覆盖为保存值(含空)
        self.max_l1_spin.pack(side=tk.LEFT, padx=(4, 0))
        tk.Label(row5b, text="每级二级评论采集数量:", font=("Microsoft YaHei UI", 9)
                 ).pack(side=tk.LEFT, padx=(8, 0))
        _saved_l2 = str(self.ui.get("max_l2", 0) or "")   # 空=无限, 0=不展
        self.max_l2_var = tk.StringVar(value="")
        self.max_l2_spin = tk.Spinbox(row5b, from_=0, to=9999, textvariable=self.max_l2_var, width=5,
                                      font=("Microsoft YaHei UI", 10))
        self.max_l2_var.set(_saved_l2)   # 同上
        self.max_l2_spin.pack(side=tk.LEFT, padx=(2, 0))

        # 联动: 一级评论≠0(采集评论) -> 4指标强制开启(置灰不可取消)
        #       一级评论=0(不采评论) -> 二级置灰默认0
        def _sync_comment_ui(*_a):
            _v1 = (self.max_l1_var.get() or "").strip()
            if _v1 != "0":
                # 采集评论: 4指标强制开启
                self.capture_4metrics_var.set(True)
                self.capture_4metrics_chk.config(state=tk.DISABLED)
                # 一级有效: 二级可设置
                self.max_l2_spin.config(state=tk.NORMAL)
            else:
                # 不采评论: 4指标恢复可自由选择
                self.capture_4metrics_chk.config(state=tk.NORMAL)
                # 一级=0: 二级置灰并默认0
                self.max_l2_var.set("0")
                self.max_l2_spin.config(state=tk.DISABLED)
        self.max_l1_var.trace_add("write", _sync_comment_ui)
        _sync_comment_ui()


        # 开始按钮 + 点位设置（同一栏，点位设置靠右小按钮）
        # 滚动距离 + 测试滚动 配置（紧凑排左）
        scroll_bar = tk.Frame(ctrl)
        scroll_bar.pack(fill=tk.X, padx=10, pady=(6, 2))
        tk.Label(scroll_bar, text="文章列表滚动:",
                 font=("Microsoft YaHei UI", 9)).pack(side=tk.LEFT)
        # 默认 = 屏幕高度 70%（若无记忆）
        _def_scroll = int(_u32().GetSystemMetrics(SM_CYSCREEN) * 0.7)
        saved_scroll = str(self.ui.get("scroll_px", _def_scroll))
        self.scroll_px_var = tk.StringVar(value=saved_scroll)
        tk.Spinbox(scroll_bar, from_=0, to=5000, increment=50,
                   textvariable=self.scroll_px_var, width=5,
                   font=("Microsoft YaHei UI", 9)).pack(side=tk.LEFT, padx=(3, 0))
        tk.Label(scroll_bar, text="px",
                 font=("Microsoft YaHei UI", 8), fg="#888888").pack(side=tk.LEFT, padx=1)
        # 测试滚动按钮（跟滚动距离一组）
        self.btn_scroll_test = tk.Button(scroll_bar, text="测试滚动", width=8,
                                         font=("Microsoft YaHei UI", 9),
                                         command=self.on_scroll_test)
        self.btn_scroll_test.pack(side=tk.LEFT, padx=4)
        # 评论区滚动距离 + 测试滚动
        tk.Label(scroll_bar, text="评论区滚动:",
                 font=("Microsoft YaHei UI", 9)).pack(side=tk.LEFT, padx=(14, 0))
        self.comment_scroll_px_var = tk.StringVar(
            value=str(self.ui.get("comment_scroll_px", 300)))
        tk.Spinbox(scroll_bar, from_=0, to=5000, increment=50,
                   textvariable=self.comment_scroll_px_var, width=5,
                   font=("Microsoft YaHei UI", 9)).pack(side=tk.LEFT, padx=(3, 0))
        tk.Label(scroll_bar, text="px",
                 font=("Microsoft YaHei UI", 8), fg="#888888").pack(side=tk.LEFT, padx=1)
        self.btn_comment_scroll_test = tk.Button(scroll_bar, text="测试滚动", width=8,
                                                 font=("Microsoft YaHei UI", 9),
                                                 command=self.on_comment_scroll_test)
        self.btn_comment_scroll_test.pack(side=tk.LEFT, padx=4)

        # 豆包 API Key（密码式输入，滚动距离下方一行）
        row6 = tk.Frame(ctrl)
        row6.pack(fill=tk.X, padx=10, pady=(6, 2))
        tk.Label(row6, text="豆包API Key:", font=("Microsoft YaHei UI", 9)).pack(side=tk.LEFT)
        self.doubao_key_var = tk.StringVar(
            value=str(self.ui.get("doubao_api_key", "") or ""))
        self.doubao_key_entry = tk.Entry(row6, textvariable=self.doubao_key_var, width=34,
                                         show="*", font=("Microsoft YaHei UI", 9))
        self.doubao_key_entry.pack(side=tk.LEFT, padx=(4, 0))
        self.show_key_var = tk.BooleanVar(value=False)
        tk.Checkbutton(row6, text="显示", variable=self.show_key_var,
                       font=("Microsoft YaHei UI", 9),
                       command=self.toggle_key_show).pack(side=tk.LEFT, padx=(4, 0))
        btn_bar = tk.Frame(ctrl)
        btn_bar.pack(fill=tk.X, padx=10, pady=(4, 6))
        self.btn_time = tk.Button(btn_bar, text="时间设置", width=10,
                                   font=("Microsoft YaHei UI", 12),
                                   command=self.open_time_dialog)
        self.btn_time.pack(side=tk.RIGHT, padx=(6, 0))
        self.btn_points = tk.Button(btn_bar, text="点位设置", width=10,
                                    font=("Microsoft YaHei UI", 12),
                                    command=self.open_points_dialog)
        self.btn_points.pack(side=tk.RIGHT, padx=(10, 0))
        self.btn_start = tk.Button(btn_bar, text="开始", width=16,
                                   font=("Microsoft YaHei UI", 12, "bold"),
                                   bg="#1565c0", fg="white",
                                   activebackground="#0d47a1", activeforeground="white",
                                   command=self.on_start)
        self.btn_start.pack(side=tk.LEFT, fill=tk.X, expand=True)

        # 进度区（开始按钮下面）
        self.progress_var = tk.StringVar(value="进度: 待开始")
        tk.Label(ctrl, textvariable=self.progress_var,
                 font=("Microsoft YaHei UI", 10, "bold"),
                 fg="#1565c0", anchor="w").pack(fill=tk.X, padx=10, pady=(0, 2))
        self.pbar = ttk.Progressbar(ctrl, maximum=100)
        self.pbar.pack(fill=tk.X, padx=10, pady=(0, 8))

        # 2) 控制台（日志）（下面，占剩余空间）
        log_box = tk.LabelFrame(left, text=" 控制台（日志） ", font=("Microsoft YaHei UI", 10))
        log_box.pack(side=tk.TOP, fill=tk.BOTH, expand=True, pady=(6, 0))
        self.text = scrolledtext.ScrolledText(
            log_box, state="disabled", wrap="word",
            font=("Microsoft YaHei UI", 10),
            relief=tk.GROOVE, borderwidth=1)
        self.text.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)
        # 日志颜色分级
        self.text.tag_configure("err", foreground="#c62828")
        self.text.tag_configure("ok", foreground="#2e7d32")
        self.text.tag_configure("warn", foreground="#e65100")
        self.text.tag_configure("head", foreground="#1565c0", font=("Microsoft YaHei UI", 10, "bold"))
        self.text.tag_configure("def", foreground="#555555")

        # ================= 右侧：任务区（600） =================
        right = tk.Frame(mid, width=600)
        right.pack(side=tk.RIGHT, fill=tk.BOTH, expand=False, padx=(10, 0))
        right.pack_propagate(False)

        task = tk.LabelFrame(right, text=" 任务区（input 数据，双击单元格编辑） ",
                             font=("Microsoft YaHei UI", 10))
        task.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        # 表格：操作(重置/删除) | 公众号名称 | 链接 | 状态 | 备注
        cols = ("op", "name", "url", "status", "remark")
        self.tree = ttk.Treeview(task, columns=cols, show="headings")
        self.tree.heading("op", text="操作")
        self.tree.heading("name", text="公众号名称")
        self.tree.heading("url", text="链接")
        self.tree.heading("status", text="状态")
        self.tree.heading("remark", text="备注")
        self.tree.column("op", width=96, anchor="center", stretch=False)
        self.tree.column("name", width=140, anchor="w", stretch=False)
        self.tree.column("url", width=210, anchor="w", stretch=True)
        self.tree.column("status", width=120, anchor="w", stretch=False)
        self.tree.column("remark", width=150, anchor="w", stretch=False)
        vsb = ttk.Scrollbar(task, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        hsb = ttk.Scrollbar(task, orient="horizontal", command=self.tree.xview)
        self.tree.configure(xscrollcommand=hsb.set)
        hsb.pack(side=tk.BOTTOM, fill=tk.X)
        self.tree.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)

        # 双击编辑 / 单击操作列删除
        self.tree.bind("<Double-1>", self._on_tree_double_click)
        self.tree.bind("<Button-1>", self._on_tree_click)

        # 底部按钮：重置 / 新增
        btns = tk.Frame(task)
        btns.pack(fill=tk.X, padx=6, pady=(0, 6))
        self.btn_reset = tk.Button(btns, text="重置", width=10,
                                   font=("Microsoft YaHei UI", 10),
                                   command=self.on_reset)
        self.btn_reset.pack(side=tk.RIGHT, padx=4)
        self.btn_add = tk.Button(btns, text="新增", width=10,
                                 font=("Microsoft YaHei UI", 10),
                                 command=self.on_add)
        self.btn_add.pack(side=tk.RIGHT, padx=4)

        # ---- 底部：微信版本（靠右） ----
        bottom = tk.Frame(root)
        bottom.pack(side=tk.BOTTOM, fill=tk.X, padx=14, pady=4)
        tk.Label(bottom, text=f"微信 PC 版 {WECHAT_VERSION}",
                 font=("Microsoft YaHei UI", 9),
                 fg="#888888", anchor="e").pack(side=tk.RIGHT)

        # 设置记忆：任何变更自动保存
        for v in (self.idx_start_var, self.idx_end_var, self.time_var,
                  self.max_count_var, self.scroll_px_var, self.comment_scroll_px_var,
                  self.max_l1_var, self.max_l2_var):
            v.trace_add("write", lambda *a: self._save_state())

        # 时间范围变更时启用/禁用自定义日期行
        self.time_var.trace_add("write", lambda *a: self._update_custom_state())
        self._update_custom_state()

        # 快捷键：回车 = 点击开始（焦点在输入框时不触发）
        root.bind("<Return>", self._on_return_key)

        # 窗口居中（按实际尺寸）
        root.update_idletasks()
        x = (root.winfo_screenwidth() - self.win_w) // 2
        y = (root.winfo_screenheight() - self.win_h) // 2
        root.geometry(f"+{x}+{y}")

    # ---------- 任务区数据 ----------
    def _update_title(self):
        """大标题同步 input 情况：有效链接数 / 待处理数"""
        try:
            total = len(self.input_rows)
            todo = sum(1 for _, _, _, st, _rm in self.input_rows
                       if st in ("pending", "null") or "error" in st)
            self.status_var.set(f"有效链接 {total} 个（待处理 {todo} 个）")
        except Exception:
            pass

    def reload_input(self, msg=None):
        """从 input.csv 重新加载：刷新表格 + 同步有效行 + 更新索引上限"""
        self.rows_all = load_raw_input_rows()
        self.input_rows = load_input_rows()
        self._refresh_tree()
        total = len(self.input_rows)
        self.total_label.config(text=f"有效链接 {total} 个")
        self._update_title()   # 大标题同步 input 情况
        try:
            cur_end = int(self.idx_end_var.get())
        except ValueError:
            cur_end = 0
        if self.ui.get("idx_end") is None or msg is None:
            self.idx_end_var.set(str(max(total - 1, 0)))
        if msg:
            log(msg)

    def _refresh_tree(self):
        """按 rows_all 刷新表格内容"""
        self.tree.delete(*self.tree.get_children())
        for pos, (idx, url, name, st, remark) in enumerate(self.rows_all):
            tag = ""
            if st == "pending":
                tag = "pending"
            elif "error" in st:
                tag = "error"
            self.tree.insert("", "end", iid=str(pos),
                             values=("重置 删除", name, url, st, remark), tags=(tag,))
        self.tree.tag_configure("pending", background="#fff8e1")
        self.tree.tag_configure("error", background="#ffebee")

    def _save_input(self, log_msg):
        """rows_all 写回 input.csv 并刷新；自动修正：链接已填写但状态为 null 的行改为 pending"""
        auto = 0
        for i, (idx, url, name, st, remark) in enumerate(self.rows_all):
            if st == "null" and url:
                self.rows_all[i] = (idx, url, name, "pending", remark)
                auto += 1
        write_input_csv(self.rows_all)
        self.reload_input(log_msg)
        if auto:
            log(f"状态修正: {auto} 个已填写链接但状态为 null 的行自动改为 pending")

    # ---------- 任务区交互：编辑 / 删除 / 重置 / 新增 ----------
    def _on_tree_click(self, event):
        """单击：命中操作列 -> 左半=重置, 右半=删除"""
        rowid = self.tree.identify_row(event.y)
        col = self.tree.identify_column(event.x)
        if not rowid or col != "#1":        # 非操作列
            return
        bbox = self.tree.bbox(rowid, col)
        if bbox and event.x < bbox[0] + bbox[2] / 2:
            self._reset_row(rowid)          # 左半: 重置
        else:
            self._delete_row(rowid)         # 右半: 删除

    def _on_tree_double_click(self, event):
        """双击：编辑单元格（索引列只读）"""
        rowid = self.tree.identify_row(event.y)
        col = self.tree.identify_column(event.x)
        if not rowid or not col:
            return
        col_idx = int(col.replace("#", "")) - 1
        if col_idx == 0:                    # 操作列(最左): 左半重置右半删除
            this_col = self.tree.identify_column(event.x)
            bb = self.tree.bbox(rowid, this_col)
            if bb and event.x < bb[0] + bb[2] / 2:
                self._reset_row(rowid)
            else:
                self._delete_row(rowid)
            return
        bbox = self.tree.bbox(rowid, col)
        if not bbox:
            return
        x, y, w, h = bbox
        values = self.tree.item(rowid, "values")
        e = tk.Entry(self.tree)
        e.place(x=x, y=y, width=w, height=h)
        e.insert(0, str(values[col_idx]))
        e.focus_set()
        e.select_range(0, "end")
        state = {"committed": False}
        e.bind("<Return>", lambda ev: self._commit_edit(rowid, col_idx, e, state))
        e.bind("<Escape>", lambda ev: (setattr(state, "committed", True), e.destroy()))
        e.bind("<FocusOut>", lambda ev: self._commit_edit(rowid, col_idx, e, state))

    def _commit_edit(self, rowid, col_idx, entry, state):
        """提交单元格编辑：写回内存并落盘"""
        if state.get("committed"):
            return
        state["committed"] = True
        try:
            new_val = entry.get().strip()
        except Exception:
            return
        entry.destroy()
        pos = int(rowid)
        if pos >= len(self.rows_all):
            return
        row = list(self.rows_all[pos])
        old_val = row[col_idx]
        row[col_idx] = new_val
        self.rows_all[pos] = tuple(row)
        if new_val != old_val:
            self._save_input(f"已修改: [{row[0]}] 列[{col_idx}] {old_val[:30]} -> {new_val[:30]}")

    def _delete_row(self, rowid):
        """删除表格行（带确认）"""
        if not rowid:
            return
        pos = int(rowid)
        if pos >= len(self.rows_all):
            return
        idx, url, name, st, _rm = self.rows_all[pos]
        if not messagebox.askyesno("删除确认", f"确定删除第 {idx} 行？\n{name or url[:50] or '(空)'}"):
            return
        self.rows_all.pop(pos)
        self._save_input(f"已删除: [{idx}] {name}")

    def _reset_row(self, rowid):
        """单独重置该行: 状态改为 pending
        有链接 -> pending; 无链接 -> null; 备注重置? 保留"""
        if not rowid:
            return
        pos = int(rowid)
        if pos >= len(self.rows_all):
            return
        idx, url, name, st, remark = self.rows_all[pos]
        new_st = "pending" if url else "null"
        if st == new_st:
            log(f"第 {idx} 行已是 {new_st}，无需重置")
            self._save_input(f"第 {idx} 行已是 {new_st}")
            return
        self.rows_all[pos] = (idx, url, name, new_st, remark)
        self._save_input(f"已重置: [{idx}] {name} -> {new_st}")

    def on_reset(self):
        """重置：把所有行状态改为 pending，然后重新加载 input.csv"""
        if not messagebox.askyesno("重置确认",
                                   "将所有链接状态重置为 pending（待采集）？\n链接为空的行状态设为 null，\n该操作会覆盖现有状态(done/error/null)。"):
            return
        rows = load_raw_input_rows()
        rows = [(idx, url, name, "pending" if url else "null", "")
                for idx, url, name, _st, _rm in rows]
        write_input_csv(rows)
        self.reload_input("已重置: 状态改为 pending/null，备注已清空，并重新加载 input.csv")

    def on_add(self):
        """新增：在最前面插入一行空记录（双击编辑）"""
        if not self.rows_all:
            new_idx = 0
        else:
            new_idx = min(r[0] for r in self.rows_all) - 1
        self.rows_all.insert(0, (new_idx, "", "", "null", ""))
        self._save_input(f"已新增空行 [索引 {new_idx}]，双击链接/名称列填写内容，状态默认 null")

    # ---------- 控制区逻辑 ----------
    def _on_return_key(self, event):
        """回车 = 点击开始（避免焦点在输入框时误触）"""
        try:
            w = self.root.focus_get()
            if isinstance(w, (tk.Entry, tk.Spinbox)):
                return
        except Exception:
            pass
        self.on_start()

    def _update_custom_state(self):
        """自定义时间范围选中时启用日期选择，否则禁用"""
        st = tk.NORMAL if self.time_var.get() == CUSTOM else tk.DISABLED
        for w in (self.entry_start, self.entry_end):
            try:
                w.config(state=st)
            except Exception:
                pass

    def open_points_dialog(self):
        """打开点位设置弹窗"""
        PointsDialog(self.root)

    def open_time_dialog(self):
        """打开时间设置弹窗"""
        TimeDialog(self.root, self)

    def _save_timing(self):
        """保存时间设置到 ui_state.json"""
        try:
            st = load_ui_state() or {}
            st["timing"] = {k: str(v) for k, v in self.time_cfg.items()}
            save_ui_state(st)
        except Exception as e:
            log(f"保存时间设置失败: {e}")

    def toggle_key_show(self):
        """豆包 API Key 显示/隐藏切换"""
        try:
            self.doubao_key_entry.config(show="" if self.show_key_var.get() else "*")
        except Exception:
            pass

    def on_comment_scroll_test(self):
        """测试评论区滚动：鼠标移到点位23, 按配置距离向下滚动"""
        pts = {p[0]: p for p in load_points()}
        p23 = pts.get(23)
        if not p23:
            log("错误: 缺少点位23，无法测试评论区滚动")
            return
        try:
            px = int(float(self.comment_scroll_px_var.get()))
        except ValueError:
            log("评论区滚动距离格式错误，请输入数字")
            return
        log(f"测试评论区滚动: 鼠标移到点位23({p23[2]},{p23[3]}) 向下滚动 {px}px")
        scroll_down_at(int(p23[2]), int(p23[3]), px)

    def on_scroll_test(self):
        """测试滚动：鼠标移到点位7，按配置的滚动距离向下滚动（人工已打开文章列表时用）"""
        pts = {p[0]: p for p in load_points()}
        p7 = pts.get(7)
        if not p7:
            log("错误: 缺少点位7，无法测试滚动")
            return
        try:
            px = int(float(self.scroll_px_var.get()))
        except ValueError:
            log("滚动距离格式错误，请输入数字")
            return
        if px <= 0:
            log("滚动距离应大于 0")
            return
        log(f"测试滚动: 鼠标移到点位7({p7[2]},{p7[3]}) 向下滚动 {px}px")
        scroll_down_at(int(p7[2]), int(p7[3]), px)

    def append_log(self, msg):
        """日志：放入队列，由主线程轮询写入控制台（子线程安全）"""
        try:
            self.ui_queue.put(("log", msg, _log_tag(msg)))
        except Exception:
            pass

    def _poll_ui_queue(self):
        """主线程轮询处理 UI 队列（日志/进度/窗口操作/采集结束）"""
        try:
            while True:
                item = self.ui_queue.get_nowait()
                kind = item[0]
                if kind == "log":
                    self.text.configure(state="normal")
                    self.text.insert("end", item[1] + "\n", item[2] if len(item) > 2 else "def")
                    self.text.see("end")
                    self.text.configure(state="disabled")
                elif kind == "progress":
                    self.progress_var.set(item[1])
                    self.pbar.config(value=item[2])
                elif kind == "snap":
                    self._snap_main_right()
                elif kind == "refresh_input":
                    self.reload_input("")      # 静默刷新任务区（状态已更新）
                elif kind == "lock_hint":
                    self._show_lock_hint()
                elif kind == "finish":
                    self._finish_collection(item[1], item[2], item[3])
        except queue.Empty:
            pass
        except Exception:
            pass
        try:
            self.root.after(50, self._poll_ui_queue)
        except Exception:
            pass

    def _queue_lock_hint(self):
        """钩子子线程调用：往 UI 队列放提示消息（主线程显示弹窗）"""
        try:
            self.ui_queue.put(("lock_hint",))
        except Exception:
            pass

    def _show_lock_hint(self):
        """右上角提示弹窗：显示当前正在采集、输入已禁用，1 秒后自动消失"""
        try:
            # 已有弹窗：直接重置消失计时，不重建（避免鼠标移动高频重建）
            if self._hint_win is not None:
                try:
                    self._hint_win.after_cancel(self._hint_after_id)
                except Exception:
                    pass
                try:
                    self._hint_win.after(1000, lambda: self._close_lock_hint(self._hint_win))
                except Exception:
                    pass
                return
            win = tk.Toplevel(self.root)
            win.overrideredirect(True)          # 无边框
            win.attributes("-topmost", True)    # 置顶
            win.attributes("-alpha", 0.95)      # 略透明
            sw = win.winfo_screenwidth()
            w, h = 420, 120
            x, y = sw - w - 16, 16              # 右上角
            win.geometry(f"{w}x{h}+{x}+{y}")
            frame = tk.Frame(win, bg="#fff3cd", highlightthickness=1,
                             highlightbackground="#e0a800")
            frame.pack(fill="both", expand=True)
            tk.Label(frame, text="⚠ 当前正常进行采集任务",
                     font=("微软雅黑", 13, "bold"),
                     bg="#fff3cd", fg="#856404").pack(pady=(12, 4))
            tk.Label(frame, text="鼠标和键盘操作已禁用\n可按 ESC 结束采集进程",
                     font=("微软雅黑", 11),
                     bg="#fff3cd", fg="#856404").pack(pady=(0, 12))
            self._hint_win = win
            self._hint_after_id = win.after(1000, lambda: self._close_lock_hint(win))
        except Exception:
            pass

    def _close_lock_hint(self, win):
        """关闭提示弹窗"""
        try:
            if self._hint_win is win:
                self._hint_win = None
            win.destroy()
        except Exception:
            pass

    def _save_state(self, *_a):
        save_ui_state({
            "idx_start": self.idx_start_var.get(),
            "idx_end": self.idx_end_var.get(),
            "time_range": self.time_var.get(),
            "max_count": self.max_count_var.get(),
            "scroll_px": self.scroll_px_var.get(),
            "comment_scroll_px": self.comment_scroll_px_var.get(),
            "window_split": self.window_split_var.get(),
            "capture_read": self.capture_read_var.get(),
            "capture_4metrics": self.capture_4metrics_var.get(),
            "max_l1": self.max_l1_var.get(),
            "max_l2": self.max_l2_var.get(),
            "doubao_api_key": self.doubao_key_var.get(),
        })

    # ---------- 窗口布局（采集时微信左半屏 / main 右半屏） ----------
    def _snap_main_right(self):
        """main 窗口靠右半边屏幕（采集时与微信并排）"""
        try:
            sw = self.root.winfo_screenwidth()
            sh = self.root.winfo_screenheight()
            self.root.minsize(200, 200)
            self.root.geometry(f"{sw // 2}x{sh}+{sw // 2}+0")
        except Exception:
            pass

    def _restore_main(self):
        """恢复 main 窗口到默认大小并居中（预留，当前停止后保持右半屏不调用）"""
        try:
            self.root.minsize(self.min_w, self.min_h)
            self.root.geometry(f"{self.win_w}x{self.win_h}")
            sw = self.root.winfo_screenwidth()
            sh = self.root.winfo_screenheight()
            self.root.geometry(f"+{(sw - self.win_w) // 2}+{(sh - self.win_h) // 2}")
        except Exception:
            pass

    # ---------- 启动 ----------
    def start(self):
        # 启动 UI 队列轮询（主线程定时处理子线程消息）
        self.root.after(50, self._poll_ui_queue)
        # 隐藏任务栏（采集时屏幕全高）；退出时由 atexit 恢复
        if hide_taskbar():
            log("已隐藏任务栏（程序退出时自动恢复）")
        total = len(self.input_rows)
        todo = sum(1 for _, _, _, st, _rm in self.input_rows
                   if st in ("pending", "null") or "error" in st)
        self.idx_end_var.set(str(max(total - 1, 0)))
        self.status_var.set(f"已加载 {total} 个公众号（待处理 {todo} 个）")
        log(f"{APP_NAME} 已启动")
        log(f"已加载 {CONFIG_DIR}/{INPUT_CSV}: {total} 个有效公众号（pending/null/error 共 {todo} 个）")
        log(f"微信 PC 版: {WECHAT_VERSION}（程序版本 {VERSION}）")
        log(f"记忆设置已读取: 时间范围[{dict(TIME_OPTIONS).get(self.time_var.get(), '?')}] "
            f"最大数量[{self.max_count_var.get() or '无限'}] "
            f"窗口分离[{('开' if self.window_split_var.get() else '关')}] "
            f"采集阅读[{('开' if self.capture_read_var.get() else '关')}] "
            f"采集4指标[{('开' if self.capture_4metrics_var.get() else '关')}] "
            f"一级评论[{self.max_l1_var.get()}] 每级二级[{self.max_l2_var.get()}]")
        log("右侧任务区可编辑 input 数据（双击单元格修改，操作列删除，底部重置/新增）")
        log("请在左侧采集控制设置索引范围、时间范围、最大数量后点击【开始】（或按回车）")
        if not self.input_rows:
            log("警告: input.csv 中没有有效链接，请先在任务区新增或填写数据")

    # ---------- 开始按钮（状态机；采集动作当前为模拟，待接入真实流程） ----------
    def _resolve_time_range(self, tr, cstart, cend):
        """把时间范围选择解析为 (起始date, 结束date)；不限返回 None"""
        today = date.today()
        if tr == "today":
            return (today, today)
        if tr == "week":
            return (today - timedelta(days=7), today)
        if tr == "month":
            return (today - timedelta(days=30), today)
        if tr == "year":
            return (today - timedelta(days=365), today)
        if tr == CUSTOM:
            ds, de = parse_date(cstart), parse_date(cend)
            if ds and de and ds <= de:
                return (ds, de)
        return None

    def on_start(self):
        if self.busy:
            log("收到停止请求，正在停止 ...")
            self.stop_event.set()
            try:
                self.btn_start.config(state=tk.DISABLED, text="停止中...")
            except Exception:
                pass
            return
        total = len(self.input_rows)
        if total == 0:
            log("input.csv 中没有有效链接")
            return
        try:
            s = int(self.idx_start_var.get())
            e = int(self.idx_end_var.get())
        except ValueError:
            log("索引格式错误，请输入数字")
            return
        s = max(0, min(s, total - 1))
        e = max(0, min(e, total - 1))
        if s > e:
            log("起始索引大于结束索引")
            return

        # 时间范围校验（自定义需开始 + 结束日期）
        tr = self.time_var.get()
        cstart = self.custom_start_var.get().strip()
        cend = self.custom_end_var.get().strip()
        if tr == CUSTOM:
            ds, de = parse_date(cstart), parse_date(cend)
            if not ds or not de:
                log("自定义日期格式错误，应为 YYYY-MM-DD")
                return
            if ds > de:
                log("开始日期晚于结束日期")
                return

        # 最大采集数量（空 = 无限）
        mc = self.max_count_var.get().strip()
        if mc:
            try:
                max_count = int(float(mc))
            except ValueError:
                log("最大采集数量格式错误，应为数字或留空(无限)")
                return
            if max_count < 1:
                max_count = None
        else:
            max_count = None

        # 解析时间范围为日期区间（None = 不限）
        time_range_dates = self._resolve_time_range(tr, cstart, cend)
        # 固定下载目录（不按开始时间分目录，一批任务可多次进行）
        self.session_dir = os.path.join(_data_dir(), "下载")
        self.max_count_setting = max_count
        self.time_range_dates = time_range_dates
        self.is_custom_mode = (tr == CUSTOM)   # 自定义时间范围模式标志
        log(f"文章保存目录: {self.session_dir}")
        # 预加载 OCR 引擎：点击开始时加载一次，采集中复用（避免首个任务首次使用时的卡顿）
        get_ocr_engine()
        rows = self.input_rows[s:e + 1]
        todo = [r for r in rows if r[3] in ("pending", "null") or "error" in r[3]]
        desc = time_range_desc(tr, cstart, cend)
        log("=" * 46)
        log(f"即将采集: 索引 {s}-{e}，共 {len(rows)} 个公众号，待处理 {len(todo)} 个")
        log(f"时间范围: {desc}")
        log(f"每公众号最大采集数量: {'无限' if max_count is None else max_count}")
        if not todo:
            log("范围内没有待处理(pending/null/error)的链接，无需采集")
            return
        log("待处理列表:")
        for idx, url, name, st, _rm in todo:
            log(f"  [{idx}] {name}  ({st})")

        # 微信窗口检查：找不到则暂停并提示，按钮保持【开始】
        wx = find_wechat_window()
        if wx is None:
            log("错误: 未找到微信窗口，暂停采集")
            messagebox.showwarning(
                "微信未找到",
                "未找到微信窗口。\n\n请先启动微信后再点击【开始】。")
            return
        log(f"已找到微信窗口: [{wx[1]}] (PID={wx[2]})")
        # 启动 ESC 键监听（采集中按 ESC 立即停止；幂等）
        if self.esc.start():
            log("ESC 键监听已启用（采集中按 ESC 可立即停止）")
        else:
            log("警告: ESC 键监听启动失败")
        # 锁定鼠标移动（防止误操作干扰采集；程序 SetCursorPos 不受影响）
        if self.mouse_lock.start():
            log("鼠标已锁定（移动/点击/滚轮禁用）")
        else:
            log("警告: 鼠标锁定启动失败")
        # 锁定键盘输入（仅放行 ESC 和程序自己的输入）
        self.esc._block_keys = True
        log("键盘已锁定（仅 ESC 可用）")
        # 立即前置微信并靠左半边屏幕（已就位则跳过）
        moved = snap_wechat_left(wx[0])
        log(f"微信窗口: 前置并靠左半屏{'（已就位，跳过）' if not moved else ''}")

        # 进入运行状态
        self.busy = True
        self.stop_event.clear()
        try:
            self.btn_start.config(state=tk.NORMAL, text="结束")
        except Exception:
            pass
        self._set_progress(f"进度: 0/{len(todo)} 开始采集")
        # main 窗口靠右半边屏幕（主线程执行）
        self._snap_main_right()
        threading.Thread(target=self._run_collection,
                         args=(todo, desc, max_count, wx), daemon=True).start()

    def _run_collection(self, todo, desc, max_count, wx):
        """采集线程：遍历任务，每个任务执行点位操作流程"""
        total = len(todo)
        done_n = 0
        # 本批次开始: 重置豆包失败计数
        self._api_fail_streak = 0
        self._api_disabled = False
        try:
            for n, (idx, url, name, st, _rm) in enumerate(todo):
                self._check_stop()
                if self._abort_all:
                    log("检测到中止标志，停止剩余任务")
                    break
                log(f"════════ 任务 {n + 1}/{total} · {name} ════════")
                log(f"【{n + 1}/{total}】[{idx}] {name}  {url[:45]}{'...' if len(url) > 45 else ''}")
                # main 界面靠右半边屏幕（通过队列交给主线程处理）
                self.ui_queue.put(("snap",))
                ok = self._process_task(idx, url, name, wx)
                self._check_stop()
                if ok:
                    update_input_status(idx, "done")
                    log(f"任务 {idx} 完成，状态=done")
                    done_n += 1
                else:
                    update_input_status(idx, f"error:{self.last_error or '流程失败'}")
                    log(f"任务 {idx} 失败，状态=error: {self.last_error}")
                # 通知主线程刷新任务区（状态已写入 input.csv）
                self.ui_queue.put(("refresh_input",))
                self._set_progress(f"进度: {n + 1}/{total}（{name}）",
                                   (n + 1) / total * 100)
        except StopSignal:
            log("已停止：ESC 中止采集")
        except Exception as e:
            log(f"采集线程异常: {e}")
        finally:
            # 解锁鼠标和键盘（防止采集结束后仍被锁定）
            self.mouse_lock.stop()
            self.esc._block_keys = False
            log("鼠标/键盘已解锁")
            self.ui_queue.put(("finish", self.stop_event.is_set(), total, done_n))

    def ts(self, name):
        """读取命名时间配置值(秒); 未知名称/异常返回默认值"""
        try:
            return float(self.time_cfg.get(name, TIME_SETTINGS.get(name, (None, 0.3))[1]))
        except Exception:
            return 0.3

    def _sleep(self, seconds):
        """可中断 sleep：分段检查停止信号。被停止时抛 StopSignal 结束采集"""
        end = time.time() + seconds
        while time.time() < end:
            if self.stop_event.is_set():
                raise StopSignal()
            time.sleep(min(0.2, max(0.01, end - time.time())))

    def _check_stop(self):
        """统一停止检查点：已停止则抛 StopSignal(由最外层捕获)"""
        if self.stop_event.is_set():
            raise StopSignal()

    def _process_task(self, idx, url, name, wx):
        """单个任务流程：
        1) 聚焦微信窗口，检查是否左半屏，不是则移动并等待0.5秒
        2) 点击点位1 -> 等0.5秒 -> 输入1 -> 删除 -> 点击点位2
        3) Ctrl+Shift+W
        4) 再次：点位1 -> 输入1 -> 删除 -> 点位2（触发新窗口）
        5) 新窗口调整到左半屏并聚焦（位置没错则仅聚焦）
        6) 点击点位3 -> 全选删除 -> 输入任务链接（模仿旧项目输入）-> 按回车
        7) 等待5秒 -> 点击点位4"""
        # 1) 聚焦微信并确保左半屏
        if wx:
            moved = snap_wechat_left(wx[0])
            if moved:
                log(f"微信窗口: 已移动到左半屏 [{wx[1]}]，等待0.3秒")
                self._sleep(0.3)
            else:
                log(f"微信窗口: 已在左半屏 [{wx[1]}]，不动")
        # 加载点位
        pts = {p[0]: p for p in load_points()}
        p1 = pts.get(1)
        p2 = pts.get(2)
        p11 = pts.get(11)
        window_split = self.window_split_var.get()
        if not p1 or not p2:
            log("错误: 缺少点位1或点位2，任务失败")
            self.last_error = "缺少点位1/2"
            return False
        # 2) 点击点位1（搜索框）-> 输入1 -> 删除 -> 点击点位2
        log(f"点击点位1({p1[2]},{p1[3]}) {p1[1]}")
        mouse_click(p1[2], p1[3])
        log("输入 1")
        type_text("1")
        self._sleep(0.3)
        log("删除")
        ctrl_key("A")          # 全选（光标在末尾时 Delete 删不掉，先全选）
        self._sleep(0.15)
        key_press(VK_DELETE)
        self._sleep(0.3)
        log(f"点击点位2({p2[2]},{p2[3]}) {p2[1]}")
        mouse_click(p2[2], p2[3])
        self._sleep(0.5)
        # 窗口分离开启：点击点位2后额外点击点位11
        if window_split:
            if not p11:
                log("错误: 缺少点位11（窗口分离已开启），任务失败")
                self.last_error = "缺少点位11"
                return False
            try:
                px11, py11 = int(p11[2]), int(p11[3])
            except (TypeError, ValueError):
                px11 = py11 = 0
            if px11 <= 0 and py11 <= 0:
                log("错误: 点位11坐标未采集（窗口分离已开启），任务失败")
                self.last_error = "缺少点位11"
                return False
            log(f"点击点位11({px11},{py11}) {p11[1]}")
            mouse_click(px11, py11)
            self._sleep(0.3)
        # 3) Ctrl+Shift+W
        log("触发 Ctrl+Shift+W")
        ctrl_shift_key("W")
        self._sleep(0.8)
        # 4) 再次：点位1 -> 输入1 -> 删除 -> 点位2（触发新窗口）
        log(f"点击点位1({p1[2]},{p1[3]}) {p1[1]}")
        mouse_click(p1[2], p1[3])
        log("输入 1")
        type_text("1")
        self._sleep(0.3)
        log("删除")
        ctrl_key("A")
        self._sleep(0.15)
        key_press(VK_DELETE)
        self._sleep(0.3)
        log(f"点击点位2({p2[2]},{p2[3]}) {p2[1]}")
        mouse_click(p2[2], p2[3])
        self._sleep(0.5)
        # 窗口分离开启：点击点位2后额外点击点位11
        if window_split:
            if not p11:
                log("错误: 缺少点位11（窗口分离已开启），任务失败")
                self.last_error = "缺少点位11"
                return False
            try:
                px11, py11 = int(p11[2]), int(p11[3])
            except (TypeError, ValueError):
                px11 = py11 = 0
            if px11 <= 0 and py11 <= 0:
                log("错误: 点位11坐标未采集（窗口分离已开启），任务失败")
                self.last_error = "缺少点位11"
                return False
            log(f"点击点位11({px11},{py11}) {p11[1]}")
            mouse_click(px11, py11)
            self._sleep(0.3)
        # 5) 新窗口：调整到左半屏并聚焦（已就位则仅聚焦）
        new_win = get_foreground_window_info()
        if new_win:
            moved = snap_wechat_left(new_win[0])
            log(f"新窗口: 调整左半屏并聚焦{'（已就位，仅聚焦）' if not moved else ''} [{new_win[1]}]")
        else:
            log("警告: 未获取到新窗口")
        # 6) 点击点位3 -> 全选删除 -> 输入任务链接（模仿旧项目输入）
        p3 = pts.get(3)
        if not p3:
            log("错误: 缺少点位3，无法输入链接")
            self.last_error = "缺少点位3"
            return False
        log(f"点击点位3({p3[2]},{p3[3]}) {p3[1]}")
        mouse_click(p3[2], p3[3])
        ctrl_key("A")          # 全选
        self._sleep(0.15)
        key_press(VK_DELETE)    # 清空
        self._sleep(0.15)
        log(f"输入任务链接(剪贴板粘贴): {url}")
        if not set_clipboard_text(url):
            log("错误: 剪贴板写入失败，改用逐字输入")
            type_text(url)
        else:
            ctrl_key("V")       # 粘贴
        self._sleep(0.3)
        log("按回车")
        key_press(VK_RETURN)
        # 按回车后: 连续点击作者名称+识图(每0.1秒轮询, 总超时5秒)
        # 区域状态: 全白=加载中 → 不全白=作者名称出现(本轮点击已点中, 进入下一页)
        p4 = pts.get(4)
        p19 = pts.get(19)
        p20 = pts.get(20)
        _loaded = False
        if p4 and p19 and p20:
            try:
                ax1, ay1 = int(p19[2]), int(p19[3])
                ax2, ay2 = int(p20[2]), int(p20[3])
                log("连续点击作者名称并识别区域 ...")
                _deadline = time.time() + self.ts("author_timeout")   # 作者检测总超时(可配)
                _saw_name = False
                while time.time() < _deadline:
                    self._check_stop()
                    from PIL import ImageGrab as _G
                    mouse_click(int(p4[2]), int(p4[3]))   # 点击作者名称
                    _a_img = _G.grab(bbox=(min(ax1, ax2), min(ay1, ay2), max(ax1, ax2), max(ay1, ay2)))
                    _has, _dark = _region_has_content(_a_img)
                    if _has:
                        if not _saw_name:
                            _saw_name = True
                            log(f"作者名称已出现(暗像素={_dark})，点击后等待区域转全白进入下一页")
                    elif _saw_name:
                        # 严格状态机: 作者名称出现后转全白 = 点击成功进入下一页
                        log("作者名称已点击，区域转全白(进入下一页)")
                        _loaded = True
                        self._sleep(0.5)
                        break
                    self._sleep(0.1)
            except Exception as _e:
                log(f"作者名称加载检测异常: {_e}")
        if not _loaded:
            log("错误: 未检测到作者名称，任务失败")
            self.last_error = "未检测到作者名称"
            return False
        # 文章列表页加载稳定检测: 0.1秒间隔截图对比, 连续1秒无变化才算加载完成
        p5 = pts.get(5)
        p7 = pts.get(7)
        if p5 and p7:
            try:
                lx1, ly1 = int(p5[2]), int(p5[3])
                lx2, ly2 = int(p7[2]), int(p7[3])
                lbox = (min(lx1, lx2), min(ly1, ly2), max(lx1, lx2), max(ly1, ly2))
                from PIL import ImageGrab as _G
                _prev = None
                _stable = 0.0
                _dl = time.time() + 8   # 总超时8秒兜底
                while time.time() < _dl:
                    self._check_stop()
                    _cur = _G.grab(bbox=lbox)
                    if _prev is not None and _image_changed(_prev, _cur):
                        _stable = 0.0        # 有变化(加载中), 重置计时
                    else:
                        _stable += 0.1
                    _prev = _cur
                    if _stable >= 1.0:       # 连续1秒无变化
                        log("文章列表加载稳定(连续1秒无变化)")
                        break
                    self._sleep(0.1)
                else:
                    log("列表加载稳定检测超时(8秒)，继续")
            except Exception as _le:
                log(f"列表加载稳定检测异常: {_le}")
        # 8) 文章列表页：OCR 采集循环
        return self._collect_articles(pts, name, idx)

    def _check_fetch_results(self):
        """检查后台抓取线程结果，处理写入记录和时间范围检测
        返回 True 表示需要停止（达到停止条件）"""
        if not self._pending_futures:
            return False
        stop_needed = False
        finished = []
        for future, link, name in self._pending_futures:
            if not future.done():
                continue
            finished.append((future, link, name))
            try:
                r = future.result()
                if r.get("error"):
                    log(f"后台抓取失败: {link} - {r.get('error')}")
                    continue
                title = r.get("title") or ""
                pub_time = r.get("pub_time") or ""
                save_path = r.get("save_path")
                original = r.get("original") or ""
                ip_location = r.get("ip") or ""
                log(f"后台抓取完成: 标题[{title}] 时间[{pub_time}] 保存[{save_path or '未保存'}]")
                # 写入采集记录（单点一次性写入，互动数据一起带入）
                rec = append_collected(name, pub_time, title, link,
                                       reads=r.get("reads", -1), likes=r.get("likes", -1),
                                       forwards=r.get("forwards", -1),
                                       favorites=r.get("favorites", -1),
                                       comments=r.get("comments", -1),
                                       write_time=r.get("write_time"),
                                       shot=r.get("shot") or "",
                                       read_shot=r.get("read_shot") or "",
                                       original=original, ip=ip_location)
                if rec == "skip":
                    log(f"采集记录已存在，跳过写入: {link}")
                elif rec == "error":
                    log("采集记录写入失败")
                # 记录一次文章获取成功
                self.collected_count += 1
                # 时间范围检测（延后判定）
                if pub_time and getattr(self, "time_range_dates", None):
                    try:
                        d = date.fromisoformat(pub_time[:10])
                        start_d, end_d = self.time_range_dates
                        if d < start_d or d > end_d:
                            self._time_out_count += 1
                            if self._time_out_count > 2:
                                log(f"文章时间 {pub_time} 不在范围内({start_d}~{end_d})，已超2篇容错")
                                stop_needed = True
                            else:
                                log(f"文章时间 {pub_time} 不在范围内（置顶旧文章，容忍 {self._time_out_count}/2）")
                    except Exception:
                        pass
                # 最大下载数量检测
                mc = getattr(self, "max_count_setting", None)
                if mc and self.collected_count >= mc:
                    log(f"已达到最大下载数量 {mc}")
                    stop_needed = True
            except Exception as e:
                log(f"处理后台结果异常: {e}")
        # 移除已完成的任务
        for item in finished:
            self._pending_futures.remove(item)
        return stop_needed

    def _wait_all_fetches(self):
        """等待所有后台抓取线程完成"""
        if not self._pending_futures:
            return
        log(f"等待 {len(self._pending_futures)} 个后台抓取任务完成...")
        for future, link, name in self._pending_futures:
            try:
                future.result(timeout=30)  # 最多等30秒
            except Exception:
                pass
        # 最后检查一次结果（先检查再清空，避免丢失最后一批结果）
        self._check_fetch_results()
        self._pending_futures.clear()

    # ---------- 文章采集循环（OCR） ----------
    def _collect_articles(self, pts, name, idx=None):
        """文章列表循环采集：
        循环: OCR识别卡片 -> 依次点击(5秒后文章操作) -> 全部点完 -> 滚动 -> 再OCR
        停止条件: 无卡片 / 达到最大数量 / 文章时间超出范围"""
        # 本任务成功下载计数
        self.collected_count = 0
        self._time_out_count = 0   # 时间范围外容错计数（置顶旧文章最多2篇）
        self._exit_loop = False
        self._found_start = False  # 自定义模式：是否已找到范围开始点
        self._pending_time = None  # 跨轮保留的时间点位(滚动衔接)
        # 等待文章列表加载（由 OCR 识别过程自然加载，无需额外等待）
        p5 = pts.get(5)
        p7 = pts.get(7)
        p12 = pts.get(12)
        if not p5 or not p7:
            log("错误: 缺少点位5/7（截图区域），任务失败")
            self.last_error = "缺少点位5/7"
            return False
        if not p12:
            log("错误: 缺少点位12（文章x轴线），任务失败")
            self.last_error = "缺少点位12"
            return False
        p12_x = int(p12[2])
        # 由两个对角点确定截图区域（自动归一化顺序）
        x1, y1 = int(p5[2]), int(p5[3])
        x2, y2 = int(p7[2]), int(p7[3])
        box = (min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2))
        # 滚动距离：优先用界面配置，无配置则默认屏幕高度 70%
        try:
            scroll_px = int(float(self.scroll_px_var.get()))
        except (AttributeError, ValueError):
            scroll_px = int(_u32().GetSystemMetrics(SM_CYSCREEN) * 0.7)
        if scroll_px <= 0:
            scroll_px = int(_u32().GetSystemMetrics(SM_CYSCREEN) * 0.7)
        log(f"文章列表 OCR 区域: {box}，滚动距离 {scroll_px}px")
        loop_n = 0
        while True:
            self._check_stop()
            if self._exit_loop:
                break
            # 检查后台抓取线程结果（延后判定停止条件）
            if self._check_fetch_results():
                log("后台任务触发停止条件，走完当前任务后停止")
                self._exit_loop = True
                break
            loop_n += 1
            log(f"--- 列表循环 {loop_n}：OCR 识别中 ---")
            # 识别文章列表(新结构: 时间点位/文章点位 交替, 支持"余下"加载更多)
            ordered = []
            for attempt in range(1, 6):
                self._check_stop()
                try:
                    items = ocr_region(box)
                except Exception as e:
                    log(f"OCR 失败: {e}")
                    self.last_error = f"OCR 失败: {e}"
                    return False
                # "余下"按钮: 点击加载更多文章后再重新OCR(可多次, 最多5次防死循环)
                more = find_more_buttons(items)
                _more_cnt = 0
                while more:
                    _mx, _my, _mt = more[0]
                    log(f"识别到'余下'加载更多按钮({_mx},{_my})[{_mt}]，点击后重新OCR")
                    mouse_click(int(_mx), int(_my))
                    self._sleep(1)
                    items = ocr_region(box)
                    more = find_more_buttons(items)
                    _more_cnt += 1
                    if _more_cnt >= 5:
                        log("'余下'加载按钮连续点击5次仍未消失，停止继续加载")
                        break
                ordered = classify_article_items(items, box)
                if ordered:
                    break
                log(f"OCR 未识别到文章点位，重试 {attempt}/5...")
            if not ordered:
                log("错误: OCR 未识别到文章（列表页异常），任务失败")
                self.last_error = "未识别到文章"
                return False
            times = [(c, y, t) for _, typ, c, y, t in ordered if typ == "time"]
            articles = [(c, y, t) for _, typ, c, y, t in ordered if typ == "article"]
            log(f"识别到 {len(times)} 个时间点位, {len(articles)} 篇文章")
            # ---- 自定义模式: 置顶识别 + 范围判断(基于时间点位序列) ----
            is_custom = getattr(self, "is_custom_mode", False)
            tr_dates = getattr(self, "time_range_dates", None)
            start_d = end_d = None
            pinned_count = 0
            page_has_in_range = False
            _today = date.today()
            if is_custom and tr_dates:
                start_d, end_d = tr_dates
                if loop_n == 1:
                    for i in range(1, min(3, len(times))):
                        dp = resolve_article_date(times[i - 1][2], _today)
                        dc = resolve_article_date(times[i][2], _today)
                        if dp and dc and dc > dp:
                            pinned_count = i
                            break
                if pinned_count:
                    log(f"识别到 {pinned_count} 个置顶文章（时间跳变），置顶不计入范围定位")
            # 范围不可达: 顶部第一个时间点位已早于范围开始 -> 只会更旧, 停止
            if is_custom and tr_dates and not self._found_start and not pinned_count and times:
                _top_d = resolve_article_date(times[0][2], _today)
                if _top_d and _top_d < start_d:
                    log(f"顶部时间[{times[0][2]}]已早于范围开始({start_d})，往下只会更旧，范围内无文章，结束采集")
                    self._exit_loop = True
                    break
            # ---- 时间状态机: 时间点位赋予其下文章直到下一时间点位 ----
            # 继承上一轮末尾的时间点位(滚动衔接: 上轮末尾"今天"给本轮顶部文章用)
            cur_time = self._pending_time
            for _, typ, cx, cy, text in ordered:
                self._check_stop()
                if typ == "time":
                    cur_time = text
                    continue   # 时间点位不点击
                # 文章(数据)点位: 时间取最近的时间点位
                art_time = cur_time or ""
                d = resolve_article_date(art_time, _today)
                # 自定义范围判断(基于该文章所属时间)
                if is_custom and tr_dates:
                    is_pinned = False
                    in_range = d is not None and start_d <= d <= end_d
                    if in_range:
                        self._found_start = True
                        page_has_in_range = True
                    else:
                        log(f"跳过文章 ({cx},{cy}) 时间[{art_time}] 日期[{d or '无法解析'}] 不在范围 {start_d}~{end_d}")
                        continue
                click_time = time.strftime("%Y-%m-%d %H:%M:%S")
                reads = extract_reads(text)   # 阅读数(-1=未识别到)
                likes = extract_likes(text)   # 点赞数(-1=未识别到)
                log(f"点击文章点位 (x=点位12:{p12_x}, y={cy}) 阅读[{reads}] 赞[{likes}] 时间[{art_time}] 日期[{d or '-'}]")
                mouse_click(p12_x, cy)
                self._sleep(self.ts("article_load"))   # 点击文章点位后等待(可配)
                r = self._collect_article_link(pts, name, click_time, reads, likes, idx)
                if r is False:
                    log("文章操作失败，任务标记 error")
                    return False
                if r == "stop":
                    log("达到停止条件，退出文章采集循环")
                    self._exit_loop = True
                    break

                log("Ctrl+W 关闭文章")
                ctrl_key("W")
                self._sleep(self.ts("close_after"))
                # 每处理完一张卡片检查后台结果（及时写入CSV）
                if self._check_fetch_results():
                    log("后台任务触发停止条件，退出文章采集循环")
                    self._exit_loop = True
                    break
            # 自定义模式停止判定：已找到开始点，但本页无任何正常范围内点位 -> 范围结束
            if is_custom and tr_dates and self._found_start and not page_has_in_range:
                log("已找到范围结束点（本页无范围内点位），结束文章采集")
                break
            # 轮末: 保留最新时间点位给下一轮(滚动衔接)
            self._pending_time = cur_time
            # 全部点击完毕：滚动前先检查后台结果（可能已触发停止条件）
            if self._check_fetch_results():
                log("后台任务触发停止条件，不再滚动，结束文章采集")
                self._exit_loop = True
                break
            if self._exit_loop:  # 达到停止条件则不滚动
                break
            log(f"全部点击完毕，移动鼠标到点位7({p7[2]},{p7[3]}) 向下滚动 {scroll_px}px")
            scroll_down_at(int(p7[2]), int(p7[3]), scroll_px)
            log("列表滚动后等待刷新...")
            self._sleep(self.ts("scroll_after"))
        # 等待所有后台抓取任务完成
        self._wait_all_fetches()
        return True

    def _sub_region(self, pts, id_a, id_b):
        """由两个点位 id 取归一化截图区域 box 或 None"""
        a, b = pts.get(id_a), pts.get(id_b)
        if not a or not b:
            return None
        x1, y1 = int(a[2]), int(a[3])
        x2, y2 = int(b[2]), int(b[3])
        if x1 > 0 and y1 > 0 and x2 > 0 and y2 > 0:
            return (min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2))
        return None

    def _copy_link(self, pts, p8, p18):
        """复制链接：点8(三点) → 点18(固定复制链接按钮) → 轮询剪贴板
        仅保留清空剪贴板后等0.5秒; 最多尝试5次; 成功返回链接, 失败返回 None"""
        link = None
        for attempt in range(1, 6):
            self._check_stop()
            log(f"--- 复制链接尝试 {attempt}/5 ---")
            log(f"点击点位8({p8[2]},{p8[3]}) {p8[1]}")
            mouse_click(int(p8[2]), int(p8[3]))
            tx, ty = int(p18[2]), int(p18[3])
            log(f"点击点位18({tx},{ty}) {p18[1]}")
            # 点击前清空剪贴板，确保检测到的一定是新复制的链接
            clear_clipboard()
            self._sleep(0.5)
            before = read_clipboard_text()
            mouse_click(tx, ty)
            # 轮询等待剪贴板更新（0.1 秒/次 × 30 次 = 3 秒）
            for _p in range(30):
                self._check_stop()
                self._sleep(0.1)
                cur = read_clipboard_text()
                if cur and cur != before and "mp.weixin.qq.com" in cur:
                    link = cur
                    break
            if link:
                break
            log(f"尝试{attempt}: 剪贴板未更新为文章链接，点击两次点位8重试")
            # 失败后额外操作：点击两次点位8(重新触发三点菜单), 间隔0.5秒(原0.3+0.2)
            for _ in range(2):
                mouse_click(int(p8[2]), int(p8[3]))
                self._sleep(0.5)
        return link

    def _api_fail(self):
        """豆包调用失败: 计数+1; 返回True表示已连续失败3次(触发禁用)"""
        self._api_fail_streak += 1
        if self._api_fail_streak >= 3:
            self._api_disabled = True
            log(f"⚠️ 豆包API连续{self._api_fail_streak}次调用失败，判定短时间无法恢复，后续任务跳过豆包调用")
            return True
        return False

    def _api_ok(self):
        """豆包调用成功: 重置失败计数"""
        self._api_fail_streak = 0
        self._api_disabled = False

    def _parse_int(self, v):
        """评论数量解析: 空=无限(None), 0=不采集, >0=采集N条"""
        s = (v or "").strip()
        if s == "":
            return None
        try:
            return int(float(s))
        except (TypeError, ValueError):
            return 0

    def _wait_comment_stable(self, pts):
        """评论区加载稳定检测: 截图点位22/23区域, 0.1秒间隔, 最多50次
        连续30次无变化判定加载完成; 第一张仅作基准不对比
        返回 True=已稳定 / False=超时"""
        rbox = self._sub_region(pts, 22, 23)
        if not rbox:
            return False
        from PIL import ImageGrab as _G
        prev = None
        stable = 0
        for _i in range(50):
            self._check_stop()
            cur = _G.grab(bbox=rbox)
            if prev is None:
                prev = cur          # 第一张仅作基准
                self._sleep(0.1)
                continue
            if _image_changed(prev, cur):
                stable = 0          # 有变化, 重置
            else:
                stable += 1
            prev = cur
            if stable >= 30:        # 连续30次无变化
                log("评论区加载稳定(连续30次无变化)")
                return True
            self._sleep(0.1)
        log("评论区稳定检测超时(50次)")
        return False

    def _collect_comments(self, pts, article_url, interact_future=None, idx=None):
        """评论采集循环: 截图→OCR回复→点击展开→豆包识别→写CSV→滚动
        连续3次截图相同(到底)或达到数量上限停止
        interact_future: 4指标异步识别结果, 确认留言=0时立即停止并清理已写入评论
        豆包失败: 单次记录错误备注(任务继续); 连续3次 -> 错误+停止全部任务"""
        try:
            _key = (self.ui.get("doubao_api_key") or "").strip()
        except Exception:
            _key = ""
        if not _key:
            log("评论采集: 缺少豆包API Key，跳过")
            return
        if self._quota_error:
            if idx is not None:
                update_input_remark(idx, "评论采集失败:豆包无额度,评论未采集")
            log("评论采集: 豆包无额度，跳过")
            return
        if self._api_disabled:
            if idx is not None:
                update_input_remark(idx, "评论采集失败:豆包API连续失败暂不可用,评论未采集")
            log("评论采集: 豆包API已禁用(连续失败)，跳过")
            return
        from PIL import ImageGrab as _G
        import base64, io

        max_l1 = self._parse_int(self.max_l1_var.get())     # 一级: 空=无限, 0=不采, >0=N条
        max_l2 = self._parse_int(self.max_l2_var.get())     # 二级: 空=无限, 0=不展, >0=N条

        l1_count = 0       # 已采一级评论数
        total_new = 0      # 本轮已写入新评论数
        loop_n = 0
        prev_shot = None   # 上一张截图(滚动对比用)
        same_count = 0     # 连续相同截图轮数
        seen_ids = set()   # 本次采集已识别评论ID(跨轮去重, 不读CSV)

        log(f"评论采集开始(一级上限={max_l1}, 每级二级={max_l2})")

        while same_count < 3:
            self._check_stop()
            loop_n += 1
            # 快速检查: 4指标识别已完成且留言=0 → 停止并清理
            if interact_future is not None and interact_future.done():
                try:
                    _res = interact_future.result()
                    if _res and _res[3] == 0:
                        log(f"4指标确认留言=0，停止评论采集并清理已写入数据")
                        _deleted = delete_comments(article_url)
                        log(f"已删除误采集评论 {_deleted} 条")
                        return
                except Exception:
                    pass
            log(f"评论采集第{loop_n}轮: 截图评论区(点位22/23)...")

            # ① 截图评论区(点位22/23); 截图前统一移开鼠标(点位23, 避免遮挡)
            rbox = self._sub_region(pts, 22, 23)
            if not rbox:
                log("评论采集: 缺少点位22/23，停止")
                break
            _pm = pts.get(23)
            if _pm:
                mouse_move(int(_pm[2]), int(_pm[3]))
            shot = _G.grab(bbox=rbox)

            # ② 与上一张对比: 相同→跳过识别直接滚动; 连续3次相同→到底停止
            if prev_shot is not None and not _image_changed(prev_shot, shot):
                same_count += 1
                log(f"评论采集第{loop_n}轮: 截图与上一张相同(连续{same_count}/3)，跳过识别继续滚动")
                if same_count >= 3:
                    log("连续3次截图完全相同，评论区到底，停止采集")
                    break
                try:
                    _px = int(float(self.comment_scroll_px_var.get()))
                except Exception:
                    _px = 300
                p23_now = pts.get(23)
                if p23_now:
                    log(f"评论采集第{loop_n}轮: 滚动评论区({_px}px)")
                    scroll_down_at(int(p23_now[2]), int(p23_now[3]), _px)
                pts = {p[0]: p for p in load_points()}
                self._sleep(self.ts("comment_scroll"))   # 评论区滚动后(可配)
                continue
            same_count = 0
            prev_shot = shot

            # ③ 采集二级评论: OCR找"回复"(灰色) → 依次点击展开
            if max_l2 is None or max_l2 > 0:
                self._expand_replies(shot, rbox, pts)

            # ④ 重新截图(展开后); 截图前移开鼠标
            _pm2 = pts.get(23)
            if _pm2:
                mouse_move(int(_pm2[2]), int(_pm2[3]))
            shot2 = _G.grab(bbox=rbox)
            buf2 = io.BytesIO()
            shot2.save(buf2, format="WEBP", lossless=True, method=6)
            shot2_b64 = base64.b64encode(buf2.getvalue()).decode()

            # ⑤ 并行执行: 豆包识图提取评论(网络) + OCR名称行层级(本地CPU)
            log(f"评论采集第{loop_n}轮: 并行识别中(豆包+OCR校准)...")
            import concurrent.futures as _cf
            with _cf.ThreadPoolExecutor(max_workers=2) as _ex:
                _f_doubao = _ex.submit(doubao_extract_comments, shot2_b64, _key)
                _f_ocr = _ex.submit(self._ocr_name_levels, shot2)
                try:
                    comments = _f_doubao.result()
                except DoubaoQuotaError as _e:
                    self._quota_error = True
                    if idx is not None:
                        update_input_remark(idx, "评论采集失败:豆包无额度,评论未采集")
                    if self._api_fail():
                        self.last_error = "豆包API连续失败(评论采集)"
                        self._abort_all = True
                        if idx is not None:
                            update_input_remark(idx, "豆包API连续失败,评论采集终止")
                    log(f"❌ 豆包API没有额度/欠费，停止评论采集: {_e}")
                    return
                except Exception as _e:
                    # 豆包调用异常(非额度): 普通失败 -> 记错误备注, 结束本任务评论采集
                    if idx is not None:
                        update_input_remark(idx, "评论采集失败:豆包调用异常")
                    if self._api_fail():
                        # 连续3次失败 -> 错误 + 停止全部
                        self.last_error = "豆包API连续失败(评论采集)"
                        self._abort_all = True
                        if idx is not None:
                            update_input_remark(idx, "豆包API连续失败,评论采集终止")
                        log(f"评论采集: 豆包连续失败, 标记错误并停止全部任务: {_e}")
                        return
                    log(f"评论采集: 豆包调用失败(普通), 评论未采集, 任务继续: {_e}")
                    return
                _levels = _f_ocr.result()
            # OCR坐标覆盖层级(稳定可靠), 豆包"是否缩进"作兜底
            for _i, _c in enumerate(comments):
                if _i < len(_levels):
                    _c["层级"] = _levels[_i]
            log(f"评论采集第{loop_n}轮: 豆包识别{len(comments)}条, OCR校准层级{_levels}")
            if comments:
                # ⑥ 跨轮去重: 本次采集已识别过的评论不重复写入
                fresh = []
                for _c in comments:
                    _cid = calc_comment_id(
                        _c.get("名称", ""), _c.get("地区", ""), _c.get("时间", ""),
                        str(_c.get("点赞数量", "0")), _c.get("正文", ""), _c.get("层级", 1))
                    if _cid in seen_ids:
                        continue
                    seen_ids.add(_cid)
                    fresh.append(_c)
                if fresh:
                    # ⑦ 写入评论CSV(采集时间=第一次看到, 即本轮)
                    wrote = append_comments(article_url, fresh)
                    total_new += wrote
                    # 统计一级评论数
                    for c in fresh:
                        if c.get("层级") == 1:
                            l1_count += 1
                    log(f"评论采集第{loop_n}轮: 写入{wrote}条新评论(累计{total_new})")
                else:
                    log(f"评论采集第{loop_n}轮: {len(comments)}条均为本次采集已识别过的(重复), 不写入")

            # ⑦ 检查数量上限
            hit_limit = False
            if max_l1 is not None and max_l1 > 0 and l1_count >= max_l1:
                log(f"一级评论达到上限({max_l1})，停止")
                hit_limit = True
            if hit_limit:
                break

            # ⑧ 滚动评论区
            try:
                _px = int(float(self.comment_scroll_px_var.get()))
            except Exception:
                _px = 300
            p23_now = pts.get(23)
            if p23_now:
                log(f"评论采集第{loop_n}轮: 滚动评论区({_px}px)")
                scroll_down_at(int(p23_now[2]), int(p23_now[3]), _px)
            pts = {p[0]: p for p in load_points()}
            self._sleep(self.ts("comment_scroll"))   # 评论区滚动后(可配)

        # 最终确认: 4指标结果留言=0 → 清理本次误采集
        if interact_future is not None:
            try:
                _res = interact_future.result(timeout=60)
                if _res and _res[3] == 0 and total_new > 0:
                    log(f"确认留言=0，清理误采集评论")
                    _deleted = delete_comments(article_url)
                    log(f"已删除误采集评论 {_deleted} 条")
            except Exception:
                pass
        log(f"评论采集结束: 共写入{total_new}条评论")

    def _ocr_name_levels(self, shot_img):
        """OCR识别名称行(含时间'7月13日'或'作者'标签), 返回层级序列[1,2,1,...]
        x缩进>15px=二级; 无名称行返回[]"""
        try:
            items = ocr_img(shot_img)
        except Exception:
            return []
        name_rows = []
        for cx, cy, text, score, sbox, brightness in items:
            if re.search(r"\d+月\d+日", text) or "作者" in text:
                x0 = min(p[0] for p in sbox)
                y0 = min(p[1] for p in sbox)
                name_rows.append((y0, x0, text))
        if not name_rows:
            return []
        name_rows.sort()
        min_x = min(r[1] for r in name_rows)
        return [2 if (r[1] - min_x) > 15 else 1 for r in name_rows]

    def _expand_replies(self, shot_img, rbox, pts):
        """OCR识别评论区截图中的"回复"字样(灰色), 依次点击展开二级评论"""
        log("评论采集: OCR检查'回复'按钮...")
        # OCR识别当前截图
        try:
            items = ocr_img(shot_img)
        except Exception:
            items = []
        # 筛选含"回复"的灰色点位
        reply_btns = []
        for cx, cy, txt, score, sbox, brightness in items:
            txt_s = txt.strip()
            if "回复" in txt_s and len(txt_s) <= 4:
                try:
                    if 100 < brightness < 200:  # 灰色范围
                        abs_x = rbox[0] + cx
                        abs_y = rbox[1] + cy
                        reply_btns.append((abs_x, abs_y, txt_s))
                except Exception:
                    continue
        if not reply_btns:
            log("评论采集: 未发现'回复'按钮")
            return
        log(f"发现{len(reply_btns)}个回复按钮，依次点击展开")
        for x, y, txt in reply_btns:
            self._check_stop()
            mouse_click(x, y)
            self._sleep(self.ts("reply_load"))  # 等二级评论加载(可配)
        # 展开后等稳定
        self._sleep(1.0)

    def _capture_interact_shot(self, pts):
        """采集4指标：截图底部互动栏(点位13/14) -> base64
        提交豆包识别为异步future(不等待), 评论采集可提前进行
        返回 (shot_b64, interact_future); future结果=(点赞,转发,喜欢,留言) 或 None"""
        shot_b64 = None
        interact_future = None
        if self.capture_4metrics_var.get():
            rbox = self._sub_region(pts, 13, 14)
            if rbox:
                try:
                    shot_b64 = capture_region_base64(rbox, scale=1.0)
                    log(f"底部互动栏截图完成 (base64 {len(shot_b64) if shot_b64 else 0} B)")
                except Exception as e:
                    log(f"互动栏截图失败: {e}")
        if shot_b64 and not self._quota_error and not self._api_disabled:
            _key = (self.doubao_key_var.get() or "").strip()
            if _key:
                import concurrent.futures as _cf
                interact_future = self._fetch_executor.submit(
                    doubao_recognize_interact, shot_b64, _key)
        return shot_b64, interact_future

    def _capture_read_count(self, pts, link):
        """采集阅读数：滚动到底 → Ctrl+W关闭 → 点位17搜索 → 输入链接 → 回车 → 截图(点位15/16)
        返回 read_shot_b64(未配置点位/失败返回 None)"""
        read_shot_b64 = None
        p15 = pts.get(15)
        if not p15:
            return None
        try:
            px15, py15 = int(p15[2]), int(p15[3])
            log(f"采集阅读数：移动鼠标到点位15({px15},{py15})")
            _u32().SetCursorPos(px15, py15)
            time.sleep(FAST_SCROLL_SLEEP)
            for _round in range(SCROLL_READ_ROUNDS):
                ticks = SCROLL_READ_PX // WHEEL_TICK_PX
                for _ in range(ticks):
                    _u32().mouse_event(MOUSEEVENTF_WHEEL, 0, 0, -WHEEL_DELTA, None)
                log(f"采集阅读数：第{_round+1}/{SCROLL_READ_ROUNDS}次快速滚动完成")
                time.sleep(FAST_SCROLL_SLEEP)
        except Exception as e:
            log(f"采集阅读数滚动失败: {e}")
        # 等0.5秒 → Ctrl+W关闭标签 → 等0.5秒
        self._sleep(0.5)
        log("采集阅读数：Ctrl+W 关闭标签页")
        ctrl_key("W")
        self._sleep(0.5)
        p17 = pts.get(17)
        if p17:
            px17, py17 = int(p17[2]), int(p17[3])
            log(f"采集阅读数：点击点位17({px17},{py17}) 搜索按钮")
            mouse_click(px17, py17)
            ctrl_key("A")          # 全选
            self._sleep(0.15)
            key_press(VK_DELETE)    # 清空
            self._sleep(0.15)
            log("采集阅读数：输入链接")
            if not set_clipboard_text(link):
                type_text(link)
            else:
                ctrl_key("V")       # 粘贴
            self._sleep(0.15)
            log("采集阅读数：按回车")
            key_press(VK_RETURN)
            self._sleep(self.ts("search_wait"))   # 搜索后等列表(可配)
            # 等加载 → 截图点位15/16区域(阅读数) → base64
            self._sleep(self.ts("read_load"))   # 阅读数加载(可配)
            try:
                from PIL import ImageGrab as _Grab
                rbox = self._sub_region(pts, 15, 16)
                if rbox:
                    img_raw = _Grab.grab(bbox=rbox)
                    read_info = find_read_in_img(img_raw)
                    if read_info:
                        _rcx, _rcy, rtext, rb = read_info
                        log(f"阅读数截图中找到[{rtext}] 亮度={rb:.0f} (灰色={rb>=100} 深色={rb<100})")
                    else:
                        log("阅读数截图中未找到'阅读'字段")
                    read_shot_b64 = _pil_to_b64(img_raw, scale=0.75)
                    log(f"阅读数截图完成 (base64 {len(read_shot_b64) if read_shot_b64 else 0} B)")
            except Exception as e:
                log(f"阅读数截图失败: {e}")
        return read_shot_b64

    def _spawn_fetch(self, link, name, shot_b64, read_shot_b64,
                     click_time, reads, likes, forwards, favorites, comments):
        """提交后台抓取任务(标题/时间/HTML + 豆包识图互动数据)，不阻塞主流程"""
        def _fetch_task(link, name, shot_b64, read_shot_b64,
                      likes, forwards, favorites, comments):
            """后台抓取任务：抓取标题/时间 + 保存 HTML + 互动数据
            返回统一 dict：title/pub_time/save_path/error + 互动数据"""
            # 后台：豆包识图识别互动栏（若截图成功且未同步识别, 异步执行不阻塞采集）
            if shot_b64 and forwards == -1 and not self._quota_error and not self._api_disabled:
                _key = self.doubao_key_var.get()
                if _key:
                    try:
                        _res = doubao_recognize_interact(shot_b64, _key)
                    except DoubaoQuotaError as _e:
                        self._quota_error = True
                        self._api_fail()
                        log(f"❌ 豆包API没有额度/欠费: {_e}")
                        _res = None
                    if _res:
                        self._api_ok()
                        likes, forwards, favorites, comments = _res
                        log(f"豆包识图: 点赞[{likes}] 转发[{forwards}] 喜欢[{favorites}] 留言[{comments}]")
                    else:
                        self._api_fail()
                        log("豆包识图失败，互动数据保持默认(截图已保存可二次处理)")

            def _result(error="", **kw):
                base = {"title": "", "pub_time": "", "save_path": None, "error": error,
                        "reads": -1, "likes": -1, "forwards": -1,
                        "favorites": -1, "comments": -1, "shot": "", "read_shot": "",
                        "original": "", "ip": ""}
                base.update(kw)
                return base

            try:
                save_dir = os.path.join(self.session_dir, clean_filename(name))
                os.makedirs(save_dir, exist_ok=True)
            except Exception:
                save_dir = None
            save_path = None
            if save_dir:
                fetched = fetch_article(link, save_path=None)
                if fetched is None:
                    return _result(error="标题/时间获取失败")
                title, pub_time, original, ip_location = fetched
                _stem = clean_filename(title or "untitled")
                _date = (pub_time or "")[:10]
                # 每篇文章保存为独立文件夹: <日期>_<题目>/<日期>_<题目>.html + images/
                _folder = f"{_date}_{_stem}" if _date else _stem
                _art_dir = os.path.join(save_dir, _folder)
                os.makedirs(_art_dir, exist_ok=True)
                save_path = os.path.join(_art_dir, _folder + ".html")
                fetched2 = fetch_article(link, save_path)
                if fetched2 is None:
                    return _result(error="HTML 保存失败")
                # 下载文章图片到本地(images/相对html), 实现离线可看
                _img_n = localize_article_images(save_path)
                log(f"文章图片本地化: {_img_n} 张")
            else:
                fetched = fetch_article(link)
                if fetched is None:
                    return _result(error="抓取失败")
                title, pub_time, original, ip_location = fetched
            return _result(title=title, pub_time=pub_time, save_path=save_path,
                           write_time=click_time, reads=reads, likes=likes,
                           forwards=forwards, favorites=favorites, comments=comments,
                           shot=shot_b64, read_shot=read_shot_b64,
                           original=original, ip=ip_location)
        # 提交到线程池异步执行(截图数据已就绪, 参数传递避免闭包时序问题)
        future = self._fetch_executor.submit(
            _fetch_task, link, name, shot_b64, read_shot_b64,
            likes, forwards, favorites, comments)
        self._pending_futures.append((future, link, name))

    def _collect_article_link(self, pts, name, click_time=None, reads=-1, likes=-1, idx=None):
        """正式文章操作流程：复制链接 → 采集4指标截图 → 采集阅读数 → 后台抓取
        click_time: 点击时间点位的时间（写入 CSV 用）
        reads/likes: 列表页 OCR 提取的阅读/点赞数（-1=未识别到）
        返回: True=成功继续 / False=失败(error)"""
        p8 = pts.get(8)
        p18 = pts.get(18)
        if not p8 or not p18:
            log("错误: 缺少点位8/18，任务失败")
            self.last_error = "缺少点位8/18"
            return False
        link = self._copy_link(pts, p8, p18)
        if not link:
            log("错误: 5次尝试复制链接均失败，任务失败")
            self.last_error = "复制链接失败(5次)"
            return False
        self.collected_links.append(link)
        log(f"已复制文章链接: {link}")
        # 采集4指标截图(评论采集开启时同步识图, 其余后台执行)
        shot_b64, interact_future = self._capture_interact_shot(pts)
        # 乐观并发: 不等待4指标结果, 提前点击点位21并开始评论采集
        _m1 = self._parse_int(self.max_l1_var.get())
        if _m1 is None or _m1 > 0:
            if self._quota_error:
                if idx is not None:
                    update_input_remark(idx, "评论采集:豆包无额度,评论未采集")
                log("评论采集: 豆包无额度,评论未采集(任务继续)")
            if self._api_disabled:
                if idx is not None:
                    update_input_remark(idx, "评论采集:豆包API连续失败,评论未采集")
                log("评论采集: 豆包API连续失败已禁用,评论未采集(任务继续)")
            p21 = pts.get(21)
            if p21:
                log("乐观: 提前点击评论按钮(点位21)，4指标识别后台进行中")
                mouse_click(int(p21[2]), int(p21[3]))
                # 立即移开鼠标到点位23, 避免遮挡评论区
                _p23m = pts.get(23)
                if _p23m:
                    mouse_move(int(_p23m[2]), int(_p23m[3]))
                self._wait_comment_stable(pts)
                _q_before = self._quota_error
                try:
                    self._collect_comments(pts, link, interact_future, idx)
                except Exception as e:
                    log(f"评论采集异常: {e}")
                if not _q_before and self._quota_error:
                    # 评论采集因无额度失败: 单次 -> 记错误备注, 任务继续
                    # (连续3次失败触发停止全部已在 _collect_comments 内处理)
                    if idx is not None:
                        update_input_remark(idx, "评论采集失败:豆包无额度,评论未采集")
                    log("评论采集: 豆包无额度,评论未采集(单次失败,任务继续)")
                # 评论采集连续失败触发的停止全部标志
                if self._abort_all:
                    return False
            else:
                log("缺少点位21(评论按钮)，无法采集评论")
        # 只有评论采集开启时才等4指标结果(留言判断已在采集内处理, 等待通常秒级);
        # 不采集评论时不等待, 互动数据由后台抓取异步识别
        forwards = favorites = comments = -1   # 转发/喜欢/留言 默认-1(未识别)
        if _m1 is None or _m1 > 0:
            if interact_future is not None:
                try:
                    sync_res = interact_future.result(timeout=90)
                    if sync_res:
                        self._api_ok()
                        likes, forwards, favorites, comments = sync_res
                        log(f"4指标识别: 点赞[{likes}] 转发[{forwards}] 喜欢[{favorites}] 留言[{comments}]")
                    else:
                        # 识别失败: 普通失败处理 -> 跳过并备注, 任务继续
                        if idx is not None:
                            update_input_remark(idx, "4指标识别:豆包调用失败,截图已保存待二次处理")
                        if self._api_fail() and idx is not None:
                            update_input_remark(idx, "豆包API连续失败,后续任务跳过豆包调用(截图仍保存)")
                        log("4指标识别失败, 截图已保存待二次处理")
                except DoubaoQuotaError as _e:
                    self._quota_error = True
                    if idx is not None:
                        update_input_remark(idx, "4指标识别:豆包无额度,截图已保存待二次处理")
                    self._api_fail()
                    log(f"❌ 豆包API没有额度/欠费: {_e} (4指标截图已保存,可二次处理)")
                except Exception as e:
                    log(f"4指标识别等待异常: {e}")
            elif self._api_disabled:
                # 豆包已禁用(连续失败): 跳过识别, 截图已存, 走后续流程
                if idx is not None:
                    update_input_remark(idx, "4指标识别:豆包API暂不可用,跳过识别(截图已保存)")
                log("豆包API已禁用, 跳过4指标识别(截图已保存), 继续后续流程")
        # 采集阅读数: 仅当时间点位未提取到阅读数(reads==-1)时执行
        read_shot_b64 = None
        if self.capture_read_var.get() and reads == -1:
            log("时间点位未提取到阅读数，执行采集阅读数流程")
            read_shot_b64 = self._capture_read_count(pts, link)
        # 后台抓取文章(标题/时间/HTML + 互动数据), 不等待直接返回
        self._spawn_fetch(link, name, shot_b64, read_shot_b64,
                          click_time, reads, likes, forwards, favorites, comments)
        return True

    def _finish_collection(self, stopped, total, done_n):
        """采集结束：恢复按钮/进度状态（main 保持右半屏，不恢复居中）"""
        self.busy = False
        try:
            self.btn_start.config(state=tk.NORMAL, text="开始")
        except Exception:
            pass
        if stopped:
            self._set_progress(f"进度: 已停止（完成 {done_n}/{total}）",
                               done_n / total * 100 if total else 0)
            log(f"已停止（完成 {done_n}/{total}）")
        else:
            self._set_progress(f"进度: 完成（{done_n}/{total}）", 100)
            log(f"完成: {done_n}/{total} 个")

    def _set_progress(self, text, value=None):
        """进度更新：放入队列，主线程处理（子线程安全）"""
        try:
            self.ui_queue.put(("progress", text, value or 0))
        except Exception:
            pass

    # ---------- 关闭 ----------
    def on_exit(self):
        self._save_state()
        try:
            self._fetch_executor.shutdown(wait=False)   # 停止后台抓取线程池
        except Exception:
            pass
        show_taskbar()              # 恢复任务栏
        log(f"退出（设置已记忆 -> {UI_STATE_FILE}）")
        self.root.destroy()


# ================= 入口 =================
# ================= 依赖自检 =================
REQUIRED_PACKAGES = [
    ("rapidocr_onnxruntime", "rapidocr_onnxruntime"),
    ("requests", "requests"),
    ("PIL", "Pillow"),
]


def check_dependencies():
    """启动时检查必需依赖是否安装，缺少则给出安装命令并退出"""
    missing = []
    for module_name, pip_name in REQUIRED_PACKAGES:
        try:
            __import__(module_name)
        except ImportError:
            missing.append(pip_name)
    if missing:
        print("=" * 50)
        print("[错误] 缺少以下依赖，请先安装：")
        print("=" * 50)
        print(f"\npip install {" ".join(missing)}\n")
        print("=" * 50)
        sys.exit(1)


def main():
    check_dependencies()
    try:
        ctypes.WinDLL("kernel32").SetConsoleOutputCP(65001)
    except Exception:
        pass
    enable_dpi_awareness()
    # 任何退出路径都恢复任务栏（含异常退出）
    import atexit
    atexit.register(show_taskbar)
    root = tk.Tk()
    app = App(root)

    if "--ui-shot" in sys.argv:
        # 截图自检（调试用）：1.5 秒后前置窗口截图并退出
        i = sys.argv.index("--ui-shot")
        shot_path = sys.argv[i + 1] if len(sys.argv) > i + 1 else "_ui.png"
        root.after(1500, lambda: (app.start(),
                                  root.attributes("-topmost", True),
                                  root.lift(),
                                  root.after(400, lambda: (
                                      _grab_screen(shot_path), root.destroy()))))
    else:
        root.after(100, app.start)
    root.mainloop()


def _grab_screen(path):
    from PIL import ImageGrab
    ImageGrab.grab().save(path)
    print(f"截图已保存 -> {path}")


if __name__ == "__main__":
    main()

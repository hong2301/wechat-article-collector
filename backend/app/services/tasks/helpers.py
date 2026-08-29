# -*- coding: utf-8 -*-
"""任务子包: 后台线程池 + 调试截图辅助"""
import os, shutil, time as _t
import os, shutil, time as _t
import os, base64, time as _t
import threading
from concurrent.futures import ThreadPoolExecutor

_bg_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="bg")
_bg_futures = []          # 已提交的后台 future 集合(完成后移除)
_bg_futures_lock = threading.Lock()

from ...core.robot import tasks_echo


def _submit_bg(fn, *args, **kwargs):
    """提交后台任务并记录 future(供 wait_bg_done 等待); 完成后自动移除"""
    f = _bg_executor.submit(fn, *args, **kwargs)
    with _bg_futures_lock:
        _bg_futures.append(f)
    f.add_done_callback(lambda _f: _done_bg(_f))
    return f




def _save_debug_shot(shot_path, folder, tag):
    """调试: 复制截图文件到桌面文件夹(如 豆包/), 带时间戳防覆盖"""
    try:
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
        dst_dir = os.path.join(os.path.expanduser("~/Desktop"), folder)
        os.makedirs(dst_dir, exist_ok=True)
        name = f"{_t.strftime('%H%M%S')}_{tag.replace('#','_')}.png"
        sb = shot_b64.split(",", 1)[1] if "," in shot_b64 else shot_b64
        with open(os.path.join(dst_dir, name), "wb") as f:
            f.write(base64.b64decode(sb))
        tasks_echo(f"[async:{tag}] 调试截图已存桌面/{folder}/{name}")
    except Exception:
        pass

def _done_bg(f):
    with _bg_futures_lock:
        try:
            _bg_futures.remove(f)
        except ValueError:
            pass


def wait_bg_done(timeout=120):
    """等待本次所有后台异步任务完成(自动停止时调用, 确保写表/保存Html/4指标/阅读数OCR收尾)
    主动停止不调用; 只等已提交的 future, executor 保持可复用(不 shutdown)"""
    with _bg_futures_lock:
        fs = list(_bg_futures)
    if fs:
        try:
            wait(fs, timeout=timeout)
        except Exception:
            pass



# -*- coding: utf-8 -*-
"""观测基建(切面式, 业务逻辑零侵入): 耗时/计数窗口聚合 + 周期资源采样

用法:
  from .core import obs
  @obs.timed("ocr")          # 装饰器: 自动累计耗时/次数/峰值/失败
  def ocr(img): ...

  obs.start_sampler()        # main 启动时调用: 每 60s 输出一条聚合监控日志
采样输出示例:
  [perf] rss=512MB threads=9 handles=830 | ocr: 42次 avg=312.4ms max=980 | clip.read: 600次 | 60s窗口
聚合在内存中(锁保护), 采样线程每窗口清零, 业务调用零开销(仅一次加时戳)
"""
import functools
import logging
import threading
import time

log = logging.getLogger("perf")

# 名称 -> [count, total_ms, max_ms, failed]
_STATS: dict[str, list] = {}
_STATS_lock = threading.Lock()


def _record(name: str, ms: float, ok: bool):
    with _STATS_lock:
        st = _STATS.setdefault(name, [0, 0.0, 0.0, 0])
        st[0] += 1
        if ok:
            st[1] += ms
            if ms > st[2]:
                st[2] = ms
        else:
            st[3] += 1


def timed(name: str):
    """切面装饰器: 记录函数耗时/次数(成功/失败), 不改变函数行为/签名"""
    def deco(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            t0 = time.perf_counter()
            try:
                r = fn(*args, **kwargs)
                _record(name, (time.perf_counter() - t0) * 1000, True)
                return r
            except Exception:
                _record(name, (time.perf_counter() - t0) * 1000, False)
                raise
            except BaseException:
                _record(name, (time.perf_counter() - t0) * 1000, False)
                raise
        return wrapper
    return deco


def _rss_mb():
    try:
        import psutil
        return psutil.Process().memory_info().rss / 1024 / 1024
    except Exception:
        return -1.0


def _threads_handles():
    threads = threading.active_count()
    try:
        import ctypes
        k32 = ctypes.windll.kernel32
        out = ctypes.c_ulong()
        if k32.GetProcessHandleCount(ctypes.c_void_p(k32.GetCurrentProcess()),
                                     ctypes.byref(out)):
            return threads, out.value
    except Exception:
        pass
    return threads, -1


def _flush(interval: int):
    """取走窗口内统计并输出一行监控日志(两段式消费, 不阻塞业务路径)"""
    global _STATS
    with _STATS_lock:
        snap, _STATS = _STATS, {}
    threads, handles = _threads_handles()
    rss = _rss_mb()
    parts = [f"rss={rss:.0f}MB threads={threads} handles={handles}"]
    for name, (cnt, total, mx, failed) in (snap or {}).items():
        avg = (total / cnt) if cnt and total else 0.0
        s = f"{name}: {cnt}次"
        if cnt and total:
            s += f" avg={avg:.1f}ms max={mx:.0f}"
        if failed:
            s += f" 失败{failed}"
        parts.append(s)
    parts.append(f"{interval}s窗口")
    log.info("[perf] " + " | ".join(parts))


def start_sampler(interval: int = 60, daemon: bool = True):
    """启动周期采样线程(幂等)"""
    if getattr(start_sampler, "_started", False):
        return
    start_sampler._started = True

    def loop():
        while True:
            try:
                time.sleep(interval)
                _flush(interval)
            except Exception:
                pass
    threading.Thread(target=loop, daemon=daemon, name="perf-sampler").start()
    log.info("[perf] 采样线程已启动(%ds)", interval)
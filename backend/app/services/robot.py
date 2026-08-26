# -*- coding: utf-8 -*-
"""backend.app.services.robot: 采集运行状态(停止信号/实时日志钩子)

被 tasks 主函数与 collect 路由共用的全局状态, 独立成模块避免循环依赖。
"""
import threading

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
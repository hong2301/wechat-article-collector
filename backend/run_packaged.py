# -*- coding: utf-8 -*-
"""打包版后端启动入口(PyInstaller 使用)

与 run.py 的区别:
  - 关闭 reload(避免打包后多进程/端口冲突)
  - 直接导入 app 对象(字符串导入 PyInstaller 无法静态追踪)
  - 固定 127.0.0.1:8000, 由 Electron 负责拉起; 可用 BACKEND_PORT 覆盖(测试用)
  - 看门狗: 若环境变量 WECHAT_PARENT_PID(Electron 主进程PID) 存在,
    则监听父进程存活, 父进程消失后本进程自动退出(防孤儿残留)
"""
import os
import threading
import time

import uvicorn
from app.main import app


def _is_parent_alive(pid):
    """Windows: 检查指定 PID 的进程是否存活(OpenProcess 失败即视为已死)"""
    if os.name != "nt":
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False
    try:
        import ctypes
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        h = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not h:
            return False
        code = ctypes.c_ulong()
        ok = ctypes.windll.kernel32.GetExitCodeProcess(h, ctypes.byref(code))
        ctypes.windll.kernel32.CloseHandle(h)
        return bool(ok and code.value == 259)  # 259 = STILL_ACTIVE
    except Exception:
        return True  # 异常时保守视为存活


def start_watchdog(parent_pid):
    """后台线程: 父进程(主程序)消失后自动退出, 防止孤儿残留"""
    def loop():
        while True:
            time.sleep(3)
            if not _is_parent_alive(parent_pid):
                print(f"[watchdog] 主程序(pid={parent_pid})已退出, 本进程自动关闭")
                os._exit(0)
    threading.Thread(target=loop, daemon=True).start()
    print(f"[watchdog] 已启用: 监听主程序 pid={parent_pid}")


if __name__ == "__main__":
    parent = os.environ.get("WECHAT_PARENT_PID")
    if parent and parent.isdigit():
        start_watchdog(int(parent))
    port = int(os.environ.get("BACKEND_PORT", "8000"))
    uvicorn.run(app, host="127.0.0.1", port=port, reload=False)
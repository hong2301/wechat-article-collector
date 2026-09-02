# -*- coding: utf-8 -*-
os.environ.setdefault("BACKEND_PORT", "8000")  # 端口单一来源: 供内部自调用/其它模块读取
"""后端启动入口: python backend/run.py
启动前检测 8000 端口占用, 被占则给出明确提示(避免重复 dev 起多个后端抢端口)"""
import os
import socket
import sys

import uvicorn

HOST = "127.0.0.1"
PORT = int(os.environ.get("BACKEND_PORT", "8000"))   # 与打包版一致, 可用环境变量改端口


def port_in_use(host, port):
    """端口是否已被占用: 能连上 = 占用"""
    try:
        s = socket.create_connection((host, port), timeout=0.5)
        s.close()
        return True
    except OSError:
        return False


if __name__ == "__main__":
    if port_in_use(HOST, PORT):
        print("\n" + "=" * 52)
        print(f"❌ 端口 {PORT} 已被占用!")
        print(f"   可能已有后端在运行, 请先关闭旧进程:")
        print(f"   taskkill /F /IM collector-backend.exe   (打包版后端)")
        print(f"   taskkill /F /IM python.exe              (开发版后端, 慎用)")
        print("=" * 52 + "\n")
        sys.exit(1)
    uvicorn.run("app.main:app", host=HOST, port=PORT, reload=True)
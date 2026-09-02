# -*- coding: utf-8 -*-
"""打包 FastAPI 后端为单目录可执行程序 (PyInstaller onedir)

产物: backend/dist/collector-backend/
  由 Electron 在 resources/backend 下随 app 一起分发并 spawn 启动

用法:
  cd backend && python build_backend.py
"""
import os
import shutil
import subprocess
import sys

BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
DIST = os.path.join(BACKEND_DIR, "dist", "collector-backend")

def _gen_version():
    """构建时: 读根 package.json version -> 生成 app/version.py(打包进 exe, 版本单一来源)"""
    import json
    try:
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(root, "package.json"), encoding="utf-8") as f:
            ver = json.load(f).get("version", "")
        lines = ["# -*- coding: utf-8 -*-",
                 '"""程序版本(构建时由根 package.json 生成, 打包进 exe)"""',
                 "VERSION = %r" % ver]
        vp = os.path.join(BACKEND_DIR, "app", "version.py")
        with open(vp, "w", encoding="utf-8") as f:
            f.write(chr(10).join(lines))
        print("  版本注入:", ver)
    except Exception as e:
        print("警告: 版本注入失败", e)


def main():
    _gen_version()
    # 清理旧产物
    for p in (DIST, os.path.join(BACKEND_DIR, "build"), os.path.join(BACKEND_DIR, "collector-backend.spec")):
        if os.path.exists(p):
            shutil.rmtree(p, ignore_errors=True)

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean",
        "--name", "collector-backend",
        "--onedir",
        "--distpath", os.path.join(BACKEND_DIR, "dist"),
        "--workpath", os.path.join(BACKEND_DIR, "build"),
        "--specpath", os.path.join(BACKEND_DIR),
        "--paths", BACKEND_DIR,
        # uvicorn 动态加载子模块
        "--collect-all", "uvicorn",
        "--collect-submodules", "fastapi",
        # OCR 引擎(模型文件在包内)
        "--collect-all", "rapidocr_onnxruntime",
        # onnxruntime: 只收 DLL/元数据, 不全收子模块 --- 否则 quantization 会拖入 torch(365MB)
        "--collect-binaries", "onnxruntime",
        "--copy-metadata", "onnxruntime",
        # 排除冗余大模块(未使用的依赖链, 累计 500MB+)
        "--exclude-module", "torch",
        "--exclude-module", "pandas",
        "--exclude-module", "matplotlib",
        "--exclude-module", "llvmlite",
        "--exclude-module", "numba",
        "--exclude-module", "Pythonwin",
        "--exclude-module", "onnxruntime.quantization",
        "--hidden-import", "PIL.ImageGrab",
        "--hidden-import", "uvicorn.logging",
        "--hidden-import", "uvicorn.loops.auto",
        "--hidden-import", "uvicorn.protocols.http.auto",
        "--hidden-import", "uvicorn.protocols.websockets.auto",
        os.path.join(BACKEND_DIR, "run_packaged.py"),
    ]
    print(" ".join(cmd))
    subprocess.run(cmd, check=True)
    print(f"[build_backend] 完成: {DIST}")
    print(f"   入口: {os.path.join(DIST, 'collector-backend.exe')}")

if __name__ == "__main__":
    main()
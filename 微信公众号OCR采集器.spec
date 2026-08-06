# -*- mode: python ; coding: utf-8 -*-
# PyInstaller 打包配置：微信公众号OCR采集器
# 生成: pyinstaller 微信公众号OCR采集器.spec
# 产物: dist/微信公众号OCR采集器.exe

import os
from PyInstaller.utils.hooks import collect_all

# 收集 rapidocr_onnxruntime 全部资源（onnx 模型 + config.yaml）
rapidocr_datas, rapidocr_binaries, rapidocr_hidden = collect_all("rapidocr_onnxruntime")

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=rapidocr_binaries,
    datas=rapidocr_datas + [("README.md", ".")],
    hiddenimports=rapidocr_hidden + [
        "onnxruntime",
        "PIL",
        "requests",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="微信公众号OCR采集器",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,          # GUI 程序，不显示控制台
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

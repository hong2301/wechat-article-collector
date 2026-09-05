# -*- coding: utf-8 -*-
"""版本硬编码(构建时生成/覆盖): 由根目录 .env 的 APP_VERSION / WECHAT_VERSION 注入
- 构建: build.js 组装前读 .env(缺失回退根 package.json/TEMPLATE) 重写本文件, PyInstaller 打进 exe
- dev : 直接读本文件(提交的当前版本), 与打包版一致
- 数据库/接口不再存版本(从 settings 表剔除, 同步脚本删除)
"""
APP_VERSION = "4.4.0"       # 程序版本(单一来源: 根 .env APP_VERSION → 构建时写入)
WECHAT_VERSION = "4.1.13.12"  # 微信基准版本(单一来源: 根 .env WECHAT_VERSION → 构建时写入)

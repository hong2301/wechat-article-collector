# -*- coding: utf-8 -*-
"""运行环境统一判定: dev 版 / 打包(正式)版 —— 只看环境变量 WECHAT_ENV(前后端皆用)
- dev 入口 run.py              setdefault WECHAT_ENV=dev
- 打包入口 run_packaged.py     setdefault WECHAT_ENV=prod
- Electron(main.js)            spawn 后端时注入 WECHAT_ENV(值统一为 APP_ENV)
- 业务代码一律用 env()/is_prod()/is_dev(), 不散落 sys.frozen / app.isPackaged 等判断
"""
import os


def env():
    """运行环境: 'dev' / 'prod'(默认 dev)"""
    return os.environ.get("WECHAT_ENV", "dev")


def is_prod():
    """是否打包(正式)版"""
    return env() == "prod"


def is_dev():
    """是否开发版"""
    return not is_prod()

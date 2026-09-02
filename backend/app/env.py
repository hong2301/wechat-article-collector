# -*- coding: utf-8 -*-
"""运行环境统一判定: dev / prod 只看环境变量 WECHAT_ENV(前后端皆用)
- dev 入口 run.py    注入 WECHAT_ENV=dev
- 正式入口 run_packaged.py 注入 WECHAT_ENV=prod
- 业务代码一律用 is_prod()/is_dev()/env(), 不再散落 sys.frozen/app.isPackaged 等判断
"""
import os

_KEY = "WECHAT_ENV"


def env():
    """运行环境: 'dev' / 'prod'(默认 dev)"""
    return os.environ.get(_KEY, "dev")


def is_prod():
    """是否正式(打包)版"""
    return env() == "prod"


def is_dev():
    """是否开发版"""
    return not is_prod()
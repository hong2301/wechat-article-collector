# -*- coding: utf-8 -*-
"""点位自动设置子包: engine=机制(装饰器/上下文/锁/停止/排序/run-all)
各点位族文件按 @flow_point 注册进 POINT_FLOWS, 此处聚合导入触发注册"""
from .engine import *  # noqa: F401,F403
from . import calc_points  # noqa: F401  触发点位注册
from . import content_points  # noqa: F401  触发点位注册
from . import split_points  # noqa: F401  触发点位注册
from . import link_points  # noqa: F401  触发点位注册
from . import base_points  # noqa: F401  触发点位注册

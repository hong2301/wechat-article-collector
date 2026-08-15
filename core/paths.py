# -*- coding: utf-8 -*-
"""core.paths: 常量 + 路径函数(独立, 无其他模块依赖)"""
import os
import sys

APP_NAME = "微信公众号OCR采集器"
VERSION = "V1.1.7"
WECHAT_VERSION = "4.1.11.24"    # 依赖: 微信 PC 版版本

CONFIG_DIR = "config"
INPUT_CSV = "input.csv"
UI_STATE_FILE = "ui_state.json"
DATA_DIR = "data"
COLLECTED_CSV = "collected.csv"
COLLECTED_HEADER = ["公众号名称", "日期", "标题", "链接", "阅读", "点赞",
                    "转发", "喜欢", "评论", "写入时间", "互动截图", "阅读截图"]
POINTS_CSV = "points.csv"
CUSTOM = "custom"

LOG_FILE = os.path.join(CONFIG_DIR, "log.txt")


def _script_root():
    """项目根目录（打包后为 exe 所在目录，开发时为 main.py 所在目录）"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _config_dir():
    """配置文件目录（input.csv / ui_state.json）"""
    return os.path.join(_script_root(), CONFIG_DIR)


def _input_path():
    return os.path.join(_config_dir(), INPUT_CSV)


def _points_path():
    return os.path.join(_config_dir(), POINTS_CSV)


def _data_dir():
    """数据目录（文章HTML + collected.csv）"""
    return os.path.join(_script_root(), DATA_DIR)


def _collected_path():
    return os.path.join(_data_dir(), COLLECTED_CSV)


__all__ = ["APP_NAME", "VERSION", "WECHAT_VERSION", "CONFIG_DIR", "INPUT_CSV",
           "UI_STATE_FILE", "DATA_DIR", "COLLECTED_CSV", "COLLECTED_HEADER",
           "POINTS_CSV", "CUSTOM", "LOG_FILE", "_script_root", "_config_dir",
           "_input_path", "_points_path", "_data_dir", "_collected_path"]

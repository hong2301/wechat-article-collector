# -*- coding: utf-8 -*-
"""backend.app.services.tasks: 任务组合模块

用途: 把 computer(电脑交互原语) 等底层模块按业务步骤组合成"任务函数"。
此文件为子包聚合入口: 按功能域拆分子模块, 统一对外导出。

子模块:
  wx_window       窗口初始化(微信/搜一搜/查询/采集器)
  article_collect 文章采集(列表定位/保存/4指标/阅读数OCR/主流程)
  comment_collect 评论采集(展开回复/豆包AI识别/主循环)
  helpers         后台线程池 + 调试截图
"""
from ...core import computer as pc  # noqa: F401
from ...core.common import _read_point, wait_page_stable  # noqa: F401
from ...core.robot import (request_stop, clear_stop, stop_requested,  # noqa: F401
                           bind_tasks_echo, tasks_echo)
from ...database import get_conn  # noqa: F401

from .wx_window import (init_wechat_window, search_window_init, search_query,  # noqa: F401
                        init_app_window, WECHAT_MAIN, WECHAT_APPEX,
                        APP_TITLE, APP_EXE)
from .helpers import _submit_bg, _done_bg, wait_bg_done  # noqa: F401
from .article_collect import (article_data_collect, article_list_wait_stable,  # noqa: F401
                              _save_article_base, _save_html_block,
                              _bg_ai_metrics, _collect_metrics,
                              _bg_reads_ocr, _collect_reads)
from . import comment_collect  # noqa: F401  确保评论采集模块加载

# 模块加载时启用 DPI 感知(进程级, 幂等): 确保所有点位坐标用物理像素, 避免缩放偏移
pc.enable_dpi_awareness()
# 微信公众号OCR采集器 - 架构关系文档

> 由分析 main.py(3141行) 生成，作为模块化拆分的蓝图。

## 一、当前结构
- 单文件 `main.py`：3141 行 / 134 个 def / 15 个 class

## 二、拆模块方案(按依赖耦合度排序)

### core/win32util.py — 键鼠/窗口/剪贴板低层
- 低层结构类: POINT MSLLHOOKSTRUCT KEYBDINPUT MOUSEINPUT _INPUTUNION INPUT KBDLLHOOKSTRUCT PROCESSENTRY32W
- 钩子/锁: EscListener MouseLock MousePointCollector
- 函数: _u32 _k32 get_top_windows get_wechat_pids find_wechat_window
  _force_foreground find_taskbar hide_taskbar show_taskbar snap_wechat_left
  mouse_click scroll_down_at scroll_up_at type_text ctrl_key ctrl_shift_key key_press
  get_foreground_window_info set_clipboard_text clear_clipboard read_clipboard_text
  enable_dpi_awareness

### core/image_ocr.py — OCR/截图/颜色/WebP
- get_ocr_engine screenshot_region _text_brightness ocr_region _parse_interact_text(依赖?)
  _pil_to_b64 capture_region_base64 ocr_img find_read_in_img find_time_items extract_reads extract_likes

### core/doubao_api.py — 豆包识别
- doubao_recognize_interact DOUBAO_URL/DOUBAO_MODEL/DOUBAO_PROMPT _parse_interact_text

### core/datastore.py — 数据层(CSV/配置持久化)
- _script_dir _config_dir _input_path _points_path _data_dir _collected_path
  load_raw_input_rows load_input_rows write_input_csv update_input_status
  append_collected load_points write_points load_ui_state save_ui_state
  parse_date time_range_desc

### core/utils.py — 杂项工具
- log clean_filename resolve_article_date fetch_article check_dependencies _grab_screen

### main.py(保留) — App类 + GUI弹窗 + 入口
- App(1664-3089, GUI+采集核心) DatePicker PointsDialog main check_dependencies
- 通过 `from core.xxx import *` 接入各模块

## 三、关键依赖
- image_ocr 依赖 win32util(截图) + datastore(_data_dir)
- doubao_api 独立(仅 requests/re)
- datastore 依赖 utils(log)
- App 依赖全部

## 四、风险控制
- 保持函数名/签名不变,纯搬家(logic 零改动)
- 分模块提交,每模块冒烟测试
- PyInstaller: spec 自动跟踪 import, 多文件可打包

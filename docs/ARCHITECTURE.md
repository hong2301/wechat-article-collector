# 微信公众号OCR采集器 - 架构关系文档

> **状态: V3.0.0（2026-08-17）**
> 原单文件 main.py 已按关注点分离拆分为 core/ 6 个模块。
> main.py(GUI+App采集核心) + core/ 工具层。

## 一、当前结构

- `main.py`: App 类 + GUI + 入口（高内聚保留，含采集流程编排）
- `core/`: paths / utils / win32util / image_ocr / doubao_api / datastore
- `docs/`: 本架构文档

## 二、模块职责与函数清单

### core/paths.py — 常量与路径（打包兼容）

- 常量: APP_NAME / VERSION(V3.0.0) / WECHAT_VERSION(4.1.11.24)
- CSV 表头: COLLECTED_HEADER(14列) / COMMENTS_HEADER(14列, 含采集时间)
- 路径: _script_root / _config_dir / _data_dir / _input_path / _points_path / _collected_path

### core/win32util.py — 键鼠/窗口/剪贴板低层

- 低层结构: POINT, MSLLHOOKSTRUCT, KEYBDINPUT, MOUSEINPUT, _INPUTUNION, INPUT, KBDLLHOOKSTRUCT, PROCESSENTRY32W
- 钩子/锁: EscListener(ESC停止), MouseLock, MousePointCollector
- 函数: _u32, _k32, get_top_windows, get_wechat_pids, find_wechat_window,
  _force_foreground, find_taskbar, hide_taskbar, show_taskbar, snap_wechat_left,
  mouse_move(移动不点击), mouse_click, scroll_down_at, scroll_up_at,
  type_text, ctrl_key, ctrl_shift_key, key_press, set/read_clipboard_text,
  enable_dpi_awareness

### core/image_ocr.py — OCR/截图/颜色/WebP

- get_ocr_engine(单例+锁), screenshot_region, _image_changed(截图对比),
  _region_has_content(像素检测), _text_brightness(时间文本亮度过滤),
  ocr_region, ocr_img(返回含坐标/亮度), find_read_in_img, find_time_items,
  extract_reads, _pil_to_b64(WebP lossless method=6), capture_region_base64

### core/doubao_api.py — 豆包识图（纯净，无OCR）

- doubao_recognize_interact: 4指标(点赞/转发/喜欢/留言)识别
- doubao_extract_comments: 评论区评论提取(JSON数组输出)
- COMMENTS_PROMPT: 评论结构提示词(层级/置顶/作者/缩进/截断处理)
- DoubaoQuotaError: 无额度异常(403 + AccountOverdueError/欠费码)
  - 两函数在状态码403时检测并抛出, 调用方捕获后停止后续调用
- 函数内不依赖 log(避免工作线程 NameError), 失败静默返回

### core/datastore.py — 数据层(CSV/配置持久化)

- 文章: append_collected(14列, 含原创/IP属地)
- 评论: calc_comment_id(MD5前16位), append_comments(批次内去重+采集时间),
  delete_comments(按文章链接清理误采集)
- input: load_raw_input_rows / load_input_rows / write_input_csv / update_input_status
- points: load_points / write_points
- 配置: load_ui_state / save_ui_state
- 工具: parse_date / time_range_desc

### core/utils.py — 杂项工具

- log(控制台+data/log.txt, 自动建目录, 线程安全)
- clean_filename, resolve_article_date, check_dependencies
- fetch_article(抓取标题/时间/HTML + 原创/IP属地解析)

## 三、关键依赖

```
main.py ──┐
          ├→ core.paths (常量/路径)
          ├→ core.utils (log/fetch_article)
          ├→ core.doubao_api (4指标/评论识别, DoubaoQuotaError)
          ├→ core.datastore (CSV读写)
          ├→ core.image_ocr (OCR/截图/WebP)
          └→ core.win32util (键鼠/窗口)
image_ocr → win32util(截图) + datastore(_data_dir)
datastore → utils(log)
doubao_api 独立(仅 requests/re)
```

## 四、采集流程架构

### 文章采集(单任务)

```
复制链接(点位18, 无OCR) → 4指标截图(异步提交识别future)
  → 乐观并发: 立即点点位21 → 评论区稳定检测 → 评论采集(与识别并行)
  → 等future结果(仅评论采集开启时) → (可选)采集阅读数
  → 后台线程池 _spawn_fetch(抓HTML + 原创/IP + 互动数据识别)
```

### 评论采集

```
循环(截图点位22/23):
  截图对比: 相同→滚动跳过; 连续3次相同→到底停止
  OCR"回复"按钮 → 点击展开二级
  并行线程池(2线程): 豆包识别评论(网络) + OCR名称行层级校准(本地)
  跨轮去重(内存seen_ids) → append_comments → 滚动
停止: 到底 / 一级上限 / future确认留言=0(delete_comments清理)
```

### 无额度熔断

```
豆包403+欠费码 → DoubaoQuotaError → 捕获: log明确提示 + self._quota_error=True
→ 后续所有豆包调用点检查标志跳过
```

## 五、数据流

```
采集 → collected.csv(14列文章数据) / comments.csv(14列评论数据)
评论ID: md5(名称|地区|时间|点赞|正文|层级) 前16位
父级ID: 二级"回复某某"→某某的ID; 否则→所属一级ID
采集时间: 每条评论第一次被看到的时间(精确到秒)
去重: 批次内(豆包重复) + 本次采集会话跨轮(内存), 不读CSV历史
```

## 六、线程安全

- OCR 推理在 `_ocr_lock` 下（onnxruntime Session 非线程安全）
- 评论识别用 ThreadPoolExecutor(2线程)：豆包(网络)与OCR(本地)并行
- 4指标识别提交到 `_fetch_executor` 后台线程池
- CSV 写入均在 `_log_lock` 下（append 模式 + 表头兼容）

## 七、打包说明

- PyInstaller 打包（spec 自动跟踪 import），脚本与 spec 仅本地使用，不上传仓库
- Version 从 `core/paths.py` 读取（V3.0.0）

## 八、风险控制

- 豆包 mini 模型无法感知像素级缩进 → 层级用 OCR 名称行 x 坐标判断（>15px=二级）
- 模型随机性 → 不依赖"是否缩进"字段作为唯一依据（OCR 覆盖）
- 网络/额度异常 → DoubaoQuotaError 熔断 + 明确日志
- 误采集 → 留言=0 时 delete_comments 按链接清理
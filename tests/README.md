# 测试（tests/）

前后端所有自动化测试统一收在这个目录（根目录不散落测试文件/产物）。

## 两套测试

| 套 | 位置 | 跑法 | 测什么 |
|---|---|---|---|
| **UI 端到端**（Playwright） | `specs/` + `fixtures/` + `utils/` + `setup/` | `npm run test:ui` | 通过真实页面操作前端（dev 浏览器 / Electron） |
| **后端接口矩阵**（pytest） | `api/` | `npm run test:api` | 直接调用后端接口（TestClient，隔离测试库，不动真实数据） |

## 目录职责

```
tests/
├─ api/                      后端接口矩阵(pytest)
│  ├─ conftest.py                隔离库: 复制 scripts/template_collector.db -> 临时目录, 设 WECHAT_COLLECTOR_DATA_DIR
│  └─ test_*.py                  按模块: accounts / points / settings / articles ...
├─ specs/                     UI 用例(Playwright): 按功能分目录 ui/ automation/ health/...
├─ fixtures/                  Page Object: 一个页面一个文件(home.ts ...), 用例里直接调
├─ utils/                     通用工具: API 请求 / SSE 流读取 / 日志断言(e2e.ts)
├─ setup/                     global-setup/teardown: 自动拉起 next dev + 后端, 记录日志基线
├─ playwright.config.ts       UI 测试配置(双 project: dev-browser / electron)
└─ pytest.ini                 API 测试配置
```

## 如何新增

**加一个 UI 用例**
1. 若操作新页面 → 先建 `fixtures/<page>.ts`（Page Object，定位/填表/断言都放这）
2. 在 `specs/` 对应目录加 `<功能>.spec.ts`，用 fixture 写"像人操作"的步骤
3. 全链路类（触发采集/自动设置）打 `@all`/`@dev` 标签，动屏的单独文件

**加一个接口用例**
1. `tests/api/test_<模块>.py` 写用例（直接用 `client` fixture，它已经套了隔离库）
2. 会动微信/屏幕的用例标 `@pytest.mark.manual`（默认跳过，`-m manual` 手动跑）

## 写用例注意（项目踩过的坑）

- antd 中文按钮会插空格：用 `hasText: /保\s*存/` 而非精确文案
- 弹窗定位用 `.ant-modal`（antd6 结构）
- 保存/关闭后要等弹窗消失再操作页面（遮罩会拦截点击）
- 列表接口有 400ms 去重缓存：连续写入后立读前先 `sleep(0.7)`
- 测试数据用唯一标识（时间戳后缀），用例自包含、跑完清理

## 产物（都收在 tests/ 内, 已 gitignore）

- `tests/.pytest_cache/`、`tests/.tmp-tests/`（pytest 缓存/临时库）
- `tests/artifacts/`（trace/截图/视频）、`tests/report/`（HTML 报告）、`tests/.baseline`（日志基线）

## 环境

- 依赖：`@playwright/test`（根 devDependencies）+ `pytest`（Python 环境）
- UI 测试会自动拉起 next dev(3000) 与开发后端(8000)；Electron 用例需先打包
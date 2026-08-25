# Electron 工程化更新方向（待办清单）

> 状态：V4.0 已可完整运行（前端 Next.js 静态导出 + Electron 壳 + Python 后端）。
> 本文档记录**未来**的工程化补课方向，暂不实现，按需逐步推进。

---

## 背景

当前架构：

```
Next.js(TS, 静态导出) → frontend/next/out
Electron 壳(JS, main.js) → 加载 out + spawn 后端 exe
Python 后端(FastAPI, PyInstaller) → 127.0.0.1:8000
数据: 环境变量 WECHAT_COLLECTOR_DATA_DIR 约束(开发=项目根data, 打包=exe旁data)
```

已做对的部分：`contextIsolation` + `nodeIntegration:false`、后端独立进程（天然隔离）、看门狗防孤儿后端、后端 DPI 处理。
空白部分见下，按优先级排列。

---

## 一、低成本必修（建议尽快补，共 4 项）

### 1. 单实例锁（Single Instance Lock）
- **缺口**：重复双击 exe 会开多个窗口 + 多个后端抢 8000（当前仅端口层复用兜底，应用层未拦截）
- **做法**：`app.requestSingleInstanceLock()`，拿不到锁则退出并 `app.focus()` 已有实例
- **预估**：约 10 行

### 2. 渲染进程崩溃处理
- **缺口**：`render-process-gone` / `did-fail-load` 无监听，崩溃即白屏，无提示无恢复
- **做法**：监听崩溃事件 → 弹错误页/对话框 → 可选自动 reload
- **预估**：约 30 行 + 简单错误页面

### 3. 窗口状态记忆
- **缺口**：每次启动固定 1180x760 居中
- **做法**：退出时保存 `win.getBounds()`，启动时恢复（写 userData 下 json）
- **预估**：约 20 行

### 4. CSP 安全头
- **缺口**：渲染层未配置 Content-Security-Policy（Electron 官方安全清单要求项）
- **做法**：`out/index.html` 加 `http-equiv="Content-Security-Policy"`（默认 `default-src 'self'`，按需放行 `data:`/`blob:`）
- **预估**：Next 导出模板内加 meta 即可

---

## 二、中期方向（按分发/使用场景决定）

### 5. 自动更新（electron-updater）
- 价值：发版后用户自动更新，免手动重新下载
- 依赖：需要发布渠道（GitHub Releases / 私有服务器）；内部小范围使用可后置

### 6. 崩溃监控 / 统一诊断
- 现状：仅主进程 main.log
- 做法：渲染进程错误 + 后端启动时序统一落盘/上报（crashReporter 或轻量事件日志）

### 7. 自动化测试 / CI
- 现状：零自动化，回归靠手动点
- 做法：Playwright 驱动 Electron 冒烟测试（页面加载/后端拉起/基本操作），可挂 GitHub Actions

---

## 三、可选架构演进（考虑过，暂不执行）

### electron-vite 迁移评估
- **它能给的**：主进程 TS 化、构建链统一（主/preload/渲染一个 CLI）、dev HMR 更好、打包体积更小（Next 导出换 Vite 可减几十 MB）
- **代价**：渲染层要从 Next.js 换 Vite+React —— 三个页面 + 共享组件需重建，现有功能全部重做一遍
- **结论**：当前 Next App Router 本身即 TS 体系、且更主流；除非未来要大幅减体积/统一构建链，否则不迁移。如真要尝试，可在独立分支做原型对比。

---

## 优先级速览

| # | 事项 | 优先级 | 成本 |
|---|---|---|---|
| 1 | 单实例锁 | 🔴 高 | ~10 行 |
| 2 | 渲染崩溃处理 | 🔴 高 | ~30 行 |
| 3 | 窗口状态记忆 | 🟡 中 | ~20 行 |
| 4 | CSP | 🟡 中 | meta 一行 |
| 5 | 自动更新 | 🟢 低(看分发) | 中 |
| 6 | 诊断/上报 | 🟢 低 | 中 |
| 7 | 测试/CI | 🟢 低 | 中 |
| — | electron-vite 迁移 | 暂缓 | 高 |

---

*维护：每次发版前过一遍此清单，低成本 4 项完成后归档。*
# 项目规则：微信公众号OCR采集器

## Git 操作纪律（重要）
- **任何 git 写操作（commit、push、merge、rebase、delete 等）在执行前，必须先明确征求用户同意**。
- 完成改动后先向用户汇报，问「要提交吗？」；得到用户明确同意后才执行。
- 不要擅自提交或推送。用户未明确同意前，不得运行任何可能改写仓库状态的 git 命令。

## 技术要点
- 架构：Next.js 前端（frontend/next）+ Electron 壳（frontend/electron）+ Python FastAPI 后端（backend）+ SQLite
- 分支：reactor/new 为主要开发分支
- 后端端口 8000，前后端通过 REST/SSE 通信
- 业务逻辑只在后端，Electron 是纯壳
- npm 代理已清除（旧 7892 失效），国内装包用 --registry=https://registry.npmmirror.com
- UI 全中文，不用英文按钮（用「确认/取消」）

import { defineConfig } from "@playwright/test";
import path from "path";

// E2E 配置: 双模式
//   chromium: dev 浏览器(localhost:3000 -> 开发后端 8000)
//   electron: 打包版/electron(localhost 生产后端 8001), 需要先 build 出 electron
export default defineConfig({
  testDir: "./specs",
  timeout: 120_000,               // 全链路(点位/采集)单用例上限
  expect: { timeout: 10_000 },
  fullyParallel: false,           // 会移动真实微信窗口/锁键鼠, 必须串行
  workers: 1,
  retries: 0,
  reporter: [["list"], ["html", { outputFolder: path.join(__dirname, "report"), open: "never" }]],
  outputDir: path.join(__dirname, "artifacts"),        // trace/screenshot/video 全进 tests/artifacts
  use: {
    baseURL: process.env.E2E_BASE_URL || "http://localhost:3000",  // dev 前端
    trace: "retain-on-failure",    // 失败保留 trace
    screenshot: "only-on-failure",
    video: "retain-on-failure",
  },
  projects: [
    // ---------- dev: 浏览器操作 Next(localhost:3000 -> 8000) ----------
    {
      name: "dev-browser",
      grep: /@dev|@all/i,
    },
    // ---------- 生产: Electron 启动真实 exe(内部 8001) ----------
    {
      name: "electron",
      grep: /@electron|@all/i,
    },
  ],
  globalSetup: "./setup/global-setup.ts",
  globalTeardown: "./setup/global-teardown.ts",
});
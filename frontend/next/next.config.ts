import type { NextConfig } from "next";
import fs from "fs";
import path from "path";

// 前端显示版本号: 自动跟随 package.json(升版本只改一处)
const pkg = JSON.parse(fs.readFileSync(path.join(__dirname, "package.json"), "utf8"));

const nextConfig: NextConfig = {
  // 将此项目目录作为 tracing 根，消除 package-lock 在 Git 仓库外的警告
  outputFileTracingRoot: path.join(__dirname, ".."),
  // 静态导出(生产时 Electron loadFile 加载 out/index.html)
  output: "export",
  images: { unoptimized: true },
  // 资源相对路径仅生产(静态导出/fle://)需要; dev(http)下保持默认, 否则子路由资源404
  assetPrefix: process.env.NODE_ENV === "production" ? "./" : "",
  env: { NEXT_PUBLIC_APP_VERSION: pkg.version },
};

export default nextConfig;

import type { NextConfig } from "next";
import path from "path";

const nextConfig: NextConfig = {
  // 将此项目目录作为 tracing 根，消除 package-lock 在 Git 仓库外的警告
  outputFileTracingRoot: path.join(__dirname, ".."),
  // 静态导出(生产时 Electron loadFile 加载 out/index.html)
  output: "export",
  images: { unoptimized: true },
  // 资源相对路径: Electron 用 file:// 协议加载时 /_next 绝对路径会指向盘根目录导致 404
  assetPrefix: "./",
};

export default nextConfig;

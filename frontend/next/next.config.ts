import type { NextConfig } from "next";
import path from "path";

const nextConfig: NextConfig = {
  // 将此项目目录作为 tracing 根，消除 package-lock 在 Git 仓库外的警告
  outputFileTracingRoot: path.join(__dirname, ".."),
  // 静态导出(生产时 Electron loadFile 加载 out/index.html)
  output: "export",
  images: { unoptimized: true },
};

export default nextConfig;

import type { Metadata } from "next";
import { API_BASE } from "./lib/api";
import { AntdRegistry } from "@ant-design/nextjs-registry";
import { ConfigProvider } from "antd";
import Header from "./Header";
import "./globals.css";

export const metadata: Metadata = {
  title: "微信公众号采集器",
  description: "公众号文章 / 互动数据 / 评论区自动采集",
};

// CSP(生产严格, 静态导出生效): dev 不注入 — Next HMR 依赖 unsafe-eval/devtools,
// dev 注入会引发重复加载等异常; 生产的严格基线才是真正消除 Electron 安全警告的位置
const CSP = process.env.NODE_ENV === "production"
  ? `default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; font-src 'self' data:; connect-src 'self' ${API_BASE}; frame-src 'none'; object-src 'none'; base-uri 'self'`
  : "";

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh-CN">
      {CSP && <head><meta httpEquiv="Content-Security-Policy" content={CSP} /></head>}
      <body style={{ margin: 0 }}>
        <AntdRegistry>
          <ConfigProvider>
            <div style={{ height: "100vh", boxSizing: "border-box", overflow: "hidden", display: "flex", flexDirection: "column", background: "#f5f6f8", padding: "0 20px 14px" }}>
              <Header />
              <div style={{ flex: 1, minHeight: 0, overflow: "hidden" }}>{children}</div>
            </div>
          </ConfigProvider>
        </AntdRegistry>
      </body>
    </html>
  );
}

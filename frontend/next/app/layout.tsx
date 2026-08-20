import type { Metadata } from "next";
import { AntdRegistry } from "@ant-design/nextjs-registry";
import { ConfigProvider } from "antd";
import Header from "./Header";
import "./globals.css";

export const metadata: Metadata = {
  title: "微信公众号采集器",
  description: "公众号文章 / 互动数据 / 评论区自动采集",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh-CN">
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

"use client";

import { useEffect, useState } from "react";
import { Tooltip } from "antd";
import { useWechatStatus } from "./components/useWechatStatus";
import QuickStartDialog from "./components/QuickStartDialog";

const WechatIcon = ({ color }: { color: string }) => (
  <svg width="18" height="18" viewBox="0 0 24 24" fill={color} xmlns="http://www.w3.org/2000/svg"><path d="M9.5 4C5.36 4 2 6.69 2 10c0 1.89.96 3.58 2.5 4.71L3.7 17.2a.35.35 0 0 0 .5.4l2.9-1.66c.74.2 1.53.31 2.4.31.01 0 .02 0 .03-.01a4.2 4.2 0 0 1-.2-1.29c0-2.68 2.58-4.95 5.73-4.95.3 0 .59.03.88.07C15.08 6.28 12.58 4 9.5 4zm-2.58 3.84a.87.87 0 1 1 0-1.74.87.87 0 0 1 0 1.74zm5.16 0a.87.87 0 1 1 0-1.74.87.87 0 0 1 0 1.74zM22 15.09c0-2.4-2.69-4.34-6.02-4.34-3.32 0-6.02 1.94-6.02 4.34 0 2.39 2.7 4.33 6.02 4.33.7 0 1.38-.1 2-.29l2.37 1.36a.27.27 0 0 0 .39-.3l-.74-2.01C21.4 17.51 22 16.36 22 15.09zm-7.35-.15a.67.67 0 1 1 0-1.34.67.67 0 0 1 0 1.34zm2.66 0a.67.67 0 1 1 0-1.34.67.67 0 0 1 0 1.34z"/></svg>
);

const Telescope = () => (
  <svg width="22" height="22" viewBox="0 0 1024 1024" fill="#fff" xmlns="http://www.w3.org/2000/svg"><path d="M934.4 323.84l-42.666667-165.12a128 128 0 0 0-158.293333-90.453333l-82.346667 22.186666a42.666667 42.666667 0 0 0-30.293333 52.48l11.093333 42.666667L178.773333 305.493333a42.666667 42.666667 0 0 0-30.293333 52.053334l11.093333 42.666666-42.666666 11.093334a42.666667 42.666667 0 0 0 10.666666 85.333333 46.506667 46.506667 0 0 0 11.093334 0l42.666666-11.52 11.093334 42.666667a42.666667 42.666667 0 0 0 19.626666 25.6 42.666667 42.666667 0 0 0 21.333334 5.973333 32 32 0 0 0 11.093333 0L384 515.413333v17.92a123.733333 123.733333 0 0 0 12.8 54.613334l-213.333333 213.333333a42.666667 42.666667 0 0 0 60.16 60.586667l213.333333-213.333334 11.946667 4.693334v264.106666a42.666667 42.666667 0 0 0 85.333333 0v-263.68a107.52 107.52 0 0 0 12.373333-5.12l213.333334 213.333334a42.666667 42.666667 0 1 0 60.16-60.586667l-213.333334-213.333333A131.84 131.84 0 0 0 640 533.333333v-85.333333l57.6-15.36 10.666667 42.666667a42.666667 42.666667 0 0 0 42.666666 31.573333h11.093334l82.346666-22.186667a128 128 0 0 0 90.026667-160.853333zM554.666667 533.333333a42.666667 42.666667 0 0 1-11.946667 29.44 42.666667 42.666667 0 0 1-29.44 11.946667 42.666667 42.666667 0 0 1-29.866667-12.373333 42.666667 42.666667 0 0 1-12.373333-29.866667v-42.666667L554.666667 469.333333z m-290.56-74.24l-22.186667-82.346666 412.16-110.506667 11.093333 42.666667 11.093334 42.666666z m583.68-81.066666a42.666667 42.666667 0 0 1-26.026667 20.053333l-42.666667 11.093333-33.28-123.733333L725.333333 203.093333l-11.093333-42.666666 42.666667-11.093334a42.666667 42.666667 0 0 1 52.48 30.293334l42.666666 165.12a42.666667 42.666667 0 0 1-4.266666 33.28z"/></svg>
);

const GithubIcon = () => (
  <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor"><path d="M12 .5C5.7.5.5 5.7.5 12c0 5.1 3.3 9.4 7.9 10.9.6.1.8-.3.8-.6v-2c-3.2.7-3.9-1.5-3.9-1.5-.5-1.3-1.3-1.7-1.3-1.7-1-.7.1-.7.1-.7 1.1.1 1.7 1.2 1.7 1.2 1 1.7 2.6 1.2 3.2.9.1-.7.4-1.2.7-1.5-2.4-.3-4.9-1.2-4.9-5.3 0-1.2.4-2.1 1.1-2.9-.1-.3-.5-1.4.1-2.9 0 0 .9-.3 2.9 1.1.8-.2 1.7-.3 2.6-.3s1.8.1 2.6.3c2-1.4 2.9-1.1 2.9-1.1.6 1.5.2 2.6.1 2.9.7.8 1.1 1.7 1.1 2.9 0 4.1-2.5 5-4.9 5.3.4.3.8 1 .8 2.1v3.1c0 .3.2.7.8.6 4.6-1.5 7.9-5.8 7.9-10.9C23.5 5.7 18.3.5 12 .5z"/></svg>
);

export default function Header() {
  const wxLogged = useWechatStatus();
  const wxOn = wxLogged === true;
  const [qsOpen, setQsOpen] = useState(false);
  return (
    <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "6px 0 14px" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <div style={{ width: 34, height: 34, borderRadius: 9, background: "#1565c0", display: "flex", alignItems: "center", justifyContent: "center" }}><Telescope /></div>
        <div style={{ display: "flex", flexDirection: "column", justifyContent: "center" }}>
          <div style={{ display: "flex", alignItems: "baseline", gap: 8 }}>
            <span style={{ fontSize: 19, fontWeight: 700 }}>微信公众号采集器</span>
            <span style={{ fontSize: 12, color: "#8b949e" }}>v{process.env.NEXT_PUBLIC_APP_VERSION || ""}</span>
          </div>
          <div style={{ fontSize: 12, color: "#8b949e" }}>基于 微信 Windows 版 4.1.12.55</div>
        </div>
        <Tooltip title="如果是第一次使用，建议先运行快速开始（会自动校准点位/滚动/公众号）">
          <button onClick={() => setQsOpen(true)}
            style={{ height: 34, padding: "0 12px", borderRadius: 9, background: "#fff", border: "1px solid #d0d7de", color: "#57606a", display: "flex", alignItems: "center", gap: 6, cursor: "pointer", fontSize: 13, fontWeight: 600 }}>
            <svg width="16" height="16" viewBox="0 0 24 24" fill="#f5a623" xmlns="http://www.w3.org/2000/svg"><path d="M13 2 3 14h7l-1 8 10-12h-7l1-8z" /></svg>
            快速开始
          </button>
        </Tooltip>
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <Tooltip title="刷新">
          <button onClick={() => window.location.reload()}
            style={{ width: 34, height: 34, borderRadius: 9, background: "#fff", border: "1px solid #d0d7de", color: "#57606a", display: "flex", alignItems: "center", justifyContent: "center", cursor: "pointer", padding: 0 }}>
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeMiterlimit="10"><polyline points="23 4 23 10 17 10" /><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10" /></svg>
          </button>
        </Tooltip>
        <Tooltip title={wxLogged === null ? "检测中..." : (wxOn ? "微信: 已登录" : "微信未登录或者微信窗口未唤醒")}
          open={wxLogged === false}  >
          <span onClick={() => { if (wxLogged === false) fetch("http://127.0.0.1:8000/api/settings/launch-wechat", { method: "POST" }).catch(() => {}); }}
            style={{ width: 34, height: 34, borderRadius: 9, background: "#fff", border: "1px solid #d0d7de", color: wxOn ? "#07c160" : "#a6adb4", display: "flex", alignItems: "center", justifyContent: "center", cursor: wxLogged === false ? "pointer" : "default", transition: ".2s" }}>
            <WechatIcon color={wxOn ? "#07c160" : "#a6adb4"} />
          </span>
        </Tooltip>
        <Tooltip title="GitHub 仓库">
          <a href="https://github.com/hong2301/wechat-article-collector" target="_blank" rel="noreferrer"
             style={{ width: 34, height: 34, borderRadius: 9, background: "#fff", border: "1px solid #d0d7de", color: "#57606a", display: "flex", alignItems: "center", justifyContent: "center" }}><GithubIcon /></a>
        </Tooltip>
      </div>
      <QuickStartDialog open={qsOpen} onClose={() => setQsOpen(false)} />
    </div>
  );
}

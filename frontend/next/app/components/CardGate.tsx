"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import { API_BASE } from "../lib/api";
import { Button, Input, message, Spin, Typography } from "antd";

type LicStatus = {
  ok: boolean;
  expire?: string;
  permanent?: boolean;
  warn?: boolean;
  guest?: boolean;
  msg?: string;
  loading?: boolean;
};

/* 启动门: 无有效授权 -> 独立卡密激活页; 已授权(含客人钥匙) -> 主界面 + 底部期限
  布局与主界面完全独立(全屏居中卡片, 无 Header/工作台) */
export default function CardGate({ children }: { children: React.ReactNode }) {
  const [state, setState] = useState<LicStatus>({ ok: false, loading: true });
  const [card, setCard] = useState("");
  const [busy, setBusy] = useState(false);
  const [dragOver, setDragOver] = useState(false);
  const checked = useRef(false);

  const fetchStatus = useCallback(async () => {
    try {
      const r = await (await fetch(API_BASE + "/api/license/status")).json();
      setState({ ...r, loading: false });
      return r;
    } catch {
      setState({ ok: false, loading: false, msg: "无法连接后端" });
      return { ok: false };
    }
  }, []);

  useEffect(() => {
    if (checked.current) return;
    checked.current = true;
    fetchStatus();
  }, [fetchStatus]);

  async function doVerify(cardValue?: string) {
    const val = (cardValue ?? card).trim();
    if (!val) { message.warning("请输入或拖入卡密"); return; }
    setBusy(true);
    try {
      const r = await (await fetch(API_BASE + "/api/license/verify", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ card: val }),
      })).json();
      if (r.ok) {
        message.success("激活成功");
        await fetchStatus();
      } else {
        message.error(r.msg || "卡密无效");
      }
    } catch { message.error("无法连接后端"); }
    finally { setBusy(false); }
  }

  // 拖入卡密文件
  async function onDrop(e: React.DragEvent) {
    e.preventDefault(); setDragOver(false);
    const f = e.dataTransfer.files?.[0];
    if (!f) return;
    try {
      const text = (await f.text()).trim();
      if (text) { setCard(text); message.info("已读取卡密文件"); }
    } catch { message.error("读取文件失败"); }
  }

  // 已授权(含客人钥匙): 主界面 + 底部期限(右下角灰色小字; 无期限不显示)
  if (state.ok) {
    return (
      <>
        {children}
        {!state.permanent && state.expire && (
          <div style={{ position: "fixed", left: 22, bottom: 8, color: "#9aa0a6",
                        fontSize: 12, zIndex: 2000, userSelect: "none" }}>
            授权至 {String(state.expire).slice(0, 10)}
            {state.warn && <span style={{ color: "#d4a106", marginLeft: 6 }}>即将到期，请更换新卡密</span>}
          </div>
        )}
      </>
    );
  }

  // 未授权: 独立卡密页
  return (
    <div style={{ height: "100vh", display: "flex", alignItems: "center", justifyContent: "center",
                  background: "linear-gradient(160deg,#eef3fb 0%,#f5f6f8 100%)" }}>
      <div style={{ width: 380, textAlign: "center" }}>
        {/* Logo + 标题(一行) */}
        <div style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: 14, marginBottom: 26 }}>
          <img src="icon.png" alt="" width={56} height={56}
               style={{ borderRadius: 12, boxShadow: "0 6px 18px rgba(21,101,192,.25)", background: "#fff", padding: 6 }}
               onError={(e) => { (e.target as HTMLImageElement).style.display = "none"; }} />
          <Typography.Title level={3} style={{ margin: 0 }}>微信公众号采集器</Typography.Title>
        </div>
        {/* 卡密输入(可拖入文件) */}
        <div style={{ display: "flex", gap: 8, alignItems: "stretch" }}
             onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
             onDragLeave={() => setDragOver(false)}
             onDrop={onDrop}>
          <Input size="large" placeholder="粘贴卡密，或将卡密文件拖入此处"
                 value={card} onChange={(e) => setCard(e.target.value)}
                 onPressEnter={() => doVerify()}
                 style={{ borderRadius: 10, flex: 1, borderColor: dragOver ? "#1565c0" : undefined,
                          boxShadow: dragOver ? "0 0 0 3px rgba(21,101,192,.15)" : undefined }} />
          <Button type="primary" size="large" loading={busy} onClick={() => doVerify()}
                  style={{ borderRadius: 10, background: "#1565c0" }}>确定</Button>
        </div>
        <div style={{ color: "#a6adb5", fontSize: 12, marginTop: 10 }}>
          支持拖入 txt / 卡密文件，内容即为卡密
        </div>
      </div>
      {/* 启动检测中/验签中的全屏 loading(打包版含客人钥匙时立即由此进入首页) */}
      {state.loading && (
        <div style={{ position: "fixed", inset: 0, background: "rgba(245,246,248,.85)",
                      display: "flex", alignItems: "center", justifyContent: "center", zIndex: 3000 }}>
          <Spin size="large" tip="正在验证授权..." style={{ color: "#1565c0" }} />
        </div>
      )}
    </div>
  );
}
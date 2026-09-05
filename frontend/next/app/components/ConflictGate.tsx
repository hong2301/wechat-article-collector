"use client";
// 冲突软件统一拦截: 采集/一键设置/单点自动设置/快速开始 开始前检测本机冲突软件,
// 有冲突时弹出统一弹窗(可 关闭并继续 / 忽略并继续 / 取消), 无冲突直接放行
import React, { createContext, useCallback, useContext, useRef, useState } from "react";
import { Modal, Table, Button, Space, message, Alert } from "antd";
import { API_BASE } from "../lib/api";

export interface ConflictItem {
  id: number;
  name: string;
  window_titles: string[];
  process_names: string[];
  matched_windows: [number, string, number][];
  matched_pids: number[];
}

export interface ConflictGateCtx {
  /** 执行动作前先检测冲突: 无冲突直接执行; 有冲突弹窗, 用户处理后执行/取消 */
  runWithGuard: <T>(action: () => Promise<T> | T, label?: string) => Promise<T | undefined>;
}

const GateCtx = createContext<ConflictGateCtx>({ runWithGuard: async (a: any) => a() });

export const useConflictGate = () => useContext(GateCtx);

async function checkConflicts(): Promise<{ ok: boolean; conflicts: ConflictItem[] }> {
  const r = await fetch(`${API_BASE}/api/conflicts/check`);
  if (!r.ok) throw new Error("conflict check failed");
  return r.json();
}

async function killConflicts(names: string[]) {
  const r = await fetch(`${API_BASE}/api/conflicts/kill`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ names }),
  });
  if (!r.ok) throw new Error("conflict kill failed");
  return r.json();
}

export function ConflictGateProvider({ children }: { children: React.ReactNode }) {
  const [open, setOpen] = useState(false);
  const [conflicts, setConflicts] = useState<ConflictItem[]>([]);
  const [label, setLabel] = useState("");
  const [busy, setBusy] = useState(false);
  const [detail, setDetail] = useState(false);
  const pendingRef = useRef<((v?: any) => void) | null>(null);
  const actionRef = useRef<(() => any) | null>(null);

  const runWithGuard = useCallback(async <T,>(action: () => Promise<T> | T, lb = "") => {
    try {
      const r = await checkConflicts();
      if (r.ok) return await action();
      actionRef.current = action;
      setConflicts(r.conflicts);
      setLabel(lb);
      setOpen(true);
      return await new Promise<T | undefined>((resolve) => {
        pendingRef.current = resolve as (v?: any) => void;
      });
    } catch {
      return await action();       // 检测接口异常不阻塞流程
    }
  }, []);

  const release = async () => {
    const action = actionRef.current;
    actionRef.current = null;
    pendingRef.current = null;
    return action ? await action() : undefined;
  };

  const onBtn = async (mode: "kill" | "ignore" | "cancel") => {
    if (mode === "cancel") { setOpen(false); pendingRef.current?.(undefined); return; }
    if (mode === "ignore") {
      setOpen(false); message.info("已忽略冲突，继续执行");
      pendingRef.current?.(await release()); return;
    }
    setBusy(true);
    try {
      await killConflicts(conflicts.map((c) => c.name));
      const r = await checkConflicts();
      if (r.ok) {
        setOpen(false); message.success("冲突软件已关闭");
        pendingRef.current?.(await release()); return;
      }
      setConflicts(r.conflicts);
      message.warning("仍有冲突软件未关闭");
      setBusy(false);
    } catch (e) {
      message.error("关闭失败: " + ((e as Error)?.message || e));
      setBusy(false);
    }
  };

  const cols = [
    { title: "软件", dataIndex: "name", width: 120 },
    { title: "窗口", dataIndex: "windows", render: (_: any, r: ConflictItem) =>
        (r.matched_windows || []).map((w) => w[1]).join("、") || "—" },
    { title: "进程PID", dataIndex: "pids", render: (_: any, r: ConflictItem) =>
        (r.matched_pids || []).join(", ") || "—" },
  ];

  return (
    <GateCtx.Provider value={{ runWithGuard }}>
      {children}
      <Modal
        open={open} title={`冲突软件检测${label ? ` · ${label}` : ""}`}
        footer={
          <Space>
            <Button onClick={() => onBtn("cancel")}>取消</Button>
            <Button loading={busy} onClick={() => onBtn("ignore")}>忽略并继续</Button>
            <Button type="primary" danger loading={busy} onClick={() => onBtn("kill")}>
              关闭并继续
            </Button>
          </Space>
        }
        width={620}
        onCancel={() => onBtn("cancel")}
      >
        <Alert type="warning" showIcon style={{ marginBottom: 12 }}
          message={`检测到 ${conflicts.length} 个可能干扰采集的软件在运行（会抢快捷键/弹截图/遮挡屏幕）`}
          description="建议关闭后再继续。关闭仅作用于列表中的冲突软件进程。"
        />
        <Table<ConflictItem> rowKey="id" size="small" columns={cols} dataSource={conflicts}
          pagination={false} scroll={{ y: 220 }}
        />
        <p style={{ margin: "10px 0 0", color: "#888", fontSize: 12 }}>
          检测方式：窗口标题 / 进程名（conflict_apps 表，可自行维护）
        </p>
      </Modal>
    </GateCtx.Provider>
  );
}
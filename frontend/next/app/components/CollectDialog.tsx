"use client";
/* 通用采集/更新弹窗组件: 确认设置 + 进行中(设置复述/统计卡片/日志面板) + 停止/关闭
   三个入口复用: page.tsx(公众号采集) / articles(page 更新) / comments(评论采集)
   差异(接口/队列/统计解析)由各页面负责, 本组件只做展示层 */
import { useEffect, useRef } from "react";
import { Modal, Button, Typography } from "antd";

export interface KV {
  label: string;
  value: string;
}

interface CollectDialogProps {
  open: boolean;
  title: string;                      // 标题(页面算好, 含确认/进行中/队列进度)
  started: boolean;                   // 是否进行中
  stopped: boolean;                   // 主动停止/已完成(显示"关闭")
  confirmFields: KV[];                // 确认阶段字段列表
  startedFields?: KV[];               // 进行中左卡片(设置复述)
  stats?: KV[];                       // 进行中统计卡片(开始时间/计数/速度)
  logs: string[];
  onCancel: () => void;               // 进行中=停止策略; 确认阶段=取消/关闭
  onConfirm?: () => void;
  onCloseFinish: () => void;          // 完成/停止后的"关闭"
}

const LEVEL_COLOR: Record<string, string | undefined> = {
  INFO: undefined,
  DEBUG: "#8a8a8a",
  WARNING: "#ffc53d",
  ERROR: "#ff4d4f",
};
const LEGACY_COLOR: Record<string, string> = {
  step: "#ffa940", ok: "#73d13d", fail: "#ff4d4f", warn: "#ffc53d",
};

function renderLog(l: string): { text: string; color?: string } {
  const mm = l.match(/^\[(INFO|WARNING|ERROR|DEBUG)\]\s?([\s\S]*)/);
  const mAsync = mm ? null : l.match(/^\[async:([^\]]+)\]\s?([\s\S]*)/);
  const m = mAsync || l.match(/^\[(step|ok|fail|warn)\]\s?([\s\S]*)/);
  let text = l;
  let color: string | undefined;
  if (mm) { color = LEVEL_COLOR[mm[1]]; text = mm[2]; }
  else if (mAsync) { color = "#36cfc9"; text = `[${mAsync[1]}] ${mAsync[2]}`; }
  else if (m) { color = LEGACY_COLOR[m[1]]; text = m[2]; }
  else if (/^✅/.test(l)) color = "#73d13d";
  else if (/^❌/.test(l)) color = "#ff4d4f";
  else if (/^⏹/.test(l)) color = "#69b1d6";
  return { text, color };
}

function KVList({ items, title }: { items: KV[]; title?: string }) {
  return (
    <div style={{ flex: 1, background: "#fff", border: "1px solid #eee", borderRadius: 8, padding: "4px 0" }}>
      {title && (
        <div style={{ padding: "7px 14px", fontSize: 13, fontWeight: 600, color: "#333", borderBottom: "1px solid #f0f0f0", flexShrink: 0 }}>
          {title}
        </div>
      )}
      {items.map((row) => (
        <div key={row.label} style={{ display: "flex", alignItems: "center", padding: "7px 14px", fontSize: 13 }}>
          <span style={{ width: 110, color: "#888", whiteSpace: "nowrap", flexShrink: 0 }}>{row.label}</span>
          <span style={{ color: "#333", fontWeight: 500 }}>{row.value}</span>
        </div>
      ))}
    </div>
  );
}

export default function CollectDialog(props: CollectDialogProps) {
  const { open, title, started, stopped, confirmFields, startedFields, stats, logs } = props;
  const logRef = useRef<HTMLDivElement>(null);
  // 自动滚到底
  useEffect(() => {
    if (logRef.current) {
      logRef.current.scrollTop = logRef.current.scrollHeight;
    }
  }, [logs]);

  return (
    <Modal destroyOnHidden mask={{ closable: false }}
      open={open}
      title={title}
      onCancel={props.onCancel}
      footer={started ? (
        stopped ? (
          <Button type="primary" onClick={props.onCloseFinish}>关闭</Button>
        ) : (
          <Button danger onClick={props.onCancel}>按 ESC 停止</Button>
        )
      ) : (
        <>
          <Button onClick={props.onCancel}>取消</Button>
          <Button type="primary" onClick={props.onConfirm}>确认</Button>
        </>
      )}
      width={started ? 880 : 520}
    >
      {started ? (
        <>
          {(startedFields && startedFields.length > 0) || (stats && stats.length > 0) ? (
            <div style={{ display: "flex", gap: 12 }}>
              {startedFields && startedFields.length > 0 && <KVList items={startedFields} title="采集设置" />}
              {stats && stats.length > 0 && <KVList items={stats} title="采集情况" />}
            </div>
          ) : null}
          <div style={{ background: "#fafafa", border: "1px solid #eee", borderRadius: 8, padding: "10px 12px", marginTop: 12 }}>
            <Typography.Text strong style={{ fontSize: 13 }}>日志</Typography.Text>
            <div ref={logRef} style={{
              marginTop: 8, height: 220, overflow: "auto",
              background: "#1e1e1e", borderRadius: 6, padding: 8,
              fontFamily: "Consolas, monospace", fontSize: 12, color: "#d4d4d4", whiteSpace: "pre-wrap",
            }}>
              {logs.length === 0 ? (
                <span style={{ color: "#888" }}>(暂无日志)</span>
              ) : (
                logs.slice(-2000).map((l, i) => {
                  const r = renderLog(l);
                  return <div key={i} style={r.color ? { color: r.color } : undefined}>{r.text}</div>;
                })
              )}
            </div>
          </div>
        </>
      ) : (
        <div style={{ background: "#fff", border: "1px solid #eee", borderRadius: 8, padding: "4px 0" }}>
          {confirmFields.map((row) => (
            <div key={row.label} style={{ display: "flex", alignItems: "center", padding: "7px 14px", fontSize: 13 }}>
              <span style={{ width: 110, color: "#888", whiteSpace: "nowrap", flexShrink: 0 }}>{row.label}</span>
              <span style={{ color: "#333", fontWeight: 500 }}>{row.value}</span>
            </div>
          ))}
        </div>
      )}
    </Modal>
  );
}
"use client";
// 快速开始流程弹窗: 检查点位(缺则一键设置) -> 滚动自动获取 -> 检查公众号(无则添加测试号)
//   -> 采集今天文章(第二行4开关全关)直到结束; 全程彩色日志 + ESC可退出
import { useEffect, useRef, useState } from "react";
import { API_BASE } from "../lib/api";
import { Modal, Button } from "antd";
import { hideTaskbar, showTaskbar } from "./taskbar";

interface QLog { text: string; color: string }

async function readSSE(resp: Response, onFrame: (d: any) => void): Promise<void> {
  if (!resp.ok || !resp.body) { throw new Error(`接口失败(${resp.status})`); }
  const reader = resp.body.getReader();
  const dec = new TextDecoder();
  let buf = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    let i2;
    while ((i2 = buf.indexOf("\n\n")) !== -1) {
      const block = buf.slice(0, i2); buf = buf.slice(i2 + 2);
      if (!block.startsWith("data: ")) continue;
      try { onFrame(JSON.parse(block.slice(6))); } catch { /* 忽略坏帧 */ }
    }
  }
}

export default function QuickStartDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [logs, setLogs] = useState<QLog[]>([]);
  const [running, setRunning] = useState(false);
  const [finished, setFinished] = useState(false);
  const [failed, setFailed] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  const logRef = useRef<HTMLDivElement>(null);
  const runningRef = useRef(false);
  runningRef.current = running;

  const add = (text: string, color = "#444") => setLogs((p) => [...p, { text, color }]);
  const emit = (m: string) => {
    if (m.startsWith("[ok]")) add(m, "#3fb950");
    else if (m.startsWith("[fail]")) add(m, "#f85149");
    else if (m.startsWith("[warn]")) add(m, "#d29922");
    else if (m.startsWith("[step]")) add(m, "#58a6ff");
    else if (m.startsWith("[done]")) add(m, "#ffffff");
    else if (m.includes("禁用鼠标和键盘")) add(m, "#d29922");
    else add(m, "#c9d1d9");
  };

  // 日志区自动滚底
  useEffect(() => {
    if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight;
  }, [logs]);

  async function start() {
    setLogs([]);
    setRunning(true);
    setFinished(false);
    setFailed(false);
    hideTaskbar();
    abortRef.current = new AbortController();
    const sig = abortRef.current.signal;
    try {
      // ---- 1 点位检查: 有缺失 -> 一键设置(锁+流式) ----
      add("[step] 检查点位设置…", "#58a6ff");
      const pd = await (await fetch(API_BASE + "/api/points", { signal: sig })).json();
      const pl = Array.isArray(pd) ? pd : (pd.items || []);
      const missing = pl.filter((p: any) => {
        const x = String(p.x ?? "").trim(), y = String(p.y ?? "").trim();
        return !x || !y || isNaN(Number(x)) || isNaN(Number(y));
      });
      if (missing.length > 0) {
        add(`[warn] 点位不完整(${missing.length}个), 执行一键设置(输入锁定, 请勿操作)…`, "#d29922");
        await fetch(API_BASE + "/api/auto-setup/lock", { method: "POST" }).catch(() => {});
        const resp = await fetch(API_BASE + "/api/auto-setup/run-all", { method: "POST", signal: sig });
        await readSSE(resp, (d) => { if (d.msg) emit(d.msg); });
        await fetch(API_BASE + "/api/auto-setup/unlock", { method: "POST" }).catch(() => {});
        add("[ok] 一键设置完成", "#3fb950");
      } else {
        add(`[ok] 点位已全部设置(${pl.length}个)`, "#3fb950");
      }

      // ---- 2 滚动设置: 按点位自动获取 ----
      add("[step] 按点位自动获取滚动距离…", "#58a6ff");
      for (const sid of [3, 5]) {
        const d = await (await fetch(`${API_BASE}/api/auto-setup/scroll/${sid}`, { method: "POST", signal: sig })).json();
        if (d.ok) add(`[ok] ${d.name}: 距离=${d.distance} (由${d.from} y差计算)`, "#3fb950");
        else add(`[fail] ${(d.name || `#${sid}`)}: ${d.error}`, "#f85149");
      }

      // ---- 3 公众号检查: 无则添加测试公众号 ----
      add("[step] 检查公众号列表…", "#58a6ff");
      const ad = await (await fetch(API_BASE + "/api/accounts?page=1&page_size=1", { signal: sig })).json();
      // 兼容: page=0 返回纯数组, page>=1 返回 {total,items}
      const accList = Array.isArray(ad) ? ad : (ad.items || []);
      const hasAcc = Array.isArray(ad) ? ad.length > 0 : (ad.total || 0) > 0;
      let biz = "", nme = "";
      if (hasAcc && accList.length > 0) {
        biz = accList[0].biz; nme = accList[0].name;
        add(`[ok] 已有公众号, 本次采集「${nme}」`, "#3fb950");
      } else {
        add(`[warn] 公众号列表为空, 添加测试公众号 MzA4OTQ5NTk2Mw==`, "#d29922");
        const cr = await fetch(API_BASE + "/api/accounts", {
          method: "POST", signal: sig,
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ name: "测试公众号", biz: "MzA4OTQ5NTk2Mw==", status: "pending" }),
        });
        if (!cr.ok) throw new Error("添加测试公众号失败");
        biz = "MzA4OTQ5NTk2Mw=="; nme = "测试公众号";
        add("[ok] 已添加测试公众号", "#3fb950");
      }

      // ---- 4 采集: 时间=今天, 第二行4开关(4指标/阅读数/保存Html/评论采集)全关 ----
      add("[step] 开始采集「" + nme + "」(今天, 4指标/阅读数/保存Html/评论采集均关闭)…", "#58a6ff");
      const today = new Date().toLocaleDateString("sv-SE");   // 本地日期 yyyy-mm-dd(非UTC)
      const payload = {
        collect_type: 1, name: nme, biz,
        link: `https://mp.weixin.qq.com/mp/profile_ext?action=home&__biz=${encodeURIComponent(biz || "")}`,
        date_start: today, date_end: today,
        capture_4metrics: false, capture_read: false, save_html: false, save_dir: "",
        max_comments: 0, max_level1: 0, max_level2: 0,
      };
      const cResp = await fetch(API_BASE + "/api/collect/start", {
        method: "POST", signal: sig,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      let collectOk = true;
      await readSSE(cResp, (d) => {
        if (d.type === "log" && d.msg) emit(d.msg);
        else if (d.type === "task" && d.done !== undefined) add(`进度: 已完成文章 ${d.done} 篇`, "#c9d1d9");
        else if (d.type === "done") {
          collectOk = d.ok === true;
          add(d.ok ? "✅ 采集流程结束" : `❌ 采集失败: ${d.reason || ""}`, d.ok ? "#3fb950" : "#f85149");
        }
      });
      if (!collectOk) {
        add("[fail] 快速开始流程失败: 采集未成功", "#f85149");
        setFailed(true);
        window.dispatchEvent(new Event("fast-refresh-settings"));
        return;   // 不进完成路径
      }
      add("[done] 快速开始流程全部完成", "#ffffff");
      setFinished(true);
      window.dispatchEvent(new Event("fast-refresh-settings"));   // 通知各页刷新点位/滚动完整性状态
    } catch (e: unknown) {
      if ((e as Error)?.name !== "AbortError") {
        add(`❌ 快速开始异常: ${(e as Error)?.message || e}`, "#f85149");
        setFailed(true);
      }
    } finally {
      fetch(API_BASE + "/api/auto-setup/unlock", { method: "POST" }).catch(() => {});
      showTaskbar();
      setRunning(false);
      window.dispatchEvent(new Event("fast-refresh-settings"));   // 结束/退出也刷新(可能部分写入)
    }
  }

  // ESC: 停止当前步骤(中止流 + 通知后端停止)
  useEffect(() => {
    const esc = (ev: KeyboardEvent) => {
      if (ev.key === "Escape" && open && runningRef.current) {
        add("[warn] 已请求退出: 停止当前步骤…", "#d29922");
        abortRef.current?.abort();
        fetch(API_BASE + "/api/collect/stop", { method: "POST" }).catch(() => {});
        fetch(API_BASE + "/api/auto-setup/unlock", { method: "POST" }).catch(() => {});
        showTaskbar();
        setRunning(false);
      }
    };
    window.addEventListener("keydown", esc);
    return () => window.removeEventListener("keydown", esc);
  }, [open]);

  useEffect(() => {
    if (open && !runningRef.current) { start(); }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  return (
    <Modal mask={{ closable: false }} open={open} onCancel={onClose} footer={null} width={780} title="快速开始" destroyOnHidden>
      <div style={{ display: "flex", flexDirection: "column", gap: 8, height: 420 }}>
        {running && (
          <div style={{ padding: "8px 10px", borderRadius: 8, background: "#fff8e1", border: "1px solid #ffe082", fontSize: 13, color: "#b26a00" }}>
            正在执行快速开始流程，请等待结束。如果是第一次使用该程序，快速开始流程很有必要，可以一键帮你校准参数。
            <div style={{ color: "#f5222d", marginTop: 4, fontSize: 12 }}>期间鼠标键盘不可操作，可按 ESC 结束</div>
          </div>
        )}
        {finished && (
          <div style={{ padding: "10px 12px", borderRadius: 8, background: "#f0fff4", border: "1px solid #95e1b8", fontSize: 14, color: "#16a34a", fontWeight: 600, display: "flex", alignItems: "center", gap: 8 }}>
            ✅ 快速开始流程已全部完成：点位校准、滚动距离获取、采集执行均已就绪。
          </div>
        )}
        {failed && (
          <div style={{ padding: "10px 12px", borderRadius: 8, background: "#fff1f0", border: "1px solid #ffa39e", fontSize: 14, color: "#cf1322", fontWeight: 600, display: "flex", alignItems: "center", gap: 8 }}>
            ❌ 快速开始流程失败，可关闭弹窗。请到点位设置和滚动设置人工设置参数。
          </div>
        )}
        <div ref={logRef} style={{ flex: 1, minHeight: 0, overflow: "auto", background: "#0d1117", borderRadius: 8, padding: "8px 10px", fontFamily: "Consolas, monospace", fontSize: 12 }}>
          {logs.length === 0 && <div style={{ color: "#8b949e" }}>等待开始…</div>}
          {logs.map((m, i) => (
            <div key={i} style={{ color: m.color, whiteSpace: "pre-wrap", wordBreak: "break-all" }}>{m.text}</div>
          ))}
        </div>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", minHeight: 32 }}>
          <div style={{ fontSize: 12, color: "#8b949e" }}>
            {running ? "流程执行中…" : (finished ? "🎉 全部完成" : (logs.length > 0 ? "流程已停止" : ""))}
          </div>
          {(finished || failed) && (
            <Button type="primary" style={{ minWidth: 96 }} onClick={onClose}>{finished ? "完成" : "关闭"}</Button>
          )}
        </div>
      </div>
    </Modal>
  );
}
"use client";

import { useEffect, useRef, useState, useMemo } from "react";
import { useRouter } from "next/navigation";
import { Table, Button, Typography, Space, Tag, message, Modal, Empty, Tooltip, Spin, DatePicker, InputNumber, Input, Checkbox, Progress, Switch, Select } from "antd";
import { ArrowLeftOutlined, ReloadOutlined, PlusOutlined, ImportOutlined, DeleteOutlined, SearchOutlined, ClearOutlined, FileExcelOutlined, ExclamationCircleOutlined, QuestionCircleOutlined } from "@ant-design/icons";
import * as XLSX from "xlsx";
import PaginationBar, { calcPageSize } from "../components/PaginationBar";
import { hideTaskbar, showTaskbar } from "../components/taskbar";
import { useSettingsIssues } from "../components/useSettingsIssues";
import { useWechatStatus } from "../components/useWechatStatus";
import dayjs from "dayjs";

const API = "http://127.0.0.1:8000/api/accounts";

interface CommentRow {
  id: number;
  comment_biz: string;
  parent_comment_biz: string;
  author: string;
  content: string;
  time: string;
  likes: string;
  ip: string;
  is_author: number;
  is_top: number;
  is_author_reply: number;
  is_author_like: number;
  is_first: number;
  level: number;
}

// 合并「起~止」为一体范围输入框
function NumRange({ value, onChange }: {
  value: [number | null, number | null];
  onChange: (v: [number | null, number | null]) => void;
}) {
  return (
    <div style={{ display: "flex", alignItems: "center", border: "1px solid #d9d9d9", borderRadius: 6, backgroundColor: "#fff", height: 22, padding: "0 2px" }}>
      <InputNumber size="small" variant="borderless" controls={false} min={0} placeholder="起"
        value={value[0] === null ? undefined : value[0]}
        onChange={(v) => onChange([v ?? null, value[1]])} style={{ width: 40 }} />
      <span style={{ color: "#bfc7cf", fontSize: 12, margin: "0 1px" }}>~</span>
      <InputNumber size="small" variant="borderless" controls={false} min={0} placeholder="止"
        value={value[1] === null ? undefined : value[1]}
        onChange={(v) => onChange([value[0], v ?? null])} style={{ width: 40 }} />
    </div>
  );
}

export default function CommentsPage() {
  const router = useRouter();
  const [artBiz, setArtBiz] = useState("");
  const [biz, setBiz] = useState("");
  const [title, setTitle] = useState("");
  const [name, setName] = useState("");
  const [comments, setComments] = useState<CommentRow[]>([]);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [loadErr, setLoadErr] = useState(false);
  const retryRef = useRef<ReturnType<typeof setTimeout>>(undefined);
  const retryCountRef = useRef(0);   // 连不上后端时的自动重试计数(上限5次)
  const tableWrapRef = useRef<HTMLDivElement>(null);
  // 表格可视高度(供 scroll.y, 让横向滚动条常驻表体底部)
  const [tableY, setTableY] = useState(0);
  useEffect(() => {
    const measure = () => {
      if (tableWrapRef.current) setTableY(Math.max(100, tableWrapRef.current.clientHeight - 56));
    };
    measure();
    window.addEventListener("resize", measure);
    const t = setInterval(measure, 800);   // 数据/布局变化兜底
    return () => { window.removeEventListener("resize", measure); clearInterval(t); };
  }, []);
  const fileRef = useRef<HTMLInputElement>(null);

  const [selectedKeys, setSelectedKeys] = useState<React.Key[]>([]);
  const [importing, setImporting] = useState(false);
  const [importingPct, setImportingPct] = useState(0);
  const [dragOver, setDragOver] = useState(false);
  const [kw, setKw] = useState("");
  const [dateRange, setDateRange] = useState<[any, any] | null>(null);
  const [likesRange, setLikesRange] = useState<[number | null, number | null]>([null, null]);
  const [ipFilter, setIpFilter] = useState<string[]>(["__all__"]);   // IP多选(含'全部')
  const [levelFilter, setLevelFilter] = useState<string[]>(["__all__"]); // 层级多选(含'全部')
  // 评论采集设置(独立存 commentConfig)
  const [maxComments, setMaxComments] = useState<number | null>(null);
  const [maxLevel1, setMaxLevel1] = useState<number | null>(null);
  const [maxLevel2, setMaxLevel2] = useState<number | null>(0);
  const [ccLoaded, setCcLoaded] = useState(false);
  useEffect(() => {
    try {
      const d = JSON.parse(localStorage.getItem("commentConfig") || "{}");
            if ("max_comments" in d) setMaxComments(d.max_comments);
      if ("max_level1" in d) setMaxLevel1(d.max_level1);
      if ("max_level2" in d) setMaxLevel2(d.max_level2);
      if (d.date_start && d.date_end) setDateRange([dayjs(d.date_start), dayjs(d.date_end)]);
    } catch { /* 忽略 */ }
    setCcLoaded(true);
  }, []);
  useEffect(() => {
    if (!ccLoaded) return;
    try {
      localStorage.setItem("commentConfig", JSON.stringify({
          max_comments: maxComments, max_level1: maxLevel1, max_level2: maxLevel2,
        date_start: dateRange ? dateRange[0].format("YYYY-MM-DD") : "",
        date_end: dateRange ? dateRange[1].format("YYYY-MM-DD") : "",
      }));
    } catch { /* 忽略 */ }
  }, [ccLoaded, maxComments, maxLevel1, maxLevel2, dateRange]);
  // 评论采集弹窗
  const [ccOpen, setCcOpen] = useState(false);
  const si = useSettingsIssues();
  const wxLogged = useWechatStatus();
  const [ccStarted, setCcStarted] = useState(false);
  const [ccLogs, setCcLogs] = useState<string[]>([]);
  const ccAbortRef = useRef<AbortController | null>(null);
  const [ccStopped, setCcStopped] = useState(false);   // 已停止(按钮变关闭)
  const ccLogRef = useRef<HTMLDivElement>(null);
  const [ccCount, setCcCount] = useState(0);       // 已采评论数
  const [ccCount1, setCcCount1] = useState(0);     // 一级评论数
  const [ccCount2, setCcCount2] = useState(0);     // 二级评论数
  const [ccStartTs, setCcStartTs] = useState(0);
  const [ccStartTime, setCcStartTime] = useState("");
  const [ccSpeed, setCcSpeed] = useState(0);       // 条/秒
  // 日志自动滚动
  useEffect(() => {
    if (ccLogRef.current) ccLogRef.current.scrollTop = ccLogRef.current.scrollHeight;
  }, [ccLogs]);
  // 采集速度(条/秒)
  useEffect(() => {
    if (ccStartTs > 0) {
      const sec = (Date.now() - ccStartTs) / 1000;
      setCcSpeed(sec > 0 ? ccCount / sec : 0);
    }
  }, [ccCount, ccStartTs]);

  useEffect(() => {
    const q = new URLSearchParams(window.location.search);
    const a = q.get("art_biz") || "";
    setArtBiz(a);
    setBiz(q.get("biz") || "");
    setTitle(q.get("title") || "");
    setName(q.get("name") || "");
    if (a) load(a);
  }, []);

  async function load(a: string) {
    setLoading(true);
    clearTimeout(retryRef.current);
    try {
      const ctrl = new AbortController();
      const to = setTimeout(() => ctrl.abort(), 6000);
      const qs = new URLSearchParams({ art_biz: a, page: String(page), page_size: String(pageSize) });
      if (dateRange) { qs.set("date_start", dateRange[0].format("YYYY-MM-DD")); qs.set("date_end", dateRange[1].format("YYYY-MM-DD")); }
      if (kw.trim()) qs.set("kw", kw.trim());
      if (likesRange[0] != null) qs.set("min_likes", String(likesRange[0]));
      if (likesRange[1] != null) qs.set("max_likes", String(likesRange[1]));
      if (ipFilter.length && !ipFilter.includes("__all__")) qs.set("ips", ipFilter.join(","));
      if (levelFilter.length && !levelFilter.includes("__all__")) qs.set("levels", levelFilter.join(","));
      const r = await fetch(`${API}/comments?${qs.toString()}`, { signal: ctrl.signal });
      const d = await r.json();
      clearTimeout(to);
      setComments(d.items ?? d.comments ?? []);
      setTotal(d.total ?? (d.comments ? d.comments.length : 0));
      setLoadErr(false);
      retryCountRef.current = 0;   // 连接成功, 重置重试计数
    } catch {
      retryCountRef.current += 1;
      if (retryCountRef.current <= 5) {
        message.error(`无法连接后端(8000), 正在自动重试(${retryCountRef.current}/5)`);
      } else {
        message.error("后端连接失败: 请确认后端已启动、8000端口未被占用, 再点右上角刷新");
      }
      setLoadErr(true);
      if (retryCountRef.current <= 5) retryRef.current = setTimeout(() => load(a), 3000);
    }
    finally { setLoading(false); }
  }
  function reload() { if (artBiz) load(artBiz); }
  // 分页变化重载 + 初始自动计算每页
  useEffect(() => { if (artBiz) load(artBiz); /* eslint-disable-next-line */ }, [page, pageSize]);
  useEffect(() => { setPageSize(calcPageSize()); }, []);
  // 评论采集弹窗显示=隐藏任务栏, 关闭=恢复
  useEffect(() => { if (ccOpen) hideTaskbar(); else showTaskbar(); /* eslint-disable-next-line */ }, [ccOpen]);
  // 筛选变化: 400ms 防抖后回第1页并重载(避免快速操作打爆后端)
  useEffect(() => {
    const t = setTimeout(() => {
      if (!artBiz) return;
      if (page !== 1) setPage(1); else load(artBiz);
    }, 400);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dateRange, kw, likesRange, ipFilter, levelFilter]);
  // 导出评论为 xlsx(文件名=文章标题+评论)
  async function exportExcel() {
    message.info("正在导出全部数据...");
    try {
      const qs = new URLSearchParams({ art_biz: String(artBiz || "") });
      if (dateRange) { qs.set("date_start", dateRange[0].format("YYYY-MM-DD")); qs.set("date_end", dateRange[1].format("YYYY-MM-DD")); }
      if (kw.trim()) qs.set("kw", kw.trim());
      if (likesRange[0] != null) qs.set("min_likes", String(likesRange[0]));
      if (likesRange[1] != null) qs.set("max_likes", String(likesRange[1]));
      if (ipFilter.length && !ipFilter.includes("__all__")) qs.set("ips", ipFilter.join(","));
      if (levelFilter.length && !levelFilter.includes("__all__")) qs.set("levels", levelFilter.join(","));
      const d = await (await fetch(`${API}/comments?${qs.toString()}`)).json();
      const all = Array.isArray(d.comments) ? d.comments : (d.items || []);
      if (all.length === 0) { message.info("没有可导出的数据"); return; }
    const rows = all.map((c: CommentRow) => ({
      "biz": c.comment_biz || "", "父级biz": c.parent_comment_biz || "",
      "作者": c.author || "", "内容": c.content || "", "时间": c.time || "",
      "点赞": c.likes ?? "", "IP": c.ip || "",
      "是否作者": c.is_author ? "是" : "", "置顶": c.is_top ? "是" : "",
      "作者回复": c.is_author_reply ? "是" : "", "作者点赞": c.is_author_like ? "是" : "",
      "首评": c.is_first ? "是" : "", "层级": c.level ?? "",
    }));
    const ws = XLSX.utils.json_to_sheet(rows);
    const wb = XLSX.utils.book_new();
    XLSX.utils.book_append_sheet(wb, ws, "评论");
    XLSX.writeFile(wb, `${title || "评论"}评论.xlsx`);
    } catch { message.error("导出失败"); }
  }
  // 停止评论采集: 通知后端中止(同ESC) + 断开SSE, 按钮变关闭
  function stopCc() {
    fetch("http://127.0.0.1:8000/api/collect/stop", { method: "POST" }).catch(() => {});
    ccAbortRef.current?.abort();
    setCcStopped(true);
  }
  // 关闭评论采集弹窗: 收起 + 刷新评论列表(采集到新评论)
  function closeCc() {
    setCcOpen(false);
    reload();
  }


  const hasFilter = useMemo(() => {
    return !!(dateRange || kw.trim() || likesRange[0] != null || likesRange[1] != null
      || (ipFilter.length > 0 && !ipFilter.includes("__all__")) || (levelFilter.length > 0 && !levelFilter.includes("__all__")));
  }, [dateRange, kw, likesRange]);

  function clearFilter() {
    setDateRange(null); setKw(""); setLikesRange([null, null]);
    setIpFilter(["__all__"]); setLevelFilter(["__all__"]);
  }

  // 打开评论采集弹窗
  function openCollect() {
    setCcStarted(false);
    setCcLogs([]);
    setCcCount(0); setCcCount1(0); setCcCount2(0);
    setCcOpen(true);
  }
  // 确认采集: 调后端 /api/collect/comments, SSE 接收日志
  function confirmCommentCollect() {
    if (!artBiz) { message.warning("无文章链接"); return; }
    setCcStopped(false);
    const link = `https://mp.weixin.qq.com/s/${artBiz}`;
    setCcStarted(true);
    setCcStartTs(Date.now());
    setCcStartTime(new Date().toLocaleString("zh-CN", { hour12: false }));
    setCcLogs([`开始采集评论「${title || artBiz}」`]);
    const controller = new AbortController();
    ccAbortRef.current = controller;
    const payload = {
      name: name || "", biz: biz || "", link,
 capture_4metrics: false, capture_read: false,
      save_html: false, save_dir: "",
      max_comments: maxComments, max_level1: maxLevel1, max_level2: maxLevel2,
    };
    (async () => {
      try {
        const resp = await fetch("http://127.0.0.1:8000/api/collect/comments", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload), signal: controller.signal,
        });
        if (!resp.ok || !resp.body) throw new Error("采集接口失败");
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
            try {
              const d = JSON.parse(block.slice(6));
              if (d.type === "log" && d.msg) {
                setCcLogs((p) => [...p, d.msg]);
                if (d.msg.includes("禁用鼠标和键盘")) message.warning("⚠️ 采集期间禁用鼠标和键盘，按 ESC 可停止");
                // 前端统计: 评论数/一级/二级 由日志标记统计
                if (d.msg.includes("评论已写入")) {
                  if (d.msg.includes("二级")) setCcCount2((c) => c + 1);
                  else if (d.msg.includes("一级")) setCcCount1((c) => c + 1);
                  setCcCount((c) => c + 1);
                }
              } else if (d.type === "done") {
                setCcLogs((p) => [...p, d.ok ? "✅ 评论采集完成" : `❌ 采集失败: ${d.reason || ""}`]);
              }
            } catch { /* 忽略坏帧 */ }
          }
        }
        setCcLogs((p) => [...p, "⏹ 连接已断开"]);
      } catch (e: unknown) {
        if ((e as Error)?.name !== "AbortError") setCcLogs((p) => [...p, `❌ 接口异常: ${(e as Error)?.message || e}`]);
      }
    })();
  }

  // 过滤
  // 筛选已后端化, shown 直接用接口数据
  const shown = useMemo(() => comments, [comments]);

  async function importFile(f: File) {
    setImporting(true); setImportingPct(0);
    const fd = new FormData();
    fd.append("file", f);
    let total = 0, added = 0, fail = 0;
    try {
      const r = await fetch(`${API}/comments/import?art_biz=${encodeURIComponent(artBiz)}`, { method: "POST", body: fd });
      if (!r.body) throw 0;
      const reader = r.body.getReader();
      const dec = new TextDecoder();
      let buf = "";
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += dec.decode(value, { stream: true });
        let idx;
        while ((idx = buf.indexOf("\n\n")) !== -1) {
          const block = buf.slice(0, idx); buf = buf.slice(idx + 2);
          const dm = block.match(/^data: (.+)$/m);
          if (!dm) continue;
          const d = JSON.parse(dm[1]);
          if (d.total) total = d.total;
          if (d.done !== undefined) {
            setImportingPct(Math.round((d.done / (total || 1)) * 100));
            if (d.ok) added++; else if (!d.dup) fail++;
          }
        }
      }
      setImportingPct(100);
      reload();
      message.success(`评论导入完成: 新增${added}${fail ? `, 失败${fail}` : ""}`);
      setTimeout(() => setImporting(false), 800);
    } catch { setImporting(false); message.error("导入失败"); }
  }
  // 删除选中
  function deleteSelected() {
    if (selectedKeys.length === 0) { Modal.warning({ title: "未选择", content: "请先勾选要删除的评论", okText: "知道了" }); return; }
    Modal.confirm({ title: "删除选中", content: `确定删除选中的 ${selectedKeys.length} 条评论？`, okText: "确认", cancelText: "取消",
      okButtonProps: { danger: true },
      onOk: async () => {
        await fetch(`${API}/comments?ids=${selectedKeys.join(",")}&art_biz=${encodeURIComponent(artBiz)}`, { method: "DELETE" });
        setSelectedKeys([]); reload();
      } });
  }
  function del(c: CommentRow) {
    Modal.confirm({ title: "删除评论", content: "确定删除这条评论？", okText: "确认", cancelText: "取消",
      okButtonProps: { danger: true },
      onOk: async () => { await fetch(`${API}/comments?ids=${c.id}&art_biz=${encodeURIComponent(artBiz)}`, { method: "DELETE" }); reload(); } });
  }

  const yN = (v: number) => (v ? "是" : "否");

  return (
    <div style={{ height: "100%", display: "flex", flexDirection: "column", overflow: "hidden" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 12, padding: "0 0 8px" }}>
        <Button icon={<ArrowLeftOutlined />} onClick={() => router.push(`/articles?biz=${encodeURIComponent(biz)}&name=${encodeURIComponent(name)}`)}>返回</Button>
        <Typography.Title level={5} style={{ margin: 0 }}>「{title || "..."}」的评论列表</Typography.Title>
      </div>
      {/* 评论采集设置卡片 */}
      <div style={{ display: "flex", flexDirection: "column", gap: 10, background: "#fff", borderRadius: 14, boxShadow: "0 1px 3px rgba(0,0,0,.06)", padding: "12px 18px", margin: "0 0 12px" }}>
        <div style={{ display: "flex", gap: 14, alignItems: "center", flexWrap: "wrap" }}>
          <span style={{ fontSize: 14, color: "#555" }}>文章评论数</span>
          <InputNumber min={0} placeholder="无限" value={maxComments ?? null}
            onChange={(v) => setMaxComments(typeof v === "number" && v >= 0 ? v : null)} style={{ width: 110 }} />
          <span style={{ fontSize: 14, color: "#555" }}>一级评论数</span>
          <InputNumber min={0} placeholder="无限" value={maxLevel1 ?? null}
            onChange={(v) => setMaxLevel1(typeof v === "number" && v >= 0 ? v : null)} style={{ width: 110 }} />
          <span style={{ fontSize: 14, color: "#555" }}>每级二级评论数</span>
          <InputNumber min={0} placeholder="无限" value={maxLevel2}
            onChange={(v) => setMaxLevel2(typeof v === "number" && v >= 0 ? v : null)} style={{ width: 110 }} />
        </div>
      </div>
      {/* 筛选面板 */}
      <div style={{ background: "#fff", borderRadius: 14, boxShadow: "0 1px 3px rgba(0,0,0,.06)", padding: "14px 18px", margin: "0 0 12px" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 18, flexWrap: "wrap", width: "100%" }}>
          <DatePicker.RangePicker
            value={dateRange}
            onChange={(v) => setDateRange(v as any)}
            placeholder={["开始日期", "结束日期"]}
            allowClear
            style={{ width: 280 }}
          />
          <Input allowClear prefix={<SearchOutlined style={{ color: "#bfc7cf" }} />}
            placeholder="查询作者或评论内容"
            value={kw} onChange={(e) => setKw(e.target.value)}
            style={{ flex: 1, minWidth: 180 }} />
          <Space size={6}>
            <Typography.Text style={{ fontSize: 13, whiteSpace: "nowrap" }}>点赞</Typography.Text>
            <NumRange value={likesRange} onChange={setLikesRange} />
          </Space>
        </div>
        {/* 第二行: IP/层级多选 */}
        <div style={{ display: "flex", alignItems: "center", gap: 14, flexWrap: "wrap", marginTop: 10 }}>
          <Select
            mode="multiple" allowClear placeholder="IP"
            value={ipFilter}
            onChange={(v: any[]) => setIpFilter(v && v.includes("__all__") ? ["__all__"] : (v || []))}
            style={{ minWidth: 180, maxWidth: 300 }}
            options={[
              { value: "__all__", label: "全部IP" },
              ...Array.from(new Set(comments.map((c) => c.ip || ""))).filter(Boolean)
                .map((ip) => ({ value: String(ip), label: String(ip) })),
            ]}
            maxTagCount="responsive"
          />
          <Select
            mode="multiple" allowClear placeholder="层级"
            value={levelFilter}
            onChange={(v: any[]) => setLevelFilter(v && v.includes("__all__") ? ["__all__"] : (v || []))}
            style={{ minWidth: 160, maxWidth: 240 }}
            options={[
              { value: "__all__", label: "全部层级" },
              { value: "1", label: "一级" },
              { value: "2", label: "二级" },
            ]}
            maxTagCount="responsive"
          />
        </div>
        <div style={{ display: "flex", justifyContent: "flex-end", paddingTop: 8 }}>
          {hasFilter ? <Button size="small" type="link" onClick={clearFilter}><ClearOutlined /> 清除筛选</Button> : null}
        </div>
      </div>

      <div
        onDragOver={(e) => { e.preventDefault(); if (Array.from(e.dataTransfer.types || []).includes("Files")) setDragOver(true); }}
        onDragLeave={() => setDragOver(false)}
        onDrop={(e) => { e.preventDefault(); setDragOver(false); if (Array.from(e.dataTransfer.types || []).includes("Files")) { const f = e.dataTransfer.files?.[0]; if (f) importFile(f); } }}
        style={{ display: "flex", flexDirection: "column", flex: shown.length ? 1 : undefined, minHeight: shown.length ? 0 : undefined, background: dragOver ? "#eef4ff" : "#fff", borderRadius: 14, boxShadow: "0 1px 3px rgba(0,0,0,.06)", padding: "16px 18px", transition: ".2s", border: dragOver ? "2px dashed #1565c0" : "2px solid transparent" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 12, flexWrap: "wrap" }}>
          <Tooltip
            title={(si.points.length + si.scrolls.length + si.ai.length > 0 ? `采集前需补全:\n[${si.points.length + si.scrolls.length > 0 ? "点位/滚动设置有残缺; " : ""}${si.ai.length > 0 ? "AI模型未配置" : ""}]`.trim()
              : wxLogged === false ? "请先登录微信后再采集评论" : undefined)}>
            <Button type="primary" disabled={si.points.length + si.scrolls.length + si.ai.length > 0 || wxLogged === false}
              icon={si.points.length + si.scrolls.length + si.ai.length > 0 ? <ExclamationCircleOutlined /> : <ReloadOutlined />}
              onClick={openCollect}>采集</Button>
          </Tooltip>
          <div style={{ flex: 1 }} />
          <Button color="primary" variant="outlined" icon={<PlusOutlined />} onClick={() => message.info("新增评论(开发中)")}>新增</Button>
          <Button icon={<ImportOutlined />} onClick={() => fileRef.current?.click()}>导入</Button>
          <Button danger icon={<DeleteOutlined />} onClick={deleteSelected}>删除选中</Button>
          <input ref={fileRef} type="file" accept=".csv,.xlsx,.xls,.xlsm" style={{ display: "none" }} onChange={(e) => { const f = e.target.files?.[0]; if (f) importFile(f); e.target.value = ""; }} />
        </div>
        {loading ? (
        <div style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center" }}>
          <Space vertical size={10} style={{ alignItems: "center" }}>
            <Spin size="large" />
            <Typography.Text type="secondary" style={{ fontSize: 13 }}>正在加载评论…</Typography.Text>
          </Space>
        </div>
        ) : shown.length > 0 ? (
        <div ref={tableWrapRef} style={{ flex: 1, minHeight: 0, position: "relative", overflow: "auto" }}>
          <Table className="articles-table" rowKey="id" dataSource={shown} loading={loading} pagination={false} showSorterTooltip={false} size="small" sticky scroll={{ x: 1200, y: tableY }}
            rowSelection={{ selectedRowKeys: selectedKeys, onChange: setSelectedKeys }}
            locale={{ emptyText: <Empty description={loadErr ? "加载失败，请重试" : "暂无评论"} /> }}
            columns={[
              { title: "作者", dataIndex: "author", width: 90 },
              { title: "内容", dataIndex: "content", width: 400,
                render: (v: string, r: CommentRow) => (
                  <Tooltip title={v}>
                    <div>
                      {(r.is_author || r.is_top || r.is_first || r.is_author_reply || r.is_author_like) ? (
                        <Space size={4} wrap style={{ marginBottom: 3 }}>
                          {r.is_author ? <Tag color="green" style={{ margin: 0, fontSize: 11 }}>作者</Tag> : null}
                          {r.is_top ? <Tag color="gold" style={{ margin: 0, fontSize: 11 }}>置顶</Tag> : null}
                          {r.is_first ? <Tag color="cyan" style={{ margin: 0, fontSize: 11 }}>首评</Tag> : null}
                          {r.is_author_reply ? <Tag color="blue" style={{ margin: 0, fontSize: 11 }}>作者回复</Tag> : null}
                          {r.is_author_like ? <Tag color="purple" style={{ margin: 0, fontSize: 11 }}>作者点赞</Tag> : null}
                        </Space>
                      ) : null}
                      <span style={{ display: "-webkit-box", WebkitLineClamp: 3, WebkitBoxOrient: "vertical" as any, overflow: "hidden" }}>{v}</span>
                    </div>
                  </Tooltip>
                ) },
              { title: "时间", dataIndex: "time", width: 90, sorter: (a: CommentRow, b: CommentRow) => String(a.time).localeCompare(String(b.time)) },
              { title: "点赞", dataIndex: "likes", width: 90, align: "center", sorter: (a: CommentRow, b: CommentRow) => Number(a.likes || 0) - Number(b.likes || 0) },
              { title: "IP", dataIndex: "ip", width: 60 },
              { title: "层级", dataIndex: "level", width: 90, align: "center" },
              { title: "biz", dataIndex: "comment_biz", width: 120, render: (v: string) => <Typography.Text code style={{ fontSize: 11 }}>{v}</Typography.Text> },
              { title: "父级biz", dataIndex: "parent_comment_biz", width: 120, render: (v: string) => <Typography.Text code style={{ fontSize: 11 }}>{v || "—"}</Typography.Text> },
              { title: "操作", dataIndex: "op", width: 70, align: "center", fixed: "right",
                render: (_: unknown, r: CommentRow) => (
                  <Button size="small" type="link" danger icon={<DeleteOutlined />} onClick={() => del(r)}>删除</Button>
                ) },
            ]}
          />
        </div>
        ) : (
        <div style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center", padding: "40px 0" }}>
          <Empty description={loadErr ? "加载失败，请重试" : "暂无评论"} />
        </div>
        )}
        <div style={{ display: "flex", flexDirection: "column", gap: 6, paddingTop: 10, flexShrink: 0 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <Button size="small" icon={<FileExcelOutlined />} onClick={exportExcel}>导出表格</Button>
          </div>
          <div style={{ display: "flex", justifyContent: "flex-end" }}>
            <PaginationBar total={total} page={page} pageSize={pageSize}
              onChange={(p, ps) => { setPage(p); if (ps !== pageSize) setPageSize(ps); }} />
          </div>
        </div>
      </div>
      {/* 导入进度弹窗 */}
      <Modal title="正在导入" open={importing} footer={null} closable={false} width={400}>
        <div style={{ textAlign: "center", padding: "8px 0" }}>
          <Typography.Title level={5} style={{ marginTop: 0 }}>导入进度</Typography.Title>
          <Spin size="large" />
          <div style={{ margin: "10px 0" }}><Typography.Text type="secondary" style={{ fontSize: 12 }}>正在导入评论…</Typography.Text></div>
          <Progress percent={importingPct} status={importingPct >= 100 ? "success" : "active"} />
        </div>
      </Modal>

      {/* 评论采集弹窗: 确认阶段 -> 采集进行中 */}
      <Modal
        open={ccOpen}
        title={ccStarted ? `正在采集「${title || artBiz}」评论` : "确认评论采集设置"}
        onCancel={() => { if (ccStarted) { stopCc(); return; } closeCc(); }}
        footer={ccStarted ? (
          ccStopped ? (
            <Button type="primary" onClick={closeCc}>关闭</Button>
          ) : (
            <Button danger onClick={stopCc}>按 ESC 停止</Button>
          )
        ) : (
          <>
            <Button onClick={closeCc}>取消</Button>
            <Button type="primary" onClick={confirmCommentCollect}>确认</Button>
          </>
        )}
        width={ccStarted ? 880 : 520}
      >
        {ccStarted ? (
          <div style={{ display: "flex", gap: 12 }}>
            <div style={{ flex: 1, background: "#fff", border: "1px solid #eee", borderRadius: 8, padding: "4px 0" }}>
              <div style={{ padding: "7px 14px", fontSize: 13, fontWeight: 600, color: "#333", borderBottom: "1px solid #f0f0f0" }}>采集设置</div>
              {[
                { label: "文章评论数", value: maxComments == null ? "无限" : String(maxComments) },
                { label: "一级评论数", value: maxLevel1 == null ? "无限" : String(maxLevel1) },
                { label: "每级二级评论数", value: maxLevel2 == null ? "无限" : String(maxLevel2) },
              ].map((row) => (
                <div key={row.label} style={{ display: "flex", alignItems: "center", padding: "7px 14px", fontSize: 13 }}>
                  <span style={{ width: 110, color: "#888" }}>{row.label}</span>
                  <span style={{ color: "#333", fontWeight: 500 }}>{row.value}</span>
                </div>
              ))}
            </div>
            <div style={{ flex: 1, background: "#fff", border: "1px solid #eee", borderRadius: 8, padding: "4px 0" }}>
              <div style={{ padding: "7px 14px", fontSize: 13, fontWeight: 600, color: "#333", borderBottom: "1px solid #f0f0f0" }}>采集情况</div>
              <div style={{ display: "flex", flexDirection: "column", gap: 10, padding: "10px 14px", fontSize: 13, color: "#555" }}>
                <div>开始时间: <span style={{ color: "#333" }}>{ccStartTime}</span></div>
                <div>采集评论数: <span style={{ color: "#333", fontWeight: 600 }}>{ccCount}</span></div>
                <div>一级评论数: <span style={{ color: "#333" }}>{ccCount1}</span></div>
                <div>二级评论数: <span style={{ color: "#333" }}>{ccCount2}</span></div>
                <div>采集速度: <span style={{ color: "#333" }}>{ccSpeed.toFixed(1)} 条/秒</span></div>
              </div>
            </div>
          </div>
        ) : (
          <div style={{ background: "#fff", border: "1px solid #eee", borderRadius: 8, padding: "4px 0" }}>
            <div style={{ padding: "7px 14px", fontSize: 13 }}>
              <span style={{ color: "#888" }}>文章评论数 </span>
              <span style={{ color: "#333", fontWeight: 500 }}>{maxComments == null ? "无限" : String(maxComments)}</span>
            </div>
            <div style={{ padding: "7px 14px", fontSize: 13 }}>
              <span style={{ color: "#888" }}>一级评论数 </span>
              <span style={{ color: "#333", fontWeight: 500 }}>{maxLevel1 == null ? "无限" : String(maxLevel1)}</span>
            </div>
            <div style={{ padding: "7px 14px", fontSize: 13 }}>
              <span style={{ color: "#888" }}>每级二级评论数 </span>
              <span style={{ color: "#333", fontWeight: 500 }}>{maxLevel2 == null ? "无限" : String(maxLevel2)}</span>
            </div>
          </div>
        )}
        {ccStarted && (
          <div style={{ background: "#fafafa", border: "1px solid #eee", borderRadius: 8, padding: "10px 12px", marginTop: 12 }}>
            <Typography.Text strong style={{ fontSize: 13 }}>日志</Typography.Text>
            <div ref={ccLogRef} style={{
              marginTop: 8, height: 220, overflow: "auto",
              background: "#1e1e1e", borderRadius: 6, padding: 8,
              fontFamily: "Consolas, monospace", fontSize: 12, color: "#d4d4d4", whiteSpace: "pre-wrap",
            }}>
              {ccLogs.length === 0 ? (<span style={{ color: "#888" }}>(暂无日志)</span>) : (
                ccLogs.map((l, i) => {
                  // [async:任务名] 异步统一青色; [step]橙 [ok]绿 [fail]红 [warn]黄
                  const mAsync = l.match(/^\[async:([^\]]+)\]\s?([\s\S]*)/);
                  const m = mAsync || l.match(/^\[(step|ok|fail|warn)\]\s?([\s\S]*)/);
                  let text = l, color: string | undefined;
                  if (mAsync) { color = "#36cfc9"; text = `[${mAsync[1]}] ${mAsync[2]}`; }
                  else if (m) {
                    color = { step: "#ffa940", ok: "#73d13d", fail: "#ff4d4f", warn: "#ffc53d" }[m[1]];
                    text = m[2];
                  }
                  return <div key={i} style={color ? { color } : undefined}>{text}</div>;
                })
              )}
            </div>
          </div>
        )}
      </Modal>
    </div>
  );
}
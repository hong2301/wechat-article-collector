"use client";

import { useEffect, useRef, useState, useMemo, useCallback } from "react";
import { useRouter } from "next/navigation";
import { DndProvider, useDrag, useDrop } from "react-dnd";
import { HTML5Backend } from "react-dnd-html5-backend";
import { Table, Button, Typography, Tag, Tooltip, Space, Input, Checkbox, message, Modal, Spin, Progress, Empty } from "antd";
import { DatePicker, Select } from "antd";
import dayjs from "dayjs";
import { PlusOutlined, ImportOutlined, ReloadOutlined, DeleteOutlined, ScanOutlined, InboxOutlined, CalendarOutlined, ProfileOutlined, CopyOutlined, HolderOutlined, SearchOutlined, SwapOutlined } from "@ant-design/icons";
import PointsDialog from "./components/PointsDialog";
import ScrollsDialog from "./components/ScrollsDialog";

const API = "http://127.0.0.1:8000/api/accounts";
const RESOLVE = "http://127.0.0.1:8000/api/resolve-name";

interface Task {
  id: number;
  name: string;
  biz: string;
  status: string;
  remark: string;
  collected_count?: number;
}
interface CalData {
  id: number; name: string; count: number; daily: Record<string, number>;
}

const Telescope = () => (
  <svg width="22" height="22" viewBox="0 0 1024 1024" fill="#fff" xmlns="http://www.w3.org/2000/svg"><path d="M934.4 323.84l-42.666667-165.12a128 128 0 0 0-158.293333-90.453333l-82.346667 22.186666a42.666667 42.666667 0 0 0-30.293333 52.48l11.093333 42.666667L178.773333 305.493333a42.666667 42.666667 0 0 0-30.293333 52.053334l11.093333 42.666666-42.666666 11.093334a42.666667 42.666667 0 0 0 10.666666 85.333333 46.506667 46.506667 0 0 0 11.093334 0l42.666666-11.52 11.093334 42.666667a42.666667 42.666667 0 0 0 19.626666 25.6 42.666667 42.666667 0 0 0 21.333334 5.973333 32 32 0 0 0 11.093333 0L384 515.413333v17.92a123.733333 123.733333 0 0 0 12.8 54.613334l-213.333333 213.333333a42.666667 42.666667 0 0 0 60.16 60.586667l213.333333-213.333334 11.946667 4.693334v264.106666a42.666667 42.666667 0 0 0 85.333333 0v-263.68a107.52 107.52 0 0 0 12.373333-5.12l213.333334 213.333334a42.666667 42.666667 0 1 0 60.16-60.586667l-213.333334-213.333333A131.84 131.84 0 0 0 640 533.333333v-85.333333l57.6-15.36 10.666667 42.666667a42.666667 42.666667 0 0 0 42.666666 31.573333h11.093334l82.346666-22.186667a128 128 0 0 0 90.026667-160.853333zM554.666667 533.333333a42.666667 42.666667 0 0 1-11.946667 29.44 42.666667 42.666667 0 0 1-29.44 11.946667 42.666667 42.666667 0 0 1-29.866667-12.373333 42.666667 42.666667 0 0 1-12.373333-29.866667v-42.666667L554.666667 469.333333z m-290.56-74.24l-22.186667-82.346666 412.16-110.506667 11.093333 42.666667 11.093334 42.666666z m583.68-81.066666a42.666667 42.666667 0 0 1-26.026667 20.053333l-42.666667 11.093333-33.28-123.733333L725.333333 203.093333l-11.093333-42.666666 42.666667-11.093334a42.666667 42.666667 0 0 1 52.48 30.293334l42.666666 165.12a42.666667 42.666667 0 0 1-4.266666 33.28z"/></svg>
);

const GithubIcon = () => (
  <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor"><path d="M12 .5C5.7.5.5 5.7.5 12c0 5.1 3.3 9.4 7.9 10.9.6.1.8-.3.8-.6v-2c-3.2.7-3.9-1.5-3.9-1.5-.5-1.3-1.3-1.7-1.3-1.7-1-.7.1-.7.1-.7 1.1.1 1.7 1.2 1.7 1.2 1 1.7 2.6 1.2 3.2.9.1-.7.4-1.2.7-1.5-2.4-.3-4.9-1.2-4.9-5.3 0-1.2.4-2.1 1.1-2.9-.1-.3-.5-1.4.1-2.9 0 0 .9-.3 2.9 1.1.8-.2 1.7-.3 2.6-.3s1.8.1 2.6.3c2-1.4 2.9-1.1 2.9-1.1.6 1.5.2 2.6.1 2.9.7.8 1.1 1.7 1.1 2.9 0 4.1-2.5 5-4.9 5.3.4.3.8 1 .8 2.1v3.1c0 .3.2.7.8.6 4.6-1.5 7.9-5.8 7.9-10.9C23.5 5.7 18.3.5 12 .5z"/></svg>
);

const statusMap: Record<string, { color: string; text: string }> = {
  pending: { color: "gold", text: "待采集" },
  done: { color: "green", text: "已完成" },
  error: { color: "red", text: "出错" },
};

function CollectCalendar({ daily, monthKey, onMonthChange }: {
  daily: Record<string, number>; monthKey: string; onMonthChange: (m: string) => void;
}) {
  // 多个月度日历横排拼接: 选中月 往前推2个月, 共3个月横排显示
  const [y, m] = monthKey.split("-").map(Number);
  // 旧月在左新月在右: offset 从大(最早)到小(最近)
  const months = [2, 1, 0].map((off) => {
    let my = y, mm = m - off;
    if (mm <= 0) { mm += 12; my--; }
    const nd = new Date(my, mm, 0).getDate();
    const days = [];
    for (let d = 1; d <= nd; d++) {
      const ds = `${my}-${String(mm).padStart(2, "0")}-${String(d).padStart(2, "0")}`;
      days.push({ date: ds, n: daily[ds] || 0, day: d });
    }
    return { my, mm, days, first: new Date(my, mm - 1, 1).getDay() };
  });
  const allN = months.flatMap((mo) => mo.days.map((c) => c.n));
  const max = Math.max(1, ...allN);
  const color = (n: number) => n === 0 ? "#ebedf0" : `rgba(21,101,192,${0.25 + 0.75 * (n / max)})`;
  const wkHead = ["日", "一", "二", "三", "四", "五", "六"];
  return (
    <div>
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 12 }}>
        <Select value={y} style={{ width: 90 }} onChange={(yv: number) => onMonthChange(`${yv}-${m}`)}
          options={Array.from({ length: 5 }).map((_, i) => { const yr = new Date().getFullYear() - i; return { value: yr, label: `${yr} 年` }; })} />
        <Select value={m} style={{ width: 90 }} onChange={(mv: number) => onMonthChange(`${y}-${mv}`)}
          options={Array.from({ length: 12 }).map((_, i) => ({ value: i + 1, label: `${i + 1} 月` }))} />
      </div>
      <div style={{ display: "flex", gap: 24 }}>
        {months.map((mo) => (
          <div key={`${mo.my}-${mo.mm}`} style={{ flex: 1, minWidth: 0 }}>
            <Typography.Text strong style={{ fontSize: 13 }}>{mo.my} 年 {mo.mm} 月</Typography.Text>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(7, 22px)", columnGap: 4, rowGap: 4, marginTop: 8 }}>
              {wkHead.map((w) => <div key={w} style={{ textAlign: "center", fontSize: 10, color: "#bbb" }}>{w}</div>)}
              {Array.from({ length: (mo.first + 6) % 7 }).map((_, i) => <div key={"b" + i} />)}
              {mo.days.map((c) => {
                const d = c.day;
                return (
                  <div key={c.date} title={`${c.date}: ${c.n} 篇`}
                    style={{ width: 22, height: 22, borderRadius: 4, background: color(c.n), display: "flex", alignItems: "center", justifyContent: "center", fontSize: 10, color: c.n > 0 ? "#fff" : "#888" }}>
                    {c.n > 0 ? c.n : d}
                  </div>
                );
              })}
            </div>
          </div>
        ))}
      </div>
      <div style={{ display: "flex", justifyContent: "flex-end", alignItems: "center", gap: 5, marginTop: 12 }}>
        <Typography.Text type="secondary" style={{ fontSize: 11 }}>少</Typography.Text>
        <div style={{ width: 14, height: 14, borderRadius: 3, background: "#ebedf0" }} />
        <div style={{ width: 14, height: 14, borderRadius: 3, background: "rgba(21,101,192,.35)" }} />
        <div style={{ width: 14, height: 14, borderRadius: 3, background: "rgba(21,101,192,.6)" }} />
        <div style={{ width: 14, height: 14, borderRadius: 3, background: "rgba(21,101,192,.9)" }} />
        <Typography.Text type="secondary" style={{ fontSize: 11 }}>多</Typography.Text>
      </div>
    </div>
  );
}

export default function Home() {
  const router = useRouter();
  const [tasks, setTasks] = useState<Task[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadErr, setLoadErr] = useState(false);
  const [addOpen, setAddOpen] = useState(false);
  const [name, setName] = useState("");
  const [biz, setBiz] = useState("");
  const [link, setLink] = useState("");
  const [resolving, setResolving] = useState(false);
  const [saving, setSaving] = useState(false);

  const fileRef = useRef<HTMLInputElement>(null);
  const tasksRef = useRef<Task[]>([]);
  const [importing, setImporting] = useState(false);
  const [importingPct, setImportingPct] = useState(0);
  const [dragOver, setDragOver] = useState(false);
  const [failedRows, setFailedRows] = useState<{ name: string }[]>([]);
  const [sbWidth, setSbWidth] = useState(6);
  const [selectedKeys, setSelectedKeys] = useState<React.Key[]>([]);
  const [query, setQuery] = useState("");
  const [calOpen, setCalOpen] = useState(false);
  const [calData, setCalData] = useState<CalData | null>(null);
  // 采集弹窗: 确认阶段 / 进行中阶段
  const [collectOpen, setCollectOpen] = useState(false);
  const [collectTask, setCollectTask] = useState<Task | null>(null);
  const [collectStarted, setCollectStarted] = useState(false);  // true=确认后进行中
  const [collectStartTime, setCollectStartTime] = useState<string>("");
  const [collectCount, setCollectCount] = useState(0);
  const [collectLogs, setCollectLogs] = useState<string[]>([]);
  const [pointsOpen, setPointsOpen] = useState(false);
  const [scrollsOpen, setScrollsOpen] = useState(false);
  // 日期范围(采集用), 默认当天
  const [dateRange, setDateRange] = useState<[dayjs.Dayjs, dayjs.Dayjs]>([
    dayjs(), dayjs(),
  ]);

  useEffect(() => {
    const probe = document.createElement("div");
    probe.style.cssText = "width:50px;height:50px;overflow:scroll;visibility:hidden;position:absolute;";
    document.body.appendChild(probe);
    setSbWidth(probe.offsetWidth - probe.clientWidth);
    probe.remove();
  }, []);

  async function load() {
    setLoading(true);
    try { setTasks(await (await fetch(API)).json()); setLoadErr(false); }
    catch { message.error("无法连接后端"); setLoadErr(true); }
    finally { setLoading(false); }
  }
  useEffect(() => { load(); }, []);

  async function resolve() {
    if (!link.trim()) { message.warning("请先填文章链接"); return; }
    setResolving(true); setName(""); setBiz("");
    try {
      const r = await fetch(`${RESOLVE}?link=${encodeURIComponent(link.trim())}`);
      if (!r.ok) throw 0;
      const d = await r.json();
      setName(d.name || ""); setBiz(d.biz || "");
      message.success("识别成功");
    } catch { message.error("识别失败，请检查链接"); }
    finally { setResolving(false); }
  }

  async function save() {
    if (!name.trim()) { message.warning("请填写公众号名称"); return; }
    if (!biz.trim()) { message.warning("请填写biz代码"); return; }
    setSaving(true);
    try {
      const r = await fetch(API, { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: name.trim(), biz: biz.trim(), status: "pending" }) });
      if (!r.ok) {
        let err = "保存失败";
        try { const e = await r.json(); err = e.detail || err; } catch {}
        message.error(err); return;
      }
      message.success("已保存"); setAddOpen(false); setName(""); setBiz(""); setLink(""); load();
    } catch { message.error("保存失败"); }
    finally { setSaving(false); }
  }

  async function importFile(f: File) {
    setImporting(true); setImportingPct(0); setFailedRows([]);
    const fd = new FormData();
    fd.append("file", f);
    let total = 0, addedCount = 0;
    let fails: { name: string }[] = [];
    try {
      const r = await fetch(`${API}/import`, { method: "POST", body: fd });
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
            if (d.ok) addedCount++; else fails.push({ name: d.name || "(未知)" });
          }
        }
      }
    } catch { setImporting(false); message.error("导入失败"); return; }
    setImportingPct(100);
    setFailedRows(fails);
    load();
    if (fails.length > 0) {
      message.warning(`导入完成: 新增${addedCount}, 失败${fails.length}`);
    } else {
      setTimeout(() => { setImporting(false); message.success(`导入完成: 新增${addedCount}`); }, 1000);
    }
  }
  function onPick(e: React.ChangeEvent<HTMLInputElement>) {
    const f = e.target.files?.[0];
    if (f) importFile(f);
    e.target.value = "";
  }

  async function reset(row: Task) {
    await fetch(`${API}/${row.id}`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ status: "pending" }) });
    load();
  }
  async function del(row: Task) {
    Modal.confirm({ title: "删除确认", content: `确定删除「${row.name}」？`, okText: "确认", cancelText: "取消",
      onOk: async () => { await fetch(`${API}/${row.id}`, { method: "DELETE" }); load(); } });
  }
  function collectSelected() {
    if (selectedKeys.length === 0) { Modal.warning({ title: "未选择", content: "请在左侧勾选要采集的公众号", okText: "知道了" }); return; }
    message.info(`准备采集 ${selectedKeys.length} 个公众号（功能待接后端）`);
  }
  function collectRow(row: Task) {
    // 打开确认弹窗: 显示当前采集设置(日期范围)
    setCollectTask(row);
    setCollectStarted(false);
    setCollectCount(0);
    setCollectLogs([]);
    setCollectOpen(true);
  }
  // 确认采集: 进入采集进行中(暂未接后端流程, 先更新 UI 状态)
  function confirmCollect() {
    setCollectStarted(true);
    setCollectStartTime(new Date().toLocaleTimeString("zh-CN", { hour12: false }));
    setCollectLogs((p) => [...p, `开始采集「${collectTask?.name || ""}」`]);
    // TODO: 待接入后端采集流程(SSE 推送日志/进度)
  }
  const [calMonthKey, setCalMonthKey] = useState<string>("");
  async function loadCalendar(id: number, monthKey: string) {
    const [y, m] = monthKey.split("-").map(Number);
    try {
      const r = await fetch(`${API}/calendar/${id}?year=${y}&month=${m}`);
      const d = await r.json();
      setCalData(d);
      setCalMonthKey(monthKey);   // 同步显示值, 触发3个月历刷新
    } catch { message.error("获取日历失败"); }
  }
  async function openCalendar(row: Task) {
    const now = new Date();
    const mk = `${now.getFullYear()}-${now.getMonth() + 1}`;
    setCalMonthKey(mk);
    await loadCalendar(row.id, mk);
    setCalOpen(true);
  }
  // 视觉移动(hover时实时调用, 不保存)
  function moveOrder(dragId: number, overId: number) {
    const next = [...tasksRef.current];
    const oldIndex = next.findIndex((t) => t.id === dragId);
    const newIndex = next.findIndex((t) => t.id === overId);
    if (oldIndex < 0 || newIndex < 0 || oldIndex === newIndex) return;
    const [moved] = next.splice(oldIndex, 1);
    next.splice(newIndex, 0, moved);
    tasksRef.current = next;
    setTasks(next);
  }
  // 保存最终顺序(拖拽结束调用)
  function saveOrder() {
    const ids = tasksRef.current.map((t) => t.id);
    setTimeout(() => {
      fetch(`${API}/sort`, { method: "PUT", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ids }) }).catch(() => {});
    }, 0);
  }
  // 每个数据行: useDrag + useDrop 实现拖动排序
  const shown = tasks.filter((t) => {
    const q = query.trim().toLowerCase();
    if (!q) return true;
    return (t.name || "").toLowerCase().includes(q) || (t.biz || "").toLowerCase().includes(q);
  });
  const DndRow = useMemo(() => {
    return function DndRow({ children, "data-row-key": rk, ...props }: React.HTMLAttributes<HTMLTableRowElement> & { "data-row-key": string }) {
      const [{ isDragging }, drag] = useDrag(() => ({
        type: "ACCOUNT_ROW", item: { id: Number(rk) },
        collect: (m) => ({ isDragging: m.isDragging() }),
        end: () => { saveOrder(); },
      }), []);
      const [, drop] = useDrop(() => ({
        accept: "ACCOUNT_ROW",
        hover(item: { id: number }) {
          if (item.id !== Number(rk)) moveOrder(item.id, Number(rk));
        },
      }), []);
      return (
        <tr {...props} ref={(node) => { drag(drop(node)); }}
          onDragOver={(e) => {
            // 边缘自动滚动: 靠近表格可视区顶部/底部时滚动滚动容器
            const body = (e.currentTarget as HTMLElement).closest(".ant-table-body") as HTMLElement | null;
            if (!body) return;
            const r = body.getBoundingClientRect();
            const edge = 56;
            if (e.clientY < r.top + edge) body.scrollTop -= 16;
            else if (e.clientY > r.bottom - edge) body.scrollTop += 16;
          }}
          style={{ ...(props.style || {}), ...(isDragging ? { opacity: 0.35, background: "#f0f6ff" } : {}) }}>
          {children}
        </tr>
      );
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  // 保持 tasksRef 与 tasks 同步
  useEffect(() => { tasksRef.current = tasks; }, [tasks]);
  function toggleSelect(id: number, checked: boolean) {
    setSelectedKeys((prev) => checked ? [...prev, id] : prev.filter((k) => k !== id));
  }
  function toggleSelectAll(checked: boolean) {
    setSelectedKeys(checked ? shown.map((t) => t.id) : []);
  }
  function copyBiz(row: Task) {
    if (!row.biz) return;
    navigator.clipboard.writeText(row.biz);
    message.success("biz 已复制");
  }
  async function clearAll() {
    if (selectedKeys.length === 0) {
      Modal.warning({ title: "未选择", content: "请在左侧勾选要删除的公众号", okText: "知道了" });
      return;
    }
    Modal.confirm({ title: "删除选中", content: `确定删除选中的 ${selectedKeys.length} 个公众号？`, okText: "确认", cancelText: "取消",
      okButtonProps: { danger: true },
      onOk: async () => {
        for (const id of selectedKeys) { await fetch(`${API}/${String(id)}`, { method: "DELETE" }); }
        setSelectedKeys([]);
        load(); message.success("已删除选中项");
      } });
  }


  return (
      <div style={{ height: "100%", overflow: "hidden", display: "flex", flexDirection: "column", background: "#f5f6f8", padding: 14, gap: 12 }}>
      {/* 采集设置模块(在公众号列表上方) */}
      <div style={{ display: "flex", flexDirection: "column", gap: 10, background: "#fff", borderRadius: 14, boxShadow: "0 1px 3px rgba(0,0,0,.06)", padding: "12px 18px" }}>
        {/* 日期选择栏: 日期范围选择器 + 快捷按钮 */}
        <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
          <DatePicker.RangePicker
            value={dateRange}
            onChange={(v) => { if (v && v[0] && v[1]) setDateRange([v[0], v[1]]); }}
            style={{ width: 260 }}
            allowClear={false}
          />
          <Button size="small" onClick={() => setDateRange([dayjs().subtract(2, "day"), dayjs()])}>近3天</Button>
          <Button size="small" onClick={() => setDateRange([dayjs().subtract(6, "day"), dayjs()])}>近一周</Button>
          <Button size="small" onClick={() => setDateRange([dayjs().subtract(29, "day"), dayjs()])}>近一月</Button>
          <Button size="small" onClick={() => setDateRange([dayjs().subtract(364, "day"), dayjs()])}>近一年</Button>
        </div>
        {/* 设置按钮行 */}
        <div style={{ display: "flex", gap: 8 }}>
          <Button icon={<ProfileOutlined />} onClick={() => setPointsOpen(true)}>点位设置</Button>
          <Button icon={<SwapOutlined />} onClick={() => setScrollsOpen(true)}>滚动设置</Button>
        </div>
      </div>
      <PointsDialog open={pointsOpen} onClose={() => setPointsOpen(false)} />
      <ScrollsDialog open={scrollsOpen} onClose={() => setScrollsOpen(false)} />
      <div className="dropzone"
           onDragOver={(e) => { e.preventDefault(); if (Array.from(e.dataTransfer.types || []).includes("Files")) setDragOver(true); }}
           onDragLeave={() => setDragOver(false)}
           onDrop={(e) => { e.preventDefault(); setDragOver(false); if (Array.from(e.dataTransfer.types || []).includes("Files")) { const f = e.dataTransfer.files?.[0]; if (f) importFile(f); } }}
           style={{ flex: 1, minHeight: 0, overflow: "hidden", display: "flex", flexDirection: "column", background: dragOver ? "#eef4ff" : "#fff", borderRadius: 14, boxShadow: "0 1px 3px rgba(0,0,0,.06)", padding: "16px 18px", transition: ".2s", border: dragOver ? "2px dashed #1565c0" : "2px solid transparent" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 12 }}>
          <Button type="primary" icon={<InboxOutlined />} onClick={collectSelected} style={{ flexShrink: 0 }}>采集选中</Button>
          <Input allowClear prefix={<SearchOutlined style={{ color: "#bfc7cf" }} />}
            placeholder="输入公众号名称或biz代码查询"
            value={query} onChange={(e) => setQuery(e.target.value)}
            style={{ flex: "1 1 auto", minWidth: 80 }} />
          <div style={{ flex: 1 }} />
          <Button color="primary" variant="outlined" icon={<PlusOutlined />} onClick={() => setAddOpen(true)} style={{ flexShrink: 0 }}>新增</Button>
          <Button icon={<ImportOutlined />} onClick={() => fileRef.current?.click()} style={{ flexShrink: 0 }}>文件导入</Button>
          <Button danger icon={<DeleteOutlined />} onClick={clearAll} style={{ flexShrink: 0 }}>删除选中</Button>
          <input ref={fileRef} type="file" accept=".csv,.xlsx,.xls" style={{ display: "none" }} onChange={onPick} />
        </div>

            {loading ? (
            <div style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center" }}>
              <Space vertical size={10} style={{ alignItems: "center" }}>
                <Spin size="large" />
                <Typography.Text type="secondary" style={{ fontSize: 13 }}>正在加载…</Typography.Text>
              </Space>
            </div>
            ) : shown.length > 0 ? (
            <DndProvider backend={HTML5Backend}>
            <Table className="home-table" rowKey="id" dataSource={shown} loading={loading} pagination={false} bordered scroll={{ y: "calc(100vh - 255px)" }}
              locale={{ emptyText: <Empty description={loadErr ? "加载失败，请重试" : "请添加一个公众号"} image={Empty.PRESENTED_IMAGE_SIMPLE} /> }}
              components={{ body: { row: DndRow } }}
              columns={[
                {
                  title: "", dataIndex: "drag", width: 40, align: "center",
                  render: () => <HolderOutlined style={{ color: "#bfc7cf", cursor: "grab" }} />,
                },
                {
                  title: <Checkbox indeterminate={selectedKeys.length > 0 && selectedKeys.length < shown.length}
                    checked={selectedKeys.length === shown.length && shown.length > 0}
                    onChange={(e) => toggleSelectAll(e.target.checked)} />,
                  dataIndex: "select", width: 40, align: "center",
                  render: (_: unknown, r: Task) => (
                    <Checkbox checked={selectedKeys.includes(r.id)}
                      onChange={(e) => toggleSelect(r.id, e.target.checked)} />
                  ),
                },
                {
                  title: "公众号名称", dataIndex: "name",
                  render: (_: unknown, r: Task) => (
                    <Tooltip
                      title={r.biz ? (
                        <span>
                          <code style={{ marginRight: 8 }}>{r.biz}</code>
                          <a onClick={() => copyBiz(r)} style={{ color: "#69b1ff" }}><CopyOutlined /></a>
                        </span>
                      ) : "无 biz"}
                    >
                      <span style={{ cursor: "default" }}>{r.name}</span>
                    </Tooltip>
                  ),
                },

                {
                  title: "文章采集统计", dataIndex: "op2", align: "center",
                  render: (_: unknown, row: Task) => (
                    <Space>
                      <span>{row.collected_count ?? 0}</span>
                      <Button size="small" type="link" icon={<ProfileOutlined />} onClick={() => router.push(`/articles?biz=${encodeURIComponent(row.biz || "")}&name=${encodeURIComponent(row.name || "")}`)}>查看</Button>
                    </Space>
                  ),
                },
                {
                  title: "操作", dataIndex: "op", align: "center",
                  render: (_: unknown, row: Task) => (
                    <Space>
                      <Button size="small" type="link" icon={<InboxOutlined />} onClick={() => collectRow(row)}>采集</Button>
                      <Button size="small" type="link" danger icon={<DeleteOutlined />} onClick={() => del(row)}>删除</Button>
                    </Space>
                  ),
                },
              ]}
            />
            </DndProvider>
            ) : (
            <div style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center", padding: "40px 0" }}>
              <Empty description={loadErr ? "加载失败，请重试" : "请添加一个公众号"} image={Empty.PRESENTED_IMAGE_SIMPLE} />
            </div>
            )}

        <div style={{ display: "flex", justifyContent: "flex-end", paddingTop: 10 }}>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>共 {shown.length} 个公众号</Typography.Text>
        </div>
      </div>

      {/* 导入进度/失败弹窗 */}
      <Modal title={failedRows.length ? "导入结果" : "正在导入"} open={importing}
        footer={failedRows.length ? <Button type="primary" onClick={() => setImporting(false)}>关闭</Button> : null}
        closable={failedRows.length > 0} onCancel={() => setImporting(false)} width={420}>
        {failedRows.length ? (
          <div>
            <Typography.Paragraph strong style={{ color: "#c62828" }}>有 {failedRows.length} 行导入失败（无法识别公众号），需手动处理：</Typography.Paragraph>
            <Table size="small" rowKey={(r) => r.name} pagination={false} dataSource={failedRows}
              columns={[{ title: "失败项", dataIndex: "name" }]} />
          </div>
        ) : (
          <div style={{ textAlign: "center", padding: "8px 0" }}>
            <Typography.Title level={5} style={{ marginTop: 0 }}>导入进度</Typography.Title>
            <Progress percent={importingPct} status={importingPct >= 100 ? "success" : "active"} />
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>解析文件并识别公众号名称…</Typography.Text>
          </div>
        )}
      </Modal>

      {/* 采集日历弹窗 */}
      <Modal title={calData ? `${calData.name} · 采集日历` : "采集日历"} open={calOpen}
        footer={null} onCancel={() => setCalOpen(false)} width={760} style={{ maxHeight: "80vh", overflow: "auto" }}>
        {calData && <CollectCalendar daily={calData.daily} monthKey={calMonthKey} onMonthChange={(m) => loadCalendar(calData.id, m)} />}
      </Modal>

      {/* 采集弹窗: 确认阶段 -> 采集进行中 */}
      <Modal
        open={collectOpen}
        title={collectStarted ? `正在处理: ${collectTask?.name || ""} · 任务数 0/1` : "确认采集设置"}
        onCancel={() => setCollectOpen(false)}
        footer={collectStarted ? null : (
          <>
            <Button onClick={() => setCollectOpen(false)}>取消</Button>
            <Button type="primary" onClick={confirmCollect}>确认</Button>
          </>
        )}
        width={560}
      >
        {/* 采集条件卡片 */}
        <div style={{ background: "#fff", border: "1px solid #eee", borderRadius: 8, padding: "12px 14px", marginBottom: 10 }}>
          <Typography.Text strong style={{ fontSize: 13 }}>采集条件</Typography.Text>
          <div style={{ marginTop: 8, fontSize: 13, color: "#555" }}>
            时间范围: {dateRange[0].format("YYYY-MM-DD")} ~ {dateRange[1].format("YYYY-MM-DD")}
          </div>
        </div>

        {/* 采集情况统计卡片(仅进行中显示) */}
        {collectStarted && (
          <div style={{ background: "#fff", border: "1px solid #eee", borderRadius: 8, padding: "12px 14px", marginBottom: 10 }}>
            <Typography.Text strong style={{ fontSize: 13 }}>采集情况</Typography.Text>
            <div style={{ display: "flex", gap: 24, marginTop: 8, fontSize: 13, color: "#555" }}>
              <span>开始时间: {collectStartTime}</span>
              <span>已采集文章: {collectCount} 篇</span>
              <span>采集速度: 0 篇/分</span>
            </div>
          </div>
        )}

        {/* 日志区(仅进行中显示) */}
        {collectStarted && (
          <div style={{ background: "#fafafa", border: "1px solid #eee", borderRadius: 8, padding: "10px 12px" }}>
            <Typography.Text strong style={{ fontSize: 13 }}>日志</Typography.Text>
            <div style={{
              marginTop: 8, height: 200, overflow: "auto",
              background: "#1e1e1e", borderRadius: 6, padding: 8,
              fontFamily: "Consolas, monospace", fontSize: 12, color: "#d4d4d4", whiteSpace: "pre-wrap",
            }}>
              {collectLogs.length === 0 ? (
                <span style={{ color: "#888" }}>(暂无日志)</span>
              ) : (
                collectLogs.map((l, i) => <div key={i}>{l}</div>)
              )}
            </div>
          </div>
        )}
      </Modal>

      {/* 新增弹窗 */}
      <Modal title="新增公众号" open={addOpen} onOk={save} okText="保存" confirmLoading={saving}
        onCancel={() => setAddOpen(false)} cancelText="取消">
        <Space vertical style={{ width: "100%" }} size="middle">
          <Space vertical style={{ width: "100%" }}>
            <Input placeholder="公众号名称" value={name} onChange={(e) => setName(e.target.value)} />
            <Input placeholder="biz 代码" value={biz} onChange={(e) => setBiz(e.target.value)} />
          </Space>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>或通过公众号文章链接自动获取：</Typography.Text>
          <Space.Compact style={{ width: "100%" }}>
            <Input placeholder="粘贴文章链接" value={link} onChange={(e) => setLink(e.target.value)} />
            <Button type="default" loading={resolving} icon={<ScanOutlined />} onClick={resolve}>
              {resolving ? <Spin size="small" /> : "识别"}
            </Button>
          </Space.Compact>
        </Space>
      </Modal>
    </div>
  );
}

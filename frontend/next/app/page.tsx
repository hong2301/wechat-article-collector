"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { Table, Button, Typography, Tag, Tooltip, Space, Input, message, Modal, Spin, Progress, Empty } from "antd";
import { DatePicker, Select } from "antd";
import dayjs from "dayjs";
import { PlusOutlined, ImportOutlined, ReloadOutlined, DeleteOutlined, ScanOutlined, InboxOutlined, CalendarOutlined, ProfileOutlined, CopyOutlined } from "@ant-design/icons";
import { DndContext, PointerSensor, closestCenter, useSensor, useSensors, type DragEndEvent } from "@dnd-kit/core";
import { SortableContext, verticalListSortingStrategy, useSortable, arrayMove } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";

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

interface SortableRowProps extends React.HTMLAttributes<HTMLTableRowElement> {
  "data-row-key": string;
}
function SortableRow({ children, ...props }: SortableRowProps) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({ id: props["data-row-key"] });
  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
    ...(isDragging ? { opacity: 0.6, background: "#eef4ff" } : {}),
  };
  return (
    <tr suppressHydrationWarning {...props} ref={setNodeRef} style={style} {...attributes} {...listeners}>
      {children}
    </tr>
  );
}

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
  const [loading, setLoading] = useState(false);
  const [addOpen, setAddOpen] = useState(false);
  const [name, setName] = useState("");
  const [biz, setBiz] = useState("");
  const [link, setLink] = useState("");
  const [resolving, setResolving] = useState(false);
  const [saving, setSaving] = useState(false);

  const fileRef = useRef<HTMLInputElement>(null);
  const [importing, setImporting] = useState(false);
  const [importingPct, setImportingPct] = useState(0);
  const [dragOver, setDragOver] = useState(false);
  const [failedRows, setFailedRows] = useState<{ name: string }[]>([]);
  const [sbWidth, setSbWidth] = useState(6);
  const [selectedKeys, setSelectedKeys] = useState<React.Key[]>([]);
  const [calOpen, setCalOpen] = useState(false);
  const [calData, setCalData] = useState<CalData | null>(null);

  useEffect(() => {
    const probe = document.createElement("div");
    probe.style.cssText = "width:50px;height:50px;overflow:scroll;visibility:hidden;position:absolute;";
    document.body.appendChild(probe);
    setSbWidth(probe.offsetWidth - probe.clientWidth);
    probe.remove();
  }, []);

  async function load() {
    setLoading(true);
    try { setTasks(await (await fetch(API)).json()); }
    catch { message.error("无法连接后端"); }
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
    message.info(`开始采集「${row.name}」（功能待接后端）`);
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

  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 5 } }));
  async function onDragEnd(event: DragEndEvent) {
    const { active, over } = event;
    if (!over || active.id === over.id) return;
    const oldIndex = tasks.findIndex((t) => String(t.id) === active.id);
    const newIndex = tasks.findIndex((t) => String(t.id) === over.id);
    if (oldIndex < 0 || newIndex < 0) return;
    const next = arrayMove(tasks, oldIndex, newIndex);
    setTasks(next);
    try {
      await fetch(`${API}/sort`, { method: "PUT", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ids: next.map((t) => t.id) }) });
    } catch { /* 忽略 */ }
  }

  return (
      <div style={{ height: "100%", overflow: "hidden", display: "flex", flexDirection: "column", background: "#f5f6f8" }}>
      <div className="dropzone"
           onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
           onDragLeave={() => setDragOver(false)}
           onDrop={(e) => { e.preventDefault(); setDragOver(false); const f = e.dataTransfer.files?.[0]; if (f) importFile(f); }}
           style={{ flex: 1, minHeight: 0, overflow: "hidden", display: "flex", flexDirection: "column", background: dragOver ? "#eef4ff" : "#fff", borderRadius: 14, boxShadow: "0 1px 3px rgba(0,0,0,.06)", padding: "16px 18px", transition: ".2s", border: dragOver ? "2px dashed #1565c0" : "2px solid transparent" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 12, flexWrap: "wrap" }}>
          <Button type="primary" icon={<InboxOutlined />} onClick={collectSelected}>采集选中</Button>
          <div style={{ flex: 1 }} />
          <Button color="primary" variant="outlined" icon={<PlusOutlined />} onClick={() => setAddOpen(true)}>新增</Button>
          <Button icon={<ImportOutlined />} onClick={() => fileRef.current?.click()}>文件导入</Button>
          <Button danger icon={<DeleteOutlined />} onClick={clearAll}>删除选中</Button>
          <input ref={fileRef} type="file" accept=".csv,.xlsx,.xls" style={{ display: "none" }} onChange={onPick} />
        </div>

        <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={onDragEnd}>
          <SortableContext items={tasks.map((t) => String(t.id))} strategy={verticalListSortingStrategy}>
            <Table className="home-table" rowKey="id" dataSource={tasks} loading={loading} pagination={false} bordered scroll={{ y: "calc(100vh - 255px)" }}
              locale={{ emptyText: <Empty description="请添加一个公众号" image={Empty.PRESENTED_IMAGE_SIMPLE} /> }}
              components={{ body: { row: SortableRow } }}
              rowSelection={{ selectedRowKeys: selectedKeys, onChange: setSelectedKeys }}
              columns={[
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
                      <Button size="small" type="link" icon={<ProfileOutlined />} onClick={() => router.push(`/articles?biz=${encodeURIComponent(row.biz || "")}`)}>查看</Button>
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
          </SortableContext>
        </DndContext>
        <div style={{ display: "flex", justifyContent: "flex-end", paddingTop: 10 }}>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>当前 {tasks.length} 个公众号</Typography.Text>
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

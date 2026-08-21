"use client";

import { useEffect, useRef, useState, useMemo } from "react";
import { useRouter } from "next/navigation";
import { Table, Button, Typography, Space, Tag, message, Modal, Empty, Tooltip, Spin, DatePicker, InputNumber, Input, Checkbox, Progress } from "antd";
import { ArrowLeftOutlined, InboxOutlined, PlusOutlined, ImportOutlined, DeleteOutlined, SearchOutlined, ClearOutlined } from "@ant-design/icons";
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
  const [loading, setLoading] = useState(true);
  const [loadErr, setLoadErr] = useState(false);
  const tableWrapRef = useRef<HTMLDivElement>(null);
  const [tableH, setTableH] = useState(400);
  const fileRef = useRef<HTMLInputElement>(null);

  const [selectedKeys, setSelectedKeys] = useState<React.Key[]>([]);
  const [importing, setImporting] = useState(false);
  const [importingPct, setImportingPct] = useState(0);
  const [dragOver, setDragOver] = useState(false);
  const [kw, setKw] = useState("");
  const [dateRange, setDateRange] = useState<[any, any] | null>(null);
  const [likesRange, setLikesRange] = useState<[number | null, number | null]>([null, null]);

  useEffect(() => {
    const q = new URLSearchParams(window.location.search);
    const a = q.get("art_biz") || "";
    setArtBiz(a);
    setBiz(q.get("biz") || "");
    setTitle(q.get("title") || "");
    setName(q.get("name") || "");
    if (a) load(a);
  }, []);

  useEffect(() => {
    if (loading) return;   // 表格尚未渲染, 等加载完成后测
    const el = tableWrapRef.current;
    if (!el) return;
    const upd = () => setTableH(el.clientHeight);
    upd();
    const ro = new ResizeObserver(upd);
    ro.observe(el);
    return () => ro.disconnect();
  }, [loading]);

  async function load(a: string) {
    setLoading(true);
    try {
      const r = await fetch(`${API}/comments?art_biz=${encodeURIComponent(a)}`);
      const d = await r.json();
      setComments(d.comments || []);
      setLoadErr(false);
    } catch { message.error("加载失败"); setLoadErr(true); }
    finally { setLoading(false); }
  }
  function reload() { if (artBiz) load(artBiz); }


  const hasFilter = useMemo(() => {
    return !!(dateRange || kw.trim() || likesRange[0] != null || likesRange[1] != null);
  }, [dateRange, kw, likesRange]);

  function clearFilter() {
    setDateRange(null); setKw(""); setLikesRange([null, null]);
  }

  // 过滤
  const shown = useMemo(() => {
    return comments.filter((c) => {
      if (dateRange) {
        const [s, e] = dateRange;
        const sT = s.startOf("day").valueOf(), eT = e.endOf("day").valueOf();
        if (!c.time) return false;
        const t = dayjs(c.time.replace?.(/-/g, "/") || c.time).valueOf();
        if (!Number.isFinite(t) || t < sT || t > eT) return false;
      }
      if (likesRange[0] != null || likesRange[1] != null) {
        const v = Number(String(c.likes || "").replace(/[^0-9.]/g, ""));
        if (!Number.isFinite(v)) return false;
        if (likesRange[0] != null && v < likesRange[0]!) return false;
        if (likesRange[1] != null && v > likesRange[1]!) return false;
      }
      const q = kw.trim().toLowerCase();
      if (q && !((c.author || "").toLowerCase().includes(q) || (c.content || "").toLowerCase().includes(q))) return false;
      return true;
    });
  }, [comments, dateRange, likesRange, kw]);

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
          <Button type="primary" icon={<InboxOutlined />} onClick={() => message.info("评论采集(开发中)")}>采集选中</Button>
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
        <div ref={tableWrapRef} style={{ flex: 1, minHeight: 0, position: "relative", overflow: "hidden" }}>
          <Table className="articles-table" rowKey="id" dataSource={shown} loading={loading} pagination={false} showSorterTooltip={false} size="small" scroll={{ x: 1200, y: Math.max(100, tableH - 48) }}
            rowSelection={{ selectedRowKeys: selectedKeys, onChange: setSelectedKeys }}
            locale={{ emptyText: <Empty description={loadErr ? "加载失败，请重试" : "暂无评论"} /> }}
            columns={[
              { title: "评论作者", dataIndex: "author", width: 90 },
              { title: "评论内容", dataIndex: "content", width: 400,
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
              { title: "评论时间", dataIndex: "time", width: 90, sorter: (a: CommentRow, b: CommentRow) => String(a.time).localeCompare(String(b.time)) },
              { title: "点赞", dataIndex: "likes", width: 90, align: "center", sorter: (a: CommentRow, b: CommentRow) => Number(a.likes || 0) - Number(b.likes || 0) },
              { title: "IP", dataIndex: "ip", width: 90 },
              { title: "层级", dataIndex: "level", width: 90, align: "center" },
              { title: "评论biz", dataIndex: "comment_biz", width: 90, render: (v: string) => <Typography.Text code style={{ fontSize: 11 }}>{v}</Typography.Text> },
              { title: "父级biz", dataIndex: "parent_comment_biz", width: 90, render: (v: string) => <Typography.Text code style={{ fontSize: 11 }}>{v || "—"}</Typography.Text> },
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
        <div style={{ display: "flex", justifyContent: "flex-end", paddingTop: 10 }}>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>共 {shown.length} 条评论</Typography.Text>
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
    </div>
  );
}
"use client";

import { useEffect, useRef, useState, useMemo } from "react";
import { useRouter } from "next/navigation";
import dayjs from "dayjs";
import { Table, Button, Typography, Space, Tag, message, Modal, Empty, Input, Tooltip, Progress, DatePicker } from "antd";
import { ArrowLeftOutlined, DeleteOutlined, PlusOutlined, ImportOutlined, InboxOutlined } from "@ant-design/icons";

const API = "http://127.0.0.1:8000/api/accounts";

interface Article {
  id: number;
  title: string;
  date: string;
  link: string;
  reads: string;
  likes: string;
  forwards: string;
  favorites: string;
  comments: string;
  write_time: string;
  original: string;
  ip: string;
}

export default function ArticlePage() {
  const router = useRouter();
  const [biz, setBiz] = useState("");
  const [name, setName] = useState("");
  const [articles, setArticles] = useState<Article[]>([]);
  const [sortInfo, setSortInfo] = useState<{ key: string; order: "ascend" | "descend" }>({ key: "date", order: "descend" });
  const [dateRange, setDateRange] = useState<[any, any] | null>(null);
  const [loading, setLoading] = useState(false);
  const [kw, setKw] = useState("");
  const [selectedKeys, setSelectedKeys] = useState<React.Key[]>([]);
  const [addOpen, setAddOpen] = useState(false);
  const [newLink, setNewLink] = useState("");
  const [saving, setSaving] = useState(false);
  const [importing, setImporting] = useState(false);
  const [importingPct, setImportingPct] = useState(0);
  const [failedLinks, setFailedLinks] = useState<string[]>([]);
  const [dupRows, setDupRows] = useState<any[]>([]);
  const [dragOver, setDragOver] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const b = new URLSearchParams(window.location.search).get("biz") || "";
    setBiz(b);
    if (b) load(b);
  }, []);

  // 无日期的(新增)排最前(按id倒序), 有日期的按日期倒序
  function sortArticles(list: Article[]) {
    const noDate = list.filter((a) => !a.date).sort((a, b) => b.id - a.id);
    const hasDate = list.filter((a) => a.date).sort((a, b) => (new Date(b.date).getTime() - new Date(a.date).getTime()) || (b.id - a.id));
    return [...noDate, ...hasDate];
  }

  async function load(b: string) {
    setLoading(true);
    try {
      const r = await fetch(`${API}/articles-by-biz?biz=${encodeURIComponent(b)}`);
      const d = await r.json();
      setName(d.name || "");
      setArticles(sortArticles(d.articles || []));
    } catch { message.error("加载失败"); }
    finally { setLoading(false); }
  }

  // 取列值(空值恒最前)
  function colVal(a: Article, key: string): string | number {
    const v = (a as any)[key] ?? "";
    if (key === "date" || key === "write_time") return typeof v === "string" ? v.trim() : String(v);
    return v;
  }
  const sorted = useMemo(() => {
    const key = sortInfo.key;
    const dir = sortInfo.order === "descend" ? -1 : 1;
    const arr = [...articles];
    arr.sort((a, b) => {
      const av = colVal(a, key), bv = colVal(b, key);
      const aEmpty = av === "" || av == null, bEmpty = bv === "" || bv == null;
      if (aEmpty || bEmpty) { if (aEmpty && bEmpty) return 0; return aEmpty ? -1 : 1; }
      if (key === "date" || key === "write_time") {
        const at = new Date(String(av)).getTime(), bt = new Date(String(bv)).getTime();
        return (at - bt) * dir;
      }
      const an = Number(av), bn = Number(bv);
      const r = (Number.isFinite(an) && Number.isFinite(bn)) ? an - bn : String(av).localeCompare(String(bv), "zh");
      return r * dir;
    });
    return arr;
  }, [articles, sortInfo]);

  const shown = useMemo(() => {
    if (!dateRange) return sorted;
    const [s, e] = dateRange;
    const sT = s.startOf("day").valueOf(), eT = e.endOf("day").valueOf();
    return sorted.filter((a) => {
      if (!a.date) return false;
      const t = dayjs(a.date.replace?.(/-/g, "/") || a.date).valueOf();
      return Number.isFinite(t) && t >= sT && t <= eT;
    });
  }, [sorted, dateRange]);
  function reload() { if (biz) load(biz); }

  async function importFile(f: File) {
    setImporting(true); setImportingPct(0); setFailedLinks([]); setDupRows([]);
    const fd = new FormData();
    fd.append("file", f);
    let total = 0, addedCount = 0;
    const fails: string[] = [];
    try {
      const r = await fetch(`${API}/articles-by-biz/import?biz=${encodeURIComponent(biz)}`, { method: "POST", body: fd });
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
          if (d.dups) setDupRows(d.dups);
          if (d.done !== undefined) {
            setImportingPct(Math.round((d.done / (total || 1)) * 100));
            if (d.ok) addedCount++;
            else if (d.dup) { /* 重复跳过, 不视为失败 */ }
            else fails.push(d.name || "(未知)");
          }
        }
      }
    } catch { setImporting(false); message.error("导入失败"); return; }
    setImportingPct(100);
    setFailedLinks(fails);
    reload();
    const hasFail = fails.length > 0, hasDup = dupRows.length > 0;
    if (hasFail || hasDup) {
      message.warning(`导入完成: 新增${addedCount}${hasDup ? `, 重复${dupRows.length}` : ""}${hasFail ? `, 失败${fails.length}` : ""}`);
    } else {
      setTimeout(() => { setImporting(false); message.success(`导入完成: 新增${addedCount}`); }, 1000);
    }
  }
  // 用导入文件数据覆盖已有重复记录
  async function replaceDup(row: any) {
    try {
      const r = await fetch(`${API}/articles-by-biz/save`, { method: "PUT", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ biz: row.biz || biz, link: row.link, title: row.title, date: row.date, reads: row.reads,
          likes: row.likes, forwards: row.forwards, favorites: row.favorites, comments: row.comments, original: row.original, ip: row.ip }) });
      if (!r.ok) { message.error("替换失败"); return; }
      message.success("已替换"); setDupRows((prev) => prev.filter((d) => d.link !== row.link)); reload();
    } catch { message.error("替换失败"); }
  }
  function onPick(e: React.ChangeEvent<HTMLInputElement>) {
    const f = e.target.files?.[0];
    if (f) importFile(f);
    e.target.value = "";
  }

  function openAdd() { setNewLink(""); setAddOpen(true); }

  async function saveNew() {
    const link = newLink.trim();
    if (!link) { message.warning("请输入文章链接"); return; }
    setSaving(true);
    try {
      const r = await fetch(`${API}/articles-by-biz`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ biz, link }),
      });
      if (!r.ok) { const e = await r.json().catch(() => ({})); message.error(e.detail || "保存失败"); return; }
      message.success("已新增");
      setAddOpen(false); setNewLink(""); reload();
    } catch { message.error("保存失败"); }
    finally { setSaving(false); }
  }

  async function deleteSelected() {
    if (selectedKeys.length === 0) {
      Modal.warning({ title: "未选择", content: "请在左侧勾选要删除的文章", okText: "知道了" });
      return;
    }
    Modal.confirm({ title: "删除选中", content: `确定删除选中的 ${selectedKeys.length} 篇文章？`, okText: "确认", cancelText: "取消",
      okButtonProps: { danger: true },
      onOk: async () => {
        for (const id of selectedKeys) { await fetch(`${API}/articles-by-biz/${String(id)}?biz=${encodeURIComponent(biz)}`, { method: "DELETE" }); }
        setSelectedKeys([]); reload();
      } });
  }
  function del(a: Article) {
    Modal.confirm({ title: "删除文章", content: `确定删除「${a.title?.slice(0, 30)}」？`, okText: "确认", cancelText: "取消",
      okButtonProps: { danger: true },
      onOk: async () => { await fetch(`${API}/articles-by-biz/${a.id}?biz=${encodeURIComponent(biz)}`, { method: "DELETE" }); reload(); } });
  }

  return (
    <div style={{ height: "100%", display: "flex", flexDirection: "column", overflow: "hidden" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 12, padding: "0 0 8px" }}>
        <Button icon={<ArrowLeftOutlined />} onClick={() => router.push("/")}>返回</Button>
        <Typography.Title level={5} style={{ margin: 0 }}>「{name || "..."}」的文章列表</Typography.Title>
      </div>
      {/* 筛选面板 */}
      <div style={{ background: "#fff", borderRadius: 14, boxShadow: "0 1px 3px rgba(0,0,0,.06)", padding: "12px 18px", margin: "0 0 12px", display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
        <Typography.Text strong style={{ fontSize: 13 }}>筛选</Typography.Text>
        <DatePicker.RangePicker
          value={dateRange}
          onChange={(v) => setDateRange(v as any)}
          placeholder={["开始日期", "结束日期"]}
          allowClear
          style={{ width: 280 }}
        />
        {dateRange ? <Button size="small" type="link" onClick={() => setDateRange(null)}>清除筛选</Button> : null}
      </div>
      <div
        onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
        onDragLeave={() => setDragOver(false)}
        onDrop={(e) => { e.preventDefault(); setDragOver(false); const f = e.dataTransfer.files?.[0]; if (f) importFile(f); }}
        style={{ maxHeight: "calc(100vh - 205px)", overflowY: "auto", background: dragOver ? "#eef4ff" : "#fff", borderRadius: 14, boxShadow: "0 1px 3px rgba(0,0,0,.06)", padding: "16px 18px", transition: ".2s", border: dragOver ? "2px dashed #1565c0" : "2px solid transparent" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 12, flexWrap: "wrap" }}>
          <Button type="primary" icon={<InboxOutlined />} onClick={() => message.info("采集选中(开发中)")}>采集选中</Button>
          <div style={{ flex: 1 }} />
          <Button color="primary" variant="outlined" icon={<PlusOutlined />} onClick={openAdd}>新增</Button>
          <Button icon={<ImportOutlined />} onClick={() => fileRef.current?.click()}>导入</Button>
          <Button danger icon={<DeleteOutlined />} onClick={deleteSelected}>删除选中</Button>
          <input ref={fileRef} type="file" accept=".csv,.xlsx,.xls,.xlsm" style={{ display: "none" }} onChange={onPick} />
        </div>
        <Table className="articles-table" rowKey="id" dataSource={shown} loading={loading} pagination={false} scroll={{ x: 1100 }} size="small"
          onChange={(_p: any, _f: any, sorter: any) => {
            const s = Array.isArray(sorter) ? sorter[0] : sorter;
            const key = s?.columnKey;
            const order = s?.order;
            if (key && (order === "ascend" || order === "descend")) setSortInfo({ key, order });
            else setSortInfo({ key: "date", order: "descend" });
          }}
          rowSelection={{ selectedRowKeys: selectedKeys, onChange: setSelectedKeys }}
          locale={{ emptyText: <Empty description="暂无文章" /> }}
          columns={[
            {
              title: "标题", dataIndex: "title", width: 220,
              render: (v: string, r: Article) => {
                const text = v || "";
                const shown = text.length > 8 ? text.slice(0, 8) + "…" : text;
                return (
                  <Space size={6}>
                    {r.original === "原创" ? <Tag color="green" style={{ margin: 0 }}>原创</Tag> : null}
                    <Tooltip title={text}>
                      {r.link ? <a href={r.link} target="_blank" style={{ display: "inline-block", maxWidth: "100%", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{shown}</a> : <span>{shown}</span>}
                    </Tooltip>
                  </Space>
                );
              },
            },
            {
              title: "日期", dataIndex: "date", width: 110, sorter: true,
              sortOrder: sortInfo.key === "date" ? sortInfo.order : null,
              render: (v: string) => {
                const t = v || "";
                const m = t.match(/(\d{4})-(\d{1,2})-(\d{1,2})/);
                const short = m ? `${m[1]}/${Number(m[2])}/${Number(m[3])}` : t;
                return <Tooltip title={t}><span style={{ cursor: "default" }}>{short}</span></Tooltip>;
              },
            },
            { title: "阅读", dataIndex: "reads", width: 80, sorter: true, sortOrder: sortInfo.key === "reads" ? sortInfo.order : null },
            { title: "点赞", dataIndex: "likes", width: 80, sorter: true, sortOrder: sortInfo.key === "likes" ? sortInfo.order : null },
            { title: "转发", dataIndex: "forwards", width: 80, sorter: true, sortOrder: sortInfo.key === "forwards" ? sortInfo.order : null },
            { title: "喜欢", dataIndex: "favorites", width: 80, sorter: true, sortOrder: sortInfo.key === "favorites" ? sortInfo.order : null },
            { title: "评论", dataIndex: "comments", width: 80, sorter: true, sortOrder: sortInfo.key === "comments" ? sortInfo.order : null },
            { title: "IP", dataIndex: "ip", width: 120 },
            {
              title: "写入时间", dataIndex: "write_time", width: 110, sorter: true,
              sortOrder: sortInfo.key === "write_time" ? sortInfo.order : null,
              render: (v: string) => {
                const t = v || "";
                const m = t.match(/(\d{4})-(\d{1,2})-(\d{1,2})/);
                const short = m ? `${m[1]}/${Number(m[2])}/${Number(m[3])}` : t;
                return <Tooltip title={t}><span style={{ cursor: "default" }}>{short}</span></Tooltip>;
              },
            },
            { title: "操作", dataIndex: "op", align: "center",
              render: (_: unknown, r: Article) => (
                <Space>
                  <Button size="small" type="link" icon={<InboxOutlined />} onClick={() => message.info("采集功能开发中")}>采集</Button>
                  <Button size="small" type="link" danger icon={<DeleteOutlined />} onClick={() => del(r)}>删除</Button>
                </Space>
              ) },
          ]}
        />
        <div style={{ display: "flex", justifyContent: "flex-end", paddingTop: 10 }}>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>共 {shown.length} 篇</Typography.Text>
        </div>
      </div>
      {/* 导入进度/失败弹窗 */}
      <Modal title={failedLinks.length || dupRows.length ? "导入结果" : "正在导入"} open={importing}
        footer={(failedLinks.length || dupRows.length) ? <Button type="primary" onClick={() => setImporting(false)}>关闭</Button> : null}
        closable={(failedLinks.length || dupRows.length) > 0} onCancel={() => setImporting(false)} width={520}>
        {(failedLinks.length || dupRows.length) ? (
          <div>
            {dupRows.length > 0 ? (
              <div style={{ marginBottom: 14 }}>
                <Typography.Paragraph strong>有 {dupRows.length} 条重复（未覆盖）。如文件数据更全，可点击替换更新已有记录：</Typography.Paragraph>
                <Table size="small" rowKey={(r) => r.link} pagination={false} dataSource={dupRows}
                  columns={[
                    { title: "标题", dataIndex: "title", render: (v: string, r: any) => <a href={r.link} target="_blank" style={{ fontSize: 12 }}>{(v || r.link).slice(0, 24)}</a> },
                    { title: "日期", dataIndex: "date", width: 90, render: (v: string) => <span style={{ fontSize: 12 }}>{v || "—"}</span> },
                    { title: "操作", width: 70, align: "center",
                      render: (_: unknown, r: any) => <Button size="small" type="link" onClick={() => replaceDup(r)}>替换</Button> },
                  ]} />
              </div>
            ) : null}
            {failedLinks.length > 0 ? (
              <div>
                <Typography.Paragraph strong style={{ color: "#c62828" }}>有 {failedLinks.length} 条链接导入失败，需手动处理：</Typography.Paragraph>
                <Table size="small" rowKey={(r) => r} pagination={false} dataSource={failedLinks}
                  columns={[{ title: "失败链接", dataIndex: 0, render: (v: string) => <a href={v} target="_blank" style={{ fontSize: 12 }}>{v.slice(0, 60)}</a> }]} />
              </div>
            ) : null}
          </div>
        ) : (
          <div style={{ textAlign: "center", padding: "8px 0" }}>
            <Typography.Title level={5} style={{ marginTop: 0 }}>导入进度</Typography.Title>
            <Progress percent={importingPct} status={importingPct >= 100 ? "success" : "active"} />
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>解析文件并识别文章链接…</Typography.Text>
          </div>
        )}
      </Modal>

      <Modal title="新增文章" open={addOpen} onOk={saveNew} confirmLoading={saving} onCancel={() => setAddOpen(false)}
        okText="保存" cancelText="取消">
        <Space vertical style={{ width: "100%" }}>
          <div>请输入文章链接，保存后显示在标题列（无标题则显示链接）。</div>
          <Input placeholder="https://mp.weixin.qq.com/s/..." value={newLink} onChange={(e) => setNewLink(e.target.value)} onPressEnter={saveNew} />
        </Space>
      </Modal>
    </div>
  );
}

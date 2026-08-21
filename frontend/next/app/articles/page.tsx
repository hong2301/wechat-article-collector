"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { Table, Button, Typography, Space, Tag, message, Modal, Empty, Input, Tooltip, Progress } from "antd";
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
  const [loading, setLoading] = useState(false);
  const [kw, setKw] = useState("");
  const [selectedKeys, setSelectedKeys] = useState<React.Key[]>([]);
  const [addOpen, setAddOpen] = useState(false);
  const [newLink, setNewLink] = useState("");
  const [saving, setSaving] = useState(false);
  const [importing, setImporting] = useState(false);
  const [importingPct, setImportingPct] = useState(0);
  const [failedLinks, setFailedLinks] = useState<string[]>([]);
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

  const shown = kw ? articles.filter((a) => (a.title || "").includes(kw)) : articles;
  function reload() { if (biz) load(biz); }

  async function importFile(f: File) {
    setImporting(true); setImportingPct(0); setFailedLinks([]);
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
          if (d.done !== undefined) {
            setImportingPct(Math.round((d.done / (total || 1)) * 100));
            if (d.ok) addedCount++; else fails.push(d.name || "(未知)");
          }
        }
      }
    } catch { setImporting(false); message.error("导入失败"); return; }
    setImportingPct(100);
    setFailedLinks(fails);
    reload();
    if (fails.length > 0) {
      message.warning(`导入完成: 新增${addedCount}, 失败/重复${fails.length}`);
    } else {
      setTimeout(() => { setImporting(false); message.success(`导入完成: 新增${addedCount}`); }, 1000);
    }
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
              title: "日期", dataIndex: "date", width: 110,
              render: (v: string) => {
                const t = v || "";
                const m = t.match(/(\d{4})-(\d{1,2})-(\d{1,2})/);
                const short = m ? `${m[1]}/${Number(m[2])}/${Number(m[3])}` : t;
                return <Tooltip title={t}><span style={{ cursor: "default" }}>{short}</span></Tooltip>;
              },
            },
            { title: "阅读", dataIndex: "reads", width: 80 },
            { title: "点赞", dataIndex: "likes", width: 80 },
            { title: "转发", dataIndex: "forwards", width: 80 },
            { title: "喜欢", dataIndex: "favorites", width: 80 },
            { title: "评论", dataIndex: "comments", width: 80 },
            { title: "IP", dataIndex: "ip", width: 120 },
            {
              title: "写入时间", dataIndex: "write_time", width: 110,
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
      <Modal title={failedLinks.length ? "导入结果" : "正在导入"} open={importing}
        footer={failedLinks.length ? <Button type="primary" onClick={() => setImporting(false)}>关闭</Button> : null}
        closable={failedLinks.length > 0} onCancel={() => setImporting(false)} width={460}>
        {failedLinks.length ? (
          <div>
            <Typography.Paragraph strong style={{ color: "#c62828" }}>有 {failedLinks.length} 条链接未能导入（重复或格式不符），需手动处理：</Typography.Paragraph>
            <Table size="small" rowKey={(r) => r} pagination={false} dataSource={failedLinks}
              columns={[{ title: "失败链接", dataIndex: 0, render: (v: string) => <a href={v} target="_blank" style={{ fontSize: 12 }}>{v.slice(0, 60)}</a> }]} />
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

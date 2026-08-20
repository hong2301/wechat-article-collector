"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Table, Button, Typography, Space, Tag, message, Modal, Empty, Input, Tooltip } from "antd";
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

  useEffect(() => {
    const b = new URLSearchParams(window.location.search).get("biz") || "";
    setBiz(b);
    if (b) load(b);
  }, []);

  async function load(b: string) {
    setLoading(true);
    try {
      const r = await fetch(`${API}/articles-by-biz?biz=${encodeURIComponent(b)}`);
      const d = await r.json();
      setName(d.name || "");
      setArticles(d.articles || []);
    } catch { message.error("加载失败"); }
    finally { setLoading(false); }
  }

  const shown = kw ? articles.filter((a) => (a.title || "").includes(kw)) : articles;
  function reload() { if (biz) load(biz); }

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
      <div style={{ maxHeight: "calc(100vh - 205px)", overflowY: "auto", background: "#fff", borderRadius: 14, boxShadow: "0 1px 3px rgba(0,0,0,.06)", padding: "16px 18px" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 12, flexWrap: "wrap" }}>
          <Button type="primary" icon={<InboxOutlined />} onClick={() => message.info("采集选中(开发中)")}>采集选中</Button>
          <div style={{ flex: 1 }} />
          <Button color="primary" variant="outlined" icon={<PlusOutlined />} onClick={openAdd}>新增</Button>
          <Button icon={<ImportOutlined />} onClick={() => message.info("导入文章(待接后端)")}>导入</Button>
          <Button danger icon={<DeleteOutlined />} onClick={deleteSelected}>删除选中</Button>
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
                    <Tag color={r.original === "原创" ? "green" : "default"} style={{ margin: 0 }}>{r.original || "非原创"}</Tag>
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

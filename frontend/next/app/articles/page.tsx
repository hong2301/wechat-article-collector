"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Table, Button, Typography, Space, Tag, message, Modal, Empty, Input } from "antd";
import { ArrowLeftOutlined, DeleteOutlined } from "@ant-design/icons";

const API = "http://127.0.0.1:8000/api/accounts";

interface Article {
  id: number;
  title: string;
  date: string;
  link: string;
  reads: string;
  likes: string;
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

  function del(a: Article) {
    Modal.confirm({ title: "删除文章", content: `确定删除「${a.title?.slice(0, 30)}」？`, okText: "确认", cancelText: "取消",
      okButtonProps: { danger: true },
      onOk: async () => { await fetch(`${API}/articles-by-biz/${a.id}?biz=${encodeURIComponent(biz)}`, { method: "DELETE" }); reload(); } });
  }

  return (
    <div style={{ height: "100%", display: "flex", flexDirection: "column", overflow: "hidden" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 12, padding: "0 0 12px" }}>
        <Button icon={<ArrowLeftOutlined />} onClick={() => router.push("/")}>返回</Button>
        <Typography.Title level={5} style={{ margin: 0 }}>「{name || "..."}」的文章列表</Typography.Title>
        <div style={{ flex: 1 }} />
        <Input.Search placeholder="搜索标题" value={kw} onChange={(e) => setKw(e.target.value)} style={{ width: 200 }} allowClear />
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>共 {shown.length} 篇</Typography.Text>
      </div>

      <div style={{ flex: 1, minHeight: 0, overflow: "hidden", background: "#fff", borderRadius: 14, boxShadow: "0 1px 3px rgba(0,0,0,.06)", padding: "16px 18px" }}>
        <Table rowKey="id" dataSource={shown} loading={loading} pagination={false} scroll={{ y: "calc(100vh - 205px)" }} size="middle"
          locale={{ emptyText: <Empty description="暂无文章" /> }}
          columns={[
            { title: "标题", dataIndex: "title", render: (v: string, r: Article) => r.link ? <a href={r.link} target="_blank">{v}</a> : v },
            { title: "日期", dataIndex: "date", width: 160 },
            { title: "阅读", dataIndex: "reads", width: 80 },
            { title: "点赞", dataIndex: "likes", width: 80 },
            { title: "原创", dataIndex: "original", width: 90, render: (v: string) => <Tag color={v === "原创" ? "green" : "default"}>{v || "—"}</Tag> },
            { title: "IP属地", dataIndex: "ip", width: 130 },
            { title: "操作", dataIndex: "op", width: 80, align: "center",
              render: (_: unknown, r: Article) => (
                <Space><Button size="small" type="link" danger icon={<DeleteOutlined />} onClick={() => del(r)}>删除</Button></Space>
              ) },
          ]}
        />
      </div>
    </div>
  );
}

"use client";

import { ConfigProvider, Table, Button, Typography, Tag, Tooltip, Space } from "antd";
import { PlusOutlined, ImportOutlined, ReloadOutlined, DeleteOutlined } from "@ant-design/icons";

/* 望远镜 Logo (白色, 用于蓝色圆角方块) */
const Telescope = () => (
  <svg width="22" height="22" viewBox="0 0 1024 1024" fill="#ffffff" xmlns="http://www.w3.org/2000/svg">
    <path d="M934.4 323.84l-42.666667-165.12a128 128 0 0 0-158.293333-90.453333l-82.346667 22.186666a42.666667 42.666667 0 0 0-30.293333 52.48l11.093333 42.666667L178.773333 305.493333a42.666667 42.666667 0 0 0-30.293333 52.053334l11.093333 42.666666-42.666666 11.093334a42.666667 42.666667 0 0 0 10.666666 85.333333 46.506667 46.506667 0 0 0 11.093334 0l42.666666-11.52 11.093334 42.666667a42.666667 42.666667 0 0 0 19.626666 25.6 42.666667 42.666667 0 0 0 21.333334 5.973333 32 32 0 0 0 11.093333 0L384 515.413333v17.92a123.733333 123.733333 0 0 0 12.8 54.613334l-213.333333 213.333333a42.666667 42.666667 0 0 0 60.16 60.586667l213.333333-213.333334 11.946667 4.693334v264.106666a42.666667 42.666667 0 0 0 85.333333 0v-263.68a107.52 107.52 0 0 0 12.373333-5.12l213.333334 213.333334a42.666667 42.666667 0 1 0 60.16-60.586667l-213.333334-213.333333A131.84 131.84 0 0 0 640 533.333333v-85.333333l57.6-15.36 10.666667 42.666667a42.666667 42.666667 0 0 0 42.666666 31.573333h11.093334l82.346666-22.186667a128 128 0 0 0 90.026667-160.853333zM554.666667 533.333333a42.666667 42.666667 0 0 1-11.946667 29.44 42.666667 42.666667 0 0 1-29.44 11.946667 42.666667 42.666667 0 0 1-29.866667-12.373333 42.666667 42.666667 0 0 1-12.373333-29.866667v-42.666667L554.666667 469.333333z m-290.56-74.24l-22.186667-82.346666 412.16-110.506667 11.093333 42.666667 11.093334 42.666666z m583.68-81.066666a42.666667 42.666667 0 0 1-26.026667 20.053333l-42.666667 11.093333-33.28-123.733333L725.333333 203.093333l-11.093333-42.666666 42.666667-11.093334a42.666667 42.666667 0 0 1 52.48 30.293334l42.666666 165.12a42.666667 42.666667 0 0 1-4.266666 33.28z" />
  </svg>
);

/* GitHub 图标 */
const GithubIcon = () => (
  <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor">
    <path d="M12 .5C5.7.5.5 5.7.5 12c0 5.1 3.3 9.4 7.9 10.9.6.1.8-.3.8-.6v-2c-3.2.7-3.9-1.5-3.9-1.5-.5-1.3-1.3-1.7-1.3-1.7-1-.7.1-.7.1-.7 1.1.1 1.7 1.2 1.7 1.2 1 1.7 2.6 1.2 3.2.9.1-.7.4-1.2.7-1.5-2.4-.3-4.9-1.2-4.9-5.3 0-1.2.4-2.1 1.1-2.9-.1-.3-.5-1.4.1-2.9 0 0 .9-.3 2.9 1.1.8-.2 1.7-.3 2.6-.3s1.8.1 2.6.3c2-1.4 2.9-1.1 2.9-1.1.6 1.5.2 2.6.1 2.9.7.8 1.1 1.7 1.1 2.9 0 4.1-2.5 5-4.9 5.3.4.3.8 1 .8 2.1v3.1c0 .3.2.7.8.6 4.6-1.5 7.9-5.8 7.9-10.9C23.5 5.7 18.3.5 12 .5z" />
  </svg>
);

interface Task {
  key: string;
  name: string;
  link: string;
  status: "pending" | "done" | "error";
}

const tasks: Task[] = [
  { key: "1", name: "中国通融地产", link: "mp.weixin.qq.com/s/ryh…", status: "done" },
  { key: "2", name: "债文新说", link: "mp.weixin.qq.com/s/aaL…", status: "done" },
  { key: "3", name: "天风研究", link: "mp.weixin.qq.com/s/J94…", status: "pending" },
  { key: "4", name: "损益笔记", link: "mp.weixin.qq.com/s/kZC…", status: "error" },
];

const statusMap: Record<Task["status"], { color: string; text: string }> = {
  pending: { color: "gold", text: "待采集" },
  done: { color: "green", text: "已完成" },
  error: { color: "red", text: "出错" },
};

export default function Home() {
  return (
    <ConfigProvider>
      <div style={{ minHeight: "100vh", background: "#f5f6f8", padding: "14px 20px 40px" }}>
        {/* 顶栏 */}
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "12px 2px 16px" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <div style={{ width: 34, height: 34, borderRadius: 9, background: "#1565c0", display: "flex", alignItems: "center", justifyContent: "center" }}>
              <Telescope />
            </div>
            <div>
              <div style={{ display: "flex", alignItems: "baseline", gap: 8 }}>
                <span style={{ fontSize: 19, fontWeight: 700 }}>微信公众号采集器</span>
                <span style={{ fontSize: 12, color: "#8b949e" }}>v3.1.0</span>
              </div>
              <div style={{ fontSize: 12, color: "#8b949e" }}>基于 微信 Windows 版 4.1.12.55</div>
            </div>
          </div>
          <Tooltip title="GitHub 仓库">
            <a href="https://github.com/hong2301/wechat-article-collector" target="_blank" rel="noreferrer"
               style={{ width: 34, height: 34, borderRadius: 9, background: "#fff", border: "1px solid #d0d7de", color: "#57606a", display: "flex", alignItems: "center", justifyContent: "center" }}>
              <GithubIcon />
            </a>
          </Tooltip>
        </div>

        {/* 公众号列表 */}
        <div style={{ background: "#fff", borderRadius: 14, boxShadow: "0 1px 3px rgba(0,0,0,.06)", padding: "16px 18px" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 12, flexWrap: "wrap" }}>
            <Button type="primary" icon={<PlusOutlined />}>新增</Button>
            <Button icon={<ImportOutlined />}>文件导入</Button>
            <div style={{ flex: 1 }} />
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>当前 {tasks.length} 个公众号</Typography.Text>
          </div>

          <Table
            dataSource={tasks}
            pagination={false}
            columns={[
              { title: "公众号名称", dataIndex: "name", width: 140 },
              { title: "文章链接", dataIndex: "link", render: (v: string) => <Typography.Text type="secondary" style={{ fontSize: 12 }}>{v}</Typography.Text> },
              { title: "状态", dataIndex: "status", width: 100, render: (s: Task["status"]) => <Tag color={statusMap[s].color}>{statusMap[s].text}</Tag> },
              {
                title: "操作", dataIndex: "op", width: 130,
                render: () => (
                  <Space>
                    <Button size="small" type="link" icon={<ReloadOutlined />}>重置</Button>
                    <Button size="small" type="link" danger icon={<DeleteOutlined />}>删除</Button>
                  </Space>
                ),
              },
            ]}
          />
        </div>
      </div>
    </ConfigProvider>
  );
}

"use client";

import { useEffect, useRef, useState } from "react";
import {
  Modal, Table, Button, Input, Space, message, Select, InputNumber,
  Empty, Typography, Checkbox,
} from "antd";
import {
  PlusOutlined, DeleteOutlined, SwapOutlined, EditOutlined, ImportOutlined,
} from "@ant-design/icons";

const API = "http://127.0.0.1:8000/api/scrolls";
const POINTS_API = "http://127.0.0.1:8000/api/points";

interface Scroll {
  id: number;
  name: string;
  distance: string;
  point_id: number;
  direction: string;
  remark: string;
}
interface Point {
  id: number;
  name: string;
}

interface EditState {
  open: boolean;
  isNew: boolean;
  id: number | null;
  name: string;
  distance: number | null;
  point_id: number | null;
  direction: string;
  remark: string;
}

export default function ScrollsDialog({
  open, onClose,
}: {
  open: boolean;
  onClose: () => void;
}) {
  const [rows, setRows] = useState<Scroll[]>([]);
  const [points, setPoints] = useState<Point[]>([]);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [running, setRunning] = useState<number | null>(null);
  const [selectedKeys, setSelectedKeys] = useState<React.Key[]>([]);
  const fileRef = useRef<HTMLInputElement>(null);
  const [dragOver, setDragOver] = useState(false);
  const [edit, setEdit] = useState<EditState>({
    open: false, isNew: false, id: null, name: "", distance: null,
    point_id: null, direction: "down", remark: "",
  });

  async function load() {
    setLoading(true);
    try {
      const [rs, ps] = await Promise.all([
        fetch(API).then((r) => r.json()),
        fetch(POINTS_API).then((r) => r.json()),
      ]);
      setRows(Array.isArray(rs) ? rs : []);
      setPoints(Array.isArray(ps) ? ps : []);
    } catch {
      message.error("滚动设置加载失败");
      setRows([]);
    } finally {
      setLoading(false);
    }
  }
  useEffect(() => { if (open) load(); }, [open]);

  // ---------- 新增 / 修改 ----------
  function openAdd() {
    setEdit({ open: true, isNew: true, id: null, name: "", distance: null,
      point_id: null, direction: "down", remark: "" });
  }
  function openEdit(s: Scroll) {
    setEdit({ open: true, isNew: false, id: s.id, name: s.name,
      distance: s.distance ? Number(s.distance) : null,
      point_id: s.point_id || null, direction: s.direction || "down", remark: s.remark });
  }
  async function saveEdit() {
    const { isNew, id, name, distance, point_id, direction, remark } = edit;
    if (!name.trim()) { message.warning("请填写名称"); return; }
    if (!point_id) { message.warning("请选择点位"); return; }
    setSaving(true);
    try {
      const body = JSON.stringify({
        name: name.trim(),
        distance: String(distance ?? 0),
        point_id, direction, remark: remark.trim(),
      });
      const r = isNew
        ? await fetch(API, { method: "POST", headers: { "Content-Type": "application/json" }, body })
        : await fetch(`${API}/${id}`, { method: "PUT", headers: { "Content-Type": "application/json" }, body });
      if (!r.ok) { message.error("保存失败"); return; }
      message.success(isNew ? "已新增" : "已保存");
      setEdit({ open: false, isNew: false, id: null, name: "", distance: null,
        point_id: null, direction: "down", remark: "" });
      load();
    } catch {
      message.error("保存失败");
    } finally {
      setSaving(false);
    }
  }

  // ---------- 行内更新(列表直接修改距离/点位/方向) ----------
  async function updateRow(sid: number, fields: Partial<Scroll>) {
    try {
      const r = await fetch(`${API}/${sid}`, {
        method: "PUT", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(fields),
      });
      if (!r.ok) { message.error("保存失败"); return; }
      // 本地更新列表(避免整表刷新闪烁)
      setRows((prev) => prev.map((s) => s.id === sid ? { ...s, ...fields } : s));
    } catch {
      message.error("保存失败");
    }
  }

  // ---------- 删除 ----------
  function delRow(s: Scroll) {
    Modal.confirm({
      title: "删除确认", content: `确定删除滚动 [${s.id}] ${s.name}？`, okText: "确认", cancelText: "取消",
      onOk: async () => {
        await fetch(`${API}/${s.id}`, { method: "DELETE" });
        message.success("已删除");
        load();
      },
    });
  }

  // ---------- 执行滚动 ----------
  async function runRow(s: Scroll) {
    setRunning(s.id);
    try {
      const r = await fetch(`${API}/${s.id}/run`, { method: "POST" });
      const d = await r.json();
      if (d.ok) {
        message.success(`已执行: ${d.direction === "up" ? "向上" : "向下"}滚动 ${d.distance}px @(${d.x},${d.y})`);
      } else {
        message.warning(d.reason || "滚动执行失败");
      }
    } catch {
      message.error("滚动执行失败");
    } finally {
      setRunning(null);
    }
  }

  // ---------- 导入 ----------
  async function importFile(f: File) {
    const fd = new FormData();
    fd.append("file", f);
    try {
      const r = await fetch(`${API}/import`, { method: "POST", body: fd });
      const d = await r.json();
      if (d.ok) {
        message.success(`导入完成: 新增${d.added}, 更新${d.updated}`);
        load();
      } else {
        message.error(d.detail || "导入失败");
      }
    } catch {
      message.error("导入失败");
    }
  }
  function onPick(e: React.ChangeEvent<HTMLInputElement>) {
    const f = e.target.files?.[0];
    if (f) importFile(f);
    e.target.value = "";
  }

  // ---------- 选择 ----------
  function toggleAll(checked: boolean) {
    setSelectedKeys(checked ? rows.map((s) => s.id) : []);
  }
  function toggleOne(id: number, checked: boolean) {
    setSelectedKeys((prev) =>
      checked ? [...prev, id] : prev.filter((k) => k !== id));
  }

  // ---------- 删除选中 ----------
  function delSelected() {
    if (selectedKeys.length === 0) {
      Modal.warning({ title: "未选择", content: "请先勾选要删除的滚动配置.".replace(".", ""), okText: "知道了" });
      return;
    }
    Modal.confirm({
      title: "删除选中", content: `确定删除选中的 ${selectedKeys.length} 条滚动配置？`, okText: "确认", cancelText: "取消",
      okButtonProps: { danger: true },
      onOk: async () => {
        // 逐条删除(接口无批量)
        for (const id of selectedKeys) {
          await fetch(`${API}/${String(id)}`, { method: "DELETE" });
        }
        setSelectedKeys([]);
        message.success("已删除选中项");
        load();
      },
    });
  }

  // ---------- 点位选择器选项 ----------
  const pointOptions = points.map((p) => ({
    value: p.id,
    label: `#${p.id} ${p.name || "(未命名)"}`,
  }));
  const pointName = (id: number) => {
    const p = points.find((x) => x.id === id);
    return p ? `${p.name || "(未命名)"}` : "(无)";
  };

  const columns = [
    {
      title: <Checkbox indeterminate={selectedKeys.length > 0 && selectedKeys.length < rows.length}
        checked={selectedKeys.length === rows.length && rows.length > 0}
        onChange={(e) => toggleAll(e.target.checked)} />,
      dataIndex: "sel", width: 40, align: "center" as const,
      render: (_: unknown, s: Scroll) => (
        <Checkbox checked={selectedKeys.includes(s.id)}
          onChange={(e) => toggleOne(s.id, e.target.checked)} />
      ),
    },
    { title: "id", dataIndex: "id", width: 70, align: "center" as const },
    { title: "名称", dataIndex: "name", render: (_: unknown, s: Scroll) => s.name },
    {
      title: "距离", dataIndex: "distance", width: 110, align: "center" as const,
      render: (_: unknown, s: Scroll) => (
        <InputNumber size="small" min={0} step={50}
          value={Number(s.distance) || 0} style={{ width: 90 }}
          onChange={(v) => updateRow(s.id, { distance: String(v ?? 0) })} />
      ),
    },
    {
      title: "点位id", dataIndex: "point_id", width: 140, align: "center" as const,
      render: (_: unknown, s: Scroll) => (
        <Select size="small" value={s.point_id} options={pointOptions}
          style={{ width: 130 }}
          onChange={(v) => updateRow(s.id, { point_id: v })} />
      ),
    },
    {
      title: "方向", dataIndex: "direction", width: 90, align: "center" as const,
      render: (_: unknown, s: Scroll) => (
        <Button size="small"
          onClick={() => updateRow(s.id, { direction: s.direction === "up" ? "down" : "up" })}
          style={{ width: 70 }}>
          {s.direction === "up" ? "向上" : "向下"}
        </Button>
      ),
    },
    {
      title: "操作", dataIndex: "op", width: 130, align: "center" as const,
      render: (_: unknown, s: Scroll) => (
        <Space>
          <Button size="small" type="link" icon={<SwapOutlined />}
            loading={running === s.id} onClick={() => runRow(s)}>滚动</Button>
          <Button size="small" type="link" icon={<EditOutlined />} onClick={() => openEdit(s)}>修改</Button>
          <Button size="small" type="link" danger icon={<DeleteOutlined />} onClick={() => delRow(s)}>删除</Button>
        </Space>
      ),
    },
  ];

  return (
    <Modal title="滚动设置" open={open} onCancel={onClose}
      footer={<Button onClick={onClose}>关闭</Button>} width={900}
      style={{ maxHeight: "80vh" }}>
      <div
        onDragOver={(e) => { e.preventDefault(); if (Array.from(e.dataTransfer.types || []).includes("Files")) setDragOver(true); }}
        onDragLeave={() => setDragOver(false)}
        onDrop={(e) => { e.preventDefault(); setDragOver(false); const f = e.dataTransfer.files?.[0]; if (f) importFile(f); }}
        style={{
          display: "flex", flexDirection: "column", gap: 10, height: "62vh",
          border: dragOver ? "2px dashed #1565c0" : "2px dashed transparent",
          borderRadius: 8, padding: 4, transition: ".2s", background: dragOver ? "#eef4ff" : "transparent",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <Button type="primary" icon={<PlusOutlined />} onClick={openAdd}>新增</Button>
          <Button icon={<ImportOutlined />} onClick={() => fileRef.current?.click()}>导入</Button>
          <Button danger icon={<DeleteOutlined />} onClick={delSelected}>删除选中</Button>
          <div style={{ flex: 1 }} />
          {pointName.length > 0 && (
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              共 {rows.length} 条滚动配置
            </Typography.Text>
          )}
          <input ref={fileRef} type="file" accept=".csv,.xlsx,.xls" style={{ display: "none" }} onChange={onPick} />
        </div>
        <div style={{ flex: 1, minHeight: 0, overflow: "auto" }}>
        <Table
          rowKey="id" size="small" bordered loading={loading}
          dataSource={rows} pagination={false} columns={columns}
          locale={{ emptyText: <Empty description="暂无滚动配置" image={Empty.PRESENTED_IMAGE_SIMPLE} /> }}
          sticky scroll={{ x: true }}
        />
        </div>
      </div>

      {/* 新增/修改弹窗 */}
      <Modal title={edit.isNew ? "新增滚动" : "修改滚动"} open={edit.open}
        onOk={saveEdit} okText="保存" confirmLoading={saving}
        onCancel={() => setEdit({ open: false, isNew: false, id: null, name: "",
          distance: null, point_id: null, direction: "down", remark: "" })}
        cancelText="取消">
        <Space vertical style={{ width: "100%" }}>
          <Input placeholder="名称" value={edit.name}
            onChange={(e) => setEdit({ ...edit, name: e.target.value })} />
          <Space style={{ width: "100%" }}>
            <span style={{ width: 80 }}>距离</span>
            <InputNumber min={0} step={50} value={edit.distance}
              onChange={(v) => setEdit({ ...edit, distance: v })} style={{ width: 130 }} />
            <span>px</span>
          </Space>
          <Space style={{ width: "100%" }}>
            <span style={{ width: 80 }}>点位</span>
            <Select placeholder="选择点位" value={edit.point_id}
              options={pointOptions} style={{ width: 220 }}
              onChange={(v) => setEdit({ ...edit, point_id: v })} />
          </Space>
          <Space style={{ width: "100%" }}>
            <span style={{ width: 80 }}>方向</span>
            <Select value={edit.direction}
              options={[{ value: "down", label: "向下" }, { value: "up", label: "向上" }]}
              style={{ width: 130 }}
              onChange={(v) => setEdit({ ...edit, direction: v })} />
          </Space>
          <Input placeholder="备注" value={edit.remark}
            onChange={(e) => setEdit({ ...edit, remark: e.target.value })} />
        </Space>
      </Modal>
    </Modal>
  );
}
"use client";

import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import {
  Modal, Table, Button, Input, Space, message, Checkbox, Empty,
} from "antd";
import {
  PlusOutlined, ImportOutlined, DeleteOutlined, EyeOutlined,
  EditOutlined, ScanOutlined,
} from "@ant-design/icons";

const API = "http://127.0.0.1:8000/api/points";

interface Point {
  id: number;
  name: string;
  x: string;
  y: string;
  remark: string;
}

interface EditState {
  open: boolean;
  isNew: boolean;
  id: number | null;
  name: string;
  x: string;
  y: string;
  remark: string;
}

export default function PointsDialog({
  open, onClose,
}: {
  open: boolean;
  onClose: () => void;
}) {
  const [rows, setRows] = useState<Point[]>([]);
  const [loading, setLoading] = useState(false);
  const [selectedIds, setSelectedIds] = useState<React.Key[]>([]);
  const [saving, setSaving] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const [dragOver, setDragOver] = useState(false);
  // 编辑弹窗
  const [edit, setEdit] = useState<EditState>({
    open: false, isNew: false, id: null, name: "", x: "", y: "", remark: "",
  });
  // 遮罩选点中(点击获取坐标时)
  const [capturing, setCapturing] = useState(false);
  const [capInfo, setCapInfo] = useState<{ id: number | null; name: string }>({ id: null, name: "" });

  async function load() {
    setLoading(true);
    try {
      const r = await fetch(API);
      const d = await r.json();
      setRows(Array.isArray(d) ? d : []);
    } catch {
      message.error("点位数据加载失败");
      setRows([]);
    } finally {
      setLoading(false);
    }
  }
  useEffect(() => { if (open) load(); }, [open]);

  // ---------- 选择 ----------
  function selKeys() {
    return rows.map((p) => p.id);
  }
  function toggleAll(checked: boolean) {
    setSelectedIds(checked ? selKeys() : []);
  }
  function toggleOne(id: number, checked: boolean) {
    setSelectedIds((prev) =>
      checked ? [...prev, id] : prev.filter((k) => k !== id));
  }

  // ---------- 新增 / 修改 ----------
  function openAdd() {
    setEdit({ open: true, isNew: true, id: null, name: "", x: "", y: "", remark: "" });
  }
  function openEdit(p: Point) {
    setEdit({ open: true, isNew: false, id: p.id, name: p.name, x: p.x, y: p.y, remark: p.remark });
  }
  async function saveEdit() {
    const { isNew, id, name, x, y, remark } = edit;
    if (!name.trim()) { message.warning("请填写点位名称"); return; }
    setSaving(true);
    try {
      const body = JSON.stringify({ name: name.trim(), x: x.trim(), y: y.trim(), remark: remark.trim() });
      const r = isNew
        ? await fetch(API, { method: "POST", headers: { "Content-Type": "application/json" }, body })
        : await fetch(`${API}/${id}`, { method: "PUT", headers: { "Content-Type": "application/json" }, body });
      if (!r.ok) { message.error("保存失败"); return; }
      message.success(isNew ? "已新增" : "已保存");
      setEdit({ open: false, isNew: false, id: null, name: "", x: "", y: "", remark: "" });
      load();
    } catch {
      message.error("保存失败");
    } finally {
      setSaving(false);
    }
  }

  // ---------- 点击获取坐标(前端遮罩提示 + 后端全局监听) ----------
  function pickByClick() {
    setCapturing(true);
    setCapInfo({ id: edit.id, name: edit.name || "" });
    const BASE = "http://127.0.0.1:8000/api/points";
    // 轮询: 实时把后端最近的单击坐标预览到 x/y 输入框
    const pollTimer = window.setInterval(async () => {
      try {
        const r = await fetch(`${BASE}/capture/preview`, { method: "POST" });
        const d = await r.json();
        if (d && !d.none && d.x !== undefined && d.y !== undefined) {
          setEdit((prev) => ({ ...prev, x: String(d.x), y: String(d.y) }));
        }
      } catch { /* 忽略轮询错误 */ }
    }, 200);
    // 阻塞等后端双击/右键结果
    fetch(`${BASE}/capture`, { method: "POST" })
      .then((r) => r.json())
      .then((d) => {
        if (d && !d.canceled && d.x !== undefined && d.y !== undefined) {
          setEdit((prev) => ({ ...prev, x: String(d.x), y: String(d.y) }));
          message.success(`已获取坐标 (${d.x}, ${d.y})`);
        }
      })
      .catch(() => message.error("坐标获取失败"))
      .finally(() => {
        window.clearInterval(pollTimer);
        setCapturing(false);
      });
  }

  // ---------- 删除 ----------
  async function delRow(p: Point) {
    Modal.confirm({
      title: "删除确认", content: `确定删除点位 [${p.id}] ${p.name}？`, okText: "确认", cancelText: "取消",
      onOk: async () => {
        await fetch(`${API}/${p.id}`, { method: "DELETE" });
        message.success("已删除");
        load();
      },
    });
  }
  async function delSelected() {
    if (selectedIds.length === 0) {
      Modal.warning({ title: "未选择", content: "请先勾选要删除的点位", okText: "知道了" });
      return;
    }
    Modal.confirm({
      title: "删除选中", content: `确定删除选中的 ${selectedIds.length} 个点位？`, okText: "确认", cancelText: "取消",
      okButtonProps: { danger: true },
      onOk: async () => {
        await fetch(`${API}/batch-delete`, {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ ids: selectedIds }),
        });
        setSelectedIds([]);
        message.success("已删除选中项");
        load();
      },
    });
  }

  // ---------- 预览(调后端在真实屏幕坐标亮红点) ----------
  async function previewPoint(p: Point) {
    const x = Number(p.x), y = Number(p.y);
    if (!Number.isFinite(x) || !Number.isFinite(y)) {
      message.warning("坐标无效，请先填写 x/y");
      return;
    }
    try {
      const r = await fetch(`${API}/preview`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ x, y, duration: 1 }),
      });
      if (r.ok) {
        message.success(`${p.name || "点位"} (${x}, ${y}) 预览成功`);
      } else {
        message.error("预览失败");
      }
    } catch {
      message.error("预览失败");
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

  // ---------- 表格列 ----------
  const columns = [
    {
      title: <Checkbox indeterminate={selectedIds.length > 0 && selectedIds.length < rows.length}
        checked={selectedIds.length === rows.length && rows.length > 0}
        onChange={(e) => toggleAll(e.target.checked)} />,
      dataIndex: "sel", width: 40, align: "center" as const,
      render: (_: unknown, r: Point) => (
        <Checkbox checked={selectedIds.includes(r.id)}
          onChange={(e) => toggleOne(r.id, e.target.checked)} />
      ),
    },
    { title: "id", dataIndex: "id", width: 80, align: "center" as const },
    { title: "名称", dataIndex: "name", render: (_: unknown, p: Point) => p.name },
    { title: "x", dataIndex: "x", width: 90, align: "center" as const, render: (_: unknown, p: Point) => p.x || "—" },
    { title: "y", dataIndex: "y", width: 90, align: "center" as const, render: (_: unknown, p: Point) => p.y || "—" },
    { title: "备注", dataIndex: "remark", render: (_: unknown, p: Point) => p.remark || "" },
    {
      title: "操作", dataIndex: "op", width: 150, align: "center" as const,
      render: (_: unknown, p: Point) => (
        <Space>
          <Button size="small" type="link" icon={<EyeOutlined />} onClick={() => previewPoint(p)}>预览</Button>
          <Button size="small" type="link" icon={<EditOutlined />} onClick={() => openEdit(p)}>修改</Button>
          <Button size="small" type="link" danger icon={<DeleteOutlined />} onClick={() => delRow(p)}>删除</Button>
        </Space>
      ),
    },
  ];

  return (
    <Modal
      title="点位设置" open={open}
      onCancel={onClose}
      footer={<Button onClick={onClose}>关闭</Button>}
      width={860}
      style={{ maxHeight: "80vh" }}
    >
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
        {/* 顶部操作栏 */}
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <Button type="primary" icon={<PlusOutlined />} onClick={openAdd}>新增</Button>
          <Button icon={<ImportOutlined />} onClick={() => fileRef.current?.click()}>导入</Button>
          <Button danger icon={<DeleteOutlined />} onClick={delSelected}>删除选中</Button>
          <div style={{ flex: 1 }} />
          <input ref={fileRef} type="file" accept=".csv,.xlsx,.xls" style={{ display: "none" }} onChange={onPick} />
        </div>

        {/* 点位表 */}
        <div style={{ flex: 1, minHeight: 0, overflow: "auto" }}>
        <Table
          rowKey="id" size="small" bordered loading={loading}
          dataSource={rows} pagination={false} columns={columns}
          locale={{ emptyText: <Empty description="暂无点位" image={Empty.PRESENTED_IMAGE_SIMPLE} /> }}
          sticky scroll={{ x: true }}
        />
        </div>
      </div>

      {/* 新增/修改弹窗 */}
      <Modal
        title={edit.isNew ? "新增点位" : "修改点位"} open={edit.open}
        onOk={saveEdit} okText="保存" confirmLoading={saving}
        onCancel={() => setEdit({ open: false, isNew: false, id: null, name: "", x: "", y: "", remark: "" })}
        cancelText="取消"
      >
        <Space vertical style={{ width: "100%" }}>
          <Input placeholder="名称" value={edit.name}
            onChange={(e) => setEdit({ ...edit, name: e.target.value })} />
          <div style={{ display: "flex", gap: 8 }}>
            <Input placeholder="x 坐标" value={edit.x} style={{ width: 90 }}
              onChange={(e) => setEdit({ ...edit, x: e.target.value })} />
            <Input placeholder="y 坐标" value={edit.y} style={{ width: 90 }}
              onChange={(e) => setEdit({ ...edit, y: e.target.value })} />
            <Button icon={<ScanOutlined />} onClick={pickByClick} loading={capturing}>点击获取</Button>
          </div>
          <Input placeholder="备注" value={edit.remark}
            onChange={(e) => setEdit({ ...edit, remark: e.target.value })} />
        </Space>
      </Modal>

      {/* 全局最顶层遮罩: 选点中(createPortal 到 body, 盖在所有之上) */}
      {capturing && createPortal(
        <div style={{
          position: "fixed", inset: 0, zIndex: 99999,
          background: "rgba(0,0,0,.6)",
          display: "flex", alignItems: "center", justifyContent: "center",
        }}>
          <div style={{ textAlign: "center", color: "#fff" }}>
            <div style={{ fontSize: 22, fontWeight: "bold", marginBottom: 20 }}>
              {capInfo.name ? `正在修改点位 [${capInfo.id}] ${capInfo.name}` : "正在设置点位坐标"}
            </div>
            <div style={{ fontSize: 15, lineHeight: 2.2, opacity: .95 }}>
              <div>单击设置点位</div>
              <div>双击确认并退出</div>
              <div>右键直接退出</div>
            </div>
          </div>
        </div>,
        document.body
      )}
    </Modal>
  );
}
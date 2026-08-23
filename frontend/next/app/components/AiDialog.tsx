"use client";

import { useEffect, useState } from "react";
import {
  Modal, Button, Input, Select, Space, message, Typography, Form,
} from "antd";

const API = "http://127.0.0.1:8000/api/settings/ai";

// AI 厂商(目前只支持豆包)
const PROVIDERS = [{ value: "doubao", label: "豆包" }];
// 豆包视觉模型id选项(默认当前可用)
const MODEL_OPTIONS = [
  { value: "doubao-seed-2-0-mini-260428", label: "doubao-seed-2-0-mini-260428" },
  { value: "doubao-1-5-vision-pro-32k-250115", label: "doubao-1-5-vision-pro-32k-250115" },
  { value: "doubao-1-5-vision-lite-32k-250115", label: "doubao-1-5-vision-lite-32k-250115" },
];
// 默认可用配置
const DEFAULT_API_KEY = "802ffe3f-4bc9-4030-a3f4-cc00409a4d4e";
const DEFAULT_MODELS = ["doubao-seed-2-0-mini-260428"];

export default function AiDialog({
  open, onClose,
}: {
  open: boolean;
  onClose: () => void;
}) {
  const [provider, setProvider] = useState("doubao");
  const [apiKey, setApiKey] = useState("");
  const [models, setModels] = useState<string[]>([]);
  const [saving, setSaving] = useState(false);

  async function load() {
    try {
      const r = await fetch(API);
      const d = await r.json();
      setProvider(d.provider || "doubao");
      setApiKey(d.api_key || DEFAULT_API_KEY);
      setModels(d.models && d.models.length ? d.models : DEFAULT_MODELS);
    } catch {
      message.error("AI设置加载失败");
      setApiKey(DEFAULT_API_KEY);
      setModels(DEFAULT_MODELS);
    }
  }
  useEffect(() => { if (open) load(); }, [open]);

  async function save() {
    if (!apiKey.trim()) { message.warning("请填写 Key"); return; }
    if (!models.length) { message.warning("请选择模型Id"); return; }
    setSaving(true);
    try {
      const r = await fetch(API, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ provider, api_key: apiKey.trim(), models }),
      });
      if (r.ok) {
        message.success("已保存");
        onClose();
      } else {
        message.error("保存失败");
      }
    } catch {
      message.error("保存失败");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal
      title="AI模型设置" open={open}
      onOk={save} okText="保存" confirmLoading={saving}
      onCancel={onClose} cancelText="取消"
      footer={(
        <>
          <Button onClick={onClose}>取消</Button>
          <Button type="primary" loading={saving} onClick={save}>保存</Button>
        </>
      )}
    >
      <Space orientation="vertical" style={{ width: "100%" }} size="middle">
        <Space style={{ width: "100%" }} orientation="vertical">
          <Typography.Text strong>Key</Typography.Text>
          <Input.Password
            placeholder="请输入 Key"
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
          />
        </Space>
        <Space style={{ width: "100%" }} orientation="vertical">
          <Typography.Text strong>模型Id</Typography.Text>
          <Select
            placeholder="选择模型Id"
            value={models.length ? models[0] : undefined}
            options={MODEL_OPTIONS}
            style={{ width: "100%" }}
            onChange={(v) => setModels(v ? [v] : [])}
          />
        </Space>
        <Space style={{ width: "100%" }} orientation="vertical">
          <Typography.Text strong>厂商</Typography.Text>
          <Select
            value={provider}
            options={PROVIDERS}
            style={{ width: "100%" }}
            onChange={(v) => setProvider(v)}
          />
        </Space>
      </Space>
    </Modal>
  );
}
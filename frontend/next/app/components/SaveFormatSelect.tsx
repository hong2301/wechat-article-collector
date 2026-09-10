"use client";
// 保存格式多选(采集/更新/评论 共用): 数据结构与展示统一
// 后端字段: save_formats: string[]  (html/pdf/txt/md/word; 空数组=不保存)
import { Select } from "antd";

export const SAVE_FORMAT_OPTIONS = [
  { value: "html", label: "HTML" },
  { value: "pdf", label: "PDF" },
  { value: "md", label: "Markdown" },
  { value: "txt", label: "TXT" },
  { value: "word", label: "Word" },
];

/** 格式数组 -> 展示文本(弹窗复述用) */
export function fmtLabel(v?: string[] | null): string {
  return v && v.length ? v.join(", ") : "关";
}

/** 从 localStorage 配置恢复格式数组(兼容旧的 save_html: bool) */
export function readSaveFormats(d: any): string[] | null {
  if (Array.isArray(d?.save_formats)) return d.save_formats;
  if (d?.save_html === true) return ["html"];   // 旧配置兼容
  if (d?.save_html === false) return [];
  return null;                                   // 无配置 -> 不覆盖
}

export default function SaveFormatSelect({
  value,
  onChange,
  disabled,
  style,
}: {
  value?: string[];
  onChange?: (v: string[]) => void;
  disabled?: boolean;
  style?: React.CSSProperties;
}) {
  return (
    <Select
      mode="multiple"
      allowClear
      size="small"
      placeholder="不保存"
      maxTagCount="responsive"
      value={value || []}
      onChange={(v) => onChange?.(v || [])}
      disabled={disabled}
      options={SAVE_FORMAT_OPTIONS}
      style={{ minWidth: 200, ...style }}
    />
  );
}
"use client";

import { InputNumber, Button, Input } from "antd";
import { useEffect, useState } from "react";

// 每页条数自动计算: 按可视高度估算一页能放下多少行(表头约48px, 行高约40px)
export function calcPageSize(containerH?: number): number {
  const h = containerH || (typeof window !== "undefined" ? window.innerHeight : 800);
  const rows = Math.floor((h - 220) / 40);   // 减顶部占用(header/筛选/工具栏/底栏等)
  return Math.max(10, Math.min(50, rows));
}

export default function PaginationBar({
  total, page, pageSize, onChange,
}: {
  total: number;
  page: number;
  pageSize: number;
  onChange: (page: number, pageSize: number) => void;
}) {
  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  const [jump, setJump] = useState("");

  useEffect(() => { setJump(""); }, [page, pageSize, total]);

  // 页码: 首页 + 当前页附近(±2) + 末页, 间隔用…省略
  const build = (): (number | "l" | "r")[] => {
    const arr: (number | "l" | "r")[] = [];
    const add = (p: number) => { if (p >= 1 && p <= totalPages && !arr.includes(p)) arr.push(p); };
    add(1);
    add(page - 2); add(page - 1); add(page); add(page + 1); add(page + 2);
    add(totalPages);
    arr.sort((a: any, b: any) => a - b);
    // 插入省略号
    const out: (number | "l" | "r")[] = [];
    let prev = 0;
    for (const p of arr) {
      if (p === "l" || p === "r") continue;
      if (p as unknown === 1) {} else if (p - prev > 1) out.push(out.length && out[out.length-1] === "r" ? "r" : "l");
      out.push(p);
      prev = p;
    }
    return out;
  };
  const pages = build();

  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 12, color: "#555" }}>
      <span>共 {total} 条</span>
      <span>每页</span>
      <InputNumber
        size="small" min={1} max={200} value={pageSize}
        onChange={(v) => { const n = Number(v); if (n >= 1) onChange(1, n); }}
        style={{ width: 60 }}
      />
      <span>条</span>
      <Button size="small" disabled={page <= 1} onClick={() => onChange(page - 1, pageSize)}>‹</Button>
      {pages.map((p, i) => p === "l" || p === "r"
        ? <span key={`e${i}`} style={{ color: "#bbb", padding: "0 2px" }}>…</span>
        : <Button key={p} size="small" type={p === page ? "primary" : "default"}
            onClick={() => onChange(p as number, pageSize)}>{p}</Button>)}
      <Button size="small" disabled={page >= totalPages} onClick={() => onChange(page + 1, pageSize)}>›</Button>
      <span>跳至</span>
      <Input
        size="small" style={{ width: 50 }} value={jump}
        onChange={(e) => setJump(e.target.value)}
        onPressEnter={() => {
          const n = Number(jump);
          if (n >= 1 && n <= totalPages) onChange(Math.floor(n), pageSize);
          else setJump("");
        }}
      />
      <span>页</span>
    </div>
  );
}
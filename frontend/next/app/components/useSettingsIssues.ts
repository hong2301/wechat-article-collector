// 点位/滚动设置完整性共享 Hook: 有报红(缺坐标/滚动距离空或0)时三页采集按钮置灰+提示
"use client";
import { useEffect, useState } from "react";
import { API_BASE } from "../lib/api";

export interface SettingsIssues {
  points: string[];    // 问题点位原因列表
  scrolls: string[];   // 问题滚动原因列表
}

export function useSettingsIssues() {
  const [points, setPoints] = useState<string[]>([]);
  const [scrolls, setScrolls] = useState<string[]>([]);
  const [ai, setAi] = useState<string[]>([]);
  const [tick, setTick] = useState(0);

  const refresh = () => setTick((t) => t + 1);

  // 监听全局刷新事件(快速开始/一键设置等完成后广播, 组件不共享实例无法直接调用)
  useEffect(() => {
    const h = () => refresh();
    window.addEventListener("fast-refresh-settings", h);
    window.addEventListener("focus", h);
    return () => {
      window.removeEventListener("fast-refresh-settings", h);
      window.removeEventListener("focus", h);
    };
  }, []);

  useEffect(() => {
    (async () => {
      // 点位: x/y 空或非数字
      try {
        const pd = await (await fetch(API_BASE + "/api/points")).json();
        const pl = Array.isArray(pd) ? pd : (pd.items || []);
        setPoints(pl
          .filter((p: any) => {
            const x = String(p.x ?? "").trim();
            const y = String(p.y ?? "").trim();
            return !x || !y || isNaN(Number(x)) || isNaN(Number(y));
          })
          .map((p: any) => `「${p.name || `#${p.id}`}」坐标不完整${(!String(p.x ?? "").trim() || isNaN(Number(p.x))) ? "缺x" : "缺y"}`));
      } catch { setPoints([]); }
      // 滚动: distance 空/0/非数字
      try {
        const sd = await (await fetch(API_BASE + "/api/scrolls")).json();
        const sl = Array.isArray(sd) ? sd : (sd.items || []);
        setScrolls(sl
          .filter((s: any) => {
            const dist = String(s.distance ?? "").trim();
            return !dist || Number(dist) === 0 || isNaN(Number(dist));
          })
          .map((s: any) => `「${s.name || `#${s.id}`}」滚动距离${(!String(s.distance ?? "").trim() || Number(s.distance) === 0) ? "未填写" : "无效"}`));
      } catch { setScrolls([]); }
      // AI模型: key空/无模型ID/无厂商 -> 报红
      try {
        const d = await (await fetch(API_BASE + "/api/settings/ai")).json();
        const issues: string[] = [];
        if (!String(d.api_key || "").trim()) issues.push("未填写 API Key");
        if (!Array.isArray(d.models) || d.models.length === 0) issues.push("未选择模型ID");
        if (!String(d.provider || "").trim()) issues.push("未选择厂商");
        setAi(issues);
      } catch { setAi([]); }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tick]);

  return { points, scrolls, ai, refresh };
}
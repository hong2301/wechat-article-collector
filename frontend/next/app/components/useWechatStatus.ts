// 微信登录状态共享 Hook: 1s 短轮询瞬时 GET(无长连接, 后端 Ctrl+C 秒退优雅)
"use client";
import { useEffect, useState } from "react";
import { API_BASE } from "../lib/api";

export function useWechatStatus(): boolean | null {
  const [wxLogged, setWxLogged] = useState<boolean | null>(null);
  useEffect(() => {
    let stopped = false;
    async function check() {
      try {
        const d = await (await fetch(API_BASE + "/api/settings/wechat-status")).json();
        if (!stopped) setWxLogged(!!d.logged_in);
      } catch { /* 后端不可达保持旧状态 */ }
    }
    check();
    const t = setInterval(check, 3000);   // 3 秒一次(1s 过频, 日志/负载都无谓)
    return () => { stopped = true; clearInterval(t); };
  }, []);
  return wxLogged;
}
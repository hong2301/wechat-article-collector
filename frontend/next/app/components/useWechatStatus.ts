// 微信登录状态共享 Hook: 1秒短轮询瞬时 GET(无长连接不阻塞后端关停)
"use client";
import { useEffect, useState } from "react";

export function useWechatStatus(): boolean | null {
  const [wxLogged, setWxLogged] = useState<boolean | null>(null);
  useEffect(() => {
    let stopped = false;
    async function check() {
      try {
        const d = await (await fetch("http://127.0.0.1:8000/api/settings/wechat-status")).json();
        if (!stopped) setWxLogged(!!d.logged_in);
      } catch { /* 后端不可达保持旧状态 */ }
    }
    check();
    const t = setInterval(check, 1000);   // 1 秒一次
    return () => { stopped = true; clearInterval(t); };
  }, []);
  return wxLogged;
}
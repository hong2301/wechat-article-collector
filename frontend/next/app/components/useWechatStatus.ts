// 微信登录状态共享 Hook: 后端1s检测 + SSE推送(前端零轮询, 状态变化即时收到)
"use client";
import { useEffect, useState } from "react";

export function useWechatStatus(): boolean | null {
  const [wxLogged, setWxLogged] = useState<boolean | null>(null);
  useEffect(() => {
    const es = new EventSource("http://127.0.0.1:8000/api/settings/wechat-status/stream");
    es.onmessage = (e) => {
      try {
        const d = JSON.parse(e.data);
        setWxLogged(!!d.logged_in);
      } catch { /* 忽略坏帧 */ }
    };
    es.onerror = () => { /* EventSource 自动重连 */ };
    return () => es.close();
  }, []);
  return wxLogged;
}
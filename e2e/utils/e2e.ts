/* 测试通用工具: 后端 API / SSE 读取 / 日志断言 */
import { test, expect } from "@playwright/test";

export const API_DEV = "http://127.0.0.1:8000";
export const LOG_FILE = require("path").join(
  __dirname, "..", "..", "data", "logs", "backend.log");

/** 请求后端接口, 自动断言 2xx */
export async function api(path: string, init?: RequestInit) {
  const r = await fetch(`${API_DEV}${path}`, init);
  expect(r.status).toBeLessThan(300);
  return r.json();
}

/** 读取后端日志新增段(自 startSize 起); 断言不含异常关键字 */
export async function assertLogClean(startSize = 0, extra = "Traceback"):
    Promise<void> {
  const fs = require("fs");
  const st = fs.statSync(LOG_FILE);
  const fd = fs.openSync(LOG_FILE, "r");
  const buf = Buffer.alloc(Math.max(0, st.size - startSize));
  if (buf.length) fs.readSync(fd, buf, 0, buf.length, startSize);
  fs.closeSync(fd);
  const seg = buf.toString("utf-8");
  expect(seg).not.toContain(extra);
}

/** 等 SSE 流结束(done 事件), 返回事件数组 */
export async function collectSSE(resp: Response, timeoutMs = 120000): Promise<any[]> {
  const events: any[] = [];
  const reader = resp.body!.getReader();
  const dec = new TextDecoder();
  const deadline = Date.now() + timeoutMs;
  let buf = "";
  for (;;) {
    if (Date.now() > deadline) throw new Error("SSE 超时未收到 done");
    const { done, value } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    let i;
    while ((i = buf.indexOf("\n\n")) !== -1) {
      const block = buf.slice(0, i); buf = buf.slice(i + 2);
      const m = block.match(/^data: (.+)$/m);
      if (m) events.push(JSON.parse(m[1]));
    }
  }
  return events;
}

export { test, expect };
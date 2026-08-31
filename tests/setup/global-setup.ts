/* E2E 全局启动: 拉起后端(dev 8000 / prod 8001), 记录日志基线
   返回的 data 传给 global-teardown: { logFile, startSize, procs } */
import { spawn, ChildProcess } from "child_process";
import fs from "fs";
import path from "path";

const ROOT = path.join(__dirname, "..", "..");
const DATA = path.join(ROOT, "data");
const LOG_FILE = path.join(DATA, "logs", "backend.log");

export default async function globalSetup(): Promise<any> {
  fs.mkdirSync(path.join(DATA, "logs"), { recursive: true });
  const startSize = fs.existsSync(LOG_FILE) ? fs.statSync(LOG_FILE).size : 0;
  // 基线写入临时文件, 供用例"只查本轮新增日志"
  fs.writeFileSync(path.join(__dirname, "..", ".baseline"), String(startSize));

  // dev 后端(8000): 已存在则复用; 否则拉起
  const procs: ChildProcess[] = [];
  const devUp = await health("http://127.0.0.1:8000/api/health");
  if (!devUp) {
    console.log("[e2e] 拉起开发后端(8000)");
    const p = spawn("python", [path.join(ROOT, "backend", "run.py")], {
      cwd: path.join(ROOT, "backend"),
      stdio: "ignore",
      detached: true,
    });
    procs.push(p);
  }
  // dev 前端(next dev on 3000): 未运行则拉起
  const feUp = await health("http://localhost:3000");
  if (!feUp) {
    console.log("[e2e] 拉起开发前端(next dev:3000)");
    const fe = spawn("cmd", ["/c", "npx", "next", "dev"], {
      cwd: path.join(ROOT, "frontend", "next"),
      stdio: "ignore",
      detached: true,
    });
    procs.push(fe);
  }
  // 等待前后端就绪
  for (let i = 0; i < 60; i++) {
    const u1 = await health("http://127.0.0.1:8000/api/health");
    const u2 = await health("http://localhost:3000");
    if (u1 && u2) break;
    await sleep(1000);
  }
  return { procs, logFile: LOG_FILE, startSize };
}

async function sleep(ms: number) { return new Promise((r) => setTimeout(r, ms)); }
async function health(url: string): Promise<boolean> {
  try {
    const r = await fetch(url, { signal: AbortSignal.timeout(1500) });
    return r.ok;
  } catch { return false; }
}
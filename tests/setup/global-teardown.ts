import { ChildProcess } from "child_process";

export default async function globalTeardown(data: any) {
  if (!data) return;
  // 杀掉 setup 里拉起的后端(自己起的才杀, 复用的不动)
  for (const p of data.procs || []) {
    try { process.kill(-(p as ChildProcess).pid as number); } catch {}
    try { (p as ChildProcess).kill(); } catch {}
  }
  // 生产(8001)测试进程由 Electron exe 自己管, 不动
}
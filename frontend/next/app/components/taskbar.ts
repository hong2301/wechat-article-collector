import { API_BASE } from "../lib/api";
// 任务栏控制: 采集弹窗显示即隐藏任务栏(整屏采集), 弹窗关闭即恢复
export function hideTaskbar() {
  fetch(`${API_BASE}/api/settings/taskbar`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action: "hide" }),
  }).catch(() => { /* 忽略失败 */ });
}

export function showTaskbar() {
  fetch(`${API_BASE}/api/settings/taskbar`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action: "show" }),
  }).catch(() => { /* 忽略失败 */ });
}
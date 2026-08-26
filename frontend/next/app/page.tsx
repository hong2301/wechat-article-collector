"use client";

import { useEffect, useRef, useState, useMemo, useCallback } from "react";
import { useRouter } from "next/navigation";
import { DndProvider, useDrag, useDrop } from "react-dnd";
import { HTML5Backend } from "react-dnd-html5-backend";
import { Table, Button, Typography, Tag, Tooltip, Space, Input, Checkbox, message, Modal, Spin, Progress, Empty, Switch, InputNumber } from "antd";
import { DatePicker, Select } from "antd";
import dayjs from "dayjs";
import { PlusOutlined, ImportOutlined, ReloadOutlined, DeleteOutlined, ScanOutlined, InboxOutlined, CalendarOutlined, ProfileOutlined, CopyOutlined, HolderOutlined, SearchOutlined, SwapOutlined, RobotOutlined, FolderOpenOutlined, FileExcelOutlined, UnorderedListOutlined, ExclamationCircleOutlined, QuestionCircleOutlined } from "@ant-design/icons";
import * as XLSX from "xlsx";
import PointsDialog from "./components/PointsDialog";
import PaginationBar, { calcPageSize } from "./components/PaginationBar";
import { hideTaskbar, showTaskbar } from "./components/taskbar";
import { useSettingsIssues } from "./components/useSettingsIssues";
import ScrollsDialog from "./components/ScrollsDialog";
import AiDialog from "./components/AiDialog";

const API = "http://127.0.0.1:8000/api/accounts";
const RESOLVE = "http://127.0.0.1:8000/api/resolve-name";
const COLLECT = "http://127.0.0.1:8000/api/collect/start";
// 采集触发类型枚举(可扩展)
const COLLECT_TYPE = {
  ACCOUNT_CLICK: 1,   // 公众号列表点击采集
} as const;

interface Task {
  id: number;
  name: string;
  biz: string;
  status: string;
  remark: string;
  collected_count?: number;
}
interface CalData {
  id: number; name: string; count: number; daily: Record<string, number>;
}

const Telescope = () => (
  <svg width="22" height="22" viewBox="0 0 1024 1024" fill="#fff" xmlns="http://www.w3.org/2000/svg"><path d="M934.4 323.84l-42.666667-165.12a128 128 0 0 0-158.293333-90.453333l-82.346667 22.186666a42.666667 42.666667 0 0 0-30.293333 52.48l11.093333 42.666667L178.773333 305.493333a42.666667 42.666667 0 0 0-30.293333 52.053334l11.093333 42.666666-42.666666 11.093334a42.666667 42.666667 0 0 0 10.666666 85.333333 46.506667 46.506667 0 0 0 11.093334 0l42.666666-11.52 11.093334 42.666667a42.666667 42.666667 0 0 0 19.626666 25.6 42.666667 42.666667 0 0 0 21.333334 5.973333 32 32 0 0 0 11.093333 0L384 515.413333v17.92a123.733333 123.733333 0 0 0 12.8 54.613334l-213.333333 213.333333a42.666667 42.666667 0 0 0 60.16 60.586667l213.333333-213.333334 11.946667 4.693334v264.106666a42.666667 42.666667 0 0 0 85.333333 0v-263.68a107.52 107.52 0 0 0 12.373333-5.12l213.333334 213.333334a42.666667 42.666667 0 1 0 60.16-60.586667l-213.333334-213.333333A131.84 131.84 0 0 0 640 533.333333v-85.333333l57.6-15.36 10.666667 42.666667a42.666667 42.666667 0 0 0 42.666666 31.573333h11.093334l82.346666-22.186667a128 128 0 0 0 90.026667-160.853333zM554.666667 533.333333a42.666667 42.666667 0 0 1-11.946667 29.44 42.666667 42.666667 0 0 1-29.44 11.946667 42.666667 42.666667 0 0 1-29.866667-12.373333 42.666667 42.666667 0 0 1-12.373333-29.866667v-42.666667L554.666667 469.333333z m-290.56-74.24l-22.186667-82.346666 412.16-110.506667 11.093333 42.666667 11.093334 42.666666z m583.68-81.066666a42.666667 42.666667 0 0 1-26.026667 20.053333l-42.666667 11.093333-33.28-123.733333L725.333333 203.093333l-11.093333-42.666666 42.666667-11.093334a42.666667 42.666667 0 0 1 52.48 30.293334l42.666666 165.12a42.666667 42.666667 0 0 1-4.266666 33.28z"/></svg>
);

const GithubIcon = () => (
  <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor"><path d="M12 .5C5.7.5.5 5.7.5 12c0 5.1 3.3 9.4 7.9 10.9.6.1.8-.3.8-.6v-2c-3.2.7-3.9-1.5-3.9-1.5-.5-1.3-1.3-1.7-1.3-1.7-1-.7.1-.7.1-.7 1.1.1 1.7 1.2 1.7 1.2 1 1.7 2.6 1.2 3.2.9.1-.7.4-1.2.7-1.5-2.4-.3-4.9-1.2-4.9-5.3 0-1.2.4-2.1 1.1-2.9-.1-.3-.5-1.4.1-2.9 0 0 .9-.3 2.9 1.1.8-.2 1.7-.3 2.6-.3s1.8.1 2.6.3c2-1.4 2.9-1.1 2.9-1.1.6 1.5.2 2.6.1 2.9.7.8 1.1 1.7 1.1 2.9 0 4.1-2.5 5-4.9 5.3.4.3.8 1 .8 2.1v3.1c0 .3.2.7.8.6 4.6-1.5 7.9-5.8 7.9-10.9C23.5 5.7 18.3.5 12 .5z"/></svg>
);

const statusMap: Record<string, { color: string; text: string }> = {
  pending: { color: "gold", text: "待采集" },
  done: { color: "green", text: "已完成" },
  error: { color: "red", text: "出错" },
};

function CollectCalendar({ daily, monthKey, onMonthChange }: {
  daily: Record<string, number>; monthKey: string; onMonthChange: (m: string) => void;
}) {
  // 多个月度日历横排拼接: 选中月 往前推2个月, 共3个月横排显示
  const [y, m] = monthKey.split("-").map(Number);
  // 旧月在左新月在右: offset 从大(最早)到小(最近)
  const months = [2, 1, 0].map((off) => {
    let my = y, mm = m - off;
    if (mm <= 0) { mm += 12; my--; }
    const nd = new Date(my, mm, 0).getDate();
    const days = [];
    for (let d = 1; d <= nd; d++) {
      const ds = `${my}-${String(mm).padStart(2, "0")}-${String(d).padStart(2, "0")}`;
      days.push({ date: ds, n: daily[ds] || 0, day: d });
    }
    return { my, mm, days, first: new Date(my, mm - 1, 1).getDay() };
  });
  const allN = months.flatMap((mo) => mo.days.map((c) => c.n));
  const max = Math.max(1, ...allN);
  const color = (n: number) => n === 0 ? "#ebedf0" : `rgba(21,101,192,${0.25 + 0.75 * (n / max)})`;
  const wkHead = ["日", "一", "二", "三", "四", "五", "六"];
  return (
    <div>
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 12 }}>
        <Select value={y} style={{ width: 90 }} onChange={(yv: number) => onMonthChange(`${yv}-${m}`)}
          options={Array.from({ length: 5 }).map((_, i) => { const yr = new Date().getFullYear() - i; return { value: yr, label: `${yr} 年` }; })} />
        <Select value={m} style={{ width: 90 }} onChange={(mv: number) => onMonthChange(`${y}-${mv}`)}
          options={Array.from({ length: 12 }).map((_, i) => ({ value: i + 1, label: `${i + 1} 月` }))} />
      </div>
      <div style={{ display: "flex", gap: 24 }}>
        {months.map((mo) => (
          <div key={`${mo.my}-${mo.mm}`} style={{ flex: 1, minWidth: 0 }}>
            <Typography.Text strong style={{ fontSize: 13 }}>{mo.my} 年 {mo.mm} 月</Typography.Text>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(7, 22px)", columnGap: 4, rowGap: 4, marginTop: 8 }}>
              {wkHead.map((w) => <div key={w} style={{ textAlign: "center", fontSize: 10, color: "#bbb" }}>{w}</div>)}
              {Array.from({ length: (mo.first + 6) % 7 }).map((_, i) => <div key={"b" + i} />)}
              {mo.days.map((c) => {
                const d = c.day;
                return (
                  <div key={c.date} title={`${c.date}: ${c.n} 篇`}
                    style={{ width: 22, height: 22, borderRadius: 4, background: color(c.n), display: "flex", alignItems: "center", justifyContent: "center", fontSize: 10, color: c.n > 0 ? "#fff" : "#888" }}>
                    {c.n > 0 ? c.n : d}
                  </div>
                );
              })}
            </div>
          </div>
        ))}
      </div>
      <div style={{ display: "flex", justifyContent: "flex-end", alignItems: "center", gap: 5, marginTop: 12 }}>
        <Typography.Text type="secondary" style={{ fontSize: 11 }}>少</Typography.Text>
        <div style={{ width: 14, height: 14, borderRadius: 3, background: "#ebedf0" }} />
        <div style={{ width: 14, height: 14, borderRadius: 3, background: "rgba(21,101,192,.35)" }} />
        <div style={{ width: 14, height: 14, borderRadius: 3, background: "rgba(21,101,192,.6)" }} />
        <div style={{ width: 14, height: 14, borderRadius: 3, background: "rgba(21,101,192,.9)" }} />
        <Typography.Text type="secondary" style={{ fontSize: 11 }}>多</Typography.Text>
      </div>
    </div>
  );
}

export default function Home() {
  const router = useRouter();
  const [tasks, setTasks] = useState<Task[]>([]);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [loadErr, setLoadErr] = useState(false);
  const retryRef = useRef<ReturnType<typeof setTimeout>>(undefined);
  const retryCountRef = useRef(0);   // 连不上后端时的自动重试计数(上限5次)
  const [addOpen, setAddOpen] = useState(false);
  const [name, setName] = useState("");
  const [biz, setBiz] = useState("");
  const [link, setLink] = useState("");
  const [resolving, setResolving] = useState(false);
  const [saving, setSaving] = useState(false);

  const fileRef = useRef<HTMLInputElement>(null);
  const tasksRef = useRef<Task[]>([]);
  const collectAbortRef = useRef<AbortController | null>(null);  // 采集SSE控制器
  const collectLogRef = useRef<HTMLDivElement>(null);            // 日志区(自动滚动)
  const collectStartTsRef = useRef<number>(0);                  // 采集开始时间戳(毫秒)
  const [importing, setImporting] = useState(false);
  const [importingPct, setImportingPct] = useState(0);
  const [dragOver, setDragOver] = useState(false);
  const [failedRows, setFailedRows] = useState<{ name: string }[]>([]);
  const [sbWidth, setSbWidth] = useState(6);
  const [selectedKeys, setSelectedKeys] = useState<React.Key[]>([]);
  const [query, setQuery] = useState("");
  const [calOpen, setCalOpen] = useState(false);
  const [calData, setCalData] = useState<CalData | null>(null);
  // 采集弹窗: 确认阶段 / 进行中阶段
  const [collectOpen, setCollectOpen] = useState(false);
  const [collectTask, setCollectTask] = useState<Task | null>(null);
  const [collectStarted, setCollectStarted] = useState(false);  // true=确认后进行中
  const [collectStartTime, setCollectStartTime] = useState<string>("");
  const [collectCount, setCollectCount] = useState(0);
  const [collectLogs, setCollectLogs] = useState<string[]>([]);
  const [queue, setQueue] = useState<Task[]>([]);   // 采集队列(采集选中/单条)
  const [queueIdx, setQueueIdx] = useState(0);      // 当前正在采集的队列下标
  const [collectDone, setCollectDone] = useState(false); // 全部采集完成(弹窗保留可关)
  const [collectStopped, setCollectStopped] = useState(false); // 已手动停止(按钮变关闭)
  const collectRunRef = useRef(false);              // 是否采集中(队列运行中)
  const [speed, setSpeed] = useState(0);
  // 评论采集统计(仅采集情况卡, 前端读日志)
  const [collectComments, setCollectComments] = useState(0);  // 已采集评论数
  const [collectCommentSpeed, setCollectCommentSpeed] = useState(0); // 条/分
  const [pointsOpen, setPointsOpen] = useState(false);
  const [scrollsOpen, setScrollsOpen] = useState(false);
  const [aiOpen, setAiOpen] = useState(false);
  // 点位/滚动完整性(共享hook, 有报红时采集按钮置灰+提示)
  const si = useSettingsIssues();
  // 是否打包版: NODE_ENV=production(Next构建期注入的公共环境变量)
  const isPackaged = process.env.NODE_ENV === "production";
  // 日期范围(采集用), null=全部(不限日期); 默认全部
  const [dateRange, setDateRange] = useState<[dayjs.Dayjs, dayjs.Dayjs] | null>(null);
  // 窗口分离(采集设置)
  const [cfgLoaded, setCfgLoaded] = useState(false);   // 采集配置localStorage加载完成
  const [windowSplit, setWindowSplit] = useState(true);
  // 采集指标开关
  const [capture4metrics, setCapture4metrics] = useState(false);
  const [captureRead, setCaptureRead] = useState(false);
  // 采集时保存HTML到本地(默认关)
  const [saveHtml, setSaveHtml] = useState(false);
  // 评论采集设置
  const [captureComments, setCaptureComments] = useState(false);   // 评论采集开关
  const [maxComments, setMaxComments] = useState<number | null>(null);   // 文章最大评论采集数(空=无限)
  const [maxLevel1, setMaxLevel1] = useState<number | null>(null);      // 一级评论数(空=无限)
  const [maxLevel2, setMaxLevel2] = useState<number | null>(0);               // 每级二级评论采集数(默认0, 空=无限)
  // 保存HTML根目录(存储路径, 空=默认 <数据目录>/article_data)
  const [saveDir, setSaveDir] = useState("");

  // 采集配置记忆: localStorage 存储(窗口分离/4指标/阅读数/时间范围)
  useEffect(() => {
    try {
      const saved = localStorage.getItem("collectConfig");
      if (saved) {
        const d = JSON.parse(saved);
        if (typeof d.window_split === "boolean") setWindowSplit(d.window_split);
        if (typeof d.capture_4metrics === "boolean") setCapture4metrics(d.capture_4metrics);
        if (typeof d.capture_read === "boolean") setCaptureRead(d.capture_read);
        if (typeof d.save_html === "boolean") setSaveHtml(d.save_html);
        // 存储路径: 旧默认 D:/article_data 视为未设置(改用新默认 <数据目录>/article_data)
        if (typeof d.save_dir === "string" && d.save_dir && d.save_dir !== "D:/article_data") setSaveDir(d.save_dir);
        if (typeof d.capture_comments === "boolean") setCaptureComments(d.capture_comments);
        if ("max_comments" in d) setMaxComments(d.max_comments);
        if ("max_level1" in d) setMaxLevel1(d.max_level1);
        if ("max_level2" in d) setMaxLevel2(d.max_level2);
        if (d.date_start && d.date_end) {
          setDateRange([dayjs(d.date_start), dayjs(d.date_end)]);
        }
      }
    } catch { /* 忽略损坏数据 */ }
    setCfgLoaded(true);
  }, []);

  // 保存采集配置到 localStorage(加载完成后生效, 避免初始默认覆盖记忆)
  useEffect(() => {
    if (!cfgLoaded) return;
    try {
      localStorage.setItem("collectConfig", JSON.stringify({
        window_split: windowSplit,
        capture_4metrics: capture4metrics,
        capture_read: captureRead,
        save_html: saveHtml,
        save_dir: saveDir,
        capture_comments: captureComments,
        max_comments: maxComments,
        max_level1: maxLevel1,
        max_level2: maxLevel2,
        date_start: dateRange ? dateRange[0].format("YYYY-MM-DD") : "",
        date_end: dateRange ? dateRange[1].format("YYYY-MM-DD") : "",
      }));
    } catch { /* 忽略写入失败 */ }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [windowSplit, capture4metrics, captureRead, saveHtml, saveDir, captureComments, maxComments, maxLevel1, maxLevel2, dateRange]);

  useEffect(() => {
    const probe = document.createElement("div");
    probe.style.cssText = "width:50px;height:50px;overflow:scroll;visibility:hidden;position:absolute;";
    document.body.appendChild(probe);
    setSbWidth(probe.offsetWidth - probe.clientWidth);
    probe.remove();
  }, []);

  async function load() {
    setLoading(true);
    clearTimeout(retryRef.current);
    try {
      const ctrl = new AbortController();
      const to = setTimeout(() => ctrl.abort(), 6000);
      const r = await fetch(`${API}?page=${page}&page_size=${pageSize}&q=${encodeURIComponent(query.trim())}`, { signal: ctrl.signal });
      clearTimeout(to);
      const d = await r.json();
      if (Array.isArray(d)) { setTasks(d); setTotal(d.length); }
      else { setTasks(d.items || []); setTotal(d.total || 0); }
      setLoadErr(false);
      retryCountRef.current = 0;   // 连接成功, 重置重试计数
    }
    catch {
      retryCountRef.current += 1;
      if (retryCountRef.current <= 5) {
        message.error(`无法连接后端(8000), 正在自动重试(${retryCountRef.current}/5)`);
      } else {
        message.error("后端连接失败: 请确认后端已启动、8000端口未被占用, 再点右上角刷新");
      }
      setLoadErr(true);
      if (retryCountRef.current <= 5) retryRef.current = setTimeout(() => load(), 3000);
    }
    finally { setLoading(false); }
  }
  useEffect(() => { load(); }, [page, pageSize, query]);
  useEffect(() => () => clearTimeout(retryRef.current), []);
  // (校验由 useSettingsIssues hook 处理)
  // 采集弹窗显示=隐藏任务栏, 关闭=恢复
  useEffect(() => { if (collectOpen) hideTaskbar(); else showTaskbar(); /* eslint-disable-next-line */ }, [collectOpen]);
  // AI模型报红: 强制关闭4指标/评论采集
  useEffect(() => {
    if (si.ai.length > 0) { setCapture4metrics(false); setCaptureComments(false); }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [si.ai]);
  // 初始自动计算每页条数
  useEffect(() => { setPageSize(calcPageSize()); }, []);

  async function resolve() {
    if (!link.trim()) { message.warning("请先填文章链接"); return; }
    setResolving(true); setName(""); setBiz("");
    try {
      const r = await fetch(`${RESOLVE}?link=${encodeURIComponent(link.trim())}`);
      if (!r.ok) throw 0;
      const d = await r.json();
      setName(d.name || ""); setBiz(d.biz || "");
      message.success("识别成功");
    } catch { message.error("识别失败，请检查链接"); }
    finally { setResolving(false); }
  }

  async function save() {
    if (!name.trim()) { message.warning("请填写公众号名称"); return; }
    if (!biz.trim()) { message.warning("请填写biz代码"); return; }
    setSaving(true);
    try {
      const r = await fetch(API, { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: name.trim(), biz: biz.trim(), status: "pending" }) });
      if (!r.ok) {
        let err = "保存失败";
        try { const e = await r.json(); err = e.detail || err; } catch {}
        message.error(err); return;
      }
      message.success("已保存"); setAddOpen(false); setName(""); setBiz(""); setLink(""); load();
    } catch { message.error("保存失败"); }
    finally { setSaving(false); }
  }

  async function importFile(f: File) {
    setImporting(true); setImportingPct(0); setFailedRows([]);
    const fd = new FormData();
    fd.append("file", f);
    let total = 0, addedCount = 0;
    let fails: { name: string }[] = [];
    try {
      const r = await fetch(`${API}/import`, { method: "POST", body: fd });
      if (!r.body) throw 0;
      const reader = r.body.getReader();
      const dec = new TextDecoder();
      let buf = "";
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += dec.decode(value, { stream: true });
        let idx;
        while ((idx = buf.indexOf("\n\n")) !== -1) {
          const block = buf.slice(0, idx); buf = buf.slice(idx + 2);
          const dm = block.match(/^data: (.+)$/m);
          if (!dm) continue;
          const d = JSON.parse(dm[1]);
          if (d.total) total = d.total;
          if (d.done !== undefined) {
            setImportingPct(Math.round((d.done / (total || 1)) * 100));
            if (d.ok) addedCount++; else fails.push({ name: d.name || "(未知)" });
          }
        }
      }
    } catch { setImporting(false); message.error("导入失败"); return; }
    setImportingPct(100);
    setFailedRows(fails);
    load();
    if (fails.length > 0) {
      message.warning(`导入完成: 新增${addedCount}, 失败${fails.length}`);
    } else {
      setTimeout(() => { setImporting(false); message.success(`导入完成: 新增${addedCount}`); }, 1000);
    }
  }
  function onPick(e: React.ChangeEvent<HTMLInputElement>) {
    const f = e.target.files?.[0];
    if (f) importFile(f);
    e.target.value = "";
  }

  async function reset(row: Task) {
    await fetch(`${API}/${row.id}`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ status: "pending" }) });
    load();
  }
  async function del(row: Task) {
    Modal.confirm({ title: "删除确认", content: `确定删除「${row.name}」？`, okText: "确认", cancelText: "取消",
      onOk: async () => { await fetch(`${API}/${row.id}`, { method: "DELETE" }); load(); } });
  }
  function collectSelected() {
    if (selectedKeys.length === 0) { Modal.warning({ title: "未选择", content: "请在左侧勾选要采集的公众号", okText: "知道了" }); return; }
    const rows = tasks.filter((t) => selectedKeys.includes(t.id));
    if (rows.length === 0) return;
    // 加入采集队列(批量)
    setQueue(rows);
    setQueueIdx(0);
    setCollectTask(rows[0]);
    setCollectStarted(false);
    setCollectDone(false);
    setCollectCount(0);
    setCollectComments(0); setCollectCommentSpeed(0);
    setCollectLogs([]);
    setCollectOpen(true);
  }
  function collectRow(row: Task) {
    // 打开确认弹窗: 只加入一个采集任务
    setQueue([row]);
    setQueueIdx(0);
    setCollectTask(row);
    setCollectStarted(false);
    setCollectDone(false);
    setCollectCount(0);
    setCollectComments(0); setCollectCommentSpeed(0);
    setCollectLogs([]);
    setCollectOpen(true);
  }
  // 确认采集: 确认设置后按队列启动采集(每个任务完整走流程)
  function confirmCollect() {
    if (queue.length === 0) return;
    setCollectStopped(false);
    setCollectStarted(true);
    runOne(0);
  }
  // 采集队列第 idx 个: 拼接链接 -> POST 后端启动(完整采集流程) -> SSE 接收
  // 任务完成后自动执行下一个; 全部完成关闭弹窗
  function runOne(idx: number) {
    const task = queue[idx];
    if (!task) { setQueueIdx(queue.length); message.success("全部采集完成"); setCollectDone(true); return; }
    setCollectDone(false);
    setQueueIdx(idx);
    setCollectTask(task);
    const link = `https://mp.weixin.qq.com/mp/profile_ext?action=home&__biz=${encodeURIComponent(task.biz || "")}`;
    if (idx === 0) {
      setCollectStartTime(new Date().toLocaleTimeString("zh-CN", { hour12: false }));
      collectStartTsRef.current = Date.now();
      setSpeed(0);
      setCollectCount(0);
      setCollectComments(0); setCollectCommentSpeed(0);
      setCollectLogs([`开始采集「${task.name || ""}」`]);
    } else {
      setCollectLogs((p) => [...p, `--- 开始采集「${task.name || ""}」(${idx + 1}/${queue.length}) ---`]);
    }

    const controller = new AbortController();
    collectAbortRef.current = controller;
    const payload = {
      collect_type: COLLECT_TYPE.ACCOUNT_CLICK,   // 触发类型: 公众号点击采集
      name: task.name || "",
      biz: task.biz || "",
      link,
      date_start: dateRange ? dateRange[0].format("YYYY-MM-DD") : "",
      date_end: dateRange ? dateRange[1].format("YYYY-MM-DD") : "",
      window_split: windowSplit,
      capture_4metrics: capture4metrics,
      capture_read: captureRead,
      save_html: saveHtml,
      save_dir: saveDir,
      max_comments: captureComments ? maxComments : 0,
      max_level1: captureComments ? maxLevel1 : 0,
      max_level2: captureComments ? maxLevel2 : 0,
    };

    (async () => {
      try {
        const resp = await fetch(COLLECT, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
          signal: controller.signal,
        });
        if (!resp.ok || !resp.body) { throw new Error("采集接口失败"); }
        let finished = false;
        const reader = resp.body.getReader();
        const dec = new TextDecoder();
        let buf = "";
        for (;;) {
          const { done, value } = await reader.read();
          if (done) break;
          buf += dec.decode(value, { stream: true });
          let i2;
          while ((i2 = buf.indexOf("\n\n")) !== -1) {
            const block = buf.slice(0, i2); buf = buf.slice(i2 + 2);
            if (!block.startsWith("data: ")) continue;
            try {
              const d = JSON.parse(block.slice(6));
              if (d.type === "log" && d.msg) {
                setCollectLogs((p) => [...p, d.msg]);
                if (d.msg.includes("禁用鼠标和键盘")) message.warning("⚠️ 采集期间禁用鼠标和键盘，按 ESC 可停止");
                // 评论采集统计: 日志 '写入N条' 累加(速度由effect计算)
                if (d.msg.includes("写入") && d.msg.includes("评论#")) {
                  const m = d.msg.match(/写入(\d+)条/);
                  if (m) setCollectComments((c) => c + Number(m[1]));
                }
                // 前端统计: 复制到链接即算获取到文章
                if (d.msg.includes("已复制链接") || d.msg.includes("已复制链接:")) {
                  setCollectCount((c) => c + 1);
                }
              } else if (d.type === "task" && d.done !== undefined) {
                if (d.done >= 1) setCollectCount(d.done);
              } else if (d.type === "done") {
                finished = true;
                setCollectLogs((p) => [...p,
                  d.ok ? "✅ 采集流程结束" : `❌ 采集失败: ${d.reason || ""}`]);
              }            } catch { /* 忽略坏帧 */ }
          }
        }
        setCollectLogs((p) => [...p, "⏹ 采集连接已断开"]);
        // 队列: 本任务结束 -> 下一个(仍完整流程)
        if (finished && collectAbortRef.current === controller) {
          runOne(idx + 1);
        }
      } catch (e: unknown) {
        if ((e as Error)?.name !== "AbortError") {
          setCollectLogs((p) => [...p, `❌ 采集接口异常: ${(e as Error)?.message || e}`]);
        }
      }
    })();
  }
  // 停止采集: 通知后端中止 + 断开SSE, 按钮变关闭
  function stopCollect() {
    fetch("http://127.0.0.1:8000/api/collect/stop", { method: "POST" }).catch(() => {});
    collectAbortRef.current?.abort();
    setCollectStopped(true);
  }
  // 关闭采集弹窗: 收起界面 + 刷新公众号列表(文章统计更新)
  function closeCollect() {
    setCollectOpen(false);
    load();
  }
  // 导出公众号列表为 xlsx
  async function exportExcel() {
    message.info("正在导出全部数据...");
    try {
      const r = await fetch(`${API}?q=${encodeURIComponent(query.trim())}`);   // page=0 返回全部
      const d = await r.json();
      const all = Array.isArray(d) ? d : (d.items || []);
      if (all.length === 0) { message.info("没有可导出的数据"); return; }
      const rows = all.map((t: Task) => ({
        "ID": t.id, "公众号名称": t.name, "biz": t.biz || "",
        "文章数": t.collected_count ?? 0, "状态": t.status || "", "备注": t.remark || "",
      }));
      const ws = XLSX.utils.json_to_sheet(rows);
      const wb = XLSX.utils.book_new();
      XLSX.utils.book_append_sheet(wb, ws, "公众号");
      XLSX.writeFile(wb, `公众号列表.xlsx`);
    } catch { message.error("导出失败"); }
  }
  // 打开下载数据文件夹(D:/article_data)
  async function openDownloads() {
    try {
      const d = await (await fetch("http://127.0.0.1:8000/api/settings/open-downloads", { method: "POST" })).json();
      if (!d.ok) message.error(d.error || "打开失败");
    } catch { message.error("无法连接后端"); }
  }
  // 选择存储路径(保存HTML根目录): 弹系统文件夹选择器(从当前路径打开)
  async function pickSaveDir() {
    try {
      const d = await (await fetch("http://127.0.0.1:8000/api/settings/pick-dir?current=" + encodeURIComponent(saveDir), { method: "POST" })).json();
      if (d.dir) setSaveDir(d.dir);
    } catch { message.error("无法连接后端"); }
  }


  const [calMonthKey, setCalMonthKey] = useState<string>("");
  async function loadCalendar(id: number, monthKey: string) {
    const [y, m] = monthKey.split("-").map(Number);
    try {
      const r = await fetch(`${API}/calendar/${id}?year=${y}&month=${m}`);
      const d = await r.json();
      setCalData(d);
      setCalMonthKey(monthKey);   // 同步显示值, 触发3个月历刷新
    } catch { message.error("获取日历失败"); }
  }
  async function openCalendar(row: Task) {
    const now = new Date();
    const mk = `${now.getFullYear()}-${now.getMonth() + 1}`;
    setCalMonthKey(mk);
    await loadCalendar(row.id, mk);
    setCalOpen(true);
  }
  // 视觉移动(hover时实时调用, 不保存)
  function moveOrder(dragId: number, overId: number) {
    const next = [...tasksRef.current];
    const oldIndex = next.findIndex((t) => t.id === dragId);
    const newIndex = next.findIndex((t) => t.id === overId);
    if (oldIndex < 0 || newIndex < 0 || oldIndex === newIndex) return;
    const [moved] = next.splice(oldIndex, 1);
    next.splice(newIndex, 0, moved);
    tasksRef.current = next;
    setTasks(next);
  }
  // 保存最终顺序(拖拽结束调用)
  function saveOrder() {
    const ids = tasksRef.current.map((t) => t.id);
    setTimeout(() => {
      fetch(`${API}/sort`, { method: "PUT", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ids }) }).catch(() => {});
    }, 0);
  }
  // 每个数据行: useDrag + useDrop 实现拖动排序 (筛选已后端化, shown=全部tasks)
  const shown = tasks;
  const DndRow = useMemo(() => {
    return function DndRow({ children, "data-row-key": rk, ...props }: React.HTMLAttributes<HTMLTableRowElement> & { "data-row-key": string }) {
      const [{ isDragging }, drag] = useDrag(() => ({
        type: "ACCOUNT_ROW", item: { id: Number(rk) },
        collect: (m) => ({ isDragging: m.isDragging() }),
        end: () => { saveOrder(); },
      }), []);
      const [, drop] = useDrop(() => ({
        accept: "ACCOUNT_ROW",
        hover(item: { id: number }) {
          if (item.id !== Number(rk)) moveOrder(item.id, Number(rk));
        },
      }), []);
      return (
        <tr {...props} ref={(node) => { drag(drop(node)); }}
          onDragOver={(e) => {
            // 边缘自动滚动: 靠近表格可视区顶部/底部时滚动滚动容器
            const body = (e.currentTarget as HTMLElement).closest(".ant-table-body") as HTMLElement | null;
            if (!body) return;
            const r = body.getBoundingClientRect();
            const edge = 56;
            if (e.clientY < r.top + edge) body.scrollTop -= 16;
            else if (e.clientY > r.bottom - edge) body.scrollTop += 16;
          }}
          style={{ ...(props.style || {}), ...(isDragging ? { opacity: 0.35, background: "#f0f6ff" } : {}) }}>
          {children}
        </tr>
      );
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  // 保持 tasksRef 与 tasks 同步
  useEffect(() => { tasksRef.current = tasks; }, [tasks]);
  // 采集日志自动滚动到底部
  useEffect(() => {
    if (collectLogRef.current) {
      collectLogRef.current.scrollTop = collectLogRef.current.scrollHeight;
    }
  }, [collectLogs]);
  // 采集速度: 每获得一篇文章重算 篇/分
  useEffect(() => {
    if (collectCount > 0 && collectStartTsRef.current > 0) {
      const mins = (Date.now() - collectStartTsRef.current) / 60000;
      setSpeed(mins > 0 ? Math.round((collectCount / mins) * 10) / 10 : 0);
    }
  }, [collectCount]);
  // 评论采集速度: 每写入评论重算 条/分
  useEffect(() => {
    if (collectComments > 0 && collectStartTsRef.current > 0) {
      const mins = (Date.now() - collectStartTsRef.current) / 60000;
      setCollectCommentSpeed(mins > 0 ? Math.round((collectComments / mins) * 10) / 10 : 0);
    }
  }, [collectComments]);
  function toggleSelect(id: number, checked: boolean) {
    setSelectedKeys((prev) => checked ? [...prev, id] : prev.filter((k) => k !== id));
  }
  function toggleSelectAll(checked: boolean) {
    setSelectedKeys(checked ? shown.map((t) => t.id) : []);
  }
  function copyBiz(row: Task) {
    if (!row.biz) return;
    navigator.clipboard.writeText(row.biz);
    message.success("biz 已复制");
  }
  async function clearAll() {
    if (selectedKeys.length === 0) {
      Modal.warning({ title: "未选择", content: "请在左侧勾选要删除的公众号", okText: "知道了" });
      return;
    }
    Modal.confirm({ title: "删除选中", content: `确定删除选中的 ${selectedKeys.length} 个公众号？`, okText: "确认", cancelText: "取消",
      okButtonProps: { danger: true },
      onOk: async () => {
        for (const id of selectedKeys) { await fetch(`${API}/${String(id)}`, { method: "DELETE" }); }
        setSelectedKeys([]);
        load(); message.success("已删除选中项");
      } });
  }


  return (
      <div style={{ height: "100%", overflow: "hidden", display: "flex", flexDirection: "column", background: "#f5f6f8", padding: 0, gap: 12 }}>
      {/* 采集设置模块(在公众号列表上方) */}
      <div style={{ display: "flex", flexDirection: "column", gap: 10, background: "#fff", borderRadius: 14, boxShadow: "0 1px 3px rgba(0,0,0,.06)", padding: "16px 18px" }}>
        {/* 日期选择栏: 日期范围选择器 + 快捷按钮 */}
        <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
          <DatePicker.RangePicker
            value={dateRange}
            placeholder={["开始日期", "结束日期"]}
            onChange={(v) => { if (v && v[0] && v[1]) setDateRange([v[0], v[1]]); }}
            style={{ width: 260 }}
            allowClear={false}
          />
          <Button size="small" type={dateRange === null ? "primary" : "default"}
            onClick={() => setDateRange(null)}>全部</Button>
          <Button size="small" type={dateRange && dateRange[0].isSame(dateRange[1], "day") && dateRange[0].isSame(dayjs(), "day") ? "primary" : "default"}
            onClick={() => setDateRange([dayjs(), dayjs()])}>今天</Button>
          <Button size="small" onClick={() => setDateRange([dayjs().subtract(2, "day"), dayjs()])}>近3天</Button>
          <Button size="small" onClick={() => setDateRange([dayjs().subtract(6, "day"), dayjs()])}>近一周</Button>
          <Button size="small" onClick={() => setDateRange([dayjs().subtract(29, "day"), dayjs()])}>近一月</Button>
          <Button size="small" onClick={() => setDateRange([dayjs().subtract(364, "day"), dayjs()])}>近一年</Button>
        </div>
        {/* 采集开关行(第二行) */}
        <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap", minHeight: 32 }}>
          <Tooltip title="窗口分离: 独立出搜一搜窗口。搜索时打开搜一搜有两种形态: ①独立弹出搜一搜窗口 ②嵌入微信窗口内部; 本功能统一为第一种(独立窗口)方式。">
            <span style={{ display: "inline-flex", alignItems: "center", gap: 4, fontSize: 14, color: "#555" }}>
              窗口分离
              <QuestionCircleOutlined style={{ color: "#8b949e" }} />
            </span>
          </Tooltip>
          <Switch checked={windowSplit} onChange={setWindowSplit} />
          <Tooltip
            title={si.ai.length > 0 ? `AI模型未配置，4指标采集不可用:\n${si.ai.join("\n")}` : undefined}>
            <span style={{ display: "inline-flex", alignItems: "center", gap: 6, whiteSpace: "nowrap", marginLeft: 12 }}>
              <span style={{ fontSize: 14, color: si.ai.length > 0 ? "#ff4d4f" : "#555" }}>采集4指标</span>
              {si.ai.length > 0 && <ExclamationCircleOutlined style={{ color: "#ff4d4f" }} />}
              <Switch checked={capture4metrics} disabled={si.ai.length > 0} onChange={setCapture4metrics} />
            </span>
          </Tooltip>
          <span style={{ marginLeft: 12, fontSize: 14, color: "#555" }}>采集阅读数</span>
          <Switch checked={captureRead} onChange={setCaptureRead} />
          <span style={{ marginLeft: 12, fontSize: 14, color: "#555" }}>保存Html</span>
          <Switch checked={saveHtml} onChange={setSaveHtml} />
          <Tooltip
            title={si.ai.length > 0 ? `AI模型未配置，评论采集不可用:\n${si.ai.join("\n")}` : undefined}>
            <span style={{ display: "inline-flex", alignItems: "center", gap: 6, whiteSpace: "nowrap", marginLeft: 12 }}>
              <span style={{ fontSize: 14, color: si.ai.length > 0 ? "#ff4d4f" : "#555" }}>评论采集</span>
              {si.ai.length > 0 && <ExclamationCircleOutlined style={{ color: "#ff4d4f" }} />}
              <Switch checked={captureComments} disabled={si.ai.length > 0} onChange={setCaptureComments} />
            </span>
          </Tooltip>
        </div>
        {/* 评论采集设置行(开关开时显示) */}
        {captureComments && (
          <div style={{ display: "flex", gap: 14, alignItems: "center", flexWrap: "wrap", minHeight: 32 }}>
            <span style={{ fontSize: 13, color: "#555" }}>文章评论数</span>
            <InputNumber min={0} placeholder="无限" value={maxComments ?? null}
              onChange={(v) => setMaxComments(typeof v === "number" && v >= 0 ? v : null)} style={{ width: 90 }} />
            <span style={{ fontSize: 13, color: "#555" }}>一级评论数</span>
            <InputNumber min={0} placeholder="无限" value={maxLevel1 ?? null}
              onChange={(v) => setMaxLevel1(typeof v === "number" && v >= 0 ? v : null)} style={{ width: 90 }} />
            <span style={{ fontSize: 13, color: "#555" }}>每级二级评论数</span>
            <InputNumber min={0} placeholder="无限" value={maxLevel2}
              onChange={(v) => setMaxLevel2(typeof v === "number" && v >= 0 ? v : null)} style={{ width: 90 }} />
          </div>
        )}
        {/* 设置按钮行(第三行) */}
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <Tooltip
            title={si.points.length > 0 ? "点位数据不完整，请点此补全" : undefined}
            placement="bottom">
            <Button danger={si.points.length > 0}
              icon={si.points.length > 0 ? <ExclamationCircleOutlined /> : <ProfileOutlined />}
              onClick={() => setPointsOpen(true)}>点位设置</Button>
          </Tooltip>
          <Tooltip
            title={si.scrolls.length > 0 ? "滚动数据不完整，请点此补全" : undefined}
            placement="bottom">
            <Button danger={si.scrolls.length > 0}
              icon={si.scrolls.length > 0 ? <ExclamationCircleOutlined /> : <SwapOutlined />}
              onClick={() => setScrollsOpen(true)}>滚动设置</Button>
          </Tooltip>
          <Tooltip
            title={si.ai.length > 0 ? `AI模型设置不完整，需配置后才能正常使用:\n${si.ai.join("\n")}` : undefined}
            placement="bottom">
            <Button danger={si.ai.length > 0}
              icon={si.ai.length > 0 ? <ExclamationCircleOutlined /> : <RobotOutlined />}
              onClick={() => setAiOpen(true)}>AI模型</Button>
          </Tooltip>
          <Button onClick={pickSaveDir}>存储路径: {saveDir || "默认(data/article_data)"}</Button>
        </div>
      </div>
      <PointsDialog compact={isPackaged} open={pointsOpen} onClose={() => { setPointsOpen(false); si.refresh(); }} />
      <AiDialog open={aiOpen} onClose={() => { setAiOpen(false); si.refresh(); }} />
      <ScrollsDialog compact={isPackaged} open={scrollsOpen} onClose={() => { setScrollsOpen(false); si.refresh(); }} />
      <div className="dropzone"
           onDragOver={(e) => { e.preventDefault(); if (Array.from(e.dataTransfer.types || []).includes("Files")) setDragOver(true); }}
           onDragLeave={() => setDragOver(false)}
           onDrop={(e) => { e.preventDefault(); setDragOver(false); if (Array.from(e.dataTransfer.types || []).includes("Files")) { const f = e.dataTransfer.files?.[0]; if (f) importFile(f); } }}
           style={{ flex: 1, minHeight: 0, overflow: "hidden", display: "flex", flexDirection: "column", background: dragOver ? "#eef4ff" : "#fff", borderRadius: 14, boxShadow: "0 1px 3px rgba(0,0,0,.06)", padding: "16px 18px", transition: ".2s", border: dragOver ? "2px dashed #1565c0" : "2px solid transparent" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 12 }}>
          <Tooltip
            title={si.points.length + si.scrolls.length > 0 ? "点位/滚动设置有残缺，需补全后才能采集" : undefined}>
            <Button type="primary" disabled={si.points.length + si.scrolls.length > 0}
              icon={si.points.length + si.scrolls.length > 0 ? <ExclamationCircleOutlined /> : <InboxOutlined />}
              onClick={collectSelected} style={{ flexShrink: 0 }}>采集选中</Button>
          </Tooltip>
          <Input allowClear prefix={<SearchOutlined style={{ color: "#bfc7cf" }} />}
            placeholder="输入公众号名称或biz代码查询"
            value={query} onChange={(e) => setQuery(e.target.value)}
            style={{ flex: "1 1 auto", minWidth: 80 }} />
          <div style={{ flex: 1 }} />
          <Button color="primary" variant="outlined" icon={<PlusOutlined />} onClick={() => setAddOpen(true)} style={{ flexShrink: 0 }}>新增</Button>
          <Button icon={<ImportOutlined />} onClick={() => fileRef.current?.click()} style={{ flexShrink: 0 }}>文件导入</Button>
          <Button danger icon={<DeleteOutlined />} onClick={clearAll} style={{ flexShrink: 0 }}>删除选中</Button>
          <input ref={fileRef} type="file" accept=".csv,.xlsx,.xls" style={{ display: "none" }} onChange={onPick} />
        </div>

            {loading ? (
            <div style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center" }}>
              <Space vertical size={10} style={{ alignItems: "center" }}>
                <Spin size="large" />
                <Typography.Text type="secondary" style={{ fontSize: 13 }}>正在加载…</Typography.Text>
              </Space>
            </div>
            ) : shown.length > 0 ? (
            <div style={{ flex: 1, minHeight: 0, overflow: "auto" }}>
            <DndProvider backend={HTML5Backend}>
            <Table className="home-table" rowKey="id" dataSource={shown} loading={loading} pagination={false} bordered sticky scroll={{ x: true }}
              locale={{ emptyText: <Empty description={loadErr ? "加载失败，请重试" : "请添加一个公众号"} image={Empty.PRESENTED_IMAGE_SIMPLE} /> }}
              components={{ body: { row: DndRow } }}
              columns={[
                {
                  title: "", dataIndex: "drag", width: 40, align: "center",
                  render: () => <HolderOutlined style={{ color: "#bfc7cf", cursor: "grab" }} />,
                },
                {
                  title: <Checkbox indeterminate={selectedKeys.length > 0 && selectedKeys.length < shown.length}
                    checked={selectedKeys.length === shown.length && shown.length > 0}
                    onChange={(e) => toggleSelectAll(e.target.checked)} />,
                  dataIndex: "select", width: 40, align: "center",
                  render: (_: unknown, r: Task) => (
                    <Checkbox checked={selectedKeys.includes(r.id)}
                      onChange={(e) => toggleSelect(r.id, e.target.checked)} />
                  ),
                },
                {
                  title: "公众号名称", dataIndex: "name",
                  render: (_: unknown, r: Task) => (
                    <Tooltip
                      title={r.biz ? (
                        <span>
                          <code style={{ marginRight: 8 }}>{r.biz}</code>
                          <a onClick={() => copyBiz(r)} style={{ color: "#69b1ff" }}><CopyOutlined /></a>
                        </span>
                      ) : "无 biz"}
                    >
                      <span style={{ cursor: "default" }}>{r.name}</span>
                    </Tooltip>
                  ),
                },

                {
                  title: "文章采集统计", dataIndex: "op2", align: "center",
                  render: (_: unknown, row: Task) => (
                    <Space>
                      <span>{row.collected_count ?? 0}</span>
                      <Button size="small" type="link" icon={<ProfileOutlined />} onClick={() => router.push(`/articles?biz=${encodeURIComponent(row.biz || "")}&name=${encodeURIComponent(row.name || "")}`)}>查看</Button>
                    </Space>
                  ),
                },
                {
                  title: "操作", dataIndex: "op", align: "center",
                  render: (_: unknown, row: Task) => (
                    <Space>
                      <Tooltip
                        title={si.points.length + si.scrolls.length > 0 ? "点位/滚动设置有残缺，需补全后才能采集" : undefined}>
                        <Button size="small" type="link" disabled={si.points.length + si.scrolls.length > 0}
                          icon={si.points.length + si.scrolls.length > 0 ? <ExclamationCircleOutlined /> : <InboxOutlined />}
                          onClick={() => collectRow(row)}>采集</Button>
                      </Tooltip>
                      <Button size="small" type="link" danger icon={<DeleteOutlined />} onClick={() => del(row)}>删除</Button>
                    </Space>
                  ),
                },
              ]}
            />
            </DndProvider>
            </div>
            ) : (
            <div style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center", padding: "40px 0" }}>
              <Empty description={loadErr ? "加载失败，请重试" : "请添加一个公众号"} image={Empty.PRESENTED_IMAGE_SIMPLE} />
            </div>
            )}

        <div style={{ display: "flex", flexDirection: "column", gap: 6, paddingTop: 10, flexShrink: 0 }}>
          <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
            <Button size="small" color="primary" variant="outlined" icon={<UnorderedListOutlined />} onClick={() => router.push("/articles?biz=all&name=全部文章")}>查看全部文章</Button>
            <Button size="small" icon={<FolderOpenOutlined />} onClick={openDownloads}>打开下载数据</Button>
            <Button size="small" icon={<FileExcelOutlined />} onClick={exportExcel}>导出表格</Button>
          </div>
          <div style={{ display: "flex", justifyContent: "flex-end" }}>
            <PaginationBar total={total} page={page} pageSize={pageSize}
              onChange={(p, ps) => { setPage(p); if (ps !== pageSize) setPageSize(ps); }} />
          </div>
        </div>
      </div>

      {/* 导入进度/失败弹窗 */}
      <Modal title={failedRows.length ? "导入结果" : "正在导入"} open={importing}
        footer={failedRows.length ? <Button type="primary" onClick={() => setImporting(false)}>关闭</Button> : null}
        closable={failedRows.length > 0} onCancel={() => setImporting(false)} width={420}>
        {failedRows.length ? (
          <div>
            <Typography.Paragraph strong style={{ color: "#c62828" }}>有 {failedRows.length} 行导入失败（无法识别公众号），需手动处理：</Typography.Paragraph>
            <Table size="small" rowKey={(r) => r.name} pagination={false} dataSource={failedRows}
              columns={[{ title: "失败项", dataIndex: "name" }]} />
          </div>
        ) : (
          <div style={{ textAlign: "center", padding: "8px 0" }}>
            <Typography.Title level={5} style={{ marginTop: 0 }}>导入进度</Typography.Title>
            <Progress percent={importingPct} status={importingPct >= 100 ? "success" : "active"} />
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>解析文件并识别公众号名称…</Typography.Text>
          </div>
        )}
      </Modal>

      {/* 采集日历弹窗 */}
      <Modal title={calData ? `${calData.name} · 采集日历` : "采集日历"} open={calOpen}
        footer={null} onCancel={() => setCalOpen(false)} width={760} style={{ maxHeight: "80vh", overflow: "auto" }}>
        {calData && <CollectCalendar daily={calData.daily} monthKey={calMonthKey} onMonthChange={(m) => loadCalendar(calData.id, m)} />}
      </Modal>

      {/* 采集弹窗: 确认阶段 -> 采集进行中(停止由后端ESC监听) */}
      <Modal
        open={collectOpen}
        title={collectStarted ? `正在采集「${collectTask?.name || ""}」 (${queueIdx}/${queue.length})` : queue.length > 1 ? `确认采集设置 (共 ${queue.length} 个)` : "确认采集设置"}
        onCancel={() => {
          if (collectStarted) { stopCollect(); return; }
          closeCollect();
        }}
        footer={collectStarted ? (
          collectStopped || collectDone ? (
            <Button type="primary" onClick={closeCollect}>关闭</Button>
          ) : (
            <Button danger onClick={stopCollect}>按 ESC 停止</Button>
          )
        ) : (
          <>
            <Button onClick={closeCollect}>取消</Button>
            <Button type="primary" onClick={confirmCollect}>确认</Button>
          </>
        )}
        width={collectStarted ? 920 : 560}
      >
        {/* 进行中: 采集设置 + 采集情况 左右两卡片 */}
        {collectStarted ? (
          <div style={{ display: "flex", gap: 12 }}>
            {/* 左: 采集设置 */}
            <div style={{ flex: 1, background: "#fff", border: "1px solid #eee", borderRadius: 8, padding: "4px 0", maxHeight: 220, display: "flex", flexDirection: "column" }}>
              <div style={{ padding: "7px 14px", fontSize: 13, fontWeight: 600, color: "#333", borderBottom: "1px solid #f0f0f0", flexShrink: 0 }}>采集设置</div>
              <div style={{ overflow: "auto", flex: 1, minHeight: 0 }}>
              {[
                { label: "时间范围", value: dateRange ? `${dateRange[0].format("YYYY-MM-DD")} ~ ${dateRange[1].format("YYYY-MM-DD")}` : "全部" },
                { label: "窗口分离", value: windowSplit ? "开" : "关" },
                { label: "采集4指标", value: capture4metrics ? "开" : "关" },
                { label: "采集阅读数", value: captureRead ? "开" : "关" },
                { label: "保存Html", value: saveHtml ? "开" : "关" },
                { label: "评论采集", value: captureComments ? "开" : "关" },
                { label: "文章评论数", value: captureComments ? (maxComments == null ? "无限" : String(maxComments)) : "0" },
                { label: "一级评论数", value: captureComments ? (maxLevel1 == null ? "无限" : String(maxLevel1)) : "0" },
                { label: "每级二级评论数", value: captureComments ? (maxLevel2 == null ? "无限" : String(maxLevel2)) : "0" },
              ].map((row) => (
                <div key={row.label} style={{ display: "flex", alignItems: "center", padding: "7px 14px", fontSize: 13 }}>
                  <span style={{ width: 110, color: "#888", whiteSpace: "nowrap" }}>{row.label}</span>
                  <span style={{ color: "#333", fontWeight: 500 }}>{row.value}</span>
                </div>
              ))}
              </div>
            </div>
            {/* 右: 采集情况 */}
            <div style={{ flex: 1, background: "#fff", border: "1px solid #eee", borderRadius: 8, padding: "4px 0", maxHeight: 220, display: "flex", flexDirection: "column" }}>
              <div style={{ padding: "7px 14px", fontSize: 13, fontWeight: 600, color: "#333", borderBottom: "1px solid #f0f0f0", flexShrink: 0 }}>采集情况</div>
              <div style={{ overflow: "auto", flex: 1, minHeight: 0, display: "flex", flexDirection: "column", gap: 10, padding: "10px 14px" }}>
                <div>开始时间: <span style={{ color: "#333" }}>{collectStartTime}</span></div>
                <div>已采集文章: <span style={{ color: "#333", fontWeight: 600 }}>{collectCount} 篇</span></div>
                <div>采集速度: <span style={{ color: "#333" }}>{speed} 篇/分</span></div>
                {captureComments && (
                  <>
                    <div>已采集评论: <span style={{ color: "#333", fontWeight: 600 }}>{collectComments} 条</span></div>
                    <div>评论速度: <span style={{ color: "#333" }}>{collectCommentSpeed} 条/分</span></div>
                  </>
                )}
              </div>
            </div>
          </div>
        ) : (
          // 确认阶段: 单一设置卡片
          <div style={{ background: "#fff", border: "1px solid #eee", borderRadius: 8, padding: "4px 0", marginBottom: 12 }}>
            {[
              { label: "时间范围", value: dateRange ? `${dateRange[0].format("YYYY-MM-DD")} ~ ${dateRange[1].format("YYYY-MM-DD")}` : "全部" },
              { label: "窗口分离", value: windowSplit ? "开" : "关" },
              { label: "采集4指标", value: capture4metrics ? "开" : "关" },
              { label: "采集阅读数", value: captureRead ? "开" : "关" },
              { label: "保存Html", value: saveHtml ? "开" : "关" },
              { label: "评论采集", value: captureComments ? "开" : "关" },
              { label: "文章评论数", value: captureComments ? (maxComments == null ? "无限" : String(maxComments)) : "0" },
              { label: "一级评论数", value: captureComments ? (maxLevel1 == null ? "无限" : String(maxLevel1)) : "0" },
              { label: "每级二级评论数", value: captureComments ? (maxLevel2 == null ? "无限" : String(maxLevel2)) : "0" },
            ].map((row) => (
              <div key={row.label} style={{ display: "flex", alignItems: "center", padding: "7px 14px", fontSize: 13 }}>
                <span style={{ width: 110, color: "#888", whiteSpace: "nowrap" }}>{row.label}</span>
                <span style={{ color: "#333", fontWeight: 500 }}>{row.value}</span>
              </div>
            ))}
          </div>
        )}

        {/* 日志区(仅进行中显示) */}
        {collectStarted && (
          <div style={{ background: "#fafafa", border: "1px solid #eee", borderRadius: 8, padding: "10px 12px", marginTop: 12 }}>
            <Typography.Text strong style={{ fontSize: 13 }}>日志</Typography.Text>
            <div ref={collectLogRef} style={{
              marginTop: 8, height: 220, overflow: "auto",
              background: "#1e1e1e", borderRadius: 6, padding: 8,
              fontFamily: "Consolas, monospace", fontSize: 12, color: "#d4d4d4", whiteSpace: "pre-wrap",
            }}>
              {collectLogs.length === 0 ? (
                <span style={{ color: "#888" }}>(暂无日志)</span>
              ) : (
                collectLogs.map((l, i) => {
                  // [async:任务名] 异步统一青色; [step]橙 [ok]绿 [fail]红 [warn]黄
                  const mAsync = l.match(/^\[async:([^\]]+)\]\s?([\s\S]*)/);
                  const m = mAsync || l.match(/^\[(step|ok|fail|warn)\]\s?([\s\S]*)/);
                  let text = l, color: string | undefined;
                  if (mAsync) { color = "#36cfc9"; text = `[${mAsync[1]}] ${mAsync[2]}`; }
                  else if (m) {
                    color = { step: "#ffa940", ok: "#73d13d", fail: "#ff4d4f", warn: "#ffc53d" }[m[1]];
                    text = m[2];
                  }
                  return <div key={i} style={color ? { color } : undefined}>{text}</div>;
                })
              )}
            </div>
          </div>
        )}
      </Modal>

      {/* 新增弹窗 */}
      <Modal title="新增公众号" open={addOpen} onOk={save} okText="保存" confirmLoading={saving}
        onCancel={() => setAddOpen(false)} cancelText="取消">
        <Space vertical style={{ width: "100%" }} size="middle">
          <Space vertical style={{ width: "100%" }}>
            <Input placeholder="公众号名称" value={name} onChange={(e) => setName(e.target.value)} />
            <Input placeholder="biz 代码" value={biz} onChange={(e) => setBiz(e.target.value)} />
          </Space>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>或通过公众号文章链接自动获取：</Typography.Text>
          <Space.Compact style={{ width: "100%" }}>
            <Input placeholder="粘贴文章链接" value={link} onChange={(e) => setLink(e.target.value)} />
            <Button type="default" loading={resolving} icon={<ScanOutlined />} onClick={resolve}>
              {resolving ? <Spin size="small" /> : "识别"}
            </Button>
          </Space.Compact>
        </Space>
      </Modal>
    </div>
  );
}
